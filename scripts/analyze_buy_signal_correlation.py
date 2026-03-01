#!/usr/bin/env python3
"""
分析量化买入信号数量与胜率/收益的相关性
自动回测是否应该提高买入信号的分值占比

分析维度:
1. buy_signals 分箱统计: 不同买入信号数量区间的胜率和平均收益
2. 相关性分析: buy_signals 与 return_5d 的统计相关性
3. 回测不同的买入信号奖励策略: 测试增加 buy_signal bonus 的效果
4. 与其他特征对比: buy_signals vs RSI/chase_risk/sector_score 的预测力
5. 交叉分析: buy_signals + 其他因子的组合效果
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime
from copy import deepcopy

# 项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(PROJECT_ROOT, 'results')

# ========== v9优化后参数 ==========
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
    # 新增: 买入信号奖励参数 (初始为0, 待优化)
    'buy_sig_5_bonus': 0,    # buy_sig >= 5 奖励
    'buy_sig_8_bonus': 0,    # buy_sig >= 8 奖励
    'buy_sig_10_bonus': 0,   # buy_sig >= 10 奖励
    'buy_sig_12_bonus': 0,   # buy_sig >= 12 奖励
    'buy_sig_15_bonus': 0,   # buy_sig >= 15 奖励
    'buy_ratio_bonus': 0,    # buy/(buy+sell) > 0.7 奖励
}


def score_row(row, params):
    """参数化评分 (与rebuild_and_optimize.py一致 + 新增买入信号奖励)"""
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

    # RSI惩罚
    if pd.notna(rsi):
        if rsi >= 85: penalty += params['rsi_85_pen']
        elif rsi > 80: penalty += params['rsi_80_pen']
        elif rsi > 75: penalty += params['rsi_75_pen']

    # 日涨幅
    if pd.notna(day_chg):
        if day_chg >= 20: penalty += params['day_chg_20_pen']
        elif day_chg >= 9.5:
            if pd.notna(chase) and chase >= 50: penalty += params['zt_chase_pen']
            elif pd.notna(buy_sig) and buy_sig > 8: penalty += params['zt_signal_pen']
            else: penalty += params['zt_base_pen']
        elif day_chg >= 7: penalty += params['chg7_pen']
        elif day_chg >= 5: penalty += params['chg5_pen']

    # 短期涨幅
    if pd.notna(chg_5d) and chg_5d > 18: penalty += params['chg5d_18_pen']
    if pd.notna(chg_3d):
        if chg_3d > 20: penalty += params['chg3d_20_pen']
        elif chg_3d > 15: penalty += params['chg3d_15_pen']
        elif chg_3d > 10: penalty += params['chg3d_10_pen']

    # 追高
    if pd.notna(chase):
        if chase >= 80: penalty += params['chase_80_pen']
        elif chase >= 60: penalty += params['chase_60_pen']

    # 技术面低
    if pd.notna(tech) and tech < 60:
        has_exempt = False
        if pd.notna(day_chg) and 9.5 <= day_chg < 20:
            if pd.notna(chase) and chase < 50 and pd.notna(buy_sig) and buy_sig <= 8:
                has_exempt = True
        if pd.notna(day_chg) and 3 <= day_chg < 10:
            if pd.notna(chase) and chase < 50 and pd.notna(qs) and 55 <= qs <= 80:
                has_exempt = True
        if not has_exempt: penalty += params['tech_low_pen']

    # 板块
    if pd.notna(sector):
        if sector >= 95: penalty += params['sector_hot_pen']
        elif 60 <= sector < 75: penalty += params['sector_dead_pen']

    # 原始评分过高
    if score >= params['score_high_threshold']: penalty += params['score_high_pen']

    # 组合风险
    if pd.notna(rsi) and pd.notna(chg_3d) and rsi > 80 and chg_3d > 10: penalty += params['rsi80_3d10_pen']
    if pd.notna(chg_5d) and pd.notna(rsi) and chg_5d > 15 and rsi > 72: penalty += params['chg5d15_rsi72_pen']

    # 信号拥挤
    if pd.notna(buy_sig) and buy_sig >= 15: penalty += params['signal_crowd_pen']

    # 卖出信号
    if pd.notna(sell_sig) and pd.notna(buy_sig) and sell_sig > buy_sig: penalty += params['sell_dom_pen']
    if pd.notna(sell_sig) and sell_sig >= 5: penalty += params['sell_abs_pen']

    # 追高超买组合
    if pd.notna(chase) and pd.notna(rsi) and chase > 30 and rsi > 60: penalty += params['chase_rsi_combo_pen']

    # === 原有奖励 ===
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

    # === 新增: 买入信号数量奖励 ===
    if pd.notna(buy_sig):
        if buy_sig >= 15: bonus += params.get('buy_sig_15_bonus', 0)
        elif buy_sig >= 12: bonus += params.get('buy_sig_12_bonus', 0)
        elif buy_sig >= 10: bonus += params.get('buy_sig_10_bonus', 0)
        elif buy_sig >= 8: bonus += params.get('buy_sig_8_bonus', 0)
        elif buy_sig >= 5: bonus += params.get('buy_sig_5_bonus', 0)

    # 买入比例奖励
    if pd.notna(buy_sig) and pd.notna(sell_sig):
        total = buy_sig + sell_sig
        if total > 0 and buy_sig / total > 0.7:
            bonus += params.get('buy_ratio_bonus', 0)

    # 计算
    adj = max(0, score - penalty + bonus)
    if params['sweet_low'] <= adj <= params['sweet_high']: adj += params['sweet_bonus']
    if adj >= params['adj_high_threshold']: adj -= params['adj_high_pen']
    return adj


def evaluate(df, params, threshold=78, top_n=10):
    """评估参数组合"""
    df = df.copy()
    df['adj_score'] = df.apply(lambda r: score_row(r, params), axis=1)
    high = df[df['adj_score'] >= threshold]
    r5_high = high['return_5d'].dropna()

    top_selections = []
    for date, group in df.groupby('report_date'):
        top = group.nlargest(top_n, 'adj_score')
        top_selections.append(top)
    df_top = pd.concat(top_selections) if top_selections else pd.DataFrame()
    r5_top = df_top['return_5d'].dropna()

    result = {}
    if len(r5_high) > 0:
        result['wr'] = (r5_high > 0).mean() * 100
        result['avg'] = r5_high.mean()
        result['n'] = len(r5_high)
    else:
        result['wr'] = 0; result['avg'] = 0; result['n'] = 0

    if len(r5_top) > 0:
        result['top_wr'] = (r5_top > 0).mean() * 100
        result['top_avg'] = r5_top.mean()
    else:
        result['top_wr'] = 0; result['top_avg'] = 0

    return result


def objective(result, min_n=5):
    """目标函数"""
    if result['n'] < min_n:
        return -999
    n_weight = min(1.0, np.log(result['n'] + 1) / np.log(50))
    return result['wr'] * 0.5 + result['avg'] * 0.3 + result['top_wr'] * 0.1 + result['top_avg'] * 0.1 * n_weight


def load_data():
    """加载回测数据"""
    csv_path = os.path.join(RESULTS_DIR, 'backtest_rebuilt_20260225_093815.csv')
    df = pd.read_csv(csv_path)
    df_valid = df.dropna(subset=['return_5d'])
    print(f"加载数据: {len(df)} 行, 有return_5d: {len(df_valid)} 行")
    print(f"buy_signals 有效: {df_valid['buy_signals'].notna().sum()}/{len(df_valid)} "
          f"({df_valid['buy_signals'].notna().mean()*100:.1f}%)")
    return df_valid


# ========== 第1部分: 原始相关性分析 ==========

def analyze_raw_correlation(df):
    """分析buy_signals与收益的原始相关性"""
    print("\n" + "=" * 70)
    print("  第1部分: 量化买入信号 vs 5日收益 — 原始相关性分析")
    print("=" * 70)

    df_bs = df[df['buy_signals'].notna()].copy()
    print(f"\n  有buy_signals数据的样本: {len(df_bs)} 行")

    # 基本统计
    corr_pearson = df_bs['buy_signals'].corr(df_bs['return_5d'])
    corr_spearman = df_bs['buy_signals'].corr(df_bs['return_5d'], method='spearman')
    print(f"\n  Pearson相关系数:  {corr_pearson:+.4f}")
    print(f"  Spearman相关系数: {corr_spearman:+.4f}")

    # 分箱统计
    bins = [0, 3, 5, 8, 10, 12, 15, 30]
    labels = ['0-2', '3-4', '5-7', '8-9', '10-11', '12-14', '15+']
    df_bs['bs_bin'] = pd.cut(df_bs['buy_signals'], bins=bins, labels=labels, right=False)

    print(f"\n  {'信号区间':>8} | {'样本数':>6} | {'胜率':>8} | {'平均5d收益':>10} | {'中位数':>8} | {'最大亏损':>8} | {'最大收益':>8}")
    print("  " + "-" * 80)

    bin_stats = []
    for label in labels:
        subset = df_bs[df_bs['bs_bin'] == label]['return_5d']
        if len(subset) == 0:
            continue
        wr = (subset > 0).mean() * 100
        avg = subset.mean()
        med = subset.median()
        mn = subset.min()
        mx = subset.max()
        print(f"  {label:>8} | {len(subset):>6} | {wr:>7.1f}% | {avg:>+9.2f}% | {med:>+7.2f}% | {mn:>+7.2f}% | {mx:>+7.2f}%")
        bin_stats.append({
            'bin': label, 'n': len(subset), 'wr': wr, 'avg': avg,
            'median': med, 'min': mn, 'max': mx
        })

    # 高/低买入信号对比
    low_bs = df_bs[df_bs['buy_signals'] < 5]['return_5d']
    mid_bs = df_bs[(df_bs['buy_signals'] >= 5) & (df_bs['buy_signals'] < 10)]['return_5d']
    high_bs = df_bs[df_bs['buy_signals'] >= 10]['return_5d']

    print(f"\n  汇总对比:")
    print(f"  {'区间':>12} | {'样本':>5} | {'胜率':>8} | {'平均收益':>10}")
    print("  " + "-" * 50)
    for name, s in [('低(<5)', low_bs), ('中(5-9)', mid_bs), ('高(>=10)', high_bs)]:
        if len(s) > 0:
            print(f"  {name:>12} | {len(s):>5} | {(s>0).mean()*100:>7.1f}% | {s.mean():>+9.2f}%")

    # 与其他特征对比预测力
    print(f"\n  各特征与5日收益的相关性对比:")
    features = ['buy_signals', 'rsi', 'chase_risk', 'sector_score', 'quant_score',
                'tech_score', 'sell_signals', 'day_change', 'change_3d', 'change_5d', 'score']
    for feat in features:
        valid = df[[feat, 'return_5d']].dropna()
        if len(valid) > 10:
            pc = valid[feat].corr(valid['return_5d'])
            sc = valid[feat].corr(valid['return_5d'], method='spearman')
            print(f"  {feat:>15}: Pearson={pc:+.4f}, Spearman={sc:+.4f} (n={len(valid)})")

    return bin_stats


# ========== 第2部分: 在v9评分体系下的分析 ==========

def analyze_scored_correlation(df):
    """分析v9评分后, adj_score高分股票中buy_signals的作用"""
    print("\n" + "=" * 70)
    print("  第2部分: v9评分体系下的买入信号效果分析")
    print("=" * 70)

    df = df.copy()
    df['adj_score'] = df.apply(lambda r: score_row(r, V9_PARAMS), axis=1)

    # 按调整后评分分层
    tiers = [
        ('S级(>=85)', df[df['adj_score'] >= 85]),
        ('A级(78-85)', df[(df['adj_score'] >= 78) & (df['adj_score'] < 85)]),
        ('B级(70-78)', df[(df['adj_score'] >= 70) & (df['adj_score'] < 78)]),
        ('C级(<70)', df[df['adj_score'] < 70]),
    ]

    print(f"\n  各评级中 buy_signals 分布:")
    print(f"  {'评级':>12} | {'样本':>5} | {'胜率':>8} | {'平均收益':>10} | {'平均buy_sig':>12} | {'中位buy_sig':>12}")
    print("  " + "-" * 75)
    for tier_name, tier_df in tiers:
        r5 = tier_df['return_5d'].dropna()
        bs = tier_df['buy_signals'].dropna()
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            avg = r5.mean()
            bs_mean = bs.mean() if len(bs) > 0 else 0
            bs_med = bs.median() if len(bs) > 0 else 0
            print(f"  {tier_name:>12} | {len(r5):>5} | {wr:>7.1f}% | {avg:>+9.2f}% | {bs_mean:>11.1f} | {bs_med:>11.1f}")

    # 在B/C级中, 高买入信号是否提升了结果
    for tier_name, tier_df in tiers:
        if len(tier_df) < 10:
            continue
        tier_bs = tier_df[tier_df['buy_signals'].notna()]
        if len(tier_bs) < 10:
            continue
        high_bs = tier_bs[tier_bs['buy_signals'] >= 10]['return_5d'].dropna()
        low_bs = tier_bs[tier_bs['buy_signals'] < 10]['return_5d'].dropna()
        if len(high_bs) > 3 and len(low_bs) > 3:
            print(f"\n  {tier_name}内部 — 高买入信号(>=10) vs 低买入信号(<10):")
            print(f"    高(>=10): n={len(high_bs)}, wr={((high_bs>0).mean()*100):.1f}%, avg={high_bs.mean():+.2f}%")
            print(f"    低(<10):  n={len(low_bs)}, wr={((low_bs>0).mean()*100):.1f}%, avg={low_bs.mean():+.2f}%")


# ========== 第3部分: 买入信号奖励策略回测 ==========

def backtest_buy_signal_strategies(df):
    """回测不同的买入信号奖励策略"""
    print("\n" + "=" * 70)
    print("  第3部分: 买入信号奖励策略回测")
    print("=" * 70)

    # 基线: 当前v9参数
    base_result = evaluate(df, V9_PARAMS)
    base_obj = objective(base_result)
    print(f"\n  v9基线: wr={base_result['wr']:.1f}%, avg={base_result['avg']:+.2f}%, "
          f"n={base_result['n']}, top_wr={base_result['top_wr']:.1f}%, obj={base_obj:.2f}")

    strategies = []

    # 策略1: 阶梯式买入信号奖励
    print(f"\n  --- 策略组A: 不同阶梯奖励幅度 ---")
    ladder_configs = [
        # (name, buy_5, buy_8, buy_10, buy_12, buy_15)
        ('轻量奖励',       2, 3, 4, 5, 3),
        ('中等奖励',       3, 5, 7, 8, 5),
        ('较强奖励',       4, 6, 8, 10, 6),
        ('强奖励',         5, 8, 10, 12, 8),
        ('重奖励',         6, 10, 13, 15, 10),
        ('极强奖励',       8, 12, 15, 18, 12),
        ('仅高信号奖励',   0, 0, 5, 8, 5),
        ('仅超高信号奖励', 0, 0, 0, 8, 10),
        ('低门槛宽奖励',   5, 5, 5, 5, 0),
    ]

    print(f"  {'策略名':>18} | {'wr':>6} | {'avg':>9} | {'n':>4} | {'top_wr':>7} | {'obj':>8} | {'vs基线':>8}")
    print("  " + "-" * 75)

    for name, b5, b8, b10, b12, b15 in ladder_configs:
        test_params = deepcopy(V9_PARAMS)
        test_params['buy_sig_5_bonus'] = b5
        test_params['buy_sig_8_bonus'] = b8
        test_params['buy_sig_10_bonus'] = b10
        test_params['buy_sig_12_bonus'] = b12
        test_params['buy_sig_15_bonus'] = b15
        result = evaluate(df, test_params)
        obj = objective(result)
        delta = obj - base_obj
        print(f"  {name:>18} | {result['wr']:>5.1f}% | {result['avg']:>+8.2f}% | {result['n']:>4} | "
              f"{result['top_wr']:>6.1f}% | {obj:>7.2f} | {delta:>+7.2f}")
        strategies.append({
            'name': f"阶梯-{name}",
            'params': {k: v for k, v in test_params.items() if k.startswith('buy_sig')},
            'result': result, 'obj': obj, 'delta': delta
        })

    # 策略2: 买入比例奖励
    print(f"\n  --- 策略组B: 买入比例(buy/(buy+sell)>70%)奖励 ---")
    ratio_configs = [3, 5, 8, 10, 12, 15]
    print(f"  {'buy_ratio_bonus':>18} | {'wr':>6} | {'avg':>9} | {'n':>4} | {'top_wr':>7} | {'obj':>8} | {'vs基线':>8}")
    print("  " + "-" * 75)

    for bonus in ratio_configs:
        test_params = deepcopy(V9_PARAMS)
        test_params['buy_ratio_bonus'] = bonus
        result = evaluate(df, test_params)
        obj = objective(result)
        delta = obj - base_obj
        print(f"  {bonus:>18} | {result['wr']:>5.1f}% | {result['avg']:>+8.2f}% | {result['n']:>4} | "
              f"{result['top_wr']:>6.1f}% | {obj:>7.2f} | {delta:>+7.2f}")
        strategies.append({
            'name': f"比例奖励-{bonus}",
            'params': {'buy_ratio_bonus': bonus},
            'result': result, 'obj': obj, 'delta': delta
        })

    # 策略3: 提高buy_dominance_bonus
    print(f"\n  --- 策略组C: 提高买入占优奖励(buy>=5且buy>=sell*2) ---")
    dom_configs = [5, 8, 10, 12, 15, 18, 20]
    print(f"  {'buy_dom_bonus':>18} | {'wr':>6} | {'avg':>9} | {'n':>4} | {'top_wr':>7} | {'obj':>8} | {'vs基线':>8}")
    print("  " + "-" * 75)

    for bonus in dom_configs:
        test_params = deepcopy(V9_PARAMS)
        test_params['buy_dominance_bonus'] = bonus
        result = evaluate(df, test_params)
        obj = objective(result)
        delta = obj - base_obj
        print(f"  {bonus:>18} | {result['wr']:>5.1f}% | {result['avg']:>+8.2f}% | {result['n']:>4} | "
              f"{result['top_wr']:>6.1f}% | {obj:>7.2f} | {delta:>+7.2f}")
        strategies.append({
            'name': f"占优奖励-{bonus}",
            'params': {'buy_dominance_bonus': bonus},
            'result': result, 'obj': obj, 'delta': delta
        })

    # 策略4: 降低signal_crowd惩罚 (当前15+才惩罚1分)
    print(f"\n  --- 策略组D: 调整信号拥挤惩罚阈值/力度 ---")
    crowd_configs = [
        ('移除拥挤惩罚', 0, 99),    # 完全不惩罚
        ('拥挤>=20才罚', 1, 20),    # 提高到20
        ('当前(>=15罚1)', 1, 15),   # 现状
        ('拥挤>=15罚3', 3, 15),
        ('拥挤>=12罚5', 5, 12),
    ]
    print(f"  {'策略名':>18} | {'wr':>6} | {'avg':>9} | {'n':>4} | {'top_wr':>7} | {'obj':>8} | {'vs基线':>8}")
    print("  " + "-" * 75)

    for name, pen, threshold in crowd_configs:
        test_params = deepcopy(V9_PARAMS)
        test_params['signal_crowd_pen'] = pen
        # 修改score_row中的阈值需要特殊处理
        test_params['_crowd_threshold'] = threshold
        result = evaluate(df, test_params)
        obj = objective(result)
        delta = obj - base_obj
        print(f"  {name:>18} | {result['wr']:>5.1f}% | {result['avg']:>+8.2f}% | {result['n']:>4} | "
              f"{result['top_wr']:>6.1f}% | {obj:>7.2f} | {delta:>+7.2f}")

    return strategies


# ========== 第4部分: 组合优化搜索 ==========

def optimize_buy_signal_params(df):
    """针对买入信号相关参数进行细粒度优化"""
    print("\n" + "=" * 70)
    print("  第4部分: 买入信号参数组合优化搜索")
    print("=" * 70)

    base_result = evaluate(df, V9_PARAMS)
    base_obj = objective(base_result)

    best_params = deepcopy(V9_PARAMS)
    best_obj = base_obj
    best_result = base_result

    # 搜索空间: 买入信号阶梯奖励
    buy_sig_space = {
        'buy_sig_5_bonus': [0, 2, 3, 4, 5, 6, 8],
        'buy_sig_8_bonus': [0, 3, 5, 6, 8, 10],
        'buy_sig_10_bonus': [0, 3, 5, 7, 8, 10, 12],
        'buy_sig_12_bonus': [0, 5, 8, 10, 12, 15],
        'buy_sig_15_bonus': [0, 3, 5, 8, 10],
    }

    # 同时搜索buy_dominance_bonus和buy_ratio_bonus
    other_space = {
        'buy_dominance_bonus': [3, 5, 8, 10, 12, 15],
        'buy_ratio_bonus': [0, 3, 5, 8, 10, 12],
    }

    total_search = 1
    for vals in buy_sig_space.values():
        total_search *= len(vals)
    for vals in other_space.values():
        total_search *= len(vals)

    print(f"\n  搜索空间: {total_search:,} 组合")
    print(f"  (采用分步优化减少计算量)\n")

    # 第1步: 逐个参数扫描
    print("  步骤1: 逐个参数最优值扫描")
    current_params = deepcopy(V9_PARAMS)
    all_search = {**buy_sig_space, **other_space}

    for iteration in range(3):  # 迭代3轮
        improved_count = 0
        for param_name, values in all_search.items():
            cur_obj = objective(evaluate(df, current_params))
            param_best_val = current_params[param_name]
            param_best_obj = cur_obj

            for val in values:
                test_params = deepcopy(current_params)
                test_params[param_name] = val
                result = evaluate(df, test_params)
                obj = objective(result)
                if obj > param_best_obj:
                    param_best_obj = obj
                    param_best_val = val

            if param_best_val != current_params[param_name]:
                print(f"    [{iteration+1}] {param_name}: {current_params[param_name]} → {param_best_val} "
                      f"(obj: {cur_obj:.2f} → {param_best_obj:.2f})")
                current_params[param_name] = param_best_val
                improved_count += 1

        if improved_count == 0:
            print(f"    [{iteration+1}] 未找到改善, 停止迭代")
            break

    step1_result = evaluate(df, current_params)
    step1_obj = objective(step1_result)
    print(f"\n  步骤1结果: wr={step1_result['wr']:.1f}%, avg={step1_result['avg']:+.2f}%, "
          f"n={step1_result['n']}, obj={step1_obj:.2f} (vs基线 {step1_obj-base_obj:+.2f})")

    # 第2步: 关键参数对的联合搜索
    print(f"\n  步骤2: 关键参数对联合搜索")
    key_pairs = [
        ('buy_sig_10_bonus', 'buy_sig_12_bonus'),
        ('buy_sig_8_bonus', 'buy_sig_10_bonus'),
        ('buy_dominance_bonus', 'buy_ratio_bonus'),
        ('buy_sig_5_bonus', 'buy_dominance_bonus'),
        ('buy_sig_12_bonus', 'buy_sig_15_bonus'),
    ]

    for p1, p2 in key_pairs:
        pair_best_obj = objective(evaluate(df, current_params))
        pair_best = (current_params[p1], current_params[p2])

        for v1 in all_search.get(p1, [current_params[p1]]):
            for v2 in all_search.get(p2, [current_params[p2]]):
                test_params = deepcopy(current_params)
                test_params[p1] = v1
                test_params[p2] = v2
                result = evaluate(df, test_params)
                obj = objective(result)
                if obj > pair_best_obj:
                    pair_best_obj = obj
                    pair_best = (v1, v2)

        if pair_best != (current_params[p1], current_params[p2]):
            print(f"    {p1}={pair_best[0]}, {p2}={pair_best[1]} → obj={pair_best_obj:.2f}")
            current_params[p1] = pair_best[0]
            current_params[p2] = pair_best[1]

    final_result = evaluate(df, current_params)
    final_obj = objective(final_result)

    print(f"\n  最终优化结果:")
    print(f"    wr={final_result['wr']:.1f}%, avg={final_result['avg']:+.2f}%, n={final_result['n']}")
    print(f"    top_wr={final_result['top_wr']:.1f}%, obj={final_obj:.2f}")
    print(f"    vs v9基线: obj {final_obj - base_obj:+.2f}")

    # 显示最优的买入信号参数
    print(f"\n  最优买入信号参数:")
    bs_params = {}
    for k in list(buy_sig_space.keys()) + list(other_space.keys()):
        old = V9_PARAMS.get(k, 0)
        new = current_params[k]
        marker = " ←改变" if old != new else ""
        print(f"    {k}: {old} → {new}{marker}")
        bs_params[k] = new

    return current_params, final_result, bs_params


# ========== 第5部分: 交叉验证 ==========

def cross_validate(df, optimized_params):
    """时间序列交叉验证, 避免过拟合"""
    print("\n" + "=" * 70)
    print("  第5部分: 时间序列交叉验证")
    print("=" * 70)

    dates = sorted(df['report_date'].unique())
    n_dates = len(dates)
    fold_size = max(1, n_dates // 5)

    print(f"\n  日期范围: {dates[0]} ~ {dates[-1]} ({n_dates} 天)")
    print(f"  5折时间序列验证 (每折~{fold_size}天)")

    v9_folds = []
    opt_folds = []

    for i in range(5):
        test_start = i * fold_size
        test_end = min((i + 1) * fold_size, n_dates)
        if test_start >= n_dates:
            break

        test_dates = dates[test_start:test_end]
        train_dates = [d for d in dates if d not in test_dates]

        df_train = df[df['report_date'].isin(train_dates)]
        df_test = df[df['report_date'].isin(test_dates)]

        if len(df_test) < 5:
            continue

        # v9在测试集
        v9_result = evaluate(df_test, V9_PARAMS)
        # 优化参数在测试集
        opt_result = evaluate(df_test, optimized_params)

        v9_folds.append(v9_result)
        opt_folds.append(opt_result)

        print(f"\n  Fold {i+1}: 测试 {test_dates[0]}~{test_dates[-1]} ({len(df_test)}样本)")
        print(f"    v9:  wr={v9_result['wr']:.1f}%, avg={v9_result['avg']:+.2f}%, n={v9_result['n']}")
        print(f"    优化: wr={opt_result['wr']:.1f}%, avg={opt_result['avg']:+.2f}%, n={opt_result['n']}")

    # 汇总
    if v9_folds:
        v9_avg_wr = np.mean([f['wr'] for f in v9_folds])
        opt_avg_wr = np.mean([f['wr'] for f in opt_folds])
        v9_avg_ret = np.mean([f['avg'] for f in v9_folds if f['n'] > 0])
        opt_avg_ret = np.mean([f['avg'] for f in opt_folds if f['n'] > 0])
        v9_total_n = sum([f['n'] for f in v9_folds])
        opt_total_n = sum([f['n'] for f in opt_folds])

        print(f"\n  交叉验证汇总:")
        print(f"    v9平均:  wr={v9_avg_wr:.1f}%, avg={v9_avg_ret:+.2f}%, 总选股={v9_total_n}")
        print(f"    优化平均: wr={opt_avg_wr:.1f}%, avg={opt_avg_ret:+.2f}%, 总选股={opt_total_n}")
        print(f"    提升: wr {opt_avg_wr-v9_avg_wr:+.1f}%, avg {opt_avg_ret-v9_avg_ret:+.2f}%")


# ========== 第6部分: 综合结论 ==========

def print_conclusion(bin_stats, strategies, bs_params, optimized_params, df):
    """输出综合结论和建议"""
    print("\n" + "=" * 70)
    print("  第6部分: 综合结论与建议")
    print("=" * 70)

    # 判断相关性强度
    df_bs = df[df['buy_signals'].notna()]
    corr = df_bs['buy_signals'].corr(df_bs['return_5d'])
    high_bs_wr = (df_bs[df_bs['buy_signals'] >= 10]['return_5d'] > 0).mean() * 100
    low_bs_wr = (df_bs[df_bs['buy_signals'] < 5]['return_5d'] > 0).mean() * 100

    print(f"\n  1. 相关性结论:")
    if corr > 0.1:
        print(f"    ✓ buy_signals与5日收益呈正相关 (r={corr:+.4f})")
    elif corr > 0:
        print(f"    △ buy_signals与5日收益弱正相关 (r={corr:+.4f})")
    else:
        print(f"    ✗ buy_signals与5日收益无正相关 (r={corr:+.4f})")

    print(f"    高信号(>=10)胜率: {high_bs_wr:.1f}%, 低信号(<5)胜率: {low_bs_wr:.1f}%")
    if high_bs_wr > low_bs_wr + 5:
        print(f"    ✓ 高买入信号确实具有更高胜率 (差距 {high_bs_wr-low_bs_wr:+.1f}%)")
    else:
        print(f"    △ 高低信号胜率差距不显著 (差距 {high_bs_wr-low_bs_wr:+.1f}%)")

    # 最佳策略
    positive_strategies = [s for s in strategies if s['delta'] > 0]
    if positive_strategies:
        best = max(positive_strategies, key=lambda s: s['delta'])
        print(f"\n  2. 最佳策略: {best['name']}")
        print(f"    提升: obj {best['delta']:+.2f}")
        print(f"    效果: wr={best['result']['wr']:.1f}%, avg={best['result']['avg']:+.2f}%, n={best['result']['n']}")

    # 推荐参数
    print(f"\n  3. 推荐的买入信号参数 (v10):")
    changes = []
    for k, v in bs_params.items():
        old = V9_PARAMS.get(k, 0)
        if old != v:
            changes.append((k, old, v))
            print(f"    {k}: {old} → {v}")
    if not changes:
        print(f"    (无变化, v9参数已是最优)")

    # 最终评估
    base_result = evaluate(df, V9_PARAMS)
    opt_result = evaluate(df, optimized_params)
    print(f"\n  4. 整体效果:")
    print(f"    v9基线: wr={base_result['wr']:.1f}%, avg={base_result['avg']:+.2f}%, n={base_result['n']}")
    print(f"    优化后: wr={opt_result['wr']:.1f}%, avg={opt_result['avg']:+.2f}%, n={opt_result['n']}")

    should_update = len(changes) > 0 and objective(opt_result) > objective(base_result)
    print(f"\n  5. 建议: {'建议更新参数到v10' if should_update else '当前v9参数已经足够好, 暂不需要调整'}")

    return should_update, changes


def main():
    print("=" * 70)
    print("  量化买入信号与胜率相关性分析")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    df = load_data()

    # 第1部分: 原始相关性
    bin_stats = analyze_raw_correlation(df)

    # 第2部分: v9评分体系下分析
    analyze_scored_correlation(df)

    # 第3部分: 策略回测
    strategies = backtest_buy_signal_strategies(df)

    # 第4部分: 组合优化
    optimized_params, opt_result, bs_params = optimize_buy_signal_params(df)

    # 第5部分: 交叉验证
    cross_validate(df, optimized_params)

    # 第6部分: 结论
    should_update, changes = print_conclusion(bin_stats, strategies, bs_params, optimized_params, df)

    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result_file = os.path.join(RESULTS_DIR, f'buy_signal_analysis_{timestamp}.json')
    result_data = {
        'timestamp': datetime.now().isoformat(),
        'bin_stats': bin_stats,
        'v9_baseline': evaluate(df, V9_PARAMS),
        'optimized': opt_result,
        'bs_params': bs_params,
        'should_update': should_update,
        'changes': [{'param': k, 'old': old, 'new': new} for k, old, new in changes],
    }
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    print(f"\n  结果已保存: {result_file}")


if __name__ == '__main__':
    main()
