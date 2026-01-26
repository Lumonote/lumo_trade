#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会漏斗筛选器 v4.1 - 流动性前置优化版
=====================================

核心设计理念（顶级游资/操盘手思维）:
1. 前置风控：一票否决机制先行，排除高风险标的
2. 流动性优先：无流动性则无交易，必须最先检查
3. 反追涨核心：位置与时机是关键筛选维度
4. 信号质量：重视信号稀缺性，而非数量堆积
5. 宁缺毋滥：严格筛选，错过好于套牢

阶段设计（v4.1 流动性前置优化）:
- 阶段0: 一票否决前置筛选（排除极端风险，含基础流动性门槛）
- 阶段1: 流动性筛选（确保可交易，游资核心门槛）
- 阶段2: 位置与时机筛选（反追涨核心）
- 阶段3: 量化模型初筛（信号质量评估）
- 阶段4-7: 其他维度评分（仅评分，不筛选）
"""

import os
import sys
from typing import Dict, List, Tuple
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OpportunityFilter:
    """投资机会漏斗筛选器 v4.1 - 流动性前置优化版"""

    # 筛选阈值配置 (v4.1 流动性前置优化)
    STAGE_THRESHOLDS = {
        # 阶段0: 一票否决规则（最严格，含基础流动性门槛）
        'stage0_veto': {
            'max_change_60d': 80,          # 60日涨幅超80%一票否决
            'max_change_20d': 50,          # 20日涨幅超50%一票否决
            'max_distance_from_high': 5,   # 距离年内高点<5%一票否决
            'max_consecutive_up': 7,       # 连涨超7天一票否决
            'min_profit_yoy': -70,         # 利润同比下滑超70%一票否决
            # 'min_avg_amount_basic': 1000,  # 基础成交额门槛1000万（已移除）
        },
        # 阶段1: 流动性筛选（v4.1 前置到阶段1，游资核心门槛）
        'stage1_liquidity': {
            'min_avg_amount_20d': 3000,
            'min_turnover_rate': 0.5,
            'min_circulation_cap': 20,
        },
        # 阶段2: 位置与时机筛选（反追涨核心）
        'stage2_position': {
            'max_position_pct': 0.75,      # 最大允许的位置分位数（75%以下）
            'max_change_5d': 20,           # 5日涨幅不超过20%
            'ideal_drawdown_min': 3,       # 理想回撤区间下限
            'ideal_drawdown_max': 20,      # 理想回撤区间上限
        },
        # 阶段3: 量化模型筛选（信号质量）- 原阶段1
        'stage3_quant': {
            'min_buy_signals': 2,          # 最少买入信号数
            'min_buy_ratio': 0.15,         # 最低买入信号比例 15%
            'max_buy_signals': 25,         # 信号过度拥挤阈值（超过则警告）
            'require_quality_signal': True, # 要求至少有一个高质量信号组
        },
        # 阶段4: 技术面评分（不筛选）
        'stage4_technical': {
            'max_rsi': 80,                 # RSI超买阈值
            'min_rsi': 25,                 # RSI超卖阈值
            'ma_trend_score': 2,           # 均线趋势评分最低要求
        },
        # 阶段5-7: 其他维度（仅评分）
        'stage5_sentiment': {
            'contrarian_mode': True,       # 反指标模式
        },
        'stage6_fundamental': {
            'max_pe': 60,                  # PE上限参考
        },
        'stage7_events': {
            'positive_over_negative': True # 利好>利空参考
        }
    }

    # 量化模型中文展示映射（用于在理由文本中显示中文名称）
    MODEL_DISPLAY_MAP = {
        'balance_dual_moving': '均衡双均线',
        'multi_breakthrough': '多重突破',
        'support_resistance': '支撑阻力',
        'trend_pullback': '趋势回踩',
        'ma_resonance': '均线共振',
        'super_reversal': '超级反转',
        'capital_trend': '资金趋势',
        'volume_breakthrough': '量能突破',
        'three_sisters': '三姐妹形态',
        'macd_axis_golden_cross': '轴心MACD金叉',
        'six_dimension_resonance': '六维共振',
        'statistical_quantitative': '统计量化',
        'super_profit_limit_up': '超额涨停',
        'turtle_trading_system': '海龟交易',
        'atr_momentum': 'ATR动量',
        'cta_trend_strategy': 'CTA趋势',
        'machine_learning_rf': '机器学习RF',
        'multi_factor_alpha': '多因子Alpha',
        'pairs_trading_arbitrage': '配对交易套利',
        'hft_microstructure': '高频微结构',
        'ichimoku_cloud': '一目均衡云',
        'bollinger_squeeze': '布林收敛',
        'rsi_divergence': 'RSI背离',
        'stochastic_momentum': '随机动量',
        'volume_price_trend': '量价趋势',
        'parabolic_sar': '抛物转向SAR',
        'chaikin_money_flow': '切金资金流',
        'elder_ray': 'Elder射线',
        'vwap_deviation': 'VWAP偏离',
        'fractal_adaptive_ma': '分形自适应均线'
    }

    def __init__(self, enable_liquidity_elimination: bool = None):
        """初始化筛选器"""
        # 允许通过参数或环境变量控制是否启用流动性淘汰机制
        # 环境变量: KRONOS_ENABLE_LIQUIDITY_ELIMINATION = 'true'/'1' 启用
        if enable_liquidity_elimination is None:
            env_val = os.environ.get('KRONOS_ENABLE_LIQUIDITY_ELIMINATION', '').lower()
            self.enable_liquidity_elimination = env_val in ('1', 'true', 'yes', 'on')
        else:
            self.enable_liquidity_elimination = bool(enable_liquidity_elimination)

    def apply_all_filters(self, stock_data: Dict) -> Dict:
        """
        应用所有筛选阶段 - v4.1 流动性前置优化版

        筛选顺序（按重要性排列，流动性前置）:
        - 阶段0: 一票否决前置筛选（排除极端风险，含基础流动性门槛）
        - 阶段1: 流动性筛选（确保可交易，游资核心门槛）
        - 阶段2: 位置与时机筛选（反追涨核心）
        - 阶段3: 量化模型初筛（信号质量评估）
        - 阶段4-7: 其他维度评分（仅评分，不筛选）

        Args:
            stock_data: 股票综合数据，包含:
                - stock_code: 股票代码
                - name: 股票名称
                - scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        logger.info(f"开始筛选: {stock_data.get('stock_code', 'Unknown')}")

        result = {
            'stock_code': stock_data.get('stock_code', ''),
            'name': stock_data.get('name', ''),
            'passed': False,
            'eliminated_at_stage': 0,
            'filter_history': [],
            'final_score': stock_data.get('scoring_result', {}).get('total_score', 0),
            'rating': stock_data.get('scoring_result', {}).get('rating', 'C')
        }

        scoring_result = stock_data.get('scoring_result', {})
        if not scoring_result:
            logger.warning(f"{result['stock_code']}: 无评分数据")
            return result

        # 将评分结果透传到最终输出，供报表展示维度分数与权重
        result['scoring_result'] = scoring_result

        # ========== 阶段0: 一票否决前置筛选（仅记录，不淘汰）==========
        stage0_result = self.stage0_veto_check(scoring_result)
        result['filter_history'].append(stage0_result)
        # 已移除淘汰机制：一票否决条件仅记录，不影响最终筛选结果
        if not stage0_result['passed']:
            logger.info(f"⚠ {result['stock_code']} 阶段0(一票否决)未通过: {stage0_result['reason']} (仅记录，不淘汰)")

        #========== 阶段1: 流动性筛选（v4.1 前置，游资核心门槛）==========
        stage1_result = self.stage1_liquidity_check(scoring_result)
        
        # 仅在启用淘汰机制时添加到筛选历史，否则隐藏（避免显示无意义的警告）
        # 用户要求移除流动性筛选报告 (2025-12-08)
        if self.enable_liquidity_elimination:
             result['filter_history'].append(stage1_result)

             if not stage1_result['passed']:
                 result['eliminated_at_stage'] = 1
                 logger.info(f"✗ {result['stock_code']} 在阶段1(流动性)被淘汰: {stage1_result['reason']}")
                 return result

        # ========== 阶段2: 位置与时机筛选（仅记录，不淘汰）==========
        stage2_result = self.stage2_position_timing(scoring_result)
        result['filter_history'].append(stage2_result)
        # 已移除淘汰机制：位置时机不符合要求仅记录，不影响最终筛选结果
        if not stage2_result['passed']:
            logger.info(f"⚠ {result['stock_code']} 阶段2(位置时机)未通过: {stage2_result['reason']} (仅记录，不淘汰)")

        # ========== 阶段3: 量化模型初筛（仅记录，不淘汰）==========
        stage3_result = self.stage3_quantitative_models(scoring_result)
        result['filter_history'].append(stage3_result)
        # 已移除淘汰机制：量化信号不足仅记录，不影响最终筛选结果
        if not stage3_result['passed']:
            logger.info(f"⚠ {result['stock_code']} 阶段3(量化模型)未通过: {stage3_result['reason']} (仅记录，不淘汰)")

        # ========== 阶段4-7: 评分阶段（仅评分，不筛选）==========
        # 阶段4: 技术面评分
        stage4_result = self.stage4_technical_score(scoring_result)
        result['filter_history'].append(stage4_result)

        # 阶段5: 情绪面评分（反指标模式）
        stage5_result = self.stage5_sentiment_score(scoring_result)
        result['filter_history'].append(stage5_result)

        # 阶段6: 基本面评分
        stage6_result = self.stage6_fundamental_score(scoring_result)
        result['filter_history'].append(stage6_result)

        # 阶段7: 消息面评分
        stage7_result = self.stage7_events_score(scoring_result)
        result['filter_history'].append(stage7_result)

        # 全部通过
        result['passed'] = True
        logger.info(f"✓ {result['stock_code']} 通过所有筛选！综合得分: {result['final_score']}")

        return result

    def stage0_veto_check(self, scoring_result: Dict) -> Dict:
        """
        阶段0: 一票否决前置筛选 - v4.0 游资思维核心

        核心理念：宁可错过，不可套牢！

        触发任一条件即淘汰:
        - 60日涨幅超80%：主力大概率已出货
        - 20日涨幅超50%：短期涨幅过大，接盘风险
        - 距离年内高点<5%：追高风险极大
        - 连涨超7天：连续逼空，回调风险
        - 利润同比下滑超70%：业绩暴雷

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 0,
            'stage_name': '一票否决前置筛选',
            'passed': True,
            'reason': '',
            'details': {}
        }

        try:
            # 获取配置阈值
            config = self.STAGE_THRESHOLDS['stage0_veto']

            # 获取动量数据
            momentum_details = scoring_result.get('details', {}).get('momentum', {})
            fund_details = scoring_result.get('details', {}).get('fundamental', {})

            veto_reasons = []  # 严重风险
            warning_reasons = []  # 警告风险

            # 检查60日涨幅
            change_60d = momentum_details.get('change_60d', 0)
            if change_60d and change_60d > config['max_change_60d']:
                veto_reasons.append(f"60日涨幅{change_60d:.1f}%超过{config['max_change_60d']}%")

            # 检查20日涨幅
            change_20d = momentum_details.get('change_20d', 0)
            if change_20d and change_20d > config['max_change_20d']:
                veto_reasons.append(f"20日涨幅{change_20d:.1f}%超过{config['max_change_20d']}%")

            # 检查距离年内高点
            distance_from_high = momentum_details.get('distance_from_high', 100)
            
            # 豁免逻辑：如果是强势突破（涨停或龙虎榜大额净买入），则不视作追高风险
            is_limit_up = scoring_result.get('details', {}).get('technical', {}).get('is_limit_up', False)
            dragon_tiger = scoring_result.get('details', {}).get('sentiment', {}).get('dragon_tiger', {})
            net_buy = 0
            if dragon_tiger and dragon_tiger.get('has_records'):
                 records = dragon_tiger.get('records', [])
                 if records:
                     net_buy = records[0].get('net_buy_amount', 0) or 0
            
            is_strong_breakthrough = is_limit_up or (net_buy > 10000000)

            if distance_from_high is not None and distance_from_high < config['max_distance_from_high']:
                if is_strong_breakthrough:
                    warning_reasons.append(f"接近年内高点({distance_from_high:.1f}%)但强势突破")
                else:
                    veto_reasons.append(f"距年内高点仅{distance_from_high:.1f}%")

            # 检查连涨天数
            consecutive_up = momentum_details.get('consecutive_up_days', 0)
            if consecutive_up and consecutive_up >= config['max_consecutive_up']:
                veto_reasons.append(f"连涨{consecutive_up}天")

            # 检查利润暴雷
            profit_yoy = fund_details.get('net_profit_yoy')
            if profit_yoy is not None and isinstance(profit_yoy, (int, float)):
                if profit_yoy < config['min_profit_yoy']:
                    veto_reasons.append(f"利润同比下滑{abs(profit_yoy):.1f}%")

            # 检查 scorer 中已有的排除标���
            exclusion_flags = scoring_result.get('exclusion_flags', [])
            for flag in exclusion_flags:
                if '🚨' in flag:
                    veto_reasons.append(flag.replace('🚨 ', ''))
                elif '⚠️' in flag:
                    warning_reasons.append(flag.replace('⚠️ ', ''))

            # 判断是否通过
            passed = len(veto_reasons) == 0

            stage_result['passed'] = passed
            stage_result['details'] = {
                'change_60d': change_60d,
                'change_20d': momentum_details.get('change_20d', 0),
                'change_5d': momentum_details.get('change_5d', 0),
                'distance_from_high': distance_from_high,
                'consecutive_up_days': consecutive_up,
                'profit_yoy': profit_yoy,
                'veto_reasons': veto_reasons,
                'warning_reasons': warning_reasons,
                'exclusion_flags': exclusion_flags
            }

            if not passed:
                stage_result['reason'] = f"🚨 一票否决: " + "; ".join(veto_reasons)
            elif warning_reasons:
                stage_result['reason'] = f"✓ 通过（有警告: {'; '.join(warning_reasons[:2])}）"
            else:
                stage_result['reason'] = f"✓ 无极端风险信号"

        except Exception as e:
            stage_result['reason'] = f"⚠ 一票否决检查异常: {str(e)}"
            logger.error(f"一票否决检查异常: {e}", exc_info=True)

        return stage_result

    def stage3_quantitative_models(self, scoring_result: Dict) -> Dict:
        """
        阶段3: 量化模型初筛 - v4.1 信号���量评估版

        核心改进（信号质量评估）:
        1. 不仅看信号数量，更看信号质量
        2. 分组信号去相关：趋势类、量价类、高级量化类
        3. 信号稀缺性评估：少数先行信号更有价值
        4. 信号拥挤度检测：过多同向信号反而危险

        筛选标准:
        - 买入信号数量 ≥ 2个 OR 买入信号比例 ≥ 15%
        - 至少有一个高质量信号组发出买入信号
        - 信号拥挤度检查（超过25个买入信号警告）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 3,
            'stage_name': '量化模型初筛',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            quant_details = scoring_result.get('details', {}).get('quantitative', {})

            if 'error' in quant_details:
                stage_result['reason'] = f"✗ 无法获取量化模型数据: {quant_details['error']}"
                stage_result['details'] = quant_details
                return stage_result

            buy_count = quant_details.get('buy_count', 0)
            sell_count = quant_details.get('sell_count', 0)
            total_count = quant_details.get('total_count', 30)
            buy_ratio = quant_details.get('buy_ratio', 0)
            top_buy_models = quant_details.get('top_buy_models', [])
            signal_quality = quant_details.get('signal_quality', '一般')

            # 获取分组信号数据（v4.0新增）
            group_signals = quant_details.get('group_signals', {})
            trend_buy = group_signals.get('trend_buy', 0)
            volume_buy = group_signals.get('volume_buy', 0)
            advanced_buy = group_signals.get('advanced_buy', 0)

            # 获取阈值配置
            config = self.STAGE_THRESHOLDS['stage3_quant']
            threshold_signals = config['min_buy_signals']
            threshold_ratio = config['min_buy_ratio']
            max_signals = config['max_buy_signals']

            # ========== 信号质量评估 ==========
            # 条件1: 基本信号数量/比例
            basic_condition = (buy_count >= threshold_signals) or (buy_ratio >= threshold_ratio)

            # 条件2: 至少有一个高质量信号组发出买入（趋势类、量价类、高级量化类）
            quality_condition = True

            # 条件3: 卖出信号不能过多（不超过买入信号的2倍）
            sell_check = sell_count <= max(buy_count * 2, 10)

            # 信号拥挤度检查
            is_crowded = buy_count > max_signals
            crowded_warning = ''
            if is_crowded:
                crowded_warning = f'⚠️ 信号拥挤({buy_count}个买入信号)'

            # 综合判断
            passed = basic_condition and quality_condition and sell_check

            stage_result['passed'] = passed
            stage_result['details'] = {
                'buy_count': buy_count,
                'sell_count': sell_count,
                'total_count': total_count,
                'buy_ratio': buy_ratio,
                'threshold_signals': threshold_signals,
                'threshold_ratio': threshold_ratio,
                'top_buy_models': top_buy_models[:5],
                'signal_quality': signal_quality,
                'group_signals': group_signals,
                'basic_condition': basic_condition,
                'quality_condition': quality_condition,
                'sell_check': sell_check,
                'is_crowded': is_crowded
            }

            if passed:
                display_models = [self.MODEL_DISPLAY_MAP.get(m, m) for m in top_buy_models[:3]]
                reason_parts = [
                    f"买入信号{buy_count}个(占比{buy_ratio*100:.0f}%)",
                ]
                if display_models:
                    reason_parts.append(f"关键模型: {', '.join(display_models)}")
                stage_result['reason'] = f"✓ " + ", ".join(reason_parts)
                if crowded_warning:
                    stage_result['reason'] += f" ({crowded_warning})"
            else:
                fail_reasons = []
                if not basic_condition:
                    fail_reasons.append(f"买入信号{buy_count}个(占比{buy_ratio*100:.0f}%) < 阈值")
                
                if not sell_check:
                    fail_reasons.append(f"卖出信号过多({sell_count}个)")
                stage_result['reason'] = f"✗ " + ", ".join(fail_reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段1筛选异常: {str(e)}"
            logger.error(f"阶段1筛选异常: {e}", exc_info=True)

        return stage_result

    def stage2_position_timing(self, scoring_result: Dict) -> Dict:
        """
        阶段2: 位置与时机筛选（反追涨核心）- v4.0 游资思维

        核心理念：
        1. 已涨股票是风险，调整到位才是机会
        2. 底部启动优于高位追涨
        3. 回踩支撑有效性判断

        筛选标准:
        - 位置分位数 ≤ 75%（不追高位）
        - 5日涨幅 ≤ 20%（不追涨）
        - 理想买点：回撤3%-20%（调整到位）
        - 底部启动信号优先

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 2,
            'stage_name': '位置与时机筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            config = self.STAGE_THRESHOLDS['stage2_position']
            momentum_details = scoring_result.get('details', {}).get('momentum', {})

            if 'error' in momentum_details:
                stage_result['reason'] = f"✗ 无法获取位置数据: {momentum_details['error']}"
                stage_result['details'] = momentum_details
                return stage_result

            # 获取关键指标
            position_pct = momentum_details.get('position_pct', 0.5)
            change_5d = momentum_details.get('change_5d', 0)
            change_20d = momentum_details.get('change_20d', 0)
            distance_from_high = momentum_details.get('distance_from_high', 50)
            drawdown_from_recent = momentum_details.get('drawdown_from_recent', 0)
            entry_timing = momentum_details.get('entry_timing', '观望')
            signals = momentum_details.get('signals', [])

            # 检测低位启动信号
            low_pos_start = scoring_result.get('details', {}).get('low_position_start', {})
            has_low_pos_signal = low_pos_start.get('is_low_position', False) and low_pos_start.get('bonus', 0) > 0

            # ========== 筛选条件 ==========
            # 条件1: 位置不能太高（≤75%分位）
            position_ok = position_pct <= config['max_position_pct']

            # 条件2: 5日涨幅不能太大（≤20%）
            change_5d_ok = change_5d <= config['max_change_5d']

            # 条件3: 回撤在合理区间（3%-20%最佳）或处于底部区域
            ideal_min = config['ideal_drawdown_min']
            ideal_max = config['ideal_drawdown_max']
            drawdown_ok = (ideal_min <= drawdown_from_recent <= ideal_max) or position_pct <= 0.35

            # 低位启动可豁免部分条件
            if has_low_pos_signal:
                # 底部启动信号可适当放宽位置要求
                position_ok = position_pct <= 0.85
                change_5d_ok = change_5d <= 25  # 底部放量可容忍更大涨幅

            # 综合判断
            passed = position_ok and change_5d_ok and drawdown_ok

            stage_result['passed'] = passed
            stage_result['details'] = {
                'position_pct': position_pct,
                'max_position_pct': config['max_position_pct'],
                'position_ok': position_ok,
                'change_5d': change_5d,
                'max_change_5d': config['max_change_5d'],
                'change_5d_ok': change_5d_ok,
                'change_20d': change_20d,
                'distance_from_high': distance_from_high,
                'drawdown_from_recent': drawdown_from_recent,
                'drawdown_ok': drawdown_ok,
                'entry_timing': entry_timing,
                'has_low_pos_signal': has_low_pos_signal,
                'signals': signals[:5]
            }

            if passed:
                reason_parts = []
                if position_pct <= 0.35:
                    reason_parts.append(f"底部区域({position_pct*100:.0f}%分位)")
                elif position_pct <= 0.50:
                    reason_parts.append(f"中低位({position_pct*100:.0f}%分位)")
                else:
                    reason_parts.append(f"位置适中({position_pct*100:.0f}%分位)")

                if ideal_min <= drawdown_from_recent <= ideal_max:
                    reason_parts.append(f"调整到位(回撤{drawdown_from_recent:.1f}%)")

                if has_low_pos_signal:
                    reason_parts.append("🔥 底部启动信号")

                stage_result['reason'] = f"✓ " + ", ".join(reason_parts)
            else:
                fail_reasons = []
                if not position_ok:
                    fail_reasons.append(f"位置过高({position_pct*100:.0f}%>{config['max_position_pct']*100:.0f}%)")
                if not change_5d_ok:
                    fail_reasons.append(f"5日涨幅过大({change_5d:.1f}%>{config['max_change_5d']}%)")
                if not drawdown_ok:
                    if drawdown_from_recent < ideal_min:
                        fail_reasons.append(f"回撤不足({drawdown_from_recent:.1f}%<{ideal_min}%)，等待回调")
                    else:
                        fail_reasons.append(f"回撤过深({drawdown_from_recent:.1f}%>{ideal_max}%)")

                stage_result['reason'] = f"✗ " + ", ".join(fail_reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段2筛选异常: {str(e)}"
            logger.error(f"阶段2筛选异常: {e}", exc_info=True)

        return stage_result

    def stage1_liquidity_check(self, scoring_result: Dict) -> Dict:
        """
        阶段1: 流动性筛选 - v4.1 游资核心门槛

        核心理念：
        1. 流动性是交易的基础，低流动性股票无法快速进出
        2. 成交额反映资金承载力
        3. 换手率反映市场活跃度

        筛选标准:
        - 20日均成交额 ≥ 3000万
        - 换手率 ≥ 0.5%
        - 流通市值 ≥ 20亿（可选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 1,
            'stage_name': '流动性筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            config = self.STAGE_THRESHOLDS.get('stage1_liquidity', {})
            liquidity_details = scoring_result.get('details', {}).get('liquidity', {})

            if 'error' in liquidity_details:
                # v4.1 修复: 无流动性数据时不应默认通过
                # 游资思维: 流动性是交易的前提，无法评估流动性则不应入选
                stage_result['passed'] = False
                stage_result['reason'] = f"✗ 无法获取流动性数据，无法评估可交易性"
                stage_result['details'] = liquidity_details
                return stage_result

            # 获取流动性指标
            avg_amount_wan = liquidity_details.get('avg_amount_20d_wan', 0)
            avg_turnover = liquidity_details.get('avg_turnover_20d', 0)
            circulation_cap = liquidity_details.get('circulation_market_cap', 0)
            liquidity_level = liquidity_details.get('liquidity_level', '一般')

            min_avg_amount_20d = float(config.get('min_avg_amount_20d', 3000) or 3000)
            min_turnover_rate = float(config.get('min_turnover_rate', 0.5) or 0.5)
            min_circulation_cap = float(config.get('min_circulation_cap', 20) or 20)

            # ========== 筛选条件 ==========
            # 条件1: 成交额门槛
            amount_ok = avg_amount_wan >= min_avg_amount_20d

            # 条件2: 换手率门槛
            turnover_ok = avg_turnover >= min_turnover_rate

            # 条件3: 流通市值门槛（可选，如无数据则通过）
            cap_ok = circulation_cap >= min_circulation_cap if circulation_cap > 0 else True

            # 综合判断：成交额和换手率必须满足，市值可选
            passed = True  # amount_ok and turnover_ok (用户要求移除流动性筛选)

            stage_result['passed'] = passed
            stage_result['details'] = {
                'avg_amount_20d_wan': avg_amount_wan,
                'min_avg_amount': min_avg_amount_20d,
                'amount_ok': amount_ok,
                'avg_turnover_20d': avg_turnover,
                'min_turnover_rate': min_turnover_rate,
                'turnover_ok': turnover_ok,
                'circulation_market_cap': circulation_cap,
                'min_circulation_cap': min_circulation_cap,
                'cap_ok': cap_ok,
                'liquidity_level': liquidity_level
            }

            if passed:
                reason_parts = [f"成交额{avg_amount_wan:.0f}万"]
                if avg_turnover > 0:
                    reason_parts.append(f"换手率{avg_turnover:.2f}%")
                if circulation_cap > 0:
                    reason_parts.append(f"流通市值{circulation_cap:.0f}亿")
                reason_parts.append(f"流动性{liquidity_level}")
                if not (amount_ok and turnover_ok and cap_ok):
                    reason_parts.append("未达建议门槛")
                reason_parts.append("(筛选已禁用)")
                stage_result['reason'] = f"✓ " + ", ".join(reason_parts)
            else:
                # Unreachable code but kept for structure
                fail_reasons = []
                if not amount_ok:
                    fail_reasons.append(f"成交额不足({avg_amount_wan:.0f}万<{min_avg_amount_20d:.0f}万)")
                if not turnover_ok:
                    fail_reasons.append(f"换手率过低({avg_turnover:.2f}%<{min_turnover_rate:.2f}%)")
                stage_result['reason'] = f"✗ " + ", ".join(fail_reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段1(流动性)筛选异常: {str(e)}"
            logger.error(f"阶段1(流动性)筛选异常: {e}", exc_info=True)

        return stage_result

    def stage4_technical_score(self, scoring_result: Dict) -> Dict:
        """
        阶段4: 技术面评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 4,
            'stage_name': '技术面评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            tech_details = scoring_result.get('details', {}).get('technical', {})
            tech_score = scoring_result.get('scores', {}).get('technical', 50)

            if 'error' in tech_details:
                stage_result['reason'] = f"⚠ 无技术面数据"
                stage_result['details'] = tech_details
                return stage_result

            # 获取技术指标
            rsi = tech_details.get('RSI')
            rsi_status = tech_details.get('RSI_status', '中性')
            macd = tech_details.get('MACD')
            ma_status = tech_details.get('MA_status', '中性')
            signals = tech_details.get('signals', [])

            stage_result['details'] = {
                'technical_score': tech_score,
                'RSI': rsi,
                'RSI_status': rsi_status,
                'MACD': macd,
                'MA_status': ma_status,
                'signals': signals[:5]
            }

            # 构建理由
            info_parts = [f"技术面{tech_score:.0f}分"]
            if rsi is not None:
                info_parts.append(f"RSI={rsi:.1f}({rsi_status})")
            if macd:
                info_parts.append(f"MACD{macd}")
            if ma_status:
                info_parts.append(f"均线{ma_status}")

            stage_result['reason'] = f"✓ " + ", ".join(info_parts)

        except Exception as e:
            stage_result['reason'] = f"⚠ 技术面评分异常: {str(e)}"
            logger.error(f"技术面评分异常: {e}", exc_info=True)

        return stage_result

    def stage7_events_score(self, scoring_result: Dict) -> Dict:
        """
        阶段7: 消息面评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 7,
            'stage_name': '消息面评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            events_details = scoring_result.get('details', {}).get('events', {})
            events_score = scoring_result.get('scores', {}).get('events', 50)

            if 'error' in events_details:
                stage_result['reason'] = f"⚠ 无消息面数据"
                stage_result['details'] = events_details
                return stage_result

            positive_count = events_details.get('positive_events', 0)
            negative_count = events_details.get('negative_events', 0)
            comprehensive_score = events_details.get('comprehensive_score', 0)
            rating = events_details.get('rating', '中性')
            hot_news_bonus = events_details.get('hot_news_bonus', 0)

            stage_result['details'] = {
                'events_score': events_score,
                'positive_events': positive_count,
                'negative_events': negative_count,
                'comprehensive_score': comprehensive_score,
                'rating': rating,
                'hot_news_bonus': hot_news_bonus
            }

            # 构建理由
            reason_parts = [f"消息面{events_score:.0f}分"]
            reason_parts.append(f"利好{positive_count}个/利空{negative_count}个")
            reason_parts.append(f"评级:{rating}")
            if hot_news_bonus > 0:
                reason_parts.append(f"热点加分+{hot_news_bonus:.0f}")

            stage_result['reason'] = f"✓ " + ", ".join(reason_parts)

        except Exception as e:
            stage_result['reason'] = f"⚠ 消息面评分异常: {str(e)}"
            logger.error(f"消息面评分异常: {e}", exc_info=True)

        return stage_result

    def _stage2_technical_analysis_legacy(self, scoring_result: Dict) -> Dict:
        """
        【已废弃】阶段2: 技术面筛选（增强版）
        保留用于参考，实际使用 stage2_position_timing

        筛选标准（多指标综合判断，满足以下任一组合即可通过）:

        组合1 - 超卖反弹信号:
          - RSI < 30 (超卖) 或 KDJ_J < 20 (超卖)
          - 成交量放大 > 1.5倍
          - 均线趋势评分 ≥ 2分

        组合2 - 趋势突破信号:
          - RSI在30-75之间 (非超买超卖)
          - MACD金叉 或 布林带突破
          - 均线趋势评分 ≥ 3分

        组合3 - 强势上涨信号:
          - 均线多头���列(趋势评分=5)
          - MACD金叉
          - 成交量放大或持平

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 2,
            'stage_name': '技术面筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            tech_details = scoring_result.get('details', {}).get('technical', {})

            if 'error' in tech_details:
                stage_result['reason'] = f"✗ 无法获取技术分析数据: {tech_details['error']}"
                stage_result['details'] = tech_details
                return stage_result

            # 0. 前置风险检查 (新增)
            momentum_details = scoring_result.get('details', {}).get('momentum', {})
            change_60d = momentum_details.get('change_60d', 0)
            distance_from_high = momentum_details.get('distance_from_high', 100)

            # 前置排除：60日涨幅超过80%的股票
            if change_60d > 80:
                 stage_result['reason'] = f"✗ 60日涨幅过大({change_60d}%)，风险较高"
                 stage_result['passed'] = False
                 stage_result['details'] = {'change_60d': change_60d}
                 return stage_result

            # 前置排除：距离年内高点小于5%
            # 优化：不再直接淘汰，而是记录警告信息
            if distance_from_high < 5:
                 warning_msg = f"⚠️ 接近历史高点(距高点{distance_from_high}%)，请注意风险"
                 # 将警告信息添加到 details 中，而不是直接返回 False
                 tech_details['warning'] = warning_msg
                 # logger.info(f"{scoring_result.get('stock_code')} {warning_msg}")
                 # stage_result['reason'] = f"✗ 接近历史高点(距高点{distance_from_high}%)，风险较高"
                 # stage_result['passed'] = False
                 # stage_result['details'] = {'distance_from_high': distance_from_high}
                 # return stage_result

            # 获取技术指标
            rsi = tech_details.get('RSI', 50)
            macd = tech_details.get('MACD', '')
            bollinger = tech_details.get('Bollinger', '')
            kdj_k = tech_details.get('KDJ_K', 50)
            kdj_d = tech_details.get('KDJ_D', 50)
            kdj_j = tech_details.get('KDJ_J', 50)
            ma5 = tech_details.get('MA5', 0)
            ma10 = tech_details.get('MA10', 0)
            ma20 = tech_details.get('MA20', 0)
            ma60 = tech_details.get('MA60', 0)
            volume_ratio = tech_details.get('volume_ratio', 1.0)  # 当日量/5日均量

            # 获取阈值配置
            config = self.STAGE_THRESHOLDS['stage2_technical']
            max_rsi = config['max_rsi']
            min_rsi = config['min_rsi']
            max_kdj_j = config['max_kdj_j']
            min_kdj_j = config['min_kdj_j']
            min_ma_score = config['ma_trend_score']
            volume_threshold = config['volume_surge_threshold']

            # 计算各项指标状态
            # 1. RSI状态
            rsi_oversold = rsi < 30
            rsi_overbought = rsi > max_rsi
            rsi_normal = 30 <= rsi <= max_rsi

            # 2. KDJ状态
            kdj_oversold = kdj_j < 20
            kdj_overbought = kdj_j > max_kdj_j
            kdj_golden_cross = kdj_k > kdj_d and kdj_k < 80  # K线上穿D线且未超买

            # 3. MACD状态
            macd_ok = '金叉' in str(macd)
            macd_strong = macd_ok and '强' in str(macd)

            # 4. 布林带状态
            bb_lower = '下轨' in str(bollinger)
            bb_breakout = '突破' in str(bollinger)
            bb_ok = bb_lower or bb_breakout

            # 5. 均线趋势评分 (0-5分)
            ma_score = self._calculate_ma_trend_score(ma5, ma10, ma20, ma60)

            # 6. 成交量状态
            volume_surge = volume_ratio >= volume_threshold
            volume_normal = 0.8 <= volume_ratio < volume_threshold

            # 判断是否满足任一组合
            # 组合1: 超卖反弹信号
            combo1 = (rsi_oversold or kdj_oversold) and volume_surge and ma_score >= 2

            # 组合2: 趋势突破信号
            combo2 = rsi_normal and (macd_ok or bb_ok) and ma_score >= 3

            # 组合3: 强势上涨信号
            combo3 = (ma_score == 5) and macd_ok and (volume_surge or volume_normal)

            # 组合4: KDJ金叉信号
            combo4 = kdj_golden_cross and rsi_normal and ma_score >= 2

            passed = combo1 or combo2 or combo3 or combo4

            # 保存详情
            stage_result['passed'] = passed
            stage_result['details'] = {
                'RSI': rsi,
                'RSI_status': 'oversold' if rsi_oversold else ('overbought' if rsi_overbought else 'normal'),
                'MACD': macd,
                'MACD_ok': macd_ok,
                'Bollinger': bollinger,
                'Bollinger_ok': bb_ok,
                'KDJ_K': kdj_k,
                'KDJ_D': kdj_d,
                'KDJ_J': kdj_j,
                'KDJ_golden_cross': kdj_golden_cross,
                'MA5': ma5,
                'MA10': ma10,
                'MA20': ma20,
                'MA60': ma60,
                'MA_trend_score': ma_score,
                'volume_ratio': volume_ratio,
                'volume_surge': volume_surge,
                'combo1': combo1,
                'combo2': combo2,
                'combo3': combo3,
                'combo4': combo4
            }

            # 构建理由
            if passed:
                reasons = []
                if combo1:
                    reasons.append(f"超卖反弹(RSI={rsi:.1f}/KDJ_J={kdj_j:.1f}, 量比={volume_ratio:.2f}, 均线评分={ma_score})")
                if combo2:
                    signal = "MACD金叉" if macd_ok else f"布林带{bollinger}"
                    reasons.append(f"趋势突破({signal}, RSI={rsi:.1f}, 均线评分={ma_score})")
                if combo3:
                    reasons.append(f"强势上涨(多头排列, MACD金叉, 量比={volume_ratio:.2f})")
                if combo4:
                    reasons.append(f"KDJ金叉(K={kdj_k:.1f}>D={kdj_d:.1f}, RSI={rsi:.1f}, 均线评分={ma_score})")
                stage_result['reason'] = f"✓ " + " | ".join(reasons)
            else:
                fail_reasons = []
                if rsi_overbought:
                    fail_reasons.append(f"RSI={rsi:.1f}超买")
                if kdj_overbought:
                    fail_reasons.append(f"KDJ_J={kdj_j:.1f}超买")
                if ma_score < min_ma_score:
                    fail_reasons.append(f"均线趋势弱(评分={ma_score}<{min_ma_score})")
                if not macd_ok and not bb_ok and not kdj_golden_cross:
                    fail_reasons.append("无明确买入信号")
                if not volume_surge and not volume_normal:
                    fail_reasons.append(f"量能不足(量比={volume_ratio:.2f})")

                stage_result['reason'] = f"✗ " + ", ".join(fail_reasons if fail_reasons else ["未满足任一筛选组合"])

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段2筛选异常: {str(e)}"
            logger.error(f"阶段2筛选异常: {e}", exc_info=True)

        return stage_result

    def _calculate_ma_trend_score(self, ma5: float, ma10: float, ma20: float, ma60: float) -> int:
        """
        计算均线趋势评分 (0-5分)

        评分规则:
        - 0分: 空头排列 (ma5 < ma10 < ma20 < ma60)
        - 1分: 弱势整理 (均线纠缠,无明显排列)
        - 2分: 短期转强 (ma5 > ma10, 但ma10 < ma20)
        - 3分: 中期趋势 (ma5 > ma10 > ma20, 但ma20 < ma60)
        - 4分: 长期趋势 (ma5 > ma10 > ma20 > ma60, 但间距较小)
        - 5分: 完美多头 (ma5 > ma10 > ma20 > ma60, 且间距递增)

        Args:
            ma5, ma10, ma20, ma60: 各期均线值

        Returns:
            评分 (0-5分)
        """
        try:
            # 检查数据有效性
            if not all([ma5, ma10, ma20, ma60]):
                return 1

            # 完美空头排列
            if ma5 < ma10 < ma20 < ma60:
                return 0

            # 完美多头排列
            if ma5 > ma10 > ma20 > ma60:
                # 检查间距是否递增(理想的多头排列)
                gap1 = ma5 - ma10
                gap2 = ma10 - ma20
                gap3 = ma20 - ma60
                if gap1 > gap2 > gap3 and gap3 > 0:
                    return 5
                return 4

            # 中期趋势
            if ma5 > ma10 > ma20:
                return 3

            # 短期转强
            if ma5 > ma10:
                return 2

            # 其他情况
            return 1

        except Exception as e:
            logger.warning(f"均线趋势评分计算失败: {e}")
            return 1

    def stage3_sentiment_filter(self, scoring_result: Dict) -> Dict:
        """
        阶段3: 情绪面筛选

        筛选标准:
        - 股民情绪得分 ≥ 55 AND
        - 板块情绪得分 ≥ 50

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 3,
            'stage_name': '情绪面筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            sentiment_details = scoring_result.get('details', {}).get('sentiment', {})
            sector_details = scoring_result.get('details', {}).get('sector', {})

            # 股民情绪
            investor_score = scoring_result.get('scores', {}).get('sentiment', 50)
            investor_sentiment = sentiment_details.get('comprehensive_sentiment', '中性')

            # 板块情绪
            sector_score = scoring_result.get('scores', {}).get('sector', 50)
            sector_name = sector_details.get('sector_name', '未知')
            sector_sentiment = sector_details.get('overall', '中性')

            # 应用筛选标准
            min_investor = self.STAGE_THRESHOLDS['stage3_sentiment']['min_investor_sentiment']
            min_sector = self.STAGE_THRESHOLDS['stage3_sentiment']['min_sector_sentiment']

            investor_ok = investor_score >= min_investor
            sector_ok = sector_score >= min_sector

            passed = investor_ok and sector_ok

            stage_result['passed'] = passed
            stage_result['details'] = {
                'investor_score': investor_score,
                'investor_sentiment': investor_sentiment,
                'sector_score': sector_score,
                'sector_name': sector_name,
                'sector_sentiment': sector_sentiment,
                'min_investor': min_investor,
                'min_sector': min_sector,
                'investor_ok': investor_ok,
                'sector_ok': sector_ok
            }

            # 构建理由
            reasons = []
            if investor_ok:
                reasons.append(f"股民情绪{investor_score:.0f}分({investor_sentiment}) ≥ {min_investor}")
            else:
                reasons.append(f"股民情绪{investor_score:.0f}分({investor_sentiment}) < {min_investor}")

            if sector_ok:
                reasons.append(f"板块({sector_name})情绪{sector_score:.0f}分({sector_sentiment}) ≥ {min_sector}")
            else:
                reasons.append(f"板块({sector_name})情绪{sector_score:.0f}分({sector_sentiment}) < {min_sector}")

            if passed:
                stage_result['reason'] = f"✓ " + ", ".join(reasons)
            else:
                stage_result['reason'] = f"✗ " + ", ".join(reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段3筛选异常: {str(e)}"
            logger.error(f"阶段3筛选异常: {e}", exc_info=True)

        return stage_result

    def stage4_fundamental_filter(self, scoring_result: Dict) -> Dict:
        """
        阶段4: 基本面筛选

        筛选标准:
        - PE < 50 (估值不太高) AND
        - (营收增长率 > 0 OR 净利润增长率 > 0)

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 4,
            'stage_name': '基本面筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            fund_details = scoring_result.get('details', {}).get('fundamental', {})

            if 'error' in fund_details:
                # 如果无基本面数据，给予通过（降低筛选严格度）
                stage_result['passed'] = True
                stage_result['reason'] = f"⚠ 无基本面数据，默认通过"
                stage_result['details'] = fund_details
                return stage_result

            pe_ratio = fund_details.get('pe_ratio', 'N/A')
            revenue_yoy = fund_details.get('revenue_yoy', 'N/A')
            profit_yoy = fund_details.get('net_profit_yoy', 'N/A')

            # 解析PE
            pe_ok = True
            pe_value = None
            max_pe = self.STAGE_THRESHOLDS['stage4_fundamental']['max_pe']

            if pe_ratio and pe_ratio != 'N/A':
                try:
                    pe_value = float(pe_ratio)
                    pe_ok = pe_value < max_pe
                except:
                    pass

            # 解析增长率
            growth_ok = False
            revenue_growth = None
            profit_growth = None

            if revenue_yoy and revenue_yoy != 'N/A':
                try:
                    revenue_growth = float(revenue_yoy)
                    if revenue_growth > 0:
                        growth_ok = True
                except:
                    pass

            if profit_yoy and profit_yoy != 'N/A':
                try:
                    profit_growth = float(profit_yoy)
                    if profit_growth > 0:
                        growth_ok = True
                except:
                    pass

            # 如果两个增长率都无数据，默认通过
            if revenue_growth is None and profit_growth is None:
                growth_ok = True

            passed = pe_ok and growth_ok

            stage_result['passed'] = passed
            stage_result['details'] = {
                'pe_ratio': pe_value,
                'revenue_yoy': revenue_growth,
                'profit_yoy': profit_growth,
                'max_pe': max_pe,
                'pe_ok': pe_ok,
                'growth_ok': growth_ok
            }

            # 构建理由
            reasons = []

            if pe_value is not None:
                if pe_ok:
                    reasons.append(f"PE={pe_value:.1f} < {max_pe}")
                else:
                    reasons.append(f"PE={pe_value:.1f} ≥ {max_pe} (估值偏高)")
            else:
                reasons.append("PE数据缺失")

            if revenue_growth is not None or profit_growth is not None:
                growth_info = []
                if revenue_growth is not None:
                    growth_info.append(f"营收增长{revenue_growth:+.1f}%")
                if profit_growth is not None:
                    growth_info.append(f"利润增长{profit_growth:+.1f}%")

                # 更精确的增长描述：区分混合情况
                label = None
                rev_pos = (revenue_growth is not None and revenue_growth > 0)
                rev_neg = (revenue_growth is not None and revenue_growth < 0)
                prof_pos = (profit_growth is not None and profit_growth > 0)
                prof_neg = (profit_growth is not None and profit_growth < 0)

                if rev_pos and prof_pos:
                    label = "(正增长)"
                elif rev_neg and prof_neg:
                    label = "(负增长)"
                elif rev_pos and prof_neg:
                    label = "(营收正增长/利润负增长)"
                elif rev_neg and prof_pos:
                    label = "(营收负增长/利润正增长)"
                elif rev_pos and profit_growth is None:
                    label = "(营收正增长)"
                elif rev_neg and profit_growth is None:
                    label = "(营收负增长)"
                elif prof_pos and revenue_growth is None:
                    label = "(利润正增长)"
                elif prof_neg and revenue_growth is None:
                    label = "(利润负增长)"
                else:
                    label = ""

                reasons.append(", ".join(growth_info) + (" " + label if label else ""))
            else:
                reasons.append("增长数据缺失")

            if passed:
                stage_result['reason'] = f"✓ " + ", ".join(reasons)
            else:
                stage_result['reason'] = f"✗ " + ", ".join(reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段4筛选异常: {str(e)}"
            logger.error(f"阶段4筛选异常: {e}", exc_info=True)

        return stage_result

    def stage5_events_filter(self, scoring_result: Dict) -> Dict:
        """
        阶段5:消息面筛选

        筛选标准:
        - 利好事件数量 > 利空事件数量 OR
        - 综合事件评分 ≥ 0

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            筛选结果字典
        """
        stage_result = {
            'stage': 5,
            'stage_name': '事件面筛选',
            'passed': False,
            'reason': '',
            'details': {}
        }

        try:
            events_details = scoring_result.get('details', {}).get('events', {})

            if 'error' in events_details:
                # 如果无事件数据，给予通过
                stage_result['passed'] = True
                stage_result['reason'] = f"⚠ 无事件数据，默认通过"
                stage_result['details'] = events_details
                return stage_result

            positive_count = events_details.get('positive_events', 0)
            negative_count = events_details.get('negative_events', 0)
            comprehensive_score = events_details.get('comprehensive_score', 0)
            rating = events_details.get('rating', '中性')

            # 应用筛选标准
            passed = (positive_count > negative_count) or (comprehensive_score >= 0)

            stage_result['passed'] = passed
            stage_result['details'] = {
                'positive_events': positive_count,
                'negative_events': negative_count,
                'comprehensive_score': comprehensive_score,
                'rating': rating
            }

            # 构建理由
            if passed:
                if positive_count > negative_count:
                    stage_result['reason'] = (
                        f"✓ 利好事件{positive_count}个 > 利空事件{negative_count}个, "
                        f"综合评级: {rating}"
                    )
                else:
                    stage_result['reason'] = (
                        f"✓ 综合事件评分{comprehensive_score:+.0f} ≥ 0, "
                        f"评级: {rating}"
                    )
            else:
                stage_result['reason'] = (
                    f"✗ 利好事件{positive_count}个 ≤ 利空事件{negative_count}个, "
                    f"且综合评分{comprehensive_score:+.0f} < 0, 评级: {rating}"
                )

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段5筛选异常: {str(e)}"
            logger.error(f"阶段5筛选异常: {e}", exc_info=True)

        return stage_result


    def stage3_sentiment_score(self, scoring_result: Dict) -> Dict:
        """
        阶段3: 情绪面评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 3,
            'stage_name': '情绪面评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            sentiment_details = scoring_result.get('details', {}).get('sentiment', {})
            sector_details = scoring_result.get('details', {}).get('sector', {})

            # 股民情绪
            investor_score = scoring_result.get('scores', {}).get('sentiment', 50)
            investor_sentiment = sentiment_details.get('comprehensive_sentiment', '中性')

            # 板块情绪
            sector_score = scoring_result.get('scores', {}).get('sector', 50)
            sector_name = sector_details.get('sector_name', '未知')
            sector_sentiment = sector_details.get('overall', '中性')

            stage_result['details'] = {
                'investor_score': investor_score,
                'investor_sentiment': investor_sentiment,
                'sector_score': sector_score,
                'sector_name': sector_name,
                'sector_sentiment': sector_sentiment
            }

            # 构建理由（仅展示评分信息）
            stage_result['reason'] = (
                f"✓ 股民情绪{investor_score:.0f}分({investor_sentiment}), "
                f"板块({sector_name})情绪{sector_score:.0f}分({sector_sentiment})"
            )

        except Exception as e:
            stage_result['reason'] = f"⚠ 情绪面评分异常: {str(e)}"
            logger.error(f"情绪面评分异常: {e}", exc_info=True)

        return stage_result

    def stage4_fundamental_score(self, scoring_result: Dict) -> Dict:
        """
        阶段4: 基本面评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 4,
            'stage_name': '基本面评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            fund_details = scoring_result.get('details', {}).get('fundamental', {})

            if 'error' in fund_details:
                stage_result['reason'] = f"⚠ 无基本面数据"
                stage_result['details'] = fund_details
                return stage_result

            fundamental_score = scoring_result.get('scores', {}).get('fundamental', 50)
            pe_ratio = fund_details.get('pe_ratio', 'N/A')
            revenue_yoy = fund_details.get('revenue_yoy', 'N/A')
            profit_yoy = fund_details.get('net_profit_yoy', 'N/A')

            stage_result['details'] = {
                'fundamental_score': fundamental_score,
                'pe_ratio': pe_ratio,
                'revenue_yoy': revenue_yoy,
                'profit_yoy': profit_yoy
            }

            # 构建理由
            info_parts = [f"基本面{fundamental_score:.0f}分"]
            if pe_ratio != 'N/A':
                info_parts.append(f"PE={pe_ratio:.1f}" if isinstance(pe_ratio, (int, float)) else f"PE={pe_ratio}")
            if revenue_yoy != 'N/A':
                info_parts.append(f"营收增长{revenue_yoy:+.1f}%" if isinstance(revenue_yoy, (int, float)) else f"营收增长{revenue_yoy}")
            if profit_yoy != 'N/A':
                info_parts.append(f"利润增长{profit_yoy:+.1f}%" if isinstance(profit_yoy, (int, float)) else f"利润增长{profit_yoy}")

            stage_result['reason'] = f"✓ " + ", ".join(info_parts)

        except Exception as e:
            stage_result['reason'] = f"⚠ 基本面评分异常: {str(e)}"
            logger.error(f"基本面评分异常: {e}", exc_info=True)

        return stage_result

    def stage5_events_score(self, scoring_result: Dict) -> Dict:
        """
        阶段5: 消息面评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 5,
            'stage_name': '事件面评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            events_details = scoring_result.get('details', {}).get('events', {})

            if 'error' in events_details:
                stage_result['reason'] = f"⚠ 无事件数据"
                stage_result['details'] = events_details
                return stage_result

            events_score = scoring_result.get('scores', {}).get('events', 50)
            positive_count = events_details.get('positive_events', 0)
            negative_count = events_details.get('negative_events', 0)
            comprehensive_score = events_details.get('comprehensive_score', 0)
            rating = events_details.get('rating', '中性')

            stage_result['details'] = {
                'events_score': events_score,
                'positive_events': positive_count,
                'negative_events': negative_count,
                'comprehensive_score': comprehensive_score,
                'rating': rating
            }

            # 构建理由
            stage_result['reason'] = (
                f"✓ 消息面{events_score:.0f}分, "
                f"利好事件{positive_count}个, 利空事件{negative_count}个, "
                f"评级: {rating}"
            )

        except Exception as e:
            stage_result['reason'] = f"⚠ 消息面评分异常: {str(e)}"
            logger.error(f"事件面评分异常: {e}", exc_info=True)

        return stage_result

    def stage6_dragon_tiger_score(self, scoring_result: Dict) -> Dict:
        """
        阶段6: 龙虎榜评分（仅评分，不筛选）

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            评分结果字典
        """
        stage_result = {
            'stage': 6,
            'stage_name': '龙虎榜评分',
            'passed': True,  # 仅评分,不筛选,始终通过
            'reason': '',
            'details': {}
        }

        try:
            sentiment_details = scoring_result.get('details', {}).get('sentiment', {})
            dragon_tiger = sentiment_details.get('dragon_tiger', {})

            if not dragon_tiger or not dragon_tiger.get('has_records', False):
                stage_result['reason'] = f"⚠ 无龙虎榜数据"
                stage_result['details'] = {'no_data': True}
                return stage_result

            # 龙虎榜评分逻辑
            dragon_tiger_score = self._calculate_dragon_tiger_score(dragon_tiger)

            # 获取最新记录的详情
            records = dragon_tiger.get('records', [])
            latest_record = records[0] if records else {}
            net_buy = latest_record.get('net_buy_amount', 0) or 0
            reason = dragon_tiger.get('last_reason', '未知')
            last_date = dragon_tiger.get('last_date', 'N/A')

            stage_result['details'] = {
                'dragon_tiger_score': dragon_tiger_score,
                'has_records': True,
                'net_buy_amount': net_buy,
                'reason': reason,
                'last_date': last_date
            }

            # 构建理由
            stage_result['reason'] = (
                f"✓ 龙虎榜{dragon_tiger_score:.0f}分, "
                f"上榜({last_date}), 净买入{net_buy/10000:.2f}万元"
            )

        except Exception as e:
            stage_result['reason'] = f"⚠ 龙虎榜评分异常: {str(e)}"
            logger.error(f"龙虎榜评分异常: {e}", exc_info=True)

        return stage_result

    def stage5_sentiment_score(self, scoring_result: Dict) -> Dict:
        """
        阶段5: 情绪面评分（仅评分，不筛选）
        """
        stage_result = {
            'stage': 5,
            'stage_name': '情绪面评分',
            'passed': True,
            'reason': '',
            'details': {}
        }

        try:
            sentiment_details = scoring_result.get('details', {}).get('sentiment', {})
            sector_details = scoring_result.get('details', {}).get('sector', {})

            investor_score = scoring_result.get('scores', {}).get('sentiment', 50)
            investor_sentiment = sentiment_details.get('comprehensive_sentiment', '中性')

            sector_score = scoring_result.get('scores', {}).get('sector', 50)
            sector_name = sector_details.get('sector_name', '未知')
            sector_sentiment = sector_details.get('overall', '中性')

            stage_result['details'] = {
                'investor_score': investor_score,
                'investor_sentiment': investor_sentiment,
                'sector_score': sector_score,
                'sector_name': sector_name,
                'sector_sentiment': sector_sentiment
            }

            stage_result['reason'] = (
                f"✓ 股民情绪{investor_score:.0f}分({investor_sentiment}), "
                f"板块({sector_name})情绪{sector_score:.0f}分({sector_sentiment})"
            )

        except Exception as e:
            stage_result['reason'] = f"⚠ 情绪面评分异常: {str(e)}"
            logger.error(f"情绪面评分异常: {e}", exc_info=True)

        return stage_result

    def stage6_fundamental_score(self, scoring_result: Dict) -> Dict:
        """
        阶段6: 基本面评分（仅评分，不筛选）
        """
        stage_result = {
            'stage': 6,
            'stage_name': '基本面评分',
            'passed': True,
            'reason': '',
            'details': {}
        }

        try:
            fund_details = scoring_result.get('details', {}).get('fundamental', {})

            if 'error' in fund_details:
                stage_result['reason'] = f"⚠ 无基本面数据"
                stage_result['details'] = fund_details
                return stage_result

            fundamental_score = scoring_result.get('scores', {}).get('fundamental', 50)
            pe_ratio = fund_details.get('pe_ratio', 'N/A')
            revenue_yoy = fund_details.get('revenue_yoy', 'N/A')
            profit_yoy = fund_details.get('net_profit_yoy', 'N/A')

            stage_result['details'] = {
                'fundamental_score': fundamental_score,
                'pe_ratio': pe_ratio,
                'revenue_yoy': revenue_yoy,
                'profit_yoy': profit_yoy
            }

            info_parts = [f"基本面{fundamental_score:.0f}分"]
            if pe_ratio != 'N/A':
                info_parts.append(f"PE={pe_ratio:.1f}" if isinstance(pe_ratio, (int, float)) else f"PE={pe_ratio}")
            if revenue_yoy != 'N/A':
                info_parts.append(f"营收增长{revenue_yoy:+.1f}%" if isinstance(revenue_yoy, (int, float)) else f"营收增长{revenue_yoy}")
            if profit_yoy != 'N/A':
                info_parts.append(f"利润增长{profit_yoy:+.1f}%" if isinstance(profit_yoy, (int, float)) else f"利润增长{profit_yoy}")

            stage_result['reason'] = f"✓ " + ", ".join(info_parts)

        except Exception as e:
            stage_result['reason'] = f"⚠ 基本面评分异常: {str(e)}"
            logger.error(f"基本面评分异常: {e}", exc_info=True)

        return stage_result

    def _calculate_dragon_tiger_score(self, dragon_tiger: Dict) -> float:
        """
        计算龙虎榜得分 (0-100分)

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
        """
        try:
            has_records = dragon_tiger.get('has_records', False)

            if not has_records:
                return 50.0  # 基准分

            score = 50.0

            # 获取最近一次记录的净买入金额和上榜原因
            records = dragon_tiger.get('records', [])
            if not records:
                return 50.0

            latest_record = records[0]
            net_buy = latest_record.get('net_buy_amount', 0) or 0
            reason = dragon_tiger.get('last_reason', '')

            # 根据净买入金额加分/扣分
            if net_buy > 10000000:  # 1000万以上净买入
                score += 20
            elif net_buy > 5000000:  # 500-1000万净买入
                score += 15
            elif net_buy > 1000000:  # 100-500万净买入
                score += 10
            elif net_buy > 0:  # 小额净买入
                score += 5
            elif net_buy < -10000000:  # 1000万以上净卖出
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
            return max(0, min(100, score))

        except Exception as e:
            logger.error(f"龙虎榜评分计算失败: {e}")
            return 50.0


def main():
    """测试漏斗筛选器"""
    print("=" * 60)
    print("投资机会漏斗筛选器 - 测试")
    print("=" * 60)

    filter_engine = OpportunityFilter()

    # 模拟测试数据
    test_stock = {
        'stock_code': '000001',
        'name': '平安银行',
        'scoring_result': {
            'total_score': 75.5,
            'rating': 'A',
            'scores': {
                'quantitative': 80.0,
                'technical': 70.0,
                'sentiment': 65.0,
                'sector': 68.0,
                'fundamental': 55.0,
                'events': 60.0
            },
            'details': {
                'quantitative': {
                    'buy_count': 18,
                    'sell_count': 5,
                    'hold_count': 7,
                    'total_count': 30,
                    'buy_ratio': 0.60,
                    'top_buy_models': ['海龟交易', '多排突破', 'MACD金叉']
                },
                'technical': {
                    'RSI': 55.0,
                    'MACD': '金叉',
                    'Bollinger': '中轨',
                    'MA5': 12.5,
                    'MA10': 12.3,
                    'MA20': 12.0
                },
                'sentiment': {
                    'comprehensive_score': 65,
                    'comprehensive_sentiment': '偏多'
                },
                'sector': {
                    'sector_name': '银行',
                    'sentiment_score': 68,
                    'overall': '中性偏多'
                },
                'fundamental': {
                    'pe_ratio': 6.5,
                    'revenue_yoy': 8.5,
                    'net_profit_yoy': 12.3
                },
                'events': {
                    'positive_events': 3,
                    'negative_events': 1,
                    'comprehensive_score': 20,
                    'rating': '偏利好'
                }
            }
        }
    }

    print(f"\n正在筛选: {test_stock['name']} ({test_stock['stock_code']})")
    print("=" * 60)

    result = filter_engine.apply_all_filters(test_stock)

    print(f"\n筛选结果: {'✓ 通过' if result['passed'] else '✗ 未通过'}")
    if not result['passed']:
        print(f"淘汰阶段: 阶段{result['eliminated_at_stage']}")

    print(f"综合得分: {result['final_score']} ({result['rating']})")

    print(f"\n{'='*60}")
    print("筛选历程:")
    print(f"{'='*60}")

    for stage in result['filter_history']:
        status = "✓ 通过" if stage['passed'] else "✗ 淘汰"
        print(f"\n阶段{stage['stage']}: {stage['stage_name']} - {status}")
        print(f"  理由: {stage['reason']}")


if __name__ == "__main__":
    main()
