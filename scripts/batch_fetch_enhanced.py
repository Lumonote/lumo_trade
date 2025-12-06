#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版批量股票数据获取脚本
支持多数据源、智能分批采集、数据补全
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 导入多源数据获取器（支持多爬虫自动切换）
try:
    from scripts.fetch_data import MultiSourceDataFetcher

    MULTI_SOURCE_FETCHER_AVAILABLE = True
    print("✅ 多源数据获取器已加载（支持多爬虫自动切换）")
except ImportError as e:
    MULTI_SOURCE_FETCHER_AVAILABLE = False
    print(f"❌ 多源数据获取器不可用: {e}")
    sys.exit(1)


def get_standard_filename(symbol: str, period: str) -> str:
    """生成标准的文件名格式，与data目录现有格式一致"""
    # 转换股票代码格式
    if '.' in symbol:
        code, exchange = symbol.split('.')
        if exchange == 'SZ':
            exchange_code = 'XSHE'
        elif exchange == 'SH':
            exchange_code = 'XSHG'
        else:
            exchange_code = exchange
    else:
        # 根据股票代码推断交易所
        code = symbol.zfill(6)
        if code.startswith(('000', '001', '002', '003', '300')):
            exchange_code = 'XSHE'  # 深交所
        elif code.startswith(('600', '601', '603', '605', '688')):
            exchange_code = 'XSHG'  # 上交所
        else:
            exchange_code = 'XSHG'  # 默认上交所

    # 转换周期格式
    if period in ['5m', '5min']:
        period_str = '5m'
    elif period == '1m':
        period_str = '1min'
    elif period == '15m':
        period_str = '15min'
    elif period == '30m':
        period_str = '30min'
    elif period == '1h':
        period_str = '1h'
    elif period == '1d':
        period_str = 'D'
    else:
        period_str = period

    # 生成标准格式文件名: 5m_300555.csv
    return f"{period_str}_{code}.csv"


async def batch_fetch_stocks(symbols: List[str], source: str = 'auto',
                             period: str = '5m', start_date: str = None,
                             end_date: str = None, min_days: int = 365,
                             output_dir: str = 'data') -> Dict[str, Any]:
    """
    批量获取多只股票的数据
    
    Args:
        symbols: 股票代码列表
        source: 数据源
        period: 数据周期
        start_date: 开始日期
        end_date: 结束日期
        min_days: 最少天数
        output_dir: 输出目录
        
    Returns:
        批量获取结果统计
    """
    # 创建输出目录
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # 设置默认时间范围
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')

    if not start_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        start_dt = end_dt - timedelta(days=min_days)
        start_date = start_dt.strftime('%Y-%m-%d')

    print(f"🚀 启动批量数据获取")
    print(f"📊 股票数量: {len(symbols)}")
    print(f"🌐 数据源: {source}")
    print(f"⏰ 数据周期: {period}")
    print(f"📅 时间范围: {start_date} 到 {end_date}")
    print(f"📁 输出目录: {output_path}")
    print(f"=== 开始处理 ===\n")

    # 初始化多源数据获取器（支持多爬虫自动切换）
    fetcher = MultiSourceDataFetcher()

    # 批量处理结果统计
    results = {
        'total': len(symbols),
        'success': 0,
        'failed': 0,
        'success_list': [],
        'failed_list': [],
        'success_details': [],  # 新增详细信息
        'files': []
    }

    for i, symbol in enumerate(symbols, 1):
        print(f"📈 [{i}/{len(symbols)}] 处理股票: {symbol}")
        start_time = asyncio.get_event_loop().time()

        try:
            # 获取数据 - 使用新的多爬虫自动切换功能
            df = await fetcher.fetch_stock_data(
                symbol=symbol,
                source=source,
                freq=period,  # period 对应 freq 参数
                start_date=start_date,
                end_date=end_date,
                auto_extend=True,
                min_days=min_days
            )

            if df is not None and not df.empty:
                # 使用数据获取器的save_data方法保存数据（与现有格式兼容）
                try:
                    filepath = fetcher.save_data(df, symbol, period)

                    if filepath and Path(filepath).exists():
                        # 计算处理时间
                        end_time = asyncio.get_event_loop().time()
                        time_taken = end_time - start_time

                        results['success'] += 1
                        results['success_list'].append(symbol)
                        results['success_details'].append({
                            'symbol': symbol,
                            'records': len(df),
                            'time_taken': time_taken,
                            'filepath': filepath
                        })
                        results['files'].append(filepath)

                        print(f"✅ [{i}/{len(symbols)}] {symbol} 成功: {len(df)} 条记录 -> {filepath}")

                        # 显示数据概览
                        if not df.empty:
                            time_range = f"{df['timestamps'].min()} 到 {df['timestamps'].max()}" if 'timestamps' in df.columns else "N/A"
                            price_range = f"{df['close'].min():.2f} - {df['close'].max():.2f}" if 'close' in df.columns else "N/A"
                            print(f"   📊 时间范围: {time_range}")
                            print(f"   💰 价格范围: {price_range}")

                        # 验证文件保存成功
                        file_size = Path(filepath).stat().st_size
                        print(f"   💾 文件大小: {file_size:,} 字节")
                    else:
                        print(f"❌ [{i}/{len(symbols)}] {symbol} 保存失败: 文件保存异常")
                        results['failed'] += 1
                        results['failed_list'].append(symbol)

                except Exception as save_error:
                    print(f"❌ [{i}/{len(symbols)}] {symbol} 保存失败: {save_error}")
                    results['failed'] += 1
                    results['failed_list'].append(symbol)
            else:
                results['failed'] += 1
                results['failed_list'].append(symbol)
                print(f"❌ [{i}/{len(symbols)}] {symbol} 失败: 未获取到数据 (已自动尝试所有可用数据源)")

        except Exception as e:
            results['failed'] += 1
            results['failed_list'].append(symbol)
            print(f"❌ [{i}/{len(symbols)}] {symbol} 出错: {e}")

        # 添加延时避免请求过快
        if i < len(symbols):
            print(f"⏱️ 等待 1 秒...\n")
            await asyncio.sleep(1)

    return results


def print_batch_results(results: Dict[str, Any]):
    """打印批量处理结果（支持多爬虫自动切换功能统计）"""
    print(f"\n{'=' * 60}")
    print(f"📊 多爬虫自动切换批量获取完成统计")
    print(f"{'=' * 60}")

    # 使用results中的统计数据，这些是在处理过程中实时累计的准确数据
    total = results.get('total', 0)
    success_count = results.get('success', 0)
    failed_count = results.get('failed', 0)

    print(f"📈 总股票数: {total}")
    print(f"✅ 成功: {success_count} ({success_count / total * 100:.1f}%)" if total > 0 else "✅ 成功: 0")
    print(f"❌ 失败: {failed_count} ({failed_count / total * 100:.1f}%)" if total > 0 else "❌ 失败: 0")

    # 显示唯一股票代码统计（用于参考）
    unique_success_symbols = list(dict.fromkeys(results.get('success_list', [])))
    unique_failed_symbols = list(dict.fromkeys(results.get('failed_list', [])))

    if len(unique_success_symbols) != success_count or len(unique_failed_symbols) != failed_count:
        print(f"📋 唯一股票代码统计:")
        print(f"   ✅ 成功的唯一股票: {len(unique_success_symbols)}")
        print(f"   ❌ 失败的唯一股票: {len(unique_failed_symbols)}")

    # 计算总记录数和总耗时（基于去重后的数据）
    unique_details = {}
    total_time = 0

    for detail in results.get('success_details', []):
        symbol = detail.get('symbol')
        if symbol and symbol not in unique_details:
            unique_details[symbol] = detail
            total_time += detail.get('time_taken', 0)

    total_records = sum(detail.get('records', 0) for detail in unique_details.values())

    if total_records > 0:
        print(f"📊 总记录数: {total_records:,}")
        print(f"⏱️ 总耗时: {total_time:.1f}秒")

        if total_time > 0:
            avg_speed = total_records / total_time
            print(f"⚡ 平均速度: {avg_speed:.1f} 记录/秒")

    if results['success_list']:
        print(f"\n✅ 成功获取的股票:")
        # 使用字典去重并保留详细信息
        unique_success = {}
        for i, symbol in enumerate(results['success_list']):
            if symbol not in unique_success:
                # 查找对应的详细信息
                symbol_details = None
                for detail in results.get('success_details', []):
                    if detail.get('symbol') == symbol:
                        symbol_details = detail
                        break

                if symbol_details:
                    unique_success[symbol] = {
                        'records': symbol_details.get('records', 0),
                        'time_taken': symbol_details.get('time_taken', 0)
                    }
                else:
                    unique_success[symbol] = {'records': 0, 'time_taken': 0}

        # 显示去重后的结果
        for symbol, details in unique_success.items():
            records = details['records']
            time_taken = details['time_taken']
            print(f"{symbol}: {records:,} 条记录 ({time_taken:.1f}s)")

        # 检查是否有重复（用于调试）
        if len(results['success_list']) > len(unique_success):
            duplicate_count = len(results['success_list']) - len(unique_success)
            print(f"\n⚠️  检测到 {duplicate_count} 个重复处理，已自动去重显示")

    if results['failed_list']:
        # 对失败列表也进行去重
        unique_failed = list(dict.fromkeys(results['failed_list']))
        print(f"\n❌ 获取失败的股票:")
        for symbol in unique_failed:
            print(f"{symbol}: 所有数据源均无法获取数据")

    if results['files']:
        # 文件列表也去重
        unique_files = list(dict.fromkeys(results['files']))
        print(f"\n📁 生成的数据文件 ({len(unique_files)}个):")
        for i, filepath in enumerate(unique_files, 1):
            print(f"  {i}. {Path(filepath).name}")

    print(f"\n💡 多爬虫自动切换功能:")
    print(f"   - 自动尝试 Tushare、东方财富、同花顺、雪球等多个数据源")
    print(f"   - 单个数据源失败时自动切换到其他可用数据源")
    print(f"   - 确保数据获取的可靠性和成功率")
    print(f"\n{'=' * 60}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='增强版批量股票数据获取')
    parser.add_argument('--symbols', '-s', required=True,
                        help='股票代码列表，用逗号分隔')
    parser.add_argument('--source', choices=['auto', 'tushare', 'crawler', 'eastmoney', 'tonghuashun', 'xueqiu'],
                        default='auto', help='数据源')
    parser.add_argument('--period', '-p', default='5m',
                        help='数据周期 (1m, 5m, 15m, 30m, 1h, 1d, 1w, 1M)')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--min-days', type=int, default=365,
                        help='最少获取天数')
    parser.add_argument('--output-dir', default='data',
                        help='输出目录')
    parser.add_argument('--config', help='配置文件路径')

    args = parser.parse_args()

    # 解析股票代码列表，并去重
    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
    symbols = list(dict.fromkeys(symbols))  # 保持顺序去重

    if not symbols:
        print("❌ 未提供有效的股票代码")
        return 1

    print(f"📊 解析到 {len(symbols)} 个唯一股票代码: {', '.join(symbols)}")

    try:
        # 执行批量获取
        results = await batch_fetch_stocks(
            symbols=symbols,
            source=args.source,
            period=args.period,
            start_date=args.start_date,
            end_date=args.end_date,
            min_days=args.min_days,
            output_dir=args.output_dir
        )

        # 打印结果
        print_batch_results(results)

        # 根据结果设置退出码
        if results['success'] == 0:
            print("\n❌ 所有股票获取都失败")
            return 1
        elif results['failed'] > 0:
            print(f"\n⚠️ 部分股票获取失败 ({results['failed']}/{results['total']})")
            return 2
        else:
            print(f"\n🎉 所有股票获取成功!")
            return 0

    except KeyboardInterrupt:
        print("\n⏹️ 用户中断操作")
        return 130
    except Exception as e:
        print(f"\n❌ 批量获取失败: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
