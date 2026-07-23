"""自选股智能提醒测试 —— 离线,不联网。

覆盖 :mod:`analysis.watchlist_alerts`(超跌反弹/超买/超卖/量化介入/主力出逃/
收割预警/放量异动 规则与严重度排序)与
:func:`webui.services.stock_screener_service.watchlist_alerts`(聚合编排,数据源注入)。
"""

from analysis import watchlist_alerts as wa
from webui.services import stock_screener_service as sc


def _bars(n=30, step=0.2, base=20.0, last_pct=None, last_vol_x=1.0):
    out = []
    for i in range(n):
        c = base + step * i
        vol = 1e6 * (last_vol_x if i == n - 1 else 1.0)
        out.append({"date": f"2026-06-{i + 1:02d}", "open": c - 0.02, "close": c,
                    "high": c + 0.1, "low": c - 0.1, "volume": vol,
                    "pct_chg": last_pct if i == n - 1 else 0.5})
    return out


def _rebound_bars():
    """深跌25根后反弹3根,末根 +2.5%:RSI 自超卖回升。"""
    out = []
    c = 30.0
    for i in range(28):
        c = c - 0.5 if i < 25 else c + 0.4
        out.append({"date": f"2026-06-{i + 1:02d}", "open": c - 0.02, "close": round(c, 2),
                    "high": c + 0.1, "low": c - 0.1, "volume": 1e6,
                    "pct_chg": 2.5 if i == 27 else -1.0})
    return out


def _types(alerts):
    return [a["type"] for a in alerts]


def test_tech_snapshot_requires_bars():
    assert wa.tech_snapshot([]) is None
    assert wa.tech_snapshot(_bars(n=10)) is None
    snap = wa.tech_snapshot(_bars())
    assert snap["rsi"] is not None and snap["vol_ratio"] is not None


def test_overbought_and_oversold_rules():
    up = wa.detect(bars=_bars(step=0.3, last_pct=1.0))
    assert "overbought" in _types(up)
    down = wa.detect(bars=_bars(step=-0.3, last_pct=-1.0))
    assert "oversold" in _types(down)
    assert "overbought" not in _types(down)


def test_oversold_rebound_rule():
    alerts = wa.detect(bars=_rebound_bars())
    assert "oversold_rebound" in _types(alerts)


def test_volume_surge_rule():
    alerts = wa.detect(bars=_bars(last_pct=3.0, last_vol_x=2.5))
    surge = [a for a in alerts if a["type"] == "volume_surge"]
    assert surge and "放量上攻" in surge[0]["text"]


def test_main_fleeing_and_inflow_rules():
    out = wa.detect(flow={"streak_out": 3, "streak": 0, "net_rate": -2.0, "main_net_wan": -8000})
    assert _types(out) == ["main_fleeing"]
    assert out[0]["level"] == "danger"
    out2 = wa.detect(flow={"streak_out": 0, "streak": 1, "net_rate": -6.5, "main_net_wan": -3000})
    assert _types(out2) == ["main_fleeing"]
    inflow = wa.detect(flow={"streak_out": 0, "streak": 4, "net_rate": 2.0, "main_net_wan": 5000})
    assert _types(inflow) == ["main_inflow"]


def test_quant_involved_merges_reasons():
    alerts = wa.detect(radar={"activity": 66, "direction": "拉抬", "changes_total": 9},
                       accum={"qualified": True, "accum_days": 22}, quant_seat=True)
    involved = [a for a in alerts if a["type"] == "quant_involved"]
    assert len(involved) == 1
    assert "量化雷达活跃度 66" in involved[0]["text"]
    assert "量化席位" in involved[0]["text"]
    assert "吸筹判定达标" in involved[0]["text"]


def test_smash_warning_and_severity_order():
    alerts = wa.detect(bars=_bars(step=-0.3, last_pct=-2.0),
                       flow={"streak_out": 4, "streak": 0, "net_rate": -8.0, "main_net_wan": -9000},
                       radar={"activity": 70, "direction": "砸盘", "changes_total": 18})
    types = _types(alerts)
    assert "smash_warning" in types and "main_fleeing" in types
    levels = [a["level"] for a in alerts]
    assert levels == sorted(levels, key=lambda lv: -{"danger": 3, "warn": 2, "info": 1}[lv])
    assert alerts[0]["level"] == "danger"


def test_no_data_no_alerts():
    assert wa.detect() == []


# ----------------------------- 服务聚合 -----------------------------

def _flow_rows_out(code="600000.SH"):
    rows = []
    for i, net in enumerate([-500, -800, -1200]):
        rows.append({"trade_date": f"2026-07-{14 + i}", "ts_code": code, "name": "浦发银行",
                     "net_amount": net, "net_amount_rate": -6.0, "close": 10.0, "pct_change": -2.0})
    return rows


def test_watchlist_alerts_service_aggregates(tmp_path):
    payload = sc.watchlist_alerts(
        [{"code": "600000", "name": "浦发银行"}, {"code": "BK0475", "name": "非股票"}],
        kline_fetcher=lambda code, limit: _bars(step=-0.3, last_pct=-2.0),
        flow_window_fn=lambda days: _flow_rows_out(),
        radar_rows_fn=lambda: [{"code": "600000", "trade_date": "2026-07-16", "activity": 70,
                                "direction": "砸盘", "changes_total": 18, "industry": "银行"}],
        accum_fn=lambda w: {},
        quant_seats_fn=lambda days: {})
    assert payload["ok"] is True
    assert payload["checked"] == 1  # 非法代码剔除
    item = payload["items"][0]
    assert item["code"] == "600000" and item["name"] == "浦发银行"
    types = [a["type"] for a in item["alerts"]]
    assert "main_fleeing" in types and "smash_warning" in types and "oversold" in types
    assert payload["alert_count"] == len(item["alerts"])
    assert payload["dates"]["flow"] == "2026-07-16" and payload["dates"]["radar"] == "2026-07-16"


def test_watchlist_alerts_service_empty_and_notes():
    payload = sc.watchlist_alerts([], kline_fetcher=None,
                                  flow_window_fn=lambda days: [],
                                  radar_rows_fn=lambda: [],
                                  accum_fn=lambda w: {},
                                  quant_seats_fn=lambda days: {})
    assert payload["checked"] == 0 and payload["alert_count"] == 0
    assert any("资金流" in n for n in payload["notes"])
    assert any("量化雷达" in n for n in payload["notes"])


def test_build_flow_map_streak_out():
    m = sc.build_flow_map(_flow_rows_out())
    assert m["600000"]["streak_out"] == 3 and m["600000"]["streak"] == 0
