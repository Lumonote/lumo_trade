#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘 - 主程序
整合热门股票获取、多维度打分、漏斗筛选、报表生成
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.hot_stocks_fetcher import HotStocksFetcher
from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter
from scripts.opportunity_report_generator import OpportunityReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class OpportunityDiscovery:
    """投资机会挖掘系统"""

    def __init__(self, max_workers: int = 10):
        """
        初始化投资机会挖掘系统

        Args:
            max_workers: 并发处理的最大线程数
        """
        self.hot_stocks_fetcher = HotStocksFetcher()
        self.scorer = OpportunityScorer()
        self.filter = OpportunityFilter()
        # 尊重打包环境的结果目录设置
        output_dir = os.environ.get('KRONOS_RESULTS_DIR', 'results')
        self.report_generator = OpportunityReportGenerator(output_dir=output_dir)
        self.max_workers = max_workers

    def run(self, limit: int = 100) -> str:
        """
        运行完整的投资机会挖掘流程

        Args:
            limit: 获取热门股票的数量（默认100）

        Returns:
            生成的报表文件路径
        """
        logger.info("=" * 60)
        logger.info("🎯 投资机会挖掘系统启动")
        logger.info("=" * 60)

        start_time = datetime.now()

        # 步骤1: 获取热门股票 TOP 100
        logger.info(f"\n步骤1: 正在获取热门股票 TOP {limit}...")
        # 强制直接采集，避免使用缓存或本地回退
        hot_stocks = self.hot_stocks_fetcher.get_hot_stocks(limit=limit, force_refresh=True)

        if not hot_stocks:
            logger.error("✗ 获取热门股票失败，程序终止")
            return ""

        logger.info(f"✓ 成功获取 {len(hot_stocks)} 只热门股票")

        # 步骤2: 多维度打分分析（并发处理）
        logger.info(f"\n步骤2: 正在进行多维度打分分析...")
        logger.info(f"并发线程数: {self.max_workers}")

        scored_stocks = []
        completed_count = 0
        total_count = len(hot_stocks)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有分析任务
            future_to_stock = {
                executor.submit(self._analyze_single_stock, stock): stock
                for stock in hot_stocks
            }

            # 收集结果
            for future in as_completed(future_to_stock):
                stock = future_to_stock[future]
                try:
                    result = future.result()
                    if result:
                        scored_stocks.append(result)

                    completed_count += 1

                    # 显示进度
                    progress = (completed_count / total_count) * 100
                    logger.info(f"进度: {completed_count}/{total_count} ({progress:.1f}%) - {stock.get('name', stock.get('code'))}")

                except Exception as e:
                    logger.error(f"分析 {stock.get('code')} 失败: {e}")
                    completed_count += 1

        logger.info(f"✓ 完成 {len(scored_stocks)}/{total_count} 只股票的分析")

        # 步骤3: 漏斗筛选
        logger.info(f"\n步骤3: 正在进行漏斗筛选...")

        filter_results = []
        for stock_data in scored_stocks:
            filter_result = self.filter.apply_all_filters(stock_data)
            filter_results.append(filter_result)

        # 统计筛选结果
        passed_count = sum(1 for r in filter_results if r.get('passed', False))
        logger.info(f"✓ 筛选完成: {passed_count}/{len(filter_results)} 只股票通过")

        # 步骤4: 生成报表
        logger.info(f"\n步骤4: 正在生成投资机会挖掘报表...")

        report_path = self.report_generator.generate_report(
            analysis_results=filter_results,
            report_title="投资机会挖掘报告"
        )

        # 完成
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("\n" + "=" * 60)
        logger.info("🎉 投资机会挖掘完成！")
        logger.info("=" * 60)
        logger.info(f"总耗时: {duration:.1f} 秒")
        logger.info(f"分析股票: {len(scored_stocks)} 只")
        logger.info(f"通过筛选: {passed_count} 只")
        logger.info(f"报表路径: {report_path}")
        logger.info("=" * 60)

        return report_path

    def _analyze_single_stock(self, hot_stock: Dict) -> Dict:
        """
        分析单只股票

        Args:
            hot_stock: 热门股票信息 (来自HotStocksFetcher)

        Returns:
            {
                'stock_code': '000001',
                'name': '平安银行',
                'exchange': 'SZ',
                'popularity_score': 95.5,
                'scoring_result': {...}  # OpportunityScorer的结果
            }
        """
        stock_code = hot_stock.get('code', '')
        stock_name = hot_stock.get('name', '未知')

        try:
            # 多维度打分
            scoring_result = self.scorer.calculate_comprehensive_score(stock_code)

            return {
                'stock_code': stock_code,
                'name': stock_name,
                'exchange': hot_stock.get('exchange', 'UNKNOWN'),
                'popularity_score': hot_stock.get('popularity_score', 0),
                'scoring_result': scoring_result
            }

        except Exception as e:
            logger.error(f"分析 {stock_code} ({stock_name}) 失败: {e}")
            return None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='投资机会挖掘系统')
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='获取热门股票的数量（默认100）'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=10,
        help='并发处理线程数（默认10）'
    )

    args = parser.parse_args()

    # 创建并运行
    discovery = OpportunityDiscovery(max_workers=args.workers)
    report_path = discovery.run(limit=args.limit)

    if report_path and os.path.exists(report_path):
        print(f"\n✓ 报表已生成: {report_path}")

        # 尝试在浏览器中打开报表
        try:
            import webbrowser
            abs_path = os.path.abspath(report_path)
            webbrowser.open(f'file://{abs_path}')
            print(f"✓ 报表已在浏览器中打开")
        except Exception as e:
            print(f"自动打开浏览器失败: {e}")
            print(f"请手动打开: {os.path.abspath(report_path)}")
    else:
        print("\n✗ 报表生成失败")


if __name__ == "__main__":
    main()
