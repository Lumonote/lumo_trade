import sys
import os
sys.path.insert(0, os.getcwd())
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.investor_sentiment import InvestorSentimentAnalyzer

def test_pe(code):
    print(f"Testing PE for {code}...")
    collector = FundamentalDataCollector(code)
    data = collector.get_financial_indicators()
    print(f"Result for {code}: PE={data.get('pe_ratio')}")

def test_sentiment(stock_code):
    print(f"Testing Sentiment for {stock_code}...")
    try:
        analyzer = InvestorSentimentAnalyzer(stock_code)
        
        # Test Market Sentiment
        sentiment = analyzer.get_market_sentiment()
        print(f"Result for {stock_code}: Turnover={sentiment.get('turnover_rate')}")
        
        # Test Capital Flow
        print(f"Testing Capital Flow for {stock_code}...")
        capital = analyzer.get_capital_flow()
        print(f"Result for {stock_code}: Main Inflow={capital.get('main_inflow')}")
        
        # Test Dragon Tiger
        print(f"Testing Dragon Tiger for {stock_code}...")
        dt = analyzer.get_dragon_tiger_list()
        print(f"Result for {stock_code}: Has Records={dt.get('has_records')}")
        
    except Exception as e:
        print(f"Error getting sentiment for {stock_code}: {e}")

if __name__ == "__main__":
    test_pe("300102")
    test_sentiment("300102")
    test_pe("000678")
