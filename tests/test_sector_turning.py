"""板块拐点判据(纯函数)。每条判据的 fired / watch / 不成立三态都要覆盖。

⚠️ 判据阈值最终由 scripts/validate_turning_rules.py 的历史校验决定是否上线,
本测试只锁定「判据实现符合定义」,不代表判据有效。
"""
import pytest

from analysis import sector_turning as st


def _series(n=30, **overrides):
    """生成 n 天的中性序列,再用 overrides 覆盖尾部若干天的指定字段。

    overrides 形如 net_amount=[...],列表从**末尾**对齐(最后一个元素是今天)。
    """
    base = [{
        "trade_date": f"2026-07-{(i % 28) + 1:02d}",
        "sector": "测试板块", "sector_type": "行业", "member_count": 20,
        "net_amount": -10.0, "net_rate_median": -0.1, "pct_chg_mean": 0.0,
        "breadth": 0.5, "amount_median": 1000.0, "excess_vs_market": -0.1,
        "seat_count": 0, "provisional": 0,
    } for i in range(n)]
    # 让 trade_date 严格递增,避免排序歧义
    for i, row in enumerate(base):
        row["trade_date"] = f"2026-{6 + i // 28:02d}-{(i % 28) + 1:02d}"
    for field, values in overrides.items():
        for offset, value in enumerate(reversed(values)):
            base[-1 - offset][field] = value
    return base


def _rule(results, rule_id):
    for r in results:
        if r["rule"] == rule_id:
            return r
    return None


# ---------------------------------------------------------------- T1
# 基线每天 -10。20 日窗口:今日累计 = -10*17 + a + b + c;昨日累计 = -10*18 + a + b。
# 取 (a,b,c) = (50,50,200):今日 +130 > 0、昨日 -80 <= 0、连续 3 日净流入 → fired。
FIRED_T1 = [50.0, 50.0, 200.0]


def test_t1_fires_when_cum20_flips_positive_with_3day_streak():
    assert _rule(st.evaluate_rules(_series(net_amount=FIRED_T1)), "T1")["state"] == "fired"


def test_t1_watch_when_streak_present_but_cum20_still_negative():
    series = _series(net_amount=[10.0, 10.0, 10.0])  # 累计仍为负
    assert _rule(st.evaluate_rules(series), "T1")["state"] == "watch"


def test_t1_watch_when_flip_happens_without_full_streak():
    """累计刚转正但连续流入不足 3 日 → 只到临界,不算已触发。"""
    series = _series(net_amount=[100.0, -5.0, 100.0])
    hit = _rule(st.evaluate_rules(series), "T1")
    assert hit["state"] == "watch"
    assert "还差" in hit["gap"]


def test_t1_absent_when_no_inflow_at_all():
    assert _rule(st.evaluate_rules(_series()), "T1") is None


def test_t1_evidence_carries_cum20():
    ev = _rule(st.evaluate_rules(_series(net_amount=FIRED_T1)), "T1")["evidence"]
    assert ev["cum20"] > 0
    assert ev["cum20_prev"] <= 0
    assert ev["streak"] == 3


# ---------------------------------------------------------------- T2
def test_t2_fires_on_divergence_then_volume_breakout():
    series = _series(
        pct_chg_mean=[-1.0] * 10 + [2.0],
        net_amount=[50.0] * 10 + [50.0],
        amount_median=[1000.0] * 10 + [2000.0],
    )
    assert _rule(st.evaluate_rules(series), "T2")["state"] == "fired"


def test_t2_watch_when_divergence_without_breakout():
    series = _series(
        pct_chg_mean=[-1.0] * 10 + [0.1],
        net_amount=[50.0] * 10 + [50.0],
        amount_median=[1000.0] * 10 + [1000.0],
    )
    assert _rule(st.evaluate_rules(series), "T2")["state"] == "watch"


def test_t2_absent_when_price_rose_during_window():
    series = _series(
        pct_chg_mean=[1.0] * 10 + [2.0],
        net_amount=[50.0] * 10 + [50.0],
        amount_median=[1000.0] * 10 + [2000.0],
    )
    assert _rule(st.evaluate_rules(series), "T2") is None


# ---------------------------------------------------------------- T3
def test_t3_fires_on_two_day_breadth_breakout_after_narrow_market():
    series = _series(breadth=[0.3, 0.3, 0.3, 0.3, 0.3, 0.7, 0.7])
    assert _rule(st.evaluate_rules(series), "T3")["state"] == "fired"


def test_t3_watch_on_first_day_only():
    series = _series(breadth=[0.3, 0.3, 0.3, 0.3, 0.3, 0.5, 0.7])
    assert _rule(st.evaluate_rules(series), "T3")["state"] == "watch"


def test_t3_absent_when_market_was_already_broad():
    series = _series(breadth=[0.65, 0.65, 0.65, 0.65, 0.65, 0.7, 0.7])
    assert _rule(st.evaluate_rules(series), "T3") is None


# ---------------------------------------------------------------- T4
def test_t4_fires_when_excess_cum20_flips_positive():
    # 基线 -0.1/天:今日累计 = -0.1*19 + 5.0 = +3.1;昨日累计 = -2.0
    series = _series(excess_vs_market=[5.0])
    assert _rule(st.evaluate_rules(series), "T4")["state"] == "fired"


def test_t4_watch_when_excess_close_to_zero():
    series = _series(excess_vs_market=[1.5])  # 累计约 -0.4,落在 (-1.0, 0]
    assert _rule(st.evaluate_rules(series), "T4")["state"] == "watch"


# ---------------------------------------------------------------- T5
def test_t5_fires_on_seat_surge():
    series = _series(seat_count=[1] * 20 + [6])
    assert _rule(st.evaluate_rules(series), "T5")["state"] == "fired"


def test_t5_absent_without_surge():
    series = _series(seat_count=[1] * 20 + [1])
    assert _rule(st.evaluate_rules(series), "T5") is None


# ---------------------------------------------------------------- 边界
def test_evaluate_rules_short_series_returns_empty():
    assert st.evaluate_rules(_series(3)) == []


def test_evaluate_rules_empty_series_returns_empty():
    assert st.evaluate_rules([]) == []


def test_evaluate_rules_tolerates_none_fields():
    series = _series(net_amount=[None, None, None], breadth=[None], excess_vs_market=[None])
    assert isinstance(st.evaluate_rules(series), list)  # 不抛


def test_evaluate_rules_sorts_series_by_date():
    """入参乱序也要给出与升序一致的结论。"""
    series = _series(net_amount=FIRED_T1)
    shuffled = list(reversed(series))
    assert _rule(st.evaluate_rules(shuffled), "T1")["state"] == "fired"


# ---------------------------------------------------------------- 评分与全市场
def test_turning_score_zero_without_fired_rules():
    assert st.turning_score([]) == 0.0


def test_turning_score_increases_with_more_fired_rules():
    one = st.turning_score([{"rule": "T1", "state": "fired"}])
    two = st.turning_score([{"rule": "T1", "state": "fired"},
                            {"rule": "T3", "state": "fired"}])
    assert 0 < one < two <= 100


def test_turning_score_watch_counts_less_than_fired():
    fired = st.turning_score([{"rule": "T1", "state": "fired"}])
    watch = st.turning_score([{"rule": "T1", "state": "watch"}])
    assert watch < fired


def test_turning_score_respects_weights():
    default = st.turning_score([{"rule": "T1", "state": "fired"}])
    heavy = st.turning_score([{"rule": "T1", "state": "fired"}], weights={"T1": 2.0})
    assert heavy > default


def test_evaluate_universe_splits_fired_and_watch():
    fired_series = _series(net_amount=FIRED_T1)
    watch_series = _series(net_amount=[10.0, 10.0, 10.0])
    out = st.evaluate_universe({
        ("涨板块", "行业"): fired_series,
        ("等板块", "概念"): watch_series,
    })
    assert [x["sector"] for x in out["fired"]] == ["涨板块"]
    assert [x["sector"] for x in out["watch"]] == ["等板块"]


def test_evaluate_universe_enabled_filters_rules():
    """校验没通过的判据可以整条关掉。"""
    series = _series(net_amount=FIRED_T1)
    out = st.evaluate_universe({("测试", "行业"): series}, enabled=("T3",))
    assert out["fired"] == [] and out["watch"] == []


def test_evaluate_universe_sorts_fired_by_score_desc():
    strong = _series(net_amount=FIRED_T1,
                     breadth=[0.3, 0.3, 0.3, 0.3, 0.3, 0.7, 0.7])
    weak = _series(net_amount=FIRED_T1)
    out = st.evaluate_universe({("强", "行业"): strong, ("弱", "行业"): weak})
    assert [x["sector"] for x in out["fired"]] == ["强", "弱"]


def test_turning_score_weights_define_full_denominator():
    """只上线一条判据时,满命中应接近满分(而非按 5 条判据摊薄到 20 分)。"""
    only_t5 = st.turning_score([{"rule": "T5", "state": "fired"}], weights={"T5": 1.0})
    assert only_t5 == pytest.approx(100.0)
    watch_t5 = st.turning_score([{"rule": "T5", "state": "watch"}], weights={"T5": 1.0})
    assert watch_t5 == pytest.approx(40.0)


def test_turning_score_ignores_rules_outside_weight_table():
    """未上线的判据即使命中也不计分。"""
    assert st.turning_score([{"rule": "T1", "state": "fired"}], weights={"T5": 1.0}) == 0.0
