#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v24 共享打分规则单测 — 重点覆盖 5 条 v24 参数改动的方向与边界。

规则来源: analysis/scoring_rules.py (sim/live 统一消费)。
证据: docs/superpowers/specs/2026-06-10-pc-and-scoring-optimization-analysis.md §4
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.scoring_rules import (  # noqa: E402
    LIVE_PATTERN_COVERED_RULES,
    RULESET,
    RULESET_VERSION,
    evaluate_shared_rules,
    is_degraded_quant,
    shared_bonus,
    shared_penalty,
)


def hits_by_rule(factors, **kw):
    return {h.rule: h.delta for h in evaluate_shared_rules(factors, **kw)}


def test_ruleset_version_is_v24():
    assert RULESET_VERSION == 'v24'


# ===== v24#1: chg3d ≥12 罚12, ≥18 罚15 (恢复重罚) =====

def test_chg3d_12_penalty():
    h = hits_by_rule({'change_3d': 13})
    assert h.get('chg3d_12') == -12


def test_chg3d_18_penalty():
    h = hits_by_rule({'change_3d': 19})
    assert h.get('chg3d_18') == -15
    assert 'chg3d_12' not in h  # 不叠加


def test_chg3d_below_threshold_no_penalty():
    h = hits_by_rule({'change_3d': 11.9})
    assert 'chg3d_12' not in h and 'chg3d_18' not in h


# ===== v24#2: chase 分段罚 40-60:-5 / 60-80:-12 / ≥80:-15, 且无任何 chase 奖励 =====

@pytest.mark.parametrize('chase,rule,pen', [
    (45, 'chase_40', -5),
    (59.9, 'chase_40', -5),
    (60, 'chase_60', -12),
    (75, 'chase_60', -12),   # 旧 live 此处 +4 奖励, v24 改为罚 (方向冲突修复)
    (80, 'chase_80', -15),
    (95, 'chase_80', -15),
])
def test_chase_band_penalties(chase, rule, pen):
    h = hits_by_rule({'chase_risk': chase})
    assert h.get(rule) == pen


def test_chase_no_bonus_anywhere():
    """v24#2: 移除 live 的 chase>=75 +4 / >=50 +2 奖励 — chase 单因子只能产生惩罚"""
    for chase in [0, 10, 30, 50, 55, 65, 75, 85, 100]:
        hits = evaluate_shared_rules({'chase_risk': chase})
        assert all(h.delta <= 0 for h in hits), f'chase={chase} 不应产生奖励: {hits}'


def test_chase_below_40_no_penalty():
    h = hits_by_rule({'chase_risk': 39.9})
    assert not any(r.startswith('chase_') for r in h)


# ===== v24#3: 移除 zt_high_chase_bonus (涨停+chase≥50 不再 +8) =====

def test_zt_high_chase_no_bonus():
    h = hits_by_rule({'day_change': 10.0, 'chase_risk': 60})
    assert 'zt_high_chase' not in h
    assert 'zt_low_chase' not in h  # chase>=50 也不给低chase奖励
    bonus_rules = [r for r, d in h.items() if d > 0]
    assert bonus_rules == [], f'涨停+高chase不应有任何奖励: {h}'


def test_zt_low_chase_bonus_kept():
    h = hits_by_rule({'day_change': 10.0, 'chase_risk': 30, 'buy_signals': 5})
    assert h.get('zt_low_chase') == RULESET['zt_low_chase_bonus']


def test_zt_low_chase_blocked_by_signal_crowd():
    h = hits_by_rule({'day_change': 10.0, 'chase_risk': 30, 'buy_signals': 9})
    assert 'zt_low_chase' not in h


# ===== v24#4: quant<50 奖励加 sector<55 门控; sector 缺失视为不满足 =====

def test_qs_low_bonus_with_cold_sector():
    h = hits_by_rule({'quant_score': 45, 'sector_score': 50})
    assert h.get('qs_low_gated') == RULESET['qs_low_bonus']


def test_qs_low_no_bonus_with_warm_sector():
    h = hits_by_rule({'quant_score': 45, 'sector_score': 70})
    assert 'qs_low_gated' not in h


def test_qs_low_no_bonus_when_sector_missing():
    assert 'qs_low_gated' not in hits_by_rule({'quant_score': 45})
    assert 'qs_low_gated' not in hits_by_rule({'quant_score': 45, 'sector_score': None})
    assert 'qs_low_gated' not in hits_by_rule({'quant_score': 45, 'sector_score': float('nan')})


# ===== v24#5: RSI≥80 × chase≥60 组合罚 -10 =====

def test_rsi80_chase60_combo_penalty():
    h = hits_by_rule({'rsi': 81, 'chase_risk': 65})
    assert h.get('rsi80_chase60') == -10
    # 同时独立惩罚也在 (组合罚是额外的)
    assert h.get('rsi_overbought') == -15
    assert h.get('chase_60') == -12


def test_rsi80_chase60_combo_requires_both():
    assert 'rsi80_chase60' not in hits_by_rule({'rsi': 81, 'chase_risk': 50})
    assert 'rsi80_chase60' not in hits_by_rule({'rsi': 75, 'chase_risk': 65})


# ===== 其余共享规则方向回归 =====

def test_quant_extreme_consensus_penalties():
    assert hits_by_rule({'quant_score': 96}).get('qs_extreme') == -RULESET['qs_95_pen']
    assert hits_by_rule({'quant_score': 92}).get('qs_high') == -RULESET['qs_90_pen']


def test_sell0_bonus_and_zt_escalation():
    assert hits_by_rule({'sell_signals': 0}).get('sell0') == RULESET['sell0_bonus']
    assert hits_by_rule({'sell_signals': 0, 'day_change': 10}).get('sell0') == RULESET['sell0_zt_bonus']
    assert 'sell0' not in hits_by_rule({'sell_signals': 1})


def test_sector_dead_zone_u_shape():
    mid = hits_by_rule({'sector_score': 67.5}).get('sector_dead')
    edge = hits_by_rule({'sector_score': 61}).get('sector_dead', 0)
    assert mid == -RULESET['sector_dead_peak_pen']
    assert abs(edge) < abs(mid)  # 边界惩罚轻于中心
    assert 'sector_dead' not in hits_by_rule({'sector_score': 59})
    assert hits_by_rule({'sector_score': 96}).get('sector_hot') == -RULESET['sector_hot_pen']


def test_missing_factors_trigger_nothing():
    assert evaluate_shared_rules({}) == []
    assert evaluate_shared_rules({'rsi': None, 'chase_risk': float('nan')}) == []


def test_skip_live_pattern_covered_rules():
    factors = {'day_change': 10.0, 'chase_risk': 30, 'buy_signals': 5}
    h = hits_by_rule(factors, skip=LIVE_PATTERN_COVERED_RULES)
    assert 'zt_low_chase' not in h  # live 由牛股Pattern块承担, 共享侧跳过


def test_penalty_bonus_aggregation():
    hits = evaluate_shared_rules({'rsi': 45, 'chase_risk': 85})
    assert shared_bonus(hits) == RULESET['rsi_golden_bonus']
    assert shared_penalty(hits) == RULESET['chase_80_pen']


# ===== degraded 判定: 仅数据缺失算降级, 真实弱信号不算 =====

def test_is_degraded_quant():
    assert is_degraded_quant({'error': '无历史数据'}) is True
    assert is_degraded_quant({'error': '无历史数据', 'degraded': True}) is True
    assert is_degraded_quant({'buy_count': 0, 'sell_count': 5}) is False  # 真实弱信号
    assert is_degraded_quant({'error': '其他错误'}) is False
    assert is_degraded_quant(None) is False
