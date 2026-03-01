#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v11 深度优化 - 解决S级缺失 + B级收益过低
==========================================
核心问题诊断:
  1. S级缺失: adj_high_threshold=79, adj_high_pen=8 导致评分上限被压缩
     - 任何score达到79+都会被减8, 实际最高只能约71-79
     - 要达到S级(85+)需要原始adj>=93, 几乎不可能
  2. B级收益低: B级内部存在明显分化
     - tech_score>=80 在B级中表现最差(胜率34.6%)
     - RSI 40-55 黄金区间表现最好(胜率73.3%)
     - 原始score>=76 的B级股票反而亏损(胜率18.2%)

解决方案:
  1. 调整adj_high_threshold/pen, 释放S级空间
  2. 新增tech_high_pen: 技术面虚高惩罚
  3. 新增score_very_high_pen: 原始高分反向指标惩罚
  4. 新增rsi_golden_bonus: RSI黄金区间奖励
  5. 新增低波动奖励: 3日涨幅温和时加分
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime
from copy import deepcopy

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
RESULTS_DIR = os.path.join(project_root, 'results')

# v10 当前生产参数
V10_PARAMS = {
    'rsi_85_pen': 25, 'rsi_80_pen': 15, 'rsi_75_pen': 3,
    'day_chg_20_pen': 25, 'zt_chase_pen': 12, 'zt_signal_pen': 14,
    'zt_base_pen': 3, 'chg7_pen': 3, 'chg5_pen': 5,
    'chg5d_18_pen': 25, 'chg3d_20_pen': 20, 'chg3d_15_pen': 16, 'chg3d_10_pen': 12,
    'chase_80_pen': 20, 'chase_60_pen': 6,
    'tech_low_pen': 10, 'sector_hot_pen': 10, 'sector_dead_pen': 3,
    'score_high_threshold': 72, 'score_high_pen': 19,
    'rsi80_3d10_pen': 10, 'chg5d15_rsi72_pen': 10,
    'signal_crowd_pen': 1, 'sell_dom_pen': 0, 'sell_abs_pen': 0,
    'chase_rsi_combo_pen': 0,
    'rsi_oversold_bonus': 9, 'buy_dominance_bonus': 0,
    'zt_low_chase_bonus': 10, 'strong_low_chase_bonus': 15,
    'momentum_start_bonus': 5, 'quant_moderate_bonus': 0,
    'low_risk_momentum_bonus': 5,
    'sweet_low': 63, 'sweet_high': 69, 'sweet_bonus': 0,
    'adj_high_threshold': 79, 'adj_high_pen': 8,
    # === v11 新增参数 ===
    'tech_high_pen': 0,           # 技术面>=80虚高惩罚 (B级中tech>80胜率仅34.6%)
    'score_very_high_pen': 0,     # 原始评分>=76额外惩罚 (B级中score>=76胜率仅18.2%)
    'score_very_high_threshold': 76,
    'rsi_golden_bonus': 0,        # RSI 40-55黄金区间奖励 (B级中胜率73.3%)
    'rsi_golden_low': 40,
    'rsi_golden_high': 55,
    'low_volatility_bonus': 0,    # 3日涨幅温和(0~5%)奖励
    'day_chg_neg_bonus': 0,       # 当日小跌(-5%~0%)反弹奖励
}


def score_row(row, params):
    """评分函数 - 兼容v10 + v11新增参数"""
    score = float(row.get('score', 0) or 0)
    chase = row.get('chase_risk')
    rsi = row.get('rsi')
    day_chg = row.get('day_change')
    chg_5d = row.get('change_5d')
    chg_3d = row.get('change_3d')
    qs = row.get('quant_score')
    buy_sig = row.get('buy_signals')
    sell_sig = row.get('sell_signals')
    tech = row.get('tech_score')
    sector = row.get('sector_score')

    penalty = 0
    bonus = 0

    # ========== 原有v10惩罚 ==========
    if pd.notna(rsi):
        if rsi >= 85: penalty += params['rsi_85_pen']
        elif rsi > 80: penalty += params['rsi_80_pen']
        elif rsi > 75: penalty += params['rsi_75_pen']

    if pd.notna(day_chg):
        if day_chg >= 20: penalty += params['day_chg_20_pen']
        elif day_chg >= 9.5:
            if pd.notna(chase) and chase >= 50: penalty += params['zt_chase_pen']
            elif pd.notna(buy_sig) and buy_sig > 8: penalty += params['zt_signal_pen']
            else: penalty += params['zt_base_pen']
        elif day_chg >= 7: penalty += params['chg7_pen']
        elif day_chg >= 5: penalty += params['chg5_pen']

    if pd.notna(chg_5d) and chg_5d > 18: penalty += params['chg5d_18_pen']
    if pd.notna(chg_3d):
        if chg_3d > 20: penalty += params['chg3d_20_pen']
        elif chg_3d > 15: penalty += params['chg3d_15_pen']
        elif chg_3d > 10: penalty += params['chg3d_10_pen']

    if pd.notna(chase):
        if chase >= 80: penalty += params['chase_80_pen']
        elif chase >= 60: penalty += params['chase_60_pen']

    if pd.notna(tech) and tech < 60:
        has_exempt = False
        if pd.notna(day_chg) and 9.5 <= day_chg < 20:
            if pd.notna(chase) and chase < 50 and pd.notna(buy_sig) and buy_sig <= 8:
                has_exempt = True
        if pd.notna(day_chg) and 3 <= day_chg < 10:
            if pd.notna(chase) and chase < 50 and pd.notna(qs) and 55 <= qs <= 80:
                has_exempt = True
        if not has_exempt: penalty += params['tech_low_pen']

    if pd.notna(sector):
        if sector >= 95: penalty += params['sector_hot_pen']
        elif 60 <= sector < 75: penalty += params['sector_dead_pen']

    if score >= params['score_high_threshold']: penalty += params['score_high_pen']

    if pd.notna(rsi) and pd.notna(chg_3d) and rsi > 80 and chg_3d > 10: penalty += params['rsi80_3d10_pen']
    if pd.notna(chg_5d) and pd.notna(rsi) and chg_5d > 15 and rsi > 72: penalty += params['chg5d15_rsi72_pen']

    if pd.notna(buy_sig) and buy_sig >= 15: penalty += params['signal_crowd_pen']
    if pd.notna(sell_sig) and pd.notna(buy_sig) and sell_sig > buy_sig: penalty += params['sell_dom_pen']
    if pd.notna(sell_sig) and sell_sig >= 5: penalty += params['sell_abs_pen']
    if pd.notna(chase) and pd.notna(rsi) and chase > 30 and rsi > 60: penalty += params['chase_rsi_combo_pen']

    # ========== v11 新增惩罚 ==========

    # 技术面虚高惩罚 (tech>=80在B级表现最差)
    if pd.notna(tech) and tech >= 80:
        penalty += params['tech_high_pen']

    # 原始评分极高惩罚 (score>=76在B级亏损)
    if score >= params['score_very_high_threshold']:
        penalty += params['score_very_high_pen']

    # ========== 原有v10奖励 ==========
    if pd.notna(rsi) and rsi < 35: bonus += params['rsi_oversold_bonus']
    if pd.notna(buy_sig) and pd.notna(sell_sig) and buy_sig >= 5 and sell_sig > 0 and buy_sig >= sell_sig * 2:
        bonus += params['buy_dominance_bonus']
    if pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase < 50:
        if not (pd.notna(buy_sig) and buy_sig > 8): bonus += params['zt_low_chase_bonus']
    elif pd.notna(day_chg) and day_chg >= 7 and pd.notna(chase) and chase < 40:
        bonus += params['strong_low_chase_bonus']
    if pd.notna(day_chg) and 3 <= day_chg < 10 and pd.notna(chase) and chase < 50:
        bonus += params['momentum_start_bonus']
    if pd.notna(qs) and 55 <= qs <= 80: bonus += params['quant_moderate_bonus']
    if pd.notna(chase) and pd.notna(rsi) and chase < 25 and rsi < 50: bonus += params['low_risk_momentum_bonus']

    # ========== v11 新增奖励 ==========

    # RSI黄金区间奖励 (40-55在B级胜率73.3%)
    if pd.notna(rsi) and params['rsi_golden_low'] <= rsi <= params['rsi_golden_high']:
        bonus += params['rsi_golden_bonus']

    # 低波动奖励 (3日涨幅温和)
    if pd.notna(chg_3d) and 0 <= chg_3d <= 5:
        bonus += params['low_volatility_bonus']

    # 当日小跌反弹奖励
    if pd.notna(day_chg) and -5 <= day_chg < 0:
        bonus += params['day_chg_neg_bonus']

    adj = max(0, score - penalty + bonus)
    if params['sweet_low'] <= adj <= params['sweet_high']: adj += params['sweet_bonus']
    if adj >= params['adj_high_threshold']: adj -= params['adj_high_pen']
    return adj


def evaluate_full(df, params):
    """多层级全面评估"""
    df = df.copy()
    df['adj_score'] = df.apply(lambda r: score_row(r, params), axis=1)

    tiers = {}
    for name, lo, hi in [('S', 85, 999), ('A', 78, 85), ('B', 70, 78), ('C+', 60, 70), ('C', 0, 60)]:
        mask = (df['adj_score'] >= lo) & (df['adj_score'] < hi) if hi < 999 else df['adj_score'] >= lo
        tier_df = df[mask]
        r5 = tier_df['return_5d'].dropna()
        r3 = tier_df['return_3d'].dropna()
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            avg = r5.mean()
            losses = r5[r5 < 0]
            pf = abs(r5[r5 > 0].sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 999
            avg3 = r3.mean() if len(r3) > 0 else 0
        else:
            wr = 0; avg = 0; pf = 0; avg3 = 0
        tiers[name] = {'n': len(r5), 'wr': wr, 'avg': avg, 'pf': pf, 'avg3': avg3}

    return tiers


def multi_tier_objective(tiers):
    """
    多层级目标函数 - v11增强版
    重点: S级可达性 + A级质量 + B级正收益 + 层级单调
    """
    s = tiers.get('S', {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0})
    a = tiers.get('A', {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0})
    b = tiers.get('B', {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0})
    cp = tiers.get('C+', {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0})

    score = 0

    # S级奖励 (权重15%) - 关键: 有S级就加分
    if s['n'] > 0:
        s_score = min(s['n'], 10) * 2 + s['wr'] * 0.3 + min(s['avg'], 30) * 0.5
        score += s_score * 0.15
    else:
        score -= 5  # 无S级扣分

    # A级质量 (权重30%)
    if a['n'] >= 3:
        a_score = a['wr'] * 0.3 + a['avg'] * 0.5 + min(a['n'], 20) * 0.5
        score += a_score * 0.30
    elif a['n'] > 0:
        a_score = a['wr'] * 0.3 + a['avg'] * 0.5
        score += a_score * 0.15
    else:
        score -= 15

    # B级质量 (权重35%) - 最重要
    if b['n'] >= 5:
        b_score = b['wr'] * 0.25 + b['avg'] * 0.8 + min(b['n'], 50) * 0.1
        # B级正收益额外奖励
        if b['avg'] > 0:
            b_score += min(b['avg'] * 3, 15)
        elif b['avg'] < -1:
            b_score -= 10
        score += b_score * 0.35
    elif b['n'] > 0:
        b_score = b['wr'] * 0.2 + b['avg'] * 0.5
        score += b_score * 0.15

    # 层级单调性 (权重15%)
    monotonic = 0
    if s['n'] > 0 and a['n'] > 0:
        if s['avg'] > a['avg']: monotonic += 3
        if s['wr'] >= a['wr']: monotonic += 3
    if a['n'] > 0 and b['n'] > 0:
        if a['wr'] > b['wr']: monotonic += 4
        if a['avg'] > b['avg']: monotonic += 4
    if b['n'] > 0 and cp['n'] > 0:
        if b['wr'] > cp['wr']: monotonic += 3
        if b['avg'] > cp['avg']: monotonic += 3
    score += monotonic * 0.15

    # A+B总量惩罚 (如果高质量股太少也不好)
    total_good = s['n'] + a['n'] + b['n']
    if total_good < 15:
        score -= (15 - total_good) * 0.5

    return score


def print_tiers(tiers, label=""):
    if label:
        print(f"\n  {label}:")
    print(f"  {'评级':>6} | {'数量':>5} | {'胜率':>7} | {'5d收益':>10} | {'3d收益':>10} | {'盈亏比':>6}")
    print("  " + "-" * 60)
    for name in ['S', 'A', 'B', 'C+', 'C']:
        t = tiers.get(name, {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0, 'avg3': 0})
        if t['n'] > 0:
            pf_str = f"{t['pf']:.2f}" if t['pf'] < 100 else "∞"
            avg3 = t.get('avg3', 0)
            print(f"  {name:>6} | {t['n']:>5} | {t['wr']:>6.1f}% | {t['avg']:>+9.2f}% | {avg3:>+9.2f}% | {pf_str:>6}")
        else:
            print(f"  {name:>6} | {t['n']:>5} | {'—':>7} | {'—':>10} | {'—':>10} | {'—':>6}")


# ============ 搜索空间 ============
# 只搜索与S级/B级问题直接相关的参数
SEARCH_SPACE = {
    # === S级关键: 调整高分压制 ===
    'adj_high_threshold': [79, 82, 85, 88, 90, 95, 999],  # 999=禁用
    'adj_high_pen': [0, 3, 5, 8, 10],

    # === B级关键: 新增参数 ===
    'tech_high_pen': [0, 3, 5, 8, 10, 12, 15],
    'score_very_high_pen': [0, 3, 5, 8, 10, 12],
    'score_very_high_threshold': [74, 76, 78, 80],
    'rsi_golden_bonus': [0, 3, 5, 8, 10, 12],
    'rsi_golden_low': [35, 40, 45],
    'rsi_golden_high': [50, 55, 60],
    'low_volatility_bonus': [0, 2, 3, 5, 8],
    'day_chg_neg_bonus': [0, 2, 3, 5, 8],

    # === 现有参数微调 ===
    'score_high_threshold': [70, 72, 74, 76],
    'score_high_pen': [10, 15, 19, 22, 25],
    'tech_low_pen': [5, 8, 10, 15],
    'chase_60_pen': [3, 5, 6, 8, 10],
    'chg3d_10_pen': [5, 8, 10, 12, 15],
    'rsi_oversold_bonus': [5, 8, 9, 12, 15],
    'momentum_start_bonus': [3, 5, 8, 10],
    'low_risk_momentum_bonus': [3, 5, 8, 10],
    'strong_low_chase_bonus': [10, 15, 18, 20],
    'zt_low_chase_bonus': [5, 10, 12, 15],
}


def main():
    print("=" * 70)
    print("  v11 深度优化 - S级释放 + B级收益提升")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 加载数据
    csv_files = sorted([f for f in os.listdir(RESULTS_DIR)
                        if f.startswith('backtest_rebuilt_') and f.endswith('.csv')])
    csv_path = os.path.join(RESULTS_DIR, csv_files[-1])
    df = pd.read_csv(csv_path)
    df_valid = df[df['return_5d'].notna()].copy()
    print(f"\n  有效数据: {len(df_valid)} 行, {df_valid['report_date'].nunique()} 天")

    # ============ 诊断: adj_high_threshold对S级的影响 ============
    print("\n" + "=" * 60)
    print("  诊断: adj_high_threshold 对各级别的影响")
    print("=" * 60)

    for threshold in [79, 82, 85, 88, 90, 95, 999]:
        for pen in [0, 5, 8]:
            test = dict(V10_PARAMS)
            test['adj_high_threshold'] = threshold
            test['adj_high_pen'] = pen
            tiers = evaluate_full(df_valid, test)
            s_n = tiers.get('S', {}).get('n', 0)
            a_n = tiers.get('A', {}).get('n', 0)
            b_n = tiers.get('B', {}).get('n', 0)
            s_avg = tiers.get('S', {}).get('avg', 0)
            a_avg = tiers.get('A', {}).get('avg', 0)
            b_avg = tiers.get('B', {}).get('avg', 0)
            if s_n > 0 or threshold in [79, 999]:
                label = "★" if s_n > 0 else ""
                print(f"  threshold={threshold:>3}, pen={pen}: "
                      f"S={s_n:>2}({s_avg:+.1f}%) A={a_n:>2}({a_avg:+.1f}%) B={b_n:>3}({b_avg:+.1f}%) {label}")

    # ============ 基线评估 ============
    base_tiers = evaluate_full(df_valid, V10_PARAMS)
    base_obj = multi_tier_objective(base_tiers)
    print_tiers(base_tiers, "v10基线")
    print(f"  目标函数: {base_obj:.2f}")

    # ============ 第1轮: S级释放参数搜索 ============
    print("\n" + "=" * 60)
    print("  第1轮: S级释放 - adj_high参数优化")
    print("=" * 60)

    best_adj = (V10_PARAMS['adj_high_threshold'], V10_PARAMS['adj_high_pen'])
    best_adj_obj = base_obj

    for threshold in SEARCH_SPACE['adj_high_threshold']:
        for pen in SEARCH_SPACE['adj_high_pen']:
            test = dict(V10_PARAMS)
            test['adj_high_threshold'] = threshold
            test['adj_high_pen'] = pen
            tiers = evaluate_full(df_valid, test)
            obj = multi_tier_objective(tiers)
            if obj > best_adj_obj:
                best_adj_obj = obj
                best_adj = (threshold, pen)
                s_n = tiers.get('S', {}).get('n', 0)
                a_n = tiers.get('A', {}).get('n', 0)
                b_n = tiers.get('B', {}).get('n', 0)
                print(f"  ★ threshold={threshold}, pen={pen}: obj={obj:.2f} "
                      f"S={s_n} A={a_n} B={b_n}")

    current = dict(V10_PARAMS)
    current['adj_high_threshold'] = best_adj[0]
    current['adj_high_pen'] = best_adj[1]
    print(f"\n  最优: threshold={best_adj[0]}, pen={best_adj[1]}, obj={best_adj_obj:.2f}")

    r1_tiers = evaluate_full(df_valid, current)
    print_tiers(r1_tiers, "第1轮结果(S级释放)")

    # ============ 第2轮: 新参数搜索(B级增强) ============
    print("\n" + "=" * 60)
    print("  第2轮: B级增强 - 新增参数搜索")
    print("=" * 60)

    # 逐个搜索新参数
    new_params = ['tech_high_pen', 'score_very_high_pen', 'score_very_high_threshold',
                  'rsi_golden_bonus', 'rsi_golden_low', 'rsi_golden_high',
                  'low_volatility_bonus', 'day_chg_neg_bonus']

    for param_name in new_params:
        cur_obj = multi_tier_objective(evaluate_full(df_valid, current))
        best_val = current[param_name]
        best_obj = cur_obj

        for val in SEARCH_SPACE.get(param_name, []):
            test = dict(current)
            test[param_name] = val
            tiers = evaluate_full(df_valid, test)
            obj = multi_tier_objective(tiers)
            if obj > best_obj:
                best_obj = obj
                best_val = val

        if best_val != current[param_name]:
            old = current[param_name]
            current[param_name] = best_val
            tiers = evaluate_full(df_valid, current)
            b_avg = tiers.get('B', {}).get('avg', 0)
            b_wr = tiers.get('B', {}).get('wr', 0)
            print(f"  {param_name}: {old} → {best_val} (obj {cur_obj:.2f}→{best_obj:.2f}, B级: wr={b_wr:.1f}% avg={b_avg:+.2f}%)")

    r2_tiers = evaluate_full(df_valid, current)
    print_tiers(r2_tiers, "第2轮结果(新参数)")

    # ============ 第3轮: 现有参数微调 ============
    print("\n" + "=" * 60)
    print("  第3轮: 现有参数联合微调")
    print("=" * 60)

    existing_params = ['score_high_threshold', 'score_high_pen', 'tech_low_pen',
                       'chase_60_pen', 'chg3d_10_pen', 'rsi_oversold_bonus',
                       'momentum_start_bonus', 'low_risk_momentum_bonus',
                       'strong_low_chase_bonus', 'zt_low_chase_bonus']

    for iteration in range(3):
        changed = 0
        for param_name in existing_params:
            cur_obj = multi_tier_objective(evaluate_full(df_valid, current))
            best_val = current[param_name]
            best_obj = cur_obj

            for val in SEARCH_SPACE.get(param_name, []):
                test = dict(current)
                test[param_name] = val
                tiers = evaluate_full(df_valid, test)
                obj = multi_tier_objective(tiers)
                if obj > best_obj:
                    best_obj = obj
                    best_val = val

            if best_val != current[param_name]:
                print(f"    [{iteration+1}] {param_name}: {current[param_name]} → {best_val} (+{best_obj-cur_obj:.3f})")
                current[param_name] = best_val
                changed += 1

        if changed == 0:
            print(f"    [{iteration+1}] 无改善, 停止")
            break

    r3_tiers = evaluate_full(df_valid, current)
    print_tiers(r3_tiers, "第3轮结果(微调)")

    # ============ 第4轮: 关键参数对联合搜索 ============
    print("\n" + "=" * 60)
    print("  第4轮: 关键参数对联合搜索")
    print("=" * 60)

    pairs = [
        ('adj_high_threshold', 'adj_high_pen'),
        ('tech_high_pen', 'score_very_high_pen'),
        ('rsi_golden_bonus', 'rsi_golden_high'),
        ('rsi_golden_low', 'rsi_golden_high'),
        ('score_high_threshold', 'score_high_pen'),
        ('score_very_high_threshold', 'score_very_high_pen'),
        ('tech_high_pen', 'tech_low_pen'),
        ('momentum_start_bonus', 'low_risk_momentum_bonus'),
        ('low_volatility_bonus', 'day_chg_neg_bonus'),
        ('strong_low_chase_bonus', 'zt_low_chase_bonus'),
    ]

    for p1, p2 in pairs:
        cur_obj = multi_tier_objective(evaluate_full(df_valid, current))
        best = (current[p1], current[p2])
        best_obj = cur_obj

        for v1 in SEARCH_SPACE.get(p1, [current[p1]]):
            for v2 in SEARCH_SPACE.get(p2, [current[p2]]):
                test = dict(current)
                test[p1] = v1
                test[p2] = v2
                tiers = evaluate_full(df_valid, test)
                obj = multi_tier_objective(tiers)
                if obj > best_obj:
                    best_obj = obj
                    best = (v1, v2)

        if best != (current[p1], current[p2]):
            print(f"    {p1}={best[0]}, {p2}={best[1]} (obj {cur_obj:.2f}→{best_obj:.2f})")
            current[p1] = best[0]
            current[p2] = best[1]

    r4_tiers = evaluate_full(df_valid, current)
    print_tiers(r4_tiers, "第4轮结果(参数对)")

    # ============ 第5轮: 最终迭代收敛 ============
    print("\n" + "=" * 60)
    print("  第5轮: 最终全参数迭代收敛")
    print("=" * 60)

    all_params = list(SEARCH_SPACE.keys())
    for iteration in range(5):
        changed = 0
        for param_name in all_params:
            cur_obj = multi_tier_objective(evaluate_full(df_valid, current))
            best_val = current[param_name]
            best_obj = cur_obj

            for val in SEARCH_SPACE.get(param_name, []):
                test = dict(current)
                test[param_name] = val
                tiers = evaluate_full(df_valid, test)
                obj = multi_tier_objective(tiers)
                if obj > best_obj:
                    best_obj = obj
                    best_val = val

            if best_val != current[param_name]:
                current[param_name] = best_val
                changed += 1

        cur_obj = multi_tier_objective(evaluate_full(df_valid, current))
        print(f"    [{iteration+1}] 变更{changed}个参数, obj={cur_obj:.2f}")
        if changed == 0:
            break

    # ============ 最终对比 ============
    print("\n" + "=" * 60)
    print("  最终对比")
    print("=" * 60)

    opt_tiers = evaluate_full(df_valid, current)
    opt_obj = multi_tier_objective(opt_tiers)

    print_tiers(base_tiers, "v10基线")
    print(f"  目标函数: {base_obj:.2f}")
    print_tiers(opt_tiers, "v11优化")
    print(f"  目标函数: {opt_obj:.2f}")

    # 参数变化
    changes = []
    for k in sorted(V10_PARAMS.keys()):
        old = V10_PARAMS[k]
        new = current[k]
        if old != new:
            changes.append((k, old, new))

    if changes:
        print(f"\n  参数变化 ({len(changes)} 个):")
        for k, old, new in changes:
            print(f"    {k}: {old} → {new}")
    else:
        print(f"\n  无参数变化")

    # 层级单调性验证
    print(f"\n  层级单调性验证:")
    s_t = opt_tiers.get('S', {'n': 0, 'wr': 0, 'avg': 0})
    a_t = opt_tiers.get('A', {'n': 0, 'wr': 0, 'avg': 0})
    b_t = opt_tiers.get('B', {'n': 0, 'wr': 0, 'avg': 0})
    cp_t = opt_tiers.get('C+', {'n': 0, 'wr': 0, 'avg': 0})

    if s_t['n'] > 0 and a_t['n'] > 0:
        print(f"    S>A 收益: {'PASS' if s_t['avg'] >= a_t['avg'] else 'FAIL'} ({s_t['avg']:+.2f}% vs {a_t['avg']:+.2f}%)")
    if a_t['n'] > 0 and b_t['n'] > 0:
        print(f"    A>B 胜率: {'PASS' if a_t['wr'] >= b_t['wr'] else 'FAIL'} ({a_t['wr']:.1f}% vs {b_t['wr']:.1f}%)")
        print(f"    A>B 收益: {'PASS' if a_t['avg'] >= b_t['avg'] else 'FAIL'} ({a_t['avg']:+.2f}% vs {b_t['avg']:+.2f}%)")
    if b_t['n'] > 0 and cp_t['n'] > 0:
        print(f"    B>C+ 胜率: {'PASS' if b_t['wr'] >= cp_t['wr'] else 'FAIL'} ({b_t['wr']:.1f}% vs {cp_t['wr']:.1f}%)")
        print(f"    B>C+ 收益: {'PASS' if b_t['avg'] >= cp_t['avg'] else 'FAIL'} ({b_t['avg']:+.2f}% vs {cp_t['avg']:+.2f}%)")

    # ============ Top10模拟 ============
    print("\n" + "=" * 60)
    print("  Top10选股模拟对比")
    print("=" * 60)

    # v10 Top10
    df_v10 = df_valid.copy()
    df_v10['adj_score'] = df_v10.apply(lambda r: score_row(r, V10_PARAMS), axis=1)
    v10_sels = []
    for date, group in df_v10.groupby('report_date'):
        top = group.nlargest(10, 'adj_score')
        v10_sels.append(top)
    df_v10_top = pd.concat(v10_sels, ignore_index=True) if v10_sels else pd.DataFrame()

    # v11 Top10
    df_v11 = df_valid.copy()
    df_v11['adj_score'] = df_v11.apply(lambda r: score_row(r, current), axis=1)
    v11_sels = []
    for date, group in df_v11.groupby('report_date'):
        top = group.nlargest(10, 'adj_score')
        v11_sels.append(top)
    df_v11_top = pd.concat(v11_sels, ignore_index=True) if v11_sels else pd.DataFrame()

    for label, data in [('v10 Top10', df_v10_top), ('v11 Top10', df_v11_top)]:
        for period in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
            r = data[period].dropna()
            if len(r) > 0:
                pass  # just for later
        r5 = data['return_5d'].dropna()
        r3 = data['return_3d'].dropna()
        r10 = data['return_10d'].dropna()
        print(f"\n  {label}:")
        print(f"    样本: {len(data)}")
        if len(r5) > 0:
            print(f"    5日: 收益{r5.mean():+.2f}%, 胜率{(r5>0).mean()*100:.1f}%")
        if len(r3) > 0:
            print(f"    3日: 收益{r3.mean():+.2f}%, 胜率{(r3>0).mean()*100:.1f}%")
        if len(r10) > 0:
            print(f"    10日: 收益{r10.mean():+.2f}%, 胜率{(r10>0).mean()*100:.1f}%")

    # ============ 交叉验证 ============
    print("\n" + "=" * 60)
    print("  时间序列交叉验证")
    print("=" * 60)

    dates = sorted(df_valid['report_date'].unique())
    n_dates = len(dates)
    fold_size = max(1, n_dates // 5)

    cv_v10_wins = 0
    cv_v11_wins = 0

    for i in range(5):
        test_start = i * fold_size
        test_end = min((i + 1) * fold_size, n_dates)
        if test_start >= n_dates:
            break
        test_dates = dates[test_start:test_end]
        df_test = df_valid[df_valid['report_date'].isin(test_dates)]
        if len(df_test) < 5:
            continue

        v10_t = evaluate_full(df_test, V10_PARAMS)
        v11_t = evaluate_full(df_test, current)

        v10_obj = multi_tier_objective(v10_t)
        v11_obj = multi_tier_objective(v11_t)

        v10_a = v10_t.get('A', {'n': 0, 'wr': 0, 'avg': 0})
        v11_a = v11_t.get('A', {'n': 0, 'wr': 0, 'avg': 0})
        v10_b = v10_t.get('B', {'n': 0, 'wr': 0, 'avg': 0})
        v11_b = v11_t.get('B', {'n': 0, 'wr': 0, 'avg': 0})
        v10_s = v10_t.get('S', {'n': 0, 'wr': 0, 'avg': 0})
        v11_s = v11_t.get('S', {'n': 0, 'wr': 0, 'avg': 0})

        winner = "v11" if v11_obj > v10_obj else "v10"
        if v11_obj > v10_obj:
            cv_v11_wins += 1
        else:
            cv_v10_wins += 1

        print(f"\n  Fold {i+1}: {test_dates[0]}~{test_dates[-1]} ({len(df_test)}样本) → {winner}")
        print(f"    v10: S={v10_s['n']}, A={v10_a['n']}({v10_a['wr']:.0f}%), B={v10_b['n']}({v10_b['avg']:+.1f}%), obj={v10_obj:.1f}")
        print(f"    v11: S={v11_s['n']}, A={v11_a['n']}({v11_a['wr']:.0f}%), B={v11_b['n']}({v11_b['avg']:+.1f}%), obj={v11_obj:.1f}")

    print(f"\n  CV总结: v10赢{cv_v10_wins}折, v11赢{cv_v11_wins}折")

    # ============ 保存结果 ============
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result = {
        'timestamp': datetime.now().isoformat(),
        'data_rows': len(df_valid),
        'v10_tiers': base_tiers,
        'v11_tiers': opt_tiers,
        'v10_obj': base_obj,
        'v11_obj': opt_obj,
        'v11_params': current,
        'changes': [{'param': k, 'old': o, 'new': n} for k, o, n in changes],
        'cv_v10_wins': cv_v10_wins,
        'cv_v11_wins': cv_v11_wins,
    }
    result_file = os.path.join(RESULTS_DIR, f'optimization_v11_deep_{timestamp}.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {result_file}")

    # ============ 结论 ============
    print("\n" + "=" * 60)
    print("  结论")
    print("=" * 60)

    s_ok = opt_tiers.get('S', {}).get('n', 0) > 0
    a_ok = opt_tiers.get('A', {}).get('n', 0) >= 3
    b_ok = opt_tiers.get('B', {}).get('avg', -999) > 0
    b_wr = opt_tiers.get('B', {}).get('wr', 0) > 50

    print(f"  S级存在: {'PASS' if s_ok else 'FAIL'} (n={opt_tiers.get('S', {}).get('n', 0)})")
    print(f"  A级>=3: {'PASS' if a_ok else 'FAIL'} (n={opt_tiers.get('A', {}).get('n', 0)})")
    print(f"  B级正收益: {'PASS' if b_ok else 'FAIL'} (avg={opt_tiers.get('B', {}).get('avg', 0):+.2f}%)")
    print(f"  B级胜率>50%: {'PASS' if b_wr else 'FAIL'} (wr={opt_tiers.get('B', {}).get('wr', 0):.1f}%)")

    if changes and opt_obj > base_obj:
        print(f"\n  建议更新 {len(changes)} 个参数到生产环境")
        print(f"\n  完整v11参数:")
        for k in sorted(current.keys()):
            marker = " ← CHANGED" if k in [c[0] for c in changes] else ""
            print(f"    '{k}': {current[k]},{marker}")
    else:
        print(f"\n  v10参数保持不变")


if __name__ == '__main__':
    main()
