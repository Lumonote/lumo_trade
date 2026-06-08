# tests/test_paper_trading_engine.py
"""Phase 5 撮合 + EOD:settle() 惰性补算(开盘/收盘/触价 limit)、mark_to_market()
权益曲线、run_eod() 当日复盘生成与幂等。

撮合价规则(§8.1):
  - 开盘价单 → created_date 之后首个有日K交易日的 open 成交
  - 收盘价单 → 该日 close 成交
  - 指定价买 → 当日 low<=limit 才成交,价 = min(open, limit)
  - 指定价卖 → 当日 high>=limit 才成交,价 = max(open, limit)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd
import pytest

from data_store.schema import migrate


@pytest.fixture
def paper_mod(tmp_path, monkeypatch):
    path = tmp_path / "kronos_engine.sqlite"
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


def _daily(rows):
    """rows: list of (date, open, high, low, close)."""
    return pd.DataFrame([
        {"timestamps": pd.Timestamp(d), "open": o, "high": h, "low": lo, "close": c, "volume": 0, "amount": 0}
        for (d, o, h, lo, c) in rows
    ])


# ----------------------------- 开盘 / 收盘 -----------------------------

def test_settle_fills_open_price_order_on_next_trading_day(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "open", qty=1000, name="华电国际")
    assert order["status"] == "pending"

    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),   # created day — 不参与
        ("2026-06-05", 10.2, 10.5, 10.0, 10.3),  # 次日开盘 10.2 成交
    ])
    summary = svc.settle(as_of="2026-06-05", ohlcv_loader=loader)

    assert summary["filled_count"] == 1
    filled = svc.get_order(order["id"])
    assert filled["status"] == "filled"
    assert filled["filled_price"] == pytest.approx(10.2)
    assert filled["filled_qty"] == 1000
    trades = svc.trades()
    assert trades[0]["trade_date"] == "2026-06-05"  # 成交归属补算日
    assert {p["ts_code"]: p for p in svc.positions()}["600027"]["qty"] == 1000


def test_settle_fills_close_price_order(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "close", qty=1000)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),
        ("2026-06-05", 10.2, 10.5, 10.0, 10.3),
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    assert svc.get_order(order["id"])["filled_price"] == pytest.approx(10.3)  # 次日 close


# ----------------------------- 指定价 limit -----------------------------

def test_settle_limit_buy_fills_at_limit_when_low_touches(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "limit", qty=1000, limit_price=9.5)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),
        ("2026-06-05", 9.8, 9.9, 9.3, 9.6),  # low 9.3<=9.5 → 成交价 min(open9.8, limit9.5)=9.5
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    f = svc.get_order(order["id"])
    assert f["status"] == "filled"
    assert f["filled_price"] == pytest.approx(9.5)


def test_settle_limit_buy_fills_at_open_on_gap_down(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "limit", qty=1000, limit_price=9.5)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),
        ("2026-06-05", 9.2, 9.4, 9.0, 9.3),  # 跳空低开 9.2<limit → 成交价 min(open9.2, limit9.5)=9.2
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    assert svc.get_order(order["id"])["filled_price"] == pytest.approx(9.2)


def test_settle_limit_buy_stays_pending_when_never_touches(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "limit", qty=1000, limit_price=9.5)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),
        ("2026-06-05", 10.0, 10.5, 9.7, 10.3),  # low 9.7>9.5 → 不成交
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    assert svc.get_order(order["id"])["status"] == "pending"


def test_settle_limit_sell_fills_at_limit_when_high_reaches(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")  # 先建仓
    order = svc.place_order("600027", "sell", "limit", qty=1000, limit_price=11.0)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 10.0, 10.2, 9.9, 10.1),
        ("2026-06-05", 10.8, 11.5, 10.7, 11.2),  # high 11.5>=11 → 成交价 max(open10.8, limit11.0)=11.0
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    f = svc.get_order(order["id"])
    assert f["status"] == "filled"
    assert f["filled_price"] == pytest.approx(11.0)
    assert svc.positions() == []  # 卖出清仓


def test_settle_leaves_pending_when_no_day_after_created(paper_mod):
    svc = _svc(paper_mod)
    order = svc.place_order("600027", "buy", "open", qty=1000)
    loader = lambda code: _daily([("2026-06-04", 9.9, 10.1, 9.8, 10.0)])  # 仅当日,无次日  # noqa: E731
    svc.settle(as_of="2026-06-04", ohlcv_loader=loader)
    assert svc.get_order(order["id"])["status"] == "pending"


def test_settle_rejects_open_buy_when_cash_insufficient_at_fill(paper_mod):
    svc = _svc(paper_mod)
    svc.reset(initial_cash=5000)  # 资金不足买 1000 股 @10
    order = svc.place_order("600027", "buy", "open", qty=1000)
    loader = lambda code: _daily([  # noqa: E731
        ("2026-06-04", 9.9, 10.1, 9.8, 10.0),
        ("2026-06-05", 10.2, 10.5, 10.0, 10.3),
    ])
    svc.settle(as_of="2026-06-05", ohlcv_loader=loader)
    f = svc.get_order(order["id"])
    assert f["status"] == "rejected"
    assert "资金不足" in (f["note"] or "")


# ----------------------------- 盯市 / 权益曲线 -----------------------------

def test_mark_to_market_writes_equity_curve_and_daily_pnl(paper_mod):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}})
    svc.place_order("600027", "buy", "market", qty=1000)  # 成本 10005.1,现金 989994.9

    svc.mark_to_market("2026-06-04", close_provider=lambda code: 11.0)  # 收盘盯市 11

    curve = svc.equity_curve()
    assert len(curve) == 1
    row = curve[0]
    assert row["trade_date"] == "2026-06-04"
    assert row["position_value"] == pytest.approx(11000.0)
    assert row["total_equity"] == pytest.approx(989994.9 + 11000.0)
    # 首日无前值,基准 = initial 100W;daily_pnl = 浮盈(净买入费) = 11000-10005.1
    assert row["daily_pnl"] == pytest.approx(11000.0 - 10005.1)
    # 权益曲线喂入回撤统计
    assert "max_drawdown" in svc.stats()


# ----------------------------- EOD 复盘 -----------------------------

def test_run_eod_generates_review_markdown_and_is_idempotent(paper_mod, tmp_path):
    svc = _svc(paper_mod, quotes={"600027": {"price": 10.0}}, now=datetime(2026, 6, 4, 15, 30, 0))
    svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")  # 当日有成交

    out = svc.run_eod(
        "2026-06-04",
        ohlcv_loader=lambda c: _daily([("2026-06-04", 9.9, 10.1, 9.8, 10.0)]),
        close_provider=lambda c: 10.0,
        results_dir=str(tmp_path),
        market_env_text="🟡 中性 | 沪深300 近5日 -1.57%",
    )

    assert out["generated"] is True
    review = tmp_path / "paper_review_2026-06-04.md"
    assert review.exists()
    content = review.read_text(encoding="utf-8")
    assert "模拟盘" in content and "华电国际" in content and "中性" in content

    # 幂等:复盘文件已存在 → 再次运行不重生成
    out2 = svc.run_eod(
        "2026-06-04",
        ohlcv_loader=lambda c: _daily([]),
        close_provider=lambda c: 10.0,
        results_dir=str(tmp_path),
    )
    assert out2["generated"] is False


def test_run_eod_skips_review_without_activity(paper_mod, tmp_path):
    svc = _svc(paper_mod, now=datetime(2026, 6, 4, 15, 30, 0))  # 无持仓无成交
    out = svc.run_eod("2026-06-04", ohlcv_loader=lambda c: _daily([]),
                      close_provider=lambda c: None, results_dir=str(tmp_path))
    assert out["generated"] is False
    assert not (tmp_path / "paper_review_2026-06-04.md").exists()


def test_marked_positions_price_at_close_not_live_quote(paper_mod):
    # 盘中手动结算时,实时报价≠收盘价;复盘持仓必须用收盘价基准,与权益一致
    svc = _svc(paper_mod, quotes={"600027": {"price": 8.0}})
    svc.place_order("600027", "buy", "market", qty=1000)  # 市价单按报价 8.0 成交 → avg≈8.00508
    marked = svc.marked_positions("2026-06-04", close_provider=lambda c: 11.0)  # 收盘价 11.0
    assert len(marked) == 1
    p = marked[0]
    assert p["close"] == pytest.approx(11.0)             # 用收盘价,非实时报价 8.0
    assert p["market_value"] == pytest.approx(11000.0)
    assert p["float_pnl"] == pytest.approx(11000.0 - 8005.08)  # 收盘价市值 - 含费成本


def test_run_eod_review_holdings_consistent_with_equity(paper_mod, tmp_path):
    # 复盘的持仓盯市与账户概览必须同源(收盘价),即便实时报价不同
    svc = _svc(paper_mod, quotes={"600027": {"price": 8.0}}, now=datetime(2026, 6, 4, 15, 30, 0))
    svc.place_order("600027", "buy", "market", qty=1000, name="华电国际")  # 成交价 8.0
    svc.run_eod("2026-06-04", ohlcv_loader=lambda c: _daily([("2026-06-04", 9.9, 11.2, 9.8, 11.0)]),
                close_provider=lambda c: 11.0, results_dir=str(tmp_path))
    content = (tmp_path / "paper_review_2026-06-04.md").read_text(encoding="utf-8")
    assert "收盘价" in content              # 持仓表表头用收盘价口径
    assert "11.000" in content             # 收盘价 11.0 进入持仓表
    assert "+2,994.92" in content          # 收盘价口径浮盈(若误用报价 8.0 则为 -5.08)


