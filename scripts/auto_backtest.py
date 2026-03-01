#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动回测模块 v8.0
==================
在每日投资机会挖掘完成后自动运行回测验证，
追踪历史推荐的实际收益表现。

功能:
1. 记录每次推荐的股票信息
2. 自动获取推荐股票的后续收益（1d/3d/5d/10d）
3. 生成回测统计报告
4. 与历史回测基线对比，监控算法退化

使用方式:
  python scripts/auto_backtest.py                    # 回测所有历史推荐
  python scripts/auto_backtest.py --days 7            # 回测最近7天的推荐
  python scripts/auto_backtest.py --report-only        # 仅生成报告（不更新收益数据）
"""

import os
import sys
import json
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)

# 回测数据存储路径
BACKTEST_DIR = os.path.join(project_root, 'results', 'backtest')
RECOMMENDATIONS_FILE = os.path.join(BACKTEST_DIR, 'recommendations.csv')
BACKTEST_REPORT_DIR = os.path.join(BACKTEST_DIR, 'reports')

# 回测基线（v8.0算法优化 - 去重后Top10 + 置信度分级，score>=78阈值）
BASELINE = {
    'version': 'v8.0',
    'avg_5d': 4.48,     # score>=78的5日平均收益（去重后）
    'wr_5d': 66.7,      # score>=78的5日胜率（去重后）
    'avg_10d': 0,        # 待回测确认
    'pf_5d': 4.82,      # score>=78的盈亏比（去重后）
    'bull_rate': 35.9,
}


def ensure_dirs():
    """确保回测目录存在"""
    os.makedirs(BACKTEST_DIR, exist_ok=True)
    os.makedirs(BACKTEST_REPORT_DIR, exist_ok=True)


def save_recommendations(passed_stocks: List[Dict], report_date: str = None):
    """
    保存当日推荐股票到回测记录

    Args:
        passed_stocks: 通过筛选的股票列表（来自run_opportunity_discovery）
        report_date: 报告日期，默认今天
    """
    ensure_dirs()

    if not report_date:
        report_date = datetime.now().strftime('%Y-%m-%d')

    records = []
    for i, stock in enumerate(passed_stocks):
        scoring = stock.get('scoring_result', {})
        details = scoring.get('details', {})
        scores = scoring.get('scores', {})
        price_changes = details.get('price_changes', {})
        momentum = details.get('momentum', {})
        quant = details.get('quantitative', {})

        record = {
            'report_date': report_date,
            'rank': i + 1,
            'code': stock.get('stock_code', ''),
            'name': stock.get('stock_name', ''),
            'score': scoring.get('total_score', 0),
            'chase_risk': momentum.get('chase_risk_score', 0),
            'buy_signals': quant.get('buy_count', 0),
            'sell_signals': quant.get('sell_count', 0),
            'rsi': details.get('technical', {}).get('RSI', 0),
            'day_change': price_changes.get('change_1d', 0),
            'change_3d': price_changes.get('change_3d', 0),
            'change_5d': price_changes.get('change_5d', 0),
            'sector_score': scores.get('sector', 0),
            'quant_score': scores.get('quantitative', 0),
            'tech_score': scores.get('technical', 0),
            'momentum_pattern': json.dumps(scoring.get('momentum_pattern', []), ensure_ascii=False),
            'buy_price': 0,  # 待填充
            'return_1d': None,
            'return_3d': None,
            'return_5d': None,
            'return_10d': None,
        }
        records.append(record)

    if not records:
        logger.info("没有推荐股票需要记录")
        return

    new_df = pd.DataFrame(records)

    # 追加到已有记录
    if os.path.exists(RECOMMENDATIONS_FILE):
        existing = pd.read_csv(RECOMMENDATIONS_FILE)
        # 去除同日重复
        existing = existing[existing['report_date'] != report_date]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(RECOMMENDATIONS_FILE, index=False, encoding='utf-8-sig')
    logger.info(f"已保存 {len(records)} 条推荐记录到 {RECOMMENDATIONS_FILE}")


def update_returns(days_back: int = 30):
    """
    更新历史推荐的实际收益数据

    Args:
        days_back: 回溯天数
    """
    if not os.path.exists(RECOMMENDATIONS_FILE):
        logger.warning("没有历史推荐记录")
        return

    df = pd.read_csv(RECOMMENDATIONS_FILE)

    # 找需要更新的记录（有空收益的）
    needs_update = df[
        (df['return_5d'].isna()) &
        (pd.to_datetime(df['report_date']) <= datetime.now() - timedelta(days=1))
    ]

    if len(needs_update) == 0:
        logger.info("所有记录已有收益数据，无需更新")
        return

    logger.info(f"需要更新收益的记录: {len(needs_update)} 条")

    # 尝试导入数据获取模块
    try:
        from scripts.fetch_data import fetch_stock_data
        has_fetcher = True
    except ImportError:
        has_fetcher = False

    try:
        import baostock as bs
        bs.login()
        has_baostock = True
    except Exception:
        has_baostock = False

    updated_count = 0
    for idx, row in needs_update.iterrows():
        code = str(row['code'])
        report_date = row['report_date']

        try:
            report_dt = pd.to_datetime(report_date)
            days_since = (datetime.now() - report_dt).days

            if days_since < 1:
                continue

            # 使用baostock获取后续价格
            if has_baostock:
                # 转换代码格式
                if code.startswith('6'):
                    bs_code = f'sh.{code}'
                else:
                    bs_code = f'sz.{code}'

                start_date = report_dt.strftime('%Y-%m-%d')
                end_date = (report_dt + timedelta(days=20)).strftime('%Y-%m-%d')

                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,close",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2"
                )

                prices = []
                while (rs.error_code == '0') and rs.next():
                    prices.append(rs.get_row_data())

                if len(prices) >= 2:
                    buy_price = float(prices[0][1])  # 推荐当日收盘价
                    df.at[idx, 'buy_price'] = buy_price

                    if len(prices) >= 2:
                        df.at[idx, 'return_1d'] = (float(prices[1][1]) / buy_price - 1) * 100
                    if len(prices) >= 4:
                        df.at[idx, 'return_3d'] = (float(prices[3][1]) / buy_price - 1) * 100
                    if len(prices) >= 6:
                        df.at[idx, 'return_5d'] = (float(prices[5][1]) / buy_price - 1) * 100
                    if len(prices) >= 11:
                        df.at[idx, 'return_10d'] = (float(prices[10][1]) / buy_price - 1) * 100

                    updated_count += 1

        except Exception as e:
            logger.warning(f"更新 {code} 收益失败: {e}")
            continue

    if has_baostock:
        try:
            bs.logout()
        except Exception:
            pass

    df.to_csv(RECOMMENDATIONS_FILE, index=False, encoding='utf-8-sig')
    logger.info(f"已更新 {updated_count} 条记录的收益数据")


def generate_backtest_report(days_back: int = None) -> str:
    """
    生成回测报告

    Args:
        days_back: 回溯天数，None表示全部

    Returns:
        报告文件路径
    """
    ensure_dirs()

    if not os.path.exists(RECOMMENDATIONS_FILE):
        logger.warning("没有历史推荐记录")
        return ""

    df = pd.read_csv(RECOMMENDATIONS_FILE)

    if days_back:
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        df = df[df['report_date'] >= cutoff]

    if len(df) == 0:
        logger.warning("没有符合条件的回测数据")
        return ""

    # 只分析有收益数据的
    df_with_returns = df[df['return_5d'].notna()].copy()

    lines = []
    lines.append(f"# v7.0 自动回测报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**数据范围**: {df['report_date'].min()} ~ {df['report_date'].max()}")
    lines.append(f"**总推荐数**: {len(df)} 条")
    lines.append(f"**已有收益数据**: {len(df_with_returns)} 条")
    lines.append(f"")

    if len(df_with_returns) == 0:
        lines.append("暂无收益数据（推荐后需等待交易日获取后续价格）")
    else:
        # 核心统计
        lines.append("## 一、核心指标")
        lines.append("")
        lines.append("| 指标 | 实盘 | v5.5基线 | 差异 |")
        lines.append("|------|------|----------|------|")

        for period, label in [('return_1d', '1日'), ('return_3d', '3日'),
                              ('return_5d', '5日'), ('return_10d', '10日')]:
            valid = df_with_returns[period].dropna()
            if len(valid) > 0:
                avg = valid.mean()
                wr = (valid > 0).mean() * 100
                baseline_avg = BASELINE.get(f'avg_{period.split("_")[1]}', 0)
                baseline_wr = BASELINE.get(f'wr_{period.split("_")[1]}', 0)
                diff_avg = avg - baseline_avg if baseline_avg else 0
                diff_wr = wr - baseline_wr if baseline_wr else 0

                lines.append(f"| {label}收益 | {avg:+.2f}% | {baseline_avg:+.2f}% | {diff_avg:+.2f}% |")
                lines.append(f"| {label}胜率 | {wr:.1f}% | {baseline_wr:.1f}% | {diff_wr:+.1f}% |")

        # 盈亏比
        valid_5d = df_with_returns['return_5d'].dropna()
        if len(valid_5d) > 0:
            wins = valid_5d[valid_5d > 0]
            losses = valid_5d[valid_5d < 0]
            if len(losses) > 0 and losses.sum() != 0:
                pf = abs(wins.sum() / losses.sum())
            else:
                pf = float('inf')
            pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
            lines.append(f"| 5日盈亏比 | {pf_str} | {BASELINE['pf_5d']:.2f} | - |")

        # 牛股率
        df_with_returns['is_bull'] = (df_with_returns['return_5d'] > 10) | (df_with_returns['return_10d'].fillna(0) > 15)
        bull_rate = df_with_returns['is_bull'].mean() * 100
        lines.append(f"| 牛股率 | {bull_rate:.1f}% | {BASELINE['bull_rate']:.1f}% | {bull_rate - BASELINE['bull_rate']:+.1f}% |")

        lines.append("")

        # 月度分解
        lines.append("## 二、月度表现")
        lines.append("")
        lines.append("| 月份 | 推荐数 | 有收益 | 5日收益 | 5日胜率 | 牛股数 |")
        lines.append("|------|--------|--------|---------|---------|--------|")

        df_with_returns['month'] = pd.to_datetime(df_with_returns['report_date']).dt.strftime('%Y-%m')
        for month in sorted(df_with_returns['month'].unique()):
            m = df_with_returns[df_with_returns['month'] == month]
            m_all = df[pd.to_datetime(df['report_date']).dt.strftime('%Y-%m') == month]
            valid = m['return_5d'].dropna()
            if len(valid) > 0:
                lines.append(f"| {month} | {len(m_all)} | {len(valid)} | "
                           f"{valid.mean():+.2f}% | {(valid > 0).mean() * 100:.1f}% | "
                           f"{m['is_bull'].sum()} |")

        lines.append("")

        # 动量模式效果
        lines.append("## 三、动量识别效果")
        lines.append("")
        has_momentum = df_with_returns[df_with_returns['momentum_pattern'].notna() &
                                        (df_with_returns['momentum_pattern'] != '[]')]
        no_momentum = df_with_returns[df_with_returns['momentum_pattern'].isna() |
                                       (df_with_returns['momentum_pattern'] == '[]')]

        if len(has_momentum) > 0:
            m_valid = has_momentum['return_5d'].dropna()
            lines.append(f"- 有动量标记: {len(has_momentum)} 条, "
                        f"5d={m_valid.mean():+.2f}%, wr={(m_valid > 0).mean() * 100:.1f}%")
        if len(no_momentum) > 0:
            n_valid = no_momentum['return_5d'].dropna()
            lines.append(f"- 无动量标记: {len(no_momentum)} 条, "
                        f"5d={n_valid.mean():+.2f}%, wr={(n_valid > 0).mean() * 100:.1f}%")

        lines.append("")

        # 评分区间表现
        lines.append("## 四、评分区间表现")
        lines.append("")
        lines.append("| 评分区间 | 数量 | 5日收益 | 5日胜率 |")
        lines.append("|----------|------|---------|---------|")

        for low, high, label in [(80, 100, '优秀(80+)'), (70, 80, '良好(70-80)'),
                                  (60, 70, '一般(60-70)'), (0, 60, '较差(<60)')]:
            sub = df_with_returns[(df_with_returns['score'] >= low) & (df_with_returns['score'] < high)]
            valid = sub['return_5d'].dropna()
            if len(valid) > 0:
                lines.append(f"| {label} | {len(valid)} | {valid.mean():+.2f}% | "
                           f"{(valid > 0).mean() * 100:.1f}% |")

        # 算法退化警告
        lines.append("")
        lines.append("## 五、算法健康度")
        lines.append("")

        if len(valid_5d) >= 10:
            current_wr = (valid_5d > 0).mean() * 100
            current_avg = valid_5d.mean()

            health_status = "正常"
            if current_wr < BASELINE['wr_5d'] - 10:
                health_status = "**警告: 胜率显著下降**"
            elif current_wr < BASELINE['wr_5d'] - 5:
                health_status = "注意: 胜率有所下降"
            if current_avg < 0:
                health_status = "**警告: 平均收益为负**"

            lines.append(f"- 健康状态: {health_status}")
            lines.append(f"- 5日胜率: {current_wr:.1f}% (基线{BASELINE['wr_5d']:.1f}%)")
            lines.append(f"- 5日收益: {current_avg:+.2f}% (基线{BASELINE['avg_5d']:+.2f}%)")

            # 最近5天趋势
            recent = df_with_returns.sort_values('report_date').tail(20)
            recent_valid = recent['return_5d'].dropna()
            if len(recent_valid) >= 5:
                recent_wr = (recent_valid > 0).mean() * 100
                lines.append(f"- 最近20条胜率: {recent_wr:.1f}%")
        else:
            lines.append(f"- 数据量不足(仅{len(valid_5d)}条)，暂无法评估")

    # 保存报告
    report_name = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(BACKTEST_REPORT_DIR, report_name)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f"回测报告已生成: {report_path}")

    # 输出关键指标到控制台
    if len(df_with_returns) > 0:
        valid_5d = df_with_returns['return_5d'].dropna()
        if len(valid_5d) > 0:
            print(f"\n{'='*50}")
            print(f"  v7.0 自动回测结果")
            print(f"{'='*50}")
            print(f"  推荐总数: {len(df)}")
            print(f"  有收益数据: {len(valid_5d)}")
            print(f"  5日平均收益: {valid_5d.mean():+.2f}% (基线: {BASELINE['avg_5d']:+.2f}%)")
            print(f"  5日胜率: {(valid_5d > 0).mean()*100:.1f}% (基线: {BASELINE['wr_5d']:.1f}%)")
            valid_10d = df_with_returns['return_10d'].dropna()
            if len(valid_10d) > 0:
                print(f"  10日平均收益: {valid_10d.mean():+.2f}% (基线: {BASELINE['avg_10d']:+.2f}%)")
            print(f"{'='*50}")

    return report_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description='v7.0 自动回测系统')
    parser.add_argument('--days', type=int, default=None, help='回溯天数')
    parser.add_argument('--report-only', action='store_true', help='仅生成报告，不更新收益数据')
    parser.add_argument('--update-only', action='store_true', help='仅更新收益数据，不生成报告')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if not args.report_only:
        update_returns(days_back=args.days or 30)

    if not args.update_only:
        generate_backtest_report(days_back=args.days)


if __name__ == '__main__':
    main()
