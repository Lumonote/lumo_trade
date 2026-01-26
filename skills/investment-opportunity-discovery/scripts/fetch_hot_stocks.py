#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hot Stocks Fetcher Script
Fetch popular stocks from multiple data sources
"""

import os
import sys
import argparse
import logging
import json
from typing import List, Dict, Optional

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from scripts.hot_stocks_fetcher import HotStocksFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def fetch_hot_stocks(limit: int = 100, force_refresh: bool = True,
                     output_file: Optional[str] = None,
                     source: Optional[str] = None) -> List[Dict]:
    """
    Fetch hot stocks from data sources

    Args:
        limit: Number of stocks to fetch
        force_refresh: Force refresh data (ignore cache)
        output_file: Optional output file path
        source: Data source (auto, eastmoney, tonghuashun, xueqiu)

    Returns:
        List of hot stock dictionaries
    """
    logger.info(f"Fetching hot stocks (limit: {limit}, source: {source or 'auto'})")
    logger.info("=" * 60)

    try:
        # Initialize fetcher
        fetcher = HotStocksFetcher(disable_cache=not force_refresh)

        # Fetch stocks
        logger.info("Fetching hot stocks from data sources...")
        hot_stocks = fetcher.get_hot_stocks(limit=limit, force_refresh=force_refresh)

        if not hot_stocks:
            logger.error("No hot stocks fetched")
            return []

        # Display summary
        logger.info(f"\n✓ Successfully fetched {len(hot_stocks)} hot stocks")

        # Show data source info
        source_stats = {}
        for stock in hot_stocks:
            src = stock.get('source', 'unknown')
            source_stats[src] = source_stats.get(src, 0) + 1

        logger.info("\nData Source Breakdown:")
        for src, count in source_stats.items():
            logger.info(f"  {src}: {count} stocks")

        # Display top 10
        logger.info(f"\nTop 10 Hot Stocks:")
        logger.info("-" * 60)
        for i, stock in enumerate(hot_stocks[:10], start=1):
            code = stock.get('code', 'N/A')
            name = stock.get('name', 'N/A')
            price = stock.get('price', 0)
            change = stock.get('change_pct', 0)
            logger.info(f"{i:2}. {code} {name:<15} Price: {price:>8.2f} Change: {change:>6.2f}%")

        # Save to file if requested
        if output_file:
            try:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(hot_stocks, f, ensure_ascii=False, indent=2)
                logger.info(f"\n✓ Data saved to: {output_file}")
            except Exception as e:
                logger.error(f"Failed to save file: {e}")

        return hot_stocks

    except Exception as e:
        logger.error(f"Failed to fetch hot stocks: {e}")
        import traceback
        traceback.print_exc()
        return []


def list_data_sources():
    """List available data sources"""
    logger.info("\nAvailable Data Sources:")
    logger.info("-" * 60)
    logger.info("1. auto        - Automatic selection (recommended)")
    logger.info("2. eastmoney   - Eastmoney crawler")
    logger.info("3. tonghuashun - Tonghuashun crawler")
    logger.info("4. xueqiu      - Xueqiu crawler")
    logger.info("\nNote: 'auto' mode will try sources in order until one succeeds")


def main():
    parser = argparse.ArgumentParser(description='Fetch Hot Stocks')
    parser.add_argument('--limit', type=int, default=100,
                       help='Number of stocks to fetch (default: 100)')
    parser.add_argument('--source', type=str,
                       choices=['auto', 'eastmoney', 'tonghuashun', 'xueqiu'],
                       help='Data source (default: auto)')
    parser.add_argument('--no-cache', action='store_true',
                       help='Disable cache (force fresh data)')
    parser.add_argument('--output', type=str,
                       help='Output JSON file path')
    parser.add_argument('--list-sources', action='store_true',
                       help='List available data sources')

    args = parser.parse_args()

    if args.list_sources:
        list_data_sources()
        return

    # Fetch stocks
    hot_stocks = fetch_hot_stocks(
        limit=args.limit,
        force_refresh=not args.no_cache,
        output_file=args.output,
        source=args.source
    )

    if hot_stocks:
        logger.info(f"\n✓ Successfully fetched {len(hot_stocks)} hot stocks")
    else:
        logger.error("✗ Failed to fetch hot stocks")
        sys.exit(1)


if __name__ == "__main__":
    main()
