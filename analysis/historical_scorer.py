#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HistoricalScorer - 历史回测专用评分器
====================================
继承 OpportunityScorer，重写API依赖的方法返回中性值，
保留77%权重的OHLCV纯计算评分（量化模型+位置+量价+技术）。

用法:
    scorer = HistoricalScorer()
    result = scorer.calculate_comprehensive_score(
        stock_code, historical_data=df, fundamental_data=fund_dict
    )
"""

import logging
from typing import Dict, Optional, Tuple

from analysis.opportunity_scorer import OpportunityScorer

logger = logging.getLogger(__name__)


class HistoricalScorer(OpportunityScorer):
    """
    历史回测评分器 - 无任何外部API依赖

    继承的评分维度（纯OHLCV计算，权重77%）:
    - _score_quantitative_models (0.25): 30个量化模型
    - _score_momentum (0.22): 位置与时机
    - _score_volume_health (0.22): 量价健康
    - _score_technical_analysis (0.08): 技术指标

    重写为中性值的维度（权重23%）:
    - _score_sector_sentiment (0.05)
    - _score_dragon_tiger (0.06)
    - _score_events (0.03)
    - _score_investor_sentiment (0.00, 已跳过)
    - _score_liquidity (0.05): 部分可算，降级处理
    - _score_fundamental (0.04): 可接受external_data
    """

    def __init__(self):
        # 从类属性拷贝配置（不调用super().__init__避免API初始化）
        self.RATING_THRESHOLDS = dict(type(self).RATING_THRESHOLDS)
        self.DIMENSION_WEIGHTS = dict(type(self).DIMENSION_WEIGHTS)
        self.EXCLUSION_RULES = dict(type(self).EXCLUSION_RULES)

        # 跳过 _load_runtime_config 和 _init_data_fetcher
        self.advanced_analyzer = None
        self._data_fetcher = None

        logger.info("HistoricalScorer 初始化完成（无外部API依赖）")

    def _score_sector_sentiment(self, stock_code: str) -> Tuple[float, Dict]:
        """板块情绪 - 返回中性值"""
        return 50.0, {'source': 'historical_neutral', 'sector_name': '未知'}

    def _score_events(self, stock_code: str, global_hot_news: Optional[list] = None) -> Tuple[float, Dict]:
        """消息面 - 返回中性值"""
        return 50.0, {'source': 'historical_neutral'}

    def _score_dragon_tiger(self, stock_code: str, sentiment_details: Dict) -> Tuple[float, Dict]:
        """龙虎榜 - 返回中性值"""
        return 50.0, {'source': 'historical_neutral'}

    def _score_investor_sentiment(self, stock_code: str, momentum_details: Dict = None) -> Tuple[float, Dict]:
        """股民情绪 - 返回中性值（权重0.00已跳过）"""
        return 50.0, {'source': 'historical_neutral'}
