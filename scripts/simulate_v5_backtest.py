#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v24 纯评分算法模拟回测 - 无淘汰版
====================
基于已有的回测数据(backtest_rebuilt CSV)，模拟应用 v24 共享评分规则，
对比优化前后的收益表现。

v24核心变更(vs v20, 见 docs/superpowers/specs/2026-06-10-pc-and-scoring-optimization-analysis.md §4):
- 事后奖惩规则统一抽取到 analysis/scoring_rules.py (sim/live 同一套, 消除双轨漂移)
- chg3d≥12 罚12 / ≥18 罚15 (恢复重罚)
- chase 分段罚: 40-60 罚5 / 60-80 罚12 / ≥80 罚15
- 移除 zt_high_chase_bonus (v17 涨停+chase≥50 +8)
- quant<50 奖励加 sector<55 门控
- 新增 RSI≥80 × chase≥60 组合罚 -10
- degraded(数据缺失降级) 行默认从统计中剔除 (--include-degraded 可包含)

sim-only 规则 (保留在本文件, RULESET 中以 sim_ 前缀登记):
- 原始评分过高渐进惩罚 (score>=76)
- 技术面虚高惩罚 (tech>=80: -3)
- 净买入信号梯度奖励 (live 由 buy_count 梯度+headroom 机制承担)
- 最终分 ≥95 上限保护
"""

import argparse
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.scoring_rules import (  # noqa: E402
    RULESET, RULESET_VERSION, evaluate_shared_rules, shared_bonus, shared_penalty,
)


def mark_degraded(df: pd.DataFrame) -> pd.DataFrame:
    """补全 degraded 列: 优先用 CSV 自带列; 否则用 quant_score==0 启发式
    (scorer 在无历史数据时量化评分恒为 0, 真实弱信号不会是精确 0)。"""
    df = df.copy()
    if 'degraded' in df.columns:
        df['degraded'] = df['degraded'].fillna(0).astype(float) > 0
    elif 'quant_score' in df.columns:
        df['degraded'] = df['quant_score'].notna() & (df['quant_score'] == 0)
    else:
        df['degraded'] = False
    return df


def load_backtest_data(csv_path: str) -> pd.DataFrame:
    """加载回测数据，去除重复记录（同一股票同一天只保留最新报告）"""
    df = pd.read_csv(csv_path)
    # 按filename降序排列（最新报告在前），然后去重保留第一条
    if 'code' in df.columns and 'report_date' in df.columns:
        before = len(df)
        df = df.sort_values('filename', ascending=False).drop_duplicates(
            subset=['code', 'report_date'], keep='first'
        ).sort_values(['report_date', 'rank']).reset_index(drop=True)
        after = len(df)
        if before != after:
            print(f"  去重: {before} → {after} (移除{before - after}条重复)")
    df = mark_degraded(df)
    # v25: 主力资金/期指多空因子富集(读 SQLite 历史;缺数据列为 None → 规则不触发,
    # 历史回填见 scripts/backfill_factor_history.py)
    try:
        from analysis.factor_history import enrich_frame

        df["code6"] = df["code"].map(lambda c: str(c).split(".")[0].strip().zfill(6))
        df = enrich_frame(df)
        print(f"  v25因子富集: 主力资金覆盖 {df['main_net_rate'].notna().mean() * 100:.1f}%, "
              f"期指覆盖 {df['fut_net_chg_3d'].notna().mean() * 100:.1f}%")
    except Exception as exc:  # noqa: BLE001 无因子历史时退回 v24 行为
        print(f"  v25因子富集跳过: {exc}")
    return df


def apply_v8_scoring(df: pd.DataFrame) -> pd.DataFrame:
    """
    v24 纯评分机制（无淘汰，全部转为扣分/加分）

    事后奖惩规则全部来自 analysis/scoring_rules.py (与 live 同一套);
    本函数仅额外应用 sim-only 规则 (score>=76 渐进惩罚 / tech>=80 / 净买入梯度 / 95上限)。
    """
    df = df.copy()
    df['v8_score'] = df['score'].astype(float).copy()
    df['v8_penalty_detail'] = ''
    df['confidence_tier'] = ''

    for idx, row in df.iterrows():
        score = float(row.get('score', 0) or 0)

        # ===== 共享规则 (v24, 与 live 同源) =====
        factors = {
            'rsi': row.get('rsi'),
            'chase_risk': row.get('chase_risk'),
            'change_3d': row.get('change_3d'),
            'change_5d': row.get('change_5d'),
            'day_change': row.get('day_change'),
            'quant_score': row.get('quant_score'),
            'tech_score': row.get('tech_score'),
            'sector_score': row.get('sector_score'),
            'buy_signals': row.get('buy_signals'),
            'sell_signals': row.get('sell_signals'),
            'main_net_rate': row.get('main_net_rate'),      # v25 主力净流入率%
            'fut_net_chg_3d': row.get('fut_net_chg_3d'),    # v25 期指3日净变动(张)
        }
        hits = evaluate_shared_rules(factors)
        penalty = shared_penalty(hits)
        bonus = shared_bonus(hits)
        details = [h.detail for h in hits]

        buy_sig = row.get('buy_signals')
        sell_sig = row.get('sell_signals')
        tech = row.get('tech_score')

        # ===== sim-only 规则 (RULESET 中以 sim_ 前缀登记) =====

        # 原始评分过高（v18: 渐进惩罚，高分扣更多）
        # 回测: score>=90仅25%wr，越高越差，渐进惩罚防止高分股污染A级
        if score >= RULESET['sim_score_high_threshold']:
            score_pen = max(15, int((score - RULESET['sim_score_high_threshold']) * 1.2))
            penalty += score_pen
            details.append(f'评分过高{score:.0f}:-{score_pen}[sim-only]')

        # v11: 技术面虚高惩罚 (B级中tech>=80表现最差)
        if pd.notna(tech) and tech >= 80:
            penalty += RULESET['sim_tech_high_pen']
            details.append(f"技术面虚高{tech:.0f}:-{RULESET['sim_tech_high_pen']:.0f}[sim-only]")

        # v20强化: 量化净买入信号梯度奖励 - (买入-卖出)越多分数越高
        # [sim-only] live 由 buy_count 梯度 + headroom 机制承担
        # v25 审计: net_buy>=10 组 wr 33.3% vs 未触发 40.8%, 奖励负向群体 → 开关可关
        if RULESET.get('sim_net_buy_gradient', 1) and pd.notna(buy_sig) and pd.notna(sell_sig):
            net_buy = buy_sig - sell_sig
            buy_bonus_val = 0
            if net_buy >= 12: buy_bonus_val = 16
            elif net_buy >= 10: buy_bonus_val = 12
            elif net_buy >= 8: buy_bonus_val = 8
            elif net_buy >= 6: buy_bonus_val = 5
            elif net_buy >= 4: buy_bonus_val = 3
            if buy_bonus_val > 0:
                bonus += buy_bonus_val
                details.append(f'净买入{net_buy:.0f}(b{buy_sig:.0f}-s{sell_sig:.0f}):+{buy_bonus_val}[sim-only]')

        # ========== 计算最终评分 ==========
        adj = max(0, score - penalty + bonus)

        # v21: ≥95 上限保护 (实测 ≥95 胜率 42.86%, 比 ≥85 的 61.76% 反而差 19pp)
        if adj > RULESET['sim_adj_cap']:
            adj = RULESET['sim_adj_cap']

        df.at[idx, 'v8_score'] = adj
        df.at[idx, 'v8_penalty_detail'] = '; '.join(details)

        # 置信度分级 (与 RATING_THRESHOLDS 一致: S>=85, A>=78, B>=70, C<70)
        if adj >= 85:
            df.at[idx, 'confidence_tier'] = 'S'
        elif adj >= 78:
            df.at[idx, 'confidence_tier'] = 'A'
        elif adj >= 70:
            df.at[idx, 'confidence_tier'] = 'B'
        else:
            df.at[idx, 'confidence_tier'] = 'C'

    return df


def simulate_v8_selection(df: pd.DataFrame) -> pd.DataFrame:
    """
    v8.0选股: 无淘汰，纯按评分排序，每日Top10
    """
    v8_selections = []
    for date, group in df.groupby('report_date'):
        top = group.nlargest(10, 'v8_score')
        top = top.copy()
        top['v8_rank'] = range(1, len(top) + 1)
        v8_selections.append(top)

    if v8_selections:
        return pd.concat(v8_selections, ignore_index=True)
    return pd.DataFrame()


def compute_stats(df: pd.DataFrame, label: str) -> dict:
    """计算收益统计"""
    stats = {'label': label, 'count': len(df)}
    for period in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
        valid = df[period].dropna()
        if len(valid) > 0:
            stats[f'{period}_mean'] = valid.mean()
            stats[f'{period}_median'] = valid.median()
            stats[f'{period}_winrate'] = (valid > 0).mean() * 100
            stats[f'{period}_avg_win'] = valid[valid > 0].mean() if (valid > 0).any() else 0
            stats[f'{period}_avg_loss'] = valid[valid < 0].mean() if (valid < 0).any() else 0
            pf = abs(valid[valid > 0].sum() / valid[valid < 0].sum()) if (valid < 0).any() and valid[valid < 0].sum() != 0 else float('inf')
            stats[f'{period}_pf'] = pf
        else:
            for suffix in ['_mean', '_median', '_winrate', '_avg_win', '_avg_loss', '_pf']:
                stats[f'{period}{suffix}'] = 0
    return stats


def generate_comparison_report(df_original: pd.DataFrame, df_v8: pd.DataFrame, output_path: str):
    """生成优化前后对比报告"""
    lines = []

    df_orig_top10 = df_original[df_original['rank'] <= 10]
    df_orig_top5 = df_original[df_original['rank'] <= 5]

    orig_all = compute_stats(df_original, '原始全部推荐')
    orig_top10 = compute_stats(df_orig_top10, '原始Top10')
    orig_top5 = compute_stats(df_orig_top5, '原始Top5')
    v8_stats = compute_stats(df_v8, 'v8.0 Top10')

    lines.append("# 评分算法优化 v8.0 - 纯评分无淘汰版回测报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**数据范围**: {df_original['report_date'].min()} ~ {df_original['report_date'].max()}")
    lines.append(f"**原始推荐数**: {len(df_original)} 条")
    lines.append(f"**v8.0入选数**: {len(df_v8)} 条 (每日Top10，无淘汰)")
    lines.append("")

    # 核心对比
    lines.append("## 一、核心指标对比")
    lines.append("")
    lines.append("| 指标 | 原始全部 | 原始Top10 | 原始Top5 | **v8.0 Top10** |")
    lines.append("|------|----------|-----------|----------|----------------|")

    all_stats = [orig_all, orig_top10, orig_top5, v8_stats]

    lines.append(f"| 样本数 | {orig_all['count']} | {orig_top10['count']} | {orig_top5['count']} | "
                 f"**{v8_stats['count']}** |")

    for period, period_label in [('return_1d', '1日收益'), ('return_3d', '3日收益'),
                                  ('return_5d', '5日收益'), ('return_10d', '10日收益')]:
        row_line = f"| {period_label} |"
        for s in all_stats:
            mean = s.get(f'{period}_mean', 0)
            row_line += f" {mean:+.2f}% |"
        lines.append(row_line)

    for period, period_label in [('return_5d', '5日胜率'), ('return_10d', '10日胜率')]:
        row_line = f"| {period_label} |"
        for s in all_stats:
            wr = s.get(f'{period}_winrate', 0)
            row_line += f" {wr:.1f}% |"
        lines.append(row_line)

    pf_row = "| 5日盈亏比 |"
    for s in all_stats:
        pf = s.get('return_5d_pf', 0)
        pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
        pf_row += f" {pf_str} |"
    lines.append(pf_row)
    lines.append("")

    # 置信度分级表现
    lines.append("## 二、v8.0 置信度分级表现")
    lines.append("")
    lines.append("| 置信度 | 说明 | 数量 | 5日均收益 | 5日胜率 | 10日均收益 | 盈亏比 |")
    lines.append("|--------|------|------|-----------|---------|-----------|--------|")

    tiers = [('S', '强烈推荐(adj>=85)'), ('A', '可考虑(adj>=78)'), ('B', '谨慎(adj>=70)'), ('C', '不建议(adj<70)')]
    for tier, tier_desc in tiers:
        subset = df_v8[df_v8['confidence_tier'] == tier]
        if len(subset) == 0:
            lines.append(f"| {tier} | {tier_desc} | 0 | - | - | - | - |")
            continue
        r5 = subset['return_5d'].dropna()
        r10 = subset['return_10d'].dropna()
        if len(r5) > 0:
            pf = abs(r5[r5 > 0].sum() / r5[r5 < 0].sum()) if (r5 < 0).any() and r5[r5 < 0].sum() != 0 else float('inf')
            pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
            r10_mean = r10.mean() if len(r10) > 0 else 0
            lines.append(f"| {tier} | {tier_desc} | {len(subset)} | "
                         f"{r5.mean():+.2f}% | {(r5 > 0).mean()*100:.1f}% | "
                         f"{r10_mean:+.2f}% | {pf_str} |")
        else:
            lines.append(f"| {tier} | {tier_desc} | {len(subset)} | - | - | - | - |")
    lines.append("")

    # 按排名对比
    lines.append("## 三、v8.0按排名表现")
    lines.append("")
    lines.append("| 排名 | 数量 | 5日均收益 | 5日胜率 | 10日均收益 |")
    lines.append("|------|------|-----------|---------|-----------|")
    for rank in range(1, 11):
        sub = df_v8[df_v8['v8_rank'] == rank]
        r5 = sub['return_5d'].dropna()
        r10 = sub['return_10d'].dropna()
        if len(r5) > 0:
            lines.append(f"| {rank} | {len(r5)} | {r5.mean():+.2f}% | {(r5>0).mean()*100:.1f}% | {r10.mean() if len(r10) > 0 else 0:+.2f}% |")
    lines.append("")

    # 评分区间
    lines.append("## 四、v8.0调整后评分区间表现")
    lines.append("")
    lines.append("| 评分区间 | 数量 | 5日均收益 | 5日胜率 | 3日均收益 |")
    lines.append("|----------|------|-----------|---------|-----------|")

    bins = [(85, 999, '85+'), (80, 85, '80-85'), (75, 80, '75-80'),
            (70, 75, '70-75'), (60, 70, '60-70'), (0, 60, '<60')]
    for low, high, label in bins:
        if high == 999:
            subset = df_v8[df_v8['v8_score'] >= low]
        else:
            subset = df_v8[(df_v8['v8_score'] >= low) & (df_v8['v8_score'] < high)]
        if len(subset) == 0:
            lines.append(f"| {label} | 0 | - | - | - |")
            continue
        r5 = subset['return_5d'].dropna()
        r3 = subset['return_3d'].dropna()
        if len(r5) > 0:
            lines.append(f"| {label} | {len(subset)} | "
                         f"{r5.mean():+.2f}% | {(r5 > 0).mean()*100:.1f}% | "
                         f"{r3.mean():+.2f}% |")
    lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return output_path


V20_BASELINE = {  # 全样本分档基线 (v20, 同一数据集), 用于对比展示
    'S': (45, 31.1), 'A': (80, 45.0), 'B': (398, 45.7), 'C': (954, 38.2),
}


def print_tier_table(df_scored: pd.DataFrame, label: str):
    """打印全样本 S/A/B/C 分档表 (n/5日胜率/平均5日收益), 附 v20 基线对比"""
    print(f"\n  {label} — {RULESET_VERSION} 全样本分档表 (vs v20 基线):")
    print(f"  {'档位':>4} | {'n':>5} | {'5d胜率':>8} | {'5d均收益':>9} | {'10d均收益':>9} | v20基线(n/wr)")
    print(f"  {'-'*4}-+-{'-'*5}-+-{'-'*8}-+-{'-'*9}-+-{'-'*9}-+-{'-'*14}")
    for tier in ['S', 'A', 'B', 'C']:
        sub = df_scored[df_scored['confidence_tier'] == tier]
        r5 = sub['return_5d'].dropna()
        r10 = sub['return_10d'].dropna() if 'return_10d' in sub.columns else pd.Series(dtype=float)
        base_n, base_wr = V20_BASELINE.get(tier, (0, 0))
        if len(r5) > 0:
            wr = (r5 > 0).mean() * 100
            print(f"  {tier:>4} | {len(r5):>5} | {wr:>7.1f}% | {r5.mean():>+8.2f}% | "
                  f"{(r10.mean() if len(r10) else 0):>+8.2f}% | {base_n}/{base_wr:.1f}%")
        else:
            print(f"  {tier:>4} | {0:>5} | {'---':>8} | {'---':>9} | {'---':>9} | {base_n}/{base_wr:.1f}%")


def main():
    parser = argparse.ArgumentParser(description=f'{RULESET_VERSION} 纯评分算法模拟回测 (共享规则版)')
    parser.add_argument('--csv', default=None,
                        help='回测数据CSV路径 (默认取 results/ 下最新 backtest_rebuilt_*.csv)')
    parser.add_argument('--include-degraded', action='store_true',
                        help='统计中包含 degraded(数据缺失降级) 行 (默认剔除)')
    args = parser.parse_args()

    print("=" * 70)
    print(f"  {RULESET_VERSION} 纯评分算法（无淘汰, sim/live 共享规则）- 模拟回测")
    print("=" * 70)

    results_dir = os.path.join(project_root, 'results')

    if args.csv:
        csv_path = args.csv if os.path.isabs(args.csv) else os.path.join(project_root, args.csv)
        if not os.path.exists(csv_path):
            print(f"指定的CSV不存在: {csv_path}")
            return
    else:
        # 优先使用rebuilt数据，其次使用analysis数据
        csv_files = sorted([f for f in os.listdir(results_dir) if f.startswith('backtest_rebuilt_') and f.endswith('.csv')])
        if not csv_files:
            csv_files = sorted([f for f in os.listdir(results_dir) if f.startswith('backtest_analysis_') and f.endswith('.csv')])
        if not csv_files:
            print("未找到回测数据CSV文件")
            return
        csv_path = os.path.join(results_dir, csv_files[-1])

    print(f"\n加载回测数据: {os.path.basename(csv_path)}")

    df = load_backtest_data(csv_path)
    print(f"原始数据: {len(df)} 条")

    degraded_n = int(df['degraded'].sum())
    if args.include_degraded:
        print(f"  degraded(数据缺失降级)行: {degraded_n} 条 [--include-degraded: 保留]")
    else:
        df = df[~df['degraded']].reset_index(drop=True)
        print(f"  degraded(数据缺失降级)行: {degraded_n} 条 [默认剔除, 剩余 {len(df)} 条]")

    # Step 1: 纯评分（无淘汰）
    print(f"\n[1/2] 应用{RULESET_VERSION}纯评分（共享规则 + sim-only规则）...")
    df = apply_v8_scoring(df)
    penalized = df[df['v8_penalty_detail'] != '']
    print(f"  被扣分调整: {len(penalized)} 条")
    print(f"  评分分布: min={df['v8_score'].min():.0f}, median={df['v8_score'].median():.0f}, max={df['v8_score'].max():.0f}")

    # 全样本分档表 (与 v20 基线同口径)
    print_tier_table(df, '剔除degraded' if not args.include_degraded else '含degraded')

    # Step 2: 选股（纯排序，无淘汰）
    print(f"\n[2/2] 按评分排序选股 (每日Top10)...")
    df_v8 = simulate_v8_selection(df)
    print(f"  {RULESET_VERSION}入选: {len(df_v8)} 条")

    # 生成报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(results_dir, f"{RULESET_VERSION}_scoring_comparison_{timestamp}.md")
    generate_comparison_report(df, df_v8, report_path)
    print(f"\n报告已生成: {report_path}")

    # 输出关键对比
    print(f"\n{'=' * 70}")
    print(f"  关键对比结果")
    print(f"{'=' * 70}")

    orig_top10 = df[df['rank'] <= 10]
    orig_5d = orig_top10['return_5d'].dropna()
    v8_5d = df_v8['return_5d'].dropna()

    print(f"\n  原始Top10:")
    print(f"    5日平均收益: {orig_5d.mean():+.2f}%")
    print(f"    5日胜率: {(orig_5d > 0).mean()*100:.1f}%")

    print(f"\n  {RULESET_VERSION} Top10 (纯评分排序):")
    print(f"    5日平均收益: {v8_5d.mean():+.2f}%")
    print(f"    5日胜率: {(v8_5d > 0).mean()*100:.1f}%")

    print(f"\n  改善幅度:")
    print(f"    5日收益: {v8_5d.mean() - orig_5d.mean():+.2f}%")
    print(f"    5日胜率: {(v8_5d > 0).mean()*100 - (orig_5d > 0).mean()*100:+.1f}%")

    # 置信度分级 (每日Top10入选子集)
    print(f"\n  {RULESET_VERSION} 置信度分级 (每日Top10子集):")
    for tier, tier_desc in [('S', '强烈推荐'), ('A', '推荐'), ('B', '关注'), ('C', '观望')]:
        tier_data = df_v8[df_v8['confidence_tier'] == tier]
        tier_5d = tier_data['return_5d'].dropna()
        if len(tier_5d) > 0:
            print(f"    {tier}级({tier_desc}): n={len(tier_5d)}, 5d_wr={(tier_5d > 0).mean()*100:.1f}%, avg={tier_5d.mean():+.2f}%")

    print(f"\n{'=' * 70}")


if __name__ == '__main__':
    main()
