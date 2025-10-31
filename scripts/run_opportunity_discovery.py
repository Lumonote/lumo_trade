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
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.hot_stocks_fetcher import HotStocksFetcher
from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter
from scripts.opportunity_report_generator import OpportunityReportGenerator
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
        self.hot_stocks_fetcher = HotStocksFetcher()
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

    def run(self, limit: int = 100) -> str:
        """
        运行完整的投资机会挖掘流程

        Args:
            limit: 获取热门股票的数量（默认100）

        Returns:
            生成的报表文件路径
        """
        logger.info("=" * 60)
        logger.info("🎯 投资机会挖掘系统启动")
        logger.info("=" * 60)

        start_time = datetime.now()

        # 步骤1: 获取热门股票 TOP 100 与全市场热门新闻TOP10
        logger.info(f"\n步骤1: 正在获取热门股票 TOP {limit}...")
        # 强制直接采集，避免使用缓存或本地回退
        hot_stocks = self.hot_stocks_fetcher.get_hot_stocks(limit=limit, force_refresh=True)

        if not hot_stocks:
            logger.error("✗ 获取热门股票失败，程序终止")
            return ""

        logger.info(f"✓ 成功获取 {len(hot_stocks)} 只热门股票")

        # 同步采集：全市场热门新闻TOP10
        try:
            logger.info("正在采集全市场热门新闻 TOP10（东方财富/同花顺/雪球）...")
            self.global_hot_news = self.hot_news_collector.get_top_news(limit=10)
            logger.info(f"✓ 成功采集 {len(self.global_hot_news)} 条热门新闻")
        except Exception as e:
            logger.warning(f"热门新闻采集失败: {e}")
            self.global_hot_news = []

        # 步骤2: 多维度打分分析（并发处理）
        logger.info(f"\n步骤2: 正在进行多维度打分分析...")
        logger.info(f"并发线程数: {self.max_workers}")

        scored_stocks = []
        completed_count = 0
        total_count = len(hot_stocks)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有分析任务
            future_to_stock = {
                executor.submit(self._analyze_single_stock, stock): stock
                for stock in hot_stocks
            }

            # 收集结果
            for future in as_completed(future_to_stock):
                stock = future_to_stock[future]
                try:
                    result = future.result()
                    if result:
                        scored_stocks.append(result)

                    completed_count += 1

                    # 显示进度
                    progress = (completed_count / total_count) * 100
                    logger.info(f"进度: {completed_count}/{total_count} ({progress:.1f}%) - {stock.get('name', stock.get('code'))}")

                except Exception as e:
                    logger.error(f"分析 {stock.get('code')} 失败: {e}")
                    completed_count += 1

        logger.info(f"✓ 完成 {len(scored_stocks)}/{total_count} 只股票的分析")

        # 步骤3: 漏斗筛选
        logger.info(f"\n步骤3: 正在进行漏斗筛选...")

        filter_results = []
        for stock_data in scored_stocks:
            filter_result = self.filter.apply_all_filters(stock_data)
            filter_results.append(filter_result)

        # 统计筛选结果
        passed_count = sum(1 for r in filter_results if r.get('passed', False))
        logger.info(f"✓ 筛选完成: {passed_count}/{len(filter_results)} 只股票通过")

        # 额外步骤：采集板块相关新闻（按通过股票的板块频次选取Top板块）
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
        logger.info(f"\n步骤3.5: 对B级及以上股票进行LLM深度分析...")

        try:
            llm_config = LLMConfig()
            if llm_config.is_configured():
                llm_analyzer = LLMAnalyzer(llm_config)

                # 筛选B级及以上股票(评分≥45分)
                high_grade_stocks = [
                    r for r in filter_results
                    if r.get('passed', False) and
                    r.get('scoring_result', {}).get('total_score', 0) >= 45
                ]

                if high_grade_stocks:
                    logger.info(f"发现 {len(high_grade_stocks)} 只B级及以上股票，准备进行LLM分析...")

                    llm_analyzed_count = 0
                    for stock_result in high_grade_stocks:
                        stock_code = stock_result.get('stock_code', '')
                        stock_name = stock_result.get('name', '')
                        scoring_result = stock_result.get('scoring_result', {})

                        try:
                            logger.info(f"  正在分析 {stock_code} ({stock_name})...")

                            # 准备LLM分析数据
                            stock_data = self._prepare_llm_analysis_data(
                                stock_code, stock_name, scoring_result
                            )

                            # 调用LLM分析
                            success, llm_result = llm_analyzer.analyze_stock(stock_data)

                            if success:
                                # 保存LLM分析结果
                                stock_result['llm_analysis'] = llm_result

                                # 提取预测K线数据
                                llm_predicted_kline = llm_analyzer.extract_predicted_kline(llm_result)
                                if not llm_predicted_kline.empty:
                                    stock_result['llm_predicted_kline'] = llm_predicted_kline
                                    logger.info(f"    ✓ LLM分析完成，含{len(llm_predicted_kline)}天预测数据")
                                else:
                                    logger.info(f"    ✓ LLM分析完成")

                                llm_analyzed_count += 1
                            else:
                                logger.warning(f"    ✗ LLM分析失败: {llm_result}")

                        except Exception as e:
                            logger.error(f"  LLM分析 {stock_code} 失败: {e}")

                    logger.info(f"✓ LLM深度分析完成: {llm_analyzed_count}/{len(high_grade_stocks)} 只股票")
                else:
                    logger.info("无B级及以上股票，跳过LLM分析")
            else:
                logger.info("⏭️ LLM未配置，跳过深度分析")
                logger.info("💡 可在GUI中配置通义千问或DeepSeek API以启用AI智能分析")

        except Exception as e:
            logger.warning(f"LLM深度分析流程失败: {e}")

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

        return report_path

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
            # 多维度打分（注入全市场热门新闻以进行事件面加分）
            scoring_result = self.scorer.calculate_comprehensive_score(
                stock_code,
                global_hot_news=self.global_hot_news
            )

            return {
                'stock_code': stock_code,
                'name': stock_name,
                'exchange': hot_stock.get('exchange', 'UNKNOWN'),
                'popularity_score': hot_stock.get('popularity_score', 0),
                'scoring_result': scoring_result
            }

        except Exception as e:
            logger.error(f"分析 {stock_code} ({stock_name}) 失败: {e}")
            return None

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

        # 格式化技术面数据
        def format_technical_for_llm(tech_details: Dict) -> str:
            if not tech_details:
                return "技术面数据暂缺"

            parts = []
            if 'RSI' in tech_details and tech_details['RSI']:
                parts.append(f"RSI: {tech_details['RSI']:.2f}")
            if 'MACD' in tech_details:
                parts.append(f"MACD: {tech_details['MACD']}")
            if 'Bollinger' in tech_details:
                parts.append(f"布林带: {tech_details['Bollinger']}")
            if tech_details.get('MA5') and tech_details.get('MA10') and tech_details.get('MA20'):
                parts.append(
                    f"均线: MA5={tech_details['MA5']:.2f}, MA10={tech_details['MA10']:.2f}, MA20={tech_details['MA20']:.2f}")

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
            result += f"买入比例: {quant_details.get('buy_ratio', 0) * 100:.1f}%"

            return result

        # 格式化基本面数据
        def format_fundamental_for_llm(fund_details: Dict) -> str:
            if not fund_details:
                return "基本面数据暂缺"

            parts = []
            if 'pe_ratio' in fund_details and fund_details['pe_ratio']:
                parts.append(f"PE: {fund_details['pe_ratio']:.2f}")
            if 'pb_ratio' in fund_details and fund_details['pb_ratio']:
                parts.append(f"PB: {fund_details['pb_ratio']:.2f}")
            if 'revenue_yoy' in fund_details and fund_details['revenue_yoy'] is not None:
                parts.append(f"营收增长: {fund_details['revenue_yoy']:.2f}%")
            if 'net_profit_yoy' in fund_details and fund_details['net_profit_yoy'] is not None:
                parts.append(f"利润增长: {fund_details['net_profit_yoy']:.2f}%")

            return "\n".join(parts) if parts else "基本面数据不足"

        # 格式化情绪数据
        def format_sentiment_for_llm(sentiment_details: Dict, sector_details: Dict) -> str:
            if not sentiment_details and not sector_details:
                return "情绪数据暂缺"

            parts = []

            # 股民情绪
            if sentiment_details:
                comprehensive = sentiment_details.get('comprehensive_sentiment', '未知')
                score = sentiment_details.get('comprehensive_score', 50)
                parts.append(f"综合情绪: {comprehensive} (评分: {score})")

                guba = sentiment_details.get('guba_sentiment', {})
                if guba:
                    parts.append(
                        f"股吧情绪: 看多{guba.get('bullish_ratio', 0)}%, 看空{guba.get('bearish_ratio', 0)}%")

            # 板块情绪
            if sector_details:
                sector_name = sector_details.get('sector_name', '未知板块')
                sector_overall = sector_details.get('overall', '中性')
                sector_change = sector_details.get('change_pct', 0)
                parts.append(f"所属板块: {sector_name}, 板块情绪: {sector_overall}, 涨跌幅: {sector_change:.2f}%")

            return "\n".join(parts) if parts else "情绪数据不足"

        # 格式化消息面数据
        def format_events_for_llm(events_details: Dict) -> str:
            if not events_details:
                return "消息面数据暂缺"

            parts = []
            rating = events_details.get('rating', '中性')
            comp_score = events_details.get('comprehensive_score', 0)
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
            'current_price': 0,  # 需要从details中获取实时价格
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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='投资机会挖掘系统')
    parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='获取热门股票的数量（默认100）'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=10,
        help='并发处理线程数（默认10）'
    )

    args = parser.parse_args()

    # 创建并运行
    discovery = OpportunityDiscovery(max_workers=args.workers)
    report_path = discovery.run(limit=args.limit)

    if report_path and os.path.exists(report_path):
        print(f"\n✓ 报表已生成: {report_path}")

        # 尝试在浏览器中打开报表
        try:
            import webbrowser
            abs_path = os.path.abspath(report_path)
            webbrowser.open(f'file://{abs_path}')
            print(f"✓ 报表已在浏览器中打开")
        except Exception as e:
            print(f"自动打开浏览器失败: {e}")
            print(f"请手动打开: {os.path.abspath(report_path)}")
    else:
        print("\n✗ 报表生成失败")


if __name__ == "__main__":
    main()
