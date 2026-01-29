#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 批量数据获取脚本
批量获取多只股票的历史数据
"""

import os
import sys
import json
import argparse
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# 导入数据获取器
try:
    from scripts.fetch_data import TushareDataFetcher, MultiSourceDataFetcher
except ImportError as e:
    print(f"❌ 无法导入fetch_data模块: {e}")
    print(f"   当前工作目录: {os.getcwd()}")
    print(f"   项目根目录: {project_root}")
    print(f"   Python路径: {sys.path}")

    # 尝试直接导入
    try:
        import fetch_data
        from fetch_data import TushareDataFetcher, MultiSourceDataFetcher

        print("✅ 通过直接导入成功")
    except ImportError as e2:
        print(f"❌ 直接导入也失败: {e2}")
        sys.exit(1)


class BatchDataFetcher:
    """批量数据获取器"""

    def __init__(self, config_path: str = "config/tushare_config.json"):
        """初始化批量获取器"""
        self.config_path = config_path
        self.results = []
        self.lock = threading.Lock()

        # 尝试初始化多数据源获取器
        try:
            self.fetcher = MultiSourceDataFetcher(config_path)
            self.use_multi_source = True
            print("✅ 多数据源获取器初始化成功")
        except Exception as e:
            print(f"⚠️  多数据源获取器初始化失败: {e}")
            # 回退到单一Tushare数据源
            try:
                self.config = self._load_config(config_path)
                self.fetcher = TushareDataFetcher(self.config)
                self.use_multi_source = False
                print("✅ Tushare数据源初始化成功")
            except Exception as e2:
                print(f"❌ 所有数据源初始化失败: {e2}")
                raise e2

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except FileNotFoundError:
            print(f"❌ 配置文件不存在: {config_path}")
            print("请先运行安装脚本创建配置文件")
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        except json.JSONDecodeError as e:
            print(f"❌ 配置文件格式错误: {e}")
            raise json.JSONDecodeError(f"配置文件格式错误: {e}", "", 0)

    def load_stock_list(self, list_file: str = None) -> List[str]:
        """加载股票列表"""
        stocks = []

        if list_file and Path(list_file).exists():
            # 从文件加载
            try:
                with open(list_file, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content.startswith('[') and content.endswith(']'):
                        # JSON格式
                        stocks = json.loads(content)
                    else:
                        # 每行一个股票代码
                        stocks = [line.strip() for line in content.split('\n') if line.strip()]
                print(f"✅ 从文件加载了 {len(stocks)} 只股票")
            except Exception as e:
                print(f"❌ 加载股票列表失败: {e}")
        else:
            # 使用配置文件中的默认列表
            try:
                stocks = self.config.get('stock_lists', {}).get('popular_stocks', [])
                print(f"✅ 使用配置文件中的默认股票列表 ({len(stocks)} 只)")
            except Exception as e:
                print(f"❌ 加载默认股票列表失败: {e}")

        return stocks

    async def fetch_single_stock(self, symbol: str, **kwargs) -> Dict[str, Any]:
        """获取单只股票数据"""
        result = {
            'symbol': symbol,
            'success': False,
            'filepath': '',
            'records': 0,
            'error': '',
            'start_time': datetime.now()
        }

        try:
            print(f"🔄 开始获取: {symbol}")

            # 获取数据
            if self.use_multi_source:
                # 使用异步多数据源获取器，优先使用Tushare，然后是爬虫
                # 批量分析时优先使用Tushare，失败后使用爬虫作为备选
                available_sources = self.fetcher.get_available_sources()
                
                df = None
                # 优先尝试Tushare
                if 'tushare' in available_sources:
                    try:
                        print(f"📡 尝试Tushare数据源...")
                        df = await self.fetcher.fetch_stock_data(
                            symbol=symbol,
                            start_date=kwargs.get('start_date'),
                            end_date=kwargs.get('end_date'),
                            freq=kwargs.get('freq', '5min'),
                            source='tushare',  # 明确指定Tushare
                            adj=kwargs.get('adj', 'qfq'),
                            auto_extend=kwargs.get('auto_extend', True),
                            min_days=kwargs.get('min_days', 365)
                        )
                        if df is not None and not df.empty:
                            print(f"✅ Tushare数据源成功获取 {len(df)} 条数据")
                    except Exception as e:
                        print(f"⚠️ Tushare数据源失败: {e}")
                
                # 如果Tushare失败，尝试爬虫数据源作为备选
                if df is None or df.empty:
                    print(f"⚠️ Tushare数据源不可用，尝试爬虫数据源作为备选...")
                    crawler_sources = [s for s in available_sources if s in ['eastmoney', 'tonghuashun', 'xueqiu']]
                    for crawler_source in crawler_sources:
                        try:
                            print(f"📡 尝试爬虫数据源: {crawler_source}")
                            df = await self.fetcher.fetch_stock_data(
                                symbol=symbol,
                                start_date=kwargs.get('start_date'),
                                end_date=kwargs.get('end_date'),
                                freq=kwargs.get('freq', '5min'),
                                source=crawler_source,
                                adj=kwargs.get('adj', 'qfq'),
                                auto_extend=kwargs.get('auto_extend', True),
                                min_days=kwargs.get('min_days', 365)
                            )
                            if df is not None and not df.empty:
                                print(f"✅ 爬虫数据源 {crawler_source} 成功获取 {len(df)} 条数据")
                                break
                        except Exception as e:
                            print(f"⚠️ 爬虫数据源 {crawler_source} 失败: {e}")
                            continue
            else:
                # 使用同步Tushare获取器
                df = self.fetcher.fetch_stock_data(
                    symbol=symbol,
                    start_date=kwargs.get('start_date'),
                    end_date=kwargs.get('end_date'),
                    freq=kwargs.get('freq', '5min'),
                    adj=kwargs.get('adj', 'qfq')
                )

            if df is not None and not df.empty:
                # 保存数据
                filepath = self.fetcher.save_data(df, symbol, kwargs.get('freq', '5min'))

                if filepath:
                    # 检查是否有timestamp列来生成时间范围
                    time_range = "N/A"
                    if 'timestamp' in df.columns and not df['timestamp'].empty:
                        try:
                            time_range = f"{df['timestamp'].min()} - {df['timestamp'].max()}"
                        except Exception as e:
                            print(f"⚠️  时间范围计算失败: {e}")

                    result.update({
                        'success': True,
                        'filepath': filepath,
                        'records': len(df),
                        'time_range': time_range
                    })
                    print(f"✅ {symbol}: {len(df)} 条记录")
                else:
                    result['error'] = '保存失败'
                    print(f"❌ {symbol}: 保存失败")
            else:
                result['error'] = '无数据'
                print(f"⚠️  {symbol}: 无数据")

        except Exception as e:
            result['error'] = str(e)
            print(f"❌ {symbol}: {str(e)}")

        result['end_time'] = datetime.now()
        result['duration'] = (result['end_time'] - result['start_time']).total_seconds()

        # 线程安全地添加结果
        with self.lock:
            self.results.append(result)

        return result

    async def batch_fetch(self,
                          stock_list: List[str],
                          start_date: str = None,
                          end_date: str = None,
                          freq: str = '5min',
                          adj: str = 'qfq',
                          max_workers: int = 3,
                          delay: float = 1.0,
                          auto_extend: bool = True,
                          min_days: int = 365) -> List[Dict[str, Any]]:
        """批量获取股票数据"""

        # 根据min_days设置时间范围
        if not start_date and not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
            # 使用用户指定的天数，而不是固定的365天
            actual_days = min_days if min_days else 365
            start_date = (datetime.now() - timedelta(days=actual_days)).strftime('%Y-%m-%d')
            print(f"📅 使用{actual_days}天时间范围: {start_date} - {end_date}")

        print(f"🚀 开始批量获取 {len(stock_list)} 只股票的数据")
        print(f"📅 时间范围: {start_date or '默认'} - {end_date or '默认'}")
        print(f"⏱️  频率: {freq}, 复权: {adj}")
        print(f"🔧 并发数: {max_workers}, 延迟: {delay}s")
        print("=" * 50)

        self.results = []  # 重置结果

        # 准备参数
        fetch_kwargs = {
            'start_date': start_date,
            'end_date': end_date,
            'freq': freq,
            'adj': adj,
            'auto_extend': auto_extend,
            'min_days': min_days
        }

        if self.use_multi_source:
            # 使用异步方式处理
            semaphore = asyncio.Semaphore(max_workers)
            tasks = []

            async def fetch_with_semaphore(symbol, delay_time=0):
                if delay_time > 0:
                    await asyncio.sleep(delay_time)
                async with semaphore:
                    return await self.fetch_single_stock(symbol, **fetch_kwargs)

            for i, symbol in enumerate(stock_list):
                delay_time = delay * i if i > 0 else 0
                task = fetch_with_semaphore(symbol, delay_time)
                tasks.append(task)

            # 等待所有任务完成
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ 任务执行异常: {result}")
                else:
                    with self.lock:
                        self.results.append(result)
        else:
            # 使用线程池处理同步调用
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交任务
                future_to_symbol = {}
                for i, symbol in enumerate(stock_list):
                    if i > 0:  # 第一个任务不延迟
                        time.sleep(delay)

                    # 创建同步包装函数
                    def sync_fetch(sym, **kw):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(self.fetch_single_stock(sym, **kw))
                        finally:
                            loop.close()

                    future = executor.submit(sync_fetch, symbol, **fetch_kwargs)
                    future_to_symbol[future] = symbol

            # 等待完成
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result()
                except Exception as e:
                    print(f"❌ {symbol} 任务异常: {e}")

        return self.results

    def generate_report(self, results: List[Dict[str, Any]]) -> str:
        """生成获取报告"""
        if not results:
            return "无结果数据"

        # 统计信息（按股票代码去重，避免重复累计）
        unique_map = {}
        for r in results:
            # 保留该股票最后一次结果（更接近最终状态）
            unique_map[r.get('symbol')] = r
        unique_results = list(unique_map.values())

        total = len(unique_results)
        successful_list = [r for r in unique_results if r.get('success')]
        successful = len(successful_list)
        failed = total - successful
        total_records = sum(r.get('records', 0) for r in successful_list)
        total_time = sum(r.get('duration', 0.0) for r in unique_results)

        # 生成报告
        report = []
        report.append("\n" + "=" * 60)
        report.append("📊 批量获取报告")
        report.append("=" * 60)
        report.append(f"📈 总股票数: {total}")
        report.append(f"✅ 成功: {successful} ({successful / total * 100:.1f}%)")
        report.append(f"❌ 失败: {failed} ({failed / total * 100:.1f}%)")
        report.append(f"📊 总记录数: {total_records:,}")
        report.append(f"⏱️  总耗时: {total_time:.1f}秒")
        report.append(f"⚡ 平均速度: {total_records / total_time:.1f} 记录/秒" if total_time > 0 else "")

        # 成功列表（去重后）
        if successful > 0:
            report.append("\n✅ 成功获取的股票:")
            for r in successful_list:
                report.append(f"  {r.get('symbol')}: {r.get('records', 0):,} 条记录 ({r.get('duration', 0.0):.1f}s)")

        # 失败列表（去重后）
        if failed > 0:
            report.append("\n❌ 获取失败的股票:")
            for r in unique_results:
                if not r.get('success'):
                    report.append(f"  {r.get('symbol')}: {r.get('error', '获取失败')}")

        # 保存位置
        report.append("\n📁 数据保存位置:")
        data_dir = Path(self.fetcher.config.get('data_settings', {}).get('output_dir', './data/'))
        report.append(f"  {data_dir.absolute()}")

        report.append("\n💡 提示: 现在可以使用这些数据文件进行Kronos预测")
        report.append("=" * 60)

        return "\n".join(report)

    def save_report(self, results: List[Dict[str, Any]], output_file: str = None) -> str:
        """保存详细报告到文件"""
        if not output_file:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"logs/batch_fetch_report_{timestamp}.json"

        # 确保目录存在
        Path(output_file).parent.mkdir(exist_ok=True)

        # 准备报告数据
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total': len(results),
                'successful': len([r for r in results if r['success']]),
                'failed': len([r for r in results if not r['success']]),
                'total_records': sum(r['records'] for r in results if r['success']),
                'total_time': sum(r['duration'] for r in results)
            },
            'details': results
        }

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
            print(f"📄 详细报告已保存: {output_file}")
            return output_file
        except Exception as e:
            print(f"⚠️  保存报告失败: {e}")
            return ""


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Kronos批量数据获取工具')
    parser.add_argument('--list', '-l', help='股票列表文件路径 (JSON或每行一个代码)')
    parser.add_argument('--symbols', '-s', nargs='+', help='直接指定股票代码列表')
    parser.add_argument('--start-date', help='开始日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--end-date', help='结束日期 (YYYY-MM-DD 或 YYYYMMDD)')
    parser.add_argument('--freq', default='5min',
                        choices=['1min', '5min', '15min', '30min', '60min', 'D'],
                        help='数据频率 (默认: 5min)')
    parser.add_argument('--adj', default='qfq', choices=['qfq', 'hfq', None],
                        help='复权类型 (默认: qfq)')
    parser.add_argument('--workers', type=int, default=3,
                        help='并发线程数 (默认: 3)')
    parser.add_argument('--delay', type=float, default=1.0,
                        help='请求间隔秒数 (默认: 1.0)')
    parser.add_argument('--config', default='config/tushare_config.json',
                        help='配置文件路径')
    parser.add_argument('--save-report', action='store_true',
                        help='保存详细报告到文件')
    parser.add_argument('--no-auto-extend', action='store_true',
                        help='禁用数据自动扩展功能')
    parser.add_argument('--min-days', type=int, default=365,
                        help='最少数据天数 (默认: 365天)')

    args = parser.parse_args()

    print("🚀 Kronos批量数据获取工具启动")
    print("=" * 50)

    # 初始化批量获取器
    try:
        batch_fetcher = BatchDataFetcher(args.config)
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return 1

    # 获取股票列表
    if args.symbols:
        stock_list = args.symbols
        print(f"📋 使用命令行指定的股票列表 ({len(stock_list)} 只)")
    else:
        stock_list = batch_fetcher.load_stock_list(args.list)

    if not stock_list:
        print("❌ 未找到股票列表")
        return 1

    print(f"📊 股票列表: {', '.join(stock_list)}")

    # 开始批量获取
    start_time = datetime.now()

    results = await batch_fetcher.batch_fetch(
        stock_list=stock_list,
        start_date=args.start_date,
        end_date=args.end_date,
        freq=args.freq,
        adj=args.adj,
        max_workers=args.workers,
        delay=args.delay,
        auto_extend=not args.no_auto_extend,
        min_days=args.min_days
    )

    end_time = datetime.now()

    # 生成并显示报告
    report = batch_fetcher.generate_report(results)
    print(report)

    # 保存详细报告
    if args.save_report:
        batch_fetcher.save_report(results)

    # 返回状态码
    successful = len([r for r in results if r['success']])
    exit_code = 0 if successful == len(results) else (2 if successful > 0 else 1)

    # 清理异步资源，避免Windows退出时管道未关闭告警
    try:
        if getattr(batch_fetcher, 'use_multi_source', False) and hasattr(batch_fetcher.fetcher, 'close'):
            await batch_fetcher.fetcher.close()
    except Exception as e:
        print(f"⚠️  资源清理失败: {e}")

    return exit_code


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⚠️  操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        sys.exit(1)
