#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TOP10股票5日持有收益回测工具
基于opportunity_top10的md文件，统计5日每日收益率
"""

import os
import sys
import re
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def parse_top10_md(filepath: str) -> List[Dict]:
    """解析opportunity_top10 md文件，提取股票代码和名称"""
    stocks = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

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
            code = cols[1]
            name = cols[2]
            # 分数字段可能包含额外空格
            score = float(re.sub(r'[^0-9.\-]', '', cols[3]))
        except Exception:
            continue

        stocks.append({
            'rank': rank,
            'code': code,
            'name': name,
            'score': score
        })

    return stocks


async def fetch_kline_data(stock_code: str, start_date: str, days: int = 10) -> Optional[pd.DataFrame]:
    """获取K线数据"""
    from scripts.fetch_data import MultiSourceDataFetcher
    
    fetcher = MultiSourceDataFetcher()
    try:
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = start_dt + timedelta(days=days + 10)
        
        df = await fetcher.fetch_stock_data(
            symbol=stock_code,
            start_date=start_date,
            end_date=end_dt.strftime('%Y-%m-%d'),
            freq='daily',
            source='auto',
            auto_extend=False
        )
        return df
    except Exception as e:
        print(f"  ✗ {stock_code} 数据获取失败: {e}")
        return None
    finally:
        await fetcher.close()


def calculate_daily_returns(df: pd.DataFrame, start_date: str, trading_days: int = 5) -> List[Dict]:
    """计算持有到每日收盘的累计收益率，基于首日开盘价"""
    if df is None or df.empty:
        return []
    
    df = df.copy()
    # 兼容timestamp列名
    if 'timestamp' in df.columns and 'timestamps' not in df.columns:
        df = df.rename(columns={'timestamp': 'timestamps'})
        
    df['timestamps'] = pd.to_datetime(df['timestamps'])
    df = df.sort_values('timestamps').reset_index(drop=True)
    
    start_dt = pd.to_datetime(start_date)
    df_filtered = df[df['timestamps'] >= start_dt].head(trading_days)
    
    if df_filtered.empty:
        return []
    
    base_open = float(df_filtered.iloc[0]['open'])
    
    results = []
    for _, row in df_filtered.iterrows():
        open_price = float(row['open'])
        close_price = float(row['close'])
        cum_return = (close_price - base_open) / base_open * 100
        results.append({
            'date': row['timestamps'].strftime('%Y-%m-%d'),
            'open': open_price,
            'close': close_price,
            'return_pct': cum_return
        })
    
    return results


def generate_report(stocks: List[Dict], all_returns: Dict, start_date: str, output_path: str, trading_days: int = 5):
    """生成Markdown统计报告"""
    lines = []
    lines.append(f"# TOP10股票{trading_days}日持有收益统计")
    lines.append(f"")
    lines.append(f"**买入起始日期**: {start_date}")
    lines.append(f"**统计规则**: 第1日开盘买入，持有至第{trading_days}日收盘；每日列为持有到当日收盘的累计收益")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")
    
    lines.append("## 汇总表")
    lines.append("")
    
    header = "| 排名 | 代码 | 名称 | 综合得分 |"
    separator = "|------|------|------|----------|"
    
    day_headers = []
    day_separators = []
    max_days = trading_days
    for i in range(1, max_days + 1):
        day_headers.append(f" 第{i}日收益 |")
        day_separators.append("----------|")
    
    header += "".join(day_headers) + f" {trading_days}日累计 | 平均日收益 |"
    separator += "".join(day_separators) + "----------|------------|"
    
    lines.append(header)
    lines.append(separator)
    
    total_cumulative = 0
    valid_count = 0
    
    for stock in stocks:
        code = stock['code']
        returns = all_returns.get(code, [])
        
        row = f"| {stock['rank']} | {code} | {stock['name']} | {stock['score']:.2f} |"
        
        day_count = 0
        for i in range(max_days):
            if i < len(returns):
                ret = returns[i]['return_pct']
                day_count += 1
                color = "+" if ret >= 0 else ""
                row += f" {color}{ret:.2f}% |"
            else:
                row += " - |"
        
        if day_count > 0:
            cumulative_ret = returns[day_count - 1]['return_pct']
            avg_return = cumulative_ret / day_count
            total_cumulative += cumulative_ret
            valid_count += 1
            cum_color = "+" if cumulative_ret >= 0 else ""
            avg_color = "+" if avg_return >= 0 else ""
            row += f" {cum_color}{cumulative_ret:.2f}% | {avg_color}{avg_return:.2f}% |"
        else:
            row += " - | - |"
        
        lines.append(row)
    
    lines.append("")
    lines.append("## 整体统计")
    lines.append("")
    if valid_count > 0:
        overall_avg = total_cumulative / valid_count
        lines.append(f"- **有效股票数**: {valid_count}")
        lines.append(f"- **平均{trading_days}日累计收益**: {'+' if overall_avg >= 0 else ''}{overall_avg:.2f}%")
    else:
        lines.append("- 无有效数据")
    
    lines.append("")
    lines.append("## 每日详情")
    lines.append("")
    
    for stock in stocks:
        code = stock['code']
        returns = all_returns.get(code, [])
        
        lines.append(f"### {stock['rank']}. {stock['name']} ({code})")
        lines.append("")
        if returns:
            lines.append("| 日期 | 开盘价 | 收盘价 | 累计收益率 |")
            lines.append("|------|--------|--------|------------|")
            for r in returns:
                color = "+" if r['return_pct'] >= 0 else ""
                lines.append(f"| {r['date']} | {r['open']:.2f} | {r['close']:.2f} | {color}{r['return_pct']:.2f}% |")
        else:
            lines.append("*数据获取失败*")
        lines.append("")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    return output_path


async def run_backtest(md_filename: str, start_date: str, trading_days: int = 5):
    """执行回测"""
    results_dir = os.path.join(project_root, 'results')
    md_path = os.path.join(results_dir, md_filename)
    
    if not os.path.exists(md_path):
        print(f"✗ 文件不存在: {md_path}")
        return None
    
    print(f"📄 读取文件: {md_filename}")
    stocks = parse_top10_md(md_path)
    
    if not stocks:
        print("✗ 未能解析出股票数据")
        return None
    
    print(f"✓ 解析到 {len(stocks)} 只股票")
    for s in stocks:
        print(f"   {s['rank']}. {s['name']} ({s['code']}) - {s['score']:.2f}分")
    
    print(f"\n📅 买入起始日期: {start_date}")
    print(f"📊 统计交易日数: {trading_days}")
    print(f"\n正在获取K线数据...")
    
    all_returns = {}
    for stock in stocks:
        code = stock['code']
        print(f"  获取 {stock['name']} ({code})...")
        
        df = await fetch_kline_data(code, start_date, days=trading_days + 10)
        if df is not None and not df.empty:
            returns = calculate_daily_returns(df, start_date, trading_days)
            all_returns[code] = returns
            if returns:
                print(f"    ✓ 获取到 {len(returns)} 天数据")
            else:
                print(f"    ⚠ 指定日期范围内无数据")
        else:
            all_returns[code] = []
            print(f"    ✗ 数据获取失败")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"backtest_top10_{timestamp}.md"
    output_path = os.path.join(results_dir, output_filename)
    
    print(f"\n📝 生成报告...")
    generate_report(stocks, all_returns, start_date, output_path, trading_days)
    print(f"✓ 报告已生成: {output_path}")
    
    return output_path


def main():
    """主函数 - 交互式输入"""
    print("=" * 60)
    print("  TOP10股票持有收益回测工具")
    print("=" * 60)
    print("")
    
    results_dir = os.path.join(project_root, 'results')
    md_files = [f for f in os.listdir(results_dir) if f.startswith('opportunity_top10') and f.endswith('.md')]
    md_files.sort(reverse=True)
    
    if md_files:
        print("可用的opportunity_top10文件:")
        for i, f in enumerate(md_files[:10], 1):
            print(f"  {i}. {f}")
        print("")
    
    md_filename = input("请输入/粘贴md文件名: ").strip()
    if not md_filename:
        if md_files:
            md_filename = md_files[0]
            print(f"(未输入，默认使用最新文件) {md_filename}")
        else:
            print("✗ 文件名不能为空")
            return
    
    start_date = input("请输入买入起始日期 (格式: YYYY-MM-DD): ").strip()
    if not start_date:
        print("✗ 日期不能为空")
        return
    
    try:
        datetime.strptime(start_date, '%Y-%m-%d')
    except ValueError:
        print("✗ 日期格式错误，请使用 YYYY-MM-DD 格式")
        return
    
    trading_days_input = input("请输入统计交易日数 (默认5): ").strip()
    trading_days = int(trading_days_input) if trading_days_input else 5
    
    print("")
    asyncio.run(run_backtest(md_filename, start_date, trading_days))


if __name__ == "__main__":
    main()
