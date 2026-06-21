"""「个股机会」量化快速信息的评分分项必须全中文(不暴露 momentum/volume_health 等裸英文键)。"""
import re

import webui.core as core


def test_format_score_parts_all_chinese_labels():
    # 覆盖评分器实际产出的全部分项(含曾经漏译的 momentum/volume_health/liquidity/events/dragon_tiger)
    scores = {
        'quantitative': 100.0, 'technical': 40.0, 'momentum': 0.0,
        'volume_health': 100.0, 'liquidity': 75.0, 'sentiment': 60.0,
        'sector': 74.3, 'fundamental': 60.0, 'events': 15.0, 'dragon_tiger': 50.0,
    }
    out = core._format_score_parts(scores)
    labels = [seg.split(':', 1)[0] for seg in out.split('，')]
    # 任何分项标签都不应残留 ASCII 字母(裸英文键)
    leaked = [lbl for lbl in labels if re.search(r'[A-Za-z]', lbl)]
    assert not leaked, f"未翻译的评分分项键: {leaked} (完整串: {out})"
    assert '动量:0.0' in out and '量能:100.0' in out and '龙虎榜:50.0' in out


def test_format_score_parts_unknown_key_falls_back_to_raw():
    # 未知键仍原样显示(不静默丢弃),便于发现新增维度需要补译
    assert core._format_score_parts({'brand_new_dim': 12.0}) == 'brand_new_dim:12.0'
