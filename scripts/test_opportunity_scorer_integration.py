
import sys
import os
import pandas as pd
import logging
from datetime import datetime

sys.path.insert(0, os.getcwd())
logging.basicConfig(level=logging.INFO)

try:
    from analysis.opportunity_scorer import OpportunityScorer
except ImportError:
    # If run from scripts/ dir
    sys.path.insert(0, os.path.dirname(os.getcwd()))
    from analysis.opportunity_scorer import OpportunityScorer

def test_scorer():
    scorer = OpportunityScorer()
    
    # Mock data
    stock_code = "000001"
    dates = pd.date_range(end=datetime.now(), periods=100)
    data = {
        'open': [10.0] * 100,
        'high': [11.0] * 100,
        'low': [9.0] * 100,
        'close': [10.5] * 100,
        'volume': [100000.0] * 100,
        'amount': [1000000.0] * 100,
        'turnover': [1.0] * 100,
        'pct_chg': [0.1] * 100
    }
    df = pd.DataFrame(data, index=dates)
    
    market_data = {
        'sector_info': {'name': 'Bank', 'sentiment': {'score': 60}},
        'market_sentiment': {'score': 50}
    }
    
    print("Running calculate_comprehensive_score...")
    try:
        result = scorer.calculate_comprehensive_score(
            stock_code=stock_code,
            historical_data=df,
            market_data=market_data
        )
        
        print("\nScoring Result:")
        # Check if advanced_analysis is present and has non-zero score
        adv = result.get('advanced_analysis', {})
        print(f"Advanced Analysis Present: {bool(adv)}")
        if adv:
            score = adv.get('overall_score', {}).get('final_score', 0)
            print(f"Advanced Score: {score}")
            
            # Check if market data was used (e.g. sector score)
            dims = adv.get('dimensions', {})
            sector_res = dims.get('sector', {})
            print(f"Sector Analysis: {sector_res}")
            
            if score > 0:
                print("SUCCESS: Advanced score is non-zero.")
            else:
                print("WARNING: Advanced score is 0.0 (might be due to mock data limitations)")
        else:
            print("FAILURE: Advanced analysis missing from result.")
            
    except Exception as e:
        print(f"Scoring failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_scorer()
