import http.server
import socketserver
import json
import time
import threading
import random
import math
import os
import urllib.request

# --- Configuration ---
PORT = 8000
ROOT_DIR = "./results"

# --- Real Stock Mapping (A-Share Codes) ---
# AI: 科大讯飞, 寒武纪, 三六零, 浪潮信息, 中科曙光, 工业富联, 金山办公, 昆仑万维
# Robot: 汇川技术, 埃斯顿, 鸣志电器, 绿的谐波, 三花智控, 拓普集团
# Quantum: 国盾量子, 神州信息, 科大国创, 浙江东方
# Fusion: 安泰科技, 永鼎股份, 西部超导, 联创光电
# Space: 中国卫星, 航天电子, 中国卫通, 中科星图
REAL_CODES_MAP = {
    'ai': ['sz002230', 'sh688256', 'sh601360', 'sz000977', 'sh603019', 'sh601138', 'sh688111', 'sz300418'],
    'robot': ['sz300124', 'sz002747', 'sh603728', 'sh688017', 'sz002050', 'sh601689'],
    'quantum': ['sh688027', 'sz000555', 'sz300520', 'sh600120'],
    'fusion': ['sz000969', 'sh600105', 'sh688122', 'sh600363'],
    'space': ['sh600118', 'sh600879', 'sh601698', 'sh688568']
}

SECTORS = [
    { "id": 0, "key": 'ai', "name": '通用人工智能', "color": '#ff0055', "angle": 0, "count": 800, "hot": True },
    { "id": 1, "key": 'robot', "name": '人形机器人', "color": '#00ff88', "angle": 1.2, "count": 600, "hot": True },
    { "id": 2, "key": 'quantum', "name": '量子计算', "color": '#00ccff', "angle": 2.4, "count": 500, "hot": False },
    { "id": 3, "key": 'fusion', "name": '可控核聚变', "color": '#ffff00', "angle": 3.6, "count": 400, "hot": True },
    { "id": 4, "key": 'space', "name": '深空探测', "color": '#ff8800', "angle": 4.8, "count": 450, "hot": False },
]

# Flatten codes for API fetching
ALL_REAL_CODES = []
for k, v in REAL_CODES_MAP.items():
    ALL_REAL_CODES.extend(v)

# --- Global State ---
market_state = {
    "stocks": [],
    "index": 3824.56,
    "index_change": 2.15,
    "trades": [], 
    "last_update": time.time(),
    "real_data_cache": {} # code -> {price, change, name}
}

# --- Initialization ---
def init_market():
    global_index = 0
    for sector in SECTORS:
        real_codes = REAL_CODES_MAP.get(sector["key"], [])
        
        for i in range(sector["count"]):
            # Position (Spiral Galaxy Logic)
            arm_offset = sector["angle"]
            distance = random.random() * 40 + 10
            angle = distance * 0.1 + arm_offset
            x = math.cos(angle) * distance + (random.random() - 0.5) * 5
            y = (random.random() - 0.5) * (distance * 0.2)
            z = math.sin(angle) * distance + (random.random() - 0.5) * 5

            # Determine if this is a "Real" monitored stock or a "Background" particle
            is_real_monitored = i < len(real_codes)
            
            stock_code = "UNKNOWN"
            stock_name = "未知股票"
            
            if is_real_monitored:
                # Map to a real stock code
                full_code = real_codes[i] # e.g. sz002230
                stock_code = full_code[2:] # 002230
                stock_name = "加载中..." 
            else:
                # Background particle
                stock_code = ('60' if random.random() > 0.5 else '00') + str(random.randint(0, 9999)).zfill(4)
                stock_name = sector["name"] + "概念股"

            stock = {
                "index": global_index,
                "id": f"{sector['key']}-{i}",
                "sectorId": sector["id"],
                "real_api_code": real_codes[i] if is_real_monitored else None,
                "name": stock_name,
                "code": stock_code,
                "price": 0.0,
                "change": 0.0,
                "volume": 0,
                "isLimitUp": False,
                "position": [x, y, z],
                "tags": [sector["name"]]
            }
            market_state["stocks"].append(stock)
            global_index += 1
            
    print(f"Market initialized with {len(market_state['stocks'])} stocks.")

# --- Real Data Fetcher ---
def fetch_real_market_data():
    try:
        # Fetch in batches of 50 (we have around 30, so one batch is fine)
        url = f"http://qt.gtimg.cn/q={','.join(ALL_REAL_CODES)}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as f:
            content = f.read().decode('gbk')
            
        # Parse content
        # Format: v_sh600519="1~贵州茅台~600519~1430.01~1423.98~1423.98~..."
        lines = content.strip().split(';')
        
        total_change = 0
        count = 0
        
        for line in lines:
            if '="' in line:
                parts = line.split('="')
                if len(parts) < 2: continue
                
                api_code = parts[0].strip().replace('v_', '')
                data_str = parts[1].strip('"')
                fields = data_str.split('~')
                
                if len(fields) > 30:
                    name = fields[1]
                    current_price = float(fields[3])
                    prev_close = float(fields[4])
                    
                    change_pct = 0.0
                    if prev_close > 0:
                        change_pct = (current_price - prev_close) / prev_close * 100
                    
                    volume = float(fields[6]) # Hand/Lot
                    
                    market_state["real_data_cache"][api_code] = {
                        "name": name,
                        "price": current_price,
                        "change": change_pct,
                        "volume": volume
                    }
                    
                    total_change += change_pct
                    count += 1
                    
        # Update Index based on average of monitored stocks (Simple approximation)
        if count > 0:
            avg_change = total_change / count
            # Simulate Index: Base 3800 + influence
            market_state["index_change"] = avg_change
            market_state["index"] = 3800 * (1 + avg_change / 100)
            
    except Exception as e:
        print(f"Error fetching real data: {e}")

# --- Simulation Loop ---
def monitor_loop():
    while True:
        # 1. Fetch Real Data
        fetch_real_market_data()
        
        # 2. Update Stocks
        for stock in market_state["stocks"]:
            if stock["real_api_code"]:
                # Update Real Stocks
                data = market_state["real_data_cache"].get(stock["real_api_code"])
                if data:
                    stock["name"] = data["name"]
                    stock["price"] = data["price"]
                    stock["change"] = data["change"]
                    stock["volume"] = data["volume"]
                    stock["isLimitUp"] = data["change"] > 9.5
                    
                    # Update tags based on real change
                    stock["tags"] = [SECTORS[stock["sectorId"]]["name"]]
                    if data["change"] > 5: stock["tags"].append("资金流入")
            else:
                # Update Background Particles
                # They follow their sector's "Real" leader trend + random noise
                # Find a real leader in this sector
                sector_key = SECTORS[stock["sectorId"]]["key"]
                leaders = REAL_CODES_MAP.get(sector_key, [])
                
                base_change = 0
                if leaders:
                    leader_code = leaders[0] # Use first one as proxy
                    leader_data = market_state["real_data_cache"].get(leader_code)
                    if leader_data:
                        base_change = leader_data["change"]
                
                # Add noise
                noise = (random.random() - 0.5) * 2
                stock["change"] = base_change + noise
                stock["price"] = max(2.0, stock["price"] * (1 + stock["change"]/1000)) # Slow drift
                
        # 3. Generate "Real" Trades (Simulated based on Real Volatility)
        # We detect if any REAL stock has >3% change, we trigger a meteor
        current_time = time.time()
        if len(market_state["trades"]) < 15:
            for stock in market_state["stocks"]:
                if stock["real_api_code"] and abs(stock["change"]) > 2.0:
                    # 10% chance to trigger meteor for volatile stock
                    if random.random() < 0.1:
                        amount = round(random.random() * 10 + 1, 1)
                        trade = {
                            "targetId": stock["id"],
                            "targetName": stock["name"],
                            "targetPos": stock["position"],
                            "amount": amount,
                            "timestamp": current_time
                        }
                        # Dedup
                        if not any(t["targetId"] == stock["id"] for t in market_state["trades"]):
                            market_state["trades"].append(trade)

        # Cleanup trades
        market_state["trades"] = [t for t in market_state["trades"] if current_time - t["timestamp"] < 5]

        time.sleep(2.0) # Poll every 2s

# --- HTTP Handler ---
class MarketRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/snapshot':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            data = {
                "stocks": market_state["stocks"],
                "index": round(market_state["index"], 2),
                "index_change": round(market_state["index_change"], 2)
            }
            self.wfile.write(json.dumps(data).encode())
            
        elif self.path == '/api/trades':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(market_state["trades"]).encode())
            
        else:
            if self.path == '/' or self.path == '/index.html':
                self.path = '/高能粒子.html'
            original_path = self.path
            self.directory = os.path.abspath(ROOT_DIR)
            super().do_GET()

# --- Main ---
if __name__ == "__main__":
    init_market()
    
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    
    print(f"Starting Real-Time Market Server on port {PORT}...")
    with socketserver.TCPServer(("", PORT), MarketRequestHandler) as httpd:
        httpd.serve_forever()
