#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


from analysis.opportunity_filter import OpportunityFilter
from analysis.opportunity_scorer import OpportunityScorer


def test_stage1_liquidity_no_keyerror_with_empty_config():
    original = OpportunityFilter.STAGE_THRESHOLDS.get('stage1_liquidity')
    OpportunityFilter.STAGE_THRESHOLDS['stage1_liquidity'] = {}
    try:
        f = OpportunityFilter()
        scoring_result = {
            'details': {
                'liquidity': {
                    'avg_amount_20d_wan': 500,
                    'avg_turnover_20d': 0.1,
                    'circulation_market_cap': 10,
                    'liquidity_level': '较低'
                }
            }
        }
        r = f.stage1_liquidity_check(scoring_result)
        assert r['stage'] == 1
        assert '筛选已禁用' in r['reason']
    finally:
        if original is None:
            del OpportunityFilter.STAGE_THRESHOLDS['stage1_liquidity']
        else:
            OpportunityFilter.STAGE_THRESHOLDS['stage1_liquidity'] = original


def test_quant_buy_count_bonus_monotonic():
    scorer = OpportunityScorer()
    last = -1.0
    for buy_count in range(0, 31):
        bonus = scorer._compute_quant_buy_count_bonus(buy_count)
        assert bonus >= last
        last = bonus


def test_total_score_quant_buy_bonus_monotonic_when_sell_fixed():
    scorer = OpportunityScorer()
    last = -1.0
    for buy_count in range(0, 16):
        bonus = scorer._compute_total_score_quant_buy_bonus(buy_count, 0, 70)
        assert bonus >= last
        last = bonus

    assert scorer._compute_total_score_quant_buy_bonus(3, 3, 70) == 0.0
    assert scorer._compute_total_score_quant_buy_bonus(2, 5, 70) == 0.0


def test_score_clamp():
    scorer = OpportunityScorer()
    assert scorer._clamp_score(126.54) == 100.0
    assert scorer._clamp_score(-1) == 0.0
    assert scorer._clamp_score(99.9) == 99.9


def test_headroom_bonus():
    scorer = OpportunityScorer()
    base = 63.0
    new_score = scorer._apply_headroom_bonus(base, 37.0)
    assert base < new_score < 100.0
    assert scorer._apply_headroom_bonus(100.0, 50.0) == 100.0


def main():
    test_stage1_liquidity_no_keyerror_with_empty_config()
    test_quant_buy_count_bonus_monotonic()
    test_total_score_quant_buy_bonus_monotonic_when_sell_fixed()
    test_score_clamp()
    test_headroom_bonus()
    print('OK')


if __name__ == '__main__':
    main()
