import requests
import json

def check_pe(code):
    market_code = 'sz' + code if code.startswith(('0', '3')) else 'sh' + code
    url = f"https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        'secid': f"{'1' if market_code.startswith('sh') else '0'}.{code}",
        'fields': 'f57,f58,f162,f167,f173,f116,f117,f189,f135,f136'
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }

    print(f"Requesting data for {code}...")
    response = requests.get(url, params=params, headers=headers, timeout=10)
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        return

    try:
        data = response.json()
        if data.get('data'):
            stock_data = data['data']
            f162 = stock_data.get('f162')
            print(f"f162 (PE raw): {f162}, Type: {type(f162)}")
            
            pe_raw = f162
            if isinstance(pe_raw, (int, float)) and pe_raw > 0:
                print("Condition 1: > 0 number")
            elif isinstance(pe_raw, (int, float)) and pe_raw < 0:
                print("Condition 2: < 0 number")
            else:
                print("Condition 3: N/A")
        else:
            print("No data found")
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    check_pe("300102")
    check_pe("000678")
