#!/usr/bin/env python3
"""v19参数优化分析 - 测试多种参数变化并找出最优方案"""

import os, sys, pandas as pd, numpy as np
from itertools import product

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

def load_data():
    results_dir = os.path.join(project_root, 'results')
    csv_files = sorted([f for f in os.listdir(results_dir) if f.startswith('backtest_rebuilt_') and f.endswith('.csv')])
    df = pd.read_csv(os.path.join(results_dir, csv_files[-1]))
    if 'code' in df.columns and 'report_date' in df.columns:
        df = df.sort_values('filename', ascending=False).drop_duplicates(
            subset=['code', 'report_date'], keep='first'
        ).sort_values(['report_date', 'rank']).reset_index(drop=True)
    return df

def score_with_params(df, params):
    """Apply scoring with given parameters, return scored df"""
    df = df.copy()
    df['adj_score'] = df['score'].astype(float).copy()

    for idx, row in df.iterrows():
        penalty = 0
        bonus = 0
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

        # RSI
        if pd.notna(rsi):
            if rsi >= 85: penalty += 25
            elif rsi > 80: penalty += 15

        # 日涨幅
        if pd.notna(day_chg):
            if day_chg >= 20: penalty += 25
            elif day_chg >= 9.5:
                if pd.notna(chg_3d) and chg_3d >= 15: penalty += 5
            elif day_chg >= 7: penalty += 3
            elif day_chg >= 5: penalty += 5

        # 5日涨幅
        if pd.notna(chg_5d) and chg_5d > 25:
            penalty += 25
        elif pd.notna(chg_5d) and chg_5d > 18:
            penalty += 15

        # 3日涨幅
        if pd.notna(chg_3d):
            if chg_3d > 20: penalty += 15
            elif chg_3d > 15: penalty += 10
            elif chg_3d > 10: penalty += 8

        # 追高
        if pd.notna(chase):
            if chase >= 80: penalty += 20
            elif chase >= 60: penalty += 3

        # 技术面虚高
        if pd.notna(tech) and tech >= 80:
            penalty += params.get('tech_high_pen', 3)

        # 板块
        if pd.notna(sector):
            if sector >= 95: penalty += 12
            elif 60 <= sector < 75: penalty += params.get('sector_dead_pen', 10)

        # 评分过高 (核心参数)
        score_high_threshold = params.get('score_high_threshold', 76)
        score_high_min = params.get('score_high_min', 15)
        score_high_mult = params.get('score_high_mult', 1.2)
        if score >= score_high_threshold:
            score_pen = max(score_high_min, int((score - score_high_threshold) * score_high_mult))
            penalty += score_pen

        # 组合风险
        if pd.notna(rsi) and pd.notna(chg_3d) and rsi > 80 and chg_3d > 10: penalty += 10
        if pd.notna(chg_5d) and pd.notna(rsi) and chg_5d > 15 and rsi > 72: penalty += 10

        # 信号拥挤
        if pd.notna(buy_sig) and buy_sig >= 15:
            penalty += params.get('signal_crowd_pen', 8)

        # v18: sell>=3
        if pd.notna(sell_sig) and sell_sig >= 3:
            penalty += params.get('sell_high_pen', 5)

        # v18: qs>=90
        if pd.notna(qs) and qs >= 90:
            penalty += params.get('qs_high_pen', 5)

        # ===== 加分 =====
        if pd.notna(sell_sig) and sell_sig == 0:
            sell0_bonus = 4
            if pd.notna(day_chg) and day_chg >= 9.5: sell0_bonus = 8
            bonus += sell0_bonus

        if pd.notna(rsi) and rsi < 35: bonus += 5
        if pd.notna(rsi) and 40 <= rsi <= 50: bonus += 4

        if pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase < 50:
            if not (pd.notna(buy_sig) and buy_sig > 8): bonus += 10
        elif pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase >= 50:
            bonus += 8
        elif pd.notna(day_chg) and day_chg >= 7 and pd.notna(chase) and chase < 40:
            bonus += 12

        if pd.notna(day_chg) and 3 <= day_chg < 10 and pd.notna(chase) and chase < 50:
            bonus += 5

        if pd.notna(qs) and qs < 50: bonus += 5

        if pd.notna(chase) and pd.notna(rsi) and chase < 25 and rsi < 50:
            bonus += 8

        # === 新增可选加分 ===

        # 买入信号强势奖励 (buy>=6 & sell<=1 & qs>=70)
        if params.get('buy_strong_bonus', 0) > 0:
            if pd.notna(buy_sig) and pd.notna(sell_sig) and pd.notna(qs):
                if buy_sig >= 6 and sell_sig <= 1 and qs >= 70:
                    bonus += params['buy_strong_bonus']

        # 多维共振奖励 (quant>=80 & sector>=80)
        if params.get('multi_dim_bonus', 0) > 0:
            if pd.notna(qs) and pd.notna(sector):
                if qs >= 80 and sector >= 80:
                    bonus += params['multi_dim_bonus']

        # 板块强势奖励 (sector>=90)
        if params.get('sector_strong_bonus', 0) > 0:
            if pd.notna(sector) and sector >= 90:
                bonus += params['sector_strong_bonus']

        adj = max(0, score - penalty + bonus)
        df.at[idx, 'adj_score'] = adj

    return df

def evaluate(df, label=""):
    """Evaluate a scored df: select top10 per day, compute tier stats"""
    selections = []
    for date, group in df.groupby('report_date'):
        top = group.nlargest(10, 'adj_score')
        selections.append(top)
    if not selections:
        return None
    sel = pd.concat(selections, ignore_index=True)

    r5 = sel['return_5d'].dropna()
    if len(r5) == 0:
        return None

    # Tier stats
    tiers = {}
    for tier, low, high in [('S', 85, 999), ('A', 78, 85), ('B', 70, 78), ('C', 0, 70)]:
        if high == 999:
            sub = sel[sel['adj_score'] >= low]
        else:
            sub = sel[(sel['adj_score'] >= low) & (sel['adj_score'] < high)]
        r = sub['return_5d'].dropna()
        tiers[tier] = {
            'n': len(sub),
            'wr': (r > 0).mean() * 100 if len(r) > 0 else 0,
            'avg': r.mean() if len(r) > 0 else 0,
        }

    bp_count = tiers['S']['n'] + tiers['A']['n'] + tiers['B']['n']
    bp_sub = sel[sel['adj_score'] >= 70]
    bp_r5 = bp_sub['return_5d'].dropna()
    bp_wr = (bp_r5 > 0).mean() * 100 if len(bp_r5) > 0 else 0
    bp_avg = bp_r5.mean() if len(bp_r5) > 0 else 0

    return {
        'label': label,
        'total': len(sel),
        'S': tiers['S'],
        'A': tiers['A'],
        'B': tiers['B'],
        'C': tiers['C'],
        'B+': {'n': bp_count, 'wr': bp_wr, 'avg': bp_avg},
        'overall_wr': (r5 > 0).mean() * 100,
        'overall_avg': r5.mean(),
    }

def print_result(r):
    if r is None:
        print("  No data")
        return
    print(f"  {r['label']}")
    print(f"    S: n={r['S']['n']}, wr={r['S']['wr']:.1f}%, avg={r['S']['avg']:+.2f}%")
    print(f"    A: n={r['A']['n']}, wr={r['A']['wr']:.1f}%, avg={r['A']['avg']:+.2f}%")
    print(f"    B: n={r['B']['n']}, wr={r['B']['wr']:.1f}%, avg={r['B']['avg']:+.2f}%")
    print(f"    B+: n={r['B+']['n']}, wr={r['B+']['wr']:.1f}%, avg={r['B+']['avg']:+.2f}%")
    print(f"    C: n={r['C']['n']}")
    a_gt_b = r['A']['wr'] > r['B']['wr'] if r['A']['n'] > 3 else True
    print(f"    A>B: {'✓' if a_gt_b else '✗'} ({r['A']['wr']:.1f}% vs {r['B']['wr']:.1f}%)")
    print()

def main():
    print("加载数据...")
    df = load_data()
    print(f"数据: {len(df)}行, {df['report_date'].nunique()}天")
    print()

    # ====== 1. 当前v18基线 ======
    print("=" * 70)
    print("1. v18 基线")
    print("=" * 70)
    v18 = score_with_params(df, {})
    r18 = evaluate(v18, "v18基线")
    print_result(r18)

    # ====== 2. 逐项分析各惩罚贡献 ======
    print("=" * 70)
    print("2. 逐项去除惩罚测试")
    print("=" * 70)

    tests = [
        ("去除score_high(76)", {'score_high_threshold': 999}),
        ("score_high阈值80", {'score_high_threshold': 80, 'score_high_min': 15, 'score_high_mult': 1.2}),
        ("score_high阈值78+降低min=10", {'score_high_threshold': 78, 'score_high_min': 10, 'score_high_mult': 1.0}),
        ("score_high阈值80+min=10+mult=0.8", {'score_high_threshold': 80, 'score_high_min': 10, 'score_high_mult': 0.8}),
        ("sector_dead 10→5", {'sector_dead_pen': 5}),
        ("sector_dead 10→0", {'sector_dead_pen': 0}),
        ("tech_high 3→0", {'tech_high_pen': 0}),
        ("signal_crowd 8→3", {'signal_crowd_pen': 3}),
        ("qs_high 5→0", {'qs_high_pen': 0}),
        ("sell_high 5→0", {'sell_high_pen': 0}),
    ]

    for label, params in tests:
        scored = score_with_params(df, params)
        r = evaluate(scored, label)
        print_result(r)

    # ====== 3. 新增加分信号测试 ======
    print("=" * 70)
    print("3. 新增加分信号测试")
    print("=" * 70)

    bonus_tests = [
        ("买入强势(buy>=6,sell<=1,qs>=70):+5", {'buy_strong_bonus': 5}),
        ("买入强势(buy>=6,sell<=1,qs>=70):+8", {'buy_strong_bonus': 8}),
        ("买入强势(buy>=6,sell<=1,qs>=70):+10", {'buy_strong_bonus': 10}),
        ("多维共振(qs>=80,sector>=80):+5", {'multi_dim_bonus': 5}),
        ("多维共振(qs>=80,sector>=80):+8", {'multi_dim_bonus': 8}),
        ("板块强势(sector>=90):+5", {'sector_strong_bonus': 5}),
        ("板块强势(sector>=90):+8", {'sector_strong_bonus': 8}),
    ]

    for label, params in bonus_tests:
        scored = score_with_params(df, params)
        r = evaluate(scored, label)
        print_result(r)

    # ====== 4. 回测数据分析: 高买入信号股票的实际表现 ======
    print("=" * 70)
    print("4. 高买入信号股票实际表现分析")
    print("=" * 70)

    for buy_min in [5, 6, 8, 10]:
        sub = df[(df['buy_signals'] >= buy_min) & (df['sell_signals'] <= 2)]
        r5 = sub['return_5d'].dropna()
        if len(r5) > 0:
            print(f"  buy>={buy_min} & sell<=2: n={len(r5)}, wr={((r5>0).mean()*100):.1f}%, avg={r5.mean():+.2f}%")

    print()
    for buy_min in [5, 6, 8]:
        for sell_max in [0, 1]:
            sub = df[(df['buy_signals'] >= buy_min) & (df['sell_signals'] <= sell_max) & (df['quant_score'] >= 70)]
            r5 = sub['return_5d'].dropna()
            if len(r5) > 0:
                print(f"  buy>={buy_min} & sell<={sell_max} & qs>=70: n={len(r5)}, wr={((r5>0).mean()*100):.1f}%, avg={r5.mean():+.2f}%")

    # ====== 5. 组合优化搜索 ======
    print()
    print("=" * 70)
    print("5. 组合优化搜索 (Top 10)")
    print("=" * 70)

    best_results = []

    param_grid = {
        'score_high_threshold': [76, 78, 80],
        'score_high_min': [10, 12, 15],
        'score_high_mult': [0.8, 1.0, 1.2],
        'sector_dead_pen': [5, 10],
        'tech_high_pen': [0, 3],
        'buy_strong_bonus': [0, 5, 8],
        'multi_dim_bonus': [0, 5],
    }

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    total = 1
    for v in values:
        total *= len(v)
    print(f"  搜索 {total} 种组合...")

    for combo in product(*values):
        params = dict(zip(keys, combo))
        scored = score_with_params(df, params)
        r = evaluate(scored)
        if r is None:
            continue

        a_gt_b = r['A']['wr'] > r['B']['wr'] if r['A']['n'] > 3 else True

        # 目标: B+ wr * 0.4 + B+ avg * 10 + B+ n * 0.05 + (A>B bonus)
        objective = (r['B+']['wr'] * 0.4 +
                     r['B+']['avg'] * 10 +
                     r['B+']['n'] * 0.05 +
                     (5 if a_gt_b else -10))

        best_results.append({
            'params': params,
            'result': r,
            'objective': objective,
            'a_gt_b': a_gt_b,
        })

    best_results.sort(key=lambda x: x['objective'], reverse=True)

    for i, br in enumerate(best_results[:10]):
        r = br['result']
        p = br['params']
        print(f"\n  #{i+1} (obj={br['objective']:.2f}, A>B={'✓' if br['a_gt_b'] else '✗'})")
        print(f"    params: sh_thr={p['score_high_threshold']}, sh_min={p['score_high_min']}, sh_mult={p['score_high_mult']}")
        print(f"            sd={p['sector_dead_pen']}, th={p['tech_high_pen']}, buy_bonus={p['buy_strong_bonus']}, multi={p['multi_dim_bonus']}")
        print(f"    S:{r['S']['n']}/{r['S']['wr']:.0f}%, A:{r['A']['n']}/{r['A']['wr']:.0f}%, B:{r['B']['n']}/{r['B']['wr']:.0f}%, B+:{r['B+']['n']}/{r['B+']['wr']:.1f}%/{r['B+']['avg']:+.2f}%")

    # ====== 6. 当前报告中的典型案例分析 ======
    print()
    print("=" * 70)
    print("6. 原始评分分布分析")
    print("=" * 70)

    scores = df['score'].dropna()
    print(f"  原始评分分布: min={scores.min():.0f}, p25={scores.quantile(0.25):.0f}, median={scores.median():.0f}, p75={scores.quantile(0.75):.0f}, max={scores.max():.0f}")

    for threshold in [70, 75, 78, 80, 85, 90]:
        above = df[df['score'] >= threshold]
        r5 = above['return_5d'].dropna()
        if len(r5) > 0:
            print(f"  原始score>={threshold}: n={len(r5)}, wr={((r5>0).mean()*100):.1f}%, avg={r5.mean():+.2f}%")

if __name__ == '__main__':
    main()
