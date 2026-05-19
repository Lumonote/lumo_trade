#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v20 纯评分算法模拟回测 - 无淘汰版
====================
基于已有的回测数据(backtest_analysis CSV)，模拟应用v20的纯评分规则，
对比优化前后的收益表现。

v20核心变更(vs v19):
- 追高风险惩罚降低: chase>=80: -20→-15 (回测零影响, live减少误杀)
- 5日急涨阈值放宽: >18%/-15→>20%/-10 (回测零影响, live减少错过主升)
- 板块死区保持flat -10 (回测验证: 分段8/5/3会破坏A>B排序)
- [仅live] 惩罚上限: 30→25, 动量回收上限: 15→12

v19核心变更(vs v18):
- 新增量化买入信号梯度奖励(仅sell=0, 黄金信号57.8%wr/+5.03%):
  buy>=4:+4, >=6:+6, >=8:+8, >=10:+10 (sell>=1不奖励)
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


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
    return df


def apply_v8_scoring(df: pd.DataFrame) -> pd.DataFrame:
    """
    v8.0 纯评分机制（无淘汰，全部转为扣分/加分）

    所有风险因子转为扣分（无上限），让评分自然拉开差距:
    - 极端风险（原淘汰条件）: 重扣 -15~-25
    - 高风险: 中扣 -5~-15
    - 低风险利好: 加分 +3~+10
    - 组合因子: 额外加减分
    """
    df = df.copy()
    df['v8_score'] = df['score'].astype(float).copy()
    df['v8_penalty_detail'] = ''
    df['confidence_tier'] = ''

    for idx, row in df.iterrows():
        penalty = 0
        bonus = 0
        details = []
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

        # ========== 风险扣分（原淘汰条件转为重扣）==========

        # RSI 极端超买
        if pd.notna(rsi):
            if rsi >= 85:
                penalty += 25
                details.append(f'RSI极端{rsi:.0f}:-25')
            elif rsi > 80:
                penalty += 15  # v15: 保持15(RSI80惩罚加大无效果)
                details.append(f'RSI超买{rsi:.0f}:-15')
            elif rsi > 75:
                pass  # v13优化: 移除RSI 75-80轻度惩罚

        # 日涨幅风险
        if pd.notna(day_chg):
            if day_chg >= 20:
                penalty += 25
                details.append(f'暴涨{day_chg:.0f}%:-25')
            elif day_chg >= 9.5:
                # v14优化: 涨停首板(3日<15%)不惩罚(回测53.8%胜率+1.73%)
                if pd.notna(chg_3d) and chg_3d >= 15:
                    penalty += 5  # v14: 连板涨停才惩罚
                    details.append(f'连板涨停{day_chg:.0f}%+3d{chg_3d:.0f}%:-5')
                else:
                    details.append(f'涨停首板{day_chg:.0f}%:不惩罚')
            elif day_chg >= 7:
                penalty += 3  # v9: 轻度扣分
                details.append(f'中涨{day_chg:.0f}%:-3')
            elif day_chg >= 5:
                penalty += 5  # v9优化: 3→5
                details.append(f'小涨{day_chg:.0f}%:-5')

        # 短期涨幅风险 (v17: 修复>25判断永远不触发的BUG, v20: >18→>20, 15→10)
        if pd.notna(chg_5d) and chg_5d > 25:
            penalty += 25
            details.append(f'5日暴涨{chg_5d:.0f}%:-25')
        elif pd.notna(chg_5d) and chg_5d > 20:
            penalty += 10  # v20优化: 阈值18→20, 惩罚15→10
            details.append(f'5日涨{chg_5d:.0f}%:-10')

        if pd.notna(chg_3d):
            if chg_3d > 20:
                penalty += 15  # v17优化: 20→15
                details.append(f'3日暴涨{chg_3d:.0f}%:-15')
            elif chg_3d > 15:
                penalty += 10  # v17优化: 16→10
                details.append(f'3日涨{chg_3d:.0f}%:-10')
            elif chg_3d > 10:
                penalty += 8   # v17优化: 12→8
                details.append(f'3日涨{chg_3d:.0f}%:-8')

        # 追高风险 (v20: 20→15, 保留风控但不过度一票否决)
        if pd.notna(chase):
            if chase >= 80:
                penalty += 15  # v20优化: 20→15
                details.append(f'追高极端{chase:.0f}:-15')
            elif chase >= 60:
                penalty += 3   # v11优化: 6→3
                details.append(f'追高偏高{chase:.0f}:-3')

        # 技术面偏低 — v18移除（回测验证反效果: 被罚wr=43.2% > 未罚40.0%）
        # tech<60惩罚实际打击了趋势启动阶段的股票，移除后B+增加39%
        # if pd.notna(tech) and tech < 60:
        #     ...penalty += 8

        # v11新增: 技术面虚高惩罚 (B级中tech>=80表现最差)
        if pd.notna(tech) and tech >= 80:
            penalty += 3   # v11新增
            details.append(f'技术面虚高{tech:.0f}:-3')

        # 板块过热
        if pd.notna(sector):
            if sector >= 95:
                penalty += 12  # v12优化: 10→12
                details.append(f'板块过热{sector:.0f}:-12')
            elif 60 <= sector <= 75:
                # v21: U 型连续函数代替 flat -10, 消除 60/75 边界跳变
                # peak 在 67.5(死区中心), 边界 60/75 处自然为 0
                distance = abs(sector - 67.5) / 7.5
                sector_pen = round(10 * (1 - distance))
                if sector_pen > 0:
                    penalty += sector_pen
                    details.append(f'板块死区{sector:.0f}:-{sector_pen}')

        # 原始评分过高（v18: 渐进惩罚，高分扣更多）
        # 回测: score>=90仅25%wr，越高越差，渐进惩罚防止高分股污染A级
        if score >= 76:
            score_pen = max(15, int((score - 76) * 1.2))
            penalty += score_pen
            details.append(f'评分过高{score:.0f}:-{score_pen}')

        # 组合风险: RSI>80 + 3d>10%
        if pd.notna(rsi) and pd.notna(chg_3d) and rsi > 80 and chg_3d > 10:
            penalty += 10
            details.append(f'RSI超买+3d涨:-10')

        # 组合风险: 5d>15% + RSI>72
        if pd.notna(chg_5d) and pd.notna(rsi) and chg_5d > 15 and rsi > 72:
            penalty += 10
            details.append(f'5d涨+RSI偏高:-10')

        # 量化分反转 — 已移除(v8.0): 与买入信号奖励矛盾
        # 买入信号多→量化分高→又扣分，逻辑不自洽

        # 信号拥挤
        if pd.notna(buy_sig) and buy_sig >= 15:
            penalty += 8   # v16优化: 1→8(信号拥挤惩罚加大)
            details.append(f'信号拥挤{buy_sig:.0f}:-8')

        # v18新增: 卖出信号>=3惩罚 (sell<2: 48.3%wr vs sell>=2: 36.9%wr, delta=-11.4%)
        if pd.notna(sell_sig) and sell_sig >= 3:
            penalty += 5
            details.append(f'卖出信号多{sell_sig:.0f}:-5')

        # v18新增 + v21加重: 量化分极高惩罚 (qs>=90: 33%wr/-3.53%, qs>=95 更糟)
        # 30个量化模型一致看好 = 过度共识 = 反指标, v18 仅扣 5 分力度不够
        if pd.notna(qs) and qs >= 95:
            penalty += 18  # v21新增: 极端共识重扣
            details.append(f'量化分极端{qs:.0f}:-18')
        elif pd.notna(qs) and qs >= 90:
            penalty += 12  # v21: 5→12 (反指标力度匹配实际负收益)
            details.append(f'量化分极高{qs:.0f}:-12')

        # 卖出占优 — v9优化: 移除（回测验证无效）
        # if pd.notna(sell_sig) and pd.notna(buy_sig) and sell_sig > buy_sig:

        # v8.0: 卖出信号绝对数量 — v9优化: 移除（回测验证无效）
        # if pd.notna(sell_sig) and sell_sig >= 5:

        # v10优化: 追高+超买组合（移除，与独立惩罚冗余）
        # if pd.notna(chase) and pd.notna(rsi) and chase > 30 and rsi > 60:

        # ========== 利好加分 ==========

        # v15新增: 零卖出信号奖励 (sell=0: 53.8%胜率/+5.02%)
        if pd.notna(sell_sig) and sell_sig == 0:
            sell0_bonus = 4
            # 涨停+sell=0超强组合 (66.7%胜率/+10.97%)
            if pd.notna(day_chg) and day_chg >= 9.5:
                sell0_bonus = 8
                details.append(f'涨停+零卖出:+{sell0_bonus}')
            else:
                details.append(f'零卖出信号:+{sell0_bonus}')
            bonus += sell0_bonus

        # RSI超卖
        if pd.notna(rsi) and rsi < 35:
            bonus += 5   # v13优化: 10→5
            details.append(f'RSI超卖{rsi:.0f}:+5')

        # v15优化: RSI黄金区间收窄 (40-50胜率52.5%/+2.79%, 50-60急剧恶化36.7%)
        if pd.notna(rsi) and 40 <= rsi <= 50:
            bonus += 4   # v15优化: 3→4, 区间42-53→40-50
            details.append(f'RSI黄金区{rsi:.0f}:+4')

        # v21新增: RSI 50-60 涨停后回落区惩罚 (实测 36.7%wr/-1.37%, 严重反常)
        # 该区间通常是涨停次日位置, 大概率回落, 之前未扣分等于鼓励
        if pd.notna(rsi) and 50 < rsi < 60:
            penalty += 4
            details.append(f'RSI回落区{rsi:.0f}:-4')

        # 买入信号占优 — v10优化: 移除（全量回测验证无效，buy_signals与收益负相关）
        # if pd.notna(buy_sig) and pd.notna(sell_sig) and buy_sig >= 5 and sell_sig > 0 and buy_sig >= sell_sig * 2:

        # 涨停+低追高 = 妖股起点
        if pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase < 50:
            if not (pd.notna(buy_sig) and buy_sig > 8):  # 非信号拥挤
                bonus += 10  # v13优化: 12→10
                details.append(f'首板低chase{chase:.0f}:+10')
        elif pd.notna(day_chg) and day_chg >= 9.5 and pd.notna(chase) and chase >= 50:
            # v17新增: 涨停首板+高chase也有正收益(51.0%wr)
            bonus += 8
            details.append(f'首板高chase{chase:.0f}:+8')
        elif pd.notna(day_chg) and day_chg >= 7 and pd.notna(chase) and chase < 40:
            bonus += 12  # v13优化: 15→12
            details.append(f'强势低chase{chase:.0f}:+12')

        # 动量启动
        if pd.notna(day_chg) and 3 <= day_chg < 10 and pd.notna(chase) and chase < 50:
            bonus += 5   # v9优化: 8→5
            details.append(f'动量启动:+5')

        # 量化适中 — v9优化: 移除（全量回测验证无效）
        # if pd.notna(qs) and 55 <= qs <= 80:

        # v18新增: 量化分偏低奖励 (qs<50: 59.7%wr/+3.71%, 少数模型看好=超额收益)
        if pd.notna(qs) and qs < 50:
            bonus += 5
            details.append(f'量化分低{qs:.0f}:+5')

        # v20强化: 量化净买入信号梯度奖励 - (买入-卖出)越多分数越高
        if pd.notna(buy_sig) and pd.notna(sell_sig):
            net_buy = buy_sig - sell_sig
            buy_bonus_val = 0
            if net_buy >= 12: buy_bonus_val = 16
            elif net_buy >= 10: buy_bonus_val = 12
            elif net_buy >= 8: buy_bonus_val = 8
            elif net_buy >= 6: buy_bonus_val = 5
            elif net_buy >= 4: buy_bonus_val = 3
            if buy_bonus_val > 0:
                bonus += buy_bonus_val
                details.append(f'净买入{net_buy:.0f}(b{buy_sig:.0f}-s{sell_sig:.0f}):+{buy_bonus_val}')
                details.append(f'买入信号{buy_sig:.0f}(s0):+{buy_bonus_val}')

        # v8.0: 低追高+低RSI组合
        if pd.notna(chase) and pd.notna(rsi) and chase < 25 and rsi < 50:
            bonus += 8   # v12优化: 5→8
            details.append(f'低风险动量:+8')

        # ========== 计算最终评分 ==========
        adj = max(0, score - penalty + bonus)

        # v21新增: ≥95 上限保护 (实测 ≥95 胜率 42.86%, 比 ≥85 的 61.76% 反而差 19pp)
        # 任何评分超过 95 都强制压回 95, 避免极端共识冲顶
        if adj > 95:
            adj = 95

        # 评分甜蜜区奖励 — v10优化: 移除（回测验证无正向效果）
        # if 63 <= adj <= 69:

        # 过高评分惩罚 — v11优化: 移除（阻止S级产生，回测验证无正向效果）
        # if adj >= 79:
        #     adj -= 8

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


def main():
    print("=" * 70)
    print("  v8.0 纯评分算法（无淘汰）- 模拟回测")
    print("=" * 70)

    results_dir = os.path.join(project_root, 'results')

    # 优先使用rebuilt数据，其次使用analysis数据
    csv_files = sorted([f for f in os.listdir(results_dir) if f.startswith('backtest_rebuilt_') and f.endswith('.csv')])
    if not csv_files:
        csv_files = sorted([f for f in os.listdir(results_dir) if f.startswith('backtest_analysis_') and f.endswith('.csv')])
    if not csv_files:
        print("未找到回测数据CSV文件")
        return

    csv_path = os.path.join(results_dir, csv_files[-1])
    print(f"\n加载回测数据: {csv_files[-1]}")

    df = load_backtest_data(csv_path)
    print(f"原始数据: {len(df)} 条")

    # Step 1: 纯评分（无淘汰）
    print("\n[1/2] 应用v8.0纯评分（所有风险转为扣分）...")
    df = apply_v8_scoring(df)
    penalized = df[df['v8_penalty_detail'] != '']
    print(f"  被扣分调整: {len(penalized)} 条")
    print(f"  评分分布: min={df['v8_score'].min():.0f}, median={df['v8_score'].median():.0f}, max={df['v8_score'].max():.0f}")

    # Step 2: 选股（纯排序，无淘汰）
    print("\n[2/2] 按评分排序选股 (每日Top10)...")
    df_v8 = simulate_v8_selection(df)
    print(f"  v8.0入选: {len(df_v8)} 条")

    # 生成报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(results_dir, f"v80_scoring_comparison_{timestamp}.md")
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

    print(f"\n  v8.0 Top10 (纯评分排序):")
    print(f"    5日平均收益: {v8_5d.mean():+.2f}%")
    print(f"    5日胜率: {(v8_5d > 0).mean()*100:.1f}%")

    print(f"\n  改善幅度:")
    print(f"    5日收益: {v8_5d.mean() - orig_5d.mean():+.2f}%")
    print(f"    5日胜率: {(v8_5d > 0).mean()*100 - (orig_5d > 0).mean()*100:+.1f}%")

    # 置信度分级
    print(f"\n  v8.0 置信度分级:")
    for tier, tier_desc in [('S', '强烈推荐'), ('A', '推荐'), ('B', '关注'), ('C', '观望')]:
        tier_data = df_v8[df_v8['confidence_tier'] == tier]
        tier_5d = tier_data['return_5d'].dropna()
        if len(tier_5d) > 0:
            print(f"    {tier}级({tier_desc}): n={len(tier_5d)}, 5d_wr={(tier_5d > 0).mean()*100:.1f}%, avg={tier_5d.mean():+.2f}%")

    print(f"\n{'=' * 70}")


if __name__ == '__main__':
    main()
