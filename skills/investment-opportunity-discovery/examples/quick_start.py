#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Start Example
Demonstrates how to use the Investment Opportunity Discovery skill
"""

import sys
import os

# Add Kronos root to path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)

from skills.investment_opportunity_discovery.scripts.discover_opportunities import OpportunityDiscovery


def example_1_full_discovery():
    """Example 1: Run full opportunity discovery"""
    print("=" * 60)
    print("Example 1: Full Discovery")
    print("=" * 60)

    # Initialize discovery system
    discovery = OpportunityDiscovery(max_workers=5)

    # Run discovery with test codes
    test_codes = ['600977', '000001', '000002']
    report_path = discovery.run(
        limit=50,
        test_codes=test_codes,
        output_dir='examples/results/',
        enable_llm=False  # Disable for faster demo
    )

    print(f"\n✓ Discovery complete!")
    print(f"  Report path: {report_path}")


def example_2_single_stock():
    """Example 2: Analyze single stock"""
    print("\n" + "=" * 60)
    print("Example 2: Single Stock Analysis")
    print("=" * 60)

    # Import single stock analyzer
    from skills.investment_opportunity_discovery.scripts.analyze_single_stock import analyze_stock

    # Analyze single stock
    stock_code = '600977'
    result = analyze_stock(
        stock_code=stock_code,
        enable_llm=False,  # Disable for demo
        output_dir='examples/results/'
    )

    if result:
        print(f"\n✓ Analysis complete for {stock_code}")
        print(f"  Total score: {result['scoring_result']['total_score']:.2f}")
        print(f"  Rating: {result['scoring_result']['rating']}")
        print(f"  Report: {result['report_path']}")
    else:
        print(f"\n✗ Analysis failed for {stock_code}")


def example_3_fetch_stocks():
    """Example 3: Fetch hot stocks"""
    print("\n" + "=" * 60)
    print("Example 3: Fetch Hot Stocks")
    print("=" * 60)

    # Import fetcher
    from skills.investment_opportunity_discovery.scripts.fetch_hot_stocks import fetch_hot_stocks

    # Fetch hot stocks
    hot_stocks = fetch_hot_stocks(
        limit=20,
        force_refresh=True,
        output_file='examples/results/hot_stocks.json'
    )

    if hot_stocks:
        print(f"\n✓ Fetched {len(hot_stocks)} hot stocks")
        print(f"  Saved to: examples/results/hot_stocks.json")

        # Display top 5
        print("\nTop 5 hot stocks:")
        for i, stock in enumerate(hot_stocks[:5], start=1):
            print(f"  {i}. {stock['code']} {stock['name']}")
    else:
        print("\n✗ Failed to fetch hot stocks")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Investment Opportunity Discovery - Quick Start Examples")
    print("=" * 60)

    # Create output directory
    os.makedirs('examples/results/', exist_ok=True)

    # Run examples
    try:
        # Example 1: Full discovery
        example_1_full_discovery()

        # Example 2: Single stock
        example_2_single_stock()

        # Example 3: Fetch stocks
        example_3_fetch_stocks()

        print("\n" + "=" * 60)
        print("All examples completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Example failed: {e}")
        import traceback
        traceback.print_exc()
