# -*- coding: utf-8 -*-
"""outcome_markers 纯函数单测(TDD 先行)。

背景(2026-07-29 入选后表现回溯): 合并 1896 条「入选+10日表现」样本
(2025-11-19~2026-07-28, 剔除 degraded)后发现——总分对尾部完全没有区分度
(TOP50 中位 67.9 vs BOT50 中位 67.1, score>=85 组暴涨率反而最低 2.4%)。
真正区分暴涨/暴跌的是另一组正交特征, 且两个时段同向可复现。
本模块把这组特征固化成「标记 + 描述」, 只做提示不改分。
"""
import pytest

from analysis.outcome_markers import (
    MARKERS_VERSION,
    MARKER_SPECS,
    batch_crowding,
    constitution,
    describe_markers,
    evaluate_markers,
    extract_factors,
    marker_payload,
)


def _keys(hits):
    return {h.key for h in hits}


# ---------------------------------------------------------------- 注册表自洽
class TestRegistry:
    def test_version_present(self):
        assert isinstance(MARKERS_VERSION, str) and MARKERS_VERSION

    def test_every_spec_has_evidence_fields(self):
        for key, spec in MARKER_SPECS.items():
            assert spec["label"], key
            assert spec["kind"] in ("positive", "negative"), key
            assert spec["tail"] in ("upside", "downside"), key
            assert spec["weight"] in (0, 1), key
            # 标定依据必须齐全(留档自证, 不进对用户的描述)
            for field in ("sample_n", "avg_return_10d", "crash_rate", "evidence"):
                assert field in spec, f"{key} 缺 {field}"
            # 给用户看的两句: 现在是什么状态 + 该怎么办
            for field in ("summary", "action"):
                assert spec.get(field), f"{key} 缺 {field}"

    def test_user_facing_copy_is_compliant(self):
        """对用户的文案不得出现涨跌预判类字眼, 也不得复述回测数字。"""
        banned = ("暴涨", "暴跌", "必涨", "翻倍", "保证", "稳赚",
                  "历史同类", "历史同档", "10日均值", "胜率")
        texts = []
        for spec in MARKER_SPECS.values():
            texts += [spec["summary"], spec["action"]]
        from analysis.outcome_markers import CONSTITUTION_TIERS
        for tier in CONSTITUTION_TIERS:
            texts += [tier["grade"], tier["summary"], tier["advice"]]
        for text in texts:
            for word in banned:
                assert word not in text, f"文案「{text}」含违规/回测字眼「{word}」"

    def test_net_weight_markers_match_validated_set(self):
        """计入净分层的标记必须正好是回测验证过的 2 正 5 负。"""
        pos = {k for k, s in MARKER_SPECS.items()
               if s["kind"] == "positive" and s["weight"] == 1}
        neg = {k for k, s in MARKER_SPECS.items()
               if s["kind"] == "negative" and s["weight"] == 1}
        assert pos == {"breakout_gene", "clean_sell"}
        assert neg == {"sector_overheat", "chase_exhaust", "overbought",
                       "tech_weak", "sell_pressure"}

    def test_composite_alarms_do_not_double_count(self):
        """复合警报由已计分的分量组成, 必须 weight=0 避免重复计分。"""
        assert MARKER_SPECS["top_trap"]["weight"] == 0
        assert MARKER_SPECS["sentiment_peak"]["weight"] == 0


# ---------------------------------------------------------------- 正向标记
class TestPositiveMarkers:
    def test_breakout_gene_needs_strong_tech_and_cold_sector(self):
        assert "breakout_gene" in _keys(
            evaluate_markers({"tech_score": 65, "sector_score": 48}))

    def test_breakout_gene_not_fired_when_sector_hot(self):
        assert "breakout_gene" not in _keys(
            evaluate_markers({"tech_score": 65, "sector_score": 80}))

    def test_breakout_gene_not_fired_when_tech_weak(self):
        assert "breakout_gene" not in _keys(
            evaluate_markers({"tech_score": 50, "sector_score": 40}))

    def test_breakout_gene_upgraded_by_golden_rsi(self):
        """RSI 55-70 叠加时升级为「强」, 但仍是同一个标记(不重复计分)。"""
        hits = evaluate_markers({"tech_score": 65, "sector_score": 48, "rsi": 62})
        hit = next(h for h in hits if h.key == "breakout_gene")
        assert hit.strong is True
        assert "强" in hit.label

    def test_breakout_gene_not_strong_outside_rsi_band(self):
        hits = evaluate_markers({"tech_score": 65, "sector_score": 48, "rsi": 78})
        hit = next(h for h in hits if h.key == "breakout_gene")
        assert hit.strong is False

    def test_clean_sell_requires_exactly_zero(self):
        assert "clean_sell" in _keys(evaluate_markers({"sell_signals": 0}))
        assert "clean_sell" not in _keys(evaluate_markers({"sell_signals": 1}))


# ---------------------------------------------------------------- 负向标记
class TestNegativeMarkers:
    @pytest.mark.parametrize("factors,key", [
        ({"sector_score": 96}, "sector_overheat"),
        ({"chase_risk": 85}, "chase_exhaust"),
        ({"rsi": 76}, "overbought"),
        ({"tech_score": 40}, "tech_weak"),
        ({"sell_signals": 5}, "sell_pressure"),
    ])
    def test_negative_marker_fires_at_threshold(self, factors, key):
        assert key in _keys(evaluate_markers(factors))

    @pytest.mark.parametrize("factors,key", [
        ({"sector_score": 90}, "sector_overheat"),
        ({"chase_risk": 70}, "chase_exhaust"),
        ({"rsi": 70}, "overbought"),
        ({"tech_score": 50}, "tech_weak"),
        ({"sell_signals": 3}, "sell_pressure"),
    ])
    def test_negative_marker_silent_below_threshold(self, factors, key):
        assert key not in _keys(evaluate_markers(factors))

    def test_top_trap_needs_all_three_legs(self):
        full = {"tech_score": 40, "chase_risk": 85, "change_5d": 18}
        assert "top_trap" in _keys(evaluate_markers(full))
        for drop in ("tech_score", "chase_risk", "change_5d"):
            partial = dict(full)
            partial.pop(drop)
            assert "top_trap" not in _keys(evaluate_markers(partial))

    def test_sentiment_peak_needs_hot_sector_and_high_rsi(self):
        assert "sentiment_peak" in _keys(
            evaluate_markers({"sector_score": 100, "rsi": 72}))
        assert "sentiment_peak" not in _keys(
            evaluate_markers({"sector_score": 100, "rsi": 60}))


# ---------------------------------------------------------------- 缺失因子
class TestMissingFactors:
    def test_empty_factors_yield_no_hits(self):
        assert evaluate_markers({}) == []

    def test_none_and_nan_never_fire(self):
        assert evaluate_markers({"rsi": None, "tech_score": float("nan"),
                                 "sector_score": None, "sell_signals": None}) == []

    def test_non_numeric_is_ignored(self):
        assert evaluate_markers({"rsi": "高", "tech_score": ""}) == []

    def test_partial_factors_still_fire_what_is_known(self):
        """技术分缺失不应阻断板块过热的判定。"""
        assert "sector_overheat" in _keys(evaluate_markers({"sector_score": 98}))


# ---------------------------------------------------------------- 体质分层
class TestConstitution:
    def test_pure_positive_is_top_grade(self):
        hits = evaluate_markers({"tech_score": 70, "sector_score": 45,
                                 "sell_signals": 0})
        c = constitution(hits)
        assert c["net"] == 2
        assert c["grade"] == "爆发体质"

    def test_pure_negative_is_high_risk(self):
        hits = evaluate_markers({"sector_score": 100, "chase_risk": 90,
                                 "rsi": 80, "tech_score": 30, "sell_signals": 5})
        c = constitution(hits)
        assert c["net"] == -5
        assert c["grade"] == "高危体质"

    def test_no_hits_is_neutral(self):
        c = constitution([])
        assert c["net"] == 0
        assert c["grade"] == "中性体质"

    def test_composite_alarm_does_not_shift_net(self):
        """顶部陷阱由 tech_weak + chase_exhaust 构成, net 只应记 -2。"""
        hits = evaluate_markers({"tech_score": 40, "chase_risk": 85,
                                 "change_5d": 18})
        assert "top_trap" in _keys(hits)
        assert constitution(hits)["net"] == -2

    def test_grade_is_monotonic_in_net(self):
        order = ["高危体质", "风险体质", "偏弱体质", "中性体质",
                 "偏强体质", "爆发体质"]
        grades = [constitution([], net_override=n)["grade"] for n in range(-3, 3)]
        assert grades == order

    def test_constitution_carries_backtest_stats(self):
        c = constitution([], net_override=2)
        assert c["sample_n"] > 0
        assert c["avg_return_10d"] == pytest.approx(2.63, abs=0.01)


# ---------------------------------------------------------------- 文本描述
class TestDescribe:
    def test_describe_mentions_each_hit_label(self):
        hits = evaluate_markers({"tech_score": 70, "sector_score": 45,
                                 "sell_signals": 0})
        text = describe_markers(hits)
        assert "爆发基因" in text and "零卖压" in text

    def test_describe_states_condition_not_backtest_stats(self):
        """描述给的是对这只票的判断, 不能把回测数字抄出来。"""
        hits = evaluate_markers({"sector_score": 100, "rsi": 72})
        text = describe_markers(hits)
        for banned in ("历史同类", "历史同档", "10日均值", "暴跌率", "胜率", "基线", "例）", " 例"):
            assert banned not in text, f"描述里不该出现回测口径「{banned}」：{text}"
        # 换来的是状态刻画 + 应对
        assert "板块情绪已经打满" in text
        assert "追入的性价比偏低" in text

    def test_describe_empty_is_safe(self):
        assert isinstance(describe_markers([]), str)

    def test_negative_listed_before_positive(self):
        """风险优先展示, 避免用户只看到利好。"""
        hits = evaluate_markers({"tech_score": 70, "sector_score": 45,
                                 "sell_signals": 0, "chase_risk": 90})
        text = describe_markers(hits)
        assert text.index("追高透支") < text.index("爆发基因")


# ---------------------------------------------------------------- 批次拥挤度
class TestBatchCrowding:
    def _items(self, n, sector=50.0, chase=10.0):
        return [{"sector_score": sector, "chase_risk": chase} for _ in range(n)]

    def test_hot_sector_crowding_detected(self):
        items = self._items(6, sector=100.0) + self._items(4, sector=40.0)
        r = batch_crowding(items)
        assert r["crowded"] is True
        assert r["hot_sector_share"] == pytest.approx(0.6)
        assert "板块" in r["summary"]

    def test_chase_crowding_detected(self):
        items = self._items(5, chase=90.0) + self._items(5)
        r = batch_crowding(items)
        assert r["crowded"] is True
        assert r["high_chase_share"] == pytest.approx(0.5)

    def test_calm_batch_not_crowded(self):
        r = batch_crowding(self._items(20))
        assert r["crowded"] is False

    def test_small_batch_is_not_judged(self):
        """样本太少的批次不下拥挤结论(避免单票误报)。"""
        r = batch_crowding(self._items(3, sector=100.0))
        assert r["crowded"] is False
        assert r["insufficient"] is True

    def test_empty_batch_is_safe(self):
        r = batch_crowding([])
        assert r["crowded"] is False
        assert r["insufficient"] is True


# ---------------------------------------------------------------- 因子提取
class TestExtractFactors:
    def _stock(self, **over):
        stock = {
            "scoring_result": {
                "scores": {"technical": 66.0, "sector": 48.0},
                "details": {
                    "technical": {"RSI": 62.0},
                    "quantitative": {"sell_count": 0},
                    "price_changes": {"change_5d": 4.2},
                    "momentum": {"chase_risk_score": 30.0},
                },
            }
        }
        stock["scoring_result"]["details"].update(over.pop("details", {}))
        stock.update(over)
        return stock

    def test_reads_all_six_factors(self):
        f = extract_factors(self._stock())
        assert f["tech_score"] == 66.0
        assert f["sector_score"] == 48.0
        assert f["rsi"] == 62.0
        assert f["sell_signals"] == 0
        assert f["change_5d"] == 4.2
        assert f["chase_risk"] == 30.0

    def test_chase_prefers_advanced_analysis_over_momentum(self):
        stock = self._stock()
        stock["scoring_result"]["advanced_analysis"] = {
            "overall_score": {"risk_metrics": {"chase_risk_score": 85.0}}
        }
        assert extract_factors(stock)["chase_risk"] == 85.0

    def test_chase_falls_back_to_momentum_when_advanced_is_zero(self):
        """与 opportunity_repo/评分逻辑一致: 0 视为缺失, 回退动量明细。"""
        stock = self._stock()
        stock["scoring_result"]["advanced_analysis"] = {
            "overall_score": {"risk_metrics": {"chase_risk_score": 0}}
        }
        assert extract_factors(stock)["chase_risk"] == 30.0

    def test_empty_stock_yields_no_usable_factors(self):
        assert evaluate_markers(extract_factors({})) == []

    def test_extract_then_evaluate_round_trip(self):
        hits = evaluate_markers(extract_factors(self._stock()))
        assert "breakout_gene" in {h.key for h in hits}
        assert "clean_sell" in {h.key for h in hits}


# ---------------------------------------------------------------- 一站式出参
class TestMarkerPayload:
    def test_payload_shape(self):
        p = marker_payload({"tech_score": 70, "sector_score": 45,
                            "sell_signals": 0})
        assert p["version"] == MARKERS_VERSION
        assert isinstance(p["markers"], list)
        assert p["markers"][0]["key"]
        assert p["markers"][0]["label"]
        assert p["constitution"]["grade"] == "爆发体质"
        assert isinstance(p["description"], str)

    def test_payload_is_json_serializable(self):
        import json
        p = marker_payload({"tech_score": 40, "chase_risk": 85,
                            "change_5d": 18, "rsi": 80})
        json.dumps(p, ensure_ascii=False)  # 不抛异常即可

    def test_payload_empty_factors_is_neutral(self):
        p = marker_payload({})
        assert p["markers"] == []
        assert p["constitution"]["grade"] == "中性体质"


# ---------------------------------------------------------------- 深度描述
class TestNarrate:
    """narrate 把标记放回**这只票自己的走势**里讲, 而不是复述回测。"""

    FACTORS = {"tech_score": 19, "sector_score": 97, "rsi": 78,
               "chase_risk": 85, "sell_signals": 5, "change_5d": 18.0}
    CONTEXT = {"position_pct": 0.92, "distance_from_high": 3.2, "change_5d": 18.0,
               "change_20d": 41.0, "change_60d": 66.0, "consecutive_up_days": 5,
               "volume_ratio": 2.3, "ma_status": "均线多头排列",
               "sector_name": "通信设备"}

    def test_sections_present(self):
        from analysis.outcome_markers import narrate
        text = narrate(self.FACTORS, self.CONTEXT)
        assert "【走势定位】" in text
        assert "【风险特征】" in text
        assert "【结论】" in text

    def test_grounded_in_this_stock_numbers(self):
        """走势定位必须引用这只票自己的位置/涨幅/节奏。"""
        from analysis.outcome_markers import narrate
        text = narrate(self.FACTORS, self.CONTEXT)
        assert "年内分位 92%" in text
        assert "距年内高点 3.2%" in text
        assert "20日 +41.0%" in text
        assert "已连涨 5 天" in text
        assert "通信设备" in text

    def test_upside_section_for_positive_side(self):
        from analysis.outcome_markers import narrate
        text = narrate({"tech_score": 66, "sector_score": 42, "rsi": 61, "sell_signals": 0},
                       {"position_pct": 0.38})
        assert "【正向特征】" in text
        assert "【风险特征】" not in text

    def test_no_backtest_numbers_and_no_banned_words(self):
        from analysis.outcome_markers import narrate
        text = narrate(self.FACTORS, self.CONTEXT)
        for banned in ("历史同类", "历史同档", "10日均值", "胜率", "暴涨", "暴跌", "基线"):
            assert banned not in text, f"叙述里不该出现「{banned}」：{text}"

    def test_ends_with_disclaimer(self):
        from analysis.outcome_markers import DISCLAIMER, narrate
        assert narrate(self.FACTORS, self.CONTEXT).endswith(DISCLAIMER)
        assert narrate({}, {}).endswith(DISCLAIMER)

    def test_no_context_still_well_formed(self):
        from analysis.outcome_markers import narrate
        text = narrate(self.FACTORS)
        assert "【走势定位】" not in text      # 没走势资料就不硬编
        assert "【风险特征】" in text
        assert "【结论】" in text

    def test_no_hits_no_context_is_neutral(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {})
        assert "【特征判定】" in text
        assert "中性体质" in text

    def test_payload_exposes_narrative(self):
        p = marker_payload(self.FACTORS, self.CONTEXT)
        assert "【走势定位】" in p["narrative"]
        assert p["markers"][0]["summary"] and p["markers"][0]["action"]
        assert p["markers"][0]["tail"] in ("upside", "downside")


# ---------------------------------------------------------------- 降级 run 守卫
class TestExtractFromDegradedRun:
    """取数失败的 0 分不能被当成真实因子 —— 否则误触发「技术乏力」。"""

    def test_technical_error_makes_tech_and_rsi_missing(self):
        from analysis.outcome_markers import extract_factors
        stock = {"scoring_result": {
            "scores": {"technical": 0.0, "sector": 60},
            "details": {"technical": {"error": "无历史数据"},
                        "quantitative": {"sell_count": 2}},
        }}
        factors = extract_factors(stock)
        assert factors["tech_score"] is None
        assert factors["rsi"] is None
        assert factors["sector_score"] == 60      # 别的维度不受影响
        assert "tech_weak" not in _keys(evaluate_markers(factors))

    def test_momentum_error_makes_chase_missing(self):
        from analysis.outcome_markers import extract_factors
        stock = {"scoring_result": {
            "scores": {"technical": 55},
            "details": {"technical": {"RSI": 60}, "momentum": {"error": "无历史数据"}},
        }}
        assert extract_factors(stock)["chase_risk"] is None

    def test_healthy_run_keeps_all_factors(self):
        from analysis.outcome_markers import extract_context, extract_factors
        stock = {"sector": "通信设备", "scoring_result": {
            "scores": {"technical": 62, "sector": 48},
            "details": {
                "technical": {"RSI": 61, "volume_ratio": 1.4, "MA_status": "均线多头排列"},
                "quantitative": {"sell_count": 0},
                "price_changes": {"change_5d": 3.1},
                "momentum": {"chase_risk_score": 25, "position_pct": 0.4, "change_20d": 6.0},
            },
        }}
        factors = extract_factors(stock)
        assert factors["tech_score"] == 62 and factors["rsi"] == 61
        assert factors["chase_risk"] == 25 and factors["sell_signals"] == 0
        context = extract_context(stock)
        assert context["position_pct"] == 0.4
        assert context["ma_status"] == "均线多头排列"
        assert context["sector_name"] == "通信设备"

    def test_context_skips_failed_detail_blocks(self):
        from analysis.outcome_markers import extract_context
        stock = {"scoring_result": {"details": {
            "technical": {"error": "无历史数据", "volume_ratio": 1.4},
            "momentum": {"error": "无历史数据", "position_pct": 0.9},
        }}}
        context = extract_context(stock)
        assert "volume_ratio" not in context
        assert "position_pct" not in context


class TestTrendSentenceLabels:
    """评分链路给的是裸值('多头排列'/'金叉'/'一般'), 摆进句子必须补维度名。"""

    def test_bare_status_values_get_dimension_labels(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {"ma_status": "多头排列", "macd_status": "零轴上死叉",
                            "vol_price_status": "放量上涨", "entry_timing": "观望"})
        assert "均线多头排列" in text
        assert "MACD 零轴上死叉" in text
        assert "量价放量上涨" in text
        assert "入场时机：观望" in text

    def test_no_double_prefix_when_value_already_labelled(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {"ma_status": "均线多头排列"})
        assert "均线均线" not in text
        assert "均线多头排列" in text

    def test_uninformative_status_values_are_skipped(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {"ma_status": "中性", "macd_status": "中性",
                            "vol_price_status": "一般", "position_pct": 0.5})
        assert "中性；" not in text and "；一般" not in text

    def test_position_and_streak_rendered_from_this_stock(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {"position_pct": 0.94, "distance_from_high": 2.1,
                            "consecutive_up_days": 4, "volume_ratio": 2.1})
        assert "年内高位" in text and "年内分位 94%" in text
        assert "距年内高点 2.1%" in text
        assert "已连涨 4 天" in text
        assert "量比 2.1" in text

    def test_short_streak_and_flat_volume_are_not_mentioned(self):
        from analysis.outcome_markers import narrate
        text = narrate({}, {"consecutive_up_days": 1, "volume_ratio": 1.0})
        assert "连涨" not in text
        assert "量比" not in text
