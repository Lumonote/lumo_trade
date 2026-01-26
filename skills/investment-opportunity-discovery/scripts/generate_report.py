#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Report Generation Script
Generate HTML and Markdown reports from analysis results
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

from scripts.opportunity_report_generator import OpportunityReportGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def generate_report(input_file: str, output_dir: str = 'reports',
                    title: str = 'Investment Analysis Report',
                    format_type: str = 'html') -> str:
    """
    Generate report from analysis results

    Args:
        input_file: Input JSON file with analysis results
        output_dir: Output directory for reports
        title: Report title
        format_type: Output format (html, markdown, both)

    Returns:
        Path to generated report
    """
    logger.info(f"Generating report from: {input_file}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Format: {format_type}")
    logger.info("=" * 60)

    try:
        # Load analysis results
        if not os.path.exists(input_file):
            logger.error(f"Input file not found: {input_file}")
            return ""

        logger.info("Loading analysis results...")
        with open(input_file, 'r', encoding='utf-8') as f:
            results_data = json.load(f)

        if not results_data:
            logger.error("No analysis results found")
            return ""

        # Determine results format
        if isinstance(results_data, dict) and 'analysis_results' in results_data:
            # New format with metadata
            analysis_results = results_data['analysis_results']
            global_hot_news = results_data.get('global_hot_news', [])
        elif isinstance(results_data, list):
            # Direct list format
            analysis_results = results_data
            global_hot_news = []
        else:
            logger.error("Invalid results format")
            return ""

        # Initialize report generator
        report_generator = OpportunityReportGenerator(output_dir=output_dir)

        # Generate report
        logger.info("Generating report...")
        report_path = report_generator.generate_report(
            analysis_results=analysis_results,
            report_title=title,
            global_hot_news=global_hot_news
        )

        if report_path:
            logger.info(f"\n✓ Report generated successfully: {report_path}")
            return report_path
        else:
            logger.error("✗ Report generation failed")
            return ""

    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        import traceback
        traceback.print_exc()
        return ""


def print_report_summary(report_path: str):
    """Print report summary"""
    if not report_path or not os.path.exists(report_path):
        return

    logger.info("\n" + "=" * 60)
    logger.info("Report Summary")
    logger.info("=" * 60)
    logger.info(f"Report Path: {report_path}")
    logger.info(f"File Size: {os.path.getsize(report_path)} bytes")

    # Try to read and extract summary
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Extract key metrics from HTML
        if 'Top 10' in content or 'TOP 10' in content:
            logger.info("Contains: Top 10 Highlights")

        if 'LLM' in content or 'AI' in content:
            logger.info("Contains: LLM Analysis")

        if '<table' in content:
            logger.info("Contains: Data Tables")

        if 'chart' in content.lower() or 'plot' in content.lower():
            logger.info("Contains: Charts")

    except Exception as e:
        logger.debug(f"Could not read report summary: {e}")

    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Generate Investment Reports')
    parser.add_argument('--input', type=str, required=True,
                       help='Input JSON file with analysis results')
    parser.add_argument('--output-dir', type=str, default='reports',
                       help='Output directory for reports')
    parser.add_argument('--title', type=str,
                       default='Investment Analysis Report',
                       help='Report title')
    parser.add_argument('--format', type=str,
                       choices=['html', 'markdown', 'both'],
                       default='html',
                       help='Output format')
    parser.add_argument('--summary', action='store_true',
                       help='Print report summary after generation')

    args = parser.parse_args()

    # Generate report
    report_path = generate_report(
        input_file=args.input,
        output_dir=args.output_dir,
        title=args.title,
        format_type=args.format
    )

    if report_path:
        if args.summary:
            print_report_summary(report_path)
        logger.info("\n✓ Report generation complete")
    else:
        logger.error("\n✗ Report generation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
