#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v5.2 极限优化搜索 - 追求高胜率
==============================
在v5.1基础上探索:
1. 更严格的Top-N (Top8/Top6/Top4)
2. 最低评分门槛 (只推荐高分)
3. 更多组合条件淘汰
4. 非线性因子组合
5. 板块/技术面交叉过滤
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def load_data():
    results_dir = os.path.join(project_root, 'results')
    csv_files = sorted([f for f in os.listdir(results_dir)
                        if f.startswith('backtest_analysis_') and f.endswith('.csv')])
    csv_path = os.path.join(results_dir, csv_files[-1])
    df = pd.read_csv(csv_path)
    print(f"加载: {csv_files[-1]}, {len(df)}条", flush=True)
    return df


def apply_strategy_v52(df, p):
    """v5.2策略: 淘汰+惩罚+选择"""
    mask = pd.Series(True, index=df.index)

    # 硬淘汰 (v5.1最优基础)
    mask &= ~((df['rsi'].fillna(0) >= p.get('rsi_max', 85)))
    mask &= ~((df['day_change'].fillna(0) >= p.get('dc_max', 10)))
    mask &= ~((df['change_5d'].fillna(0) > p.get('c5d_max', 18)))
    mask &= ~((df['change_3d'].fillna(0) > p.get('c3d_max', 20)))
    # 组合淘汰
    mask &= ~((df['rsi'].fillna(0) > p.get('combo_rsi', 80)) &
              (df['change_3d'].fillna(0) > p.get('combo_c3d', 10)))
    mask &= ~((df['change_5d'].fillna(0) > p.get('pos_c5d', 15)) &
              (df['rsi'].fillna(0) > p.get('pos_rsi', 72)))

    # === v5.2新增淘汰条件 ===
    # 板块过热淘汰
    if p.get('sector_max', 999) < 999:
        mask &= ~((df['sector_score'].fillna(50) >= p['sector_max']))

    # 技术面极低淘汰
    if p.get('tech_min', 0) > 0:
        mask &= ~((df['tech_score'].fillna(50) < p['tech_min']))

    # 量化分极高淘汰 (反转效应)
    if p.get('quant_max', 999) < 999:
        mask &= ~((df['quant_score'].fillna(50) >= p['quant_max']))

    # 日涨幅+RSI组合 (追涨杀入)
    if p.get('dc_rsi_dc', 999) < 999:
        mask &= ~((df['day_change'].fillna(0) >= p['dc_rsi_dc']) &
                  (df['rsi'].fillna(0) > p.get('dc_rsi_rsi', 70)))

    # 3日涨幅+日涨幅组合 (连续暴涨)
    if p.get('c3d_dc_c3d', 999) < 999:
        mask &= ~((df['change_3d'].fillna(0) > p['c3d_dc_c3d']) &
                  (df['day_change'].fillna(0) >= p.get('c3d_dc_dc', 5)))

    # 惩罚调分
    scores = df['score'].copy()
    scores[~mask] = 0

    idx_passed = df[mask].index
    passed = df.loc[idx_passed]

    penalty = pd.Series(0.0, index=idx_passed)
    bonus = pd.Series(0.0, index=idx_passed)

    # 追高风险
    chase = passed['chase_risk'].fillna(0)
    penalty += np.where(chase >= 80, p.get('chase_p80', 20),
              np.where(chase >= 60, p.get('chase_p60', 10), 0))

    # RSI惩罚
    rsi = passed['rsi'].fillna(50)
    penalty += np.where(rsi >= 85, p.get('rsi_p85', 20),
              np.where(rsi > 80, p.get('rsi_p80', 15),
              np.where(rsi > 75, p.get('rsi_p75', 8),
              np.where(rsi > 70, p.get('rsi_p70', 0), 0))))

    # 涨停惩罚
    dc = passed['day_change'].fillna(0)
    penalty += np.where(dc >= 19.5, p.get('dc_p20', 20),
              np.where(dc >= 9.5, p.get('dc_p10', 12),
              np.where(dc >= 7, p.get('dc_p7', 8),
              np.where(dc >= 5, p.get('dc_p5', 5), 0))))

    # 暴涨惩罚
    c5d = passed['change_5d'].fillna(0)
    c3d = passed['change_3d'].fillna(0)
    penalty += np.where(c5d > 25, p.get('surge5d', 15),
              np.where(c3d > 15, p.get('surge3d', 10),
              np.where(c3d > 10, p.get('surge3d_m', 5),
              np.where(c3d > 8, p.get('surge3d_s', 0), 0))))

    # 量化分惩罚
    qs = passed['quant_score'].fillna(50)
    penalty += np.where(qs >= 90, p.get('qs_p90', 20),
              np.where(qs >= 80, p.get('qs_p80', 5),
              np.where(qs >= 70, p.get('qs_p70', 0), 0)))

    # 信号拥挤
    bs = passed['buy_signals'].fillna(5)
    penalty += np.where(bs >= 15, p.get('crowd', 8),
              np.where(bs >= 12, p.get('crowd12', 0), 0))

    # 板块过热惩罚
    ss_score = passed['sector_score'].fillna(50)
    penalty += np.where(ss_score >= 95, p.get('sector_p95', 0),
              np.where(ss_score >= 90, p.get('sector_p90', 0), 0))

    # 奖励
    ss = passed['sell_signals'].fillna(5)
    bonus += np.where(ss <= 1, p.get('low_sell', 0), 0)
    bonus += np.where(bs <= 3, p.get('low_buy', 0), 0)
    bonus += np.where(rsi < 35, p.get('rsi_os', 0), 0)
    # RSI 70-80区间奖励 (回测: 偏强但非超买)
    bonus += np.where((rsi >= 70) & (rsi < 80), p.get('rsi_strong', 0), 0)

    scores.loc[idx_passed] = np.maximum(0, scores.loc[idx_passed] - penalty + bonus)

    # 最低分门槛
    min_score = p.get('min_score', 0)
    if min_score > 0:
        scores[scores < min_score] = 0
        mask = mask & (scores >= min_score)

    # 每日TopN选择
    top_n = p.get('top_n', 10)
    df_p = df[mask & (scores > 0)].copy()
    df_p['adj_score'] = scores[mask & (scores > 0)]

    sels = []
    for date, grp in df_p.groupby('report_date'):
        top = grp.nlargest(min(top_n, len(grp)), 'adj_score')
        top = top.copy()
        top['adj_rank'] = range(1, len(top) + 1)
        sels.append(top)

    if sels:
        return pd.concat(sels, ignore_index=True), mask.sum()
    return pd.DataFrame(), 0


def eval_full(df_sel, top_n=None):
    if len(df_sel) == 0:
        return {}
    sub = df_sel[df_sel['adj_rank'] <= top_n] if top_n else df_sel
    result = {'count': len(sub)}
    for p in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
        v = sub[p].dropna()
        short = p.replace('return_', '')
        result[f'wr_{short}'] = (v > 0).mean() * 100 if len(v) > 0 else 0
        result[f'ret_{short}'] = v.mean() if len(v) > 0 else -99
    return result


def main():
    print("=" * 70, flush=True)
    print("  v5.2 极限优化 - 追求高胜率", flush=True)
    print("=" * 70, flush=True)

    df = load_data()

    # 原始基线
    orig = df[df['rank'] <= 10]
    r5 = orig['return_5d'].dropna()
    print(f"\n原始Top10: 5d收益{r5.mean():+.2f}%, 胜率{(r5>0).mean()*100:.1f}%", flush=True)

    # v5.1最优基线参数
    v51_base = {
        'rsi_max': 85, 'dc_max': 10, 'c5d_max': 18, 'c3d_max': 20,
        'combo_rsi': 80, 'combo_c3d': 10, 'pos_c5d': 15, 'pos_rsi': 72,
        'chase_p80': 20, 'chase_p60': 10,
        'rsi_p85': 20, 'rsi_p80': 15, 'rsi_p75': 10,
        'dc_p20': 20, 'dc_p10': 8, 'dc_p5': 5,
        'surge5d': 15, 'surge3d': 10, 'surge3d_m': 5,
        'qs_p90': 20, 'qs_p80': 5, 'crowd': 10,
        'low_sell': 0, 'low_buy': 5, 'rsi_os': 8,
    }

    df_sel, _ = apply_strategy_v52(df, v51_base)
    ev = eval_full(df_sel, 10)
    print(f"\nv5.1基线 Top10: 5d收益{ev['ret_5d']:+.2f}%, 胜率{ev['wr_5d']:.1f}%, 10d收益{ev['ret_10d']:+.2f}%, 胜率{ev['wr_10d']:.1f}%", flush=True)

    # ========= 策略1: 更严格TopN =========
    print(f"\n{'='*50}", flush=True)
    print(f"策略1: 不同TopN对比", flush=True)
    for top_n in [10, 8, 7, 6, 5, 4, 3]:
        p = v51_base.copy()
        p['top_n'] = top_n
        df_sel, _ = apply_strategy_v52(df, p)
        ev = eval_full(df_sel, top_n)
        ev5 = eval_full(df_sel, min(5, top_n))
        ev3 = eval_full(df_sel, min(3, top_n))
        print(f"  Top{top_n:>2}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
              f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) "
              f"1d={ev['ret_1d']:+.2f}%(wr{ev['wr_1d']:.1f}%) 样本{ev['count']}", flush=True)

    # ========= 策略2: 最低分门槛 =========
    print(f"\n{'='*50}", flush=True)
    print(f"策略2: 最低分门槛 (Top10)", flush=True)
    for min_s in [0, 50, 55, 60, 65, 68, 70, 72, 75]:
        p = v51_base.copy()
        p['min_score'] = min_s
        df_sel, _ = apply_strategy_v52(df, p)
        if len(df_sel) < 50:
            continue
        ev = eval_full(df_sel, 10)
        print(f"  min_score={min_s:>3}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
              f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # ========= 策略3: 额外条件淘汰 =========
    print(f"\n{'='*50}", flush=True)
    print(f"策略3: 额外条件淘汰 (在v5.1基础上)", flush=True)

    # 3a: 板块过热
    for sec_max in [999, 98, 95, 92, 90, 85, 80]:
        p = v51_base.copy()
        p['sector_max'] = sec_max
        df_sel, np_ = apply_strategy_v52(df, p)
        if len(df_sel) < 50:
            continue
        ev = eval_full(df_sel, 10)
        label = f"sec<{sec_max}" if sec_max < 999 else "无限制"
        print(f"  板块 {label:>7}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
              f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # 3b: 量化分上限
    for q_max in [999, 95, 90, 85, 80, 75]:
        p = v51_base.copy()
        p['quant_max'] = q_max
        df_sel, _ = apply_strategy_v52(df, p)
        if len(df_sel) < 50:
            continue
        ev = eval_full(df_sel, 10)
        label = f"qs<{q_max}" if q_max < 999 else "无限制"
        print(f"  量化 {label:>7}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
              f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # 3c: 技术分下限
    for t_min in [0, 30, 40, 50, 55, 60]:
        p = v51_base.copy()
        p['tech_min'] = t_min
        df_sel, _ = apply_strategy_v52(df, p)
        if len(df_sel) < 50:
            continue
        ev = eval_full(df_sel, 10)
        label = f"tech>{t_min}" if t_min > 0 else "无限制"
        print(f"  技术 {label:>8}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
              f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # 3d: 日涨幅+RSI组合
    for dc_th in [8, 7, 5]:
        for rsi_th in [70, 65, 60]:
            p = v51_base.copy()
            p['dc_rsi_dc'] = dc_th
            p['dc_rsi_rsi'] = rsi_th
            df_sel, _ = apply_strategy_v52(df, p)
            if len(df_sel) < 50:
                continue
            ev = eval_full(df_sel, 10)
            print(f"  dc>={dc_th}&RSI>{rsi_th}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
                  f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # 3e: 3日涨+当日涨组合
    for c3d_th in [10, 8, 6]:
        for dc_th in [5, 3]:
            p = v51_base.copy()
            p['c3d_dc_c3d'] = c3d_th
            p['c3d_dc_dc'] = dc_th
            df_sel, _ = apply_strategy_v52(df, p)
            if len(df_sel) < 50:
                continue
            ev = eval_full(df_sel, 10)
            print(f"  c3d>{c3d_th}&dc>={dc_th}: 5d={ev['ret_5d']:+.2f}%(wr{ev['wr_5d']:.1f}%) "
                  f"10d={ev['ret_10d']:+.2f}%(wr{ev['wr_10d']:.1f}%) 样本{ev['count']}", flush=True)

    # ========= 策略4: 组合最优条件 =========
    print(f"\n{'='*50}", flush=True)
    print(f"策略4: 组合搜索最优综合策略", flush=True)

    best_cs = -999
    best_p = None
    results = []

    for top_n in [10, 8, 7, 6]:
        for min_s in [0, 55, 60, 65]:
            for sec_max in [999, 95, 90]:
                for q_max in [999, 90, 85]:
                    for dc_rsi_dc in [999, 7, 5]:
                        for c3d_dc_c3d in [999, 8, 6]:
                            p = v51_base.copy()
                            p['top_n'] = top_n
                            p['min_score'] = min_s
                            p['sector_max'] = sec_max
                            p['quant_max'] = q_max
                            if dc_rsi_dc < 999:
                                p['dc_rsi_dc'] = dc_rsi_dc
                                p['dc_rsi_rsi'] = 65
                            if c3d_dc_c3d < 999:
                                p['c3d_dc_c3d'] = c3d_dc_c3d
                                p['c3d_dc_dc'] = 5

                            df_sel, _ = apply_strategy_v52(df, p)
                            if len(df_sel) < 80:
                                continue
                            ev = eval_full(df_sel, top_n)

                            # 综合评分: 重5d胜率
                            cs = (ev['wr_5d'] * 4 + ev['wr_10d'] * 2 +
                                  ev['ret_5d'] * 10 + ev['ret_10d'] * 5 +
                                  ev['wr_1d'] * 1)

                            results.append((cs, ev, p.copy()))
                            if cs > best_cs:
                                best_cs = cs
                                best_p = p.copy()

    results.sort(key=lambda x: x[0], reverse=True)
    print(f"\n  有效组合: {len(results)}", flush=True)
    print(f"\n  Top 15 综合策略:", flush=True)
    print(f"  {'#':>3} {'5d胜率':>7} {'5d收益':>8} {'10d胜率':>8} {'10d收益':>9} {'1d胜率':>7} {'样本':>5} | TopN minS sec qs dcr c3d", flush=True)
    for i, (cs, ev, p) in enumerate(results[:15]):
        print(f"  {i+1:>3} {ev['wr_5d']:>6.1f}% {ev['ret_5d']:>+7.2f}% {ev['wr_10d']:>7.1f}% {ev['ret_10d']:>+8.2f}% "
              f"{ev['wr_1d']:>6.1f}% {ev['count']:>5} | "
              f"T{p['top_n']} m{p['min_score']} s{p.get('sector_max', 999)} q{p.get('quant_max', 999)} "
              f"d{p.get('dc_rsi_dc', '-')} c{p.get('c3d_dc_c3d', '-')}", flush=True)

    # ========= 策略5: 在最优基础上微调惩罚力度 =========
    if best_p:
        print(f"\n{'='*50}", flush=True)
        print(f"策略5: 在最优组合上微调惩罚", flush=True)

        best_cs5 = -999
        best_p5 = None
        results5 = []

        for rsi_p70 in [0, 3, 5]:
            for dc_p7 in [0, 5, 8, 10]:
                for qs_p70 in [0, 3, 5]:
                    for surge3d_s in [0, 3, 5]:
                        for crowd12 in [0, 3, 5]:
                            for sec_p90 in [0, 5, 8]:
                                for sec_p95 in [0, 5, 8, 10]:
                                    p = best_p.copy()
                                    p['rsi_p70'] = rsi_p70
                                    p['dc_p7'] = dc_p7
                                    p['qs_p70'] = qs_p70
                                    p['surge3d_s'] = surge3d_s
                                    p['crowd12'] = crowd12
                                    p['sector_p90'] = sec_p90
                                    p['sector_p95'] = sec_p95

                                    df_sel, _ = apply_strategy_v52(df, p)
                                    if len(df_sel) < 80:
                                        continue
                                    tn = p['top_n']
                                    ev = eval_full(df_sel, tn)

                                    cs = (ev['wr_5d'] * 4 + ev['wr_10d'] * 2 +
                                          ev['ret_5d'] * 10 + ev['ret_10d'] * 5 +
                                          ev['wr_1d'] * 1)

                                    results5.append((cs, ev, p.copy()))
                                    if cs > best_cs5:
                                        best_cs5 = cs
                                        best_p5 = p.copy()

        results5.sort(key=lambda x: x[0], reverse=True)
        print(f"  有效组合: {len(results5)}", flush=True)
        print(f"\n  Top 10:", flush=True)
        print(f"  {'#':>3} {'5d胜率':>7} {'5d收益':>8} {'10d胜率':>8} {'10d收益':>9} {'1d胜率':>7} {'3d胜率':>7} {'样本':>5}", flush=True)
        for i, (cs, ev, p) in enumerate(results5[:10]):
            print(f"  {i+1:>3} {ev['wr_5d']:>6.1f}% {ev['ret_5d']:>+7.2f}% {ev['wr_10d']:>7.1f}% {ev['ret_10d']:>+8.2f}% "
                  f"{ev['wr_1d']:>6.1f}% {ev['wr_3d']:>6.1f}% {ev['count']:>5}", flush=True)

        final_params = best_p5 if best_p5 else best_p
    else:
        final_params = v51_base

    # ========= 最终全面评估 =========
    print(f"\n{'='*70}", flush=True)
    print(f"  最终最优v5.2策略评估", flush=True)
    print(f"{'='*70}", flush=True)

    df_sel, n_passed = apply_strategy_v52(df, final_params)
    tn = final_params.get('top_n', 10)

    print(f"\n  淘汰后: {n_passed}/{len(df)} ({n_passed/len(df)*100:.1f}%)")
    print(f"  v5.2入选: {len(df_sel)}条 (每日Top{tn})")

    print(f"\n  {'':>15} {'1d收益':>9} {'1d胜率':>7} {'3d收益':>9} {'3d胜率':>7} {'5d收益':>9} {'5d胜率':>7} {'10d收益':>9} {'10d胜率':>7}", flush=True)
    print(f"  {'-' * 90}", flush=True)

    for label, data in [('原始全部', df), ('原始Top10', df[df['rank'] <= 10])]:
        vals = {}
        for p in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
            v = data[p].dropna()
            vals[p] = (v.mean(), (v > 0).mean() * 100) if len(v) > 0 else (0, 0)
        print(f"  {label:>15} {vals['return_1d'][0]:>+8.2f}% {vals['return_1d'][1]:>6.1f}% "
              f"{vals['return_3d'][0]:>+8.2f}% {vals['return_3d'][1]:>6.1f}% "
              f"{vals['return_5d'][0]:>+8.2f}% {vals['return_5d'][1]:>6.1f}% "
              f"{vals['return_10d'][0]:>+8.2f}% {vals['return_10d'][1]:>6.1f}%", flush=True)

    for label, rk in [(f'v5.2 Top{tn}', tn), ('v5.2 Top5', min(5, tn)),
                       ('v5.2 Top3', min(3, tn))]:
        sub = df_sel[df_sel['adj_rank'] <= rk]
        vals = {}
        for p in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
            v = sub[p].dropna()
            vals[p] = (v.mean(), (v > 0).mean() * 100) if len(v) > 0 else (0, 0)
        print(f"  {label:>15} {vals['return_1d'][0]:>+8.2f}% {vals['return_1d'][1]:>6.1f}% "
              f"{vals['return_3d'][0]:>+8.2f}% {vals['return_3d'][1]:>6.1f}% "
              f"{vals['return_5d'][0]:>+8.2f}% {vals['return_5d'][1]:>6.1f}% "
              f"{vals['return_10d'][0]:>+8.2f}% {vals['return_10d'][1]:>6.1f}%", flush=True)

    # 月度
    print(f"\n  月度表现 (Top{tn}):", flush=True)
    df_sel['month'] = pd.to_datetime(df_sel['report_date']).dt.to_period('M').astype(str)
    for m in sorted(df_sel['month'].unique()):
        sub = df_sel[(df_sel['month'] == m) & (df_sel['adj_rank'] <= tn)]
        r5 = sub['return_5d'].dropna()
        r1 = sub['return_1d'].dropna()
        if len(r5) > 0:
            print(f"    {m}: {len(sub)}条, 1d={r1.mean():+.2f}%(wr{(r1>0).mean()*100:.1f}%), "
                  f"5d={r5.mean():+.2f}%(wr{(r5>0).mean()*100:.1f}%)", flush=True)

    # 5日盈亏比
    for label, rk in [(f'Top{tn}', tn), ('Top5', min(5, tn))]:
        sub = df_sel[df_sel['adj_rank'] <= rk]
        r5 = sub['return_5d'].dropna()
        wins = r5[r5 > 0]
        losses = r5[r5 < 0]
        pf = abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf')
        print(f"\n  {label} 5日盈亏比: {pf:.2f}", flush=True)

    # 参数输出
    print(f"\n{'='*70}", flush=True)
    print(f"  最优v5.2参数", flush=True)
    print(f"{'='*70}", flush=True)
    print(f"\n淘汰:", flush=True)
    for k in ['rsi_max', 'dc_max', 'c5d_max', 'c3d_max', 'combo_rsi', 'combo_c3d',
              'pos_c5d', 'pos_rsi', 'sector_max', 'quant_max', 'tech_min',
              'dc_rsi_dc', 'dc_rsi_rsi', 'c3d_dc_c3d', 'c3d_dc_dc']:
        v = final_params.get(k, 'N/A')
        if v != 'N/A' and v != 999:
            print(f"  {k}: {v}", flush=True)

    print(f"\n惩罚:", flush=True)
    for k in sorted([k for k in final_params if k.endswith(('_p80', '_p85', '_p75', '_p70',
                    '_p90', '_p95', '_p10', '_p20', '_p5', '_p7'))
                    or k in ('crowd', 'crowd12', 'surge5d', 'surge3d', 'surge3d_m', 'surge3d_s')]):
        print(f"  {k}: -{final_params.get(k, 0)}", flush=True)

    print(f"\n奖励:", flush=True)
    for k in ['low_sell', 'low_buy', 'rsi_os', 'rsi_strong']:
        if final_params.get(k, 0) > 0:
            print(f"  {k}: +{final_params[k]}", flush=True)

    print(f"\n其他:", flush=True)
    print(f"  top_n: {final_params.get('top_n', 10)}", flush=True)
    print(f"  min_score: {final_params.get('min_score', 0)}", flush=True)


if __name__ == '__main__':
    main()
