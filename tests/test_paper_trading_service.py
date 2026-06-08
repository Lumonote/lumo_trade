# tests/test_paper_trading_service.py
"""PaperTradingService:账户 / 下单 / 即时成交 / 含费摊薄 / 卖出已实现盈亏 /
资金不足拒单 / 按金额折股 / pending+撤单 / 胜率统计 / 账户摘要 / 重置。

费用模型(§9,默认值):佣金万2.5最低5(买+卖)、印花税0.05%(仅卖)、过户费万0.1(买+卖)。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from data_store.schema import migrate


@pytest.fixture
def paper_mod(tmp_path, monkeypatch):
    path = tmp_path / "kronos_paper.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)

    getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", getter)
    import webui.services.paper_trading_service as mod
    monkeypatch.setattr(mod, "get_conn", getter)
    yield mod
    c.close()


def _svc(mod, quotes=None, now=datetime(2026, 6, 4, 10, 0, 0)):
    return mod.PaperTradingService(
        quote_provider=(lambda codes: dict(quotes or {})),
        now_fn=lambda: now,
    )


# ----------------------------- 账户 -----------------------------

def test_ensure_account_creates_singleton_with_default_cash(paper_mod):
    svc = _svc(paper_mod)
    acc = svc.ensure_account()
    assert acc["initial_cash"] == pytest.approx(1_000_000)
    assert acc["cash"] == pytest.approx(1_000_000)
    # 幂等:再次调用不新建第二个账户
    again = svc.ensure_account()
    assert again["id"] == 1


# ----------------------------- 即时买入 -----------------------------

def test_market_buy_deducts_cash_with_fees_and_sets_weighted_avg_cost(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    order = svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")

    assert order["status"] == "filled"
    # gross=10000;佣金=max(2.5,5)=5;过户费=0.1;fee=5.1;总成本=10005.1
    assert order["fee"] == pytest.approx(5.1)
    assert order["filled_price"] == pytest.approx(10.0)
    assert order["filled_qty"] == 1000

    acc = svc.account_summary()
    assert acc["cash"] == pytest.approx(1_000_000 - 10005.1)

    pos = {p["ts_code"]: p for p in svc.positions()}["600027"]
    assert pos["qty"] == 1000
    assert pos["avg_cost"] == pytest.approx(10.0051)  # 含费摊薄 10005.1/1000


def test_market_buy_rejected_when_cash_insufficient(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    order = svc.place_order("600027", "buy", "market", qty=200000)  # gross 200万 > 100万

    assert order["status"] == "rejected"
    assert "资金不足" in (order["note"] or "")
    assert svc.account_summary()["cash"] == pytest.approx(1_000_000)  # 资金不动
    assert svc.positions() == []


def test_market_buy_by_amount_rounds_down_to_lots(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    # 金额 23800 / (10*100) = 23.8 → 取整 2300 股
    order = svc.place_order("600027", "buy", "market", amount=23800)

    assert order["status"] == "filled"
    assert order["filled_qty"] == 2300


def test_market_buy_by_amount_below_one_lot_is_rejected(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    order = svc.place_order("600027", "buy", "market", amount=500)  # 不足一手(1000元)

    assert order["status"] == "rejected"
    assert order["filled_qty"] in (0, None)
    assert svc.account_summary()["cash"] == pytest.approx(1_000_000)


def test_import_historical_buy_creates_filled_trade_and_position(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 12.0, "name": "华电国际"}})

    order = svc.import_historical_buy("600027", price=8.5, qty=1000, trade_date="2026-05-20")

    assert order["status"] == "filled"
    assert order["created_date"] == "2026-05-20"
    assert order["filled_price"] == pytest.approx(8.5)
    assert order["filled_qty"] == 1000
    # gross=8500;佣金=max(2.125,5)=5;过户费=0.085;fee=5.085;总成本=8505.085
    assert order["fee"] == pytest.approx(5.085)

    acc = svc.account_summary()
    assert acc["cash"] == pytest.approx(1_000_000 - 8505.085)

    pos = {p["ts_code"]: p for p in svc.positions()}["600027"]
    assert pos["name"] == "华电国际"
    assert pos["qty"] == 1000
    assert pos["avg_cost"] == pytest.approx(8.505085)

    trade = svc.trades()[0]
    assert trade["trade_date"] == "2026-05-20"
    assert trade["traded_at"] == "2026-05-20 09:30:00"
    assert trade["name"] == "华电国际"


# ----------------------------- 即时卖出 -----------------------------

def test_market_sell_realizes_pnl_and_releases_position(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")  # avg_cost=10.0051

    svc._quote_provider = lambda codes: {"600027": {"price": 11.0}}
    sell = svc.place_order("600027", "sell", "market", qty=1000)

    assert sell["status"] == "filled"
    # gross=11000;佣金=max(2.75,5)=5;印花=5.5;过户=0.11;fee=10.61;净额=10989.39
    assert sell["fee"] == pytest.approx(10.61)
    # realized = 净额 - avg_cost*qty = 10989.39 - 10005.1 = 984.29
    assert sell["realized_pnl"] == pytest.approx(984.29)
    assert svc.positions() == []  # 清仓后删除持仓

    acc = svc.account_summary()
    # 现金 = 100万 - 10005.1(买) + 10989.39(卖)
    assert acc["cash"] == pytest.approx(1_000_000 - 10005.1 + 10989.39)
    assert acc["realized_pnl"] == pytest.approx(984.29)


def test_market_sell_rejected_when_position_insufficient(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 11.0}})

    sell = svc.place_order("600027", "sell", "market", qty=1000)  # 无持仓

    assert sell["status"] == "rejected"
    assert "持仓不足" in (sell["note"] or "")


def test_partial_sell_keeps_remaining_position_at_same_avg_cost(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=2000, name="华电国际")

    svc._quote_provider = lambda codes: {"600027": {"price": 12.0}}
    svc.place_order("600027", "sell", "market", qty=500)

    pos = {p["ts_code"]: p for p in svc.positions()}["600027"]
    assert pos["qty"] == 1500
    # 买 2000 股:佣金地板5 + 过户0.2 = 5.2,总成本 20005.2 → 均价 10.0026;卖出不改变剩余均价
    assert pos["avg_cost"] == pytest.approx(10.0026)


# ----------------------------- 委托(pending)+ 撤单 -----------------------------

def test_open_price_order_is_pending_not_filled(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    order = svc.place_order("600027", "buy", "open", qty=1000, name="华电国际")

    assert order["status"] == "pending"
    assert order["filled_price"] is None
    assert svc.account_summary()["cash"] == pytest.approx(1_000_000)  # pending 不扣资金
    assert [o["id"] for o in svc.orders(status="pending")] == [order["id"]]


def test_limit_order_requires_limit_price(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})

    order = svc.place_order("600027", "buy", "limit", qty=1000)  # 缺 limit_price

    assert order["status"] == "rejected"
    assert "指定价" in (order["note"] or "")


def test_cancel_pending_order(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    order = svc.place_order("600027", "buy", "limit", qty=1000, limit_price=9.5)
    assert order["status"] == "pending"

    cancelled = svc.cancel_order(order["id"])

    assert cancelled["status"] == "cancelled"
    assert svc.orders(status="pending") == []


# ----------------------------- 统计 / 摘要 -----------------------------

def test_stats_win_rate_over_sells(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}, "000001": {"price": 10.0}})
    # 两笔买入
    svc.place_order("600027", "buy", "market", qty=1000)
    svc.place_order("000001", "buy", "market", qty=1000)
    # 一笔盈利卖出
    svc._quote_provider = lambda codes: {"600027": {"price": 20.0}}
    svc.place_order("600027", "sell", "market", qty=1000)
    # 一笔亏损卖出
    svc._quote_provider = lambda codes: {"000001": {"price": 5.0}}
    svc.place_order("000001", "sell", "market", qty=1000)

    stats = svc.stats()
    assert stats["sell_count"] == 2
    assert stats["win_count"] == 1
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["max_win"] > 0
    assert stats["max_loss"] < 0


def test_account_summary_marks_position_to_market(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")

    # 现价涨到 12 → 持仓市值 12000,浮盈 = (12 - 10.0051)*1000
    svc._quote_provider = lambda codes: {"600027": {"price": 12.0}}
    acc = svc.account_summary()

    assert acc["position_value"] == pytest.approx(12000.0)
    assert acc["float_pnl"] == pytest.approx((12.0 - 10.0051) * 1000)
    assert acc["total_equity"] == pytest.approx(acc["cash"] + 12000.0)
    assert acc["total_return"] == pytest.approx((acc["total_equity"] - 1_000_000) / 1_000_000)


def test_reset_clears_ledger_and_sets_new_initial_cash(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=1000)

    svc.reset(initial_cash=500_000)

    acc = svc.account_summary()
    assert acc["initial_cash"] == pytest.approx(500_000)
    assert acc["cash"] == pytest.approx(500_000)
    assert svc.positions() == []
    assert svc.orders() == []
    assert svc.trades() == []
