#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Investment Opportunity Discovery - Main Script
Multi-dimensional stock analysis and opportunity discovery
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
import time

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from scripts.hot_stocks_fetcher import HotStocksFetcher
from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter
from scripts.opportunity_report_generator import OpportunityReportGenerator
from analysis.llm_service import LLMConfig, LLMAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class OpportunityDiscovery:
    """Investment Opportunity Discovery System"""

    def __init__(self, max_workers: int = 10):
        """
        Initialize discovery system

        Args:
            max_workers: Maximum concurrent threads
        """
        self.hot_stocks_fetcher = HotStocksFetcher(disable_cache=True)
        self.scorer = OpportunityScorer()
        self.filter = OpportunityFilter()
        output_dir = os.environ.get('KRONOS_RESULTS_DIR', 'results')
        self.report_generator = OpportunityReportGenerator(output_dir=output_dir)
        self.max_workers = max_workers
        self.global_hot_news = []

    def run(self, limit: int = 100, test_codes: Optional[List[str]] = None,
            output_dir: str = 'results', enable_llm: bool = True) -> str:
        """
        Run complete opportunity discovery pipeline

        Args:
            limit: Number of hot stocks to analyze
            test_codes: Test stock codes (optional)
            output_dir: Output directory for reports
            enable_llm: Enable LLM analysis

        Returns:
            Path to generated report
        """
        logger.info("=" * 60)
        logger.info("🎯 Investment Opportunity Discovery Started")
        logger.info("=" * 60)

        start_time = datetime.now()

        # Step 1: Fetch hot stocks
        if test_codes:
            logger.info(f"\nStep 1: Using test stock codes: {test_codes}")
            hot_stocks = self._prepare_test_stocks(test_codes)
        else:
            logger.info(f"\nStep 1: Fetching hot stocks TOP {limit}...")
            hot_stocks = self.hot_stocks_fetcher.get_hot_stocks(limit=limit, force_refresh=True)

        if not hot_stocks:
            logger.error("✗ Failed to fetch hot stocks")
            return ""

        logger.info(f"✓ Successfully fetched {len(hot_stocks)} hot stocks")

        # Step 1.5: Collect global hot news
        try:
            from analysis.global_hot_news_collector import GlobalHotNewsCollector
            news_collector = GlobalHotNewsCollector()
            self.global_hot_news = news_collector.get_top_news(limit=10)
            logger.info(f"✓ Collected {len(self.global_hot_news)} global hot news")
        except Exception as e:
            logger.warning(f"Hot news collection failed: {e}")
            self.global_hot_news = []

        # Step 2: Multi-dimensional scoring
        logger.info(f"\nStep 2: Running multi-dimensional scoring...")
        logger.info(f"Concurrent threads: {self.max_workers}")

        scored_stocks = self._batch_score(hot_stocks)
        logger.info(f"✓ Completed {len(scored_stocks)}/{len(hot_stocks)} stock analyses")

        # Step 3: Apply filters
        logger.info(f"\nStep 3: Applying filter pipeline...")

        filter_results = []
        for stock_data in scored_stocks:
            filter_result = self.filter.apply_all_filters(stock_data)
            filter_results.append(filter_result)

        passed_count = sum(1 for r in filter_results if r.get('passed', False))
        logger.info(f"✓ Filtering complete: {passed_count}/{len(filter_results)} stocks passed")

        # Step 3.5: LLM Analysis (Optional)
        if enable_llm:
            logger.info(f"\nStep 3.5: Running LLM deep analysis...")
            try:
                llm_config = LLMConfig()
                if llm_config.is_configured():
                    llm_analyzer = LLMAnalyzer(llm_config)

                    # Select high-grade stocks (score ≥60)
                    passed_stocks = [
                        r for r in filter_results
                        if r.get('passed', False) and
                        r.get('scoring_result', {}).get('total_score', 0) >= 60
                    ]
                    passed_stocks.sort(
                        key=lambda x: x.get('scoring_result', {}).get('total_score', 0),
                        reverse=True
                    )

                    # Top 10 by score
                    high_grade_stocks = passed_stocks[:10]

                    if high_grade_stocks:
                        logger.info(f"Found {len(high_grade_stocks)} high-grade stocks (≥60 pts)")

                        max_workers = min(5, max(2, len(high_grade_stocks) // 2))
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            future_to_stock = {
                                executor.submit(self._process_llm_task, llm_analyzer, stock): stock
                                for stock in high_grade_stocks
                            }

                            for future in as_completed(future_to_stock):
                                try:
                                    future.result()
                                except Exception as e:
                                    logger.error(f"LLM task failed: {e}")

                        logger.info(f"✓ LLM analysis complete: {len(high_grade_stocks)} stocks")
                    else:
                        logger.info("No stocks meet LLM analysis criteria (≥60 pts)")
                else:
                    logger.info("⏭️ LLM not configured, skipping analysis")
            except Exception as e:
                logger.warning(f"LLM analysis failed: {e}")

        # Step 4: Generate report
        logger.info(f"\nStep 4: Generating investment report...")

        report_path = self.report_generator.generate_report(
            analysis_results=filter_results,
            report_title="Investment Opportunity Discovery Report",
            global_hot_news=self.global_hot_news
        )

        # Complete
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("\n" + "=" * 60)
        logger.info("🎉 Investment Discovery Complete!")
        logger.info("=" * 60)
        logger.info(f"Total time: {duration:.1f} seconds")
        logger.info(f"Analyzed stocks: {len(scored_stocks)}")
        logger.info(f"Passed filters: {passed_count}")
        logger.info(f"Report path: {report_path}")
        logger.info("=" * 60)

        return report_path

    def _prepare_test_stocks(self, test_codes: List[str]) -> List[Dict]:
        """Prepare test stocks"""
        hot_stocks = []
        for code in test_codes:
            hot_stocks.append({
                'code': code,
                'name': f'Test_{code}',
                'price': 0,
                'change_pct': 0
            })
        return hot_stocks

    def _batch_score(self, hot_stocks: List[Dict]) -> List[Dict]:
        """Batch score stocks"""
        scored_stocks = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_stock = {
                executor.submit(self._score_single, stock): stock
                for stock in hot_stocks
            }

            for future in as_completed(future_to_stock):
                stock = future_to_stock[future]
                try:
                    result = future.result()
                    if result:
                        scored_stocks.append(result)
                except Exception as e:
                    logger.error(f"Scoring failed {stock.get('code')}: {e}")

        return scored_stocks

    def _score_single(self, stock: Dict) -> Optional[Dict]:
        """Score single stock"""
        stock_code = stock.get('code', '')
        try:
            scoring_result = self.scorer.calculate_comprehensive_score(
                stock_code,
                global_hot_news=self.global_hot_news
            )

            if not scoring_result:
                return None

            return {
                'stock_code': stock_code,
                'name': stock.get('name', 'Unknown'),
                'exchange': stock.get('exchange', 'UNKNOWN'),
                'popularity_score': stock.get('popularity_score', 0),
                'scoring_result': scoring_result
            }
        except Exception as e:
            logger.error(f"Analysis failed {stock_code}: {e}")
            return None

    def _process_llm_task(self, llm_analyzer: LLMAnalyzer, stock_result: Dict) -> bool:
        """Process single LLM analysis task"""
        stock_code = stock_result.get('stock_code', '')
        stock_name = stock_result.get('name', '')
        scoring_result = stock_result.get('scoring_result', {})

        try:
            logger.info(f"  Analyzing {stock_code} ({stock_name})...")

            # Prepare LLM data
            stock_data = self._prepare_llm_data(stock_code, stock_name, scoring_result)

            # Run LLM analysis
            success, llm_result = llm_analyzer.analyze_stock(stock_data)

            if success:
                stock_result['llm_analysis'] = llm_result
                logger.info(f"    ✓ {stock_code} LLM analysis complete")
                return True
            else:
                logger.warning(f"    ✗ {stock_code} LLM analysis failed: {llm_result}")
                return False

        except Exception as e:
            logger.error(f"  LLM analysis {stock_code} failed: {e}")
            return False

    def _prepare_llm_data(self, stock_code: str, stock_name: str,
                         scoring_result: Dict) -> Dict:
        """Prepare LLM analysis data"""
        details = scoring_result.get('details', {})

        def _fmt_num(val, digits=2, default='-'):
            if val is None:
                return default
            if isinstance(val, (int, float)):
                return f"{val:.{digits}f}"
            return str(val)

        return {
            'code': stock_code,
            'name': stock_name,
            'current_price': details.get('technical', {}).get('current_price', 0),
            'technical_analysis': str(details.get('technical', {})),
            'quantitative_models': str(details.get('quantitative', {})),
            'fundamental_data': str(details.get('fundamental', {})),
            'sentiment_data': str(details.get('sentiment', {})),
            'sector_data': str(details.get('sector', {})),
            'overall_rating': f"Score: {scoring_result.get('total_score', 0):.1f}, "
                            f"Rating: {scoring_result.get('rating', 'C')}"
        }


def main():
    parser = argparse.ArgumentParser(description='Investment Opportunity Discovery')
    parser.add_argument('--limit', type=int, default=100,
                       help='Number of hot stocks to analyze (default: 100)')
    parser.add_argument('--workers', type=int, default=10,
                       help='Concurrent processing threads (default: 10)')
    parser.add_argument('--test-codes', type=str,
                       help='Test stock codes, comma-separated')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='Output directory for reports')
    parser.add_argument('--no-llm', action='store_true',
                       help='Disable LLM analysis')

    args = parser.parse_args()

    test_codes = None
    if args.test_codes:
        test_codes = args.test_codes.split(',')

    discovery = OpportunityDiscovery(max_workers=args.workers)
    discovery.run(
        limit=args.limit,
        test_codes=test_codes,
        output_dir=args.output_dir,
        enable_llm=not args.no_llm
    )


if __name__ == "__main__":
    main()
