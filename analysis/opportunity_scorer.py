#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会多维度打分系统 v4.0 - 游资思维重构版
=====================================

核心设计理念（顶级游资/操盘手思维）:
1. 反追涨：已涨股票是风险，调整到位才是机会
2. 低吸高抛：关注底部启动信号，惩罚高位追涨
3. 信号稀缺性：重视少数先行信号，而非同质化信号堆积
4. 量价验证：资金流入是核心，情绪是反指标
5. 风险优先：宁可错过，不可套牢

整合量化模型、技术面、情绪面、板块、基本面、事件等多维度进行综合评分
"""

import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List
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
    """
    投资机会多维度打分系统 v4.0 - 游资思维重构版

    核心改进（游资思维）:
    1. 动量评分：反追涨逻辑，已涨股票扣分，调整到位加分
    2. 量化信号：评估信号稀缺性和质量，而非简单数量累加
    3. 技术筛选：多重共振+入场时机判断
    4. 情绪分析：作为反指标处理，过度乐观反而扣分
    5. 流动性筛选：成交额/换手率门槛检查
    6. 一票否决：恢复并强化风控机制
    """

    # 评级阈值配置 (v4.0 - 提高门槛，宁缺毋滥)
    RATING_THRESHOLDS = {
        'S': 82,   # S级：82分以上，极佳投资机会（更严格）
        'A+': 72,  # A+级：72-82分，优秀投资机会
        'A': 62,   # A级：62-72分，良好投资机会
        'B': 48,   # B级：48-62分，一般投资机会
        'C': 0     # C级：48分以下，较差/高风险
    }

    # 维度权重配置 (v4.3 底部启动+防高位接盘特化版)
    # 核心理念：大幅提高位置与时机权重，严防高位接盘，寻找底部启动
    # 权重总和=1.0
    DIMENSION_WEIGHTS = {
        'position_timing': 0.25, # 【核心大幅提升】位置与时机（低位启动核心，从0.18提升到0.25）
        'volume_health': 0.20,   # 【核心提升】量价结构（主力吸筹验证，从0.16提升到0.20）
        'technical': 0.05,       # 技术分析（降权，从0.09降到0.05）
        'quantitative': 0.30,    # 量化模型（降权，从0.36降到0.30，平衡权重）
        'liquidity': 0.04,       # 流动性
        'sector': 0.10,          # 【提升】板块强度（从0.09提升到0.10）
        'dragon_tiger': 0.05,    # 龙虎榜
        'fundamental': 0.01,     # 基本面（降权）
        'events': 0.00,          # 消息催化（降权，忽略）
        'sentiment': 0.00,       # 情绪面
    }

    # 一票否决阈值 (v4.0 强化风控)
    EXCLUSION_RULES = {
        'max_change_60d': 60,          # 【收紧】60日涨幅超60%一票否决（原80%）
        'max_change_20d': 40,          # 【收紧】20日涨幅超40%一票否决（原50%）
        'max_distance_from_high': 5,   # 距离年内高点<5%一票否决
        # 'min_avg_amount_20d': 3000,    # 20日均成交额<3000万一票否决（已移除）
        # 'min_turnover_rate': 0.5,      # 换手率<0.5%一票否决（已移除）
        'max_consecutive_up': 6,       # 【收紧】连涨超6天一票否决（原7天）
        'min_profit_yoy': -70,         # 利润同比下滑超70%一票否决
    }

    # 动态权重模板（总和均为1.0）- v4.3 底部启动特化版
    DYNAMIC_WEIGHT_PROFILES = {
        # 基础模板
        'base': {
            'position_timing': 0.25,
            'volume_health': 0.20,
            'technical': 0.05,
            'quantitative': 0.30,
            'liquidity': 0.04,
            'sector': 0.10,
            'dragon_tiger': 0.05,
            'fundamental': 0.01,
            'events': 0.00,
            'sentiment': 0.00,
        },
        # 底部启动模板：极致强化低位+量价
        'bottom_start': {
            'position_timing': 0.35,  # 【极致提升】位置时机
            'volume_health': 0.25,    # 【大幅提升】量价结构
            'technical': 0.05,
            'quantitative': 0.20,     # 【降权】量化模型
            'liquidity': 0.03,
            'sector': 0.08,
            'dragon_tiger': 0.04,
            'fundamental': 0.00,
            'events': 0.00,
            'sentiment': 0.00,
        },
        # 趋势接力模板：强调量化+量价+热点（总和=1.0）
        'trend_continuation': {
            'position_timing': 0.16,  # 位置时机
            'volume_health': 0.18,    # 【提升】量价结构（主力吸筹）
            'technical': 0.11,        # 技术分析
            'quantitative': 0.35,     # 【提升】量化模型
            'liquidity': 0.04,        # 流动性
            'sector': 0.09,           # 【大幅提升】热点板块
            'dragon_tiger': 0.05,     # 【提升】龙虎榜（主力吸筹）
            'fundamental': 0.02,      # 基本面
            'events': 0.01,           # 消息催化
            'sentiment': 0.00,        # 情绪面
        },
        # 消息驱动模板：强调量化+热点+量价+主力（总和=1.0）
        'news_driven': {
            'position_timing': 0.14,  # 位置时机
            'volume_health': 0.16,    # 【提升】量价结构（主力吸筹）
            'technical': 0.07,        # 技术分析
            'quantitative': 0.33,     # 【提升】量化模型
            'liquidity': 0.04,        # 流动性
            'sector': 0.11,           # 【大幅提升】热点板块（消息驱动需要热点）
            'dragon_tiger': 0.05,     # 【提升】龙虎榜（主力吸筹）
            'fundamental': 0.02,      # 基本面
            'events': 0.05,           # 消息催化（降权，因为已有热点板块）
            'sentiment': 0.00,        # 情绪面
        },
    }

    # 兼容旧接口：映射旧维度名到新维度
    _LEGACY_DIMENSION_MAP = {
        'momentum': 'position_timing',
        'dragon_tiger': 'liquidity',
    }

    def __init__(self):
        """初始化打分系统 v4.0"""
        # 采集器按股票实例化，避免错误的无参构造
        pass

    def calculate_comprehensive_score(self, stock_code: str,
                                     historical_data: Optional[pd.DataFrame] = None,
                                     global_hot_news: Optional[list] = None,
                                     fundamental_data: Optional[Dict] = None) -> Dict:
        """
        计算综合评分

        Args:
            stock_code: 股票代码（6位数字，如 "000001"）
            historical_data: 历史K线数据（可选，如果不提供则自动获取）
            global_hot_news: 全市场热门新闻（可选，用于事件面加分）
            fundamental_data: 外部传入的基本面数据（可选，包含PE/PB/市值/增长率等，用于加速）

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
                    'events': 55.0         # 消息面得分
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
                'momentum': 0.0,        # 位置与时机
                'volume_health': 0.0,   # 量价健康
                'liquidity': 0.0,       # v4.0新增：流动性
                'sentiment': 0.0,
                'sector': 0.0,
                'fundamental': 0.0,
                'events': 0.0,
                'dragon_tiger': 0.0
            },
            'details': {},
            'exclusion_flags': []       # 一票否决标记
        }

        try:
            # 准备历史数据，避免技术面/量化评分为0
            if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty):
                historical_data = self._fetch_historical_data(stock_code)

            # 8. 基本面评分 (10%)
            # v4.1.1 修复：确保在流动性评分前获取完整基本面数据
            if fundamental_data is None:
                try:
                    collector = FundamentalDataCollector(stock_code)
                    fundamental_data = collector.get_comprehensive_data()
                except Exception as e:
                    logger.warning(f"预加载基本面数据失败: {e}")

            fundamental_score, fundamental_details = self._score_fundamental(stock_code, external_data=fundamental_data)
            result['scores']['fundamental'] = fundamental_score
            result['details']['fundamental'] = fundamental_details


            # ========== v4.1 流动性前置优化 ==========
            # 1. 【v4.1调整】流动性评分 (8%) - 前置计算，确保一票否决可用
            liquidity_score, liquidity_details = self._score_liquidity(stock_code, historical_data, fundamental_data)
            result['scores']['liquidity'] = liquidity_score
            result['details']['liquidity'] = liquidity_details

            # 2. 量化模型评分 (18%)
            quant_score, quant_details = self._score_quantitative_models(stock_code, historical_data)
            result['scores']['quantitative'] = quant_score
            result['details']['quantitative'] = quant_details

            # 3. 技术分析评分 (12%)
            tech_score, tech_details = self._score_technical_analysis(stock_code, historical_data)
            result['scores']['technical'] = tech_score
            result['details']['technical'] = tech_details

            # 4. 短期动量评分 (18%)
            momentum_score, momentum_details = self._score_momentum(stock_code, historical_data)
            result['scores']['momentum'] = momentum_score
            result['details']['momentum'] = momentum_details

            # 5. 量价健康度评分 (12%)
            volume_health_score, volume_health_details = self._score_volume_health(stock_code, historical_data)
            result['scores']['volume_health'] = volume_health_score
            result['details']['volume_health'] = volume_health_details

            # 6. 股民情绪评分 (8%)
            # 【优化】检查权重：如果所有权重模板中sentiment权重都很小(<=0.01)，跳过完整分析
            max_sentiment_weight = max(
                self.DIMENSION_WEIGHTS.get('sentiment', 0),
                max(profile.get('sentiment', 0) for profile in self.DYNAMIC_WEIGHT_PROFILES.values())
            )
            
            if max_sentiment_weight <= 0.01:
                # 权重太小，跳过完整分析，返回默认值
                sentiment_score = 50.0
                sentiment_details = {
                    'skipped': True,
                    'reason': f'情绪权重过小({max_sentiment_weight:.3f})，跳过完整分析以提升性能',
                    'raw_sentiment_score': 50,
                    'raw_sentiment_label': '中性',
                    'contrarian_score': 50.0,
                    'contrarian_signal': '中性（已跳过）',
                    'scoring_method': 'v4.2_skip_low_weight'
                }
                logger.debug(f"{stock_code} 情绪分析已跳过（权重={max_sentiment_weight:.3f}）")
            else:
                # 权重足够大，执行完整分析
                sentiment_score, sentiment_details = self._score_investor_sentiment(stock_code, momentum_details)
            
            result['scores']['sentiment'] = sentiment_score
            result['details']['sentiment'] = sentiment_details

            # 7. 板块情绪评分 (6%)
            sector_score, sector_details = self._score_sector_sentiment(stock_code)
            result['scores']['sector'] = sector_score
            result['details']['sector'] = sector_details

            # 9. 消息面评分 (10%) + 全市场热门新闻加分
            events_score, events_details = self._score_events(stock_code, global_hot_news=global_hot_news)
            result['scores']['events'] = events_score
            result['details']['events'] = events_details

            # 10. 龙虎榜评分 (6%)
            dragon_tiger_score, dragon_tiger_details = self._score_dragon_tiger(stock_code, sentiment_details)
            result['scores']['dragon_tiger'] = dragon_tiger_score
            result['details']['dragon_tiger'] = dragon_tiger_details

            # 11. 低位启动检测 (额外加分)
            low_pos_bonus, low_pos_details = self._check_low_position_start(stock_code, historical_data)
            if low_pos_bonus > 0:
                result['details']['low_position_start'] = low_pos_details

            # 12. 一票否决检查（流动性数据已在步骤1计算完毕）
            exclusion_flags = self._check_exclusion_rules(result, historical_data, low_pos_bonus)
            result['exclusion_flags'] = exclusion_flags

            # 选择动态权重
            weights_used, weight_mode = self._select_dynamic_weights(result)

            # 计算加权总分（使用动态权重）
            total_score = (
                quant_score * weights_used.get('quantitative', 0.12) +
                tech_score * weights_used.get('technical', 0.18) +
                momentum_score * weights_used.get('position_timing', weights_used.get('momentum', 0.22)) +
                volume_health_score * weights_used.get('volume_health', 0.20) +
                sentiment_score * weights_used.get('sentiment', 0.02) +
                sector_score * weights_used.get('sector', 0.08) +
                fundamental_score * weights_used.get('fundamental', 0.05) +
                events_score * weights_used.get('events', 0.04) +
                dragon_tiger_score * weights_used.get('dragon_tiger', 0.06) +
                liquidity_score * weights_used.get('liquidity', 0.08)
            )

            # [新增] 卖出信号一票否决/降权机制
            # 如果量化评分过低(<45)或卖出信号多于买入信号，强制压低总分
            # 这里的目的是防止其他维度（如消息面/技术面）掩盖了模型给出的卖出信号
            quant_sell_count = quant_details.get('sell_count', 0)
            quant_buy_count = quant_details.get('buy_count', 0)
            
            if quant_score < 45:
                # 量化评分不及格，总分上限封顶60（不能评为A级）
                logger.info(f"{stock_code} 量化评分过低({quant_score})，触发总分封顶限制")
                total_score = min(total_score, 60.0)
            
            if quant_sell_count >= quant_buy_count and quant_sell_count > 0:
                penalty = 15
                if quant_sell_count > 3:
                    penalty += 15
                total_score -= penalty
                logger.info(f"{stock_code} 卖出信号({quant_sell_count}) >= 买入信号({quant_buy_count})，总分扣除 {penalty} 分")

            # [新增] 量化买入信号额外加权
            # 如果买入信号占主导，额外奖励总分，确保好股票能被选出
            if quant_buy_count > quant_sell_count and quant_score > 60:
                bonus = 0
                if quant_buy_count >= 5:
                    bonus = 8
                elif quant_buy_count >= 3:
                    bonus = 5
                
                if bonus > 0:
                    total_score += bonus
                    logger.info(f"{stock_code} 量化买入信号主导({quant_buy_count} > {quant_sell_count})，总分额外奖励 {bonus} 分")
            
            # 应用低位启动加分 (直接加在总分上，因为这是强信号)
            if low_pos_bonus > 0:
                # 增加左侧交易保护：如果技术面和量化评分过低，屏蔽或减少加分
                is_left_side_risky = False
                
                # 检查1：基础评分过低 (量化和技术面都偏弱)
                if quant_score < 40 and tech_score < 40:
                    is_left_side_risky = True
                
                # 检查2：严重趋势卖出信号
                tech_signals = result['details']['technical'].get('signals', [])
                if any('处于年线下方' in s or '处于60日线下方' in s for s in tech_signals):
                     # 如果处于长期均线下方，且量化评分很低(<45)，视为接飞刀风险大
                     if quant_score < 45:
                         is_left_side_risky = True
                
                # 检查3：MACD死叉 (如果技术面有死叉信号)
                if any('死叉' in s for s in tech_signals):
                    # 死叉状态下，要求量化评分较高(>50)才允许抄底
                    if quant_score < 50:
                        is_left_side_risky = True

                if is_left_side_risky:
                    logger.info(f"{stock_code} 屏蔽低位启动加分(原+{low_pos_bonus}): 技术({tech_score})/量化({quant_score})评分过低或趋势向下，避免左侧接飞刀")
                    low_pos_bonus = 0
                else:
                    total_score += low_pos_bonus
                    logger.info(f"{stock_code} 触发低位启动加分: +{low_pos_bonus}")

            # 一票否决：如果有严重风险信号，大幅降低评分
            # v4.0 启用一票否决机制（游资思维：宁可错过，不可套牢）
            # if exclusion_flags:
            #     # 区分严重风险（🚨）和警告风险（⚠️）
            #     critical_flags = [f for f in exclusion_flags if '🚨' in f]
            #     warning_flags = [f for f in exclusion_flags if '⚠️' in f]

            #     # 严重风险每个扣20分，警告风险每个扣8分
            #     penalty = len(critical_flags) * 20 + len(warning_flags) * 8
            #     total_score = max(0, total_score - penalty)
            #     logger.warning(f"{stock_code} 触发一票否决: 严重{len(critical_flags)}个/警告{len(warning_flags)}个, 扣除{penalty}分")

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

            # 列名映射：兼容不同数据源的列名差异
            column_mapping = {
                'trade_date': 'timestamps',
                'timestamp': 'timestamps',
                'date': 'timestamps',
                'vol': 'volume',
                'turnover': 'amount',
            }
            df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

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
        量化模型评分 (0-100分) - v4.0 游资思维重构版

        核心改进（信号质量评估）:
        1. 信号稀缺性：少数先行信号比同质化信号堆积更有价值
        2. 信号分��：区分趋势类、震荡类、量价类模型
        3. 信号去相关：相似模型的信号不重复计分
        4. 先行信号加权：领先指标信号权重更高

        评分逻辑:
        - 基准分: 45分 (市场中性状态)
        - 稀缺买入信号（5个以下发出）: 高权重加分
        - 拥挤买入信号（15个以上发出）: 信号过度拥挤，反而扣分
        - 卖出信号: 分级扣分
        """
        try:
            if historical_data is None or historical_data.empty:
                logger.warning(f"{stock_code}: 无历史数据，量化模型评分为0")
                return 0.0, {'error': '无历史数据'}

            # 使用量化模型系统
            quant_models = QuantitativeModels(historical_data)
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

            # ========== v4.0 信号质量评估 ==========
            score = 45.0  # 基准分45分

            # 定义信号权重���按模型类型分组，避免同质化信号重复计分）
            # 趋势类模型（相关性高，取最佳信号）
            trend_models = ['海龟交易', 'CTA趋势', '均线共振', '多排突破', 'ATR动量']
            # 量价类模型
            volume_models = ['均量双动', '放量突破', '资金趋势', '主力支撑', '量价趋势']
            # 震荡类模型
            oscillator_models = ['超跌反弹', 'RSI背离', 'KDJ金叉', '随机动量']
            # 高级量化模型（独立权重）
            advanced_models = ['机器学习RF', '多因子Alpha', '配对套利', '高频微观结构']
            # 经典模型
            classic_models = ['一目均衡云', '布林挤压', '抛物转向', 'VWAP偏离', '分形自适应均线']

            # 分组统计买入信号
            trend_buy = sum(1 for m in trend_models if current_signals.get(m) == '买入')
            volume_buy = sum(1 for m in volume_models if current_signals.get(m) == '买入')
            oscillator_buy = sum(1 for m in oscillator_models if current_signals.get(m) == '买入')
            advanced_buy = sum(1 for m in advanced_models if current_signals.get(m) == '买入')
            classic_buy = sum(1 for m in classic_models if current_signals.get(m) == '买入')

            # 分组统计卖出信号
            trend_sell = sum(1 for m in trend_models if current_signals.get(m) == '卖出')
            volume_sell = sum(1 for m in volume_models if current_signals.get(m) == '卖出')
            advanced_sell = sum(1 for m in advanced_models if current_signals.get(m) == '卖出')

            # ========== v4.1 信号质量评估（结合位置动态调整）==========
            # 核心理念：
            # 1. 底部区域：稀缺信号是先行信号，价值高
            # 2. 中部区域：多模型共振更可靠
            # 3. 高位区域：信号拥挤是危险信号
            buy_ratio = buy_count / total_count if total_count > 0 else 0
            sell_ratio = sell_count / total_count if total_count > 0 else 0

            # 尝试获取位置信息（从historical_data计算）
            position_pct = 0.5  # 默认中位
            try:
                if historical_data is not None and len(historical_data) >= 60:
                    close = historical_data['close']
                    current_price = float(close.iloc[-1])
                    lookback = min(len(close), 250)
                    year_high = float(close.iloc[-lookback:].max())
                    year_low = float(close.iloc[-lookback:].min())
                    position_pct = (current_price - year_low) / (year_high - year_low + 1e-6)
            except Exception:
                pass

            # 根据位置动态调整信号评估策略
            is_bottom = position_pct < 0.30  # 底部区域
            is_middle = 0.30 <= position_pct <= 0.65  # 中部区域
            is_high = position_pct > 0.65  # 高位区域

            # 趋势判断 (v4.1新增：防止量化模型在下跌趋势中过度抄底)
            is_downtrend = False
            try:
                ma60_series = TechnicalAnalysis.calculate_ma(close, 60)
                ma60 = float(ma60_series.iloc[-1]) if len(ma60_series.dropna()) else None
                if ma60 and current_price < ma60:
                     # 60日线向下
                     if len(ma60_series) >= 20 and ma60 < float(ma60_series.iloc[-20]):
                         is_downtrend = True
            except Exception:
                pass

            signal_quality = '一般'

            if is_bottom:
                # 底部区域：稀缺信号是先行信号，价值最高
                if is_downtrend:
                    # 趋势向下时的底部信号：可能是左侧接飞刀，大幅降权
                    if 2 <= buy_count <= 5:
                        signal_quality = '底部先行(趋势向下)'
                        score += 5  # 仅微量加分 (原25)
                    elif 6 <= buy_count <= 10:
                        signal_quality = '底部启动(趋势向下)'
                        score += 5  # (原20)
                    elif 11 <= buy_count <= 15:
                        signal_quality = '底部共振(趋势向下)'
                        score += 8  # (原15)
                    elif buy_count > 15:
                        signal_quality = '底部强势(趋势向下)'
                        score += 5
                    elif buy_count == 1:
                        signal_quality = '单一信号(趋势向下)'
                        score += 0
                    else:
                        signal_quality = '无买入信号'
                        score -= 10 # 趋势向下且无信号，加速扣分
                else:
                    # 趋势企稳或向上的底部信号
                    if 2 <= buy_count <= 5:
                        signal_quality = '底部先行信号'
                        score += 25  # 底部稀缺信号最高加分
                    elif 6 <= buy_count <= 10:
                        signal_quality = '底部启动信号'
                        score += 20
                    elif 11 <= buy_count <= 15:
                        signal_quality = '底部共振信号'
                        score += 15
                    elif buy_count > 15:
                        signal_quality = '底部强势信号'
                        score += 12  # 底部即使信号多也不扣分
                    elif buy_count == 1:
                        signal_quality = '单一信号待验证'
                        score += 8
                    else:
                        signal_quality = '无买入信号'
                        score -= 5

            elif is_middle:
                # 中部区域：多模型共振更可靠
                if 10 <= buy_count <= 18:
                    signal_quality = '多模型共振'
                    score += 20  # 中部区域共振信号最优
                elif 6 <= buy_count <= 9:
                    signal_quality = '信号适中'
                    score += 15
                elif 2 <= buy_count <= 5:
                    signal_quality = '信号偏少'
                    score += 10
                elif buy_count > 18:
                    signal_quality = '信号较多'
                    score += 8  # 中部信号多稍有风险
                elif buy_count == 1:
                    signal_quality = '信号过少'
                    score += 5
                else:
                    signal_quality = '无买入信号'
                    score -= 10

            else:  # is_high
                # 高位区域：信号拥挤是危险信号
                if buy_count > 20:
                    signal_quality = '高位信号拥挤'
                    score -= 10  # 高位信号拥挤要扣分
                elif 15 < buy_count <= 20:
                    signal_quality = '高位信号偏多'
                    score += 0  # 不加分
                elif 8 <= buy_count <= 15:
                    signal_quality = '高位共振'
                    score += 10  # 高位有共振还可以
                elif 3 <= buy_count <= 7:
                    signal_quality = '高位信号谨慎'
                    score += 5
                elif buy_count <= 2:
                    signal_quality = '高位无明确信号'
                    score -= 5
                else:
                    signal_quality = '无买入信号'
                    score -= 15

            # ========== 分组信号评分（去相关处理）==========
            # 趋势类：最多加25分（避免重复计分）
            if trend_buy >= 3:
                score += 25
            elif trend_buy >= 2:
                score += 18
            elif trend_buy >= 1:
                score += 8

            # 量价类：最多加25分
            if volume_buy >= 3:
                score += 25
            elif volume_buy >= 2:
                score += 18
            elif volume_buy >= 1:
                score += 8

            # 高级量化模型：每个独立加分
            score += advanced_buy * 6  # 最多24分

            # 经典模型：适度加分
            if classic_buy >= 3:
                score += 10
            elif classic_buy >= 2:
                score += 5

            # ========== 卖出信号惩罚 ==========
            # 趋势类卖出信号权重高
            if trend_sell >= 3:
                score -= 40
            elif trend_sell >= 2:
                score -= 25
            elif trend_sell >= 1:
                score -= 12

            # 量价类卖出信号
            if volume_sell >= 3:
                score -= 30
            elif volume_sell >= 2:
                score -= 18
            elif volume_sell >= 1:
                score -= 10

            # 高级模型卖出信号
            score -= advanced_sell * 8

            # 总体卖出信号惩罚（加重）
            if sell_count > 15:
                score -= 25
            elif sell_count > 10:
                score -= 15
            elif sell_count > 5:
                score -= 10
            elif sell_count > 2:
                score -= 5
            
            # 买卖力量对比惩罚（核心修改：如果卖出多于买入，大幅扣分）
            if sell_count >= buy_count and sell_count > 0:
                score -= 20
                if sell_count > 3:
                    score -= 10

            score += buy_ratio * 60  # 提高买入信号占比权重
            score -= sell_ratio * 60 # 提高卖出信号惩罚权重
            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            details = {
                'buy_count': buy_count,
                'sell_count': sell_count,
                'hold_count': hold_count,
                'total_count': total_count,
                'buy_ratio': round(buy_ratio, 2),
                'sell_ratio': round(sell_ratio, 2),
                'signal_quality': signal_quality,
                'group_signals': {
                    'trend_buy': trend_buy,
                    'volume_buy': volume_buy,
                    'oscillator_buy': oscillator_buy,
                    'advanced_buy': advanced_buy,
                    'classic_buy': classic_buy,
                    'trend_sell': trend_sell,
                    'volume_sell': volume_sell,
                    'advanced_sell': advanced_sell,
                },
                'top_buy_models': [k for k, v in current_signals.items() if v == '买入'][:8],
                'top_sell_models': [k for k, v in current_signals.items() if v == '卖出'][:5],
                'scoring_method': 'v4.0_signal_quality'
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"量化模型评分失败: {e}")
            return 0.0, {'error': str(e)}

    def _score_technical_analysis(self, stock_code: str,
                                  historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        技术分析评分 (0-100分) - v4.0 游资思维重构版

        核心理念（多重共振+入场时机）:
        1. 单一指标信号价值低，多指标共振才有价值
        2. 重视超卖区的底部信号，惩罚超买区的追涨信号
        3. 关注均线支撑/突破的有效性
        4. 量价配合是核心验证

        评分逻辑:
        - 基准分45分（偏谨慎）
        - 超卖共振（RSI<30 + KDJ<20）：强加分
        - 超买共振（RSI>70 + KDJ>80）：强扣分
        - 均线多头+站稳支撑：加分
        - 均线空头+破位：扣分
        - 布林下轨企稳：加分机会
        - 布林上轨突破：风险信号
        """
        try:
            if historical_data is None or historical_data.empty:
                logger.warning(f"{stock_code}: 无历史数据，技术分析评分为0")
                return 0.0, {'error': '无历史数据'}

            score = 45.0  # 基准分（偏谨慎，从45开始）
            signals = []

            close = historical_data['close']
            high = historical_data['high']
            low = historical_data['low']
            volume = historical_data['volume']
            current_price = float(close.iloc[-1])

            # ========== 0. 趋势判断 (优先计算，防止接飞刀) ==========
            # 游资思维：不接下降通道的飞刀，除非有极强的反转信号
            is_downtrend = False
            try:
                ma60_series = TechnicalAnalysis.calculate_ma(close, 60)
                ma60 = float(ma60_series.iloc[-1]) if len(ma60_series.dropna()) else None
                
                ma250_series = TechnicalAnalysis.calculate_ma(close, 250)
                ma250 = float(ma250_series.iloc[-1]) if len(ma250_series.dropna()) else None

                if ma60 and current_price < ma60:
                    # 60日线向下（过去20天跌幅）
                    if len(ma60_series) >= 20 and ma60 < float(ma60_series.iloc[-20]):
                        is_downtrend = True
                        score -= 25  # 处于60日线下方且均线向下，大幅扣分
                        signals.append('⚠️ 处于60日线下方，趋势向下')
                
                if ma250 and current_price < ma250:
                    score -= 15  # 处于年线下方，长期弱势
                    signals.append('处于年线下方')
            except Exception:
                pass

            # ========== 1. RSI评估 ==========
            rsi = None
            try:
                rsi_series = TechnicalAnalysis.calculate_rsi(close, 14)
                rsi = float(rsi_series.iloc[-1]) if len(rsi_series.dropna()) else None
            except Exception:
                pass

            rsi_status = '中性'
            if rsi is not None:
                # v4.2 RSI底背离检测
                rsi_divergence = False
                try:
                    if len(close) > 20:
                        # 简单逻辑：股价创新低(近20日)，但RSI未创新低
                        recent_low_idx = close.iloc[-20:].idxmin()
                        current_is_low = (close.iloc[-1] <= close.iloc[recent_low_idx] * 1.01) # 接近新低
                        
                        rsi_min_20 = rsi_series.iloc[-20:].min()
                        rsi_current = rsi
                        
                        # 股价新低 & RSI显著高于前期低点
                        if current_is_low and rsi_current > rsi_min_20 + 5:
                            rsi_divergence = True
                except:
                    pass

                if rsi < 25:
                    bonus = 15
                    if is_downtrend:
                        bonus = 5  # 下跌趋势中超卖只是反弹，分值大幅降低
                        signals.append('下跌趋势超卖(慎抢反弹)')
                    
                    if rsi_divergence:
                        bonus += 15
                        signals.append('🔥 RSI底背离(超卖区)')
                        
                    score += bonus  # 极度超卖
                    rsi_status = '极度超卖'
                    signals.append('RSI极度超卖(<25)')
                elif rsi < 35:
                    bonus = 10
                    if is_downtrend:
                        bonus = 3
                    
                    if rsi_divergence:
                        bonus += 10
                        signals.append('RSI底背离')

                    score += bonus  # 超卖区
                    rsi_status = '超卖'
                    signals.append('RSI超卖区')
                elif rsi > 80:
                    score -= 20  # 极度超买
                    rsi_status = '极度超买'
                    signals.append('⚠️ RSI极度超买(>80)')
                elif rsi > 70:
                    score -= 12  # 超买区
                    rsi_status = '超买'
                    signals.append('⚠️ RSI超买区')
                elif 45 <= rsi <= 55:
                    score += 5  # 中性区间，有上行空间
                    rsi_status = '中性偏多'

            # ========== 2. KDJ评估 ==========
            kdj_k = kdj_d = kdj_j = None
            kdj_status = '中性'
            try:
                kdj_k_series, kdj_d_series, kdj_j_series = TechnicalAnalysis.calculate_kdj(high, low, close)
                kdj_k = float(kdj_k_series.iloc[-1]) if len(kdj_k_series.dropna()) else None
                kdj_d = float(kdj_d_series.iloc[-1]) if len(kdj_d_series.dropna()) else None
                kdj_j = float(kdj_j_series.iloc[-1]) if len(kdj_j_series.dropna()) else None
            except Exception:
                pass

            if kdj_j is not None:
                # KDJ超卖/超买判断（用J值更敏感）
                if kdj_j < 10:
                    bonus = 12
                    if is_downtrend:
                        bonus = 4
                    score += bonus
                    kdj_status = '极度超卖'
                    signals.append('KDJ-J极度超卖(<10)')
                elif kdj_j < 20:
                    bonus = 8
                    if is_downtrend:
                        bonus = 2
                    score += bonus
                    kdj_status = '超卖'
                elif kdj_j > 100:
                    score -= 15
                    kdj_status = '极度超买'
                    signals.append('⚠️ KDJ-J极度超买(>100)')
                elif kdj_j > 85:
                    score -= 8
                    kdj_status = '超买'

                # KDJ金叉/死叉（在低位金叉才加分，高位金叉反而减分）
                if kdj_k is not None and kdj_d is not None:
                    if kdj_k > kdj_d:  # 金叉
                        if kdj_k < 50:  # 低位金叉
                            score += 10
                            signals.append('低位KDJ金叉')
                        elif kdj_k > 70:  # 高位金叉（可能是诱多）
                            score -= 5
                    else:  # 死叉
                        if kdj_k > 70:  # 高位死叉
                            score -= 12
                            signals.append('⚠️ 高位KDJ死叉')
                        elif kdj_k < 30:  # 低位死叉（可能是最后一跌）
                            score += 5

            # ========== 3. RSI+KDJ 超卖共振检测 ==========
            oversold_resonance = False
            overbought_resonance = False
            if rsi is not None and kdj_j is not None:
                if rsi < 35 and kdj_j < 20:
                    oversold_resonance = True
                    bonus = 15
                    if is_downtrend:
                        bonus = 5
                    score += bonus  # 超卖共振，强买入信号
                    signals.append('🔥 RSI+KDJ超卖共振')
                elif rsi > 70 and kdj_j > 85:
                    overbought_resonance = True
                    score -= 15  # 超买共振，强卖出信号
                    signals.append('🚨 RSI+KDJ超买共振')

            # ========== 4. MACD评估（配合位置判断）==========
            macd_signal = None
            macd_status = '中性'
            try:
                macd_line, macd_signal_line, macd_hist = TechnicalAnalysis.calculate_macd(close)
                macd_val = float(macd_line.iloc[-1])
                signal_val = float(macd_signal_line.iloc[-1])
                hist_val = float(macd_hist.iloc[-1])

                if macd_val > signal_val:
                    macd_signal = '金叉'
                    # MACD在零轴下金叉更有价值（底部启动）
                    if macd_val < 0:
                        score += 12
                        macd_status = '零轴下金叉'
                        signals.append('MACD零轴下金叉（底部信号）')
                    else:
                        score += 5
                        macd_status = '金叉'
                else:
                    macd_signal = '死叉'
                    # MACD在零轴上死叉风险大
                    if macd_val > 0:
                        score -= 12
                        macd_status = '零轴上死叉'
                        signals.append('⚠️ MACD零轴上死叉')
                    else:
                        score -= 5
                        macd_status = '死叉'

                # MACD柱状图趋势
                if len(macd_hist) >= 3:
                    hist_trend = [float(macd_hist.iloc[-i]) for i in range(1, 4)]
                    if hist_trend[0] > hist_trend[1] > hist_trend[2]:  # 红柱放大
                        score += 5
                    elif hist_trend[0] < hist_trend[1] < hist_trend[2]:  # 绿柱放大
                        score -= 5
            except Exception:
                pass

            # ========== 5. 布林带评估 ==========
            bb_status = '中轨'
            bb_width = 0
            try:
                upper, middle, lower = TechnicalAnalysis.calculate_bollinger_bands(close, period=20, std_dev=2)
                upper_val = float(upper.iloc[-1])
                middle_val = float(middle.iloc[-1])
                lower_val = float(lower.iloc[-1])
                bb_width = (upper_val - lower_val) / middle_val * 100 if middle_val > 0 else 0

                if current_price < lower_val:
                    bb_status = '下轨下方'
                    # 跌破下轨，观察是否企稳
                    prev_close = float(close.iloc[-2])
                    if prev_close < lower_val and current_price > prev_close:
                        score += 10  # 下轨企稳反弹
                        signals.append('布林下轨企稳反弹')
                    else:
                        score += 3  # 跌破下轨，有机会但需观察
                elif current_price > upper_val:
                    bb_status = '上轨上方'
                    score -= 10  # 突破上轨，短期超买
                    signals.append('⚠️ 突破布林上轨')
                elif current_price > middle_val:
                    bb_status = '中轨上方'
                    score += 3
                else:
                    bb_status = '中轨下方'
                    score -= 3

                # 布林带收窄（变盘信号）
                if bb_width < 8:
                    signals.append('布林带收窄，可能变盘')
            except Exception:
                pass

            # ========== 6. 均线系统评估 ==========
            ma5 = ma10 = ma20 = ma60 = None
            ma_status = '中性'
            try:
                ma5_series = TechnicalAnalysis.calculate_ma(close, 5)
                ma10_series = TechnicalAnalysis.calculate_ma(close, 10)
                ma20_series = TechnicalAnalysis.calculate_ma(close, 20)
                ma60_series = TechnicalAnalysis.calculate_ma(close, 60)

                ma5 = float(ma5_series.iloc[-1]) if len(ma5_series.dropna()) else None
                ma10 = float(ma10_series.iloc[-1]) if len(ma10_series.dropna()) else None
                ma20 = float(ma20_series.iloc[-1]) if len(ma20_series.dropna()) else None
                ma60 = float(ma60_series.iloc[-1]) if len(ma60_series.dropna()) else None

                if all([ma5, ma10, ma20]):
                    if ma5 > ma10 > ma20:
                        ma_status = '多头排列'
                        score += 10
                        if ma60 and ma20 > ma60:
                            score += 5
                            ma_status = '强多头排列'
                    elif ma5 < ma10 < ma20:
                        ma_status = '空头排列'
                        score -= 12
                        if ma60 and ma20 < ma60:
                            score -= 5
                            ma_status = '强空头排列'
                            signals.append('⚠️ 强空头排列')

                    # 检测均线突破（站上/跌破20日线）
                    if ma20 and len(close) >= 2:
                        prev_close = float(close.iloc[-2])
                        prev_ma20 = float(ma20_series.iloc[-2]) if len(ma20_series) >= 2 else ma20
                        if current_price > ma20 and prev_close <= prev_ma20:
                            score += 8
                            signals.append('站上20日均线')
                        elif current_price < ma20 and prev_close >= prev_ma20:
                            score -= 8
                            signals.append('⚠️ 跌破20日均线')
            except Exception:
                pass

            # ========== 7. 量价配合评分 ==========
            volume_ratio = 1.0
            vol_price_status = '一般'
            try:
                if len(volume) >= 6 and len(close) >= 2:
                    current_vol = float(volume.iloc[-1])
                    avg_vol_5 = float(volume.iloc[-6:-1].mean())
                    volume_ratio = current_vol / avg_vol_5 if avg_vol_5 > 0 else 1.0

                    prev_close = float(close.iloc[-2])
                    price_up = current_price > prev_close

                    if price_up and volume_ratio >= 1.5:
                        score += 10  # 放量上涨
                        vol_price_status = '放量上涨'
                        signals.append('放量上涨')
                    elif not price_up and volume_ratio < 0.8:
                        score += 5  # 缩量下跌（正常调整）
                        vol_price_status = '缩量回调'
                    elif price_up and volume_ratio < 0.7:
                        score -= 5  # 缩量上涨（上涨乏力）
                        vol_price_status = '缩量上涨'
                        signals.append('缩量上涨，动能不足')
                    elif not price_up and volume_ratio >= 1.5:
                        score -= 10  # 放量下跌（抛压重）
                        vol_price_status = '放量下跌'
                        signals.append('⚠️ 放量下跌')
            except Exception:
                pass

            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            details = {
                'current_price': current_price,
                'RSI': rsi,
                'RSI_status': rsi_status,
                'KDJ_K': kdj_k,
                'KDJ_D': kdj_d,
                'KDJ_J': kdj_j,
                'KDJ_status': kdj_status,
                'MACD': macd_signal,
                'MACD_status': macd_status,
                'Bollinger': bb_status,
                'Bollinger_width': round(bb_width, 2),
                'MA5': ma5,
                'MA10': ma10,
                'MA20': ma20,
                'MA60': ma60,
                'MA_status': ma_status,
                'volume_ratio': round(volume_ratio, 2),
                'vol_price_status': vol_price_status,
                'oversold_resonance': oversold_resonance,
                'overbought_resonance': overbought_resonance,
                'signals': signals,
                'scoring_method': 'v4.0_resonance_based'
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"技术分析评分失败: {e}")
            return 45.0, {'error': str(e)}

    def _check_low_position_start(self, stock_code: str,
                                  historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        低位启动检测 (额外加分项)

        检测逻辑:
        1. 长期低位: 当前价格处于近一年(250日)价格分位数的20%以下
        2. 底部企稳: 近20日振幅收窄
        3. 启动信号:
           - 放量上涨: 当日涨幅>3%且量比>1.5
           - 均线突破: 站上20日均线且20日线走平或向上
        """
        try:
            if historical_data is None or historical_data.empty or len(historical_data) < 60:
                return 0.0, {}

            close = historical_data['close']
            volume = historical_data['volume']
            current_price = float(close.iloc[-1])

            # 1. 长期低位检测
            lookback = min(len(close), 250)
            recent_data = close.iloc[-lookback:]
            high_year = float(recent_data.max())
            low_year = float(recent_data.min())
            
            # 价格分位数 (0-1)
            position_pct = (current_price - low_year) / (high_year - low_year + 1e-6)
            
            is_low_position = position_pct < 0.25  # 处于底部25%区间

            if not is_low_position:
                return 0.0, {'is_low_position': False, 'position_pct': round(position_pct, 2)}

            bonus = 0.0
            signals = []

            # 2. 启动信号检测
            # 2.1 放量大涨
            prev_close = float(close.iloc[-2])
            change_pct = (current_price / prev_close - 1) * 100
            
            avg_vol_5 = float(volume.iloc[-6:-1].mean())
            current_vol = float(volume.iloc[-1])
            vol_ratio = current_vol / avg_vol_5 if avg_vol_5 > 0 else 0
            
            if change_pct > 3.0 and vol_ratio > 1.5:
                bonus += 15.0 # 【大幅提升】低位放量大涨加分（原5.0）
                signals.append('低位放量大涨')

            # 2.2 均线突破 (站上20日线)
            ma20 = float(close.rolling(window=20).mean().iloc[-1])
            ma20_prev = float(close.rolling(window=20).mean().iloc[-2])
            
            if current_price > ma20 and ma20 >= ma20_prev:
                # 且之前在均线下方
                if prev_close < ma20:
                    bonus += 10.0 # 【大幅提升】底部突破20日线加分（原3.0）
                    signals.append('底部突破20日线')

            # 2.3 筹码集中 (简单模拟: 波动率收窄)
            volatility = close.iloc[-20:].std() / close.iloc[-20:].mean()
            if volatility < 0.02: # 波动率很低，横盘整理
                bonus += 5.0 # 【提升】底部横盘缩量加分（原2.0）
                signals.append('底部横盘缩量')

            return bonus, {
                'is_low_position': True,
                'position_pct': round(position_pct, 2),
                'bonus': bonus,
                'signals': signals
            }

        except Exception as e:
            logger.warning(f"低位启动检测失败: {e}")
            return 0.0, {}

    def _score_momentum(self, stock_code: str,
                        historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        位置与时机评分 (0-100分) - v4.0 游资思维重构版

        核心理念：反追涨！
        - 已涨股票是风险，不是机会
        - 调整到位才是机会
        - 底部启动才是最佳买点

        评分逻辑（游资视角）:
        - 当前位置：距离年内高点的回撤幅度（回撤多=机会大）
        - 调整到位：涨幅后的健康回踩（3%-10%最佳）
        - 底部企稳：长期下跌后的企稳信号
        - 惩罚追涨：近期涨幅过大严重扣分
        """
        try:
            if historical_data is None or historical_data.empty:
                return 50.0, {'error': '无历史数据'}

            close = historical_data['close']
            volume = historical_data['volume']

            if len(close) < 20:
                return 50.0, {'error': '数据不足20日'}

            score = 50.0  # 基准分
            current_price = float(close.iloc[-1])
            signals = []

            # ========== 1. 当前位置评分 (-30 ~ +35) ==========
            # 核心：处于低位是机会，处于高位是风险
            lookback = min(len(close), 250)
            recent_close = close.iloc[-lookback:]
            year_high = float(recent_close.max())
            year_low = float(recent_close.min())

            # 计算位置分位数 (0-1, 0=最低, 1=最高)
            position_pct = (current_price - year_low) / (year_high - year_low + 1e-6)
            # 计算距离高点的回撤幅度
            distance_from_high = (year_high - current_price) / year_high * 100 if year_high > 0 else 0

            # 趋势检查 (v4.1新增)
            ma60 = float(close.rolling(window=60).mean().iloc[-1]) if len(close) >= 60 else current_price
            ma20 = float(close.rolling(window=20).mean().iloc[-1]) if len(close) >= 20 else current_price
            ma250 = float(close.rolling(window=250).mean().iloc[-1]) if len(close) >= 250 else None
            
            is_downtrend = current_price < ma60
            
            # 完美空头排列检测 (v4.2)
            # 价格 < MA20 < MA60 < MA250 (如果有MA250)
            is_perfect_downtrend = False
            if ma250:
                if current_price < ma20 < ma60 < ma250:
                    is_perfect_downtrend = True
            elif current_price < ma20 < ma60: # 如果没有年线，看前三均线
                 is_perfect_downtrend = True

            if position_pct <= 0.20:
                if is_perfect_downtrend:
                    score -= 10  # 完美下降通道，深不见底，即使低位也是风险
                    signals.append('🚨 完美下降通道(均线空头)，价值陷阱风险')
                elif is_downtrend:
                    score += 5   # 下跌趋势中的低位，风险仍存，大幅降分
                    signals.append('处于年内底部20%区间(趋势向下)')
                else:
                    score += 35  # 底部20%区间，极佳机会
                    signals.append('处于年内底部20%区间')
            elif position_pct <= 0.35:
                if is_perfect_downtrend:
                    score -= 15  # 下降通道中位，风险更大
                    signals.append('🚨 下降通道中位，切勿接飞刀')
                elif is_downtrend:
                    score += 0   # 下跌趋势中位，不加分
                    signals.append('处于年内底部35%区间(趋势向下)')
                else:
                    score += 25  # 底部35%区间，良好机会
                    signals.append('处于年内底部35%区间')
            elif position_pct <= 0.50:
                score += 10  # 中部区间，一般
                signals.append('处于年内中部区间')
            elif position_pct <= 0.70:
                score -= 15  # 中高位区间，风险增加（原-10）
                signals.append('处于年内中高位区间')
            elif position_pct <= 0.85:
                score -= 40  # 【大幅严惩】高位区间，追高风险（原-20）
                signals.append('⚠️ 处于年内高位区间')
            else:
                score -= 60  # 【极度严惩】接近年内最高，极高风险（原-30）
                signals.append('🚨 接近年内最高点，追高风险极大')

            # ========== 2. 近期涨幅惩罚 (游资反追涨核心) ==========
            # 近5日涨幅 - 已涨股票要扣分！
            change_5d = (current_price / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0

            # 长期横盘检测 (新增)
            # 如果长期波动率极低，且位置不高，视为“长期横盘吸筹”，不应视为下跌趋势或无动量
            is_long_consolidation = False
            if len(close) >= 120:
                # 计算120日价格区间
                hist_120 = close.iloc[-120:]
                high_120 = float(hist_120.max())
                low_120 = float(hist_120.min())
                # 如果120日振幅小于30%，视为长期横盘
                amplitude_120 = (high_120 - low_120) / low_120 if low_120 > 0 else 1.0
                
                # 计算120日均线斜率（简单的线性回归或首尾比较）
                # 这里简单比较首尾
                price_start = float(hist_120.iloc[0])
                trend_change = abs(current_price - price_start) / price_start

                if amplitude_120 < 0.30 and trend_change < 0.15:
                    is_long_consolidation = True
                    score += 20
                    signals.append('📉 长期底部横盘(120日振幅<30%)，筹码集中')
                    
                    # 如果横盘期间有放量，更加分
                    vol_120 = volume.iloc[-120:]
                    avg_vol_120 = float(vol_120.mean())
                    recent_vol_20 = float(volume.iloc[-20:].mean())
                    if recent_vol_20 > avg_vol_120 * 1.2:
                        score += 10
                        signals.append('横盘期间近期温和放量')

            if change_5d > 20:
                score -= 50  # 【严惩】5日涨幅超20%，严重高位风险（原-30）
                signals.append('🚨 5日涨幅超20%，高位接盘风险')
            elif change_5d > 15:
                score -= 30  # 【严惩】5日涨幅15-20%，追涨风险（原-20）
                signals.append('⚠️ 5日涨幅超15%，追涨风险')
            elif change_5d > 10:
                score -= 15  # 5日涨幅10-15%，需谨慎（原-10）
                signals.append('5日涨幅较大，注意回调风险')
            elif change_5d > 5:
                score -= 5   # 5日涨幅5-10%，轻微风险
            elif 0 <= change_5d <= 3:
                score += 5   # 微涨或横盘，可能是启动前兆
                signals.append('近期横盘整理')
            elif -5 <= change_5d < 0:
                score += 10  # 小幅回调，可能是买点
                signals.append('小幅回调，观察支撑')
            elif -10 <= change_5d < -5:
                score += 5   # 回调较深，观察企稳
            else:
                score -= 5   # 大幅下跌，可能趋势走坏

            # 近20日涨幅 - 中期涨幅惩罚
            change_20d = (current_price / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else 0
            if change_20d > 50:
                score -= 25  # 20日涨幅超50%，高位风险极大
                signals.append('🚨 20日涨幅超50%，一票否决级别')
            elif change_20d > 30:
                score -= 15  # 20日涨幅超30%，追涨风险
                signals.append('⚠️ 20日涨幅超30%')
            elif change_20d > 15:
                score -= 5   # 20日涨幅15-30%，需关��

            # 近60日涨幅 - 长期涨幅惩罚（游资核心：60日涨幅大意味着主力已完成拉升）
            change_60d = (current_price / float(close.iloc[-61]) - 1) * 100 if len(close) >= 61 else 0
            if change_60d > 80:
                score -= 60  # 【严惩】60日涨幅超80%，严重追高（原-40）
                signals.append('🚨 60日涨幅超80%，主力可能出货')
            elif change_60d > 50:
                score -= 35  # 【严惩】60日涨幅超50%（原-25）
                signals.append('⚠️ 60日涨幅超50%')
            elif change_60d > 30:
                score -= 15  # 60日涨幅超30%（原-10）

            # ========== 3. 调整到位评分 v4.1 (买点判断增强) ==========
            # v4.1改进：增加支撑位有效性和调整时间考量
            recent_10d_high = float(close.iloc[-10:].max())
            drawdown_from_recent = (recent_10d_high - current_price) / recent_10d_high * 100

            # 计算均线支撑
            ma5 = float(close.rolling(window=5).mean().iloc[-1]) if len(close) >= 5 else current_price
            ma10 = float(close.rolling(window=10).mean().iloc[-1]) if len(close) >= 10 else current_price
            ma20 = float(close.rolling(window=20).mean().iloc[-1]) if len(close) >= 20 else current_price
            ma60 = float(close.rolling(window=60).mean().iloc[-1]) if len(close) >= 60 else current_price

            # 判断当前价格与均线关系
            above_ma20 = current_price > ma20 * 0.98  # 允许2%容差
            above_ma60 = current_price > ma60 * 0.98
            near_ma20 = abs(current_price - ma20) / ma20 < 0.03  # 在MA20附近3%内
            near_ma60 = abs(current_price - ma60) / ma60 < 0.03

            # 计算调整时间（从近期高点到现在的天数）
            recent_high_idx = close.iloc[-10:].idxmax()
            try:
                days_since_high = len(close) - close.index.get_loc(recent_high_idx) - 1
            except Exception:
                days_since_high = 0

            # 判断是否为缩量调整（近期成交量<均值的80%）
            avg_vol_10 = float(volume.iloc[-11:-1].mean()) if len(volume) >= 11 else float(volume.iloc[-1])
            recent_vol_avg = float(volume.iloc[-3:].mean()) if len(volume) >= 3 else avg_vol_10
            is_shrinking_volume = recent_vol_avg < avg_vol_10 * 0.8

            entry_timing = '观望'
            adjustment_quality = '一般'

            # v4.1 综合判断调整到位
            if 5 <= drawdown_from_recent <= 15:
                if is_downtrend:
                    # 下跌趋势中，5-15%的回撤可能只是下跌中继，不是买点
                    base_score = 0
                    entry_timing = '趋势向下，谨慎抄底'
                    signals.append('下跌趋势中(回撤中)')
                else:
                    base_score = 15  # 基础分

                    # 支撑位有效性加分
                    if near_ma20:
                        base_score += 10
                        adjustment_quality = '回踩MA20支撑'
                        signals.append('回踩20日均线支撑')
                    elif near_ma60:
                        base_score += 8
                        adjustment_quality = '回踩MA60支撑'
                        signals.append('回踩60日均线支撑')
                    elif above_ma20:
                        base_score += 5
                        adjustment_quality = '站稳MA20上方'

                    # 调整时间加分（3-5天缩量整理最佳）
                    if 3 <= days_since_high <= 5 and is_shrinking_volume:
                        base_score += 8
                        signals.append('缩量整理3-5天（调整充分）')
                    elif 2 <= days_since_high <= 7:
                        base_score += 3

                    score += base_score
                    entry_timing = '最佳买点（调整到位）'
                    signals.append(f'调整到位，回撤{drawdown_from_recent:.1f}%')

            elif 3 <= drawdown_from_recent < 5:
                base_score = 8
                if near_ma20 or above_ma20:
                    base_score += 5
                    signals.append('小幅回踩，均线支撑有效')
                score += base_score
                entry_timing = '可买入'

            elif 15 < drawdown_from_recent <= 25:
                # 回撤较深，需要更强的支撑验证
                if near_ma60 and is_shrinking_volume:
                    score += 10
                    entry_timing = '回踩MA60，观察企稳'
                    signals.append('回踩60日均线，缩量企稳')
                elif above_ma60:
                    score += 5
                    entry_timing = '回撤较深，站稳MA60'
                else:
                    entry_timing = '回撤较深，观察支撑'

            elif drawdown_from_recent < 3:
                # 接近近期高点
                if is_shrinking_volume and days_since_high >= 2:
                    score += 0
                    entry_timing = '高位横盘蓄势'
                else:
                    score -= 5
                    entry_timing = '等待回调'

            elif drawdown_from_recent > 25:
                # 回撤过深
                if above_ma60:
                    entry_timing = '深度回调，MA60支撑'
                else:
                    score -= 5
                    entry_timing = '回撤过深，趋势可能走坏'

            # ========== 4. 底部启动信号 (额外加分) ==========
            # 条件：处于低位 + 放量上涨 + 突破均线
            if position_pct <= 0.35:  # 只有低位才检测启动信号
                prev_close = float(close.iloc[-2])
                today_change = (current_price / prev_close - 1) * 100

                # 放量检测
                avg_vol_20 = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else 0
                current_vol = float(volume.iloc[-1])
                vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1

                # 底部放量上涨信号
                if today_change > 3 and vol_ratio > 1.5:
                    score += 15
                    signals.append('🔥 底部放量上涨，启动信号')

                # 突破20日均线
                ma20 = float(close.rolling(window=20).mean().iloc[-1])
                ma20_prev = float(close.rolling(window=20).mean().iloc[-2]) if len(close) >= 21 else ma20
                if current_price > ma20 and prev_close <= ma20 and ma20 >= ma20_prev * 0.99:
                    score += 10
                    signals.append('底部突破20日均线')

            # ========== 6. 主力成本线支撑(VWAP)检测 (v4.2) ==========
            # 计算最近5天的VWAP
            if len(close) >= 5 and 'amount' in historical_data.columns:
                recent_amount = historical_data['amount'].iloc[-5:]
                recent_vol = historical_data['volume'].iloc[-5:]
                if recent_vol.sum() > 0:
                    # 假设amount是元，volume是手(100股)
                    vwap5 = recent_amount.sum() / recent_vol.sum() / 100
                    
                    # 检查是否在VWAP附近 (±2%)
                    if 0.98 <= current_price / vwap5 <= 1.02:
                        score += 10
                        signals.append('主力成本线支撑(VWAP)')
                    elif current_price > vwap5 and current_price / vwap5 < 1.05:
                         score += 5 # 站稳VWAP上方

            # ========== 7. VCP形态(波动收缩)检测 (v4.2) ==========
            # 检测最近20天，10天，5天的振幅是否递减
            if len(close) >= 20:
                highs = historical_data['high']
                lows = historical_data['low']
                
                def get_range(days):
                    h = float(highs.iloc[-days:].max())
                    l = float(lows.iloc[-days:].min())
                    if l > 0:
                        return (h - l) / l
                    return 1.0

                range_20 = get_range(20)
                range_10 = get_range(10)
                range_5 = get_range(5)
                
                # 简单的收缩判定: 20日振幅 > 10日振幅 > 5日振幅
                if range_20 > range_10 > range_5 and range_5 < 0.05: # 5日振幅小于5%
                    score += 15
                    signals.append('🔥 VCP形态(波动收缩)')

            # ========== 5. 连涨天数惩罚 ==========
            consecutive_up = 0
            for i in range(1, min(10, len(close))):
                if float(close.iloc[-i]) > float(close.iloc[-i-1]):
                    consecutive_up += 1
                else:
                    break

            if consecutive_up >= 7:
                score -= 20  # 连涨7天以上，高位风险
                signals.append('🚨 连涨超7天，追涨风险')
            elif consecutive_up >= 5:
                score -= 10  # 连涨5-6天
                signals.append('⚠️ 连涨5天以上')
            elif consecutive_up >= 3:
                score -= 5   # 连涨3-4天

            # 确保分数在合理范围内
            score = max(0, min(100, score))

            details = {
                'position_pct': round(position_pct, 2),
                'distance_from_high': round(distance_from_high, 2),
                'change_5d': round(change_5d, 2),
                'change_20d': round(change_20d, 2),
                'change_60d': round(change_60d, 2),
                'drawdown_from_recent': round(drawdown_from_recent, 2),
                'entry_timing': entry_timing,
                'consecutive_up_days': consecutive_up,
                'year_high': round(year_high, 2),
                'year_low': round(year_low, 2),
                'current_price': round(current_price, 2),
                'signals': signals,
                'scoring_method': 'v4.0_anti_chasing'
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"位置时机评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_volume_health(self, stock_code: str,
                             historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        量价健康度评分 (0-100分) - v3.0新增

        评分逻辑:
        - 量价同向: 价涨量增/价跌量缩为健康
        - 量比: 当日成交量与5日均量比值
        - 资金流入连续性: 连续放量天数
        - 异常放量检测: 突然巨量可能是风险信号
        """
        try:
            if historical_data is None or historical_data.empty:
                return 50.0, {'error': '无历史数据'}

            close = historical_data['close']
            volume = historical_data['volume']

            if len(close) < 6 or len(volume) < 6:
                return 50.0, {'error': '数据不足'}

            score = 50.0  # 基准分
            signals = []

            # 1. 量价同向评分 (-20 ~ +25)
            price_changes = []
            vol_changes = []
            for i in range(1, min(6, len(close))):
                pc = float(close.iloc[-i]) - float(close.iloc[-i-1])
                vc = float(volume.iloc[-i]) - float(volume.iloc[-i-1])
                price_changes.append(pc)
                vol_changes.append(vc)

            # 计算量价同向率
            same_direction_count = sum(1 for pc, vc in zip(price_changes, vol_changes)
                                      if (pc > 0 and vc > 0) or (pc < 0 and vc < 0))
            same_direction_rate = same_direction_count / len(price_changes) if price_changes else 0

            if same_direction_rate >= 0.8:
                score += 25  # 量价高度同向
            elif same_direction_rate >= 0.6:
                score += 15  # 量价较为同向
            elif same_direction_rate >= 0.4:
                score += 5   # 量价一般
            else:
                score -= 20  # 量价背离严重

            # 2. 量比评分 (-15 ~ +20)
            current_vol = float(volume.iloc[-1])
            avg_vol_5 = float(volume.iloc[-6:-1].mean())
            volume_ratio = current_vol / avg_vol_5 if avg_vol_5 > 0 else 1.0
            
            # 获取位置信息辅助判断 (v4.2优化)
            position_pct = 0.5
            try:
                lookback = min(len(close), 250)
                year_high = float(close.iloc[-lookback:].max())
                year_low = float(close.iloc[-lookback:].min())
                current_price = float(close.iloc[-1])
                position_pct = (current_price - year_low) / (year_high - year_low + 1e-6)
            except:
                pass
            is_low_pos = position_pct < 0.3

            if 1.5 <= volume_ratio <= 3.0:
                score += 25  # 【提升】温和放量，资金流入（从20提升到25）
            elif 1.2 <= volume_ratio < 1.5:
                score += 15  # 【提升】略微放量（从10提升到15）
            elif 0.8 <= volume_ratio < 1.2:
                score += 0   # 量能平稳
            elif volume_ratio > 3.0:
                if is_low_pos:
                    score += 35  # 【大幅提升】底部巨量，往往是主力建仓或强启动（从25提升到35）
                    signals.append('🔥 底部巨量(量比>3)，强启动信号')
                else:
                    score -= 5   # 高位/中位异常放量，需警惕出货
                    signals.append('⚠️ 异常巨量(量比>3)')
            else:
                score -= 15  # 缩量严重

            # 3. 连续放量天数评分（主力吸筹强化）
            consecutive_vol_up = 0
            for i in range(1, min(6, len(volume))):
                if float(volume.iloc[-i]) > float(volume.iloc[-i-1]):
                    consecutive_vol_up += 1
                else:
                    break

            if 2 <= consecutive_vol_up <= 4:
                score += 20  # 【提升】连续放量，资金持续流入（主力吸筹，从15提升到20）
            elif consecutive_vol_up >= 5:
                score += 15  # 【提升】放量过久需注意（从10提升到15）
            elif consecutive_vol_up == 1:
                score += 8   # 【提升】单日放量（从5提升到8）

            # 4. 伸缩倍量柱检测 (v4.2)
            # 逻辑：前天缩量，昨天倍量，今天缩量/放量均可，关键是中间的倍量柱确立资金介入
            # 近5天内是否存在倍量柱 (Vol > 2 * PrevVol) 且位置处于低位
            double_vol_signal = False
            if len(volume) >= 5 and is_low_pos:
                for i in range(1, 4): # 检查最近3天
                    curr = float(volume.iloc[-i])
                    prev = float(volume.iloc[-i-1])
                    if prev > 0 and curr / prev >= 1.95:
                        double_vol_signal = True
                        break
            
            if double_vol_signal:
                score += 25  # 【大幅提升】底部倍量柱(主力吸筹)加分从15提升到25
                signals.append('🔥 底部倍量柱(主力吸筹)')

            # 5. MACD底部反转检测 (v4.2)
            # 逻辑：MACD金叉 + (底背离 OR 零轴附近)
            macd_reversal = False
            try:
                from analysis.technical_analysis import TechnicalAnalysis
                macd, signal, hist = TechnicalAnalysis.calculate_macd(close)
                
                # 最近3天内金叉
                golden_cross = False
                for i in range(1, 4):
                    if float(macd.iloc[-i]) > float(signal.iloc[-i]) and float(macd.iloc[-i-1]) <= float(signal.iloc[-i-1]):
                        golden_cross = True
                        break
                
                if golden_cross and is_low_pos:
                    macd_reversal = True
            except:
                pass
            
            if macd_reversal:
                score += 10
                signals.append('MACD底部反转金叉')

            # 共振加分：倍量柱 + MACD反转
            if double_vol_signal and macd_reversal:
                score += 15
                signals.append('🔥 缩量倍量+MACD共振(强买点)')

            # 6. 价涨量增检测（最近一天）
            last_price_up = float(close.iloc[-1]) > float(close.iloc[-2])
            last_vol_up = float(volume.iloc[-1]) > float(volume.iloc[-2])

            if last_price_up and last_vol_up:
                score += 10  # 价涨量增，最健康信号
            elif not last_price_up and not last_vol_up:
                score += 5   # 价跌量缩，正常调整
            elif last_price_up and not last_vol_up:
                score -= 5   # 价涨量缩，上涨乏力
            else:
                score -= 10  # 价跌量增，抛压较重

            score = max(0, min(100, score))

            volume_health = '健康'
            if score >= 70:
                volume_health = '非常健康'
            elif score >= 55:
                volume_health = '健康'
            elif score >= 40:
                volume_health = '一般'
            else:
                volume_health = '较差'

            details = {
                'volume_ratio': round(volume_ratio, 2),
                'same_direction_rate': round(same_direction_rate, 2),
                'consecutive_vol_up_days': consecutive_vol_up,
                'last_price_up': last_price_up,
                'last_vol_up': last_vol_up,
                'signals': signals,
                'volume_health': volume_health
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"量价健康度评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_liquidity(self, stock_code: str,
                         historical_data: Optional[pd.DataFrame],
                         fundamental_data: Optional[Dict] = None) -> Tuple[float, Dict]:
        """
        流动性评分 (0-100分) - v4.0 新增

        核心理念（游资思维）:
        1. 流动性是交易的基础，低流动性股票无法快速进出
        2. 换手率反映市场活跃度，过低则无人关注
        3. 成交额反映资金承载力，太小的股票不适合大资金操作
        4. 市值适中更容易被资金推动

        评分逻辑:
        - 基准分50分
        - 20日均成交额评估：<3000万扣分，>1亿加分
        - 换手率评估：<1%扣分，2-8%最佳
        - 流通市值评估：50-200亿最佳
        - 成交额波动：稳定性好加分
        """
        try:
            score = 50.0  # 基准分
            signals = []

            avg_amount_20d = 0.0
            avg_turnover_20d = 0.0
            amount_volatility = 0.0
            circulation_market_cap = 0.0

            has_amount_data = False
            has_turnover_data = False
            # 从历史数据计算成交额和换手率
            if historical_data is not None and not historical_data.empty:
                if 'amount' in historical_data.columns and len(historical_data) >= 20:
                    amount = historical_data['amount']
                    # 计算20日均成交额
                    recent_amount = amount.iloc[-20:]
                    avg_amount_20d = float(recent_amount.mean())
                    # 计算成交额波动率
                    if avg_amount_20d > 0:
                        amount_volatility = float(recent_amount.std() / avg_amount_20d)
                    has_amount_data = True

                if 'turnover_rate' in historical_data.columns and len(historical_data) >= 20:
                    turnover = historical_data['turnover_rate']
                    avg_turnover_20d = float(turnover.iloc[-20:].mean())
                    has_turnover_data = True

            # 从基本面数据获取流通市值
            if fundamental_data:
                # 兼容嵌套结构
                if 'financial_indicators' in fundamental_data:
                    indicators = fundamental_data.get('financial_indicators', {})
                    circ_cap = indicators.get('circulation_market_cap')
                else:
                    circ_cap = fundamental_data.get('circulation_market_cap')
                    
                if isinstance(circ_cap, (int, float)):
                    circulation_market_cap = float(circ_cap)

            # ========== 1. 成交额评分 ==========
            # 单位转换：根据数值大小判断单位
            amount_wan = avg_amount_20d
            if avg_amount_20d > 1e8:  # 可能是元
                amount_wan = avg_amount_20d / 1e4
            elif avg_amount_20d > 1e6:  # 可能是元（但较小）
                amount_wan = avg_amount_20d / 1e4
            # 如果已经是万元级别则不转换

            if has_amount_data and amount_wan < 1000:
                score -= 25  # 成交额极低，流动性极差
                signals.append('🚨 成交额极低(<1000万)')
            elif has_amount_data and amount_wan < 3000:
                score -= 15  # 成交额偏低
                signals.append('⚠️ 成交额偏低(<3000万)')
            elif has_amount_data and amount_wan < 5000:
                score -= 5   # 成交额一般
            elif has_amount_data and amount_wan >= 10000:
                score += 20  # 成交额充足（>1亿）
                signals.append('成交额充足(>1亿)')
            elif has_amount_data and amount_wan >= 5000:
                score += 10  # 成交额良好

            # ========== 2. 换手率评分 ==========
            if has_turnover_data and avg_turnover_20d > 0:
                if avg_turnover_20d < 0.5:
                    score -= 15  # 换手率极低，无人关注
                    signals.append('⚠️ 换手率极低(<0.5%)')
                elif avg_turnover_20d < 1.0:
                    score -= 8   # 换手率偏低
                elif 2.0 <= avg_turnover_20d <= 8.0:
                    score += 15  # 最佳换手率区间
                    signals.append('换手率活跃(2-8%)')
                elif avg_turnover_20d > 15:
                    score -= 5   # 换手率过高，可能过度投机
                    signals.append('换手率过��(>15%)')
                elif avg_turnover_20d > 8.0:
                    score += 5   # 换手率偏高但可接受

            # ========== 3. 流通市值评分 (-20 ~ +15) ==========
            if circulation_market_cap > 0:
                if circulation_market_cap < 20:
                    score -= 10  # 市值太小，容易被操纵
                    signals.append('⚠️ 流通市值偏小(<20亿)')
                elif circulation_market_cap < 50:
                    score += 5   # 小市值，弹性好
                elif 50 <= circulation_market_cap <= 200:
                    score += 15  # 最佳市值区间
                    signals.append('市值适中(50-200亿)')
                elif circulation_market_cap <= 500:
                    score += 5   # 中等市值
                elif circulation_market_cap > 1000:
                    score -= 15  # 超大市值，弹性差，不适合短线爆发
                    signals.append('🚨 超大市值(>1000亿)，弹性较差')
                elif circulation_market_cap > 500:
                    score -= 5   # 大市值，弹性一般
                    signals.append('大市值(>500亿)')

            # ========== 4. 成交额稳定性评分 (-5 ~ +10) ==========
            if amount_volatility > 0:
                if amount_volatility < 0.3:
                    score += 10  # 成交额非常稳定
                    signals.append('成交额稳定')
                elif amount_volatility < 0.5:
                    score += 5   # 成交额较稳定
                elif amount_volatility > 1.0:
                    score -= 5   # 成交额波动大
                    signals.append('成交额波动大')

            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            # 流动性等级判定
            liquidity_level = '一般'
            if score >= 75:
                liquidity_level = '优秀'
            elif score >= 60:
                liquidity_level = '良好'
            elif score >= 45:
                liquidity_level = '一般'
            elif score >= 30:
                liquidity_level = '较差'
            else:
                liquidity_level = '极差'

            if not has_amount_data and not has_turnover_data:
                details = {
                    'error': '缺少成交额/换手率数据',
                    'avg_amount_20d_wan': 0,
                    'avg_turnover_20d': 0,
                    'amount_volatility': round(amount_volatility, 3),
                    'circulation_market_cap': round(circulation_market_cap, 2),
                }
            else:
                details = {
                    'avg_amount_20d_wan': round(amount_wan, 2),
                    'avg_turnover_20d': round(avg_turnover_20d, 2),
                    'amount_volatility': round(amount_volatility, 3),
                    'circulation_market_cap': round(circulation_market_cap, 2),
                    'liquidity_level': liquidity_level,
                    'signals': signals,
                    'scoring_method': 'v4.0_liquidity'
                }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"流动性评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _check_exclusion_rules(self, result: Dict,
                               historical_data: Optional[pd.DataFrame],
                               low_pos_bonus: float = 0.0) -> list:
        """
        一票否决检查 - v4.0 强化风控版

        核心理念：宁可错过，不可套牢！

        触发任一条件则标记为严重风险，实施一票否决（大幅扣分）:
        - 60日涨幅超80%：主力大概率已出货
        - 20日涨幅超50%：短期涨幅过大，接盘风险
        - 距离年内高点<5%：追高风险极大
        - 连涨超7天：连续逼空，回调风险
        - 20日均成交额<3000万：流动性风险
        - 利润同比下滑超70%：业绩暴雷
        - RSI极度超买(>90)：技术超买
        - 连续跌停：重大风险信号
        """
        exclusion_flags = []

        try:
            # ========== 1. 涨幅风险检查（最核心）==========
            momentum_details = result.get('details', {}).get('momentum', {})

            change_5d = momentum_details.get('change_5d', 0)
            change_20d = momentum_details.get('change_20d', 0)
            change_60d = momentum_details.get('change_60d', 0)
            position_pct = momentum_details.get('position_pct', 0.5)
            distance_from_high = momentum_details.get('distance_from_high', 50)
            consecutive_up = momentum_details.get('consecutive_up_days', 0)

            # 60日涨幅超80% - 一票否决
            if change_60d > self.EXCLUSION_RULES['max_change_60d']:
                exclusion_flags.append(f'🚨 60日涨幅{change_60d:.1f}%，超过{self.EXCLUSION_RULES["max_change_60d"]}%阈值')

            # 20日涨幅超50% - 一票否决
            if change_20d > self.EXCLUSION_RULES['max_change_20d']:
                exclusion_flags.append(f'🚨 20日涨幅{change_20d:.1f}%，超过{self.EXCLUSION_RULES["max_change_20d"]}%阈值')

            # 距离年内高点<5% - 一票否决
            if distance_from_high < self.EXCLUSION_RULES['max_distance_from_high']:
                exclusion_flags.append(f'🚨 距年内高点仅{distance_from_high:.1f}%，追高风险')

            # 连涨超7天 - 一票否决
            if consecutive_up >= self.EXCLUSION_RULES['max_consecutive_up']:
                exclusion_flags.append(f'🚨 连涨{consecutive_up}天，回调风险极大')

            # ========== 2. RSI超买检查 ==========
            tech_details = result.get('details', {}).get('technical', {})
            rsi = tech_details.get('RSI')

            # 计算当前价格在近一年区间的位置（用于底部豁免）
            is_low_position = position_pct < 0.30 if position_pct else False

            # 如果不是底部启动，RSI>90触发一票否决
            rsi_threshold = 90
            if low_pos_bonus > 0 or is_low_position:
                rsi_threshold = 98  # 底部启动时放宽RSI限制

            if rsi is not None and rsi > rsi_threshold:
                exclusion_flags.append(f'🚨 RSI极度超买({rsi:.1f})')

            # ========== 3. 流动性风险检查（v4.1增强）==========
            # 优先使用已计算的流动性评分数据
            liquidity_details = result.get('details', {}).get('liquidity', {})

            if liquidity_details and 'error' not in liquidity_details:
                # 使用已计算的流动性数据
                avg_amount_wan = liquidity_details.get('avg_amount_20d_wan', 0)
                avg_turnover = liquidity_details.get('avg_turnover_20d', 0)

                # 成交额检查 (已移除)
                # if avg_amount_wan < self.EXCLUSION_RULES.get('min_avg_amount_20d', 0):
                #     exclusion_flags.append(f'⚠️ 20日均成交额{avg_amount_wan:.0f}万，流动性不足')

                # v4.1新增：换手率检查 (已移除)
                # if avg_turnover < self.EXCLUSION_RULES.get('min_turnover_rate', 0):
                #     exclusion_flags.append(f'⚠️ 20日均换手率{avg_turnover:.2f}%，交易不活跃')

            elif historical_data is not None and not historical_data.empty and 'amount' in historical_data.columns:
                # 降级：从历史数据计算
                try:
                    amount = historical_data['amount']
                    if len(amount) >= 20:
                        avg_amount_20d = float(amount.iloc[-20:].mean())
                        # 判断单位
                        if avg_amount_20d > 1e8:
                            avg_amount_wan = avg_amount_20d / 1e4
                        else:
                            avg_amount_wan = avg_amount_20d

                        # if avg_amount_wan < self.EXCLUSION_RULES.get('min_avg_amount_20d', 0):
                        #     exclusion_flags.append(f'⚠️ 20日均成交额{avg_amount_wan:.0f}万，流动性不足')
                except Exception:
                    pass

            # ========== 4. 基本面风险检查 ==========
            fund_details = result.get('details', {}).get('fundamental', {})
            profit_yoy = fund_details.get('net_profit_yoy')
            if profit_yoy is not None and isinstance(profit_yoy, (int, float)):
                if profit_yoy < self.EXCLUSION_RULES['min_profit_yoy']:
                    exclusion_flags.append(f'🚨 利润同比下滑{abs(profit_yoy):.1f}%，业绩暴雷')

            # ========== 5. 连续跌停检查 ==========
            if historical_data is not None and not historical_data.empty:
                close = historical_data['close']
                if len(close) >= 4:
                    limit_down_count = 0
                    for i in range(1, 4):
                        change = (float(close.iloc[-i]) / float(close.iloc[-i-1]) - 1) * 100
                        if change < -9.5:  # 接近跌停
                            limit_down_count += 1

                    if limit_down_count >= 2:
                        exclusion_flags.append(f'🚨 近期连续跌停({limit_down_count}次)，重大风险')

            # ========== 6. 量价背离检查 ==========
            vol_details = result.get('details', {}).get('volume_health', {})
            same_dir_rate = vol_details.get('same_direction_rate', 0.5)
            if same_dir_rate < 0.2:
                exclusion_flags.append('⚠️ 量价严重背离，可能是假突破')

            # ========== 7. MACD顶背离检查 ==========
            macd_status = tech_details.get('MACD')
            if macd_status == '死叉' and change_20d > 20:
                exclusion_flags.append('⚠️ 疑似MACD顶背离（价格涨但MACD死叉）')

        except Exception as e:
            logger.error(f"一票否决检查失败: {e}")

        return exclusion_flags

    def _score_investor_sentiment(self, stock_code: str, momentum_details: Dict = None) -> Tuple[float, Dict]:
        """
        股民情绪评分 (0-100分) - v4.1 游资思维重构版（动态反指标处理）

        核心理念（游资逆向思维 + 趋势阶段结合）:
        1. 散户情绪是反指标：当大家都看多时，往往是顶部
        2. 当大家都恐慌时，往往是底部
        3. 但在主升浪中，高情绪是正常的，不应过度惩罚
        4. 关键是结合股票所处位置/阶段来判断

        v4.1改进：
        - 底部区域：悲观情绪是买入机会
        - 中部区域：中性情绪最佳
        - 高位区域��过度乐观才需警惕
        - 主升浪：高情绪是正常的，不过度惩罚
        """
        try:
            analyzer = InvestorSentimentAnalyzer(stock_code)
            sentiment_data = analyzer.get_comprehensive_sentiment(verbose=False)

            if sentiment_data:
                raw_score = sentiment_data.get('comprehensive_score', 50)
                sentiment_label = sentiment_data.get('comprehensive_sentiment', '中性')

                # 获取位置信息（从momentum_details或默认��）
                position_pct = 0.5
                change_20d = 0
                if momentum_details:
                    position_pct = momentum_details.get('position_pct', 0.5)
                    change_20d = momentum_details.get('change_20d', 0)

                # 判断趋势阶段
                is_bottom = position_pct < 0.30
                is_middle = 0.30 <= position_pct <= 0.65
                is_high = position_pct > 0.65
                is_uptrend = change_20d > 10  # 近20日涨幅>10%视为上升趋势

                # ========== v4.1 动态反指标转换 ==========
                score = 50.0
                contrarian_signal = '中性'

                if is_bottom:
                    # 底部区域：悲观情绪是强机会，乐观情绪可能是诱多
                    if raw_score <= 25:
                        score = 90
                        contrarian_signal = '底部极度悲观（强买入机会）'
                    elif raw_score <= 35:
                        score = 80
                        contrarian_signal = '底部悲观情绪（买入机会）'
                    elif raw_score <= 45:
                        score = 70
                        contrarian_signal = '底部中性偏悲观'
                    elif raw_score <= 60:
                        score = 60
                        contrarian_signal = '底部中性'
                    elif raw_score <= 75:
                        score = 45
                        contrarian_signal = '底部偏乐观（可能诱多）'
                    else:
                        score = 35
                        contrarian_signal = '底部过度乐观（警惕诱多）'

                elif is_middle:
                    # 中部区域：中性情绪最佳，极端情绪都需注意
                    if 40 <= raw_score <= 60:
                        score = 70
                        contrarian_signal = '中性情绪（最佳状态）'
                    elif 30 <= raw_score < 40:
                        score = 65
                        contrarian_signal = '轻微悲观（可能有机会）'
                    elif 60 < raw_score <= 70:
                        score = 55
                        contrarian_signal = '轻微乐观'
                    elif raw_score < 30:
                        score = 75
                        contrarian_signal = '悲观情绪（机会）'
                    elif 70 < raw_score <= 80:
                        score = 45
                        contrarian_signal = '过度乐观（谨慎）'
                    else:
                        score = 35
                        contrarian_signal = '极度乐观（警惕）'

                else:  # is_high
                    # 高位区域：情绪判断最关键
                    if is_uptrend:
                        # 主升浪中，高情绪正常，不过度惩罚
                        if raw_score >= 85:
                            score = 40
                            contrarian_signal = '主升浪极度乐观（注意）'
                        elif raw_score >= 75:
                            score = 50
                            contrarian_signal = '主升浪高情绪（正常）'
                        elif raw_score >= 60:
                            score = 55
                            contrarian_signal = '主升浪情绪稳定'
                        elif raw_score >= 45:
                            score = 60
                            contrarian_signal = '主升浪情绪分歧'
                        else:
                            score = 45
                            contrarian_signal = '主升浪悲观（可能见顶）'
                    else:
                        # 高位但无上升趋势，严格反指标
                        if raw_score >= 85:
                            score = 20
                            contrarian_signal = '高位极度乐观（强烈警惕）'
                        elif raw_score >= 75:
                            score = 30
                            contrarian_signal = '高位过度乐观（警惕）'
                        elif raw_score >= 60:
                            score = 45
                            contrarian_signal = '高位偏乐观'
                        elif raw_score >= 45:
                            score = 55
                            contrarian_signal = '高位中性'
                        else:
                            score = 60
                            contrarian_signal = '高位悲观（可能调整）'

                details = {
                    'raw_sentiment_score': raw_score,
                    'raw_sentiment_label': sentiment_label,
                    'contrarian_score': score,
                    'contrarian_signal': contrarian_signal,
                    'position_pct': position_pct,
                    'change_20d': change_20d,
                    'trend_stage': '底部' if is_bottom else ('中部' if is_middle else '高位'),
                    'is_uptrend': is_uptrend,
                    'guba_sentiment': sentiment_data.get('guba_sentiment', {}),
                    'overall_market': sentiment_data.get('overall_market_sentiment', {}),
                    'capital_flow': sentiment_data.get('capital_flow', {}),
                    'dragon_tiger': sentiment_data.get('dragon_tiger', {}),
                    'bonus_reasons': sentiment_data.get('bonus_reasons', []),
                    'scoring_method': 'v4.1_dynamic_contrarian'
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

    def _score_fundamental(self, stock_code: str, external_data: Optional[Dict] = None) -> Tuple[float, Dict]:
        """
        基本面评分 (0-100分)

        评分维度:
        - PE/PB估值水平
        - 营收增长率
        - 净利润增长率
        - 现金流状况
        """
        try:
            if external_data:
                # 检查是否为嵌套结构 (get_comprehensive_data返回的格式)
                if 'financial_indicators' in external_data:
                    indicators = external_data.get('financial_indicators', {})
                    reports = external_data.get('financial_reports', {})
                else:
                    # 使用外部传入的数据（快速模式/扁平结构）
                    indicators = {
                        'pe_ratio': external_data.get('pe_ratio', 'N/A'),
                        'pb_ratio': external_data.get('pb_ratio', 'N/A'),
                        'total_market_cap': external_data.get('total_market_cap', 'N/A'),
                        'circulation_market_cap': external_data.get('circulation_market_cap', 'N/A'),
                    }
                    reports = {
                        'revenue_yoy': external_data.get('revenue_yoy', 'N/A'),
                        'net_profit_yoy': external_data.get('net_profit_yoy', 'N/A'),
                    }
            else:
                # 传统模式：单独采集
                collector = FundamentalDataCollector(stock_code)
                fundamental_data = collector.get_comprehensive_data()

                if not fundamental_data:
                    return 50.0, {'error': '无基本面数据'}

                indicators = fundamental_data.get('financial_indicators', {})
                reports = fundamental_data.get('financial_reports', {})

            score = 50.0
            market_cap_yi = 0.0
            signals = []

            pe = indicators.get('pe_ratio')
            if isinstance(pe, (int, float)):
                if pe < 20:
                    score += 20
                elif pe <= 40:
                    score += 10
                elif pe > 50:
                    score -= 20

            # 小市值加分 (新增)
            # 逻辑：市值越小越容易被资金推动
            total_mv = indicators.get('total_market_cap')
            if isinstance(total_mv, (int, float)) and total_mv > 0:
                # 自动推断单位：如果是元(>1亿)，转换为亿；如果是万元(>1万)，转换为亿
                mv_yi = total_mv
                if total_mv > 100000000:  # 可能是元
                    mv_yi = total_mv / 100000000.0
                elif total_mv > 10000:    # 可能是万元
                    mv_yi = total_mv / 10000.0
                
                market_cap_yi = round(mv_yi, 2)

                # 仅当PE非亏损时才加分，避免炒作垃圾股
                is_loss = isinstance(pe, str) and '亏损' in pe
                if isinstance(pe, (int, float)) and pe < 0:
                    is_loss = True

                if is_loss:
                    score -= 20  # 亏损股大幅扣分
                    signals.append('⚠️ 业绩亏损')
                else:
                    if mv_yi < 50:    # 50亿以下，核心加分区间
                        score += 5    # 降低加分 (原15分)
                    elif mv_yi < 100:  # 50-100亿，次级加分
                        score += 2    # 降低加分 (原5分)
                    elif mv_yi > 2000: # 2万亿以上，超级巨头，游资回避
                        score -= 40
                    elif mv_yi > 1000: # 千亿大盘，大幅减分
                        score -= 25
                    elif mv_yi > 500: # 500亿以上，减分
                        score -= 10
                    elif mv_yi > 200: # 200亿以上，微量减分
                        score -= 5

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
                'total_market_cap': indicators.get('total_market_cap'),
                'market_cap_yi': market_cap_yi,
                'signals': signals
            }

            return round(score, 2), details
        except Exception as e:
            logger.error(f"基本面评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _score_events(self, stock_code: str, global_hot_news: Optional[list] = None) -> Tuple[float, Dict]:
        """
        消息面评分 (0-100分)

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

            # 🔥 接入全市场热门新闻TOPN并为强关联股票加分
            try:
                if global_hot_news:
                    analyzer_for_relation = EventAnalyzer(stock_code, news_data=news_data)
                    related = []
                    bonus = 0.0
                    # 规则：每条强关联热门新闻 +2 分；若热度>=80额外+1 分；总加分封顶15分
                    for item in global_hot_news:
                        title = (item.get('title') or '').strip()
                        url = (item.get('url') or '').strip()
                        source = item.get('source') or ''
                        summary_text = item.get('summary') or ''
                        try:
                            # 复用事件分析器的强关联判断
                            is_related = analyzer_for_relation._is_strongly_related_news(
                                title=title, url=url, source=source, summary=summary_text
                            )
                        except Exception:
                            is_related = False

                        if is_related:
                            related.append({
                                'title': title,
                                'url': url,
                                'source': source,
                                'rank': item.get('rank'),
                                'heat': item.get('heat'),
                                'publish_time': item.get('publish_time')
                            })
                            inc = 2.0
                            heat = item.get('heat') or 0
                            if isinstance(heat, (int, float)) and heat >= 80:
                                inc += 1.0
                            bonus += inc

                    bonus = min(15.0, bonus)
                    if bonus > 0:
                        score = max(0, min(100, score + bonus))
                        # 详情中记录加分来源
                        details['hot_news_bonus'] = round(bonus, 2)
                        details['hot_news_related_count'] = len(related)
                        # 只展示前3个以避免过长
                        details['hot_news_matches'] = related[:3]
            except Exception as e:
                logger.warning(f"热门新闻加分流程失败: {e}")

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
        根据当前股票的状态选择动态权重模板 - v4.0 游资思维重构版

        选择逻辑���基于位置和信号质量）:
        - bottom_start: 处于低位（position_pct < 0.35）且有启动信号
        - trend_continuation: 趋势已确立且量价健康
        - news_driven: 有重大消息催化
        - base: 默认均衡配置

        Returns:
            (weights_dict, mode_name)
        """
        try:
            momentum_details = result.get('details', {}).get('momentum', {})
            vol_health_details = result.get('details', {}).get('volume_health', {})
            tech_details = result.get('details', {}).get('technical', {})
            events_details = result.get('details', {}).get('events', {})
            scores = result.get('scores', {})

            position_pct = float(momentum_details.get('position_pct', 0.5) or 0.5)
            momentum_signals = momentum_details.get('signals', [])
            volume_health = vol_health_details.get('volume_health', '一般')
            ma_status = tech_details.get('MA_status', '中性')
            events_score = float(scores.get('events', 50) or 50)
            hot_news_bonus = float(events_details.get('hot_news_bonus', 0) or 0)

            # 检测是否有底部启动信号
            has_bottom_signal = any('底部' in s or '启动' in s or '🔥' in s for s in momentum_signals)
            has_low_position = position_pct < 0.35

            # 检测是否有趋势确立信号
            has_trend = ma_status in ['多头排列', '强多头排列']
            has_healthy_volume = volume_health in ['健康', '非常健康']

            # 检测是否有消息驱动
            has_news_catalyst = hot_news_bonus >= 5 or events_score >= 70

            # ========== 选择权重模板 ==========
            # 1. 底部启动模板：低位+有启动信号
            if has_low_position and has_bottom_signal:
                return self.DYNAMIC_WEIGHT_PROFILES['bottom_start'], 'bottom_start'

            # 2. 趋势接力模板：趋势确立+量价健康
            if has_trend and has_healthy_volume:
                return self.DYNAMIC_WEIGHT_PROFILES['trend_continuation'], 'trend_continuation'

            # 3. 消息驱动模板：有重大消息催化
            if has_news_catalyst:
                return self.DYNAMIC_WEIGHT_PROFILES['news_driven'], 'news_driven'

            # 4. 默认使用基础权重
            return self.DYNAMIC_WEIGHT_PROFILES['base'], 'base'

        except Exception as ex:
            logger.warning(f"动态权重选择失败，使用基础权重: {ex}")
            return self.DYNAMIC_WEIGHT_PROFILES['base'], 'base'

    def _score_dragon_tiger(self, stock_code: str, sentiment_details: Dict) -> Tuple[float, Dict]:
        """
        龙虎榜评分 (0-100分)

        评分规则:
        - 未上榜: 50分 (基准分)
        - 上榜: 根据净买入金额和上榜原因加分
          - 净买入 > 1000万: +20分
          - 净买入 500-1000万: +15分
          - 净买入 100-500万: +10分
          - 净买入 < 100万: +5分
          - 净卖出(负值): 基于卖出额扣分
          - 涨停板上榜: +10分
          - 跌停板上榜: -10分
          - 涨幅偏离: +5分
          - 跌幅偏离: -5分

        Args:
            stock_code: 股票代码
            sentiment_details: 情绪分析详情（包含龙虎榜数据）

        Returns:
            (得分, 详情字典)
        """
        try:
            dragon_tiger = sentiment_details.get('dragon_tiger', {})

            if not dragon_tiger or 'error' in dragon_tiger:
                return 50.0, {'error': '无龙虎榜数据'}

            has_records = dragon_tiger.get('has_records', False)

            if not has_records:
                return 50.0, {
                    'on_list': False,
                    'score': 50.0,
                    'reason': '未上榜'
                }

            score = 50.0

            # 获取最近一次记录的净买入金额和上榜原因
            records = dragon_tiger.get('records', [])
            if not records:
                return 50.0, {
                    'on_list': False,
                    'score': 50.0,
                    'reason': '未上榜'
                }

            latest_record = records[0]
            net_buy = latest_record.get('net_buy_amount', 0) or 0
            reason = dragon_tiger.get('last_reason', '')
            last_date = dragon_tiger.get('last_date', 'N/A')

            # 根据净买入金额加分/扣分
            if net_buy > 100000000:  # 1亿以上净买入
                score += 30
            elif net_buy > 50000000:  # 5000万-1亿净买入
                score += 25
            elif net_buy > 10000000:  # 1000-5000万净买入
                score += 20
            elif net_buy > 5000000:  # 500-1000万净买入
                score += 15
            elif net_buy > 1000000:  # 100-500万净买入
                score += 10
            elif net_buy > 0:  # 小额净买入
                score += 5
            elif net_buy < -100000000:  # 1亿以上净卖出
                score -= 30
            elif net_buy < -50000000:  # 5000万-1亿净卖出
                score -= 25
            elif net_buy < -10000000:  # 1000-5000万净卖出
                score -= 20
            elif net_buy < -5000000:  # 500-1000万净卖出
                score -= 15
            elif net_buy < -1000000:  # 100-500万净卖出
                score -= 10
            else:  # 小额净卖出
                score -= 5

            # 根据上榜原因调整
            if '涨停' in reason:
                score += 10
            elif '跌停' in reason:
                score -= 10

            if '涨幅偏离' in reason or '涨幅达到' in reason:
                score += 5
            elif '跌幅偏离' in reason or '跌幅达到' in reason:
                score -= 5

            # 确保分数在0-100范围内
            score = max(0, min(100, score))

            details = {
                'on_list': True,
                'score': score,
                'net_buy_amount': net_buy,
                'reason': reason,
                'last_date': last_date,
                'recent_positive': dragon_tiger.get('recent_positive', 0),
                'recent_negative': dragon_tiger.get('recent_negative', 0)
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"龙虎榜评分失败: {e}")
            return 50.0, {'error': str(e)}


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
            print(f"  消息面: {result['scores']['events']:.2f} (权重 {pct('events')}%)")
            print(f"  龙虎榜: {result['scores']['dragon_tiger']:.2f} (权重 {pct('dragon_tiger')}%)")
        else:
            print(f"\n✗ 评分失败")


if __name__ == "__main__":
    main()
