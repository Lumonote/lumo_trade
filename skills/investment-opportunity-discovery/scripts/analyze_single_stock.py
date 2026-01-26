#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single Stock Analysis Script
Comprehensive multi-dimensional analysis for a single stock
"""

import os
import sys
import argparse
import logging
from typing import Dict, Optional

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter
from analysis.llm_service import LLMConfig, LLMAnalyzer
from scripts.opportunity_report_generator import OpportunityReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def analyze_stock(stock_code: str, enable_llm: bool = True,
                  output_dir: str = 'results') -> Optional[Dict]:
    """
    Analyze single stock with all dimensions

    Args:
        stock_code: Stock code (e.g., '600977')
        enable_llm: Enable LLM analysis
        output_dir: Output directory

    Returns:
        Analysis results dictionary
    """
    logger.info(f"Analyzing stock: {stock_code}")
    logger.info("=" * 60)

    try:
        # Initialize components
        scorer = OpportunityScorer()
        filter_obj = OpportunityFilter()

        # Fetch stock info
        from scripts.hot_stocks_fetcher import HotStocksFetcher
        fetcher = HotStocksFetcher(disable_cache=True)
        hot_stocks = fetcher.get_hot_stocks(limit=1, force_refresh=True)

        stock_info = None
        for stock in hot_stocks:
            if stock.get('code') == stock_code:
                stock_info = stock
                break

        if not stock_info:
            # Construct basic info if not found
            stock_info = {
                'code': stock_code,
                'name': f'Stock_{stock_code}',
                'price': 0,
                'change_pct': 0
            }
            logger.warning(f"Stock {stock_code} not found in hot stocks, using basic info")

        # Run scoring
        logger.info("Running multi-dimensional scoring...")
        scoring_result = scorer.calculate_comprehensive_score(stock_code)

        if not scoring_result:
            logger.error(f"Scoring failed for {stock_code}")
            return None

        # Display results
        _print_scoring_results(stock_code, stock_info, scoring_result)

        # Apply filters
        logger.info("\nApplying filters...")
        stock_data = {
            'stock_code': stock_code,
            'name': stock_info.get('name', 'Unknown'),
            'exchange': stock_info.get('exchange', 'UNKNOWN'),
            'popularity_score': stock_info.get('popularity_score', 0),
            'scoring_result': scoring_result
        }

        filter_result = filter_obj.apply_all_filters(stock_data)
        _print_filter_results(filter_result)

        # LLM Analysis (Optional)
        if enable_llm and scoring_result.get('total_score', 0) >= 60:
            logger.info("\nRunning LLM deep analysis...")
            try:
                llm_config = LLMConfig()
                if llm_config.is_configured():
                    llm_analyzer = LLMAnalyzer(llm_config)

                    stock_data_llm = _prepare_llm_data(
                        stock_code,
                        stock_info.get('name', 'Unknown'),
                        scoring_result
                    )

                    success, llm_result = llm_analyzer.analyze_stock(stock_data_llm)

                    if success:
                        logger.info("✓ LLM analysis successful")
                        _print_llm_results(llm_result)
                        filter_result['llm_analysis'] = llm_result
                    else:
                        logger.warning(f"✗ LLM analysis failed: {llm_result}")
                else:
                    logger.info("⏭️ LLM not configured")
            except Exception as e:
                logger.warning(f"LLM analysis error: {e}")

        # Generate report
        logger.info("\nGenerating report...")
        try:
            report_generator = OpportunityReportGenerator(output_dir=output_dir)
            report_path = report_generator.generate_report(
                analysis_results=[filter_result],
                report_title=f"Single Stock Analysis - {stock_code}"
            )
            logger.info(f"✓ Report generated: {report_path}")
        except Exception as e:
            logger.warning(f"Report generation failed: {e}")
            report_path = None

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Analysis Summary")
        logger.info("=" * 60)
        logger.info(f"Stock Code: {stock_code}")
        logger.info(f"Stock Name: {stock_info.get('name', 'Unknown')}")
        logger.info(f"Total Score: {scoring_result.get('total_score', 0):.2f}")
        logger.info(f"Rating: {scoring_result.get('rating', 'C')}")
        logger.info(f"Recommendation: {scoring_result.get('recommendation', 'N/A')}")
        logger.info(f"Filter Passed: {filter_result.get('passed', False)}")
        logger.info("=" * 60)

        return {
            'stock_code': stock_code,
            'stock_info': stock_info,
            'scoring_result': scoring_result,
            'filter_result': filter_result,
            'report_path': report_path
        }

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def _print_scoring_results(stock_code: str, stock_info: Dict, result: Dict):
    """Print scoring results"""
    logger.info("\n" + "-" * 60)
    logger.info(f"Scoring Results - {stock_code}")
    logger.info("-" * 60)

    scores = result.get('scores', {})
    total_score = result.get('total_score', 0)
    rating = result.get('rating', 'C')

    logger.info(f"Total Score: {total_score:.2f} (Rating: {rating})")
    logger.info(f"\nDimension Scores:")
    logger.info(f"  Technical:     {scores.get('technical', 0):.1f}")
    logger.info(f"  Quantitative:   {scores.get('quantitative', 0):.1f}")
    logger.info(f"  Fundamental:    {scores.get('fundamental', 0):.1f}")
    logger.info(f"  Sentiment:     {scores.get('sentiment', 0):.1f}")
    logger.info(f"  Sector:        {scores.get('sector', 0):.1f}")
    logger.info(f"  Events:        {scores.get('events', 0):.1f}")
    logger.info(f"  Dragon Tiger:  {scores.get('dragon_tiger', 0):.1f}")


def _print_filter_results(filter_result: Dict):
    """Print filter results"""
    logger.info("\n" + "-" * 60)
    logger.info("Filter Results")
    logger.info("-" * 60)

    passed = filter_result.get('passed', False)
    status = "PASSED" if passed else "FAILED"
    logger.info(f"Status: {status}")

    filter_details = filter_result.get('filter_details', {})
    if filter_details:
        logger.info(f"\nFilter Breakdown:")
        for filter_name, filter_status in filter_details.items():
            icon = "✓" if filter_status.get('passed', False) else "✗"
            logger.info(f"  {icon} {filter_name}: {filter_status.get('reason', '')}")

    selection_reason = filter_result.get('selection_reason', '')
    if selection_reason:
        logger.info(f"\nSelection Reason: {selection_reason}")


def _print_llm_results(llm_result: Dict):
    """Print LLM analysis results"""
    logger.info("\n" + "-" * 60)
    logger.info("LLM Analysis Results")
    logger.info("-" * 60)

    operation = llm_result.get('operation_advice', {})
    if operation:
        logger.info(f"Action: {operation.get('action', 'N/A')}")
        logger.info(f"Position: {operation.get('position_control', 'N/A')}")
        logger.info(f"Target Price: {operation.get('target_price', 'N/A')}")
        logger.info(f"Stop Loss: {operation.get('stop_loss', 'N/A')}")
        confidence = operation.get('confidence', 0)
        logger.info(f"Confidence: {confidence * 100:.0f}%")

    risk = llm_result.get('risk_assessment', {})
    if risk:
        logger.info(f"\nRisk Level: {risk.get('risk_level', 'N/A')}")
        logger.info(f"Risk Score: {risk.get('overall_score', 0)}")

    summary = llm_result.get('summary', '')
    if summary:
        logger.info(f"\nSummary: {summary[:200]}{'...' if len(summary) > 200 else ''}")


def _prepare_llm_data(stock_code: str, stock_name: str, scoring_result: Dict) -> Dict:
    """Prepare LLM analysis data"""
    details = scoring_result.get('details', {})

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
    parser = argparse.ArgumentParser(description='Single Stock Analysis')
    parser.add_argument('--code', type=str, required=True,
                       help='Stock code (e.g., 600977)')
    parser.add_argument('--no-llm', action='store_true',
                       help='Disable LLM analysis')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='Output directory')

    args = parser.parse_args()

    result = analyze_stock(
        stock_code=args.code,
        enable_llm=not args.no_llm,
        output_dir=args.output_dir
    )

    if result:
        logger.info(f"\nAnalysis complete for {args.code}")
    else:
        logger.error(f"Analysis failed for {args.code}")
        sys.exit(1)


if __name__ == "__main__":
    main()
