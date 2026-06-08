#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会多维度打分系统 v5.6 - 深度回测优化版
=====================================

v5.6更新（13824组合网格搜索优化，Top3: 5d=+3.42%, wr=54.9%）:
- 卖出占优惩罚: sell_signals > buy_signals 扣5分（回测: sell_ratio>0.1表现差-3.25%）
- 评分甜蜜区奖励: 65-75分区间加5分（回测: 70-75分区间最优+1.16%）
- 过高评分惩罚: 88分以上扣5分（回测: 85+分反而-1.94%, wr仅25.6%，过拟合信号）

v5.5基础（保留）:
- 牛股/妖股动量识别: 7种模式，最多+25分，惩罚回收最多15分
- 涨停条件淘汰: chase>=50或buy>8才淘汰（非一刀切）
- 技术面动量豁免: 均线多头/妖股模式/启动模式可绕过tech<60
- 量化基准分55，买入奖励上限18
- 惩罚累计上限30分
- 移除大市值惩罚

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
import json
import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, List
import logging
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.technical_analysis import TechnicalAnalysis, QuantitativeModels
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.news_sentiment_collector import NewsSentimentCollector
from analysis.event_analyzer import EventAnalyzer

try:
    from analysis.advanced_analysis import AdvancedAnalyzer
    ADVANCED_ANALYSIS_AVAILABLE = True
except ImportError:
    ADVANCED_ANALYSIS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("高级分析模块未加载，部分功能不可用")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def write_signals_sidecar(results, report_path):
    """Persist per-stock structured risk signals next to the markdown report.

    `results` are the rich per-stock dicts the scorer already builds. Sidecar is
    `<report stem>.signals.json` in the same directory. Best-effort: a flat list
    keyed by code with the fields the command-center risk engine needs.
    """
    from pathlib import Path

    report_path = Path(report_path)
    out = report_path.with_suffix("").with_suffix(".signals.json")
    payload = []
    for r in results or []:
        rs = dict(r.get("risk_signals") or {})
        payload.append({
            "code": r.get("code") or r.get("stock_code"),
            "name": r.get("name") or r.get("stock_name"),
            "total_score": r.get("total_score") or r.get("score"),
            "rating": r.get("rating"),
            "sector_score": (r.get("scores") or {}).get("sector"),
            "risk_signals": {
                "chase": rs.get("chase"),
                "rsi": rs.get("rsi"),
                "change_3d": rs.get("change_3d"),
                "sell_signals": rs.get("sell_signals"),
                "quant_score": rs.get("quant_score"),
                "limit_up_streak": rs.get("limit_up_streak"),
                "is_st": rs.get("is_st", False),
                "halt": rs.get("halt", False),
            },
        })
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


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
        'S': 85,   # S级 ≥85 强烈推荐
        'A+': 82,  # A+级 82-85
        'A': 78,   # A级 78-82
        'B': 70,   # B级 70-78
        'C': 0     # C级 <70
    }

    # 维度权重配置 (v5.1 深度回测数据驱动优化版)
    # 深度回测发现（2065条记录多因子分析）:
    #   - 量化分数90+收益-4.29% vs 0-50收益+4.03%（量化维度存在反转效应）
    #   - 卖出信号0-1收益+3.26%(wr 52.9%) - 低卖出信号是最强正向因子
    #   - RSI 85+收益-7.33% - 超买是最强负向因子
    #   - 位置时机（追高风险）与收益相关-0.14 - 仍是核心维度
    #   - 板块90+收益-4.29%，但80-90收益+11.54% - 非线性关系
    # 权重总和=1.0
    DIMENSION_WEIGHTS = {
        'position_timing': 0.12, # 【v22微调】从0.15降至0.12，减少对位置的依赖
        'volume_health': 0.24,   # 【v22提高】量价结构验证主力行为，提高权重
        'technical': 0.12,       # 【v22提高】技术分析，S级高分收益好
        'quantitative': 0.30,    # 【v22微降】买入信号多=胜率高，保留高权重
        'liquidity': 0.05,       # 流动性
        'sector': 0.08,          # 【v22提高】板块强度有区分度
        'dragon_tiger': 0.06,    # 龙虎榜
        'fundamental': 0.03,     # 【v22降低】基本面权重降低
        'events': 0.00,          # 【v21归零】回测中返回中性值,无实际贡献
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

    # 动态权重模板（总和均为1.0）- v5.1 深度回测数据驱动优化版
    # 深度回测多因子分析结论:
    #   - 量化维度存在反转效应: 分数越高实际收益越差, 需大幅降权
    #   - 低卖出信号(0-1)是最强正向因子(+3.26%, 52.9%胜率)
    #   - RSI 85+是最强负向因子(-7.33%/5d)
    #   - 3日涨幅>=15%后5日收益-4.99%(18.6%胜率), 需要强力过滤
    DYNAMIC_WEIGHT_PROFILES = {
        # 基础模板 (v19 提权量化模型)
        'base': {
            'position_timing': 0.22,
            'volume_health': 0.22,
            'technical': 0.08,
            'quantitative': 0.25,
            'liquidity': 0.05,
            'sector': 0.05,
            'dragon_tiger': 0.06,
            'fundamental': 0.04,
            'events': 0.03,
            'sentiment': 0.00,
        },
        # 底部启动模板：强化低位+量价，量化适度提权
        'bottom_start': {
            'position_timing': 0.28,
            'volume_health': 0.26,
            'technical': 0.10,
            'quantitative': 0.18,
            'liquidity': 0.04,
            'sector': 0.04,
            'dragon_tiger': 0.04,
            'fundamental': 0.04,
            'events': 0.02,
            'sentiment': 0.00,
        },
        # 趋势接力模板：量化提权
        'trend_continuation': {
            'position_timing': 0.20,
            'volume_health': 0.20,
            'technical': 0.10,
            'quantitative': 0.26,
            'liquidity': 0.04,
            'sector': 0.05,
            'dragon_tiger': 0.06,
            'fundamental': 0.04,
            'events': 0.05,
            'sentiment': 0.00,
        },
        # 消息驱动模板：量化适度提权
        'news_driven': {
            'position_timing': 0.20,
            'volume_health': 0.18,
            'technical': 0.08,
            'quantitative': 0.20,
            'liquidity': 0.04,
            'sector': 0.06,
            'dragon_tiger': 0.06,
            'fundamental': 0.04,
            'events': 0.10,
            'sentiment': 0.04,
        },
    }

    # 兼容旧接口：映射旧维度名到新维度
    _LEGACY_DIMENSION_MAP = {
        'momentum': 'position_timing',
        'dragon_tiger': 'liquidity',
    }

    def __init__(self):
        """初始化打分系统 v4.5"""
        self.RATING_THRESHOLDS = dict(type(self).RATING_THRESHOLDS)
        self.DIMENSION_WEIGHTS = dict(type(self).DIMENSION_WEIGHTS)
        self.EXCLUSION_RULES = dict(type(self).EXCLUSION_RULES)
        self._load_runtime_config()

        if ADVANCED_ANALYSIS_AVAILABLE:
            self.advanced_analyzer = AdvancedAnalyzer()
        else:
            self.advanced_analyzer = None

        # 初始化共享的数据获取器（复用连接，避免频繁初始化）
        self._data_fetcher = None
        # 关键：延迟初始化，避免启动阶段卡在Playwright/爬虫组件初始化上。
        # 这不改变任何业务逻辑，只改变初始化时机：真正需要取历史数据时再初始化。
        self._lazy_data_fetcher = os.environ.get('KRONOS_LAZY_DATA_FETCHER', '1').strip().lower() in ('1', 'true', 'yes', 'on')
        if not self._lazy_data_fetcher:
            self._init_data_fetcher()

    def _load_runtime_config(self):
        config_path = os.environ.get(
            'KRONOS_SCORING_CONFIG',
            os.path.join(project_root, 'config', 'scoring_runtime_config.json')
        )
        if not os.path.exists(config_path):
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except Exception as e:
            logger.warning(f"加载运行时评分配置失败: {e}")
            return

        try:
            rating_thresholds = config_data.get('rating_thresholds')
            if isinstance(rating_thresholds, dict):
                merged = dict(self.RATING_THRESHOLDS)
                for key, value in rating_thresholds.items():
                    if key in merged:
                        merged[key] = int(value)
                self.RATING_THRESHOLDS = merged

            dimension_weights = config_data.get('dimension_weights')
            if isinstance(dimension_weights, dict):
                merged = dict(self.DIMENSION_WEIGHTS)
                for key, value in dimension_weights.items():
                    if key in merged:
                        merged[key] = float(value)
                weight_sum = sum(merged.values())
                if weight_sum > 0:
                    merged = {k: v / weight_sum for k, v in merged.items()}
                self.DIMENSION_WEIGHTS = merged

            exclusion_rules = config_data.get('exclusion_rules')
            if isinstance(exclusion_rules, dict):
                merged = dict(self.EXCLUSION_RULES)
                for key, value in exclusion_rules.items():
                    if key in merged:
                        merged[key] = float(value)
                self.EXCLUSION_RULES = merged

            logger.info(f"✓ 已加载运行时评分配置: {config_path}")
        except Exception as e:
            logger.warning(f"应用运行时评分配置失败: {e}")

    def _init_data_fetcher(self):
        """初始化共享数据获取器"""
        if self._data_fetcher is not None:
            return
        try:
            t0 = time.time()
            logger.info("开始初始化共享数据获取器（MultiSourceDataFetcher）...")
            from scripts.fetch_data import MultiSourceDataFetcher
            self._data_fetcher = MultiSourceDataFetcher()
            logger.info(f"✓ 共享数据获取器初始化成功（耗时 {time.time() - t0:.2f}s）")
        except Exception as e:
            logger.warning(f"共享数据获取器初始化失败: {e}")
            self._data_fetcher = None

    def close(self):
        """关闭数据获取器"""
        if self._data_fetcher:
            try:
                import asyncio
                try:
                    asyncio.run(self._data_fetcher.close())
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(self._data_fetcher.close())
                    finally:
                        loop.close()
            except Exception:
                pass
            self._data_fetcher = None

    def calculate_comprehensive_score(self, stock_code: str,
                                     historical_data: Optional[pd.DataFrame] = None,
                                     global_hot_news: Optional[list] = None,
                                     fundamental_data: Optional[Dict] = None,
                                     market_data: Optional[Dict] = None) -> Dict:
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
            'exclusion_flags': [],
            'score_adjustments': []
        }

        try:
            # 准备历史数据，避免技术面/量化评分为0
            if historical_data is None or (hasattr(historical_data, 'empty') and historical_data.empty):
                historical_data = self._fetch_historical_data(stock_code)

            # 计算3日和5日涨幅 — 优先使用实时数据
            realtime_data = None
            if market_data and isinstance(market_data, dict):
                hot_stock = market_data.get('hot_stock_data')
                if hot_stock and isinstance(hot_stock, dict):
                    rt_price = hot_stock.get('latest_price')
                    rt_change = hot_stock.get('change_pct')
                    if rt_price and rt_change and rt_price > 0:
                        realtime_data = {
                            'latest_price': float(rt_price),
                            'change_pct': float(rt_change)
                        }
            price_changes = self._calculate_price_changes(historical_data, realtime_data=realtime_data)
            result['details']['price_changes'] = price_changes

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

            # ========== 超大市值过滤机制（已放开）==========
            # 用户要求放开大市值限制，不再过滤超大市值股票
            market_cap_yi = fundamental_details.get('market_cap_yi', 0)
            if not isinstance(market_cap_yi, (int, float)):
                market_cap_yi = 0

            # ========== v4.1 流动性前置优化 ==========
            # 1. 【v4.1调整】流动性评分 (8%) - 前置计算，确保一票否决可用
            liquidity_score, liquidity_details = self._score_liquidity(stock_code, historical_data, fundamental_data)
            result['scores']['liquidity'] = liquidity_score
            result['details']['liquidity'] = liquidity_details

            # 2. 量化模型评分 (18%)
            quant_score, quant_details = self._score_quantitative_models(stock_code, historical_data)
            result['scores']['quantitative'] = quant_score
            result['details']['quantitative'] = quant_details

            # 早期跳过: 量化买入信号 < 卖出信号，直接返回低分，省去后续分析
            quant_buy = quant_details.get('buy_count', 0)
            quant_sell = quant_details.get('sell_count', 0)
            if quant_buy < quant_sell:
                logger.info(f"{stock_code} 量化信号不佳(买{quant_buy}<卖{quant_sell})，跳过后续分析")
                result['total_score'] = 0.0
                result['rating'] = 'C'
                result['recommendation'] = f'量化信号不佳(买入{quant_buy}/卖出{quant_sell})，跳过'
                result['skip_reason'] = 'quant_buy_lt_sell'
                return result

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

            # v23+ P0-2: 保存基础七维加权分,用于最终单调性硬约束
            # 防止"基础分弱但靠单点爆点冲到 82+"的票污染 A 级
            base_seven_dim_score = total_score

            # [已放开] 超大市值惩罚机制 - 用户要求放开大市值限制，不再扣分

            # [新增] 卖出信号一票否决/降权机制
            # 如果量化评分过低(<45)或卖出信号多于买入信号，强制压低总分
            # 这里的目的是防止其他维度（如消息面/技术面）掩盖了模型给出的卖出信号
            quant_sell_count = quant_details.get('sell_count', 0)
            quant_buy_count = quant_details.get('buy_count', 0)

            quant_cap_limit = None
            score_adjustments = result.get('score_adjustments', [])
            
            if quant_score < 45:
                logger.info(f"{stock_code} 量化评分过低({quant_score})，触发总分封顶限制")
                score_adjustments.append(f"量化评分过低({quant_score:.1f})，触发总分封顶限制")
                quant_cap_limit = 60.0
            
            if quant_sell_count > quant_buy_count and quant_sell_count > 0:
                penalty = 15
                if quant_sell_count > 3:
                    penalty += 15
                total_score -= penalty
                logger.info(f"{stock_code} 卖出信号({quant_sell_count}) > 买入信号({quant_buy_count})，总分扣除 {penalty} 分")

            # [新增] 量化买入信号额外加权
            # 如果买入信号占主导，额外奖励总分，确保好股票能被选出
            quant_buy_bonus = self._compute_total_score_quant_buy_bonus(quant_buy_count, quant_sell_count, quant_score)
            if quant_buy_bonus > 0:
                before = total_score
                total_score = self._apply_headroom_bonus(total_score, quant_buy_bonus)
                logger.info(
                    f"{stock_code} 量化买入信号主导({quant_buy_count} > {quant_sell_count})，"
                    f"总分额外奖励 {quant_buy_bonus} 分(有效+{total_score - before:.2f})"
                )
            
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
                    before = total_score
                    total_score = self._apply_headroom_bonus(total_score, low_pos_bonus)
                    logger.info(f"{stock_code} 触发低位启动加分: +{low_pos_bonus}(有效+{total_score - before:.2f})")

            if quant_cap_limit is not None:
                total_score = min(total_score, quant_cap_limit)

            # v23+ P0-1: 量化分极端共识反指标硬约束
            # 实测 qs >= 95 胜率 42.86%(低于基线),回测打分加 -18,生产侧此前没有处理
            # 此处保守处理: -10 + 强制不进入 S 级(≤ 84)
            if quant_score >= 95:
                penalty = 10
                total_score -= penalty
                # 强制压在 A 级以下,防止"30 个模型一致看好"的过度共识冲到 S 级
                total_score = min(total_score, 84.0)
                logger.info(f"{stock_code} 量化分极端共识({quant_score:.0f}>=95) 反指标处理: -{penalty} 分 + 限 ≤ 84")
                score_adjustments.append(f"量化分极端({quant_score:.0f}): -{penalty} + 限 A 级以下(过度共识反指标)")

            total_score = self._clamp_score(total_score)

            # 一票否决：风险标记，降低评分（v8.0: 不淘汰，仅扣分，含上限保护）
            if exclusion_flags:
                # 区分严重风险（🚨）和警告风险（⚠️）
                critical_flags = [f for f in exclusion_flags if '🚨' in f]
                warning_flags = [f for f in exclusion_flags if '⚠️' in f]

                # v8.0: 严重风险扣分有上限，避免与后续v5.4惩罚重复叠加导致分数过低
                # 最多扣15分（原: 每个严重风险-15无上限，容易导致3个风险扣-45）
                raw_penalty = len(critical_flags) * 15 + len(warning_flags) * 5
                penalty = min(raw_penalty, 15)
                total_score = max(0, total_score - penalty)
                logger.warning(f"{stock_code} 风险标记: 严重{len(critical_flags)}个/警告{len(warning_flags)}个, 扣除{penalty}分(原始{raw_penalty})")

            # ========== v5.4 回测优化惩罚机制（含累计上限） ==========
            # 基于v5.3回测 + v5.4调整: 提高量化评分、设置惩罚上限避免分数过低
            # 累计惩罚上限30分，防止多重惩罚叠加导致筛选结果过少

            v54_total_penalty = 0  # 追踪v5.4惩罚累计值
            v54_total_bonus = 0    # 追踪v5.4奖励累计值
            V54_PENALTY_CAP = 25   # v20优化: 30→25 (更稳健, 避免过度惩罚)

            # 1. v21重构: 追高风险 → 强势动量奖励（真回测:chase>=75: 54.3%wr/+3.13%）
            chase_risk_score = result.get('advanced_analysis', {}).get('overall_score', {}).get('risk_metrics', {}).get('chase_risk_score', 0)
            if chase_risk_score == 0:
                chase_risk_score = result.get('details', {}).get('momentum', {}).get('chase_risk_score', 0)
            if chase_risk_score >= 75:
                chase_bonus = 4  # v21: 真回测chase>=75=54.3%wr
                v54_total_bonus += chase_bonus
                logger.info(f"{stock_code} 强势动量奖励: chase={chase_risk_score}>=75, 加{chase_bonus}分")
                score_adjustments.append(f"强势动量奖励: chase={chase_risk_score}>=75, 加{chase_bonus}分")
            elif chase_risk_score >= 50:
                chase_bonus = 2  # v21: 真回测chase>=50=50%wr/+2.55%
                v54_total_bonus += chase_bonus
                logger.info(f"{stock_code} 动量奖励: chase={chase_risk_score}>=50, 加{chase_bonus}分")
                score_adjustments.append(f"动量奖励: chase={chase_risk_score}>=50, 加{chase_bonus}分")

            # 2. v21重构: RSI超买惩罚移除,改为RSI强势区奖励
            # v22增强: 基于真回测优化
            #   - RSI>=80是毁灭性信号(23.8%wr/-8.77%)，需重罚
            #   - RSI 40-50是黄金区(52.5%wr/+2.79%)，需奖励
            current_rsi = tech_details.get('RSI', 50)
            if isinstance(current_rsi, (int, float)):
                if current_rsi >= 80:
                    # v22新增: RSI>=80重罚（真回测23.8%wr/-8.77%）
                    rsi_extreme_pen = 15
                    v54_total_penalty += rsi_extreme_pen
                    logger.info(f"{stock_code} RSI极端超买惩罚: RSI={current_rsi:.1f}>=80, 扣{rsi_extreme_pen}分")
                    score_adjustments.append(f"RSI极端超买: RSI={current_rsi:.1f}>=80, 扣{rsi_extreme_pen}分")
                elif 60 <= current_rsi < 80:
                    rsi_strong_bonus = 3  # v22提高: 2→3
                    v54_total_bonus += rsi_strong_bonus
                    logger.info(f"{stock_code} RSI强势区奖励: RSI={current_rsi:.1f}在60-80, 加{rsi_strong_bonus}分")
                elif 50 < current_rsi < 60:
                    # v23新增: RSI 50-60 涨停后回落区惩罚 (实测 36.7%wr/-1.37%)
                    # 该区间多为涨停次日位置, 大概率回落, 之前未扣分等于鼓励
                    rsi_pullback_pen = 4
                    v54_total_penalty += rsi_pullback_pen
                    logger.info(f"{stock_code} RSI回落区惩罚: RSI={current_rsi:.1f}在50-60, 扣{rsi_pullback_pen}分")
                    score_adjustments.append(f"RSI回落区: RSI={current_rsi:.1f}在50-60, 扣{rsi_pullback_pen}分")
                elif 40 <= current_rsi < 50:
                    # v22新增: RSI黄金区奖励（真回测52.5%wr/+2.79%）
                    rsi_golden_bonus = 4
                    v54_total_bonus += rsi_golden_bonus
                    logger.info(f"{stock_code} RSI黄金区奖励: RSI={current_rsi:.1f}在40-50, 加{rsi_golden_bonus}分")
                    score_adjustments.append(f"RSI黄金区: RSI={current_rsi:.1f}在40-50, 加{rsi_golden_bonus}分")

            # 3. 当日涨幅惩罚
            # v14优化: 涨停+3日<15%不惩罚(回测53.8%胜率+1.73%),只惩罚连板/暴涨
            price_changes = result.get('details', {}).get('price_changes', {})
            today_change = price_changes.get('change_1d', 0) or 0
            change_3d_for_limit = price_changes.get('change_3d', 0) or 0
            if today_change >= 19.5:
                limit_penalty = 20
                v54_total_penalty += limit_penalty
                logger.info(f"{stock_code} 大涨惩罚: 当日涨幅{today_change:.1f}%>=19.5%, 扣{limit_penalty}分")
            elif today_change >= 9.5:
                if change_3d_for_limit >= 15:
                    limit_penalty = 5  # v14: 连板涨停(3日>=15%)才惩罚
                    v54_total_penalty += limit_penalty
                    logger.info(f"{stock_code} 连板涨停惩罚: 涨幅{today_change:.1f}%+3日{change_3d_for_limit:.1f}%>=15%, 扣{limit_penalty}分")
                    score_adjustments.append(f"连板涨停惩罚: 涨幅{today_change:.1f}%+3日{change_3d_for_limit:.1f}%>=15%, 扣{limit_penalty}分")
                else:
                    logger.info(f"{stock_code} 涨停首板: 涨幅{today_change:.1f}%+3日{change_3d_for_limit:.1f}%<15%, 不惩罚")
            # v9优化: 7%涨幅轻度扣分
            elif today_change >= 7:
                limit_penalty = 3
                v54_total_penalty += limit_penalty
                logger.info(f"{stock_code} 中涨惩罚: 当日涨幅{today_change:.1f}%>=7%, 扣{limit_penalty}分")
            elif today_change >= 5:
                limit_penalty = 5  # v9优化: 3→5
                v54_total_penalty += limit_penalty
                logger.info(f"{stock_code} 轻涨惩罚: 当日涨幅{today_change:.1f}%>=5%, 扣{limit_penalty}分")

            # 4. v21精简: 短期涨幅惩罚（真回测: 3d 10-20%=48.8%/+1.67%, 动量续航有效）
            change_3d = price_changes.get('change_3d', 0) or 0
            change_5d = price_changes.get('change_5d', 0) or 0
            if change_5d > 25:
                surge_penalty = 15  # v21: 保留极端惩罚
                v54_total_penalty += surge_penalty
                logger.info(f"{stock_code} 5日暴涨惩罚: 5日涨幅{change_5d:.1f}%>25%, 扣{surge_penalty}分")
                score_adjustments.append(f"5日暴涨惩罚: 5日涨幅{change_5d:.1f}%>25%, 扣{surge_penalty}分")
            if change_3d > 20:
                surge_penalty = 8   # v21: 15→8 (真回测3d>=20%仅37.5%wr/-0.99%)
                v54_total_penalty += surge_penalty
                logger.info(f"{stock_code} 3日暴涨惩罚: 3日涨幅{change_3d:.1f}%>20%, 扣{surge_penalty}分")
                score_adjustments.append(f"3日暴涨惩罚: 3日涨幅{change_3d:.1f}%>20%, 扣{surge_penalty}分")
            # v21移除: 3d 10-15%惩罚 (真回测: 3d 10-20%=48.8%wr/+1.67%, 不应惩罚)

            # 5. v21移除信号拥挤惩罚 (买入信号越多越好,不应惩罚)
            # 原: buy>=15扣8分, 真回测buy>=10=55%wr

            # 6. 量化分反转惩罚 — 已移除(v8.0)

            # v21移除: 卖出信号>=3惩罚 (真回测sell>=3: 43.9%wr/+0.55%, 不差)
            # v21移除: 量化分极高惩罚 (真回测qs>=90: 44.9%wr/+1.01%, 不差)

            # === 应用惩罚（含上限保护） ===
            actual_penalty = min(v54_total_penalty, V54_PENALTY_CAP)
            if v54_total_penalty > V54_PENALTY_CAP:
                logger.info(f"{stock_code} 惩罚触及上限: 原始惩罚{v54_total_penalty}分, 实际扣除{actual_penalty}分(上限{V54_PENALTY_CAP})")
                score_adjustments.append(f"惩罚触及上限: 原始惩罚{v54_total_penalty}分, 实际扣除{actual_penalty}分(上限{V54_PENALTY_CAP})")
            total_score -= actual_penalty

            # 7. 低买入信号奖励 — 已移除(v8.0优化): 回测验证无正向效果

            # v21移除: RSI超卖奖励 (真回测RSI<40仅5样本,不可靠)
            # v21移除: RSI黄金区间奖励 (真回测RSI 40-50: 41.7%wr/-1.04%, 负效果)

            # 9. 正向奖励: 买入信号占优 — v10优化: 移除

            # v21移除: sell=0奖励 (真回测sell=0: 38.5%wr/-2.53%, 负效果)

            # 10. v9优化: 量化适中奖励 — 移除

            # v21移除: qs<50奖励 (真回测仅6样本,不可靠)

            # v21核心: 模型买入信号越多,分数越高 (真回测: buy>=10=55%wr/+2.16%)
            buy_bonus_val = 0
            if quant_buy_count >= 14: buy_bonus_val = 10
            elif quant_buy_count >= 12: buy_bonus_val = 8
            elif quant_buy_count >= 10: buy_bonus_val = 6
            elif quant_buy_count >= 8: buy_bonus_val = 4
            elif quant_buy_count >= 6: buy_bonus_val = 2
            if buy_bonus_val > 0:
                v54_total_bonus += buy_bonus_val
                logger.info(f"{stock_code} 买入信号奖励: buy={quant_buy_count}, 加{buy_bonus_val}分")

            # v21新增: 高位股奖励 (真回测pos>=0.7: 49.1%wr/+2.57%)
            position_pct_val = result.get('details', {}).get('momentum', {}).get('position_pct', 0.5)
            if isinstance(position_pct_val, (int, float)):
                if position_pct_val >= 0.7:
                    pos_bonus = 3  # 高位=强势
                    v54_total_bonus += pos_bonus
                    logger.info(f"{stock_code} 高位强势奖励: pos={position_pct_val:.2f}>=0.7, 加{pos_bonus}分")

            total_score += v54_total_bonus

            # ========== v5.5 牛股/妖股动量识别机制 ==========
            # 核心理念: 不是所有高动量股都是追高，真正的牛股有明确的动量特征
            # 识别到牛股模式时给予额外加分，并部分回收惩罚
            momentum_bonus = 0
            momentum_signals = []

            # 获取关键动量数据
            momentum_details = result.get('details', {}).get('momentum', {})
            volume_details = result.get('details', {}).get('volume_health', {})
            tech_details_for_momentum = result.get('details', {}).get('technical', {})

            position_pct = momentum_details.get('position_pct', 0.5)
            consecutive_up = momentum_details.get('consecutive_up_days', 0)
            volume_ratio = volume_details.get('volume_ratio', 1.0)
            volume_health_level = volume_details.get('volume_health', '一般')
            ma_status = tech_details_for_momentum.get('MA_status', '中性')
            macd_status = tech_details_for_momentum.get('MACD_status', '中性')
            vol_price_status = tech_details_for_momentum.get('vol_price_status', '一般')
            bollinger_width = tech_details_for_momentum.get('Bollinger_width', 20)

            # 量价模式检测
            vol_patterns = volume_details.get('volume_price_patterns', {})
            vol_up_price_up = vol_patterns.get('vol_up_price_up', {})
            vol_up_pu_days = vol_up_price_up.get('consecutive_days', 0) if isinstance(vol_up_price_up, dict) else 0
            vol_up_pu_strength = vol_up_price_up.get('pattern_strength', 'weak') if isinstance(vol_up_price_up, dict) else 'weak'

            # Pattern 1: 均线多头排列 + 量价配合 = 趋势确认牛股 (+12分)
            if '多头排列' in ma_status:
                if vol_price_status in ['放量上涨', '缩量回调']:
                    momentum_bonus += 12
                    momentum_signals.append(f'趋势确认({ma_status}+{vol_price_status}):+12')
                elif vol_price_status == '缩量上涨':
                    momentum_bonus += 6
                    momentum_signals.append(f'趋势延续({ma_status}+缩量上涨):+6')

            # Pattern 2: 底部放量启动 = 主力进场 (+10分)
            if position_pct < 0.40 and volume_ratio > 1.5 and today_change >= 3:
                momentum_bonus += 10
                momentum_signals.append(f'底部放量启动(pos={position_pct:.0%},vol={volume_ratio:.1f}x,涨{today_change:.1f}%):+10')

            # Pattern 3: 连续放量上涨 = 强势攻击 (+8~15分)
            if vol_up_pu_days >= 3:
                if vol_up_pu_strength in ['strong', 'very_strong']:
                    mb = 15
                else:
                    mb = 8
                momentum_bonus += mb
                momentum_signals.append(f'连续放量上涨{vol_up_pu_days}日({vol_up_pu_strength}):+{mb}')
            elif vol_up_pu_days >= 2:
                momentum_bonus += 5
                momentum_signals.append(f'放量上涨{vol_up_pu_days}日:+5')

            # Pattern 4: 连续上涨 + 量价健康 = 主力控盘 (+8分)
            if consecutive_up >= 3 and volume_health_level in ['健康', '非常健康']:
                momentum_bonus += 8
                momentum_signals.append(f'连涨{consecutive_up}日+量价健康:+8')
            elif consecutive_up >= 2 and today_change >= 3:
                momentum_bonus += 4
                momentum_signals.append(f'连涨{consecutive_up}日+今涨{today_change:.1f}%:+4')

            # Pattern 5: 布林收窄后突破 = 变盘启动 (+8分)
            if isinstance(bollinger_width, (int, float)) and bollinger_width < 10 and today_change >= 3:
                momentum_bonus += 8
                momentum_signals.append(f'布林收窄突破(宽{bollinger_width:.1f}%+涨{today_change:.1f}%):+8')

            # Pattern 6: MACD金叉共振 + RSI黄金区间 (+6分)
            if '金叉' in macd_status and 55 <= current_rsi <= 80:
                momentum_bonus += 6
                momentum_signals.append(f'MACD金叉+RSI黄金区({current_rsi:.0f}):+6')

            # Pattern 7: 涨停板首板 + 低追高风险 = 妖股起点 (+10分)
            if today_change >= 9.5 and chase_risk_score < 50:
                momentum_bonus += 10  # v13优化: 12→10
                momentum_signals.append(f'首板涨停(chase={chase_risk_score:.0f}<50):+10')
            elif today_change >= 9.5 and chase_risk_score >= 50:
                # v17新增: 涨停首板+高chase也有正收益(51.0%wr)
                momentum_bonus += 8
                momentum_signals.append(f'首板涨停高chase(chase={chase_risk_score:.0f}>=50):+8')
            elif today_change >= 7 and chase_risk_score < 40:
                momentum_bonus += 12  # v13优化: 15→12
                momentum_signals.append(f'强势涨幅(涨{today_change:.1f}%+chase={chase_risk_score:.0f}):+12')

            # 应用动量奖励（上限15分, v21缩减避免超100）
            momentum_bonus = min(15, momentum_bonus)

            # v20优化: 动量回收严格限制在已扣分的50%以内
            # 防止高风险票通过动量回收净加分, 导致排序不稳定
            penalty_recovery = 0
            if momentum_bonus >= 10 and actual_penalty > 0:
                penalty_recovery = min(actual_penalty // 2, 12)  # v20: 回收上限15→12, 且不超过已扣分50%
                momentum_signals.append(f'惩罚回收(动量抵消):+{penalty_recovery}')

            total_score += momentum_bonus + penalty_recovery

            if momentum_signals:
                result['momentum_pattern'] = momentum_signals
                logger.info(f"{stock_code} 牛股动量识别: {', '.join(momentum_signals)} (总+{momentum_bonus + penalty_recovery}分)")
                score_adjustments.append(f"牛股动量识别: {', '.join(momentum_signals)} (总+{momentum_bonus + penalty_recovery}分)")

            # ========== v5.6 回测新因子优化 ==========
            # 基于13824组合网格搜索发现的新有效因子

            # 1. 卖出信号占优惩罚 — v9优化: 移除（全量回测验证无效）
            # if quant_sell_count > quant_buy_count:

            # ========== v8.0 算法优化: 卖出信号强化惩罚 ==========
            # v9优化: 卖出信号绝对数量惩罚已移除（全量回测验证无效）
            # if quant_sell_count >= 5:

            # v10优化: 追高+超买组合风险惩罚（移除，与独立惩罚冗余）
            # if isinstance(chase_risk_score, (int, float)) and isinstance(current_rsi, (int, float)):
            #     if chase_risk_score > 30 and current_rsi > 60:

            # v21移除: 低追高+低RSI组合奖励 (真回测: 低chase/低RSI都是差信号)
            # 原: chase<25且RSI<50加8分

            # v10优化: 板块过热惩罚（大幅增加）
            if sector_score >= 95:
                sector_hot_penalty = 12  # v12优化: 10→12
                total_score -= sector_hot_penalty
                logger.info(f"{stock_code} 板块过热惩罚: sector_score={sector_score:.0f}>=95, 扣{sector_hot_penalty}分")

            # v10优化 + v23: 板块死区 U 型连续函数 (消除 60/75 边界跳变)
            # peak penalty 在死区中心 67.5(原 flat -10), 边界 60/75 处自然为 0
            # 之前 sector=59 不扣分而 sector=60 突然扣 10 分,违反单调性
            if 60 <= sector_score <= 75:
                distance = abs(sector_score - 67.5) / 7.5
                sector_dead_penalty = round(10 * (1 - distance))
                if sector_dead_penalty > 0:
                    total_score -= sector_dead_penalty
                    logger.info(f"{stock_code} 板块死区惩罚(U型): sector_score={sector_score:.0f}, 扣{sector_dead_penalty}分")
                    score_adjustments.append(f"板块死区惩罚: sector_score={sector_score:.0f}, 扣{sector_dead_penalty}分")

            # v21移除: 技术面虚高惩罚 (真回测tech>=80: 41.2%wr, 不算差)
            tech_score = result.get('dimension_scores', {}).get('technical', 50)

            # v21移除: 评分过高惩罚 (真回测74-76=49.5%/+4.06%, 高分是好事!)
            # 原: score>=76扣min(15, (score-76)*1.2), 阻止了S/A级产生

            # 2. 评分甜蜜区奖励 — v10优化: 移除（回测验证无正向效果）
            # if 63 <= total_score <= 69:

            # 3. 过高评分惩罚 — v11优化: 移除（阻止S级产生，回测验证pen=0最优）
            # if total_score >= 79:
            #     high_score_penalty = 8
            #     total_score -= high_score_penalty

            # v21: 总分clamp到0-100
            total_score = max(0, min(100, total_score))

            # v23+ P0-2: [82, 85) 单调性硬约束
            # 实测此区间胜率 51.5%,反低于 [80, 82) 的 58.6%。根因:基础分弱但靠单点
            # 爆点(如涨停 +10 + 趋势确认 +12)冲入 82+。此规则强制要求多维共振才能进入
            # 修复后预期 [82, 85) 段质量回升,A 级整体可信度恢复单调
            try:
                _base_seven = float(base_seven_dim_score)
            except Exception:
                _base_seven = total_score
            if _base_seven < 70.0 and 82.0 <= total_score < 85.0:
                _capped = 81.5
                logger.info(f"{stock_code} 单调性硬约束: 基础七维分{_base_seven:.1f}<70 但加分后冲到{total_score:.1f}, 压回{_capped} (防止单点爆冲 A 级)")
                score_adjustments.append(f"单调性约束: 基础分{_base_seven:.1f}<70, 总分压回{_capped} (避免单点爆冲)")
                total_score = _capped

            result['total_score'] = round(total_score, 2)
            result['rating'] = self._get_rating(total_score)
            result['recommendation'] = self._get_recommendation(result['rating'])
            result['weights_used'] = weights_used
            result['weight_mode'] = weight_mode

            # ========== v21 置信度分级标记 ==========
            # 总分已clamp至100, 阈值与原始一致
            if total_score >= 85:
                result['confidence_tier'] = 'S'
                result['confidence_label'] = '强烈推荐'
                logger.info(f"{stock_code} 置信度: S级(强烈推荐) - 评分{total_score:.0f}>=85")
            elif total_score >= 78:
                result['confidence_tier'] = 'A'
                result['confidence_label'] = '可考虑'
                logger.info(f"{stock_code} 置信度: A级(可考虑) - 评分{total_score:.0f}>=78")
            elif total_score >= 70:
                result['confidence_tier'] = 'B'
                result['confidence_label'] = '谨慎'
                logger.info(f"{stock_code} 置信度: B级(谨慎) - 评分{total_score:.0f}>=70")
            else:
                result['confidence_tier'] = 'C'
                result['confidence_label'] = '观望'

            if self.advanced_analyzer is not None and historical_data is not None:
                try:
                    advanced_result = self.advanced_analyzer.full_analysis(
                        stock_code=stock_code,
                        historical_data=historical_data,
                        fundamental_data=fundamental_data,
                        market_data=market_data
                    )
                    result['advanced_analysis'] = advanced_result
                    
                    adv_score = advanced_result.get('overall_score', {}).get('final_score', 50)
                    combined_score = result['total_score'] * 0.7 + adv_score * 0.3
                    combined_score = self._clamp_score(combined_score)
                    result['combined_score'] = round(combined_score, 2)
                    result['combined_rating'] = self._get_rating(combined_score)
                    
                    logger.info(f"{stock_code} 高级分析完成: 基础{result['total_score']}分 + 高级{adv_score}分 = 综合{combined_score}分")
                    result.get('score_adjustments', []).append(
                        f"高级分析完成: 基础{result['total_score']:.2f}分 + 高级{float(adv_score):.2f}分 = 综合{combined_score:.3f}分"
                    )
                except Exception as adv_e:
                    logger.warning(f"{stock_code} 高级分析失败: {adv_e}")

            logger.info(f"使用权重模式: {weight_mode} -> {weights_used}")

            logger.info(f"✓ {stock_code} 综合评分完成: {result['total_score']}分 ({result['rating']}级)")

        except Exception as e:
            logger.error(f"计算 {stock_code} 综合评分失败: {e}", exc_info=True)

        return result

    def _fetch_historical_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """获取历史K线数据（日线，优先使用统一缓存）"""
        try:
            # 1. 优先从统一文件缓存读取 (超过1小时视为过期, 自动重新获取)
            try:
                from data.cache.data_cache import get_ohlcv, fetch_and_cache_ohlcv
                cached = get_ohlcv(stock_code, min_rows=200, max_age_seconds=3600)
                if cached is not None:
                    logger.info(f"{stock_code}: 从统一缓存读取K线 ({len(cached)}行)")
                    return cached
                # 缓存不存在或已过期, 通过Tushare重新获取并缓存
                ok = fetch_and_cache_ohlcv(stock_code)
                if ok:
                    cached = get_ohlcv(stock_code, min_rows=60)
                    if cached is not None:
                        logger.info(f"{stock_code}: Tushare获取并缓存K线 ({len(cached)}行)")
                        return cached
                # 刷新失败(Tushare 限流/网络抖动/批量取数被拒)时，回退到「任意时效的历史缓存」。
                # 日线技术面与量化模型只需足够长度的历史序列，几天前的收盘 K 线足以支撑评分，
                # 远胜于返回 None 导致 quant=0 → 触发「量化评分过低总分封顶」(整份报告分数断层、
                # 量化模型摘要为空)。仅在新鲜数据确实拿不到时启用，不影响正常路径。
                stale = get_ohlcv(stock_code, min_rows=60, max_age_seconds=None)
                if stale is not None:
                    logger.warning(f"{stock_code}: 刷新失败，回退到陈旧缓存K线 ({len(stale)}行)")
                    return stale
            except ImportError:
                pass  # 缓存模块不可用, 降级到原始方式

            # 2. 降级: 使用MultiSourceDataFetcher
            if not self._data_fetcher:
                # 惰性初始化：避免程序启动阶段卡住；只有确实需要降级取数时才初始化
                self._init_data_fetcher()
            if not self._data_fetcher:
                logger.warning(f"{stock_code}: 数据获取器未初始化，无法获取历史数据")
                return None

            import asyncio

            timeout_seconds = int(os.environ.get('KRONOS_HISTORY_TIMEOUT', '60'))

            async def _run():
                # 过去一年到今天的日线数据
                end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
                start_date = (pd.Timestamp.today() - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
                return await asyncio.wait_for(
                    self._data_fetcher.fetch_stock_data(
                        symbol=stock_code,
                        start_date=start_date,
                        end_date=end_date,
                        freq='daily',
                        source='auto',
                        auto_extend=True,
                        min_days=240
                    ),
                    timeout=timeout_seconds
                )

            # 在同步环境中运行异步获取
            # 注意: 不能使用 asyncio.set_event_loop() + loop.close()，
            # 这会破坏线程的事件循环状态，导致后续 Playwright sync_playwright() 崩溃
            try:
                df = asyncio.run(_run())
            except RuntimeError:
                # 若已有事件循环（如在线程池中），创建独立循环但不设为全局
                loop = asyncio.new_event_loop()
                try:
                    df = loop.run_until_complete(_run())
                finally:
                    loop.close()
            except asyncio.TimeoutError:
                logger.warning(f"{stock_code}: 历史数据获取超时({timeout_seconds}s)")
                return None

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

    def _calculate_price_changes(self, historical_data: Optional[pd.DataFrame],
                                realtime_data: Optional[Dict] = None) -> Dict:
        """计算股票涨幅数据

        Args:
            historical_data: 历史K线数据
            realtime_data: 实时数据 {'latest_price': float, 'change_pct': float}
                          来自东方财富实时API，优先级高于历史缓存
        """
        try:
            if historical_data is None or historical_data.empty or len(historical_data) < 6:
                # 即使没有历史数据，如果有实时数据也返回当日涨幅
                if realtime_data:
                    return {
                        'change_1d': round(realtime_data['change_pct'], 2),
                        'change_3d': None,
                        'change_5d': None,
                        'current_price': realtime_data['latest_price']
                    }
                return {'change_1d': None, 'change_3d': None, 'change_5d': None}

            df = historical_data.copy()
            df = df.sort_values('timestamps', ascending=False)

            # 如果有实时数据，用实时价格计算（确保使用最新数据，不受缓存时效影响）
            if realtime_data:
                current_price = realtime_data['latest_price']
                change_1d_pct = realtime_data['change_pct']

                # 判断缓存的最新K线是否是今天
                today = pd.Timestamp.now().normalize()
                cache_latest = df['timestamps'].iloc[0]
                if hasattr(cache_latest, 'normalize'):
                    cache_latest = cache_latest.normalize()
                cache_has_today = (cache_latest >= today)

                if cache_has_today:
                    # 缓存包含今天: close[0]=今天, close[3]=T-3, close[5]=T-5
                    idx_3d, idx_5d = 3, 5
                else:
                    # 缓存不包含今天: close[0]=昨天(T-1), close[2]=T-3, close[4]=T-5
                    idx_3d, idx_5d = 2, 4

                if len(df) > idx_3d and df['close'].iloc[idx_3d] != 0:
                    change_3d_pct = (current_price - df['close'].iloc[idx_3d]) / df['close'].iloc[idx_3d] * 100
                else:
                    change_3d_pct = None

                if len(df) > idx_5d and df['close'].iloc[idx_5d] != 0:
                    change_5d_pct = (current_price - df['close'].iloc[idx_5d]) / df['close'].iloc[idx_5d] * 100
                else:
                    change_5d_pct = None
            else:
                # 回测模式：无实时数据，从历史K线计算
                current_price = df['close'].iloc[0] if len(df) > 0 else 0

                change_1d = df['close'].iloc[0] - df['close'].iloc[1] if len(df) > 1 else 0
                change_1d_pct = (change_1d / df['close'].iloc[1] * 100) if len(df) > 1 and df['close'].iloc[1] != 0 else None

                change_3d = df['close'].iloc[0] - df['close'].iloc[3] if len(df) > 3 else 0
                change_3d_pct = (change_3d / df['close'].iloc[3] * 100) if len(df) > 3 and df['close'].iloc[3] != 0 else None

                change_5d = df['close'].iloc[0] - df['close'].iloc[5] if len(df) > 5 else 0
                change_5d_pct = (change_5d / df['close'].iloc[5] * 100) if len(df) > 5 and df['close'].iloc[5] != 0 else None

            return {
                'change_1d': round(change_1d_pct, 2) if change_1d_pct is not None else None,
                'change_3d': round(change_3d_pct, 2) if change_3d_pct is not None else None,
                'change_5d': round(change_5d_pct, 2) if change_5d_pct is not None else None,
                'current_price': current_price
            }
        except Exception as e:
            logger.warning(f"计算涨幅失败: {e}")
            return {'change_1d': None, 'change_3d': None, 'change_5d': None}

    @staticmethod
    def _compute_quant_buy_count_bonus(buy_count: int) -> float:
        if not isinstance(buy_count, int):
            try:
                buy_count = int(buy_count)
            except Exception:
                return 0.0
        if buy_count <= 1:
            return 0.0
        return float(min(12.0, (buy_count - 1) * 0.8))

    @staticmethod
    def _compute_total_score_quant_buy_bonus(quant_buy_count: int, quant_sell_count: int, quant_score: float) -> float:
        try:
            buy_count = int(quant_buy_count)
            sell_count = int(quant_sell_count)
            score = float(quant_score)
        except Exception:
            return 0.0

        if buy_count <= sell_count:
            return 0.0

        dominance = buy_count - sell_count
        bonus = dominance * 2.5 + max(0, buy_count - 3) * 1.0  # v5.4: 提升奖励系数(2.0→2.5, 0.5→1.0)
        bonus = min(18.0, bonus)  # v5.4: 上限从12提升至18

        # v22新增: sell=0是最强正向信号（真回测53.8%wr/+5.02%）
        if sell_count == 0:
            bonus += 5
            logger.info(f"卖出信号为0，增加额外奖励+5分")

        if score < 45:
            bonus = min(5.0, bonus)  # v5.4: 低分时也给更多奖励(3→5)
        return round(float(bonus), 2)

    @staticmethod
    def _clamp_score(score: float) -> float:
        try:
            score_val = float(score)
        except Exception:
            return 0.0
        return max(0.0, min(100.0, score_val))

    @staticmethod
    def _apply_headroom_bonus(base_score: float, bonus_points: float) -> float:
        """v21: 分段线性 — 90 以下加分完全保留, 90 以上做缓收敛防止冲过100。

        旧公式 base + bonus*(100-base)/100 在 base=70 时仅保留 30% 加分,
        导致中段优质股永远突破不了 90 分。新公式让中段票分数能正确反映质量。
        """
        base = OpportunityScorer._clamp_score(base_score)
        try:
            bonus = float(bonus_points)
        except Exception:
            bonus = 0.0
        if bonus <= 0:
            return base
        candidate = base + bonus
        if candidate <= 90.0:
            return candidate  # 完全线性: bonus 100% 落地
        # 超过 90 后, 用 0.6 系数缓收敛, 避免冲到 100
        return min(100.0, 90.0 + (candidate - 90.0) * 0.6)

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
            score = 55.0  # v5.4: 基准分从45提升至55，避免惩罚后分数过低导致筛选结果过少
            signals = []

            # 定义信号权重（按模型类型分组，避免同质化信号重复计分）
            # 注意: 键名必须与 technical_analysis.py 中 self.signals[] 的英文键一致
            # 趋势类模型（相关性高，取最佳信号）
            trend_models = ['turtle_trading_system', 'cta_trend_strategy', 'ma_resonance', 'multi_breakthrough', 'atr_momentum']
            # 量价类模型
            volume_models = ['balance_dual_moving', 'volume_breakthrough', 'capital_trend', 'support_resistance', 'volume_price_trend']
            # 震荡类模型
            oscillator_models = ['super_reversal', 'rsi_divergence', 'stochastic_momentum', 'macd_axis_golden_cross']
            # 高级量化模型（独立权重）
            advanced_models = ['machine_learning_rf', 'multi_factor_alpha', 'pairs_trading_arbitrage', 'hft_microstructure']
            # 经典模型
            classic_models = ['ichimoku_cloud', 'bollinger_squeeze', 'parabolic_sar', 'vwap_deviation', 'fractal_adaptive_ma']

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

            buy_count_bonus = self._compute_quant_buy_count_bonus(buy_count)
            if buy_count_bonus > 0:
                score += buy_count_bonus
                signals.append(f'量化买入{buy_count}个')
            # [新增] 阳线占比与连续红柱 (Red Bar Ratio & Consecutive Red Bars)
            # 游资喜欢“红肥绿瘦”的K线形态，意味着多头强势
            try:
                close = historical_data['close']
                red_bars = 0
                consecutive_red = 0
                current_consecutive = 0
                
                # 统计近10天
                check_days = min(10, len(close))
                for i in range(1, check_days + 1):
                    c_price = float(close.iloc[-i])
                    o_price = float(historical_data['open'].iloc[-i])
                    
                    if c_price >= o_price: # 收阳（包含十字星）
                        red_bars += 1
                        current_consecutive += 1
                    else:
                        current_consecutive = 0
                    consecutive_red = max(consecutive_red, current_consecutive)
                
                # 阳线占比加分
                if red_bars >= 7:
                    score += 15
                    signals.append(f'红肥绿瘦(近10日{red_bars}阳)')
                elif red_bars >= 5:
                    score += 5
                
                # 连续红柱加分 (当前连续天数)
                curr_streak = 0
                for i in range(1, check_days + 1):
                    if float(close.iloc[-i]) >= float(historical_data['open'].iloc[-i]):
                        curr_streak += 1
                    else:
                        break
                
                if curr_streak >= 3:
                    streak_bonus = 5 + (curr_streak - 3) * 3
                    score += streak_bonus
                    signals.append(f'连续{curr_streak}日收阳')
            except Exception as e:
                pass

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
                'signals': signals,
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

            next_day_risk_score = 35.0
            close_strength = 0.5
            upper_shadow_ratio = 0.0
            rebound_setup = False
            rebound_signal_count = 0
            current_vol = float(volume.iloc[-1]) if len(volume) > 0 else 0.0

            if {'open', 'high', 'low'}.issubset(historical_data.columns):
                try:
                    today_open = float(historical_data['open'].iloc[-1])
                    today_high = float(historical_data['high'].iloc[-1])
                    today_low = float(historical_data['low'].iloc[-1])
                    day_range = max(today_high - today_low, current_price * 0.001)
                    close_strength = (current_price - today_low) / day_range
                    upper_shadow_ratio = (today_high - current_price) / day_range

                    high_series = historical_data['high']
                    low_series = historical_data['low']
                    if len(high_series) >= 10 and len(low_series) >= 10:
                        avg_amp_10 = float(((high_series.iloc[-10:] - low_series.iloc[-10:]) /
                                            low_series.iloc[-10:].replace(0, np.nan)).mean())
                    else:
                        avg_amp_10 = 0.0
                    today_amp = (today_high - today_low) / today_low if today_low > 0 else 0.0

                    avg_vol_10 = float(volume.iloc[-11:-1].mean()) if len(volume) >= 11 else float(volume.mean())
                    vol_ratio_10 = current_vol / avg_vol_10 if avg_vol_10 > 0 else 1.0

                    if close_strength >= 0.72 and upper_shadow_ratio <= 0.25:
                        score += 8
                        rebound_signal_count += 1
                        signals.append('收盘接近全天高位')
                    elif close_strength < 0.35 or upper_shadow_ratio > 0.55:
                        score -= 12
                        next_day_risk_score += 22
                        signals.append('冲高回落，隔日承压')

                    if avg_amp_10 > 0 and today_amp > avg_amp_10 * 1.8 and close_strength < 0.55:
                        score -= 8
                        next_day_risk_score += 10
                        signals.append('当日波动过大，隔日分歧风险')

                    if vol_ratio_10 >= 1.2 and close_strength >= 0.65:
                        next_day_risk_score -= 8
                except Exception:
                    pass

            try:
                rsi_series = TechnicalAnalysis.calculate_rsi(close, 14)
                if len(rsi_series.dropna()) >= 3:
                    rsi_now = float(rsi_series.iloc[-1])
                    rsi_prev = float(rsi_series.iloc[-2])
                    rsi_prev2 = float(rsi_series.iloc[-3])
                    if rsi_prev < 30 and rsi_now > rsi_prev:
                        score += 10
                        rebound_signal_count += 1
                        signals.append('RSI超卖回升')
                    if rsi_prev2 < 30 and rsi_now > rsi_prev and rsi_prev > rsi_prev2:
                        score += 8
                        rebound_signal_count += 1
                        signals.append('RSI连续抬升')
                    if rsi_now > 78:
                        next_day_risk_score += 12
            except Exception:
                pass

            if len(close) >= 4:
                is_price_turn = float(close.iloc[-1]) > float(close.iloc[-2]) and float(close.iloc[-2]) <= float(close.iloc[-3])
                if is_price_turn and position_pct <= 0.45:
                    score += 8
                    rebound_signal_count += 1
                    signals.append('短线止跌拐点')

            rebound_setup = rebound_signal_count >= 2
            if rebound_setup:
                next_day_risk_score -= 10
            next_day_risk_score = max(0.0, min(100.0, next_day_risk_score))

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

            consecutive_down = 0
            for i in range(1, min(10, len(close))):
                if float(close.iloc[-i]) < float(close.iloc[-i-1]):
                    consecutive_down += 1
                else:
                    break

            if consecutive_down >= 3:
                if rebound_setup:
                    downtrend_penalty = 8 if consecutive_down == 3 else 12
                    score -= downtrend_penalty
                    signals.append(f'连续下跌{consecutive_down}天但出现止跌信号')
                else:
                    score -= 20
                    signals.append(f'连续下跌{consecutive_down}天，趋势偏弱')

            # ========== 8. [v4.5] 追高风险综合评估 ==========
            # 综合考虑：位置+涨幅+连涨天数，给出追高风险等级
            chase_risk_score = 0
            chase_risk_factors = []
            
            # 位置风险
            if position_pct > 0.85:
                chase_risk_score += 40
                chase_risk_factors.append('接近年内最高点')
            elif position_pct > 0.70:
                chase_risk_score += 25
                chase_risk_factors.append('处于高位区间')
            elif position_pct > 0.50:
                chase_risk_score += 10
                chase_risk_factors.append('处于中高位')
            
            # 短期涨幅风险
            if change_5d > 20:
                chase_risk_score += 35
                chase_risk_factors.append(f'5日涨幅{change_5d:.1f}%过大')
            elif change_5d > 10:
                chase_risk_score += 20
                chase_risk_factors.append(f'5日涨幅{change_5d:.1f}%偏高')
            
            # 中期涨幅风险
            if change_20d > 40:
                chase_risk_score += 30
                chase_risk_factors.append(f'20日涨幅{change_20d:.1f}%过大')
            elif change_20d > 25:
                chase_risk_score += 15
                chase_risk_factors.append(f'20日涨幅{change_20d:.1f}%偏高')
            
            # 连涨天数风险
            if consecutive_up >= 5:
                chase_risk_score += 20
                chase_risk_factors.append(f'连涨{consecutive_up}天')
            elif consecutive_up >= 3:
                chase_risk_score += 10
            
            # 距离高点风险
            if distance_from_high < 5:
                chase_risk_score += 25
                chase_risk_factors.append('距高点<5%')
            elif distance_from_high < 10:
                chase_risk_score += 10
            
            # 追高风险等级判定（分数压缩到0-100，避免过激表述）
            chase_risk_level = 'low'
            chase_risk_score = max(0, min(100, chase_risk_score))

            if chase_risk_score >= 75:
                chase_risk_level = 'high'
                score -= 20
                signals.append(f'⚠️ 追高风险偏高({chase_risk_score}分): {", ".join(chase_risk_factors[:2])}')
            elif chase_risk_score >= 50:
                chase_risk_level = 'medium'
                score -= 10
                signals.append(f'⚠️ 追高风险居中({chase_risk_score}分)')
            elif chase_risk_score >= 25:
                chase_risk_level = 'low_medium'
                score -= 5

            # 确保分数在合理范围内
            score = max(0, min(100, score))

            next_day_risk_level = 'low'
            if next_day_risk_score >= 70:
                next_day_risk_level = 'high'
            elif next_day_risk_score >= 50:
                next_day_risk_level = 'medium'

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
                'chase_risk_score': chase_risk_score,
                'chase_risk_level': chase_risk_level,
                'chase_risk_factors': chase_risk_factors,
                'next_day_risk_score': round(next_day_risk_score, 2),
                'next_day_risk_level': next_day_risk_level,
                'close_strength': round(close_strength, 2),
                'upper_shadow_ratio': round(upper_shadow_ratio, 2),
                'rebound_setup': rebound_setup,
                'rebound_signal_count': rebound_signal_count,
                'signals': signals,
                'scoring_method': 'v4.5_anti_chasing_enhanced'
            }

            return round(score, 2), details

        except Exception as e:
            logger.error(f"位置时机评分失败: {e}")
            return 50.0, {'error': str(e)}

    def _detect_consecutive_volume_price_pattern(self, 
                                                  close: pd.Series, 
                                                  volume: pd.Series,
                                                  pattern_type: str = '放量上涨',
                                                  min_days: int = 2,
                                                  max_lookback: int = 10) -> Dict:
        """
        检测连续多日量价形态 - v4.5核心方法
        
        Args:
            close: 收盘价序列
            volume: 成交量序列
            pattern_type: 形态类型 ('放量上涨', '缩量下跌', '放量下跌', '缩量上涨')
            min_days: 最小连续天数
            max_lookback: 最大回溯天数
            
        Returns:
            {
                'detected': bool,           # 是否检测到形态
                'consecutive_days': int,    # 连续天数
                'avg_volume_ratio': float,  # 平均量比
                'total_gain_pct': float,    # 总涨跌幅
                'pattern_strength': str     # 形态强度: 'weak', 'medium', 'strong', 'very_strong'
            }
        """
        result = {
            'detected': False,
            'consecutive_days': 0,
            'avg_volume_ratio': 1.0,
            'total_gain_pct': 0.0,
            'pattern_strength': 'none'
        }
        
        try:
            if len(close) < 6 or len(volume) < 6:
                return result
            
            # 计算5日均量作为基准
            avg_vol_5 = float(volume.iloc[-6:-1].mean())
            if avg_vol_5 <= 0:
                return result
            
            consecutive_days = 0
            total_vol_ratio = 0.0
            start_price = float(close.iloc[-1])
            end_price = start_price
            
            # 从最近一天往前检测
            for i in range(1, min(max_lookback + 1, len(close))):
                curr_close = float(close.iloc[-i])
                prev_close = float(close.iloc[-i-1]) if i < len(close) - 1 else curr_close
                curr_vol = float(volume.iloc[-i])
                prev_vol = float(volume.iloc[-i-1]) if i < len(volume) - 1 else curr_vol
                
                vol_ratio = curr_vol / avg_vol_5
                price_change = curr_close - prev_close
                vol_change = curr_vol - prev_vol
                
                # 根据形态类型判断是否符合条件
                pattern_match = False
                
                if pattern_type == '放量上涨':
                    # 价格上涨 + 成交量放大(>1.1倍均量)
                    pattern_match = price_change > 0 and vol_ratio > 1.1
                elif pattern_type == '缩量下跌':
                    # 价格下跌 + 成交量萎缩(<0.9倍均量)
                    pattern_match = price_change < 0 and vol_ratio < 0.9
                elif pattern_type == '放量下跌':
                    # 价格下跌 + 成交量放大(>1.1倍均量) - 危险形态
                    pattern_match = price_change < 0 and vol_ratio > 1.1
                elif pattern_type == '缩量上涨':
                    # 价格上涨 + 成交量萎缩(<0.9倍均量) - 警告形态
                    pattern_match = price_change > 0 and vol_ratio < 0.9
                
                if pattern_match:
                    consecutive_days += 1
                    total_vol_ratio += vol_ratio
                    if consecutive_days == 1:
                        end_price = curr_close
                else:
                    # 形态中断，停止检测
                    break
            
            # 判断是否达到最小天数要求
            if consecutive_days >= min_days:
                result['detected'] = True
                result['consecutive_days'] = consecutive_days
                result['avg_volume_ratio'] = total_vol_ratio / consecutive_days if consecutive_days > 0 else 1.0
                
                # 计算总涨跌幅
                first_price = float(close.iloc[-consecutive_days-1]) if consecutive_days < len(close) else float(close.iloc[0])
                result['total_gain_pct'] = (end_price / first_price - 1) * 100 if first_price > 0 else 0
                
                # 判断形态强度
                avg_vol = result['avg_volume_ratio']
                days = consecutive_days
                if days >= 5 and avg_vol > 1.5:
                    result['pattern_strength'] = 'very_strong'
                elif days >= 4 or (days >= 3 and avg_vol > 1.5):
                    result['pattern_strength'] = 'strong'
                elif days >= 3 or (days >= 2 and avg_vol > 1.3):
                    result['pattern_strength'] = 'medium'
                else:
                    result['pattern_strength'] = 'weak'
            
            return result
            
        except Exception as e:
            logger.debug(f"量价形态检测失败: {e}")
            return result

    def _score_volume_health(self, stock_code: str,
                             historical_data: Optional[pd.DataFrame]) -> Tuple[float, Dict]:
        """
        量价健康度评分 (0-100分) - v4.5 连续放量上涨/缩量下跌优化版

        核心优化（v4.5）:
        - 连续多日放量上涨: 重点加分项（健康上涨形态）
        - 连续多日缩量下跌: 健康调整形态，加分
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

            # 7. [新增] 量能逐渐放大检测 (Volume Gradually Increasing)
            # 检查最近5天的量能趋势
            try:
                if len(volume) >= 5:
                    vol_ma5 = volume.rolling(window=5).mean()
                    # 趋势向上：MA5连续3天上涨
                    if vol_ma5.iloc[-1] > vol_ma5.iloc[-2] > vol_ma5.iloc[-3]:
                         score += 10
                         signals.append('量能温和放大(MA5上行)')
                    # 或者：量能逐级放大 (Vol_t > Vol_t-1 > Vol_t-2)
                    elif float(volume.iloc[-1]) > float(volume.iloc[-2]) > float(volume.iloc[-3]):
                         score += 8
                         signals.append('成交量逐级放大')
            except:
                pass

            # 8. [新增] 缩量回调检测 (Shrinking Volume on Drop) - 增强版
            # 检查最近4天内，如果是下跌，是否缩量
            shrink_drop_count = 0
            try:
                for i in range(1, min(5, len(close))): 
                    p_curr = float(close.iloc[-i])
                    p_prev = float(close.iloc[-i-1])
                    v_curr = float(volume.iloc[-i])
                    v_prev = float(volume.iloc[-i-1])
                    
                    if p_curr < p_prev and v_curr < v_prev:
                        shrink_drop_count += 1
                
                if shrink_drop_count >= 2:
                    score += 10  # 连续缩量回调，加分
                    signals.append(f'近期缩量回调({shrink_drop_count}天)')
            except:
                pass

            # 9. [新增] 连续买入 (Continuous Buying) - 连续价涨量增
            # 检查最近连续价涨量增的天数
            buy_streak = 0
            try:
                for i in range(1, min(6, len(close))):
                    p_curr = float(close.iloc[-i])
                    p_prev = float(close.iloc[-i-1])
                    v_curr = float(volume.iloc[-i])
                    v_prev = float(volume.iloc[-i-1])
                    
                    if p_curr > p_prev and v_curr > v_prev:
                        buy_streak += 1
                    else:
                        break 
                
                if buy_streak >= 2:
                    buy_streak_score = 10 + (buy_streak - 2) * 5
                    score += buy_streak_score
                    signals.append(f'连续价涨量增({buy_streak}天)')
            except:
                pass

            # 10. [v4.5核心] 连续多日放量上涨检测 (Consecutive Volume-Up Price-Up)
            # 游资核心形态: 连续放量上涨是主力持续吸筹的强信号
            consecutive_vol_up_price_up = self._detect_consecutive_volume_price_pattern(
                close, volume, pattern_type='放量上涨'
            )
            if consecutive_vol_up_price_up['detected']:
                days = consecutive_vol_up_price_up['consecutive_days']
                avg_vol_ratio = consecutive_vol_up_price_up['avg_volume_ratio']
                total_gain = consecutive_vol_up_price_up['total_gain_pct']
                
                # 根据连续天数和放量幅度动态加分
                if days >= 5:
                    bonus = 35  # 5天以上连续放量上涨，极强信号
                    signals.append(f'🔥🔥 连续{days}日放量上涨(量比{avg_vol_ratio:.1f}x,涨幅{total_gain:.1f}%)')
                elif days >= 4:
                    bonus = 28
                    signals.append(f'🔥 连续{days}日放量上涨(量比{avg_vol_ratio:.1f}x,涨幅{total_gain:.1f}%)')
                elif days >= 3:
                    bonus = 20
                    signals.append(f'连续{days}日放量上涨(量比{avg_vol_ratio:.1f}x)')
                elif days >= 2:
                    bonus = 12
                    signals.append(f'连续{days}日放量上涨')
                else:
                    bonus = 0
                
                # 低位放量上涨额外加分
                if is_low_pos and days >= 3:
                    bonus += 10
                    signals.append('低位连续放量上涨(主力吸筹)')
                
                score += bonus

            # 11. [v4.5核心] 连续多日缩量下跌检测 (Consecutive Volume-Down Price-Down)
            # 健康调整形态: 缩量下跌说明抛压减轻，调整接近尾声
            consecutive_vol_down_price_down = self._detect_consecutive_volume_price_pattern(
                close, volume, pattern_type='缩量下跌'
            )
            if consecutive_vol_down_price_down['detected']:
                days = consecutive_vol_down_price_down['consecutive_days']
                avg_vol_ratio = consecutive_vol_down_price_down['avg_volume_ratio']
                total_loss = abs(consecutive_vol_down_price_down['total_gain_pct'])
                
                # 缩量下跌是健康调整，但需要结合位置判断
                if days >= 4:
                    bonus = 20  # 4天以上缩量下跌，调整充分
                    signals.append(f'连续{days}日缩量下跌(量比{avg_vol_ratio:.1f}x,跌幅{total_loss:.1f}%),调整充分')
                elif days >= 3:
                    bonus = 15
                    signals.append(f'连续{days}日缩量下跌(量比{avg_vol_ratio:.1f}x),健康调整')
                elif days >= 2:
                    bonus = 8
                    signals.append(f'连续{days}日缩量下跌,正常回调')
                else:
                    bonus = 0
                
                # 如果是低位缩量下跌后企稳，更佳
                if is_low_pos and days >= 3:
                    bonus += 8
                    signals.append('低位缩量整理(筹码集中)')
                
                score += bonus

            # 12. [v4.5] 放量下跌风险检测 (Volume-Up Price-Down Warning)
            # 危险形态: 放量下跌说明主力出货
            consecutive_vol_up_price_down = self._detect_consecutive_volume_price_pattern(
                close, volume, pattern_type='放量下跌'
            )
            if consecutive_vol_up_price_down['detected']:
                days = consecutive_vol_up_price_down['consecutive_days']
                avg_vol_ratio = consecutive_vol_up_price_down['avg_volume_ratio']
                total_loss = abs(consecutive_vol_up_price_down['total_gain_pct'])
                
                # 放量下跌是危险信号，扣分
                if days >= 3:
                    penalty = 25
                    signals.append(f'⚠️ 连续{days}日放量下跌(量比{avg_vol_ratio:.1f}x,跌幅{total_loss:.1f}%),抛压沉重')
                elif days >= 2:
                    penalty = 15
                    signals.append(f'⚠️ 连续{days}日放量下跌,需警惕')
                else:
                    penalty = 0
                
                score -= penalty

            # 13. [v4.5] 缩量上涨警告 (Volume-Down Price-Up Warning)
            # 警告形态: 缩量上涨说明上涨动能不足
            consecutive_vol_down_price_up = self._detect_consecutive_volume_price_pattern(
                close, volume, pattern_type='缩量上涨'
            )
            if consecutive_vol_down_price_up['detected']:
                days = consecutive_vol_down_price_up['consecutive_days']
                
                # 缩量上涨是警告信号，轻微扣分
                if days >= 3:
                    penalty = 10
                    signals.append(f'缩量上涨{days}日,上涨动能不足')
                elif days >= 2:
                    penalty = 5
                    signals.append(f'缩量上涨,动能减弱')
                else:
                    penalty = 0
                
                score -= penalty

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
                'volume_health': volume_health,
                'volume_price_patterns': {
                    'vol_up_price_up': consecutive_vol_up_price_up if consecutive_vol_up_price_up['detected'] else None,
                    'vol_down_price_down': consecutive_vol_down_price_down if consecutive_vol_down_price_down['detected'] else None,
                    'vol_up_price_down': consecutive_vol_up_price_down if consecutive_vol_up_price_down['detected'] else None,
                    'vol_down_price_up': consecutive_vol_down_price_up if consecutive_vol_down_price_up['detected'] else None,
                },
                'scoring_method': 'v4.5_volume_price_pattern'
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

            # ========== 3. 流通市值评分 (-10 ~ +15) ==========
            # v5.4: 用户要求放开大市值限制，移除>500亿和>1000亿的惩罚
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
                else:
                    pass  # v5.4: 大市值不再扣分，保持中性

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
                sector_sentiment = sector.get('sector_sentiment', {})
                score = sector_sentiment.get('sentiment_score', 50)
                details = {
                    'sector_name': sector.get('sector_name', '未知'),
                    'sentiment_score': score,
                    'overall': sector_sentiment.get('overall', '中性'),
                    'change_pct': sector_sentiment.get('change_pct', 0),
                    'turnover_rate': sector_sentiment.get('turnover_rate', 0),
                    'leader_stock': sector_sentiment.get('leader_stock', {}),
                    'data_source': sector_sentiment.get('data_source', '')
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
            # external_data 为扁平结构时(total_market_cap 来自 HotStocksFetcher)，单位已是“亿元”
            # 否则默认为“元”，转换为“亿元”
            total_mv = indicators.get('total_market_cap')
            if isinstance(total_mv, (int, float)) and total_mv > 0:
                if external_data is not None and 'financial_indicators' not in external_data:
                    mv_yi = float(total_mv)
                else:
                    mv_yi = total_mv / 100000000.0

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
            'S': '🌟 强烈推荐',
            'A+': '⭐ 推荐',
            'A': '✓ 可考虑',
            'B': '△ 谨慎',
            'C': '✗ 不建议'
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
