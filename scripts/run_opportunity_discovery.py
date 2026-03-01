#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘 - 主程序
整合热门股票获取、多维度打分、漏斗筛选、报表生成
"""

import os
import sys
import argparse
import logging
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
import time
import requests
from requests.adapters import HTTPAdapter  # 【优化1】连接池管理

# 【优化6】Rich进度条支持（可选，未安装时降级到文本输出）
try:
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# 添加项目根目录到路径 - 优先使用环境变量，否则使用当前工作目录
project_root = os.environ.get('KRONOS_PROJECT_ROOT', os.getcwd())
sys.path.insert(0, project_root)
# 也添加脚本所在目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scripts.hot_stocks_fetcher import HotStocksFetcher
from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter
from scripts.opportunity_report_generator import OpportunityReportGenerator
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.global_hot_news_collector import GlobalHotNewsCollector
from analysis.sector_hot_news_collector import SectorNewsCollector
from analysis.trending_topics_collector import TrendingTopicsCollector
from analysis.llm_service import LLMConfig, LLMAnalyzer
from analysis.technical_analysis import TechnicalAnalysis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class OpportunityDiscovery:
    """投资机会挖掘系统"""

    def __init__(self, max_workers: int = 10):
        """
        初始化投资机会挖掘系统

        Args:
            max_workers: 并发处理的最大线程数
        """
        # 【优化1】创建全局HTTP Session，复用连接
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        # 投资机会挖掘流程要求实时数据，禁用热门股票缓存
        self.hot_stocks_fetcher = HotStocksFetcher(disable_cache=True)
        self.scorer = OpportunityScorer()
        self.filter = OpportunityFilter()
        # 尊重打包环境的结果目录设置
        output_dir = os.environ.get('KRONOS_RESULTS_DIR', 'results')
        self.report_generator = OpportunityReportGenerator(output_dir=output_dir)
        self.hot_news_collector = GlobalHotNewsCollector()
        self.sector_news_collector = SectorNewsCollector()
        self.topics_collector = TrendingTopicsCollector()
        self.global_hot_news = []
        self.sector_hot_news = []
        self.max_workers = max_workers

    def _load_tushare_token(self) -> str:
        config_path = os.path.join(project_root, 'config', 'tushare_config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get('tushare', {}).get('token', '')
        except Exception as e:
            logger.warning(f"加载Tushare配置失败: {e}")
            return ''

    def _resolve_latest_trade_date(self, pro, base_dt: datetime, max_back_days: int = 14) -> str:
        base_str = base_dt.strftime('%Y%m%d')
        try:
            start_str = (base_dt - timedelta(days=30)).strftime('%Y%m%d')
            cal_df = pro.trade_cal(exchange='SSE', start_date=start_str, end_date=base_str, fields='cal_date,is_open')
            if cal_df is not None and not cal_df.empty and 'is_open' in cal_df.columns and 'cal_date' in cal_df.columns:
                cal_df = cal_df.sort_values('cal_date')
                open_dates = cal_df.loc[cal_df['is_open'] == 1, 'cal_date'].tolist()
                if open_dates:
                    return open_dates[-1]
        except Exception as e:
            logger.debug(f"trade_cal不可用，回退使用日期回溯: {e}")

        candidate = base_dt
        for _ in range(max_back_days):
            if candidate.weekday() < 5:
                return candidate.strftime('%Y%m%d')
            candidate -= timedelta(days=1)
        return base_str

    def _fetch_moneyflow_dc_stocks(self, limit: int) -> List[Dict]:
        try:
            import tushare as ts
        except ImportError:
            logger.warning("Tushare未安装，无法获取资金流向榜单")
            return []

        token = self._load_tushare_token()
        if not token:
            logger.warning("Tushare Token未配置，无法获取资金流向榜单")
            return []

        try:
            pro = ts.pro_api(token)
        except Exception as e:
            logger.warning(f"初始化Tushare失败: {e}")
            return []

        max_back_days = 14
        trade_date = self._resolve_latest_trade_date(pro, datetime.now(), max_back_days=max_back_days)

        last_error: Optional[Exception] = None
        df = None
        selected_date = trade_date
        for i in range(max_back_days):
            try_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=i)).strftime('%Y%m%d')
            try:
                if hasattr(pro, 'moneyflow_dc'):
                    df = pro.moneyflow_dc(trade_date=try_date)
                else:
                    df = pro.moneyflow_ths(trade_date=try_date)
                if df is not None and not df.empty:
                    selected_date = try_date
                    break
            except Exception as e:
                last_error = e

        if df is None or df.empty:
            if last_error:
                logger.warning(f"资金流向榜单获取失败: {last_error}")
            return []

        try:
            import pandas as pd
        except ImportError:
            pd = None

        sort_cols = [
            'net_amount_rate',
            'net_mf_amount_rate',
            'buy_lg_amount_rate',
            'buy_elg_amount_rate',
            'net_amount',
            'net_mf_amount',
            'net_amount_main',
        ]
        sort_col = next((c for c in sort_cols if c in df.columns), None)
        if sort_col is None:
            sort_col = df.columns[0]

        if pd is not None:
            df['_sort_value'] = pd.to_numeric(df.get(sort_col), errors='coerce').fillna(0.0)
            df = df.sort_values('_sort_value', ascending=False)
        else:
            df = df.sort_values(by=sort_col, ascending=False)

        top_df = df.head(limit).copy()
        top_df['_amount_unit'] = '万元'

        data_dir = os.path.join(project_root, 'data')
        os.makedirs(data_dir, exist_ok=True)
        csv_path = os.path.join(data_dir, f"moneyflow_dc_{selected_date}_top{min(limit, len(top_df))}.csv")
        try:
            top_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            logger.info(f"✓ 资金流向榜单CSV已保存: {csv_path}")
        except Exception as e:
            logger.warning(f"保存资金流向CSV失败: {e}")

        def map_exchange(ts_code: str) -> str:
            if ts_code.endswith('.SZ'):
                return 'SZ'
            if ts_code.endswith('.SH'):
                return 'SH'
            if ts_code.endswith('.BJ'):
                return 'BJ'
            return 'UNKNOWN'

        results: List[Dict] = []
        sort_unit = '%' if str(sort_col).endswith('_rate') else '万元'
        for idx, (_, row) in enumerate(top_df.iterrows(), start=1):
            ts_code = str(row.get('ts_code', '') or '')
            code = ts_code.split('.')[0] if ts_code else str(row.get('code', '') or '')
            name = str(row.get('name', '') or '')
            sort_value = row.get('_sort_value', row.get(sort_col, 0))
            sort_value_float = float(sort_value) if isinstance(sort_value, (int, float)) else None
            results.append({
                'code': code,
                'name': name,
                'exchange': map_exchange(ts_code),
                'rank': idx,
                'source': 'tushare_moneyflow_dc',
                'trade_date': selected_date,
                'moneyflow_sort_field': sort_col,
                'moneyflow_sort_value': sort_value_float if sort_value_float is not None else sort_value,
                'moneyflow_sort_unit': sort_unit,
                'moneyflow_sort_value_wan': sort_value_float if (sort_unit == '万元' and sort_value_float is not None) else None,
                'moneyflow_sort_value_yuan': (sort_value_float * 10000.0) if (sort_unit == '万元' and sort_value_float is not None) else None,
                'popularity_score': max(0, 100 - idx + 1)
            })

        logger.info(f"✓ 获取资金流向榜单成功，日期: {selected_date}，共{len(results)}只股票")
        return results

    def run(self, limit: int = 100, test_codes: List[str] = None, source: str = 'heat') -> str:
        """
        运行完整的投资机会挖掘流程

        Args:
            limit: 获取热门股票的数量（默认100）
            test_codes: 指定测试的股票代码列表

        Returns:
            生成的报表文件路径
        """
        logger.info("=" * 60)
        logger.info("🎯 投资机会挖掘系统启动")
        logger.info("=" * 60)

        start_time = datetime.now()

        # 步骤1: 获取热门股票 TOP 100 与全市场热门新闻TOP10
        if test_codes:
            logger.info(f"\n步骤1: 使用测试股票代码: {test_codes}")
            hot_stocks = []
            for code in test_codes:
                # 简单构造股票信息
                hot_stocks.append({
                    'code': code,
                    'name': '测试股票', # 名称稍后会在分析中更新
                    'price': 0,
                    'change_pct': 0
                })
        else:
            if source == 'moneyflow_dc':
                logger.info(f"\n步骤1: 正在获取资金流向榜单 TOP {limit}...")
                hot_stocks = self._fetch_moneyflow_dc_stocks(limit=limit)
                if not hot_stocks:
                    logger.warning("资金流向榜单获取失败，回退使用热度榜")
                    logger.info(f"\n步骤1: 正在获取热门股票 TOP {limit}...")
                    hot_stocks = self.hot_stocks_fetcher.get_hot_stocks(limit=limit, force_refresh=True)
            else:
                logger.info(f"\n步骤1: 正在获取热门股票 TOP {limit}...")
                # 强制直接采集，避免使用缓存或本地回退
                hot_stocks = self.hot_stocks_fetcher.get_hot_stocks(limit=limit, force_refresh=True)

        if not hot_stocks:
            logger.error("✗ 获取热门股票失败，程序终止")
            return ""

        if source != 'moneyflow_dc':
            # 检查是否使用了 fallback 数据（静态备用数据，非实时热股）
            fallback_count = sum(1 for s in hot_stocks if s.get('source') == 'fallback')
            if fallback_count > 0:
                logger.warning(f"⚠️ 警告: 有 {fallback_count}/{len(hot_stocks)} 只股票来自备用数据源（非实时热股）")
                logger.warning("⚠️ 这表示所有实时数据源（东方财富/同花顺）获取失败，请检查网络连接")

        logger.info(f"✓ 成功获取 {len(hot_stocks)} 只热门股票")

        # 同步采集：全市场热门新闻TOP10
        try:
            logger.info("正在采集全市场热门新闻 TOP10（东方财富/同花顺/雪球）...")
            self.global_hot_news = self.hot_news_collector.get_top_news(limit=10)
            logger.info(f"✓ 成功采集 {len(self.global_hot_news)} 条热门新闻")
        except Exception as e:
            logger.warning(f"热门新闻采集失败: {e}")
            self.global_hot_news = []

        # 【优化2】步骤1.5: 预加载全局数据（大盘情绪、板块数据）
        logger.info(f"\n步骤1.5: 正在预加载全局数据（大盘情绪、板块数据）...")
        self._preload_global_data(hot_stocks)
        logger.info(f"✓ 全局数据预加载完成")

        # 步骤2: 多维度打分分析（并发处理）
        logger.info(f"\n步骤2: 正在进行多维度打分分析...")
        logger.info(f"并发线程数: {self.max_workers}")

        scored_stocks = []
        completed_count = 0
        total_count = len(hot_stocks)
        # 【修复】使用不同的变量名，避免覆盖全局start_time
        progress_start_time = time.time()

        # 【优化6】使用Rich进度条（如果可用）
        if RICH_AVAILABLE:
            console = Console()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("({task.completed}/{task.total})"),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=console,
                expand=True
            ) as progress:
                task = progress.add_task(
                    "[cyan]分析股票中...",
                    total=total_count
                )

                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_stock = {
                        executor.submit(self._analyze_single_stock, stock): stock
                        for stock in hot_stocks
                    }

                    for future in as_completed(future_to_stock):
                        stock = future_to_stock[future]
                        try:
                            result = future.result()
                            if result:
                                scored_stocks.append(result)
                            else:
                                scored_stocks.append({
                                    'stock_code': stock.get('code', ''),
                                    'name': stock.get('name', '未知'),
                                    'exchange': stock.get('exchange', 'UNKNOWN'),
                                    'popularity_score': stock.get('popularity_score', 0),
                                    'scoring_result': {
                                        'total_score': 0,
                                        'rating': 'C',
                                        'error': '分析失败'
                                    }
                                })
                        except Exception as e:
                            logger.error(f"分析 {stock.get('code')} 失败: {e}")
                            scored_stocks.append({
                                'stock_code': stock.get('code', ''),
                                'name': stock.get('name', '未知'),
                                'exchange': stock.get('exchange', 'UNKNOWN'),
                                'popularity_score': stock.get('popularity_score', 0),
                                'scoring_result': {
                                    'total_score': 0,
                                    'rating': 'C',
                                    'error': f'分析异常: {str(e)}'
                                }
                            })

                        completed_count += 1
                        progress.update(
                            task,
                            advance=1,
                            description=f"[cyan]分析: {stock.get('name', stock.get('code'))}"
                        )
        else:
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_stock = {
                    executor.submit(self._analyze_single_stock, stock): stock
                    for stock in hot_stocks
                }
                for future in as_completed(future_to_stock):
                    stock = future_to_stock[future]
                    try:
                        result = future.result()
                        if result:
                            scored_stocks.append(result)
                        else:
                            scored_stocks.append({
                                'stock_code': stock.get('code', ''),
                                'name': stock.get('name', '未知'),
                                'exchange': stock.get('exchange', 'UNKNOWN'),
                                'popularity_score': stock.get('popularity_score', 0),
                                'change_pct': stock.get('change_pct', 0),
                                'scoring_result': {
                                    'total_score': 0,
                                    'rating': 'C',
                                    'error': '分析失败'
                                }
                            })
                    except Exception as e:
                        logger.error(f"分析 {stock.get('code')} 失败: {e}")
                        scored_stocks.append({
                            'stock_code': stock.get('code', ''),
                            'name': stock.get('name', '未知'),
                            'exchange': stock.get('exchange', 'UNKNOWN'),
                            'popularity_score': stock.get('popularity_score', 0),
                            'change_pct': stock.get('change_pct', 0),
                            'scoring_result': {
                                'total_score': 0,
                                'rating': 'C',
                                'error': f'分析异常: {str(e)}'
                            }
                        })

                    completed_count += 1
                    progress = (completed_count / total_count) * 100
                    elapsed = time.time() - progress_start_time
                    avg_time = elapsed / completed_count if completed_count > 0 else 0
                    remaining = avg_time * (total_count - completed_count)
                    logger.info(
                        f"进度: {completed_count}/{total_count} ({progress:.1f}%) - "
                        f"{stock.get('name', stock.get('code'))} | "
                        f"已用: {elapsed:.1f}s | 预计剩余: {remaining:.1f}s"
                    )

        logger.info(f"✓ 完成 {len(scored_stocks)}/{total_count} 只股票的分析")

        # 步骤3: 漏斗筛选
        logger.info(f"\n步骤3: 正在进行漏斗筛选...")

        filter_results = []
        for stock_data in scored_stocks:
            filter_result = self.filter.apply_all_filters(stock_data)
            filter_results.append(filter_result)

        # 统计筛选结果
        passed_count = len(filter_results)  # v8.0: 所有股票都通过（无淘汰）
        risk_count = sum(1 for r in filter_results if r.get('risk_warnings', []))
        logger.info(f"✓ 评估完成: {passed_count} 只股票，其中 {risk_count} 只有风险标记")

        # 额外步骤：采集板块相关新闻（按通过股票的板块的板块频次选取Top板块）
        try:
            logger.info("\n附加: 正在采集板块相关新闻（基于通过股票的板块Top）...")
            sector_freq = {}
            # 优先使用通过筛选的股票，若为空则使用全部结果
            base_list = [r for r in filter_results if r.get('passed', False)] or filter_results
            for r in base_list:
                sd = (r.get('scoring_result') or {}).get('details', {})
                secd = sd.get('sector') or {}
                name = (secd.get('sector_name') or '').strip()
                if not name:
                    continue
                sector_freq[name] = sector_freq.get(name, 0) + 1

            # 选择Top板块名称（最多8个）
            top_sector_names = [k for k, _ in sorted(sector_freq.items(), key=lambda x: x[1], reverse=True)[:8]]

            if top_sector_names:
                self.sector_hot_news = self.sector_news_collector.get_top_news_by_sectors(
                    top_sector_names,
                    per_sector_limit=4,
                    total_limit=10
                )
                logger.info(f"✓ 成功采集 {len(self.sector_hot_news)} 条板块相关新闻，覆盖 {len(top_sector_names)} 个板块")
            else:
                logger.info("未能识别到板块名称，跳过板块新闻采集")
                self.sector_hot_news = []
        except Exception as e:
            logger.warning(f"板块新闻采集失败: {e}")
            self.sector_hot_news = []

        # 在生成报表前：改为首页“东方财富股吧话题”9条，不再展示新闻
        try:
            logger.info("\n附加: 正在采集东方财富股吧话题（最热），用于首页9条展示...")
            hot_news_title = "🔥 股吧话题精选（东方财富）"

            topics = self.topics_collector.get_guba_topics(limit=9)
            if topics and len(topics) >= 5:
                self.global_hot_news = topics
                # 供Markdown报表复用
                self.guba_topics = topics
                logger.info(f"✓ 首页热门内容已切换为股吧话题，共 {len(self.global_hot_news)} 条")
            else:
                logger.warning(f"⚠️ 股吧话题采集数量不足（{len(topics) if topics else 0} 条），将尝试通用热榜话题或热门板块兜底")
                # 尝试通用热榜话题（微博/知乎）
                try:
                    alt_topics = self.topics_collector.get_top_topics(limit=9)
                except Exception:
                    alt_topics = []

                if alt_topics and len(alt_topics) >= 5:
                    self.global_hot_news = alt_topics
                    hot_news_title = "🔥 热榜话题精选"
                else:
                    base_topics = list(self.sector_hot_news or [])
                    # 若为空，尝试用默认板块列表采集
                    if not base_topics:
                        try:
                            default_sectors = ['半导体', '新能源', '算力', 'AI应用', '智能汽车', '光伏', '储能', '芯片']
                            base_topics = self.sector_news_collector.get_top_news_by_sectors(default_sectors, per_sector_limit=3, total_limit=12)
                        except Exception as e:
                            logger.warning(f"热门话题默认采集失败: {e}")
                            base_topics = []

                    fallback_topics = []
                    for i, it in enumerate(base_topics[:9], start=1):
                        fallback_topics.append({
                            'title': it.get('title'),
                            'url': it.get('url'),
                            'source': it.get('source') or '热门话题',
                            'publish_time': it.get('publish_time') or '',
                            'heat': it.get('heat') or max(20, 100 - i * 5),
                            'rank': i,
                        })
                    self.global_hot_news = fallback_topics
                    hot_news_title = "🔥 热门话题精选（按热门板块）"

        except Exception as e:
            logger.warning(f"热榜话题采集异常: {e}")
            hot_news_title = "🔥 热门话题精选（按热门板块）"

        # 步骤3.5: LLM深度分析 (B级及以上股票)
        logger.info(f"\n步骤3.5: 对优质股票进行LLM深度分析...")

        try:
            skip_llm = os.environ.get('KRONOS_SKIP_LLM', '').strip().lower() in ('1', 'true', 'yes', 'on')
            if skip_llm:
                logger.info("⏭️ KRONOS_SKIP_LLM=1，跳过LLM深度分析")
            else:
                llm_config = LLMConfig()
                if llm_config.is_configured():
                    llm_analyzer = LLMAnalyzer(llm_config)

                    # v8.0: 所有股票都通过（无淘汰），按分数降序选Top进行LLM分析
                    passed_stocks = [
                        r for r in filter_results
                        if (
                            r.get('scoring_result', {}).get('total_score', 0) >= 65 or
                            (r.get('scoring_result', {}).get('total_score', 0) >= 60 and
                             r.get('scoring_result', {}).get('momentum_pattern', []))
                        ) and
                        '超大市值过滤' not in r.get('scoring_result', {}).get('exclusion_flags', [])
                    ]
                    # 按分数降序排序
                    passed_stocks.sort(key=lambda x: x.get('scoring_result', {}).get('total_score', 0), reverse=True)

                    # 【优化3】自适应调整LLM分析数量
                    # 基于分数差距自动降低不必要的LLM调用
                    if len(passed_stocks) > 15:
                        # 大量通过的情况：只分析Top8，避免成本过高
                        high_grade_stocks = passed_stocks[:8]
                        logger.info(f"通过股票过多({len(passed_stocks)}只)，为控制成本仅分析Top8")
                    elif len(passed_stocks) > 10:
                        # 中等数量：分析Top10，正常情况
                        high_grade_stocks = passed_stocks[:10]
                        logger.info(f"识别{len(passed_stocks)}只通过股票，分析Top10")
                    else:
                        # 数量较少：全部分析
                        high_grade_stocks = passed_stocks[:len(passed_stocks)]
                        logger.info(f"仅{len(passed_stocks)}只通过股票，全部进行LLM分析")

                    if high_grade_stocks:
                        logger.info(f"发现 {len(high_grade_stocks)} 只高分股票(≥60分, Top10)，准备进行LLM并发分析...")

                        llm_analyzed_count = 0
                        # 【优化3】动态调整并发数：股票数量少时降低并发，避免资源浪费
                        max_workers = min(5, max(2, len(high_grade_stocks) // 2))  # 2-5之间动态调整
                        logger.info(f"  LLM并发数: {max_workers} (根据股票数量动态调整)")
                        
                        # 使用线程池并发执行，限制并发数避免API限流
                        with ThreadPoolExecutor(max_workers=max_workers) as executor:
                            future_to_stock = {
                                executor.submit(self._process_single_llm_task, llm_analyzer, stock): stock 
                                for stock in high_grade_stocks
                            }
                            
                            for future in as_completed(future_to_stock):
                                try:
                                    if future.result():
                                        llm_analyzed_count += 1
                                except Exception as e:
                                    logger.error(f"LLM并发任务异常: {e}")

                        logger.info(f"✓ LLM深度分析完成: {llm_analyzed_count}/{len(high_grade_stocks)} 只股票")

                        # 输出LLM分析汇总表格
                        if llm_analyzed_count > 0:
                            self._print_llm_summary_table(high_grade_stocks)
                    else:
                        logger.info("无符合条件(≥60分)的股票，跳过LLM分析")
                else:
                    logger.info("⏭️ LLM未配置，跳过深度分析")
                    logger.info("💡 可在GUI中配置通义千问或DeepSeek API以启用AI智能分析")

        except Exception as e:
            logger.warning(f"LLM深度分析流程失败: {e}")

        # 额外步骤：为Top10股票补充具体新闻/入选原因
        logger.info(f"\n步骤3.8: 为Top10股票补充具体新闻/入选原因...")
        # v8.0: 所有股票都通过，直接按分数排序选Top10
        all_stocks = [r for r in filter_results if '超大市值过滤' not in r.get('scoring_result', {}).get('exclusion_flags', [])]
        top_stocks = sorted(all_stocks, key=lambda x: x.get('final_score', 0), reverse=True)[:10]

        for stock in top_stocks:
            try:
                code = stock.get('stock_code') or stock.get('code')
                if not code: continue

                # 构造入选原因 (优化版：优先热点与强信号)
                reasons = []
                score_details = stock.get('scoring_result', {}).get('details', {})
                
                # 1. 优先使用热门事件/新闻 (热度关联)
                events = score_details.get('events', {})
                hot_matches = events.get('hot_news_matches', [])
                if hot_matches:
                    # 取热度最高的一条
                    top_news = hot_matches[0]
                    title = top_news.get('title', '')
                    if title:
                        # 截取适中长度
                        short_title = title[:20] + '...' if len(title) > 20 else title
                        reasons.append(f"热点关联: {short_title}")

                # 2. 龙虎榜大额净买入 (资金强信号)
                dt = score_details.get('dragon_tiger', {})
                net_buy = dt.get('net_buy_amount', 0)
                if net_buy and isinstance(net_buy, (int, float)):
                    if net_buy > 100000000: # 1亿
                        reasons.append("龙虎榜净买入超1亿")
                    elif net_buy > 30000000: # 3000万
                        reasons.append("龙虎榜大额净买入")
                
                # 3. 底部启动/突破 (形态强信号)
                low_pos = score_details.get('low_position_start', {})
                if low_pos:
                    reasons.append("底部放量启动")
                
                # 4. 量化信号质量 (模型强信号)
                quant = score_details.get('quantitative', {})
                signal_quality = quant.get('signal_quality', '')
                
                # 优先使用具体的强模型名称
                top_models = quant.get('top_buy_models', [])
                model_added = False
                if top_models:
                     # Map model names to readable short reasons
                     MODEL_REASONS = {
                        'super_reversal': '超级反转',
                        'three_sisters': '三姐妹形态',
                        'volume_breakthrough': '量能突破',
                        'ma_resonance': '均线共振',
                        'super_profit_limit_up': '超额涨停',
                        'dragon_return': '龙回头',
                        'platform_breakthrough': '平台突破'
                     }
                     for m in top_models:
                         if m in MODEL_REASONS:
                             reasons.append(MODEL_REASONS[m])
                             model_added = True
                             break
                
                # 只有未添加具体模型时，才使用通用信号描述
                if not model_added and signal_quality and any(k in signal_quality for k in ['共振', '启动', '强势', '稀缺']):
                    reasons.append(signal_quality)
                
                # 5. 基本面高增长
                fund = score_details.get('fundamental', {})
                rev_yoy = fund.get('revenue_yoy')
                prof_yoy = fund.get('net_profit_yoy')
                if (rev_yoy and isinstance(rev_yoy, (int, float)) and rev_yoy > 30) or \
                   (prof_yoy and isinstance(prof_yoy, (int, float)) and prof_yoy > 30):
                    reasons.append("业绩高增长")

                # 6. 如果以上强理由都没有，才使用通用补救逻辑
                if not reasons:
                    # 技术面
                    tech = score_details.get('technical', {})
                    if tech.get('trend') == 'up': reasons.append("趋势向上")
                    
                    # 资金面
                    buy_ratio = quant.get('buy_ratio')
                    if buy_ratio and float(buy_ratio) > 0.6: reasons.append("资金共振")
                    
                    # 板块
                    sector = score_details.get('sector', {})
                    if sector.get('overall') in ['强势上涨', '偏强', 'bullish', 'slightly_bullish']: 
                        reasons.append(f"板块强势")
                
                stock['selection_reason'] = " + ".join(reasons[:2]) if reasons else "综合评分优异"

                # 采集个股新闻 - 优化：优先使用已有数据，避免重复采集
                # 从 scoring_result 中提取 events 数据
                events_data = score_details.get('events', {})
                latest_news = events_data.get('news_list', [])
                
                # 如果 events 中没有新闻，才尝试重新采集
                if not latest_news:
                    logger.info(f"正在补充采集 {stock.get('name')} ({code}) 的最新新闻...")
                    # 复用 NewsSentimentCollector, 注意它初始化需要code
                    news_collector = NewsSentimentCollector(code)
                    # 获取3条最新新闻
                    latest_news = news_collector.get_latest_news(limit=3)
                else:
                     # 确保新闻数据格式一致 (只需 title)
                     # events.news_list 通常是 [{'title':..., 'date':...}, ...]
                     pass

                if latest_news:
                    def _valid_title(t: str) -> bool:
                        if not t:
                            return False
                        ts = t.strip()
                        if len(ts) < 8:
                            return False
                        bad_keywords = ['上交所', '深交所', '证券交易所']
                        if any(b in ts for b in bad_keywords) and len(ts) < 20:
                            return False

                        # 过滤无关代码，例如 [zo90002031], [of123456], [gs10002136], [zssh000981]
                        import re
                        # 查找所有 [...] 或 (...) 格式的内容
                        brackets = re.findall(r'[\[\(]([a-zA-Z0-9]+)[\]\)]', ts)
                        for b_content in brackets:
                            # 忽略纯文字，只关注包含数字的
                            if not any(c.isdigit() for c in b_content):
                                continue

                            # 归一化：移除已知前缀，转小写
                            clean = b_content.lower()
                            # 移除所有已知的东方财富实体类型前缀
                            # gs=港股, zs/zssh/zssz=指数, of=基金, zo=其他基金, so=债券
                            for prefix in ['zssh', 'zssz', 'gs10', 'gs', 'zo9', 'zo', 'of', 'so', 'sz', 'sh']:
                                if clean.startswith(prefix):
                                    clean = clean[len(prefix):]
                                    break

                            # 如果去掉前缀后是纯数字且不是当前股票代码，则是无关实体
                            if clean.isdigit() and clean != str(code) and len(clean) >= 5:
                                return False
                            # 原始内容（含前缀）不等于当前代码，且看起来像个代码
                            if b_content.lower() != str(code) and len(b_content) >= 5:
                                if re.match(r'^(gs\d*|zs|zssh|zssz|zo\d*|of|so|sz|sh)\d+', b_content.lower()):
                                    return False

                        return True

                    latest_news = [n for n in latest_news if _valid_title(n.get('title', ''))]

                stock['latest_news'] = latest_news
                
            except Exception as e:
                logger.warning(f"为 {stock.get('name')} 补充信息失败: {e}")

        # 步骤4: 生成报表
        logger.info(f"\n步骤4: 正在生成投资机会挖掘报表...")

        report_path = self.report_generator.generate_report(
            analysis_results=filter_results,
            report_title="投资机会挖掘报告",
            global_hot_news=self.global_hot_news,
            sector_hot_news=self.sector_hot_news,
            hot_news_title=hot_news_title
        )

        # 完成
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("\n" + "=" * 60)
        logger.info("🎉 投资机会挖掘完成！")
        logger.info("=" * 60)
        logger.info(f"总耗时: {duration:.1f} 秒")
        logger.info(f"分析股票: {len(scored_stocks)} 只")
        logger.info(f"通过筛选: {passed_count} 只")
        logger.info(f"报表路径: {report_path}")
        logger.info("=" * 60)

        # 步骤5: 自动回测 - 保存推荐记录并更新历史收益
        try:
            from scripts.auto_backtest import save_recommendations, update_returns, generate_backtest_report
            logger.info(f"\n步骤5: 自动回测...")
            # v8.0: 保存Top10推荐（按评分排序，无淘汰）
            top10_stocks = top_stocks[:10]
            save_recommendations(top10_stocks)
            # 更新历史推荐的实际收益
            update_returns(days_back=30)
            # 生成回测报告
            bt_report = generate_backtest_report(days_back=30)
            if bt_report:
                logger.info(f"回测报告: {bt_report}")
        except Exception as bt_e:
            logger.warning(f"自动回测失败(不影响主流程): {bt_e}")

        # 关闭资源
        try:
            self.scorer.close()
        except Exception as e:
            logger.warning(f"关闭scorer失败: {e}")

        # 【优化1】关闭HTTP Session
        try:
            self.session.close()
        except Exception as e:
            logger.warning(f"关闭HTTP Session失败: {e}")

        return report_path

    def _preload_global_data(self, hot_stocks: List[Dict]):
        """
        【优化2】预加载全局数据（大盘情绪、板块数据）
        在批量分析前预先获取，避免每只股票重复请求
        
        Args:
            hot_stocks: 热门股票列表
        """
        try:
            from analysis.investor_sentiment import InvestorSentimentAnalyzer
            from analysis.sector_api import _get_tushare_pro, _resolve_latest_trade_date
            from analysis.sector_api import _fetch_moneyflow_ind_dc_all, _build_sector_sentiment_from_ind_row
            from analysis.sentiment_cache_manager import get_sentiment_cache
            
            cache = get_sentiment_cache()
            
            # 1. 预加载大盘情绪（只需1次，所有股票共享）
            try:
                logger.info("  正在预加载大盘情绪数据...")
                analyzer = InvestorSentimentAnalyzer('000001')  # 使用任意股票代码初始化
                market_sentiment = analyzer.get_overall_market_sentiment()
                # 缓存会自动保存，后续调用会直接使用缓存
                logger.info(f"  ✓ 大盘情绪数据已预加载")
            except Exception as e:
                logger.warning(f"  大盘情绪预加载失败: {e}")
            
            # 2. 预加载板块数据（优先Tushare资金流向接口）
            try:
                logger.info("  正在预加载板块数据（Tushare资金流向优先）...")
                pro = _get_tushare_pro()
                if not pro:
                    logger.warning("  Tushare不可用，跳过板块预加载")
                else:
                    trade_date = _resolve_latest_trade_date(pro, datetime.now())
                    rows = _fetch_moneyflow_ind_dc_all(trade_date)
                    if not rows:
                        trade_date = _resolve_latest_trade_date(pro, datetime.now() - timedelta(days=1))
                        rows = _fetch_moneyflow_ind_dc_all(trade_date)

                    if rows:
                        preloaded_count = 0
                        for row in rows:
                            if not isinstance(row, dict):
                                continue
                            sector_name = row.get('name') or row.get('ind_name')
                            if not sector_name:
                                continue
                            sentiment = _build_sector_sentiment_from_ind_row(str(sector_name), row, trade_date)
                            cache.set_sector(str(sector_name), sentiment)
                            preloaded_count += 1
                        logger.info(f"  ✓ 成功预加载 {preloaded_count} 个板块情绪数据")
                    else:
                        logger.warning("  板块资金流向数据为空，跳过板块预加载")
                
            except Exception as e:
                logger.warning(f"  板块数据预加载失败: {e}")
                
        except Exception as e:
            logger.warning(f"全局数据预加载异常: {e}")

    def _analyze_single_stock(self, hot_stock: Dict) -> Dict:
        """
        分析单只股票

        Args:
            hot_stock: 热门股票信息 (来自HotStocksFetcher)

        Returns:
            {
                'stock_code': '000001',
                'name': '平安银行',
                'exchange': 'SZ',
                'popularity_score': 95.5,
                'scoring_result': {...}  # OpportunityScorer的结果
            }
        """
        stock_code = hot_stock.get('code', '')
        stock_name = hot_stock.get('name', '未知')

        try:
            # 提取基本面数据（如果HotStocksFetcher已批量获取）
            fundamental_data = None
            if 'pe_ratio' in hot_stock:
                fundamental_data = {
                    'pe_ratio': hot_stock.get('pe_ratio'),
                    'pb_ratio': hot_stock.get('pb_ratio'),
                    'total_market_cap': hot_stock.get('total_market_cap'),
                    'circulation_market_cap': hot_stock.get('circulation_market_cap'),
                    'revenue_yoy': hot_stock.get('revenue_yoy'),
                    'net_profit_yoy': hot_stock.get('net_profit_yoy')
                }

            # 构造市场数据 (用于高级分析)
            market_data = None
            try:
                from analysis.sentiment_cache_manager import get_sentiment_cache
                cache = get_sentiment_cache()
                
                # 尝试获取板块信息
                sector_name = hot_stock.get('sector_name')
                sector_info = {}
                if sector_name:
                    sector_info = {'name': sector_name}
                    # 尝试从缓存获取板块情绪
                    sector_sentiment = cache.get_sector(sector_name)
                    if sector_sentiment:
                        sector_info['sentiment'] = sector_sentiment
                
                # 获取大盘情绪
                market_sentiment = cache.get_market_sentiment()
                
                market_data = {
                    'sector_info': sector_info,
                    'market_sentiment': market_sentiment,
                    'hot_stock_data': hot_stock  # 传递原始热股数据以备用
                }
            except Exception as e:
                logger.warning(f"构造市场数据失败: {e}")

            # 多维度打分（注入全市场热门新闻以进行事件面加分）
            scoring_result = self.scorer.calculate_comprehensive_score(
                stock_code,
                global_hot_news=self.global_hot_news,
                fundamental_data=fundamental_data,
                market_data=market_data
            )

            return {
                'stock_code': stock_code,
                'name': stock_name,
                'exchange': hot_stock.get('exchange', 'UNKNOWN'),
                'popularity_score': hot_stock.get('popularity_score', 0),
                'change_pct': hot_stock.get('change_pct', 0),
                'scoring_result': scoring_result
            }

        except Exception as e:
            logger.error(f"分析 {stock_code} ({stock_name}) 失败: {e}")
            return None

    def _process_single_llm_task(self, llm_analyzer: LLMAnalyzer, stock_result: Dict) -> bool:
        """
        处理单只股票的LLM分析任务（用于并发执行）
        支持多模型并发分析
        """
        stock_code = stock_result.get('stock_code', '')
        stock_name = stock_result.get('name', '')
        scoring_result = stock_result.get('scoring_result', {})

        try:
            # 获取所有启用的模型
            enabled_models = llm_analyzer.config.get_enabled_model_names()

            if not enabled_models:
                logger.warning(f"    ⚠️ {stock_code} 未配置任何LLM模型，跳过分析")
                return False

            logger.info(f"  正在分析 {stock_code} ({stock_name})，共{len(enabled_models)}个模型...")

            # 准备LLM分析数据
            stock_data = self._prepare_llm_analysis_data(
                stock_code, stock_name, scoring_result
            )

            # 多模型分析
            all_results = {}
            for model_full_key in enabled_models:
                model_name = model_full_key.split('/')[-1]  # 去掉 provider 前缀
                success, llm_result = llm_analyzer.analyze_stock(stock_data, model_full_key)

                if success:
                    all_results[model_name] = llm_result
                    logger.info(f"    ✓ {stock_code} [{model_name}] 分析完成")
                else:
                    logger.warning(f"    ✗ {stock_code} [{model_name}] 分析失败: {llm_result.get('error', '未知错误')}")

            if all_results:
                # 保存多模型分析结果
                stock_result['llm_analysis'] = all_results
                # 使用第一个模型的结果提取预测K线
                first_model = list(all_results.values())[0]
                llm_predicted_kline = llm_analyzer.extract_predicted_kline(first_model)
                if not llm_predicted_kline.empty:
                    stock_result['llm_predicted_kline'] = llm_predicted_kline
                    logger.info(f"    ✓ {stock_code} 多模型分析完成 ({len(all_results)}/{len(enabled_models)})，含{len(llm_predicted_kline)}天预测数据")
                else:
                    logger.info(f"    ✓ {stock_code} 多模型分析完成 ({len(all_results)}/{len(enabled_models)})")
                return True
            else:
                logger.warning(f"    ⚠️ {stock_code} 所有模型分析均失败")
                return False

        except Exception as e:
            logger.error(f"  LLM分析 {stock_code} 失败: {e}")
            return False

    def _prepare_llm_analysis_data(self, stock_code: str, stock_name: str,
                                   scoring_result: Dict) -> Dict:
        """
        准备LLM分析所需的数据

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            scoring_result: 多维度评分结果

        Returns:
            LLM分析所需的数据字典
        """
        details = scoring_result.get('details', {})
        scores = scoring_result.get('scores', {})

        # 通用的安全数值转换/格式化
        def _to_float(val, default=None):
            try:
                if val is None:
                    return default
                if isinstance(val, str):
                    v = val.strip()
                    if not v:
                        return default
                    v = v.replace('%', '').replace(',', '')
                    return float(v)
                return float(val)
            except Exception:
                return default

        def _fmt_num(val, digits=2, default='未知'):
            tv = _to_float(val, None)
            if tv is None:
                return str(val) if isinstance(val, str) and val.strip() else default
            return f"{tv:.{digits}f}"

        # 格式化技术面数据
        def format_technical_for_llm(tech_details: Dict) -> str:
            if not tech_details:
                return "技术面数据暂缺"

            parts = []
            if 'RSI' in tech_details:
                parts.append(f"RSI: {_fmt_num(tech_details.get('RSI'), 2)}")
            if 'MACD' in tech_details:
                parts.append(f"MACD: {tech_details['MACD']}")
            if 'Bollinger' in tech_details:
                parts.append(f"布林带: {tech_details['Bollinger']}")
            if tech_details.get('MA5') is not None and tech_details.get('MA10') is not None and tech_details.get('MA20') is not None:
                parts.append(
                    f"均线: MA5={_fmt_num(tech_details.get('MA5'), 2)}, MA10={_fmt_num(tech_details.get('MA10'), 2)}, MA20={_fmt_num(tech_details.get('MA20'), 2)}")

            return "\n".join(parts) if parts else "技术指标数据不足"

        # 格式化量化模型数据
        def format_quantitative_for_llm(quant_details: Dict) -> str:
            if not quant_details:
                return "量化模型数据暂缺"

            buy_count = quant_details.get('buy_count', 0)
            sell_count = quant_details.get('sell_count', 0)
            hold_count = quant_details.get('hold_count', 0)
            total = quant_details.get('total_count', 0)

            result = f"买入信号: {buy_count}个, 持有信号: {hold_count}个, 卖出信号: {sell_count}个 (共{total}个模型)\n"
            br = _to_float(quant_details.get('buy_ratio'), 0.0) or 0.0
            result += f"买入比例: {br * 100:.1f}%"

            return result

        # 格式化基本面数据
        def format_fundamental_for_llm(fund_details: Dict) -> str:
            if not fund_details:
                return "基本面数据暂缺"

            parts = []
            if 'pe_ratio' in fund_details:
                parts.append(f"PE: {_fmt_num(fund_details.get('pe_ratio'), 2)}")
            if 'pb_ratio' in fund_details:
                parts.append(f"PB: {_fmt_num(fund_details.get('pb_ratio'), 2)}")
            if 'revenue_yoy' in fund_details:
                parts.append(f"营收增长: {_fmt_num(fund_details.get('revenue_yoy'), 2)}%")
            if 'net_profit_yoy' in fund_details:
                parts.append(f"利润增长: {_fmt_num(fund_details.get('net_profit_yoy'), 2)}%")

            return "\n".join(parts) if parts else "基本面数据不足"

        # 格式化情绪数据
        def format_sentiment_for_llm(sentiment_details: Dict, sector_details: Dict) -> str:
            if not sentiment_details and not sector_details:
                return "情绪数据暂缺"

            parts = []

            # 股民情绪
            if sentiment_details:
                comprehensive = sentiment_details.get('comprehensive_sentiment', '未知')
                score = _fmt_num(sentiment_details.get('comprehensive_score', 50), 1, default='-')
                parts.append(f"综合情绪: {comprehensive} (评分: {score})")

                guba = sentiment_details.get('guba_sentiment', {})
                if guba:
                    parts.append(
                        f"股吧情绪: 看多{guba.get('bullish_ratio', 0)}%, 看空{guba.get('bearish_ratio', 0)}%")

            # 板块情绪
            if sector_details:
                sector_name = sector_details.get('sector_name', '未知板块')
                sector_overall = sector_details.get('overall', '中性')
                sector_change = _to_float(sector_details.get('change_pct', 0), 0.0) or 0.0
                parts.append(f"所属板块: {sector_name}, 板块情绪: {sector_overall}, 涨跌幅: {sector_change:.2f}%")

            return "\n".join(parts) if parts else "情绪数据不足"

        # 格式化消息面数据
        def format_events_for_llm(events_details: Dict) -> str:
            if not events_details:
                return "消息面数据暂缺"

            parts = []
            rating = events_details.get('rating', '中性')
            comp_score = _to_float(events_details.get('comprehensive_score', 0), 0.0) or 0.0
            parts.append(f"消息面评级: {rating} (综合分: {comp_score:.1f})")

            pos_events = events_details.get('positive_events', 0)
            neg_events = events_details.get('negative_events', 0)
            parts.append(f"利好事件: {pos_events}个, 利空事件: {neg_events}个")

            risk = events_details.get('risk_level', '未知')
            opp = events_details.get('opportunity_level', '未知')
            parts.append(f"风险等级: {risk}, 机会等级: {opp}")

            return "\n".join(parts)

        # 构建完整的数据
        stock_data = {
            'code': stock_code,
            'name': stock_name,
            'current_price': details.get('technical', {}).get('current_price', 0),
            'kline_data': "K线数据已通过技术分析模块计算",
            'technical_analysis': format_technical_for_llm(details.get('technical', {})) + "\n" +
                                  format_quantitative_for_llm(details.get('quantitative', {})),
            'fundamental_data': format_fundamental_for_llm(details.get('fundamental', {})),
            'news_sentiment': format_events_for_llm(details.get('events', {})),
            'market_env': format_sentiment_for_llm(
                details.get('sentiment', {}),
                details.get('sector', {})
            )
        }

        # 添加综合评分信息
        stock_data['overall_rating'] = f"""
综合评分: {scoring_result.get('total_score', 0):.2f}分
评级: {scoring_result.get('rating', 'C')}级
各维度得分:
- 量化模型: {scores.get('quantitative', 0):.1f}分
- 技术分析: {scores.get('technical', 0):.1f}分
- 股民情绪: {scores.get('sentiment', 0):.1f}分
- 板块情绪: {scores.get('sector', 0):.1f}分
- 基本面: {scores.get('fundamental', 0):.1f}分
- 消息面: {scores.get('events', 0):.1f}分
- 龙虎榜: {scores.get('dragon_tiger', 0):.1f}分
"""

        return stock_data

    def _print_llm_analysis_summary(self, stock_code: str, stock_name: str, llm_result: Dict):
        """
        输出LLM分析结果摘要到控制台

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            llm_result: LLM分析结果
        """
        try:
            # 支持多模型聚合结果格式
            if isinstance(llm_result, dict):
                # 检查是否为多模型聚合结果
                if any(k in llm_result for k in ['qwen', 'deepseek']):
                    for model_name, model_result in llm_result.items():
                        if isinstance(model_result, dict) and 'error' not in model_result:
                            self._print_single_llm_result(stock_code, stock_name, model_result, model_name)
                else:
                    # 单模型结果
                    self._print_single_llm_result(stock_code, stock_name, llm_result)
        except Exception as e:
            logger.warning(f"输出LLM分析摘要失败: {e}")

    def _print_single_llm_result(self, stock_code: str, stock_name: str, result: Dict, model_name: str = None):
        """
        输出单个LLM模型的分析结果

        Args:
            stock_code: 股票代码
            stock_name: 股票名称
            result: LLM分析结果
            model_name: 模型名称（可选）
        """
        model_label = f"[{model_name.upper()}] " if model_name else ""

        logger.info(f"\n{'='*60}")
        logger.info(f"📊 {model_label}LLM智能分析 - {stock_name}({stock_code})")
        logger.info(f"{'='*60}")

        # 操作建议
        operation = result.get('operation_advice', {})
        if operation:
            action = operation.get('action', '未知')
            position = operation.get('position_control', '��知')
            target = operation.get('target_price', '未知')
            stop_loss = operation.get('stop_loss', '未知')
            confidence = operation.get('confidence', 0)
            logger.info(f"📈 操作建议: {action} | 仓位: {position} | 目标价: {target} | 止损: {stop_loss} | 置信度: {confidence*100:.0f}%")

        # 风险评估
        risk = result.get('risk_assessment', {})
        if risk:
            risk_level = risk.get('risk_level', '未知')
            risk_score = risk.get('overall_score', 0)
            risk_points = risk.get('risk_points', [])
            logger.info(f"⚠️ 风险评估: {risk_level}风险 | 评分: {risk_score} | 风险点: {', '.join(risk_points[:3]) if risk_points else '无'}")

        # K线预测摘要
        kline_pred = result.get('kline_prediction', {})
        if kline_pred:
            trend = kline_pred.get('trend', '未知')
            conf = kline_pred.get('confidence', 0)
            support = kline_pred.get('support_levels', [])
            resistance = kline_pred.get('resistance_levels', [])
            logger.info(f"📉 趋势预测: {trend} | 置信度: {conf*100:.0f}% | 支撑位: {support[:2]} | 阻力位: {resistance[:2]}")

        # 策略建议
        strategy = result.get('strategy', {})
        if strategy:
            short_term = strategy.get('short_term', '')
            mid_term = strategy.get('mid_term', '')
            if short_term:
                logger.info(f"🎯 短线策略: {short_term[:80]}{'...' if len(short_term) > 80 else ''}")
            if mid_term:
                logger.info(f"🎯 中线策略: {mid_term[:80]}{'...' if len(mid_term) > 80 else ''}")

        # 总结
        summary = result.get('summary', '')
        if summary:
            logger.info(f"💡 综合建议: {summary[:120]}{'...' if len(summary) > 120 else ''}")

        logger.info(f"{'='*60}\n")

    def _print_llm_summary_table(self, stocks: List[Dict]):
        """
        输出LLM分析结果汇总表格到控制台

        Args:
            stocks: 包含llm_analysis的股票列表
        """
        # 筛选有LLM分析结果的股票
        llm_stocks = [s for s in stocks if s.get('llm_analysis')]
        if not llm_stocks:
            return

        logger.info("\n" + "=" * 80)
        logger.info("🤖 LLM智能分析汇总")
        logger.info("=" * 80)
        logger.info(f"{'股票':<12} {'评级':<4} {'操作':<6} {'仓位':<6} {'目标价':<12} {'止损':<10} {'风险':<6} {'趋势':<6}")
        logger.info("-" * 80)

        for stock in llm_stocks:
            llm_result = stock.get('llm_analysis', {})
            stock_name = stock.get('name', '未知')[:6]
            stock_code = stock.get('stock_code', '')
            rating = stock.get('rating', 'C')

            # 处理多模型或单模型结果
            results_to_show = []
            # 检查是否为多模型结果（字典且包含模型名称作为key）
            if isinstance(llm_result, dict) and any(k in llm_result for k in ['Qwen', 'DeepSeek', 'MiniMax', 'Kimi', 'qwen', 'deepseek']):
                for model_name, model_result in llm_result.items():
                    if isinstance(model_result, dict) and 'error' not in model_result:
                        results_to_show.append((model_name, model_result))
            elif isinstance(llm_result, dict) and 'llm_model' in llm_result:
                # 单模型旧格式
                results_to_show.append((llm_result.get('llm_model', ''), llm_result))

            for model_name, result in results_to_show:
                operation = result.get('operation_advice', {})
                action = operation.get('action', '-')
                position = operation.get('position_control', '-')
                target = str(operation.get('target_price', '-'))[:10]
                stop_loss = str(operation.get('stop_loss', '-'))[:8]

                risk = result.get('risk_assessment', {})
                risk_level = risk.get('risk_level', '-')

                kline = result.get('kline_prediction', {})
                trend = kline.get('trend', '-')

                model_tag = f"[{model_name[:2].upper()}]" if model_name else ""
                stock_display = f"{stock_name}({stock_code}){model_tag}"

                logger.info(f"{stock_display:<12} {rating:<4} {action:<6} {position:<6} {target:<12} {stop_loss:<10} {risk_level:<6} {trend:<6}")

        logger.info("=" * 80)
        logger.info("说明: 操作建议仅供参考，投资有风险，入市需谨慎")
        logger.info("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description='投资机会挖掘系统')
    parser.add_argument('--limit', type=int, default=100, help='获取热门股票的数量（默认100）')
    parser.add_argument('--source', type=str, default='heat', choices=['heat', 'moneyflow_dc'], help='候选来源：heat(热度榜) / moneyflow_dc(资金流向榜单)')
    parser.add_argument('--workers', type=int, default=10, help='并发处理线程数（默认10）')
    parser.add_argument('--test-codes', type=str, help='指定测试股票代码，逗号分隔')

    args = parser.parse_args()
    
    test_codes = None
    if args.test_codes:
        test_codes = args.test_codes.split(',')

    discovery = OpportunityDiscovery(max_workers=args.workers)
    discovery.run(limit=args.limit, test_codes=test_codes, source=args.source)


if __name__ == "__main__":
    main()
