
import sys
import os
import logging
import json

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.fundamental_data_collector import FundamentalDataCollector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_fundamental_collector():
    stock_code = "600519" # 贵州茅台
    logger.info(f"Testing FundamentalDataCollector for {stock_code}...")
    
    collector = FundamentalDataCollector(stock_code)
    
    # Test financial indicators
    logger.info("Fetching financial indicators...")
    indicators = collector.get_financial_indicators()
    logger.info(f"Indicators: {json.dumps(indicators, indent=2, ensure_ascii=False)}")
    
    if indicators.get('pe_ratio') == 'N/A':
        logger.warning("PE Ratio is N/A")
    else:
        logger.info(f"PE Ratio: {indicators.get('pe_ratio')}")

    # Test financial reports
    logger.info("Fetching financial reports...")
    reports = collector.get_financial_reports()
    logger.info(f"Reports: {json.dumps(reports, indent=2, ensure_ascii=False)}")

if __name__ == "__main__":
    test_fundamental_collector()
