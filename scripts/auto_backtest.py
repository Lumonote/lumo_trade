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
SCORING_RUNTIME_CONFIG = os.path.join(project_root, 'config', 'scoring_runtime_config.json')

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


def _normalize_stock_code(code_value) -> str:
    text = str(code_value).strip()
    if not text:
        return ''
    if text.endswith('.0'):
        text = text[:-2]
    if '.' in text:
        text = text.split('.')[0]
    return text.zfill(6)


def _to_baostock_code(code: str) -> str:
    """将 6 位股票代码映射为 baostock 市场代码。"""
    normalized = _normalize_stock_code(code)
    if not normalized:
        return ''

    if normalized.startswith(('5', '6', '9')):
        return f'sh.{normalized}'
    if normalized.startswith(('0', '1', '2', '3')):
        return f'sz.{normalized}'
    return ''


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
        code = _normalize_stock_code(row['code'])
        report_date = row['report_date']

        try:
            report_dt = pd.to_datetime(report_date)
            days_since = (datetime.now() - report_dt).days

            if days_since < 1:
                continue

            # 使用baostock获取后续价格
            if has_baostock:
                bs_code = _to_baostock_code(code)
                if not bs_code:
                    logger.debug(f"跳过baostock暂不支持的代码: {code}")
                    continue

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

    score_threshold = 80

    # 只分析有收益数据的
    df_with_returns = df[df['return_5d'].notna()].copy()
    score_series = pd.to_numeric(df_with_returns.get('score'), errors='coerce')
    df_core = df_with_returns[score_series >= score_threshold].copy()

    lines = []
    lines.append(f"# v7.0 自动回测报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**数据范围**: {df['report_date'].min()} ~ {df['report_date'].max()}")
    lines.append(f"**总推荐数**: {len(df)} 条")
    lines.append(f"**已有收益数据**: {len(df_with_returns)} 条")
    lines.append(f"**核心统计样本**: {len(df_core)} 条（评分 >= {score_threshold}）")
    lines.append(f"")

    if len(df_with_returns) == 0:
        lines.append("暂无收益数据（推荐后需等待交易日获取后续价格）")
    elif len(df_core) == 0:
        lines.append(f"暂无评分 >= {score_threshold} 的有效收益样本")
    else:
        # 核心统计
        lines.append(f"## 一、核心指标（仅统计评分 >= {score_threshold}）")
        lines.append("")
        lines.append("| 指标 | 实盘 | v5.5基线 | 差异 |")
        lines.append("|------|------|----------|------|")

        for period, label in [('return_1d', '1日'), ('return_3d', '3日'),
                              ('return_5d', '5日'), ('return_10d', '10日')]:
            valid = df_core[period].dropna()
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
        valid_5d = df_core['return_5d'].dropna()
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
        df_core['is_bull'] = (df_core['return_5d'] > 10) | (df_core['return_10d'].fillna(0) > 15)
        bull_rate = df_core['is_bull'].mean() * 100
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
            lines.append(f"- 统计口径: 仅评分 >= {score_threshold} 样本")
            lines.append(f"- 5日胜率: {current_wr:.1f}% (基线{BASELINE['wr_5d']:.1f}%)")
            lines.append(f"- 5日收益: {current_avg:+.2f}% (基线{BASELINE['avg_5d']:+.2f}%)")

            # 最近5天趋势
            recent = df_core.sort_values('report_date').tail(20)
            recent_valid = recent['return_5d'].dropna()
            if len(recent_valid) >= 5:
                recent_wr = (recent_valid > 0).mean() * 100
                lines.append(f"- 最近20条胜率: {recent_wr:.1f}%")
        else:
            lines.append(f"- 数据量不足(仅{len(valid_5d)}条评分 >= {score_threshold} 样本)，暂无法评估")

    # 保存报告
    report_name = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(BACKTEST_REPORT_DIR, report_name)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    logger.info(f"回测报告已生成: {report_path}")

    # 输出关键指标到控制台
    if len(df_core) > 0:
        valid_5d = df_core['return_5d'].dropna()
        if len(valid_5d) > 0:
            print(f"\n{'='*50}")
            print(f"  v7.0 自动回测结果")
            print(f"{'='*50}")
            print(f"  推荐总数: {len(df)}")
            print(f"  核心统计样本(>=80分): {len(valid_5d)}")
            print(f"  5日平均收益: {valid_5d.mean():+.2f}% (基线: {BASELINE['avg_5d']:+.2f}%)")
            print(f"  5日胜率: {(valid_5d > 0).mean()*100:.1f}% (基线: {BASELINE['wr_5d']:.1f}%)")
            valid_10d = df_core['return_10d'].dropna()
            if len(valid_10d) > 0:
                print(f"  10日平均收益: {valid_10d.mean():+.2f}% (基线: {BASELINE['avg_10d']:+.2f}%)")
            print(f"{'='*50}")

    return report_path


def optimize_scoring_config(days_back: int = 120, min_samples: int = 30) -> Dict:
    ensure_dirs()
    result = {
        'applied': False,
        'samples': 0,
        'changes': [],
        'config_path': SCORING_RUNTIME_CONFIG,
    }

    if not os.path.exists(RECOMMENDATIONS_FILE):
        result['reason'] = 'no_recommendations'
        return result

    df = pd.read_csv(RECOMMENDATIONS_FILE)
    if 'return_5d' not in df.columns:
        result['reason'] = 'missing_return_column'
        return result

    cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    df = df[df['report_date'] >= cutoff]
    df = df[df['return_5d'].notna()].copy()
    result['samples'] = len(df)

    if len(df) < min_samples:
        result['reason'] = 'insufficient_samples'
        return result

    from analysis.opportunity_scorer import OpportunityScorer

    base_weights = dict(OpportunityScorer.DIMENSION_WEIGHTS)
    base_thresholds = dict(OpportunityScorer.RATING_THRESHOLDS)
    base_exclusion = dict(OpportunityScorer.EXCLUSION_RULES)

    optimized_weights = dict(base_weights)
    optimized_thresholds = dict(base_thresholds)
    optimized_exclusion = dict(base_exclusion)
    signals = []

    score_corr = 0.0
    if 'score' in df.columns:
        valid = df[['score', 'return_5d']].dropna()
        if len(valid) >= 12:
            score_corr = float(valid['score'].corr(valid['return_5d']))
            if score_corr < 0:
                optimized_weights['position_timing'] = optimized_weights.get('position_timing', 0) + 0.03
                optimized_weights['quantitative'] = max(0.0, optimized_weights.get('quantitative', 0) - 0.02)
                optimized_weights['technical'] = max(0.0, optimized_weights.get('technical', 0) - 0.01)
                signals.append('score_negative_corr')
            elif score_corr < 0.03:
                optimized_weights['position_timing'] = optimized_weights.get('position_timing', 0) + 0.01
                optimized_weights['quantitative'] = max(0.0, optimized_weights.get('quantitative', 0) - 0.01)
                signals.append('score_weak_corr')

    if 'chase_risk' in df.columns:
        low = df[df['chase_risk'] <= 35]['return_5d'].dropna()
        high = df[df['chase_risk'] >= 70]['return_5d'].dropna()
        if len(low) >= 8 and len(high) >= 8:
            diff = float(low.mean() - high.mean())
            if diff > 1.2:
                optimized_weights['position_timing'] = optimized_weights.get('position_timing', 0) + 0.02
                optimized_exclusion['max_change_20d'] = max(20, optimized_exclusion.get('max_change_20d', 40) - 2)
                signals.append('chase_risk_effective')

    if 'rsi' in df.columns:
        overbought = df[df['rsi'] >= 78]['return_5d'].dropna()
        neutral = df[(df['rsi'] >= 45) & (df['rsi'] <= 65)]['return_5d'].dropna()
        if len(overbought) >= 8 and len(neutral) >= 8:
            if float(neutral.mean() - overbought.mean()) > 0.8:
                optimized_exclusion['max_consecutive_up'] = max(4, optimized_exclusion.get('max_consecutive_up', 6) - 1)
                signals.append('rsi_overbought_penalty')

    if 'score' in df.columns:
        high_score = df[df['score'] >= 85]['return_5d'].dropna()
        mid_score = df[(df['score'] >= 70) & (df['score'] < 85)]['return_5d'].dropna()
        if len(high_score) >= 6 and len(mid_score) >= 10:
            if float(mid_score.mean() - high_score.mean()) > 0.8:
                optimized_thresholds['S'] = min(95, optimized_thresholds.get('S', 85) + 2)
                optimized_thresholds['A+'] = min(92, optimized_thresholds.get('A+', 82) + 1)
                signals.append('high_score_crowded')

    weight_sum = sum(optimized_weights.values())
    if weight_sum > 0:
        optimized_weights = {k: v / weight_sum for k, v in optimized_weights.items()}

    if not signals:
        result['reason'] = 'no_optimization_signal'
        return result

    def collect_changes(old: Dict, new: Dict, target: str):
        for key, old_val in old.items():
            new_val = new.get(key, old_val)
            if isinstance(old_val, float):
                if abs(float(new_val) - float(old_val)) > 1e-6:
                    result['changes'].append({
                        'target': target,
                        'key': key,
                        'old': round(float(old_val), 6),
                        'new': round(float(new_val), 6),
                    })
            else:
                if new_val != old_val:
                    result['changes'].append({
                        'target': target,
                        'key': key,
                        'old': old_val,
                        'new': new_val,
                    })

    collect_changes(base_weights, optimized_weights, 'dimension_weights')
    collect_changes(base_thresholds, optimized_thresholds, 'rating_thresholds')
    collect_changes(base_exclusion, optimized_exclusion, 'exclusion_rules')

    if not result['changes']:
        result['reason'] = 'no_effective_change'
        return result

    runtime_config = {
        'generated_at': datetime.now().isoformat(),
        'window_days': days_back,
        'sample_count': len(df),
        'signals': signals,
        'score_corr_5d': round(score_corr, 6),
        'rating_thresholds': optimized_thresholds,
        'dimension_weights': optimized_weights,
        'exclusion_rules': optimized_exclusion,
    }

    os.makedirs(os.path.dirname(SCORING_RUNTIME_CONFIG), exist_ok=True)
    with open(SCORING_RUNTIME_CONFIG, 'w', encoding='utf-8') as f:
        json.dump(runtime_config, f, ensure_ascii=False, indent=2)

    result['applied'] = True
    result['signals'] = signals
    logger.info(f"自动优化完成，已更新配置: {SCORING_RUNTIME_CONFIG}")
    return result


def run_baostock_smoke_test(days_ago: int = 20, cleanup: bool = True) -> Dict:
    ensure_dirs()
    test_name = "__BAOSTOCK_SMOKE_TEST__"
    result = {
        'passed': False,
        'report_generated': False,
        'updated_rows': 0,
        'report_path': '',
        'reason': ''
    }

    try:
        import baostock as bs
    except Exception:
        result['reason'] = 'baostock_not_installed'
        return result

    try:
        login_result = bs.login()
        if getattr(login_result, 'error_code', '1') != '0':
            result['reason'] = f"baostock_login_failed:{getattr(login_result, 'error_msg', 'unknown')}"
            return result
    except Exception as e:
        result['reason'] = f'baostock_login_exception:{e}'
        return result

    try:
        report_date = (datetime.now() - timedelta(days=max(days_ago, 12))).strftime('%Y-%m-%d')
        if os.path.exists(RECOMMENDATIONS_FILE):
            df = pd.read_csv(RECOMMENDATIONS_FILE)
        else:
            df = pd.DataFrame()

        if len(df) > 0 and 'name' in df.columns:
            df = df[df['name'] != test_name].copy()

        test_row = {
            'report_date': report_date,
            'rank': 1,
            'code': '000001',
            'name': test_name,
            'score': 80,
            'chase_risk': 35,
            'buy_signals': 6,
            'sell_signals': 1,
            'rsi': 45,
            'day_change': 0.5,
            'change_3d': 1.2,
            'change_5d': 1.8,
            'sector_score': 60,
            'quant_score': 62,
            'tech_score': 64,
            'momentum_pattern': '[]',
            'buy_price': 0,
            'return_1d': None,
            'return_3d': None,
            'return_5d': None,
            'return_10d': None,
        }
        df = pd.concat([df, pd.DataFrame([test_row])], ignore_index=True)
        df.to_csv(RECOMMENDATIONS_FILE, index=False, encoding='utf-8-sig')

        update_returns(days_back=120)

        after_df = pd.read_csv(RECOMMENDATIONS_FILE)
        smoke_df = after_df[after_df['name'] == test_name].copy()
        if len(smoke_df) == 0:
            result['reason'] = 'smoke_row_missing'
            return result

        updated = smoke_df[smoke_df['return_1d'].notna() | smoke_df['return_5d'].notna()]
        result['updated_rows'] = len(updated)
        if len(updated) == 0:
            result['reason'] = 'returns_not_updated'
            return result

        report_path = generate_backtest_report(days_back=120)
        result['report_path'] = report_path
        result['report_generated'] = bool(report_path)
        result['passed'] = bool(report_path)
        if not result['passed']:
            result['reason'] = 'report_not_generated'
    finally:
        try:
            bs.logout()
        except Exception:
            pass

        if cleanup:
            try:
                if os.path.exists(RECOMMENDATIONS_FILE):
                    clean_df = pd.read_csv(RECOMMENDATIONS_FILE)
                    if 'name' in clean_df.columns:
                        clean_df = clean_df[clean_df['name'] != test_name]
                        clean_df.to_csv(RECOMMENDATIONS_FILE, index=False, encoding='utf-8-sig')
            except Exception:
                pass

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description='v7.0 自动回测系统')
    parser.add_argument('--days', type=int, default=None, help='回溯天数')
    parser.add_argument('--report-only', action='store_true', help='仅生成报告，不更新收益数据')
    parser.add_argument('--update-only', action='store_true', help='仅更新收益数据，不生成报告')
    parser.add_argument('--optimize', action='store_true', help='执行自动参数优化并写入运行时配置')
    parser.add_argument('--optimize-days', type=int, default=120, help='自动优化使用的回溯天数')
    parser.add_argument('--min-samples', type=int, default=30, help='自动优化最少样本数')
    parser.add_argument('--smoke-test', action='store_true', help='使用baostock执行自动回测冒烟测试')
    parser.add_argument('--keep-smoke-data', action='store_true', help='冒烟测试后保留测试数据')

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if args.smoke_test:
        smoke_result = run_baostock_smoke_test(cleanup=not args.keep_smoke_data)
        if smoke_result.get('passed'):
            logger.info(f"冒烟测试通过，报告: {smoke_result.get('report_path', '')}")
        else:
            logger.warning(f"冒烟测试失败: {smoke_result.get('reason', 'unknown')}")
        return

    if not args.report_only:
        update_returns(days_back=args.days or 30)

    if not args.update_only:
        generate_backtest_report(days_back=args.days)

    if args.optimize:
        optimize_result = optimize_scoring_config(
            days_back=args.optimize_days,
            min_samples=args.min_samples
        )
        if optimize_result.get('applied'):
            logger.info(f"自动优化生效，变更项: {len(optimize_result.get('changes', []))}")
        else:
            logger.info(f"自动优化未生效: {optimize_result.get('reason', 'unknown')}")


if __name__ == '__main__':
    main()
