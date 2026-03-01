#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v10 多层级平衡优化
==================
问题诊断: score_high_threshold=70 导致A级过少(n=1), B级收益差
目标: 同时优化A/B/C三个层级的表现, 确保:
  1. A级数量 >= 3, 胜率 >= 80%
  2. B级平均收益 > 0, 胜率 > 45%
  3. 层级单调: A > B > C (胜率和收益)
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

# v9参数 (v10有争议的变更暂时回退)
V9_PARAMS = {
    'rsi_85_pen': 25, 'rsi_80_pen': 15, 'rsi_75_pen': 3,
    'day_chg_20_pen': 25, 'zt_chase_pen': 12, 'zt_signal_pen': 14,
    'zt_base_pen': 3, 'chg7_pen': 3, 'chg5_pen': 5,
    'chg5d_18_pen': 25, 'chg3d_20_pen': 20, 'chg3d_15_pen': 16, 'chg3d_10_pen': 12,
    'chase_80_pen': 20, 'chase_60_pen': 6,
    'tech_low_pen': 15, 'sector_hot_pen': 4, 'sector_dead_pen': 11,
    'score_high_threshold': 72, 'score_high_pen': 19,
    'rsi80_3d10_pen': 10, 'chg5d15_rsi72_pen': 10,
    'signal_crowd_pen': 1, 'sell_dom_pen': 0, 'sell_abs_pen': 0,
    'chase_rsi_combo_pen': 3,
    'rsi_oversold_bonus': 9, 'buy_dominance_bonus': 5,
    'zt_low_chase_bonus': 10, 'strong_low_chase_bonus': 15,
    'momentum_start_bonus': 5, 'quant_moderate_bonus': 0,
    'low_risk_momentum_bonus': 3,
    'sweet_low': 63, 'sweet_high': 69, 'sweet_bonus': 5,
    'adj_high_threshold': 79, 'adj_high_pen': 8,
}


def score_row(row, params):
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
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            avg = r5.mean()
            losses = r5[r5 < 0]
            pf = abs(r5[r5 > 0].sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 999
        else:
            wr = 0; avg = 0; pf = 0
        tiers[name] = {'n': len(r5), 'wr': wr, 'avg': avg, 'pf': pf}

    return tiers


def multi_tier_objective(tiers, min_a=3, min_b=10):
    """多层级目标函数
    同时考虑:
    - A级质量 (胜率, 收益, 盈亏比)
    - B级表现 (收益需为正)
    - 层级单调性 (A>B>C)
    - A级数量不能太少
    """
    a = tiers.get('A', {'n': 0, 'wr': 0, 'avg': 0})
    b = tiers.get('B', {'n': 0, 'wr': 0, 'avg': 0})
    cp = tiers.get('C+', {'n': 0, 'wr': 0, 'avg': 0})
    c = tiers.get('C', {'n': 0, 'wr': 0, 'avg': 0})

    score = 0

    # A级质量 (权重40%)
    if a['n'] >= min_a:
        a_score = a['wr'] * 0.3 + a['avg'] * 0.5 + min(a['n'], 20) * 0.5
        score += a_score * 0.4
    elif a['n'] > 0:
        # A级太少, 打折
        a_score = a['wr'] * 0.3 + a['avg'] * 0.5
        score += a_score * 0.2  # 半折
    else:
        score -= 20  # 无A级, 大幅扣分

    # B级质量 (权重35%)
    if b['n'] >= min_b:
        b_score = b['wr'] * 0.2 + b['avg'] * 0.3 + min(b['n'], 50) * 0.1
        score += b_score * 0.35
    elif b['n'] > 0:
        b_score = b['wr'] * 0.2 + b['avg'] * 0.3
        score += b_score * 0.15

    # 层级单调性奖励 (权重15%)
    monotonic = 0
    if a['n'] > 0 and b['n'] > 0:
        if a['wr'] > b['wr']: monotonic += 5
        if a['avg'] > b['avg']: monotonic += 5
    if b['n'] > 0 and cp['n'] > 0:
        if b['wr'] > cp['wr']: monotonic += 3
        if b['avg'] > cp['avg']: monotonic += 3
    score += monotonic * 0.15

    # B级正收益奖励 (权重10%)
    if b['n'] >= min_b and b['avg'] > 0:
        score += min(b['avg'] * 2, 10) * 0.10
    elif b['n'] >= min_b and b['avg'] < -1:
        score -= 5  # B级亏损, 扣分

    return score


SEARCH_SPACE = {
    'rsi_85_pen': [20, 25, 30],
    'rsi_80_pen': [10, 15, 20],
    'rsi_75_pen': [0, 3, 5, 8],
    'zt_chase_pen': [8, 10, 12, 15],
    'zt_signal_pen': [10, 12, 14, 18],
    'zt_base_pen': [0, 3, 5],
    'chg7_pen': [0, 3, 5],
    'chg5_pen': [0, 3, 5, 8],
    'chg5d_18_pen': [15, 20, 25, 30],
    'chg3d_20_pen': [10, 15, 20, 25],
    'chg3d_15_pen': [8, 12, 16, 20, 25],
    'chg3d_10_pen': [5, 8, 12, 15],
    'chase_80_pen': [10, 15, 20, 25],
    'chase_60_pen': [3, 5, 6, 8, 10],
    'tech_low_pen': [5, 10, 15, 20],
    'sector_hot_pen': [0, 4, 5, 8, 10],
    'sector_dead_pen': [3, 5, 8, 11, 15],
    'score_high_threshold': [70, 72, 74, 76],
    'score_high_pen': [10, 12, 15, 19, 22],
    'rsi80_3d10_pen': [0, 5, 10, 15],
    'chg5d15_rsi72_pen': [0, 5, 10, 15],
    'signal_crowd_pen': [0, 1, 3, 5],
    'sell_dom_pen': [0, 3, 5],
    'sell_abs_pen': [0, 3, 5],
    'chase_rsi_combo_pen': [0, 2, 3, 5],
    'rsi_oversold_bonus': [0, 5, 8, 9, 12],
    'buy_dominance_bonus': [0, 3, 5, 8],
    'zt_low_chase_bonus': [0, 5, 10, 15],
    'strong_low_chase_bonus': [0, 5, 10, 15, 20],
    'momentum_start_bonus': [0, 3, 5, 8],
    'quant_moderate_bonus': [0, 2, 3, 5],
    'low_risk_momentum_bonus': [0, 2, 3, 5, 8],
    'sweet_low': [60, 63, 65, 68],
    'sweet_high': [69, 72, 75],
    'sweet_bonus': [0, 3, 5, 8],
    'adj_high_threshold': [76, 78, 79, 82, 85],
    'adj_high_pen': [5, 8, 10, 12],
}


def print_tiers(tiers, label=""):
    if label:
        print(f"\n  {label}:")
    print(f"  {'评级':>6} | {'数量':>5} | {'胜率':>7} | {'平均5d收益':>10} | {'盈亏比':>6}")
    print("  " + "-" * 50)
    for name in ['S', 'A', 'B', 'C+', 'C']:
        t = tiers.get(name, {'n': 0, 'wr': 0, 'avg': 0, 'pf': 0})
        if t['n'] > 0:
            pf_str = f"{t['pf']:.2f}" if t['pf'] < 100 else "∞"
            print(f"  {name:>6} | {t['n']:>5} | {t['wr']:>6.1f}% | {t['avg']:>+9.2f}% | {pf_str:>6}")
        else:
            print(f"  {name:>6} | {t['n']:>5} | {'—':>7} | {'—':>10} | {'—':>6}")


def main():
    print("=" * 70)
    print("  v10 多层级平衡优化")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 加载数据
    csv_files = sorted([f for f in os.listdir(RESULTS_DIR)
                        if f.startswith('backtest_rebuilt_') and f.endswith('.csv')])
    csv_path = os.path.join(RESULTS_DIR, csv_files[-1])
    df = pd.read_csv(csv_path)
    df_valid = df[df['return_5d'].notna()].copy()
    print(f"\n  有效数据: {len(df_valid)} 行, {df_valid['report_date'].nunique()} 天")

    # 基线评估
    base_tiers = evaluate_full(df_valid, V9_PARAMS)
    base_obj = multi_tier_objective(base_tiers)
    print_tiers(base_tiers, "v9基线")
    print(f"  多层级目标函数: {base_obj:.2f}")

    # ============ 第1轮: 逐参数扫描 ============
    print("\n" + "=" * 60)
    print("  第1轮: 逐参数敏感度扫描 (多层级目标)")
    print("=" * 60)

    improvements = {}
    for param_name, values in SEARCH_SPACE.items():
        best_val = V9_PARAMS[param_name]
        best_obj = base_obj

        for val in values:
            if val == V9_PARAMS[param_name]:
                continue
            test = dict(V9_PARAMS)
            test[param_name] = val
            tiers = evaluate_full(df_valid, test)
            obj = multi_tier_objective(tiers)
            if obj > best_obj:
                best_obj = obj
                best_val = val

        if best_val != V9_PARAMS[param_name]:
            improvements[param_name] = {
                'old': V9_PARAMS[param_name],
                'new': best_val,
                'improvement': best_obj - base_obj
            }

    sorted_impr = sorted(improvements.items(), key=lambda x: -x[1]['improvement'])
    print(f"\n  发现 {len(sorted_impr)} 个可改善参数:")
    for name, info in sorted_impr[:20]:
        print(f"    {name}: {info['old']} → {info['new']} (+{info['improvement']:.3f})")

    # ============ 第2轮: 迭代优化 ============
    print("\n" + "=" * 60)
    print("  第2轮: 迭代逐参数优化")
    print("=" * 60)

    current = dict(V9_PARAMS)
    for iteration in range(5):
        changed = 0
        cur_tiers = evaluate_full(df_valid, current)
        cur_obj = multi_tier_objective(cur_tiers)

        for param_name, _ in sorted_impr:
            values = SEARCH_SPACE.get(param_name, [])
            best_val = current[param_name]
            best_obj = cur_obj

            for val in values:
                test = dict(current)
                test[param_name] = val
                tiers = evaluate_full(df_valid, test)
                obj = multi_tier_objective(tiers)
                if obj > best_obj:
                    best_obj = obj
                    best_val = val

            if best_val != current[param_name]:
                print(f"    [{iteration+1}] {param_name}: {current[param_name]} → {best_val} "
                      f"(obj {cur_obj:.2f} → {best_obj:.2f})")
                current[param_name] = best_val
                cur_obj = best_obj
                changed += 1

        if changed == 0:
            print(f"    [{iteration+1}] 无改善, 停止")
            break

    r2_tiers = evaluate_full(df_valid, current)
    r2_obj = multi_tier_objective(r2_tiers)
    print_tiers(r2_tiers, "第2轮结果")
    print(f"  目标函数: {r2_obj:.2f}")

    # ============ 第3轮: 关键参数对搜索 ============
    print("\n" + "=" * 60)
    print("  第3轮: 关键参数对联合搜索")
    print("=" * 60)

    pairs = [
        ('score_high_threshold', 'score_high_pen'),
        ('sweet_low', 'sweet_high'),
        ('sweet_high', 'sweet_bonus'),
        ('adj_high_threshold', 'adj_high_pen'),
        ('chase_80_pen', 'chase_60_pen'),
        ('chg3d_15_pen', 'chg3d_10_pen'),
        ('sector_hot_pen', 'sector_dead_pen'),
        ('zt_chase_pen', 'zt_signal_pen'),
        ('rsi_80_pen', 'rsi_75_pen'),
        ('momentum_start_bonus', 'strong_low_chase_bonus'),
        ('buy_dominance_bonus', 'signal_crowd_pen'),
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
            print(f"    {p1}={best[0]}, {p2}={best[1]} (obj {cur_obj:.2f} → {best_obj:.2f})")
            current[p1] = best[0]
            current[p2] = best[1]

    r3_tiers = evaluate_full(df_valid, current)
    r3_obj = multi_tier_objective(r3_tiers)
    print_tiers(r3_tiers, "第3轮结果")

    # ============ 最终对比 ============
    print("\n" + "=" * 60)
    print("  最终对比")
    print("=" * 60)

    opt_tiers = evaluate_full(df_valid, current)
    opt_obj = multi_tier_objective(opt_tiers)

    print_tiers(base_tiers, "v9基线")
    print(f"  目标函数: {base_obj:.2f}")
    print_tiers(opt_tiers, "v10优化")
    print(f"  目标函数: {opt_obj:.2f}")

    # 参数变化
    changes = []
    for k in sorted(V9_PARAMS.keys()):
        old = V9_PARAMS[k]
        new = current[k]
        if old != new:
            changes.append((k, old, new))

    if changes:
        print(f"\n  参数变化 ({len(changes)} 个):")
        for k, old, new in changes:
            print(f"    {k}: {old} → {new}")
    else:
        print(f"\n  无参数变化")

    # 单调性验证
    print(f"\n  层级单调性验证:")
    a, b, cp = opt_tiers.get('A', {}), opt_tiers.get('B', {}), opt_tiers.get('C+', {})
    checks = []
    if a.get('n', 0) > 0 and b.get('n', 0) > 0:
        wr_ok = a['wr'] >= b['wr']
        avg_ok = a['avg'] >= b['avg']
        checks.append(f"    A>B 胜率: {'PASS' if wr_ok else 'FAIL'} ({a['wr']:.1f}% vs {b['wr']:.1f}%)")
        checks.append(f"    A>B 收益: {'PASS' if avg_ok else 'FAIL'} ({a['avg']:+.2f}% vs {b['avg']:+.2f}%)")
    if b.get('n', 0) > 0 and cp.get('n', 0) > 0:
        wr_ok = b['wr'] >= cp['wr']
        avg_ok = b['avg'] >= cp['avg']
        checks.append(f"    B>C+ 胜率: {'PASS' if wr_ok else 'FAIL'} ({b['wr']:.1f}% vs {cp['wr']:.1f}%)")
        checks.append(f"    B>C+ 收益: {'PASS' if avg_ok else 'FAIL'} ({b['avg']:+.2f}% vs {cp['avg']:+.2f}%)")
    for c in checks:
        print(c)

    # 交叉验证
    print("\n" + "=" * 60)
    print("  时间序列交叉验证")
    print("=" * 60)

    dates = sorted(df_valid['report_date'].unique())
    n_dates = len(dates)
    fold_size = max(1, n_dates // 5)
    cv_results = {'v9': [], 'v10': []}

    for i in range(5):
        test_start = i * fold_size
        test_end = min((i + 1) * fold_size, n_dates)
        if test_start >= n_dates:
            break
        test_dates = dates[test_start:test_end]
        df_test = df_valid[df_valid['report_date'].isin(test_dates)]
        if len(df_test) < 5:
            continue

        v9_t = evaluate_full(df_test, V9_PARAMS)
        v10_t = evaluate_full(df_test, current)

        v9_a = v9_t.get('A', {'n': 0, 'wr': 0, 'avg': 0})
        v10_a = v10_t.get('A', {'n': 0, 'wr': 0, 'avg': 0})
        v9_b = v9_t.get('B', {'n': 0, 'wr': 0, 'avg': 0})
        v10_b = v10_t.get('B', {'n': 0, 'wr': 0, 'avg': 0})

        print(f"\n  Fold {i+1}: {test_dates[0]}~{test_dates[-1]} ({len(df_test)}样本)")
        print(f"    v9  A: n={v9_a['n']}, wr={v9_a['wr']:.0f}%, avg={v9_a['avg']:+.1f}% | "
              f"B: n={v9_b['n']}, wr={v9_b['wr']:.0f}%, avg={v9_b['avg']:+.1f}%")
        print(f"    v10 A: n={v10_a['n']}, wr={v10_a['wr']:.0f}%, avg={v10_a['avg']:+.1f}% | "
              f"B: n={v10_b['n']}, wr={v10_b['wr']:.0f}%, avg={v10_b['avg']:+.1f}%")

        cv_results['v9'].append({'a': v9_a, 'b': v9_b})
        cv_results['v10'].append({'a': v10_a, 'b': v10_b})

    # 汇总
    v9_a_total = sum(f['a']['n'] for f in cv_results['v9'])
    v10_a_total = sum(f['a']['n'] for f in cv_results['v10'])
    v9_b_total = sum(f['b']['n'] for f in cv_results['v9'])
    v10_b_total = sum(f['b']['n'] for f in cv_results['v10'])

    print(f"\n  CV汇总: v9 A总={v9_a_total}, B总={v9_b_total} | v10 A总={v10_a_total}, B总={v10_b_total}")

    # 保存
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result = {
        'timestamp': datetime.now().isoformat(),
        'data_rows': len(df_valid),
        'v9_tiers': base_tiers,
        'v10_tiers': opt_tiers,
        'v9_obj': base_obj,
        'v10_obj': opt_obj,
        'v10_params': current,
        'changes': [{'param': k, 'old': o, 'new': n} for k, o, n in changes],
    }
    result_file = os.path.join(RESULTS_DIR, f'optimization_v10_balanced_{timestamp}.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  结果已保存: {result_file}")

    # 最终建议
    print("\n" + "=" * 60)
    print("  结论")
    print("=" * 60)
    a_ok = opt_tiers.get('A', {}).get('n', 0) >= 3
    b_ok = opt_tiers.get('B', {}).get('avg', -999) > 0
    mono = True
    a_t = opt_tiers.get('A', {'wr': 0, 'avg': 0, 'n': 0})
    b_t = opt_tiers.get('B', {'wr': 0, 'avg': 0, 'n': 0})
    if a_t['n'] > 0 and b_t['n'] > 0:
        mono = a_t['wr'] >= b_t['wr'] and a_t['avg'] >= b_t['avg']

    print(f"  A级数量>=3: {'PASS' if a_ok else 'FAIL'} (n={opt_tiers.get('A', {}).get('n', 0)})")
    print(f"  B级正收益: {'PASS' if b_ok else 'FAIL'} (avg={opt_tiers.get('B', {}).get('avg', 0):+.2f}%)")
    print(f"  层级单调: {'PASS' if mono else 'FAIL'}")

    if changes and opt_obj > base_obj:
        print(f"\n  建议更新 {len(changes)} 个参数")
    else:
        print(f"\n  v9参数保持不变")


if __name__ == '__main__':
    main()
