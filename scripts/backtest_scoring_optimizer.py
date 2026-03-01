#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评分算法回测验证与优化工具
============================
基于历史opportunity_top10报告，自动获取后续行情数据，
评估评分系统的有效性，并输出优化建议。

功能:
1. 批量解析所有历史opportunity_top10 MD报告
2. 通过baostock获取推荐后的实际行情数据（免费无限制）
3. 计算1日/3日/5日/10日持有收益
4. 分析评分维度与实际收益的相关性
5. 识别评分系统的优劣势
6. 输出具体的参数优化建议
"""

import os
import sys
import re
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

import pandas as pd
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# 第一部分: 报告解析
# ============================================================

def parse_all_reports(results_dir: str) -> List[Dict]:
    """
    解析所有opportunity_top10报告，提取推荐股票及其详细信息

    Returns:
        list of dict, 每条记录包含:
        - report_date: 报告日期 (YYYY-MM-DD)
        - rank: 排名
        - code: 股票代码
        - name: 股票名称
        - score: 综合得分
        - chase_risk: 追高风险分数(0-100)
        - chase_risk_level: 追高风险等级
        - buy_signals: 买入信号数
        - sell_signals: 卖出信号数
        - rsi: RSI值
        - day_change: 当日涨幅%
        - change_3d: 3日涨幅%
        - change_5d: 5日涨幅%
        - sector_score: 板块分数
        - quant_score: 量化分数
        - tech_score: 技术面分数
    """
    md_files = sorted([
        f for f in os.listdir(results_dir)
        if f.startswith('opportunity_top10') and f.endswith('.md')
    ])

    logger.info(f"找到 {len(md_files)} 个报告文件")

    all_records = []
    for filename in md_files:
        filepath = os.path.join(results_dir, filename)
        records = parse_single_report(filepath, filename)
        all_records.extend(records)

    logger.info(f"共解析出 {len(all_records)} 条推荐记录")
    return all_records


def parse_single_report(filepath: str, filename: str) -> List[Dict]:
    """解析单个报告文件"""
    records = []

    # 从文件名提取日期: opportunity_top10_YYYYMMDD_HHMMSS.md
    date_match = re.search(r'opportunity_top10_(\d{8})_\d{6}\.md', filename)
    if not date_match:
        return records
    report_date = datetime.strptime(date_match.group(1), '%Y%m%d').strftime('%Y-%m-%d')

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        logger.warning(f"读取文件失败 {filename}: {e}")
        return records

    lines = content.strip().split('\n')
    for raw in lines:
        line = raw.strip()
        if not line.startswith('|'):
            continue
        if '排名' in line or '---' in line:
            continue

        cols = [p.strip() for p in line.strip('|').split('|')]
        if len(cols) < 4:
            continue

        try:
            rank = int(cols[0])
            code = cols[1].strip()
            name = cols[2].strip()
            score = float(re.sub(r'[^0-9.\-]', '', cols[3]))
        except (ValueError, IndexError):
            continue

        # 从详情列解析额外信息
        detail = cols[4] if len(cols) > 4 else ''
        extra = parse_detail_column(detail)

        records.append({
            'report_date': report_date,
            'filename': filename,
            'rank': rank,
            'code': code,
            'name': name,
            'score': score,
            **extra
        })

    return records


def parse_detail_column(detail: str) -> Dict:
    """从详情列中提取关键指标"""
    result = {
        'chase_risk': None,
        'chase_risk_level': None,
        'buy_signals': None,
        'sell_signals': None,
        'total_signals': None,
        'rsi': None,
        'day_change': None,
        'change_3d': None,
        'change_5d': None,
        'sector_score': None,
        'quant_score': None,
        'tech_score': None,
    }

    if not detail:
        return result

    # 追高风险: 🟢 低(10分) / 🔴 偏高(100分)
    chase_match = re.search(r'追高风险:\s*\S+\s*(\S+)\((\d+)分\)', detail)
    if chase_match:
        result['chase_risk_level'] = chase_match.group(1)
        result['chase_risk'] = int(chase_match.group(2))

    # 量化: 买11/卖3/总30(37%)，79分
    quant_match = re.search(r'买(\d+)/卖(\d+)/总(\d+)\(\d+%\).*?(\d+)分', detail)
    if quant_match:
        result['buy_signals'] = int(quant_match.group(1))
        result['sell_signals'] = int(quant_match.group(2))
        result['total_signals'] = int(quant_match.group(3))
        result['quant_score'] = int(quant_match.group(4))

    # RSI
    rsi_match = re.search(r'RSI:(\d+\.?\d*)', detail)
    if rsi_match:
        result['rsi'] = float(rsi_match.group(1))

    # 技术面分数
    tech_match = re.search(r'布林:\S+，(\d+)分', detail)
    if tech_match:
        result['tech_score'] = int(tech_match.group(1))

    # 涨幅: 当日:+10.01%，3日:+14.33%，5日:+7.46%
    day_match = re.search(r'当日:([+\-]?\d+\.?\d*)%', detail)
    if day_match:
        result['day_change'] = float(day_match.group(1))

    change_3d_match = re.search(r'3日:([+\-]?\d+\.?\d*)%', detail)
    if change_3d_match:
        result['change_3d'] = float(change_3d_match.group(1))

    change_5d_match = re.search(r'5日:([+\-]?\d+\.?\d*)%', detail)
    if change_5d_match:
        result['change_5d'] = float(change_5d_match.group(1))

    # 板块分数
    sector_match = re.search(r'(?:偏弱|偏强|强势领涨|震荡|走强|温和上涨|领涨)[,，]\s*(\d+)分', detail)
    if sector_match:
        result['sector_score'] = int(sector_match.group(1))

    return result


# ============================================================
# 第二部分: 行情数据获取 (baostock)
# ============================================================

def code_to_baostock(code: str) -> str:
    """将6位股票代码转换为baostock格式"""
    if code.startswith(('60', '68')):
        return f"sh.{code}"
    elif code.startswith(('00', '30')):
        return f"sz.{code}"
    elif code.startswith(('4', '8')):
        return f"bj.{code}"
    return f"sz.{code}"


def fetch_all_stock_data(stock_codes: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """
    批量获取所有股票的日线数据

    Args:
        stock_codes: 股票代码列表
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        {stock_code: DataFrame} 字典
    """
    import baostock as bs

    logger.info(f"连接baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        logger.error(f"baostock登录失败: {lg.error_msg}")
        return {}

    stock_data = {}
    total = len(stock_codes)

    for i, code in enumerate(stock_codes, 1):
        bs_code = code_to_baostock(code)
        logger.info(f"  [{i}/{total}] 获取 {code} ({bs_code}) 数据...")

        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,turn",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2"  # 前复权
            )

            if rs.error_code != '0':
                logger.warning(f"  {code} 查询失败: {rs.error_msg}")
                continue

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                logger.warning(f"  {code} 无数据")
                continue

            df = pd.DataFrame(data_list, columns=rs.fields)

            # 转换数据类型
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)

            # 过滤无效数据（停牌等）
            df = df[df['volume'] > 0].reset_index(drop=True)

            stock_data[code] = df
            logger.info(f"  {code} 获取成功: {len(df)} 条日线数据")

        except Exception as e:
            logger.warning(f"  {code} 获取异常: {e}")

    bs.logout()
    logger.info(f"数据获取完成: {len(stock_data)}/{total} 只股票成功")
    return stock_data


# ============================================================
# 第三部分: 收益计算
# ============================================================

def calculate_returns(records: List[Dict], stock_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    计算每条推荐记录的后续实际收益

    逻辑:
    - 报告在日期X收盘后生成
    - 假设X+1日开盘价买入
    - 分别计算持有到1日/3日/5日/10日收盘的收益率

    Returns:
        DataFrame with columns: report_date, code, name, score, rank, ...
        return_1d, return_3d, return_5d, return_10d, max_drawdown_5d
    """
    results = []

    for rec in records:
        code = rec['code']
        report_date = rec['report_date']

        df = stock_data.get(code)
        if df is None or df.empty:
            continue

        # 找到报告日期后的第一个交易日（买入日）
        report_dt = pd.to_datetime(report_date)
        future_data = df[df['date'] > report_dt].copy()

        if len(future_data) < 2:
            continue

        buy_price = float(future_data.iloc[0]['open'])
        if buy_price <= 0:
            continue

        # 计算各持有期收益
        result = {**rec}

        # 买入日信息
        result['buy_date'] = future_data.iloc[0]['date'].strftime('%Y-%m-%d')
        result['buy_price'] = buy_price

        for days, key in [(1, 'return_1d'), (3, 'return_3d'), (5, 'return_5d'), (10, 'return_10d')]:
            if len(future_data) >= days:
                close_price = float(future_data.iloc[days - 1]['close'])
                result[key] = (close_price - buy_price) / buy_price * 100
            else:
                result[key] = None

        # 5日最大回撤
        if len(future_data) >= 5:
            prices_5d = future_data.iloc[:5]['close'].astype(float).values
            lows_5d = future_data.iloc[:5]['low'].astype(float).values
            min_low = min(lows_5d)
            result['max_drawdown_5d'] = (min_low - buy_price) / buy_price * 100
        else:
            result['max_drawdown_5d'] = None

        results.append(result)

    df_results = pd.DataFrame(results)
    logger.info(f"收益计算完成: {len(df_results)} 条有效记录（共 {len(records)} 条推荐）")
    return df_results


# ============================================================
# 第四部分: 分析与优化建议
# ============================================================

def analyze_performance(df: pd.DataFrame) -> Dict:
    """全面分析评分系统的表现"""
    analysis = {}

    # 1. 整体表现统计
    analysis['overall'] = compute_overall_stats(df)

    # 2. 按评分区间分析
    analysis['score_bins'] = compute_score_bin_stats(df)

    # 3. 按排名分析
    analysis['rank_analysis'] = compute_rank_stats(df)

    # 4. 追高风险维度分析
    analysis['chase_risk'] = compute_chase_risk_stats(df)

    # 5. 量化信号分析
    analysis['quant_signals'] = compute_quant_signal_stats(df)

    # 6. RSI分析
    analysis['rsi_analysis'] = compute_rsi_stats(df)

    # 7. 当日涨幅与后续收益的关系
    analysis['day_change_impact'] = compute_day_change_stats(df)

    # 8. 板块强度分析
    analysis['sector_analysis'] = compute_sector_stats(df)

    # 9. 时间趋势分析
    analysis['time_trend'] = compute_time_trend(df)

    # 10. 相关性矩阵
    analysis['correlations'] = compute_correlations(df)

    return analysis


def compute_overall_stats(df: pd.DataFrame) -> Dict:
    """整体表现统计"""
    stats = {}
    for period in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
        valid = df[period].dropna()
        if len(valid) == 0:
            continue
        stats[period] = {
            'count': len(valid),
            'mean': valid.mean(),
            'median': valid.median(),
            'std': valid.std(),
            'win_rate': (valid > 0).mean() * 100,
            'avg_win': valid[valid > 0].mean() if (valid > 0).any() else 0,
            'avg_loss': valid[valid < 0].mean() if (valid < 0).any() else 0,
            'max_return': valid.max(),
            'min_return': valid.min(),
            'profit_factor': abs(valid[valid > 0].sum() / valid[valid < 0].sum()) if (valid < 0).any() and valid[valid < 0].sum() != 0 else float('inf'),
        }
    return stats


def compute_score_bin_stats(df: pd.DataFrame) -> Dict:
    """按评分区间统计收益"""
    bins = [(90, 100, 'S(90-100)'), (85, 90, 'A+(85-90)'), (70, 85, 'A(70-85)'),
            (60, 70, 'B(60-70)'), (0, 60, 'C(<60)')]

    results = {}
    for low, high, label in bins:
        mask = (df['score'] >= low) & (df['score'] < high) if high < 100 else (df['score'] >= low)
        subset = df[mask]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d', 'return_10d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_rank_stats(df: pd.DataFrame) -> Dict:
    """按排名区间统计"""
    rank_bins = [(1, 5, 'Top5'), (6, 10, 'Rank6-10'), (11, 20, 'Rank11-20')]

    results = {}
    for low, high, label in rank_bins:
        subset = df[(df['rank'] >= low) & (df['rank'] <= high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_chase_risk_stats(df: pd.DataFrame) -> Dict:
    """按追高风险分析"""
    chase_bins = [(0, 30, '低风险(0-30)'), (30, 60, '中风险(30-60)'),
                  (60, 80, '偏高风险(60-80)'), (80, 101, '高风险(80-100)')]

    valid_df = df[df['chase_risk'].notna()]
    results = {}
    for low, high, label in chase_bins:
        subset = valid_df[(valid_df['chase_risk'] >= low) & (valid_df['chase_risk'] < high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_quant_signal_stats(df: pd.DataFrame) -> Dict:
    """按量化信号数量分析"""
    valid_df = df[df['buy_signals'].notna()]
    if len(valid_df) == 0:
        return {}

    signal_bins = [(0, 5, '少量(0-5)'), (5, 10, '适中(5-10)'),
                   (10, 15, '较多(10-15)'), (15, 30, '很多(15+)')]

    results = {}
    for low, high, label in signal_bins:
        subset = valid_df[(valid_df['buy_signals'] >= low) & (valid_df['buy_signals'] < high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_rsi_stats(df: pd.DataFrame) -> Dict:
    """按RSI区间分析"""
    valid_df = df[df['rsi'].notna()]
    if len(valid_df) == 0:
        return {}

    rsi_bins = [(0, 30, '超卖(<30)'), (30, 50, '偏弱(30-50)'),
                (50, 70, '中性(50-70)'), (70, 80, '偏强(70-80)'),
                (80, 100, '超买(>80)')]

    results = {}
    for low, high, label in rsi_bins:
        subset = valid_df[(valid_df['rsi'] >= low) & (valid_df['rsi'] < high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_day_change_stats(df: pd.DataFrame) -> Dict:
    """按推荐日涨幅分析"""
    valid_df = df[df['day_change'].notna()]
    if len(valid_df) == 0:
        return {}

    change_bins = [(-100, 0, '下跌(<0%)'), (0, 5, '小涨(0-5%)'),
                   (5, 10, '中涨(5-10%)'), (10, 20, '涨停(10-20%)'),
                   (20, 100, '大涨(>20%)')]

    results = {}
    for low, high, label in change_bins:
        subset = valid_df[(valid_df['day_change'] >= low) & (valid_df['day_change'] < high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_sector_stats(df: pd.DataFrame) -> Dict:
    """按板块分数分析"""
    valid_df = df[df['sector_score'].notna()]
    if len(valid_df) == 0:
        return {}

    sector_bins = [(0, 50, '弱势板块(<50)'), (50, 70, '中性板块(50-70)'),
                   (70, 90, '强势板块(70-90)'), (90, 101, '领涨板块(90+)')]

    results = {}
    for low, high, label in sector_bins:
        subset = valid_df[(valid_df['sector_score'] >= low) & (valid_df['sector_score'] < high)]
        if len(subset) == 0:
            continue

        stats = {}
        for period in ['return_1d', 'return_3d', 'return_5d']:
            valid = subset[period].dropna()
            if len(valid) == 0:
                continue
            stats[period] = {
                'count': len(valid),
                'mean': valid.mean(),
                'win_rate': (valid > 0).mean() * 100,
            }
        results[label] = stats

    return results


def compute_time_trend(df: pd.DataFrame) -> Dict:
    """按时间(月份)统计表现趋势"""
    if 'report_date' not in df.columns:
        return {}

    df_copy = df.copy()
    df_copy['month'] = pd.to_datetime(df_copy['report_date']).dt.to_period('M').astype(str)

    results = {}
    for month, group in df_copy.groupby('month'):
        valid = group['return_5d'].dropna()
        if len(valid) == 0:
            continue
        results[month] = {
            'count': len(valid),
            'mean_5d': valid.mean(),
            'win_rate_5d': (valid > 0).mean() * 100,
            'avg_score': group['score'].mean(),
        }

    return results


def compute_correlations(df: pd.DataFrame) -> Dict:
    """计算关键指标与收益的相关性"""
    metrics = ['score', 'chase_risk', 'buy_signals', 'sell_signals', 'rsi',
               'day_change', 'change_3d', 'change_5d', 'quant_score', 'tech_score',
               'sector_score', 'rank']
    targets = ['return_1d', 'return_3d', 'return_5d']

    results = {}
    for target in targets:
        corrs = {}
        for metric in metrics:
            if metric in df.columns and target in df.columns:
                valid = df[[metric, target]].dropna()
                if len(valid) > 10:
                    corrs[metric] = valid[metric].corr(valid[target])
        results[target] = corrs

    return results


# ============================================================
# 第五部分: 优化建议生成
# ============================================================

def generate_optimization_suggestions(analysis: Dict, df: pd.DataFrame) -> List[Dict]:
    """基于分析结果生成具体的优化建议"""
    suggestions = []

    # 1. 检查追高风险是否有效
    chase_stats = analysis.get('chase_risk', {})
    if chase_stats:
        low_risk = chase_stats.get('低风险(0-30)', {}).get('return_5d', {})
        high_risk = chase_stats.get('高风险(80-100)', {}).get('return_5d', {})

        if low_risk and high_risk:
            low_mean = low_risk.get('mean', 0)
            high_mean = high_risk.get('mean', 0)
            if high_mean < low_mean:
                diff = low_mean - high_mean
                suggestions.append({
                    'priority': 'P0',
                    'category': '追高风险',
                    'problem': f'高追高风险股票5日均收益({high_mean:+.2f}%) 显著低于低风险股票({low_mean:+.2f}%)，差值{diff:.2f}%',
                    'suggestion': '启用一票否决机制中的追高惩罚，追高风险>=80分应扣除15-25分总分',
                    'file': 'analysis/opportunity_scorer.py',
                    'detail': '取消注释 lines 461-469 的exclusion_flags惩罚代码，并增加追高风险权重'
                })

    # 2. 检查当日涨幅影响
    day_change_stats = analysis.get('day_change_impact', {})
    if day_change_stats:
        limit_up = day_change_stats.get('涨停(10-20%)', {}).get('return_5d', {})
        small_up = day_change_stats.get('小涨(0-5%)', {}).get('return_5d', {})

        if limit_up and small_up:
            limit_mean = limit_up.get('mean', 0)
            small_mean = small_up.get('mean', 0)
            if limit_mean < small_mean:
                suggestions.append({
                    'priority': 'P0',
                    'category': '涨停板过滤',
                    'problem': f'当日涨停股票次日买入后5日均收益({limit_mean:+.2f}%) 低于小涨股票({small_mean:+.2f}%)',
                    'suggestion': '对当日涨停(>=9.5%)的股票增加追涨惩罚，总分扣除10-15分',
                    'file': 'analysis/opportunity_scorer.py',
                    'detail': '在总分计算后增加涨停板惩罚逻辑'
                })

    # 3. 检查RSI影响
    rsi_stats = analysis.get('rsi_analysis', {})
    if rsi_stats:
        overbought = rsi_stats.get('超买(>80)', {}).get('return_5d', {})
        neutral = rsi_stats.get('中性(50-70)', {}).get('return_5d', {})

        if overbought and neutral:
            ob_mean = overbought.get('mean', 0)
            n_mean = neutral.get('mean', 0)
            if ob_mean < n_mean:
                suggestions.append({
                    'priority': 'P1',
                    'category': 'RSI超买惩罚',
                    'problem': f'RSI>80超买股票5日均收益({ob_mean:+.2f}%) 低于中性区({n_mean:+.2f}%)',
                    'suggestion': 'RSI>80时对技术面和位置时机维度额外扣分',
                    'file': 'analysis/opportunity_scorer.py',
                    'detail': '在_score_momentum中增加RSI超买惩罚力度'
                })

    # 4. 检查评分与收益的相关性
    correlations = analysis.get('correlations', {})
    corr_5d = correlations.get('return_5d', {})

    if corr_5d:
        # 评分与收益的相关性
        score_corr = corr_5d.get('score', 0)
        if abs(score_corr) < 0.05:
            suggestions.append({
                'priority': 'P0',
                'category': '评分有效性',
                'problem': f'综合评分与5日收益相关性极低({score_corr:.4f})，评分系统几乎无预测能力',
                'suggestion': '需要全面重构评分权重，当前权重配置无法区分好坏标的',
                'file': 'analysis/opportunity_scorer.py',
                'detail': '重新调整DIMENSION_WEIGHTS权重比例'
            })
        elif score_corr < -0.05:
            suggestions.append({
                'priority': 'P0',
                'category': '评分方向错误',
                'problem': f'综合评分与5日收益负相关({score_corr:.4f})，评分越高反而收益越差',
                'suggestion': '当前评分逻辑存在根本性问题，高分股票反而是风险标的',
                'file': 'analysis/opportunity_scorer.py',
                'detail': '需要大幅降低量化权重、增加反追涨权重'
            })

        # 各维度相关性分析
        chase_corr = corr_5d.get('chase_risk', 0)
        if chase_corr < -0.05:
            suggestions.append({
                'priority': 'P1',
                'category': '追高风险有效',
                'problem': f'追高风险与5日收益负相关({chase_corr:.4f})，说明该指标有效但未被充分利用',
                'suggestion': '增加追高风险在总分中的惩罚力度，当前仅影响position_timing维度',
                'file': 'analysis/opportunity_scorer.py',
                'detail': '直接在总分中扣除: chase_risk >= 80 扣15分, >= 60 扣8分'
            })

    # 5. 检查量化信号数量影响
    quant_stats = analysis.get('quant_signals', {})
    if quant_stats:
        many = quant_stats.get('很多(15+)', {}).get('return_5d', {})
        moderate = quant_stats.get('适中(5-10)', {}).get('return_5d', {})

        if many and moderate:
            many_mean = many.get('mean', 0)
            mod_mean = moderate.get('mean', 0)
            if many_mean < mod_mean:
                suggestions.append({
                    'priority': 'P1',
                    'category': '信号拥挤惩罚',
                    'problem': f'买入信号15+的股票5日均收益({many_mean:+.2f}%) 低于5-10个信号的({mod_mean:+.2f}%)',
                    'suggestion': '买入信号过多说明已是共识，应降低量化分数或增加拥挤惩罚',
                    'file': 'analysis/opportunity_scorer.py',
                    'detail': '在_score_quantitative_models中信号>15时不再线性加分，改为递减'
                })

    # 6. 检查筛选器是否应启用
    overall = analysis.get('overall', {})
    ret_5d = overall.get('return_5d', {})
    if ret_5d:
        win_rate = ret_5d.get('win_rate', 50)
        if win_rate < 50:
            suggestions.append({
                'priority': 'P0',
                'category': '筛选器启用',
                'problem': f'5日胜率仅{win_rate:.1f}%，低于50%，当前推荐的大部分股票都在亏损',
                'suggestion': '重新启用opportunity_filter.py中的淘汰机制，特别是阶段0一票否决和阶段2位置时机',
                'file': 'analysis/opportunity_filter.py',
                'detail': '移除"已移除淘汰机制"注释，恢复stage0和stage2的淘汰逻辑'
            })

    # 7. 排名有效性
    rank_stats = analysis.get('rank_analysis', {})
    if rank_stats:
        top5 = rank_stats.get('Top5', {}).get('return_5d', {})
        low_rank = rank_stats.get('Rank11-20', {}).get('return_5d', {})

        if top5 and low_rank:
            top5_mean = top5.get('mean', 0)
            low_mean = low_rank.get('mean', 0)
            if top5_mean < low_mean:
                suggestions.append({
                    'priority': 'P1',
                    'category': '排名失效',
                    'problem': f'Top5股票5日均收益({top5_mean:+.2f}%) 反而低于Rank11-20({low_mean:+.2f}%)',
                    'suggestion': '高排名股票表现更差，说明当前排序逻辑有问题',
                    'file': 'analysis/opportunity_scorer.py',
                    'detail': '调整排序算法，增加反追涨因子的权重'
                })

    # 按优先级排序
    priority_order = {'P0': 0, 'P1': 1, 'P2': 2}
    suggestions.sort(key=lambda x: priority_order.get(x['priority'], 99))

    return suggestions


# ============================================================
# 第六部分: 报告生成
# ============================================================

def generate_report(df: pd.DataFrame, analysis: Dict, suggestions: List[Dict],
                    output_path: str) -> str:
    """生成完整的回测分析报告"""
    lines = []

    lines.append("# 投资机会评分系统 - 回测验证与优化报告")
    lines.append(f"")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**分析范围**: {df['report_date'].min()} ~ {df['report_date'].max()}")
    lines.append(f"**报告总数**: {df['filename'].nunique()} 份")
    lines.append(f"**推荐记录**: {len(df)} 条 ({df['code'].nunique()} 只唯一股票)")
    lines.append("")

    # ========== 一、整体表现 ==========
    lines.append("## 一、整体表现统计")
    lines.append("")

    overall = analysis.get('overall', {})
    lines.append("| 持有期 | 样本数 | 平均收益 | 中位数 | 胜率 | 平均盈利 | 平均亏损 | 盈亏比 | 最大收益 | 最大亏损 |")
    lines.append("|--------|--------|----------|--------|------|----------|----------|--------|----------|----------|")

    for period, label in [('return_1d', '1日'), ('return_3d', '3日'), ('return_5d', '5日'), ('return_10d', '10日')]:
        stats = overall.get(period, {})
        if not stats:
            continue
        pf = stats.get('profit_factor', 0)
        pf_str = f"{pf:.2f}" if pf != float('inf') else "INF"
        lines.append(
            f"| {label} | {stats['count']} | {stats['mean']:+.2f}% | {stats['median']:+.2f}% | "
            f"{stats['win_rate']:.1f}% | {stats['avg_win']:+.2f}% | {stats['avg_loss']:+.2f}% | "
            f"{pf_str} | {stats['max_return']:+.2f}% | {stats['min_return']:+.2f}% |"
        )
    lines.append("")

    # ========== 二、评分区间分析 ==========
    lines.append("## 二、评分区间 vs 实际收益")
    lines.append("")
    lines.append("| 评级区间 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 3日胜率 | 1日均收益 | 1日胜率 |")
    lines.append("|----------|---------|-----------|---------|-----------|---------|-----------|---------|")

    score_bins = analysis.get('score_bins', {})
    for label in ['S(90-100)', 'A+(85-90)', 'A(70-85)', 'B(60-70)', 'C(<60)']:
        stats = score_bins.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r3.get('win_rate', 0):.1f}% | "
            f"{r1.get('mean', 0):+.2f}% | {r1.get('win_rate', 0):.1f}% |"
        )
    lines.append("")

    # ========== 三、排名分析 ==========
    lines.append("## 三、排名 vs 实际收益")
    lines.append("")
    lines.append("| 排名区间 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|----------|---------|-----------|---------|-----------|-----------|")

    rank_stats = analysis.get('rank_analysis', {})
    for label in ['Top5', 'Rank6-10', 'Rank11-20']:
        stats = rank_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 四、追高风险分析 ==========
    lines.append("## 四、追高风险 vs 实际收益")
    lines.append("")
    lines.append("| 追高风险 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|----------|---------|-----------|---------|-----------|-----------|")

    chase_stats = analysis.get('chase_risk', {})
    for label in ['低风险(0-30)', '中风险(30-60)', '偏高风险(60-80)', '高风险(80-100)']:
        stats = chase_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 五、当日涨幅影响 ==========
    lines.append("## 五、推荐日涨幅 vs 后续收益")
    lines.append("")
    lines.append("| 当日涨幅 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|----------|---------|-----------|---------|-----------|-----------|")

    day_change_stats = analysis.get('day_change_impact', {})
    for label in ['下跌(<0%)', '小涨(0-5%)', '中涨(5-10%)', '涨停(10-20%)', '大涨(>20%)']:
        stats = day_change_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 六、量化信号分析 ==========
    lines.append("## 六、量化买入信号数量 vs 实际收益")
    lines.append("")
    lines.append("| 信号数量 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|----------|---------|-----------|---------|-----------|-----------|")

    quant_stats = analysis.get('quant_signals', {})
    for label in ['少量(0-5)', '适中(5-10)', '较多(10-15)', '很多(15+)']:
        stats = quant_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 七、RSI分析 ==========
    lines.append("## 七、RSI区间 vs 实际收益")
    lines.append("")
    lines.append("| RSI区间 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|---------|---------|-----------|---------|-----------|-----------|")

    rsi_stats = analysis.get('rsi_analysis', {})
    for label in ['超卖(<30)', '偏弱(30-50)', '中性(50-70)', '偏强(70-80)', '超买(>80)']:
        stats = rsi_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 八、板块分析 ==========
    lines.append("## 八、板块强度 vs 实际收益")
    lines.append("")
    lines.append("| 板块强度 | 5日样本 | 5日均收益 | 5日胜率 | 3日均收益 | 1日均收益 |")
    lines.append("|----------|---------|-----------|---------|-----------|-----------|")

    sector_stats = analysis.get('sector_analysis', {})
    for label in ['弱势板块(<50)', '中性板块(50-70)', '强势板块(70-90)', '领涨板块(90+)']:
        stats = sector_stats.get(label, {})
        r5 = stats.get('return_5d', {})
        r3 = stats.get('return_3d', {})
        r1 = stats.get('return_1d', {})
        lines.append(
            f"| {label} | {r5.get('count', 0)} | {r5.get('mean', 0):+.2f}% | {r5.get('win_rate', 0):.1f}% | "
            f"{r3.get('mean', 0):+.2f}% | {r1.get('mean', 0):+.2f}% |"
        )
    lines.append("")

    # ========== 九、相关性分析 ==========
    lines.append("## 九、指标与收益的相关性")
    lines.append("")
    lines.append("相关系数越正表示正向预测力越强，越负表示反向预测力。")
    lines.append("")
    lines.append("| 指标 | 与1日收益相关性 | 与3日收益相关性 | 与5日收益相关性 |")
    lines.append("|------|----------------|----------------|----------------|")

    correlations = analysis.get('correlations', {})
    all_metrics = set()
    for period_corrs in correlations.values():
        all_metrics.update(period_corrs.keys())

    metric_names = {
        'score': '综合评分', 'chase_risk': '追高风险', 'buy_signals': '买入信号数',
        'sell_signals': '卖出信号数', 'rsi': 'RSI', 'day_change': '当日涨幅',
        'change_3d': '3日涨幅', 'change_5d': '5日涨幅', 'quant_score': '量化分数',
        'tech_score': '技术面分数', 'sector_score': '板块分数', 'rank': '排名'
    }

    for metric in ['score', 'chase_risk', 'buy_signals', 'sell_signals', 'rsi',
                    'day_change', 'change_3d', 'change_5d', 'quant_score',
                    'tech_score', 'sector_score', 'rank']:
        c1 = correlations.get('return_1d', {}).get(metric, None)
        c3 = correlations.get('return_3d', {}).get(metric, None)
        c5 = correlations.get('return_5d', {}).get(metric, None)
        name = metric_names.get(metric, metric)
        c1_str = f"{c1:+.4f}" if c1 is not None else "N/A"
        c3_str = f"{c3:+.4f}" if c3 is not None else "N/A"
        c5_str = f"{c5:+.4f}" if c5 is not None else "N/A"
        lines.append(f"| {name} | {c1_str} | {c3_str} | {c5_str} |")
    lines.append("")

    # ========== 十、月度趋势 ==========
    lines.append("## 十、月度趋势")
    lines.append("")
    lines.append("| 月份 | 推荐数 | 5日均收益 | 5日胜率 | 平均评分 |")
    lines.append("|------|--------|-----------|---------|----------|")

    time_trend = analysis.get('time_trend', {})
    for month in sorted(time_trend.keys()):
        stats = time_trend[month]
        lines.append(
            f"| {month} | {stats['count']} | {stats['mean_5d']:+.2f}% | "
            f"{stats['win_rate_5d']:.1f}% | {stats['avg_score']:.1f} |"
        )
    lines.append("")

    # ========== 十一、优化建议 ==========
    lines.append("## 十一、优化建议")
    lines.append("")

    if not suggestions:
        lines.append("暂无明确优化建议。")
    else:
        for i, s in enumerate(suggestions, 1):
            lines.append(f"### {i}. [{s['priority']}] {s['category']}")
            lines.append(f"")
            lines.append(f"**问题**: {s['problem']}")
            lines.append(f"")
            lines.append(f"**建议**: {s['suggestion']}")
            lines.append(f"")
            lines.append(f"**涉及文件**: `{s['file']}`")
            lines.append(f"")
            lines.append(f"**具体操作**: {s['detail']}")
            lines.append(f"")

    # ========== 十二、数据摘要 ==========
    lines.append("## 十二、数据导出摘要")
    lines.append("")
    lines.append(f"完整数据已保存为CSV: `{output_path.replace('.md', '.csv')}`")
    lines.append("")
    lines.append("可用于进一步分析的字段:")
    lines.append("- `report_date`: 报告日期")
    lines.append("- `code`, `name`: 股票代码和名称")
    lines.append("- `score`, `rank`: 综合评分和排名")
    lines.append("- `chase_risk`: 追高风险分数")
    lines.append("- `buy_signals`, `sell_signals`: 量化信号数")
    lines.append("- `rsi`: RSI值")
    lines.append("- `day_change`: 推荐日涨幅")
    lines.append("- `return_1d/3d/5d/10d`: 实际后续收益")
    lines.append("")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return output_path


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数 - 执行完整回测分析流程"""
    print("=" * 70)
    print("  投资机会评分系统 - 回测验证与优化工具")
    print("=" * 70)
    print()

    results_dir = os.path.join(project_root, 'results')

    # Step 1: 解析所有报告
    print("[1/5] 解析历史报告...")
    records = parse_all_reports(results_dir)
    if not records:
        print("未找到任何报告数据，退出")
        return

    df_records = pd.DataFrame(records)
    unique_codes = df_records['code'].unique().tolist()
    print(f"  解析完成: {len(records)} 条推荐, {len(unique_codes)} 只唯一股票")
    print(f"  日期范围: {df_records['report_date'].min()} ~ {df_records['report_date'].max()}")

    # Step 2: 获取行情数据
    print(f"\n[2/5] 获取行情数据 ({len(unique_codes)} 只股票)...")
    # 数据范围: 从最早报告日期到今天+15天(确保最新报告也有10个交易日)
    start_date = (pd.to_datetime(df_records['report_date'].min()) - timedelta(days=5)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

    stock_data = fetch_all_stock_data(unique_codes, start_date, end_date)
    print(f"  数据获取完成: {len(stock_data)}/{len(unique_codes)} 只成功")

    # Step 3: 计算收益
    print(f"\n[3/5] 计算持有收益...")
    df_results = calculate_returns(records, stock_data)
    if df_results.empty:
        print("无有效收益数据，退出")
        return

    # Step 4: 分析
    print(f"\n[4/5] 分析评分系统表现...")
    analysis = analyze_performance(df_results)

    # 生成优化建议
    suggestions = generate_optimization_suggestions(analysis, df_results)
    print(f"  生成了 {len(suggestions)} 条优化建议")

    # Step 5: 生成报告
    print(f"\n[5/5] 生成报告...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(results_dir, f"backtest_analysis_{timestamp}.md")
    csv_path = os.path.join(results_dir, f"backtest_analysis_{timestamp}.csv")

    # 保存CSV
    df_results.to_csv(csv_path, index=False, encoding='utf-8-sig')

    # 生成MD报告
    generate_report(df_results, analysis, suggestions, report_path)

    print(f"\n{'=' * 70}")
    print(f"  回测分析完成!")
    print(f"{'=' * 70}")
    print(f"  报告文件: {report_path}")
    print(f"  数据文件: {csv_path}")
    print(f"  推荐记录: {len(df_results)} 条有效")
    print()

    # 简要输出关键发现
    overall = analysis.get('overall', {})
    ret_5d = overall.get('return_5d', {})
    if ret_5d:
        print(f"  关键指标 (5日持有):")
        print(f"    平均收益: {ret_5d['mean']:+.2f}%")
        print(f"    胜率: {ret_5d['win_rate']:.1f}%")
        print(f"    盈亏比: {ret_5d.get('profit_factor', 0):.2f}")
        print()

    if suggestions:
        print("  优化建议摘要:")
        for s in suggestions[:5]:
            print(f"    [{s['priority']}] {s['category']}: {s['suggestion'][:60]}...")
        print()


if __name__ == '__main__':
    main()
