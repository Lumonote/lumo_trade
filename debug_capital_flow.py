import requests
import json

def check_capital_flow(stock_code):
    # Simulate the logic in analysis/investor_sentiment.py
    url = "http://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        'lmt': '0',
        'klt': '101',
        'secid': f"{'1' if stock_code.startswith('6') else '0'}.{stock_code}",
        'fields1': 'f1,f2,f3,f7',
        'fields2': 'f51,f52,f53,f54,f55,f56'
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    print(f"Checking Capital Flow for {stock_code}...")
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()
        
        if data.get('data') and data['data'].get('klines'):
            latest_data = data['data']['klines'][-1].split(',')
            print(f"Raw Data: {latest_data}")
            
            main_inflow = float(latest_data[1]) if len(latest_data) > 1 else 0
            small_inflow = float(latest_data[2]) if len(latest_data) > 2 else 0
            medium_inflow = float(latest_data[3]) if len(latest_data) > 3 else 0
            super_large_inflow = float(latest_data[4]) if len(latest_data) > 4 else 0
            large_inflow = float(latest_data[5]) if len(latest_data) > 5 else 0
            
            retail_inflow = small_inflow + medium_inflow
            main_inflow_rate = 0.0
            
            print(f"Date: {latest_data[0]}")
            print(f"Main Inflow: {main_inflow}")
            print(f"Super Large: {super_large_inflow}")
            print(f"Large: {large_inflow}")
            print(f"Medium: {medium_inflow}")
            print(f"Small: {small_inflow}")
            print(f"Retail Inflow (Calc): {retail_inflow}")
            
            # Check strength classification
            def classify_strength(rate, amount):
                if rate and abs(rate) > 0.1:
                     if abs(rate) > 10: return '强'
                     elif abs(rate) > 5: return '中'
                     else: return '弱'
                if amount is not None:
                    amount_abs = abs(amount)
                    if amount_abs > 100_000_000: return '强'
                    elif amount_abs > 30_000_000: return '中'
                    else: return '弱'
                return '弱'

            strength = classify_strength(main_inflow_rate, main_inflow)
            print(f"Strength: {strength}")
            
        else:
            print("No data found")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_capital_flow("300102") # 乾照光电 from the report
    check_capital_flow("000678") # 襄阳轴承
