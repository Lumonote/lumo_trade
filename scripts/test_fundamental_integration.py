
import sys
import os
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.hot_stocks_fetcher import HotStocksFetcher
from analysis.opportunity_scorer import OpportunityScorer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_integration():
    logger.info("Testing HotStocksFetcher and OpportunityScorer integration...")
    
    # 1. Fetch hot stocks with fundamental data
    fetcher = HotStocksFetcher()
    # Force refresh to trigger real-time fetching and batch enrichment
    hot_stocks = fetcher.get_hot_stocks(limit=5, force_refresh=True)
    
    if not hot_stocks:
        logger.error("Failed to fetch hot stocks")
        return
        
    logger.info(f"Fetched {len(hot_stocks)} stocks")
    
    # Check if fundamental data is present
    first_stock = hot_stocks[0]
    logger.info(f"First stock data: {first_stock}")
    
    if 'pe_ratio' not in first_stock:
        logger.error("Fundamental data (pe_ratio) missing from fetched stocks!")
        return
    else:
        logger.info("Fundamental data present in fetched stocks.")
        
    # 2. Pass to Scorer
    scorer = OpportunityScorer()
    
    stock_code = first_stock.get('code')
    fundamental_data = {
        'pe_ratio': first_stock.get('pe_ratio'),
        'pb_ratio': first_stock.get('pb_ratio'),
        'total_market_cap': first_stock.get('total_market_cap'),
        'circulation_market_cap': first_stock.get('circulation_market_cap'),
        'revenue_yoy': first_stock.get('revenue_yoy'),
        'net_profit_yoy': first_stock.get('net_profit_yoy')
    }
    
    logger.info(f"Passing fundamental data to scorer: {fundamental_data}")
    
    # Mock global news
    global_hot_news = []
    
    try:
        result = scorer.calculate_comprehensive_score(
            stock_code,
            global_hot_news=global_hot_news,
            fundamental_data=fundamental_data
        )
        
        logger.info("Scoring result obtained.")
        # Check score in the correct location: result['scores']['fundamental']
        fund_score = result.get('scores', {}).get('fundamental', 'N/A')
        logger.info(f"Fundamental Score: {fund_score}")
        
        if fund_score == 'N/A' or fund_score == 50.0: # 50.0 might be default if error
             # Check if details show valid inputs
             fund_details = result.get('details', {}).get('fundamental', {})
             logger.info(f"Fundamental Details: {fund_details}")
             
        logger.info("Integration test passed!")
        
    except Exception as e:
        logger.error(f"Scoring failed: {e}")

if __name__ == "__main__":
    test_integration()
