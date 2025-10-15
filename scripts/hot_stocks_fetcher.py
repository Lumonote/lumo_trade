#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
热门股票获取器
从多个数据源获取市场热度TOP100的股票
"""

import requests
import pandas as pd
from typing import List, Dict, Optional
import time
import json
import os
import asyncio
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HotStocksFetcher:
    """热门股票获取器 - 从多个数据源获取市场热度TOP股票"""

    def __init__(self, cache_dir: str = None):
        """
        初始化热门股票获取器

        Args:
            cache_dir: 缓存目录路径（可选）。
                      若未提供，将优先使用环境变量 KRONOS_DATA_DIR 下的 cache 目录，
                      否则回退到项目相对路径 data/cache。
        """
        # 优先使用用户数据目录，适配打包环境的写权限
        if cache_dir is None:
            base_data_dir = os.environ.get("KRONOS_DATA_DIR") or os.path.join(os.getcwd(), "data")
            cache_dir = os.path.join(base_data_dir, "cache")

        self.cache_dir = cache_dir
        try:
            os.makedirs(cache_dir, exist_ok=True)
        except Exception as e:
            # 在极端情况下（目录不可写）回退到用户家目录临时缓存
            fallback_dir = os.path.join(os.path.expanduser("~"), "Kronos", "cache")
            try:
                os.makedirs(fallback_dir, exist_ok=True)
                self.cache_dir = fallback_dir
                logger.warning(f"缓存目录不可写，回退到: {fallback_dir} (原因: {e})")
            except Exception:
                # 最后回退到系统临时目录
                import tempfile
                self.cache_dir = tempfile.mkdtemp(prefix="kronos_cache_")
                logger.warning(f"缓存目录不可写，回退到临时目录: {self.cache_dir}")

        self.cache_file = os.path.join(cache_dir, "hot_stocks_cache.json")
        self.cache_ttl = 3600  # 缓存1小时

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://quote.eastmoney.com/',
        }

        # 浏览器采集支持（用于同花顺反爬场景）
        try:
            from scripts.browser_manager import BrowserManager  # 延迟导入以避免未安装Playwright时失败
            self._BrowserManager = BrowserManager
        except Exception:
            self._BrowserManager = None

    def get_hot_stocks(self, limit: int = 100, force_refresh: bool = False) -> List[Dict]:
        """
        获取热门股票TOP100

        Args:
            limit: 返回股票数量，默认100
            force_refresh: 是否忽略缓存，强制直接采集（默认否）

        Returns:
            list: [{
                'code': '688401',
                'name': '金山云',
                'exchange': 'SH',  # SH或SZ
                'popularity_score': 95.5,  # 综合热度评分
                'change_pct': 3.2,  # 涨跌幅%
                'turnover_rate': 8.5,  # 换手率%
                'volume': 1234567,  # 成交量
                'amount': 1234567890.0,  # 成交额
                'latest_price': 123.45,  # 最新价
                'source': 'eastmoney'  # 数据来源
            }, ...]
        """
        logger.info(f"开始获取热门股票 TOP{limit}")

        # 环境变量可强制刷新
        env_force = os.environ.get('KRONOS_FORCE_REFRESH') == '1'

        # 检查缓存（可被强制刷新禁用）
        cached_data = None if (force_refresh or env_force) else self._load_cache()
        if cached_data:
            stocks_from_cache = cached_data.get('stocks') or []
            # 若缓存来源为本地回退或未知来源，则忽略缓存
            valid_sources = {'eastmoney', 'tonghuashun', 'xueqiu', 'tushare'}
            all_sources = {str(s.get('source') or '').lower() for s in stocks_from_cache}
            if all_sources and all_sources.issubset(valid_sources):
                logger.info(f"使用缓存数据（缓存时间: {cached_data['timestamp']}）")
                return stocks_from_cache[:limit]
            else:
                logger.info("检测到缓存来源非直接采集（可能为fallback/未知），忽略缓存，改为直接采集")

        # 尝试从多个数据源获取
        stocks = []

        # 1. 尝试东方财富热度榜
        try:
            logger.info("正在从东方财富获取热度榜...")
            eastmoney_stocks = self._fetch_from_eastmoney()
            if eastmoney_stocks:
                stocks.extend(eastmoney_stocks)
                logger.info(f"✓ 东方财富获取成功: {len(eastmoney_stocks)} 只股票")
        except Exception as e:
            logger.warning(f"东方财富获取失败: {e}")

        # 2. 尝试同花顺热度榜（备用）
        if len(stocks) < limit:
            try:
                logger.info("正在从同花顺获取热度榜...")
                tonghuashun_stocks = self._fetch_from_tonghuashun()
                if tonghuashun_stocks:
                    stocks.extend(tonghuashun_stocks)
                    logger.info(f"✓ 同花顺获取成功: {len(tonghuashun_stocks)} 只股票")
            except Exception as e:
                logger.warning(f"同花顺获取失败: {e}")

        # 去重并排序
        stocks = self._deduplicate_and_sort(stocks)

        if not stocks:
            logger.error("所有数据源均获取失败，返回空列表（不使用本地回退）")
            return []

        # 缓存数据
        self._save_cache(stocks)

        logger.info(f"✓ 热门股票获取完成: {len(stocks)} 只股票")
        return stocks[:limit]

    

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """
        从东方财富获取热度榜

        API说明:
        - 排序字段 TRADE: 成交额
        - 排序字段 TURNOVERRATE: 换手率
        - 排序字段 CHANGEPERCENT: 涨跌幅
        """
        stocks = []

        # 东方财富行情中心 - 人气榜API
        url = "https://push2.eastmoney.com/api/qt/clist/get"

        params = {
            'pn': '1',  # 页码
            'pz': '100',  # 每页数量
            'po': '1',  # 排序方式
            'np': '1',  # 不分页
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',  # 排序字段ID (f3=涨跌幅)
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # 市场筛选：A股
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f22,f11,f62,f128,f136,f115,f152',
            '_': str(int(time.time() * 1000))
        }

        try:
            response = requests.get(url, params=params, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('data') and data['data'].get('diff'):
                for item in data['data']['diff']:
                    try:
                        # 解析股票信息
                        code = item.get('f12', '')  # 股票代码
                        name = item.get('f14', '')  # 股票名称
                        market = item.get('f13', '')  # 市场代码 (0=深市, 1=沪市)

                        # 确定交易所
                        exchange = 'SZ' if market == '0' else 'SH' if market == '1' else 'UNKNOWN'

                        # 计算综合热度评分（基于多个维度）
                        change_pct = float(item.get('f3', 0)) if item.get('f3') else 0  # 涨跌幅
                        turnover_rate = float(item.get('f8', 0)) if item.get('f8') else 0  # 换手率
                        volume = float(item.get('f5', 0)) if item.get('f5') else 0  # 成交量（手）
                        amount = float(item.get('f6', 0)) if item.get('f6') else 0  # 成交额（元）

                        # 综合热度评分算法（0-100分）
                        # 权重: 成交额40% + 换手率30% + 涨跌幅20% + 成交量10%
                        popularity_score = self._calculate_popularity_score(
                            amount=amount,
                            turnover_rate=turnover_rate,
                            change_pct=change_pct,
                            volume=volume
                        )

                        stock_info = {
                            'code': code,
                            'name': name,
                            'exchange': exchange,
                            'popularity_score': round(popularity_score, 2),
                            'change_pct': round(change_pct, 2),
                            'turnover_rate': round(turnover_rate, 2),
                            'volume': int(volume * 100),  # 手转换为股
                            'amount': round(amount, 2),
                            'latest_price': float(item.get('f2', 0)) if item.get('f2') else 0,  # 最新价
                            'source': 'eastmoney'
                        }

                        stocks.append(stock_info)
                    except Exception as e:
                        logger.debug(f"解析股票信息失败: {e}")
                        continue

            return stocks

        except Exception as e:
            logger.error(f"东方财富API请求失败: {e}")
            raise

    def _fetch_from_tonghuashun(self) -> List[Dict]:
        """
        从同花顺获取热度榜

        注意: 同花顺需要更复杂的反爬处理，这里提供基础实现
        """
        stocks = []

        # 同花顺成交额榜（热门维度之一），采用Ajax端点
        url = "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/ajax/1/"

        headers = {
            **self.headers,
            'Referer': 'https://data.10jqka.com.cn/',
            'Host': 'data.10jqka.com.cn',
            'X-Requested-With': 'XMLHttpRequest'
        }

        try:
            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()

            html = response.text
            parsed = self._parse_tonghuashun_table(html)
            if parsed:
                stocks.extend(parsed[:100])
                return stocks
            else:
                logger.warning("同花顺HTML解析为空，尝试使用浏览器采集")
                browser_result = self._fetch_tonghuashun_via_browser(limit=100)
                stocks.extend(browser_result)
                return stocks

        except Exception as e:
            logger.warning(f"同花顺请求失败或被拦截 ({e})，尝试浏览器采集")
            browser_result = self._fetch_tonghuashun_via_browser(limit=100)
            stocks.extend(browser_result)
            return stocks

    def _parse_tonghuashun_table(self, html: str) -> List[Dict]:
        """解析同花顺排行榜HTML片段为股票列表"""
        try:
            import re
            pattern = r'<td>(\d{6})</td><td[^>]*>([^<]+)</td><td[^>]*>([^<]+)</td>'
            matches = re.findall(pattern, html)
            result: List[Dict] = []
            for code, name, price in matches:
                exchange = 'SH' if code.startswith('6') else 'SZ'
                result.append({
                    'code': code,
                    'name': name,
                    'exchange': exchange,
                    'popularity_score': 50.0,
                    'change_pct': 0.0,
                    'turnover_rate': 0.0,
                    'volume': 0,
                    'amount': 0.0,
                    'latest_price': float(price) if price else 0.0,
                    'source': 'tonghuashun'
                })
            return result
        except Exception as parse_err:
            logger.debug(f"同花顺HTML解析异常: {parse_err}")
            return []

    def _fetch_tonghuashun_via_browser(self, limit: int = 100) -> List[Dict]:
        """使用浏览器采集同花顺排行榜，绕过反爬与鉴权"""
        if self._BrowserManager is None:
            logger.error("浏览器管理器不可用，无法进行浏览器采集")
            return []

        try:
            return asyncio.run(self._fetch_tonghuashun_via_browser_async(limit))
        except RuntimeError:
            # 如果已有事件循环在运行，使用新循环
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(self._fetch_tonghuashun_via_browser_async(limit))
            finally:
                loop.close()

    async def _fetch_tonghuashun_via_browser_async(self, limit: int = 100) -> List[Dict]:
        url = "https://data.10jqka.com.cn/rank/cjl/board/all/field/amount/order/desc/page/1/ajax/1/"
        extra_headers = {
            **self.headers,
            'Referer': 'https://data.10jqka.com.cn/',
            'Host': 'data.10jqka.com.cn',
            'X-Requested-With': 'XMLHttpRequest',
            'Cache-Control': 'no-cache'
        }
        stocks: List[Dict] = []

        try:
            async with self._BrowserManager() as manager:
                async with manager.get_page() as page:
                    await page.set_extra_http_headers(extra_headers)
                    resp = await page.goto(url, wait_until='networkidle', timeout=15000)
                    if not resp or resp.status != 200:
                        logger.warning(f"同花顺浏览器请求失败，状态码: {resp.status if resp else 'None'}")
                        return []
                    html = await page.content()
                    parsed = self._parse_tonghuashun_table(html)
                    stocks.extend(parsed[:limit])
        except Exception as e:
            logger.error(f"同花顺浏览器采集异常: {e}")
            return []

        return stocks

    def _calculate_popularity_score(self, amount: float, turnover_rate: float,
                                   change_pct: float, volume: float) -> float:
        """
        计算综合热度评分（0-100分）

        评分维度:
        1. 成交额 (40%) - 反映市场关注度
        2. 换手率 (30%) - 反映交易活跃度
        3. 涨跌幅 (20%) - 反映市场情绪
        4. 成交量 (10%) - 反映参与度

        Args:
            amount: 成交额（元）
            turnover_rate: 换手率(%)
            change_pct: 涨跌幅(%)
            volume: 成交量（股）
        """
        # 归一化处理（使用对数缩放）
        import math

        # 成交额评分（亿为单位，对数缩放到0-100）
        amount_score = min(100, (math.log10(amount / 1e8 + 1) / math.log10(1000)) * 100) if amount > 0 else 0

        # 换手率评分（超过20%为满分）
        turnover_score = min(100, (turnover_rate / 20) * 100)

        # 涨跌幅评分（绝对值，-10%到+10%映射到0-100）
        change_score = min(100, (abs(change_pct) / 10) * 100)

        # 成交量评分（百万股为单位，对数缩放）
        volume_score = min(100, (math.log10(volume / 1e6 + 1) / math.log10(1000)) * 100) if volume > 0 else 0

        # 加权计算综合得分
        total_score = (
            amount_score * 0.4 +
            turnover_score * 0.3 +
            change_score * 0.2 +
            volume_score * 0.1
        )

        return total_score

    def _deduplicate_and_sort(self, stocks: List[Dict]) -> List[Dict]:
        """
        去重并按热度评分排序

        Args:
            stocks: 股票列表

        Returns:
            去重排序后的股票列表
        """
        # 使用字典去重（以股票代码为key）
        unique_stocks = {}
        for stock in stocks:
            code = stock['code']
            if code not in unique_stocks:
                unique_stocks[code] = stock
            else:
                # 如果已存在，保留热度更高的
                if stock['popularity_score'] > unique_stocks[code]['popularity_score']:
                    unique_stocks[code] = stock

        # 转换为列表并按热度评分降序排序
        sorted_stocks = sorted(
            unique_stocks.values(),
            key=lambda x: x['popularity_score'],
            reverse=True
        )

        return sorted_stocks

    def _load_cache(self) -> Optional[Dict]:
        """
        加载缓存数据

        Returns:
            缓存数据或None（如果缓存无效）
        """
        if not os.path.exists(self.cache_file):
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 检查缓存是否过期
            cache_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cache_time > timedelta(seconds=self.cache_ttl):
                logger.info("缓存已过期")
                return None

            return cache_data

        except Exception as e:
            logger.warning(f"加载缓存失败: {e}")
            return None

    def _save_cache(self, stocks: List[Dict]):
        """
        保存缓存数据

        Args:
            stocks: 股票列表
        """
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'stocks': stocks
            }

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

            logger.info(f"缓存已保存: {self.cache_file}")

        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")


def main():
    """测试热门股票获取器"""
    print("=" * 60)
    print("热门股票获取器 - 测试")
    print("=" * 60)

    fetcher = HotStocksFetcher()

    # 获取TOP 100热门股票
    hot_stocks = fetcher.get_hot_stocks(limit=100)

    if hot_stocks:
        print(f"\n✓ 成功获取 {len(hot_stocks)} 只热门股票\n")

        # 显示TOP 10
        print("TOP 10 热门股票:")
        print("-" * 100)
        print(f"{'排名':<6} {'代码':<10} {'名称':<15} {'交易所':<8} {'热度':<8} {'涨跌幅%':<10} {'换手率%':<10} {'成交额(亿)':<15}")
        print("-" * 100)

        for i, stock in enumerate(hot_stocks[:10], 1):
            amount_yi = stock['amount'] / 1e8  # 转换为亿
            print(f"{i:<6} {stock['code']:<10} {stock['name']:<15} {stock['exchange']:<8} "
                  f"{stock['popularity_score']:<8.2f} {stock['change_pct']:<10.2f} "
                  f"{stock['turnover_rate']:<10.2f} {amount_yi:<15.2f}")

        # 保存到CSV
        df = pd.DataFrame(hot_stocks)
        output_file = "data/hot_stocks_top100.csv"
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n✓ 数据已保存到: {output_file}")
    else:
        print("\n✗ 获取失败")


if __name__ == "__main__":
    main()
