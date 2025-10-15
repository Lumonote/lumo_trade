#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会多维度打分系统
整合量化模型、技术面、情绪面、板块、基本面、事件等多维度进行综合评分
"""

import os
import sys
import pandas as pd
from typing import Dict, Optional, Tuple
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.technical_analysis import TechnicalAnalysis, QuantitativeModels
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.event_analyzer import EventAnalyzer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpportunityScorer:
    """投资机会多维度打分系统"""

    # 评级阈值配置
    RATING_THRESHOLDS = {
        'S': 85,   # S级：85分以上，极佳投资机会（放宽）
        'A+': 75,  # A+级：75-85分，优秀投资机会（放宽）
        'A': 65,   # A级：65-75分，良好投资机会（放宽）
        'B': 50,   # B级：50-65分，一般投资机会（放宽）
        'C': 0     # C级：50分以下，较差投资机会
    }

    # 维度权重配置
    DIMENSION_WEIGHTS = {
        'quantitative': 0.32,    # 量化模型权重 32%
        'technical': 0.24,       # 技术分析权重 24%
        'sentiment': 0.10,       # 股民情绪权重 10%
        'sector': 0.14,          # 板块情绪权重 14%
        'fundamental': 0.10,     # 基本面权重 10%（上调）
        'events': 0.10           # 事件面权重 10%
    }

    # 动态权重模板（总和均为1.0）
    DYNAMIC_WEIGHT_PROFILES = {
        'base': {
            'quantitative': 0.32,
            'technical': 0.24,
            'sentiment': 0.10,
            'sector': 0.14,
            'fundamental': 0.10,
            'events': 0.10,
        },
        # 强趋势、低风险时，提高量化占比
        'trend_bull': {
            'quantitative': 0.42,
            'technical': 0.24,
            'sentiment': 0.08,
            'sector': 0.12,
            'fundamental': 0.08,
            'events': 0.06,
        },
        # 高风险或消息面主导时，降低量化占比，提升事件/情绪
        'high_risk_news': {
            'quantitative': 0.22,
            'technical': 0.22,
            'sentiment': 0.15,
            'sector': 0.21,
            'fundamental': 0.10,
            'events': 0.10,
        },
    }

    def __init__(self):
        """初始化打分系统"""
        # 采集器按股票实例化，避免错误的无参构造
        pass

    def calculate_comprehensive_score(self, stock_code: str,
                                     historical_data: Optional[pd.DataFrame] = None) -> Dict:
        """
        计算综合评分

        Args:
            stock_code: 股票代码（6位数字，如 "000001"）
            historical_data: 历史K线数据（可选，如果不提供则自动获取）

        Returns:
            {
                'total_score': 78.5,  # 综合得分 0-100
                'rating': 'A',  # 评级 S/A+/A/B/C
                'recommendation': '良好投资机会',
                'scores': {
                    'quantitative': 85.0,  # 量化模型得分
                    'technical': 72.0,     # 技术分析得分
                    'sentiment': 68.0,     # 股民情绪得分
                    'sector': 75.0,        # 板块情绪得分
                    'fundamental': 60.0,   # 基本面得分
                    'events': 55.0        # 事件面得分
                },
                'details': {
                    # 各维度的详细数据
                }
            }
        """
        logger.info(f"开始计算 {stock_code} 的综合评分...")

        # 初始化结果
        result = {
            'stock_code': stock_code,
            'total_score': 0.0,
            'rating': 'C',
            'recommendation': '',
            'scores': {
                'quantitative': 0.0,
                'technical': 0.0,
                'sentiment': 0.0,
                'sector': 0.0,
                'fundamental': 0.0,
                'events': 0.0
            },
            'details': {}
        }

        try:
            # 准备历史数据，避免技术面/量化评分为0
            if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty):
                historical_data = self._fetch_historical_data(stock_code)
            # 1. 量化模型评分 (30%)
            quant_score, quant_details = self._score_quantitative_models(stock_code, historical_data)
            result['scores']['quantitative'] = quant_score
            result['details']['quantitative'] = quant_details

            # 2. 技术分析评分 (20%)
            tech_score, tech_details = self._score_technical_analysis(stock_code, historical_data)
            result['scores']['technical'] = tech_score
            result['details']['technical'] = tech_details

            # 3. 股民情绪评分 (15%)
            sentiment_score, sentiment_details = self._score_investor_sentiment(stock_code)
            result['scores']['sentiment'] = sentiment_score
            result['details']['sentiment'] = sentiment_details

            # 4. 板块情绪评分 (15%)
            sector_score, sector_details = self._score_sector_sentiment(stock_code)
            result['scores']['sector'] = sector_score
            result['details']['sector'] = sector_details

            # 5. 基本面评分 (10%)
            fundamental_score, fundamental_details = self._score_fundamental(stock_code)
            result['scores']['fundamental'] = fundamental_score
            result['details']['fundamental'] = fundamental_details

            # 6. 事件面评分 (10%)
            events_score, events_details = self._score_events(stock_code)
            result['scores']['events'] = events_score
            result['details']['events'] = events_details

            # 选择动态权重
            weights_used, weight_mode = self._select_dynamic_weights(result)

            # 计算加权总分（使用动态权重）
            total_score = (
                quant_score * weights_used['quantitative'] +
                tech_score * weights_used['technical'] +
                sentiment_score * weights_used['sentiment'] +
                sector_score * weights_used['sector'] +
                fundamental_score * weights_used['fundamental'] +
                events_score * weights_used['events']
            )

            result['total_score'] = round(total_score, 2)
            result['rating'] = self._get_rating(total_score)
            result['recommendation'] = self._get_recommendation(result['rating'])
            result['weights_used'] = weights_used
            result['weight_mode'] = weight_mode

            logger.info(f"使用权重模式: {weight_mode} -> {weights_used}")

            logger.info(f"✓ {stock_code} 综合评分完成: {result['total_score']}分 ({result['rating']}级)")

        except Exception as e:
            logger.error(f"计算 {stock_code} 综合评分失败: {e}", exc_info=True)

        return result

    def _fetch_historical_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """获取历史K线数据（日线，尽量保证足量数据）"""
        try:
            # 延迟导入，避免在无数据需求时加载重依赖
            from scripts.fetch_data import MultiSourceDataFetcher
            import asyncio

            fetcher = MultiSourceDataFetcher()

            async def _run():
                # 过去一年到今天的日线数据
                end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
                start_date = (pd.Timestamp.today() - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
                df = await fetcher.fetch_stock_data(
                    symbol=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    freq='daily',
                    source='auto',
                    auto_extend=True,
                    min_days=240
                )
                await fetcher.close()
                return df

            # 在同步环境中运行异步获取
            try:
                df = asyncio.run(_run())
            except RuntimeError:
                # 若已有事件循环，使用新循环
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                df = loop.run_until_complete(_run())
                loop.close()

            # 基本校验
            if df is None or df.empty:
                logger.warning(f"{stock_code}: 历史数据获取为空，技术面与量化评分可能为0")
                return None

            # 确保列名兼容
            required_cols = {'timestamps', 'open', 'high', 'low', 'close', 'volume'}
            if not required_cols.issubset(set(df.columns)):
                logger.warning(f"{stock_code}: 历史数据列不完整，实际列: {list(df.columns)}")
                return None

            # 只保留必要列并按时间排序
            df = df[list(required_cols)].copy()
            df['timestamps'] = pd.to_datetime(df['timestamps'])
            df = df.sort_values('timestamps').reset_index(drop=True)

            return df
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return None

    def _score_quantitative_models(self, stock_code: str,
                                   historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        量化模型评分 (0-100分)

        评分逻辑:
        - 买入信号越多，分数越高
        - 考虑模型胜率加权
        """
        try:
            if historical_data is None or historical_data.empty:
                logger.warning(f"{stock_code}: 无历史数据，量化模型评分为0")
                return 0.0, {'error': '无历史数据'}

            # 使用量化模型系统
            quant_models = QuantitativeModels(historical_data)
            # 运行模型以生成信号（优先优化版）
            try:
                quant_models.run_all_models_optimized()
            except Exception:
                quant_models.run_all_models()
            report = quant_models.generate_analysis_report()
            current_signals = report.get('current_signals', {})

            # 统计信号
            buy_count = sum(1 for s in current_signals.values() if s == '买入')
            sell_count = sum(1 for s in current_signals.values() if s == '卖出')
            hold_count = sum(1 for s in current_signals.values() if s == '持有')
            total_count = len(current_signals)

            # 计算买入信号比例
            buy_ratio = buy_count / total_count if total_count > 0 else 0

            # 评分算法: buy_ratio * 100
            # 例如: 18个买入/30个模型 = 60%买入 = 60分
            score = buy_ratio * 100

            # 卖出信号惩罚: 每个卖出信号扣2分（下调惩罚强度）
            score -= sell_count * 2

            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            details = {
                'buy_count': buy_count,
                'sell_count': sell_count,
                'hold_count': hold_count,
                'total_count': total_count,
                'buy_ratio': round(buy_ratio, 2),
                'signals': current_signals,
                'top_buy_models': [k for k, v in current_signals.items() if v == '买入'][:5]
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"量化模型评分失败: {e}")
            return 0.0, {'error': str(e)}

    def _score_technical_analysis(self, stock_code: str,
                                  historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        技术分析评分 (0-100分)

        评分维度:
        - RSI: 超卖区(30以下)加分，超买区(70以上)减分
        - MACD: 金叉加分，死叉减分
        - 布林带: 下轨附近加分，上轨附近减分
        - 均线排列: 多头排列加分，空头排列减分
        """
        try:
            if historical_data is None or historical_data.empty:
                logger.warning(f"{stock_code}: 无历史数据，技术分析评分为0")
                return 0.0, {'error': '无历史数据'}

            # 直接用静态方法计算关键技术指标
            score = 50.0  # 基准分

            close = historical_data['close']
            high = historical_data['high']
            low = historical_data['low']

            # RSI评分 (-20 ~ +20)
            try:
                rsi_series = TechnicalAnalysis.calculate_rsi(close, 14)
                rsi = float(rsi_series.iloc[-1]) if len(rsi_series.dropna()) else None
            except Exception:
                rsi = None

            if rsi is not None:
                if rsi < 30:
                    score += 20  # 超卖，加分
                elif rsi > 70:
                    score -= 20  # 超买，减分
                elif 40 <= rsi <= 60:
                    score += 10  # 中性偏多，加分

            # MACD评分 (+15 or -15)
            try:
                macd_line, macd_signal_line, _ = TechnicalAnalysis.calculate_macd(close)
                macd_signal = '金叉' if macd_line.iloc[-1] > macd_signal_line.iloc[-1] else '死叉'
            except Exception:
                macd_signal = None

            if macd_signal == '金叉':
                score += 15
            elif macd_signal == '死叉':
                score -= 15

            # 布林带评分 (+5 or -5)（柔化扣分/加分幅度）
            try:
                upper, middle, lower = TechnicalAnalysis.calculate_bollinger_bands(close, period=20, std_dev=2)
                current_price = float(close.iloc[-1])
                if current_price < float(lower.iloc[-1]):
                    bb_status = '下轨附近'
                    score += 5
                elif current_price > float(upper.iloc[-1]):
                    bb_status = '上轨附近'
                    score -= 5
                else:
                    bb_status = '中轨附近'
            except Exception:
                bb_status = None

            # 均线排列评分 (+15 or -15)
            try:
                ma5_series = TechnicalAnalysis.calculate_ma(close, 5)
                ma10_series = TechnicalAnalysis.calculate_ma(close, 10)
                ma20_series = TechnicalAnalysis.calculate_ma(close, 20)
                ma5 = float(ma5_series.iloc[-1]) if len(ma5_series.dropna()) else None
                ma10 = float(ma10_series.iloc[-1]) if len(ma10_series.dropna()) else None
                ma20 = float(ma20_series.iloc[-1]) if len(ma20_series.dropna()) else None
                if ma5 is not None and ma10 is not None and ma20 is not None:
                    if ma5 > ma10 and ma10 > ma20:
                        score += 15  # 多头排列
                    elif ma5 < ma10 and ma10 < ma20:
                        score -= 15  # 空头排列
            except Exception:
                ma5 = ma10 = ma20 = None

            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            details = {
                'RSI': rsi,
                'MACD': macd_signal,
                'Bollinger': bb_status,
                'MA5': ma5,
                'MA10': ma10,
                'MA20': ma20
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"技术分析评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_investor_sentiment(self, stock_code: str) -> Tuple[float, Dict]:
        """
        股民情绪评分 (0-100分)

        直接使用 investor_sentiment 模块的综合情绪得分
        """
        try:
            analyzer = InvestorSentimentAnalyzer(stock_code)
            sentiment_data = analyzer.get_comprehensive_sentiment(verbose=False)

            if sentiment_data:
                score = sentiment_data.get('comprehensive_score', 50)
                details = {
                    'comprehensive_score': score,
                    'comprehensive_sentiment': sentiment_data.get('comprehensive_sentiment', '中性'),
                    'guba_sentiment': sentiment_data.get('guba_sentiment', {}),
                    'overall_market': sentiment_data.get('overall_market_sentiment', {}),
                    'capital_flow': sentiment_data.get('capital_flow', {}),
                    'dragon_tiger': sentiment_data.get('dragon_tiger', {}),
                    'bonus_reasons': sentiment_data.get('bonus_reasons', [])
                }
                return float(score), details
            return 50.0, {'error': '无情绪数据'}
        except Exception as e:
            logger.error(f"股民情绪评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_sector_sentiment(self, stock_code: str) -> Tuple[float, Dict]:
        """
        板块情绪评分 (0-100分)

        评分维度:
        - 板块涨跌幅
        - 板块换手率
        - 板块龙头表现
        """
        try:
            analyzer = InvestorSentimentAnalyzer(stock_code)
            sector = analyzer.get_sector_info_and_sentiment()

            if sector:
                score = sector.get('sentiment_score', 50)
                details = {
                    'sector_name': sector.get('sector_name', '未知'),
                    'sentiment_score': score,
                    'overall': sector.get('overall', '中性'),
                    'change_pct': sector.get('change_pct', 0),
                    'turnover_rate': sector.get('turnover_rate', 0),
                    'leader_stock': sector.get('leader_stock', {})
                }
                return float(score), details
            return 50.0, {'error': '无板块数据'}
        except Exception as e:
            logger.error(f"板块情绪评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_fundamental(self, stock_code: str) -> Tuple[float, Dict]:
        """
        基本面评分 (0-100分)

        评分维度:
        - PE/PB估值水平
        - 营收增长率
        - 净利润增长率
        - 现金流状况
        """
        try:
            collector = FundamentalDataCollector(stock_code)
            fundamental_data = collector.get_comprehensive_data()

            if not fundamental_data:
                return 50.0, {'error': '无基本面数据'}

            indicators = fundamental_data.get('financial_indicators', {})
            reports = fundamental_data.get('financial_reports', {})

            score = 50.0

            pe = indicators.get('pe_ratio')
            if isinstance(pe, (int, float)):
                if pe < 20:
                    score += 20
                elif pe <= 40:
                    score += 10
                elif pe > 50:
                    score -= 20

            revenue_yoy = reports.get('revenue_yoy')
            if isinstance(revenue_yoy, (int, float)):
                if revenue_yoy > 20:
                    score += 15
                elif revenue_yoy > 0:
                    score += 8
                else:
                    score -= 15

            profit_yoy = reports.get('net_profit_yoy')
            if isinstance(profit_yoy, (int, float)):
                if profit_yoy > 20:
                    score += 15
                elif profit_yoy > 0:
                    score += 8
                else:
                    score -= 15

            score = max(0, min(100, score))

            details = {
                'pe_ratio': pe,
                'pb_ratio': indicators.get('pb_ratio'),
                'revenue_yoy': revenue_yoy,
                'net_profit_yoy': profit_yoy,
                'total_market_cap': indicators.get('total_market_cap')
            }

            return round(score, 2), details
        except Exception as e:
            logger.error(f"基本面评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_events(self, stock_code: str) -> Tuple[float, Dict]:
        """
        事件面评分 (0-100分)

        评分维度:
        - 利好事件数量和影响力
        - 利空事件数量和影响力
        - 综合事件评级
        """
        try:
            news_collector = NewsSentimentCollector(stock_code)
            news_data = news_collector.get_comprehensive_news(verbose=False)

            analyzer = EventAnalyzer(stock_code, news_data=news_data)
            event_data = analyzer.get_comprehensive_analysis(verbose=False)

            if not event_data:
                return 50.0, {'error': '无事件数据'}

            summary = event_data.get('summary', {})
            comprehensive_score = summary.get('comprehensive_score', 0)

            # 将(-∞, +∞)的综合分数压缩到(0,100)区间的直观映射
            # 经验：+20以上为强利好，-20以下为强利空，线性映射到0-100
            score = max(0, min(100, (comprehensive_score + 20) * (100 / 40)))

            details = {
                'rating': summary.get('rating', '中性'),
                'comprehensive_score': comprehensive_score,
                'positive_events': summary.get('total_positive_events', 0),
                'negative_events': summary.get('total_negative_events', 0),
                'risk_level': summary.get('risk_level', '未知'),
                'opportunity_level': summary.get('opportunity_level', '未知')
            }

            return round(score, 2), details
        except Exception as e:
            logger.error(f"事件面评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _get_rating(self, score: float) -> str:
        """
        根据分数获取评级

        Args:
            score: 综合得分 (0-100)

        Returns:
            评级 S/A+/A/B/C
        """
        if score >= self.RATING_THRESHOLDS['S']:
            return 'S'
        elif score >= self.RATING_THRESHOLDS['A+']:
            return 'A+'
        elif score >= self.RATING_THRESHOLDS['A']:
            return 'A'
        elif score >= self.RATING_THRESHOLDS['B']:
            return 'B'
        else:
            return 'C'

    def _get_recommendation(self, rating: str) -> str:
        """
        根据评级获取投资建议

        Args:
            rating: 评级 S/A+/A/B/C

        Returns:
            投资建议文本
        """
        recommendations = {
            'S': '🌟 极佳投资机会 - 强烈推荐',
            'A+': '⭐ 优秀投资机会 - 推荐',
            'A': '✓ 良好投资机会 - 可考虑',
            'B': '△ 一般投资机会 - 谨慎',
            'C': '✗ 较差投资机会 - 不建议'
        }

        return recommendations.get(rating, '未知')

    def _select_dynamic_weights(self, result: Dict) -> Tuple[Dict, str]:
        """
        根据当前股票的指标与风险状态选择动态权重模板

        触发条件（示例）：
        - trend_bull：buy_ratio >= 0.6 且 sell_count <= 2，事件风险不含“高”，板块涨幅非负或板块得分较高
        - high_risk_news：事件风险包含“高”或事件得分 <= 40
        - base：其他情况

        Returns:
            (weights_dict, mode_name)
        """
        try:
            q = result.get('details', {}).get('quantitative', {})
            e = result.get('details', {}).get('events', {})
            s = result.get('details', {}).get('sector', {})
            scores = result.get('scores', {})

            buy_ratio = float(q.get('buy_ratio', 0) or 0)
            sell_count = int(q.get('sell_count', 0) or 0)
            risk_level = str(e.get('risk_level', '') or '')
            ev_score = float(scores.get('events', 0) or 0)
            sector_change = s.get('change_pct', 0)
            sector_score = float(scores.get('sector', 0) or 0)

            def _contains_high(text: str) -> bool:
                return any(k in text for k in ['高', '较高', '极高'])

            # 强趋势、低风险，提高量化占比
            if (buy_ratio >= 0.6 and sell_count <= 2 and not _contains_high(risk_level)
                and ((isinstance(sector_change, (int, float)) and sector_change >= 0) or sector_score >= 60)):
                return self.DYNAMIC_WEIGHT_PROFILES['trend_bull'], 'trend_bull'

            # 高风险或消息面主导，降低量化占比
            if _contains_high(risk_level) or ev_score <= 40:
                return self.DYNAMIC_WEIGHT_PROFILES['high_risk_news'], 'high_risk_news'

            # 默认使用基础权重
            return self.DYNAMIC_WEIGHT_PROFILES['base'], 'base'
        except Exception as ex:
            logger.warning(f"动态权重选择失败，使用基础权重: {ex}")
            return self.DYNAMIC_WEIGHT_PROFILES['base'], 'base'


def main():
    """测试多维度打分系统"""
    print("=" * 60)
    print("投资机会多维度打分系统 - 测试")
    print("=" * 60)

    scorer = OpportunityScorer()

    # 测试股票代码
    test_stocks = ['000001', '600000', '300001']

    for stock_code in test_stocks:
        print(f"\n{'='*60}")
        print(f"正在分析: {stock_code}")
        print(f"{'='*60}")

        result = scorer.calculate_comprehensive_score(stock_code)

        if result:
            print(f"\n✓ 综合评分: {result['total_score']} 分")
            print(f"✓ 评级: {result['rating']}")
            print(f"✓ 建议: {result['recommendation']}")

            print(f"\n各维度得分:")
            w = result.get('weights_used') or OpportunityScorer.DIMENSION_WEIGHTS
            def pct(k):
                return int(round(w.get(k, 0) * 100))
            print(f"  量化模型: {result['scores']['quantitative']:.2f} (权重 {pct('quantitative')}%)")
            print(f"  技术分析: {result['scores']['technical']:.2f} (权重 {pct('technical')}%)")
            print(f"  股民情绪: {result['scores']['sentiment']:.2f} (权重 {pct('sentiment')}%)")
            print(f"  板块情绪: {result['scores']['sector']:.2f} (权重 {pct('sector')}%)")
            print(f"  基本面: {result['scores']['fundamental']:.2f} (权重 {pct('fundamental')}%)")
            print(f"  事件面: {result['scores']['events']:.2f} (权重 {pct('events')}%)")
        else:
            print(f"\n✗ 评分失败")


if __name__ == "__main__":
    main()
