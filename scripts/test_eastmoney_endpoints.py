import requests
import time

def test_endpoints():
    base_url = "eastmoney.com"
    subdomains = [
        "push2",
        "push2his",
        "quote",
        "6.push2",
        "1.push2",
        "99.push2",
        "4.push2",
        "17.push2",
        "push2.eastmoney.com" # Just in case
    ]
    
    params = {
        'pn': '1',
        'pz': '20',
        'po': '1',
        'np': '1',
        'fltt': '2',
        'invt': '2',
        'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:80',
        'fields': 'f12,f14'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for sub in subdomains:
        if "eastmoney.com" in sub:
            host = sub
        else:
            host = f"{sub}.{base_url}"
            
        url = f"http://{host}/api/qt/clist/get"
        print(f"Testing {url} ...")
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=3)
            print(f"Status: {resp.status_code}")
            if resp.status_code == 200:
                print("Success!")
                print(resp.text[:100])
                return host
        except Exception as e:
            print(f"Failed: {e}")
            
    return None

if __name__ == "__main__":
    test_endpoints()
