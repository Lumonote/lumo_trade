
import sys
import os
import pandas as pd
import logging

# Setup path
sys.path.insert(0, os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from analysis.advanced_analysis import AdvancedAnalyzer
    print("Successfully imported AdvancedAnalyzer")
except ImportError as e:
    print(f"Failed to import AdvancedAnalyzer: {e}")
    sys.exit(1)

def test_analysis():
    analyzer = AdvancedAnalyzer()
    
    # Mock data
    stock_code = "000001"
    
    # Create dummy historical data
    dates = pd.date_range(end=pd.Timestamp.now(), periods=100)
    data = {
        'open': [10] * 100,
        'high': [11] * 100,
        'low': [9] * 100,
        'close': [10.5] * 100,
        'volume': [100000] * 100,
        'turnover': [1.0] * 100
    }
    df = pd.DataFrame(data, index=dates)
    
    print("Running full_analysis...")
    try:
        result = analyzer.full_analysis(
            stock_code=stock_code,
            historical_data=df,
            intraday_data=None,
            fundamental_data={'pe_ratio': 10},
            market_data=None
        )
        
        print("\nAnalysis Result:")
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        
        overall = result.get('overall_score', {})
        print(f"\nOverall Score: {overall.get('final_score')}")
        
    except Exception as e:
        print(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_analysis()
