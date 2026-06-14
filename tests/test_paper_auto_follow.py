# tests/test_paper_auto_follow.py
"""PaperAutoFollowService(模拟盘自动跟单)：开关关闭不下单 / 达档下单(次日开盘价) /
幂等去重(同一报告日期+股票) / 持有到期自动平仓。

参照 tests/test_paper_trading_service.py 的方式：临时 SQLite + migrate +
monkeypatch get_conn，OHLCV 用注入的 fake loader，全程离线。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd
import pytest

from data_store.schema import migrate

from webui.services.paper_auto_follow_service import PaperAutoFollowService


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


def _paper_svc(mod, quotes=None, now=datetime(2026, 6, 4, 16, 0, 0)):
    return mod.PaperTradingService(
        quote_provider=(lambda codes: dict(quotes or {})),
        now_fn=lambda: now,
    )


def _report(items):
    return {
        "file": "opportunity_top10_20260604_180000.md",
        "items": items,
    }


def _item(code, score, name="测试股"):
    return {"code": code, "name": name, "score": score, "rating": "A"}


def _daily_df(days, price=10.0):
    """构造日K：每个交易日 open=high=low=close=price。"""
    return pd.DataFrame({
        "timestamps": [pd.Timestamp(d) for d in days],
        "open": [price] * len(days),
        "high": [price] * len(days),
        "low": [price] * len(days),
        "close": [price] * len(days),
        "volume": [1000] * len(days),
        "amount": [price * 1000] * len(days),
    })


def _auto_svc(tmp_path, paper, config, events=None, now=datetime(2026, 6, 4, 18, 0, 0)):
    return PaperAutoFollowService(
        paper,
        lambda: dict(config),
        tmp_path / "auto_follow.json",
        events=events,
        now_fn=lambda: now,
    )


# ----------------------------- 1. 开关关闭不下单 -----------------------------

def test_disabled_places_no_orders(paper_mod, tmp_path):
    paper = _paper_svc(paper_mod)
    svc = _auto_svc(tmp_path, paper, {"enabled": False, "min_score": 78})

    result = svc.follow_report(_report([_item("600027", 90.0)]))

    assert result["enabled"] is False
    assert result["placed"] == 0
    assert paper.orders() == []


# ----------------------------- 2. 达档下单(次日开盘价) -----------------------------

def test_enabled_places_open_orders_for_qualified_stocks(paper_mod, tmp_path):
    paper = _paper_svc(paper_mod)
    cfg = {"enabled": True, "min_score": 78, "per_stock_amount": 20000, "hold_days": 5}
    svc = _auto_svc(tmp_path, paper, cfg)

    result = svc.follow_report(_report([
        _item("600027", 82.0, "达档A"),
        _item("000001", 70.0, "不达档B"),
    ]))

    assert result["enabled"] is True
    assert result["placed"] == 1
    pending = paper.orders(status="pending")
    assert len(pending) == 1
    order = pending[0]
    assert order["ts_code"] == "600027"
    assert order["side"] == "buy"
    assert order["price_type"] == "open"          # 次日开盘价买入
    assert order["amount_budget"] == pytest.approx(20000)
    # 台账只记录达档股票
    entries = svc.entries()
    assert len(entries) == 1
    assert entries[0]["code"] == "600027" and entries[0]["status"] == "open"


# ----------------------------- 3. 幂等去重 -----------------------------

def test_same_report_same_stock_is_idempotent(paper_mod, tmp_path):
    paper = _paper_svc(paper_mod)
    cfg = {"enabled": True, "min_score": 78, "per_stock_amount": 20000, "hold_days": 5}
    svc = _auto_svc(tmp_path, paper, cfg)
    report = _report([_item("600027", 82.0)])

    first = svc.follow_report(report)
    second = svc.follow_report(report)

    assert first["placed"] == 1
    assert second["placed"] == 0
    assert second["skipped"] == 1
    assert len(paper.orders(status="pending")) == 1   # 不重复下单


# ----------------------------- 4. 持有到期平仓 -----------------------------

def test_expiry_places_sell_and_closes_position(paper_mod, tmp_path):
    # 可推进的时钟：模拟跨多个交易日运行(生产中 now_fn=datetime.now)
    clock = {"now": datetime(2026, 6, 4, 18, 0, 0)}
    paper = paper_mod.PaperTradingService(
        quote_provider=lambda codes: {},
        now_fn=lambda: clock["now"],
    )
    cfg = {"enabled": True, "min_score": 78, "per_stock_amount": 20000, "hold_days": 2}
    svc = PaperAutoFollowService(
        paper, lambda: dict(cfg), tmp_path / "auto_follow.json",
        now_fn=lambda: clock["now"],
    )

    days = ["2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09", "2026-06-10"]
    loader = lambda code: _daily_df(days, price=10.0)  # noqa: E731

    # D0(06-04) 报告生成 → 挂次日开盘买单
    assert svc.follow_report(_report([_item("600027", 82.0)]))["placed"] == 1

    # D1(06-05) EOD：买单按开盘价成交
    clock["now"] = datetime(2026, 6, 5, 15, 35, 0)
    paper.run_eod("2026-06-05", ohlcv_loader=loader, write_review=False)
    summary = svc.process_eod("2026-06-05", ohlcv_loader=loader)
    entry = svc.entries()[0]
    assert entry["status"] == "open"
    assert entry["buy_fill_date"] == "2026-06-05"
    assert entry["filled_qty"] == 2000              # 20000 // (10*100) * 100
    assert summary["exits_placed"] == 0

    # D2(06-08)：持有1个交易日，未到期
    clock["now"] = datetime(2026, 6, 8, 15, 35, 0)
    paper.run_eod("2026-06-08", ohlcv_loader=loader, write_review=False)
    svc.process_eod("2026-06-08", ohlcv_loader=loader)
    assert svc.entries()[0]["status"] == "open"

    # D3(06-09)：持有2个交易日 = hold_days → 挂次日开盘卖单
    clock["now"] = datetime(2026, 6, 9, 15, 35, 0)
    paper.run_eod("2026-06-09", ohlcv_loader=loader, write_review=False)
    summary = svc.process_eod("2026-06-09", ohlcv_loader=loader)
    assert summary["exits_placed"] == 1
    assert svc.entries()[0]["status"] == "closing"

    # D4(06-10)：卖单按开盘价成交 → 持仓清零、条目收尾
    clock["now"] = datetime(2026, 6, 10, 15, 35, 0)
    paper.run_eod("2026-06-10", ohlcv_loader=loader, write_review=False)
    summary = svc.process_eod("2026-06-10", ohlcv_loader=loader)
    assert summary["closed"] == 1
    entry = svc.entries()[0]
    assert entry["status"] == "closed"
    assert paper.positions() == []                  # 已全部平仓
    sells = [t for t in paper.trades() if t["side"] == "sell"]
    assert len(sells) == 1 and sells[0]["qty"] == 2000
    assert sells[0]["traded_at"].startswith("2026-06-10")  # 到期次日开盘成交
