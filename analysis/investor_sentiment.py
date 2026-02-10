#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股民情绪分析模块
分析股吧评论、社交媒体讨论等股民情绪指标
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import json
import time
import random
from pathlib import Path
import sys
import re
import unicodedata

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.dynamic_crawler import DynamicCrawler
from analysis.sector_api import (
    get_stock_sector_info,
    get_sector_sentiment,
    get_stock_sector_info_multi_source,  # 多数据源版本
    get_sector_sentiment_multi_source    # 多数据源版本
)
from analysis.sentiment_cache_manager import get_sentiment_cache
import threading

# 【优化】全局请求锁字典，避免并发重复查询同一股票
_request_locks = {}
_locks_lock = threading.Lock()


class InvestorSentimentAnalyzer:
    """股民情绪分析器"""

    def __init__(self, stock_code):
        """
        初始化股民情绪分析器

        Args:
            stock_code: 股票代码 (例如: '688343', '000001')
        """
        self.stock_code = stock_code
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Referer': 'http://quote.eastmoney.com/',
            'Origin': 'http://quote.eastmoney.com',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }

        # 使用全局缓存管理器
        self.global_cache = get_sentiment_cache()

        # 轻量缓存目录（用于网络不稳定时的短期回退）
        try:
            self.cache_dir = project_root / 'cache'
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # 缓存目录创建失败不影响主流程
            self.cache_dir = project_root

    # === 缓存与备用源工具方法 ===
    def _get_data_via_curl(self, url, params):
        """使用curl命令行工具获取数据（作为requests的fallback）"""
        import subprocess
        import time
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 构建完整的URL参数
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                full_url = f"{url}?{query_string}"
                
                cmd = ['curl', '-s', full_url, '-H', 'User-Agent: curl/8.6.0']
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    try:
                        return json.loads(result.stdout)
                    except json.JSONDecodeError:
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                        return None
                else:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    print(f"   ⚠️  Curl请求失败: {result.stderr}")
                    return None
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                print(f"   ⚠️  Curl执行出错: {e}")
                return None
        return None

    def _cache_path(self, key: str) -> Path:
        try:
            return (self.cache_dir / f"{key}.json")
        except Exception:
            return (project_root / f"{key}.json")

    def _read_cache(self, key: str, max_age_sec: int = 600):
        try:
            p = self._cache_path(key)
            if not p.exists():
                return None
            mtime = p.stat().st_mtime
            if (time.time() - mtime) > max_age_sec:
                return None
            with p.open('r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    def _write_cache(self, key: str, data):
        try:
            p = self._cache_path(key)
            with p.open('w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            # 写缓存失败不影响主流程
            pass

    def _to_float(self, v):
        try:
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if s in ('', 'N/A', 'None'):
                return None
            return float(s)
        except Exception:
            return None

    def _normalize_sector_name(self, name: str) -> str:
        """
        规范化中文板块名称，移除常见后缀与标点，便于模糊匹配。
        """
        try:
            if not name:
                return ''
            s = unicodedata.normalize('NFKC', str(name)).strip()
            # 去除常见词与符号：行业/板块/指数/概念/产业/Ⅱ/Ⅰ/及/与 以及空白与标点
            s = re.sub(r'(行业|板块|指数|概念|产业|Ⅱ|Ⅰ|及|与)', '', s)
            s = re.sub(r'[\s·•、，,;；:：\-—_\/]', '', s)
            return s
        except Exception:
            return str(name or '')

    def _get_index_from_sina(self, code: str):
        """
        从新浪行情接口获取指数当前价与涨跌幅（作为备用数据源）。
        Args:
            code: 指数代码，如 'sh000001', 'sz399001', 'sz399006', 'sh000688'
        Returns:
            dict 或 None: { 'current': float, 'change_pct': float }
        """
        try:
            # 新浪接口支持同样格式代码，直接使用
            url = f"http://hq.sinajs.cn/list={code}"
            headers = {
                'User-Agent': self.headers.get('User-Agent', 'Mozilla/5.0'),
                'Referer': 'http://finance.sina.com.cn/'
            }
            resp = requests.get(url, headers=headers, timeout=6)
            # 新浪返回通常为 GBK 编码
            try:
                resp.encoding = resp.encoding or 'gbk'
            except Exception:
                pass
            text = resp.text or ''
            m = re.search(r'="([^"]+)"', text)
            if not m:
                return None
            parts = m.group(1).split(',')
            # 对于指数：parts[2] 昨收，parts[3] 当前价（多数情况）
            prev_close = self._to_float(parts[2] if len(parts) > 2 else None)
            current = self._to_float(parts[3] if len(parts) > 3 else None)
            if prev_close and current:
                change_pct = round((current - prev_close) / prev_close * 100, 2)
                return {
                    'current': round(current, 2),
                    'change_pct': change_pct
                }
            return None
        except Exception:
            return None

    def get_capital_flow(self):
        """
        获取资金流向数据

        Returns:
            dict: 资金流向数据
        """
        # 1. 尝试全局缓存
        cached = self.global_cache.get_capital_flow(self.stock_code)
        if cached:
            return cached

        try:
            # 使用历史K线流向接口 (debug_capital_flow.py 验证可用)
            # 之前使用的实时接口 (push2.eastmoney.com/api/qt/stock/get) 不稳定
            url = "http://push2his.eastmoney.com/api/qt/stock/fflow/kline/get"
            market_id = '1' if self.stock_code.startswith('6') or self.stock_code.startswith('900') else '0'
            
            # f51:日期, f52:主力净流入, f53:小单净流入, f54:中单净流入, f55:超大单净流入, f56:大单净流入
            params = {
                'lmt': '0',
                'klt': '101',
                'secid': f"{market_id}.{self.stock_code}",
                'fields1': 'f1,f2,f3,f7',
                'fields2': 'f51,f52,f53,f54,f55,f56'
            }

            data = None
            try:
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                else:
                    data = self._get_data_via_curl(url, params)
            except Exception:
                data = self._get_data_via_curl(url, params)

            if data and data.get('data') and data['data'].get('klines'):
                klines = data['data']['klines']
                if not klines:
                    return self._get_default_capital_flow()
                    
                latest_data = klines[-1].split(',')
                
                # f51,f52,f53,f54,f55,f56 -> Date, Main, Small, Medium, Super, Large
                date_str = latest_data[0]
                main_inflow = float(latest_data[1]) if len(latest_data) > 1 else 0.0
                small_inflow = float(latest_data[2]) if len(latest_data) > 2 else 0.0
                medium_inflow = float(latest_data[3]) if len(latest_data) > 3 else 0.0
                super_large_inflow = float(latest_data[4]) if len(latest_data) > 4 else 0.0
                large_inflow = float(latest_data[5]) if len(latest_data) > 5 else 0.0
                
                retail_inflow = small_inflow + medium_inflow
                
                capital_flow = {
                    'date': date_str,
                    'main_inflow': main_inflow,
                    'retail_inflow': retail_inflow,
                    'main_inflow_rate': 0.0, # 暂无法从该接口获取，依靠金额判断强度
                    'super_large_inflow': super_large_inflow,
                    'large_inflow': large_inflow,
                    'medium_inflow': medium_inflow,
                    'small_inflow': small_inflow,
                }

                # 判断资金流向趋势
                capital_flow['trend'] = '流入' if capital_flow['main_inflow'] > 0 else '流出'
                capital_flow['strength'] = self._classify_capital_strength(0, capital_flow['main_inflow'])

                # 2. 缓存到全局缓存
                self.global_cache.set_capital_flow(self.stock_code, capital_flow)

                return capital_flow
            
            return self._get_default_capital_flow()

        except Exception as e:
            print(f"   ⚠️  获取资金流向出错: {e}")
            return self._get_default_capital_flow()

    def get_dragon_tiger_list(self, limit: int = 10, days: int = 1):
        """
        获取个股近期龙虎榜记录（东方财富数据中心）

        Args:
            limit: 返回记录数量限制
            days: 查询最近N天的数据 (默认1天，即当天)

        Returns:
            dict: 简要的龙虎榜数据摘要
        """
        # 1. 尝试全局缓存
        cached = self.global_cache.get_dragon_tiger(self.stock_code)
        if cached:
            return cached

        try:
            from datetime import datetime, timedelta

            url = "http://datacenter-web.eastmoney.com/api/data/v1/get"

            # 只查询当天的龙虎榜数据
            today = datetime.now()
            today_str = today.strftime('%Y-%m-%d')

            # 使用正确的龙虎榜数据集API (2024年更新) + 当天日期过滤
            params_primary = {
                'reportName': 'RPT_BILLBOARD_DAILYDETAILS',
                'columns': 'ALL',
                'filter': f'(SECURITY_CODE="{self.stock_code}")(TRADE_DATE=\'{today_str}\')',
                'pageNumber': '1',
                'pageSize': str(limit),
                'sortColumns': 'TRADE_DATE',
                'sortTypes': '-1'
            }

            headers = getattr(self, 'headers', {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })

            def _normalize_record(rec: dict) -> dict:
                # 适配新API字段名 (RPT_BILLBOARD_DAILYDETAILS)
                date = rec.get('TRADE_DATE') or rec.get('TRADEDATE') or rec.get('TRADE_DATE_S', '')
                reason = rec.get('EXPLANATION') or rec.get('BILLBOARD_REASON') or rec.get('REASON') or ''
                net_buy = rec.get('TOTAL_NET') or rec.get('NET_BUY_AMT_VALUE') or rec.get('NETBUYAMT') or rec.get('NET_BUY_AMT')
                amt = rec.get('ACCUM_AMOUNT') or rec.get('DEAL_AMT_VALUE') or rec.get('DEALAMT') or rec.get('DEAL_AMT')
                buy_seats = rec.get('BUY_SEAT_NUM') or rec.get('BUY_NUM')
                sell_seats = rec.get('SELL_SEAT_NUM') or rec.get('SELL_NUM')
                chg1d = rec.get('CHANGE_RATE') or rec.get('CHG_PCT_1D') or rec.get('CHGPCT1')

                # 类型信息（涨停、异动、机构）
                btype = rec.get('CHANGE_TYPE') or rec.get('BILLBOARD_TYPE') or rec.get('BTYPE') or ''

                # 数值安全转换
                try:
                    net_buy = float(net_buy) if net_buy is not None else None
                except Exception:
                    net_buy = None
                try:
                    amt = float(amt) if amt is not None else None
                except Exception:
                    amt = None

                # 强度：净买入占成交额比例
                ratio = None
                if amt and amt != 0 and net_buy is not None:
                    try:
                        ratio = (net_buy / amt) * 100.0
                    except Exception:
                        ratio = None

                # 信号判断
                signal = '中性'
                if isinstance(net_buy, (int, float)):
                    signal = '正面' if net_buy > 0 else ('负面' if net_buy < 0 else '中性')

                return {
                    'date': str(date)[:10] if date else 'N/A',
                    'reason': reason or 'N/A',
                    'type': btype or 'N/A',
                    'net_buy_amount': net_buy,
                    'deal_amount': amt,
                    'buy_seats': buy_seats,
                    'sell_seats': sell_seats,
                    'change_pct_1d': chg1d,
                    'signal': signal,
                    'strength_ratio': ratio
                }

            # 请求主数据集
            data = None
            try:
                resp = requests.get(url, params=params_primary, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                else:
                    print(f"   ⚠️  API请求失败: HTTP {resp.status_code}，尝试使用Curl...")
                    data = self._get_data_via_curl(url, params_primary)
            except Exception as e:
                print(f"   ⚠️  Requests请求出错: {e}，尝试使用Curl...")
                data = self._get_data_via_curl(url, params_primary)

            records = []
            if data and data.get('success') and data.get('result'):
                raw = data['result'].get('data', []) or []
                records = [_normalize_record(r) for r in raw]

            if records:
                latest = records[0]
                summary = {
                    'has_records': True,
                    'last_date': latest.get('date', 'N/A'),
                    'last_reason': latest.get('reason', 'N/A'),
                    'last_signal': latest.get('signal', '中性'),
                    'last_strength_ratio': latest.get('strength_ratio'),
                    'recent_positive': sum(1 for r in records[:limit] if r.get('signal') == '正面'),
                    'recent_negative': sum(1 for r in records[:limit] if r.get('signal') == '负面'),
                    'records': records
                }

                # 2. 缓存到全局缓存
                self.global_cache.set_dragon_tiger(self.stock_code, summary)

                return summary

        except Exception as e:
            print(f"⚠️ 获取龙虎榜数据失败: {str(e)}")

        return self._get_default_dragon_tiger()

    def get_market_sentiment(self):
        """
        获取市场情绪指标 (个股)

        Returns:
            dict: 市场情绪数据
        """
        try:
            # 东方财富市场情绪数据
            # 使用 ulist.np 替代 stock/get (stock/get 已失效)
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            market_id = '1' if self.stock_code.startswith('6') or self.stock_code.startswith('900') else '0'
            params = {
                'secids': f"{market_id}.{self.stock_code}",
                'fltt': '2',
                'fields': 'f8,f10,f7'  # f8:换手率, f10:量比, f7:振幅
            }

            data = None
            try:
                response = requests.get(url, params=params, headers=self.headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                else:
                    print(f"   ⚠️  API请求失败: HTTP {response.status_code}，尝试使用Curl...")
                    data = self._get_data_via_curl(url, params)
            except Exception as e:
                print(f"   ⚠️  Requests请求出错: {e}，尝试使用Curl...")
                data = self._get_data_via_curl(url, params)

            if data and data.get('data') and data['data'].get('diff'):
                stock_data = data['data']['diff'][0]

                sentiment = {
                    'turnover_rate': stock_data.get('f8', 'N/A'),  # 换手率
                    'volume_ratio': stock_data.get('f10', 'N/A'),  # 量比
                    'amplitude': stock_data.get('f7', 'N/A'),  # 振幅
                    'up_down_ratio': 'N/A',  # 涨跌家数比(需要板块数据)
                    'market_cap_rank': 'N/A',  # 市值排名
                }

                # 换手率情绪判断
                if isinstance(sentiment['turnover_rate'], (int, float)):
                    if sentiment['turnover_rate'] > 10:
                        sentiment['turnover_emotion'] = '活跃'
                    elif sentiment['turnover_rate'] > 5:
                        sentiment['turnover_emotion'] = '正常'
                    else:
                        sentiment['turnover_emotion'] = '低迷'
                else:
                    sentiment['turnover_emotion'] = '未知'

                return sentiment

        except Exception as e:
            print(f"⚠️ 获取市场情绪失败: {str(e)}")

        return self._get_default_market_sentiment()

    def get_overall_market_sentiment(self):
        """
        获取大盘整体情绪 (上证、深证、创业板)

        Returns:
            dict: 大盘情绪数据
        """
        # 1. 尝试全局缓存(大盘数据是全局共享的)
        cached = self.global_cache.get_overall_market()
        if cached:
            return cached

        try:
            # 主要指数代码
            indices = {
                'sh000001': {'name': '上证指数', 'secid': '1.000001'},
                'sh000688': {'name': '科创板', 'secid': '1.000688'},  # 科创板主指数（科创50）
                'sz399001': {'name': '深证成指', 'secid': '0.399001'},
                'sz399006': {'name': '创业板指', 'secid': '0.399006'},
            }

            # 根据股票代码推断所属大盘
            def _infer_primary_index(code: str) -> str:
                try:
                    c = code or ''
                    # 先识别科创板（688开头）
                    if c.startswith('688'):
                        return 'sh000688'  # 科创板
                    # 6开头视为上证主板
                    if c.startswith('6'):
                        return 'sh000001'  # 上证指数
                    # 创业板
                    if c.startswith('300'):
                        return 'sz399006'  # 创业板指
                    # 其他默认深证主板/中小板
                    return 'sz399001'
                except Exception:
                    return 'sz399001'

            primary_key = _infer_primary_index(self.stock_code)

            market_data = {}

            for code, info in indices.items():
                try:
                    # 使用 kline/get 替代 stock/get (stock/get 已失效)
                    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
                    params = {
                        'secid': info['secid'],
                        'klt': '101',
                        'fqt': '1',
                        'lmt': '1',
                        'fields1': 'f1,f2,f3,f4,f5,f6',
                        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
                    }

                    response = requests.get(url, params=params, headers=self.headers, timeout=10)
                    data = response.json()

                    if data.get('data') and data['data'].get('klines'):
                        kline_str = data['data']['klines'][0]
                        parts = kline_str.split(',')
                        # f51(Date), f52(Open), f53(Close), f54(High), f55(Low), f56(Vol), f57(Amt), f58(Amp), f59(Chg%), f60(ChgAmt), f61(Turnover)
                        
                        try:
                            current = float(parts[2]) # f53 Close
                            change_pct = float(parts[8]) # f59 Change Pct
                        except (IndexError, ValueError):
                            current = 0
                            change_pct = 0
                        
                        market_data[code] = {
                            'name': info['name'],
                            'current': round(current, 2),
                            'change_pct': round(change_pct, 2),
                            'volume_ratio': 'N/A', # kline中无量比
                        }

                except Exception as e:
                    market_data[code] = {
                        'name': info['name'],
                        'current': 'N/A',
                        'change_pct': 'N/A',
                        'volume_ratio': 'N/A',
                    }

            # 尝试用新浪备用源补齐缺失的指数涨跌与当前价
            try:
                for code in indices.keys():
                    v = market_data.get(code)
                    # 如果涨跌幅缺失或非数值，尝试备用源
                    if (not v) or (not isinstance(v.get('change_pct'), (int, float))):
                        backup = self._get_index_from_sina(code)
                        if backup:
                            market_data[code] = {
                                'name': (v.get('name') if v and v.get('name') else indices[code]['name']),
                                'current': backup.get('current', (v.get('current') if v else 'N/A')),
                                'change_pct': backup.get('change_pct', (v.get('change_pct') if v else 'N/A')),
                                'volume_ratio': (v.get('volume_ratio') if v else 'N/A'),
                            }
            except Exception:
                pass

            # 计算整体市场情绪
            valid_changes = [v['change_pct'] for v in market_data.values()
                           if isinstance(v['change_pct'], (int, float))]

            avg_change = None
            primary_change = None
            if valid_changes:
                try:
                    avg_change = sum(valid_changes) / len(valid_changes)
                except Exception:
                    avg_change = None

                # 主指数涨跌（所属大盘）
                pk_data = market_data.get(primary_key, {})
                pc = pk_data.get('change_pct')
                if isinstance(pc, (int, float)):
                    primary_change = pc

                # 情绪评分 (0-100) 基于主指数
                # 涨幅 +3% 对应 100分, -3% 对应 0分
                base_change = primary_change if isinstance(primary_change, (int, float)) else 0
                sentiment_score = round(50 + (base_change / 3.0) * 50, 1)
                sentiment_score = max(0, min(100, sentiment_score))

                # 情绪判断
                if sentiment_score >= 65:
                    overall = '强势上涨'
                    emotion = 'bullish'
                elif sentiment_score >= 52:
                    overall = '偏强'
                    emotion = 'slightly_bullish'
                elif sentiment_score >= 48:
                    overall = '震荡'
                    emotion = 'neutral'
                elif sentiment_score >= 35:
                    overall = '偏弱'
                    emotion = 'slightly_bearish'
                else:
                    overall = '弱势下跌'
                    emotion = 'bearish'
            else:
                # 若所有指数涨跌缺失，尝试以主指数日K线回退一次
                try:
                    pk_info = indices.get(primary_key)
                    if pk_info:
                        k_url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
                        k_params = {
                            'secid': pk_info['secid'],
                            'klt': '101',  # 日线
                            'fqt': '1',
                            'lmt': '1',
                            'fields1': 'f1,f2,f3,f4,f5,f6',
                            'fields2': 'f51,f52,f53,f54,f55'
                        }
                        k_resp = requests.get(k_url, params=k_params, headers=self.headers, timeout=10)
                        k_data = k_resp.json()
                        if k_data.get('data') and k_data['data'].get('klines'):
                            last = k_data['data']['klines'][-1]
                            parts = last.split(',')
                            # 通常格式: 日期,开盘,收盘,涨跌幅,...
                            if len(parts) >= 4:
                                try:
                                    primary_change = float(parts[3])
                                except Exception:
                                    primary_change = None
                                if isinstance(primary_change, (int, float)):
                                    avg_change = primary_change
                                    base_change = primary_change
                                    sentiment_score = round(50 + (base_change / 3.0) * 50, 1)
                                    sentiment_score = max(0, min(100, sentiment_score))

                                    if sentiment_score >= 65:
                                        overall = '强势上涨'
                                        emotion = 'bullish'
                                    elif sentiment_score >= 52:
                                        overall = '偏强'
                                        emotion = 'slightly_bullish'
                                    elif sentiment_score >= 48:
                                        overall = '震荡'
                                        emotion = 'neutral'
                                    elif sentiment_score >= 35:
                                        overall = '偏弱'
                                        emotion = 'slightly_bearish'
                                    else:
                                        overall = '弱势下跌'
                                        emotion = 'bearish'
                                else:
                                    sentiment_score = 50
                                    overall = '数据不足'
                                    emotion = 'neutral'
                            else:
                                sentiment_score = 50
                                overall = '数据不足'
                                emotion = 'neutral'
                        else:
                            sentiment_score = 50
                            overall = '数据不足'
                            emotion = 'neutral'
                    else:
                        sentiment_score = 50
                        overall = '数据不足'
                        emotion = 'neutral'
                except Exception:
                    sentiment_score = 50
                    overall = '数据不足'
                    emotion = 'neutral'

            result = {
                'indices': market_data,
                'sentiment_score': sentiment_score,
                'overall': overall,
                'emotion': emotion,
                'primary_index': {
                    'key': primary_key,
                    'name': indices.get(primary_key, {}).get('name', market_data.get(primary_key, {}).get('name', '所属大盘')),
                    'change_pct': (
                        primary_change if isinstance(primary_change, (int, float))
                        else (avg_change if isinstance(avg_change, (int, float)) else 'N/A')
                    ),
                },
                'primary_change_pct': (
                    round(primary_change, 2) if isinstance(primary_change, (int, float))
                    else (round(avg_change, 2) if isinstance(avg_change, (int, float)) else 'N/A')
                ),
                'avg_change_pct': round(avg_change, 2) if isinstance(avg_change, (int, float)) else 'N/A',
            }

            # 成功获取到有效数据时写入全局缓存
            try:
                if isinstance(result.get('primary_change_pct'), (int, float)) or isinstance(result.get('avg_change_pct'), (int, float)):
                    self.global_cache.set_overall_market(result)
            except Exception:
                pass

            return result

        except Exception as e:
            print(f"⚠️ 获取大盘情绪失败: {str(e)}")
            # 失败时尝试读取全局缓存
            cached = self.global_cache.get_overall_market()
            if cached:
                return cached
            return self._get_default_overall_market_sentiment()

    def _safe_request_with_retry(self, url, params=None, max_retries=3, timeout=15):
        """
        带重试机制的安全请求方法
        
        Args:
            url: 请求URL
            params: 请求参数
            max_retries: 最大重试次数
            timeout: 超时时间
            
        Returns:
            dict: 解析后的JSON数据，失败时返回None
        """
        for attempt in range(max_retries):
            try:
                # 使用会话保持连接
                session = requests.Session()
                
                # 设置完整的请求头
                session.headers.update(self.headers)
                
                # 添加随机延迟，避免被识别为机器人
                if attempt > 0:
                    time.sleep(random.uniform(1, 3))
                
                response = session.get(
                    url, 
                    params=params, 
                    timeout=timeout,
                    verify=False,  # 忽略SSL证书验证
                    allow_redirects=True
                )
                
                # 检查HTTP状态码
                if response.status_code == 200:
                    # 检查响应内容是否为空
                    if response.text.strip():
                        try:
                            return response.json()
                        except json.JSONDecodeError as e:
                            print(f"   ⚠️  JSON解析错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                            print(f"   📄 响应内容: {response.text[:200]}...")
                    else:
                        print(f"   ⚠️  响应内容为空 (尝试 {attempt + 1}/{max_retries})")
                else:
                    print(f"   ⚠️  HTTP错误 {response.status_code} (尝试 {attempt + 1}/{max_retries})")
                    print(f"   📄 响应内容: {response.text[:200]}...")
                    
            except requests.exceptions.ConnectionError as e:
                print(f"   ⚠️  连接错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            except requests.exceptions.Timeout as e:
                print(f"   ⚠️  请求超时 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            except requests.exceptions.RequestException as e:
                print(f"   ⚠️  请求异常 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            except Exception as e:
                print(f"   ⚠️  未知错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            
            # 重试前等待，避免频繁请求
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 递增等待时间：2s, 4s, 6s
                print(f"   🔄 等待 {wait_time}s 后重试...")
                time.sleep(wait_time)
        
        return None

    def get_sector_info_and_sentiment(self):
        """
        获取股票所属板块及板块情绪 - 使用新的API获取真实数据(支持多数据源)

        Returns:
            dict: 板块信息和情绪数据
        """
        # 【优化】使用线程锁避免并发重复查询
        lock_key = f"sector_{self.stock_code}"
        with _locks_lock:
            if lock_key not in _request_locks:
                _request_locks[lock_key] = threading.Lock()
        lock = _request_locks[lock_key]
        
        with lock:
            # 先检查缓存（避免重复查询）
            sector_name_cache_key = f"sector_name_{self.stock_code}"
            cached_sector_name = self.global_cache.get(sector_name_cache_key) if hasattr(self.global_cache, 'get') else None
            
            if cached_sector_name:
                cached_sentiment = self.global_cache.get_sector(cached_sector_name)
                if cached_sentiment:
                    # 缓存命中，直接返回
                    return {
                        'sector_name': cached_sector_name,
                        'sector_sentiment': cached_sentiment,
                        'stock_name': '',
                        'current_price': 0,
                        'industry': cached_sector_name,
                        'concept_sectors': [],
                        'data_source': 'cache'
                    }
        
        # 未命中缓存，执行查询（锁保护下）
        with lock:
            # 双重检查：可能其他线程已经查询并缓存了
            if cached_sector_name:
                cached_sentiment = self.global_cache.get_sector(cached_sector_name)
                if cached_sentiment:
                    return {
                        'sector_name': cached_sector_name,
                        'sector_sentiment': cached_sentiment,
                        'stock_name': '',
                        'current_price': 0,
                        'industry': cached_sector_name,
                        'concept_sectors': [],
                        'data_source': 'cache'
                    }
            
            try:
                # 使用多数据源API获取真实数据(自动切换)
                sector_info = get_stock_sector_info_multi_source(self.stock_code)
                sector_sentiment = get_sector_sentiment_multi_source(self.stock_code)

                if sector_info.get('success'):
                    # 先尝试从全局缓存获取板块情绪(按板块名称缓存,多只股票可共享)
                    sector_name = sector_info.get('sector_name', '未知')
                    cached_sentiment = self.global_cache.get_sector(sector_name)

                    if cached_sentiment:
                        # 缓存命中，直接使用
                        sector_sentiment = cached_sentiment
                    else:
                        # 无缓存,使用API获取的情绪数据并缓存
                        sentiment_data = {
                            'sector_name': sector_sentiment.get('sector_name', '未知'),
                            'sentiment_score': sector_sentiment.get('sentiment_score', 50),
                            'overall': sector_sentiment.get('overall', '市场情绪中性'),
                            'change_pct': sector_sentiment.get('change_pct', 0),
                            'turnover_rate': sector_sentiment.get('turnover_rate', 0),
                            'emotion': sector_sentiment.get('emotion', '中性'),
                            'data_source': sector_sentiment.get('data_source', 'api')
                        }
                        
                        # 检查数据有效性：如果涨跌幅和换手率都为0，且来源不是mock，可能是无效数据
                        # 只有数据有效才缓存，避免缓存无效的0值数据
                        is_valid = (sentiment_data['change_pct'] != 0 or sentiment_data['turnover_rate'] != 0)
                        
                        if is_valid:
                            # 使用set_sector方法缓存板块情绪（按板块名称缓存，多只股票可共享）
                            self.global_cache.set_sector(sector_name, sentiment_data)
                        # 静默跳过无效数据
                            
                        sector_sentiment = sentiment_data

                    return {
                        'sector_name': sector_name,
                        'sector_sentiment': sector_sentiment,
                        'stock_name': sector_info.get('stock_name', ''),
                        'current_price': sector_info.get('current_price', 0),
                        'industry': sector_info.get('industry', '未知'),
                        'concept_sectors': sector_info.get('concept_sectors', []),
                        'data_source': sector_info.get('data_source', 'api')
                    }
                else:
                    print(f"   ⚠️ API获取失败，使用备用方案")
                    return self._get_sector_info_fallback()

            except Exception as e:
                print(f"   ❌ 板块API调用失败: {e}")
                import traceback
                traceback.print_exc()
                return self._get_sector_info_fallback()
    
    def _get_sector_from_tencent(self):
        """
        从腾讯财经获取股票板块信息
        
        Returns:
            dict: 板块信息和情绪数据
        """
        try:
            print(f"   🔍 尝试腾讯财经API获取板块信息...")
            
            # 腾讯财经股票详情API，需要添加市场前缀
            if self.stock_code.startswith('6') or self.stock_code.startswith('900'):
                market_prefix = 'sh'
            elif self.stock_code.startswith(('8', '4', '92')):
                market_prefix = 'bj'
            else:
                market_prefix = 'sz'
            
            tencent_code = f"{market_prefix}{self.stock_code}"
            tencent_url = f"http://qt.gtimg.cn/q={tencent_code}"
            
            response = requests.get(tencent_url, headers=self.headers, timeout=10)
            if response.status_code == 200 and response.text:
                content = response.text.strip()
                
                # 解析腾讯财经数据格式: v_sh688343="1~股票名称~688343~..."
                if f'v_{tencent_code}=' in content:
                    data_part = content.split('"')[1]
                    fields = data_part.split('~')
                    
                    if len(fields) > 10:
                        stock_name = fields[1]  # 股票名称
                        current_price = fields[3]  # 当前价格
                        prev_close = fields[4]  # 昨收价
                        
                        # 计算涨跌幅
                        try:
                            change_pct = ((float(current_price) - float(prev_close)) / float(prev_close)) * 100
                            change_pct_str = f"{change_pct:.2f}"
                        except (ValueError, ZeroDivisionError):
                            change_pct_str = '0.00'
                        
                        # 不再使用硬编码推断，直接返回综合
                        sector_name = '综合'
                        
                        print(f"   📊 腾讯财经获取成功: {stock_name} ({current_price})")
                        print(f"   🏢 备用板块分类: {sector_name}")
                        print(f"   📈 涨跌幅: {change_pct_str}%")
                        
                        # 计算情绪评分
                        sentiment_score = self._calculate_sentiment_from_change(change_pct_str)
                        
                        return {
                            'sector_name': sector_name,
                            'sector_sentiment': {
                                'sector_name': sector_name,
                                'sector_code': 'N/A',
                                'change_pct': change_pct_str,
                                'turnover_rate': 'N/A',
                                'sentiment_score': sentiment_score,
                                'overall': self._get_sentiment_description(sentiment_score),
                                'emotion': self._get_emotion_from_score(sentiment_score)
                            }
                        }
            
        except Exception as e:
            print(f"   ⚠️  腾讯财经API失败: {str(e)}")
        
        return {
            'sector_name': 'N/A',
            'sector_sentiment': self._get_default_sector_sentiment()
        }
    
    def _get_sector_from_eastmoney(self):
        """
        从东方财富获取股票板块信息（原有逻辑）
        
        Returns:
            dict: 板块信息和情绪数据
        """
        try:
            # 使用 ulist.np 替代 stock/get
            url = "http://push2.eastmoney.com/api/qt/ulist.np/get"
            market_id = '1' if self.stock_code.startswith('6') or self.stock_code.startswith('900') else '0'
            params = {
                'secids': f"{market_id}.{self.stock_code}",
                'fltt': '2',
                'fields': 'f100'  # f100: 所属行业
            }
            
            print(f"   🔍 尝试API端点: {url}")
            data = self._safe_request_with_retry(url, params, max_retries=2, timeout=10)

            if data and data.get('data') and data['data'].get('diff'):
                print(f"   ✅ 成功获取数据")
                stock_data = data['data']['diff'][0]
                # f100: 所属行业名称
                sector_name = stock_data.get('f100', 'N/A')
                sector_code = '' # ulist.np 不直接返回板块代码
                
                if sector_name == 'N/A':
                     sector_name = stock_data.get('f102', 'N/A')
                
                if sector_name != 'N/A':
                    # 获取板块情绪
                    sector_sentiment = self._get_sector_sentiment_score(sector_name, sector_code)
                    return {
                        'sector_name': sector_name,
                        'sector_sentiment': sector_sentiment
                    }
            else:
                print(f"   ⚠️  所有API端点均失败，尝试备用方案")
                # 尝试备用API获取基本股票信息
                return self._get_sector_info_fallback()

            # 如果无法获取行业名称，尝试基于行业代码回退计算板块情绪
            if sector_name == 'N/A' or not sector_name:
                if sector_code:
                    try:
                        # 通过行业代码获取成分股，基于成分股均值估算板块涨跌与换手
                        constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                        constituents_params = {
                            'pn': '1',
                            'pz': '200',
                            'po': '1',
                            'np': '1',
                            'fltt': '2',
                            'invt': '2',
                            'fid': 'f3',
                            'fs': f"b:{sector_code}",
                            'fields': 'f12,f14,f3,f8'
                        }

                        resp_data = self._safe_request_with_retry(constituents_url, constituents_params)
                        if resp_data and resp_data.get('data') and resp_data['data'].get('diff'):
                            stocks = resp_data['data']['diff']
                            changes = [s.get('f3') for s in stocks if isinstance(s.get('f3'), (int, float))]
                            turns = [s.get('f8') for s in stocks if isinstance(s.get('f8'), (int, float))]

                            if changes:
                                avg_change = round(sum(changes) / len(changes), 2)
                            else:
                                avg_change = 'N/A'

                            if turns:
                                avg_turnover = round(sum(turns) / len(turns), 2)
                            else:
                                avg_turnover = 'N/A'

                            # 情绪分数（与原逻辑一致）
                            if isinstance(avg_change, (int, float)):
                                sentiment_score = round(50 + (avg_change / 5.0) * 50, 1)
                                sentiment_score = max(0, min(100, sentiment_score))
                            else:
                                sentiment_score = 50

                            if sentiment_score >= 65:
                                overall = '强势领涨'
                                emotion = 'bullish'
                            elif sentiment_score >= 52:
                                overall = '偏强'
                                emotion = 'slightly_bullish'
                            elif sentiment_score >= 48:
                                overall = '震荡'
                                emotion = 'neutral'
                            elif sentiment_score >= 35:
                                overall = '偏弱'
                                emotion = 'slightly_bearish'
                            else:
                                overall = '弱势下跌'
                                emotion = 'bearish'

                            sector_sentiment = {
                                'sector_name': sector_name if sector_name and sector_name != 'N/A' else '行业板块',
                                'sector_code': sector_code,
                                'change_pct': avg_change,
                                'turnover_rate': avg_turnover,
                                'sentiment_score': sentiment_score,
                                'overall': overall,
                                'emotion': emotion,
                            }

                            # 识别龙头（与原逻辑一致）
                            try:
                                leader_item = max(stocks, key=lambda x: x.get('f3', -999999)) if stocks else None
                                if leader_item:
                                    leader = {
                                        'code': leader_item.get('f12', ''),
                                        'name': leader_item.get('f14', ''),
                                        'change_pct': round(leader_item.get('f3', 0), 2) if isinstance(leader_item.get('f3', 0), (int, float)) else leader_item.get('f3', 'N/A'),
                                        'turnover_rate': round(leader_item.get('f8', 0), 2) if isinstance(leader_item.get('f8', 0), (int, float)) else leader_item.get('f8', 'N/A'),
                                        'is_current_stock': True if leader_item.get('f12', '').endswith(self.stock_code) else False
                                    }
                                    sector_sentiment['leader_stock'] = leader
                            except Exception:
                                pass

                            # 写入板块缓存
                            try:
                                ck = f"sector_{sector_sentiment.get('sector_code') or sector_sentiment.get('sector_name') or self.stock_code}"
                                self._write_cache(ck, sector_sentiment)
                            except Exception:
                                pass

                            return sector_sentiment
                    except Exception as e:
                        print(f"   ⚠️  行业代码回退失败: {str(e)}")

                # 无行业代码，尝试计算行业板块总体均值作为回退
                try:
                    sector_url = "http://push2.eastmoney.com/api/qt/clist/get"
                    sector_params = {
                        'pn': '1',
                        'pz': '200',
                        'po': '1',
                        'np': '1',
                        'fltt': '2',
                        'invt': '2',
                        'fid': 'f3',
                        'fs': 'm:90 t:2',
                        'fields': 'f12,f14,f3,f8'
                    }
                    respx_data = self._safe_request_with_retry(sector_url, sector_params)
                    if respx_data and respx_data.get('data') and respx_data['data'].get('diff'):
                        lst = respx_data['data']['diff']
                        changes = [x.get('f3') for x in lst if isinstance(x.get('f3'), (int, float))]
                        turns = [x.get('f8') for x in lst if isinstance(x.get('f8'), (int, float))]
                        avg_change = round(sum(changes) / len(changes), 2) if changes else 'N/A'
                        avg_turnover = round(sum(turns) / len(turns), 2) if turns else 'N/A'

                        sentiment_score = 50
                        if isinstance(avg_change, (int, float)):
                            sentiment_score = round(50 + (avg_change / 5.0) * 50, 1)
                            sentiment_score = max(0, min(100, sentiment_score))

                        if sentiment_score >= 65:
                            overall = '强势领涨'
                            emotion = 'bullish'
                        elif sentiment_score >= 52:
                            overall = '偏强'
                            emotion = 'slightly_bullish'
                        elif sentiment_score >= 48:
                            overall = '震荡'
                            emotion = 'neutral'
                        elif sentiment_score >= 35:
                            overall = '偏弱'
                            emotion = 'slightly_bearish'
                        else:
                            overall = '弱势下跌'
                            emotion = 'bearish'

                        sector_sentiment = {
                            'sector_name': '行业板块',
                            'sector_code': 'N/A',
                            'change_pct': avg_change,
                            'turnover_rate': avg_turnover,
                            'sentiment_score': sentiment_score,
                            'overall': overall,
                            'emotion': emotion,
                        }
                        try:
                            ck = f"sector_{self.stock_code}"
                            self._write_cache(ck, sector_sentiment)
                        except Exception:
                            pass
                        return sector_sentiment
                except Exception:
                    pass

                # 尝试读取缓存作为回退
                cached = self._read_cache(f"sector_{sector_code or self.stock_code}", max_age_sec=600)
                if cached:
                    return cached
                return self._get_default_sector_sentiment()

            # 获取同行业板块行情数据
            try:
                # 东方财富行业板块接口
                sector_url = "http://push2.eastmoney.com/api/qt/clist/get"
                sector_params = {
                    'pn': '1',
                    'pz': '200',
                    'po': '1',
                    'np': '1',
                    'fltt': '2',
                    'invt': '2',
                    'fid': 'f3',  # 按涨跌幅排序
                    'fs': 'm:90 t:2',  # 行业板块
                    'fields': 'f12,f14,f2,f3,f8'  # 代码、名称、价格、涨跌幅、换手率
                }

                sector_data = self._safe_request_with_retry(sector_url, sector_params)

                sector_sentiment = None

                if sector_data and sector_data.get('data') and sector_data['data'].get('diff'):
                    sectors = sector_data['data']['diff']

                    # 查找匹配的行业板块
                    for sector in sectors:
                        if sector.get('f14', '') == sector_name:
                            change_pct = sector.get('f3', 0)
                            turnover_rate = sector.get('f8', 0)

                            # 东财行业板块接口 f3/f8 已为百分比数值（如 2.34 表示 2.34%），无需再次 /100
                            if isinstance(change_pct, (int, float)):
                                change_pct = round(change_pct, 2)
                            if isinstance(turnover_rate, (int, float)):
                                turnover_rate = round(turnover_rate, 2)

                            # 计算板块情绪分数
                            # 涨幅 +5% 对应 100分, -5% 对应 0分
                            sentiment_score = round(50 + (change_pct / 5.0) * 50, 1)
                            sentiment_score = max(0, min(100, sentiment_score))

                            # 情绪判断
                            if sentiment_score >= 65:
                                overall = '强势领涨'
                                emotion = 'bullish'
                            elif sentiment_score >= 52:
                                overall = '偏强'
                                emotion = 'slightly_bullish'
                            elif sentiment_score >= 48:
                                overall = '震荡'
                                emotion = 'neutral'
                            elif sentiment_score >= 35:
                                overall = '偏弱'
                                emotion = 'slightly_bearish'
                            else:
                                overall = '弱势下跌'
                                emotion = 'bearish'

                            sector_sentiment = {
                                'sector_name': sector_name,
                                'sector_code': sector.get('f12', 'N/A'),
                                'change_pct': change_pct,
                                'turnover_rate': turnover_rate,
                                'sentiment_score': sentiment_score,
                                'overall': overall,
                                'emotion': emotion,
                            }

                            # === 获取板块成分股并识别龙头 ===
                            try:
                                sec_code = sector.get('f12')
                                if sec_code:
                                    constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                                    constituents_params = {
                                        'pn': '1',
                                        'pz': '200',
                                        'po': '1',
                                        'np': '1',
                                        'fltt': '2',
                                        'invt': '2',
                                        'fid': 'f3',  # 按涨跌幅排序
                                        'fs': f"b:{sec_code}",  # 板块成分股
                                        'fields': 'f12,f14,f3,f8'  # 代码、名称、涨跌幅、换手率
                                    }

                                    resp2 = requests.get(constituents_url, params=constituents_params, headers=self.headers, timeout=10)
                                    data2 = resp2.json()
                                    if data2.get('data') and data2['data'].get('diff'):
                                        stocks = data2['data']['diff']

                                        # 识别龙头：以当日涨跌幅最高者为龙头候选
                                        leader = None
                                        try:
                                            leader_item = max(stocks, key=lambda x: x.get('f3', -999999))
                                            leader = {
                                                'code': leader_item.get('f12', ''),
                                                'name': leader_item.get('f14', ''),
                                                'change_pct': round(leader_item.get('f3', 0), 2) if isinstance(leader_item.get('f3', 0), (int, float)) else leader_item.get('f3', 'N/A'),
                                                'turnover_rate': round(leader_item.get('f8', 0), 2) if isinstance(leader_item.get('f8', 0), (int, float)) else leader_item.get('f8', 'N/A'),
                                                'is_current_stock': True if leader_item.get('f12', '').endswith(self.stock_code) else False
                                            }
                                        except Exception:
                                            leader = None

                                        if leader:
                                            sector_sentiment['leader_stock'] = leader
                                    # 若无成分股数据，跳过龙头识别
                            except Exception:
                                pass
                            break

                # 若未找到完全匹配的行业名称，尝试基于规范化名称的模糊匹配
                if not sector_sentiment and sector_name and sector_name != 'N/A':
                    try:
                        target = self._normalize_sector_name(sector_name)
                        for sec in sectors:
                            sname = sec.get('f14', '')
                            norm = self._normalize_sector_name(sname)
                            if not norm:
                                continue
                            if norm == target or (target and (norm in target or target in norm)):
                                change_pct = sec.get('f3', 0)
                                turnover_rate = sec.get('f8', 0)

                                if isinstance(change_pct, (int, float)):
                                    change_pct = round(change_pct, 2)
                                if isinstance(turnover_rate, (int, float)):
                                    turnover_rate = round(turnover_rate, 2)

                                sentiment_score = round(50 + (float(change_pct or 0) / 5.0) * 50, 1)
                                sentiment_score = max(0, min(100, sentiment_score))

                                if sentiment_score >= 65:
                                    overall = '强势领涨'
                                    emotion = 'bullish'
                                elif sentiment_score >= 52:
                                    overall = '偏强'
                                    emotion = 'slightly_bullish'
                                elif sentiment_score >= 48:
                                    overall = '震荡'
                                    emotion = 'neutral'
                                elif sentiment_score >= 35:
                                    overall = '偏弱'
                                    emotion = 'slightly_bearish'
                                else:
                                    overall = '弱势下跌'
                                    emotion = 'bearish'

                                sector_sentiment = {
                                    'sector_name': sector_name,
                                    'sector_code': sec.get('f12', 'N/A'),
                                    'change_pct': change_pct,
                                    'turnover_rate': turnover_rate,
                                    'sentiment_score': sentiment_score,
                                    'overall': overall,
                                    'emotion': emotion,
                                }
                                break
                    except Exception:
                        pass

                # 若模糊匹配仍失败，且有行业代码，则以成分股均值估算
                if (not sector_sentiment) and sector_code:
                    try:
                        constituents_url = "http://push2.eastmoney.com/api/qt/clist/get"
                        constituents_params = {
                            'pn': '1',
                            'pz': '200',
                            'po': '1',
                            'np': '1',
                            'fltt': '2',
                            'invt': '2',
                            'fid': 'f3',
                            'fs': f"b:{sector_code}",
                            'fields': 'f12,f14,f3,f8'
                        }
                        resp2 = requests.get(constituents_url, params=constituents_params, headers=self.headers, timeout=10)
                        data2 = resp2.json()
                        if data2.get('data') and data2['data'].get('diff'):
                            stocks = data2['data']['diff']
                            changes = [x.get('f3') for x in stocks if isinstance(x.get('f3'), (int, float))]
                            turns = [x.get('f8') for x in stocks if isinstance(x.get('f8'), (int, float))]
                            avg_change = round(sum(changes) / len(changes), 2) if changes else 'N/A'
                            avg_turnover = round(sum(turns) / len(turns), 2) if turns else 'N/A'

                            sentiment_score = 50
                            if isinstance(avg_change, (int, float)):
                                sentiment_score = round(50 + (avg_change / 5.0) * 50, 1)
                                sentiment_score = max(0, min(100, sentiment_score))

                            if sentiment_score >= 65:
                                overall = '强势领涨'
                                emotion = 'bullish'
                            elif sentiment_score >= 52:
                                overall = '偏强'
                                emotion = 'slightly_bullish'
                            elif sentiment_score >= 48:
                                overall = '震荡'
                                emotion = 'neutral'
                            elif sentiment_score >= 35:
                                overall = '偏弱'
                                emotion = 'slightly_bearish'
                            else:
                                overall = '弱势下跌'
                                emotion = 'bearish'

                            sector_sentiment = {
                                'sector_name': sector_name if sector_name and sector_name != 'N/A' else '行业板块',
                                'sector_code': sector_code,
                                'change_pct': avg_change,
                                'turnover_rate': avg_turnover,
                                'sentiment_score': sentiment_score,
                                'overall': overall,
                                'emotion': emotion,
                            }
                    except Exception:
                        pass

                if sector_sentiment:
                    # 写入板块缓存
                    try:
                        ck = f"sector_{sector_sentiment.get('sector_code') or sector_sentiment.get('sector_name') or self.stock_code}"
                        self._write_cache(ck, sector_sentiment)
                    except Exception:
                        pass
                    return sector_sentiment

            except Exception as e:
                print(f"   ⚠️  获取板块行情失败: {str(e)}")

            # 如果无法获取板块行情，优先尝试多种缓存键，其次用大盘情绪缓存估算，最后返回默认
            try:
                cache_keys = []
                if sector_code:
                    cache_keys.append(f"sector_{sector_code}")
                if sector_name:
                    cache_keys.append(f"sector_{sector_name}")
                cache_keys.append(f"sector_{self.stock_code}")
            except Exception:
                cache_keys = [f"sector_{self.stock_code}"]

            cached = None
            for ck in cache_keys:
                try:
                    cached = self._read_cache(ck, max_age_sec=600)
                except Exception:
                    cached = None
                if cached:
                    return cached

            # 尝试用大盘整体情绪缓存估算板块情绪，避免返回N/A
            try:
                om = self._read_cache('overall_market', max_age_sec=600)
                if om:
                    base_change = om.get('primary_change_pct')
                    if not isinstance(base_change, (int, float)):
                        base_change = om.get('avg_change_pct')

                    change_pct = (round(base_change, 2) if isinstance(base_change, (int, float)) else 0.0)
                    turnover_rate = 'N/A'  # 无法可靠估计换手，保留为N/A

                    # 以 sector 的评分标准（±5% 对应 0/100）估算情绪
                    sentiment_score = 50
                    if isinstance(base_change, (int, float)):
                        sentiment_score = round(50 + (base_change / 5.0) * 50, 1)
                        sentiment_score = max(0, min(100, sentiment_score))

                    if sentiment_score >= 65:
                        overall = '强势领涨'
                        emotion = 'bullish'
                    elif sentiment_score >= 52:
                        overall = '偏强'
                        emotion = 'slightly_bullish'
                    elif sentiment_score >= 48:
                        overall = '震荡'
                        emotion = 'neutral'
                    elif sentiment_score >= 35:
                        overall = '偏弱'
                        emotion = 'slightly_bearish'
                    else:
                        overall = '弱势下跌'
                        emotion = 'bearish'

                    pseudo_sector = {
                        'sector_name': sector_name if sector_name and sector_name != 'N/A' else '行业板块',
                        'sector_code': sector_code or 'N/A',
                        'change_pct': change_pct,
                        'turnover_rate': turnover_rate,
                        'sentiment_score': sentiment_score,
                        'overall': overall,
                        'emotion': emotion,
                    }

                    try:
                        ck = f"sector_{sector_code or sector_name or self.stock_code}"
                        self._write_cache(ck, pseudo_sector)
                    except Exception:
                        pass

                    return pseudo_sector
            except Exception:
                pass

            return {
                'sector_name': sector_name,
                'sector_code': 'N/A',
                'change_pct': 'N/A',
                'turnover_rate': 'N/A',
                'sentiment_score': 50,
                'overall': '数据不足',
                'emotion': 'neutral',
            }

        except Exception as e:
            print(f"⚠️ 获取板块情绪失败: {str(e)}")
            return self._get_default_sector_sentiment()

    def get_guba_sentiment(self, limit=50):
        """
        获取股吧情绪 - 使用Playwright爬取动态页面

        Args:
            limit: 采样评论数

        Returns:
            dict: 股吧情绪数据
        """
        # 首先尝试使用Playwright爬取动态网页
        posts = DynamicCrawler.crawl_guba_posts(self.stock_code, limit)

        if not posts:
            print(f"   ⚠️  Playwright爬取失败,尝试API接口")
            return self._get_guba_from_api(limit)

        # 标题规范化工具（全角转半角，去除多余空白）
        def _normalize_text(s: str) -> str:
            if not s:
                return ''
            s = unicodedata.normalize('NFKC', s)
            s = s.strip()
            return s

        # 过滤广告/垃圾帖关键词（不区分大小写）
        spam_keywords = [
            '荐股', '老师', '课程', '培训', '私募', '开户', '佣金', '带盘', '风控',
            '福利', '抽奖', '活动', '推广', '点击', '链接', '加我', '关注', '实盘',
            '交流群', '加群', '群号', 'vx', 'v信', '微信', 'qq', 'qq群', 'q群',
            '收徒', '收学员', '指导', '内参', '牛股', '打赏', '转发', '置顶'
        ]

        def _is_spam(title: str) -> bool:
            t = title.lower()
            if any(k in t for k in spam_keywords):
                return True
            # 联系方式模式（手机号/微信号/QQ群号）
            if re.search(r'(vx|v信|微信|qq|群)[^\w]*[\d]{5,}', t):
                return True
            if re.search(r'(\d{3}[- ]?\d{4}[- ]?\d{4})', t):  # 电话
                return True
            return False

        # 去重并过滤垃圾帖
        seen_titles = set()
        filtered_posts = []
        spam_removed = 0
        for p in posts:
            title = _normalize_text(p.get('title', ''))
            if not title:
                continue
            if _is_spam(title):
                spam_removed += 1
                continue
            if title in seen_titles:
                continue
            seen_titles.add(title)
            p['title'] = title
            filtered_posts.append(p)

        # 如果过滤过后为空，降级到API
        if not filtered_posts:
            return self._get_guba_from_api(limit)
        posts = filtered_posts

        # 增强的情绪关键词库
        bullish_keywords = {
            # 直接看多词汇
            '看多': 3, '买入': 3, '加仓': 3, '抄底': 3, '建仓': 2,
            # 涨势词汇
            '涨': 2, '上涨': 2, '暴涨': 4, '大涨': 3, '飙涨': 4, '拉升': 2, '冲高': 2,
            # 利好词汇
            '利好': 3, '好消息': 2, '利多': 3, '重大利好': 4,
            # 技术词汇
            '突破': 2, '新高': 3, '强势': 2, '反弹': 2, '回升': 1,
            # 市场情绪
            '牛': 2, '牛市': 3, '看好': 2, '乐观': 2, '推荐': 2,
            # 分红相关
            '分红': 1, '派息': 1, '高股息': 2,
            # 板块与交易术语
            '涨停': 4, '封板': 3, '连板': 3, '反包': 3, '一字板': 3, '妖股': 3
        }

        bearish_keywords = {
            # 直接看空词汇
            '看空': 3, '卖出': 3, '减仓': 3, '清仓': 4, '止损': 3,
            # 跌势词汇
            '跌': 2, '下跌': 2, '暴跌': 4, '大跌': 3, '跳水': 4, '闪崩': 4, '破位': 3,
            # 利空词汇
            '利空': 3, '坏消息': 2, '利淡': 3, '重大利空': 4,
            # 风险词汇
            '风险': 2, '危险': 3, '警惕': 2, '小心': 2, '谨慎': 1,
            # 市场情绪
            '熊': 2, '熊市': 3, '悲观': 2, '恐慌': 3,
            # 退市相关
            '退市': 3, '摘牌': 3, '割肉': 4, '腰斩': 4,
            # 跌停与极端负面
            '跌停': 4, '天地板': 4, '开盘跌停': 4, '大阴': 3, '黑天鹅': 4
        }

        neutral_keywords = {
            '观望': 2, '持有': 1, '等待': 1, '震荡': 2, '横盘': 2,
            '整理': 1, '调整': 1, '盘整': 2, '分化': 1, '轮动': 1
        }

        # 扩展否定词和疑问词
        negations = ['不', '不是', '无', '未', '没', '没有', '别', '莫', '勿', '非']
        questions = ['吗', '呢', '？', '?', '什么时候', '如何', '怎么', '为什么']

        # 强化词汇（增强情绪强度）
        intensifiers = ['非常', '特别', '极其', '超级', '巨', '狂', '疯狂', '史上', '创纪录', '重磅', '实锤', '官方']

        # 削弱词汇（降低确定性）
        downtoners = ['可能', '或许', '也许', '大概', '估计', '疑似']

        def _negation_scope_score(text: str, keywords: dict) -> float:
            """计算带否定词近邻作用的关键词得分（返回累加得分）"""
            score = 0.0
            for kw, w in keywords.items():
                start = 0
                while True:
                    idx = text.find(kw, start)
                    if idx == -1:
                        break
                    # 在关键词前3个字符内出现否定词则反向计分（降低权重）
                    window = text[max(0, idx - 3):idx]
                    if any(n in window for n in negations):
                        score -= w * 0.8
                    else:
                        score += w
                    start = idx + len(kw)
            return score

        def _classify_title_sentiment(title: str) -> str:
            """增强版标题情绪分类，考虑权重、上下文和语义"""
            if not title:
                return 'neutral'

            t = title.strip().lower()
            # 保留标点符号用于上下文分析

            # 检查是否为疑问句（疑问句通常为中性）
            has_question = any(q in t for q in questions)
            if has_question and not any(
                    kw in t for kw in list(bullish_keywords.keys()) + list(bearish_keywords.keys())):
                return 'neutral'

            # 计算情绪得分
            bull_score = 0.0
            bear_score = 0.0
            neu_score = 0.0

            # 检查强化词
            intensity_multiplier = 1.0
            for intensifier in intensifiers:
                if intensifier in t:
                    intensity_multiplier = 1.35
                    break
            # 削弱词处理
            if any(d in t for d in downtoners):
                intensity_multiplier *= 0.85

            # 计算看多得分
            bull_score += _negation_scope_score(t, bullish_keywords) * intensity_multiplier

            # 计算看空得分
            bear_score += _negation_scope_score(t, bearish_keywords) * intensity_multiplier

            # 计算中性得分
            for keyword, weight in neutral_keywords.items():
                if keyword in t:
                    neu_score += weight

            # 标点作用：感叹号增强，问号弱化
            exclamations = t.count('!') + t.count('！')
            questions_cnt = t.count('?') + t.count('？')
            if exclamations:
                bull_score *= (1 + 0.1 * min(exclamations, 2))
                bear_score *= (1 + 0.1 * min(exclamations, 2))
            if questions_cnt:
                bull_score *= (1 - 0.1 * min(questions_cnt, 2))
                bear_score *= (1 - 0.1 * min(questions_cnt, 2))

            # 上下文分析：检查数字和百分比
            import re
            numbers = re.findall(r'\d+(?:\.\d+)?%?', t)
            if numbers:
                # 如果有大数字（>20%），增强情绪
                for num_str in numbers:
                    try:
                        num = float(num_str.replace('%', ''))
                        if num > 20:
                            if bull_score > bear_score:
                                bull_score *= 1.3
                            elif bear_score > bull_score:
                                bear_score *= 1.3
                    except:
                        pass

            # 决策逻辑
            total_score = bull_score + bear_score + neu_score

            # 如果总得分太低，判为中性
            if total_score < 1:
                return 'neutral'

            # 如果看多看空得分接近，判为中性
            if abs(bull_score - bear_score) < 1 and max(bull_score, bear_score) > 0:
                return 'neutral'

            # 中性得分占主导
            if neu_score > max(bull_score, bear_score) * 1.5:
                return 'neutral'

            # 最终判断
            if bull_score > bear_score:
                return 'bullish'
            elif bear_score > bull_score:
                return 'bearish'
            else:
                return 'neutral'

        # 统计热词时也使用新的关键词库
        all_keywords = {**bullish_keywords, **bearish_keywords, **neutral_keywords}

        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        total_posts = len(posts)
        hot_keywords = {}

        # 分析帖子标题情绪
        decisive_count = 0
        for post in posts:
            title = post.get('title', '')
            sentiment_cls = _classify_title_sentiment(title)
            if sentiment_cls == 'bullish':
                bullish_count += 1
                decisive_count += 1
            elif sentiment_cls == 'bearish':
                bearish_count += 1
                decisive_count += 1
            else:
                neutral_count += 1

            # 统计热词
            for keyword in all_keywords:
                if keyword in title:
                    hot_keywords[keyword] = hot_keywords.get(keyword, 0) + 1

        # 计算比例
        bullish_ratio = round(bullish_count / total_posts * 100, 1) if total_posts > 0 else 0
        bearish_ratio = round(bearish_count / total_posts * 100, 1) if total_posts > 0 else 0
        neutral_ratio = round(neutral_count / total_posts * 100, 1) if total_posts > 0 else 0

        # 归一化
        total_ratio = bullish_ratio + bearish_ratio + neutral_ratio
        if total_ratio > 0:
            bullish_ratio = round(bullish_ratio / total_ratio * 100, 1)
            bearish_ratio = round(bearish_ratio / total_ratio * 100, 1)
            neutral_ratio = round(neutral_ratio / total_ratio * 100, 1)

        # 新增：根据有效样本比例计算置信度衰减系数
        confidence = round(decisive_count / total_posts * 100, 1) if total_posts else 0.0
        amp = max(0.25, min(1.0, confidence / 100))

        # 情绪得分 (0-100, 基于看涨比例，叠加置信度衰减)
        sentiment_score = round(50 + ((bullish_ratio - bearish_ratio) / 2) * amp, 1)

        # 提取top5热词
        top_keywords = sorted(hot_keywords.items(), key=lambda x: x[1], reverse=True)[:5]
        hot_keywords_list = [kw for kw, count in top_keywords]

        guba_sentiment = {
            'total_posts': total_posts,
            'active_users': max(int(total_posts * 0.3), 1),  # 估算活跃用户
            'bullish_ratio': bullish_ratio,
            'bearish_ratio': bearish_ratio,
            'neutral_ratio': neutral_ratio,
            'hot_keywords': hot_keywords_list,
            'sentiment_score': sentiment_score,
            'effective_posts': total_posts,
            'spam_removed': spam_removed,
            'confidence': round(decisive_count / total_posts * 100, 1) if total_posts else 0.0,
        }

        # 综合判断
        if bullish_ratio > 60:
            guba_sentiment['overall'] = '强烈看多'
        elif bullish_ratio > 50:
            guba_sentiment['overall'] = '看多'
        elif bearish_ratio > 60:
            guba_sentiment['overall'] = '强烈看空'
        elif bearish_ratio > 50:
            guba_sentiment['overall'] = '看空'
        else:
            guba_sentiment['overall'] = '中性'

        return guba_sentiment

    def _get_guba_from_api(self, limit=50):
        """使用API获取股吧情绪作为备用方案"""
        try:
            # 东方财富股吧API
            url = f"http://gbapi.eastmoney.com/post/api/v1/posts"
            params = {
                'code': self.stock_code,
                'ps': limit,
                'pn': 1
            }

            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            data = response.json()

            if data and data.get('data') and data['data'].get('list'):
                posts = data['data']['list']

                bullish_keywords = ['看多', '买入', '加仓', '涨', '利好', '牛', '突破', '上涨', '暴涨']
                bearish_keywords = ['看空', '卖出', '减仓', '跌', '利空', '熊', '破位', '下跌', '暴跌']

                bullish_count = 0
                bearish_count = 0

                for post in posts:
                    title = post.get('title', '')
                    is_bullish = any(kw in title for kw in bullish_keywords)
                    is_bearish = any(kw in title for kw in bearish_keywords)

                    if is_bullish and not is_bearish:
                        bullish_count += 1
                    elif is_bearish and not is_bullish:
                        bearish_count += 1

                total_posts = len(posts)
                bullish_ratio = round(bullish_count / total_posts * 100, 1) if total_posts > 0 else 0
                bearish_ratio = round(bearish_count / total_posts * 100, 1) if total_posts > 0 else 0
                neutral_ratio = round((total_posts - bullish_count - bearish_count) / total_posts * 100,
                                      1) if total_posts > 0 else 0

                # 新增：根据有效样本比例计算置信度衰减系数
                effective_posts = bullish_count + bearish_count
                amp = max(0.25, min(1.0, (effective_posts / total_posts) if total_posts > 0 else 0.0))

                sentiment_score = round(50 + ((bullish_ratio - bearish_ratio) / 2) * amp, 1)

                guba_sentiment = {
                    'total_posts': total_posts,
                    'active_users': max(int(total_posts * 0.3), 50),
                    'bullish_ratio': bullish_ratio,
                    'bearish_ratio': bearish_ratio,
                    'neutral_ratio': neutral_ratio,
                    'hot_keywords': [],
                    'sentiment_score': sentiment_score,
                    'confidence': round((effective_posts / total_posts) * 100, 1) if total_posts > 0 else 0.0,
                    'overall': '强烈看多' if bullish_ratio > 60 else (
                        '偏多' if bullish_ratio > 50 else ('偏空' if bearish_ratio > 50 else '中性'))
                }

                return guba_sentiment

        except Exception as e:
            print(f"⚠️ API获取股吧情绪失败: {str(e)}")

        return self._get_default_guba_sentiment()

    def get_institutional_activity(self):
        """
        获取机构活动数据 - 已移除(股民情绪只关注评论)

        Returns:
            dict: 机构活动数据
        """
        # 根据用户要求,股民情绪分析只需要展示评论情绪
        # 机构活动数据已移除
        return self._get_default_institutional_activity()

    def _classify_capital_strength(self, inflow_rate, inflow_amount=None):
        """分类资金流向强度"""
        # 优先使用流入率判断
        if inflow_rate and abs(inflow_rate) > 0.1: # 简单的非零检查
            if abs(inflow_rate) > 10:
                return '强'
            elif abs(inflow_rate) > 5:
                return '中'
            else:
                return '弱'
        
        # 如果流入率不可用，使用绝对金额判断 (单位: 元)
        if inflow_amount is not None:
            amount_abs = abs(inflow_amount)
            if amount_abs > 100_000_000: # 1亿
                return '强'
            elif amount_abs > 30_000_000: # 3000万
                return '中'
            else:
                return '弱'
                
        return '弱'

    def get_comprehensive_sentiment(self, verbose: bool = True):
        """
        获取综合情绪分析 - 专注于评论情绪分析

        Returns:
            dict: 综合情绪数据
        """
        if verbose:
            print(f"😊 正在分析 {self.stock_code} 的股民评论情绪...")

        # 获取股吧评论情绪数据
        guba_sentiment = self.get_guba_sentiment()

        # 获取大盘整体情绪与所属板块情绪
        try:
            overall_market_sentiment = self.get_overall_market_sentiment()
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取大盘情绪失败，使用默认值: {str(e)}")
            overall_market_sentiment = self._get_default_overall_market_sentiment()

        try:
            sector_sentiment = self.get_sector_info_and_sentiment()
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取板块情绪失败，使用默认值: {str(e)}")
            sector_sentiment = self._get_default_sector_sentiment()

        data = {
            'stock_code': self.stock_code,
            'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'guba_sentiment': guba_sentiment,
            'overall_market_sentiment': overall_market_sentiment,
            'sector_sentiment': sector_sentiment,
        }

        # 综合情绪评分基于股吧评论情绪
        sentiment_score = guba_sentiment['sentiment_score']

        # 资金流与龙虎榜加分（轻权重）
        bonus_points = 0.0
        bonus_reasons = []

        # 主力资金流向
        try:
            capital_flow = self.get_capital_flow()
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取资金流向失败，使用默认值: {str(e)}")
            capital_flow = self._get_default_capital_flow()

        data['capital_flow'] = capital_flow

        try:
            inflow = capital_flow.get('main_inflow', 0) or 0
            inflow_rate = capital_flow.get('main_inflow_rate', 0) or 0
            trend = capital_flow.get('trend', '未知')
            strength = capital_flow.get('strength', '未知')

            # 加分策略：流入为正，按强度微调（上限+4）
            if inflow > 0:
                if strength == '强':
                    bonus_points += 4
                    bonus_reasons.append('主力资金强力净流入 +4')
                elif strength == '中':
                    bonus_points += 2.5
                    bonus_reasons.append('主力资金净流入(中) +2.5')
                elif strength == '弱':
                    bonus_points += 1
                    bonus_reasons.append('主力资金净流入(弱) +1')
            elif inflow < 0:
                # 负流出轻微扣分（下限-3）
                if strength == '强':
                    bonus_points -= 3
                    bonus_reasons.append('主力资金强力净流出 -3')
                elif strength == '中':
                    bonus_points -= 2
                    bonus_reasons.append('主力资金净流出(中) -2')
                elif strength == '弱':
                    bonus_points -= 1
                    bonus_reasons.append('主力资金净流出(弱) -1')
        except Exception:
            pass

        # 龙虎榜信号
        try:
            dragon_tiger = self.get_dragon_tiger_list(limit=10)
        except Exception as e:
            if verbose:
                print(f"   ⚠️  获取龙虎榜失败，使用默认值: {str(e)}")
            dragon_tiger = self._get_default_dragon_tiger()

        data['dragon_tiger'] = dragon_tiger

        try:
            if dragon_tiger.get('has_records'):
                last_signal = dragon_tiger.get('last_signal', '中性')
                if last_signal == '正面':
                    bonus_points += 3
                    bonus_reasons.append('近期龙虎榜净买入 +3')
                elif last_signal == '负面':
                    bonus_points -= 3
                    bonus_reasons.append('近期龙虎榜净卖出 -3')
        except Exception:
            pass

        # 汇总加分（控制范围）
        sentiment_score_adj = max(0, min(100, round(sentiment_score + bonus_points, 1)))
        data['comprehensive_score'] = sentiment_score_adj
        if bonus_reasons:
            data['bonus_reasons'] = bonus_reasons

        # 综合情绪判断
        if data['comprehensive_score'] >= 70:
            data['comprehensive_sentiment'] = '强烈看多'
        elif data['comprehensive_score'] >= 55:
            data['comprehensive_sentiment'] = '偏多'
        elif data['comprehensive_score'] >= 45:
            data['comprehensive_sentiment'] = '中性'
        elif data['comprehensive_score'] >= 30:
            data['comprehensive_sentiment'] = '偏空'
        else:
            data['comprehensive_sentiment'] = '强烈看空'

        if verbose:
            print(f"✅ 情绪分析完成")
            print(f"   - 综合情绪: {data['comprehensive_sentiment']} ({data['comprehensive_score']}分)")
            print(f"   - 股吧评论: {data['guba_sentiment']['overall']}")
            print(f"   - 看多比例: {data['guba_sentiment']['bullish_ratio']}%")
            print(f"   - 看空比例: {data['guba_sentiment']['bearish_ratio']}%")
            # 额外输出市场与板块情绪摘要
            try:
                om = data['overall_market_sentiment']
                primary_name = om.get('primary_index', {}).get('name', '所属大盘')
                primary_chg = om.get('primary_change_pct', 'N/A')
                print(f"   - 大盘情绪: {om.get('overall', 'N/A')} 所属大盘: {primary_name} 涨跌: {primary_chg}%")
            except Exception:
                pass
            try:
                sector_info = data['sector_sentiment']
                if isinstance(sector_info, dict) and 'sector_sentiment' in sector_info:
                    # 新的数据结构：有嵌套的sector_sentiment
                    inner_sector = sector_info['sector_sentiment']
                    sector_name = sector_info.get('sector_name', 'N/A')
                    overall = inner_sector.get('overall', 'N/A')
                    change_pct = inner_sector.get('change_pct', 'N/A')
                    print(f"   - 板块情绪: {overall} ({sector_name}) 涨跌: {change_pct}%")
                else:
                    # 旧的数据结构：直接访问
                    sector_name = sector_info.get('sector_name', 'N/A')
                    overall = sector_info.get('overall', 'N/A')
                    change_pct = sector_info.get('change_pct', 'N/A')
                    print(f"   - 板块情绪: {overall} ({sector_name}) 涨跌: {change_pct}%")
            except Exception as e:
                print(f"   - 板块情绪: 获取失败 - {str(e)}")
                pass
            try:
                cf = data.get('capital_flow', {})
                dt = data.get('dragon_tiger', {})
                if cf:
                    print(f"   - 资金流向: {cf.get('trend','未知')}({cf.get('strength','未知')}) 主力净流入率: {cf.get('main_inflow_rate', 0)}%")
                if dt and dt.get('has_records'):
                    print(f"   - 龙虎榜: {dt.get('last_signal','中性')}({dt.get('last_date','N/A')}) 原因: {dt.get('last_reason','N/A')}")
            except Exception:
                pass

        return data

    def _get_default_dragon_tiger(self):
        """返回默认龙虎榜数据"""
        return {
            'has_records': False,
            'last_date': 'N/A',
            'last_reason': 'N/A',
            'last_signal': '中性',
            'last_strength_ratio': None,
            'recent_positive': 0,
            'recent_negative': 0,
            'records': []
        }

    def _get_default_capital_flow(self):
        """返回默认资金流向数据"""
        return {
            'date': 'N/A',
            'main_inflow': 0,
            'retail_inflow': 0,
            'main_inflow_rate': 0,
            'super_large_inflow': 0,
            'large_inflow': 0,
            'medium_inflow': 0,
            'small_inflow': 0,
            'trend': '未知',
            'strength': '未知',
        }

    def _get_default_market_sentiment(self):
        """返回默认市场情绪数据"""
        return {
            'turnover_rate': 'N/A',
            'volume_ratio': 'N/A',
            'amplitude': 'N/A',
            'up_down_ratio': 'N/A',
            'market_cap_rank': 'N/A',
            'turnover_emotion': '未知',
        }

    def _get_default_overall_market_sentiment(self):
        """返回默认大盘整体情绪数据"""
        return {
            'indices': {},
            'sentiment_score': 50,
            'overall': '数据不足',
            'emotion': 'neutral',
            'primary_index': {
                'key': 'sz399001',
                'name': '所属大盘',
                'change_pct': 'N/A',
            },
            'primary_change_pct': 'N/A',
            'avg_change_pct': 'N/A',
        }

    def _get_sector_info_fallback(self):
        """
        备用方案：从其他数据源获取板块信息
        
        Returns:
            dict: 板块信息和情绪数据
        """
        try:
            # 尝试从新浪财经获取股票基本信息
            sina_url = f"http://hq.sinajs.cn/list={self.stock_code}"
            
            response = requests.get(sina_url, headers=self.headers, timeout=10)
            if response.status_code == 200 and response.text:
                # 解析新浪财经数据
                content = response.text.strip()
                if 'var hq_str_' in content:
                    data_part = content.split('="')[1].split('";')[0]
                    fields = data_part.split(',')
                    
                    if len(fields) > 10:
                        stock_name = fields[0]
                        # 不再使用硬编码推断，直接返回综合
                        sector_name = '综合'
                        
                        print(f"   📊 从新浪财经获取股票信息: {stock_name}")
                        print(f"   🏢 备用板块分类: {sector_name}")
                        
                        return {
                            'sector_name': sector_name,
                            'sector_sentiment': {
                                'sector_name': sector_name,
                                'sector_code': 'N/A',
                                'change_pct': 'N/A',
                                'turnover_rate': 'N/A',
                                'sentiment_score': 50,
                                'overall': '数据来源受限',
                                'emotion': 'neutral'
                            }
                        }
            
        except Exception as e:
            print(f"   ⚠️  备用方案也失败: {str(e)}")
        
        # 最终回退到默认值
        print(f"   ⚠️  获取股票板块信息失败，使用大盘情绪兜底")
        
        # 尝试获取大盘情绪作为参考
        market_sentiment = self.get_overall_market_sentiment()
        
        return {
            'sector_name': '综合行业',
            'sector_sentiment': {
                'sector_name': '综合行业',
                'sector_code': '000000',
                'change_pct': market_sentiment.get('avg_change_pct', 0),
                'turnover_rate': 'N/A',
                'sentiment_score': market_sentiment.get('sentiment_score', 50),
                'overall': market_sentiment.get('overall', '中性'),
                'emotion': market_sentiment.get('emotion', 'neutral')
            },
            'stock_name': '未知',
            'current_price': 0,
            'industry': '综合',
            'concept_sectors': [],
            'data_source': 'market_fallback'
        }
    
    def _infer_sector_from_name(self, stock_name):
        """
        根据股票名称推断可能的行业
        
        Args:
            stock_name: 股票名称
            
        Returns:
            str: 推断的行业名称
        """
        # 移除硬编码的行业关键词映射，直接返回综合
        # 现在使用真实的API获取板块信息，不再依赖关键词匹配
        return '综合'
    
    def _calculate_sentiment_from_change(self, change_pct_str):
        """
        根据涨跌幅计算情绪评分
        
        Args:
            change_pct_str: 涨跌幅字符串
            
        Returns:
            int: 情绪评分 (0-100)
        """
        try:
            change_pct = float(change_pct_str)
            
            # 基于涨跌幅计算情绪评分
            if change_pct >= 5:
                return 90
            elif change_pct >= 2:
                return 75
            elif change_pct >= 0:
                return 60
            elif change_pct >= -2:
                return 40
            elif change_pct >= -5:
                return 25
            else:
                return 10
                
        except (ValueError, TypeError):
            return 50
    
    def _get_sentiment_description(self, score):
        """
        根据评分获取情绪描述
        
        Args:
            score: 情绪评分
            
        Returns:
            str: 情绪描述
        """
        if score >= 80:
            return "市场热情高涨"
        elif score >= 60:
            return "市场情绪积极"
        elif score >= 40:
            return "市场情绪平稳"
        elif score >= 20:
            return "市场情绪谨慎"
        else:
            return "市场情绪低迷"
    
    def _get_emotion_from_score(self, score):
        """
        根据评分获取情绪标签
        
        Args:
            score: 情绪评分
            
        Returns:
            str: 情绪标签
        """
        if score >= 70:
            return "positive"
        elif score >= 30:
            return "neutral"
        else:
            return "negative"
    
    def _get_default_sector_sentiment(self):
        """返回默认板块情绪数据"""
        return {
            'sector_name': 'N/A',
            'sector_code': 'N/A',
            'change_pct': 'N/A',
            'turnover_rate': 'N/A',
            'sentiment_score': 50,
            'overall': '数据不足',
            'emotion': 'neutral',
        }

    def _get_default_guba_sentiment(self):
        """返回默认股吧情绪数据"""
        return {
            'total_posts': 0,
            'active_users': 0,
            'bullish_ratio': 0.0,  # 修复显示为0.0%的问题
            'bearish_ratio': 0.0,
            'neutral_ratio': 100.0,
            'hot_keywords': [],
            'sentiment_score': 50,
            'overall': '中性',
        }

    def _get_default_institutional_activity(self):
        """返回默认机构活动数据"""
        return {
            'recent_research': 0,
            'institutional_buyers': 0,
            'institutional_sellers': 0,
            'net_institutional_buy': 0,
            'activity_level': '未知',
            'last_research_date': 'N/A',
        }


if __name__ == "__main__":
    # 测试代码
    analyzer = InvestorSentimentAnalyzer("688343")
    data = analyzer.get_comprehensive_sentiment()

    print("\n" + "=" * 60)
    print("股民情绪分析结果:")
    print("=" * 60)

    import json

    print(json.dumps(data, indent=2, ensure_ascii=False))
