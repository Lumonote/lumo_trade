#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会漏斗筛选器
5阶段逐步筛选，每个阶段记录详细的筛选理由
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
    """投资机会漏斗筛选器 - 5阶段筛选系统"""

    # 筛选阈值配置
    STAGE_THRESHOLDS = {
        'stage1_quant': {
            'min_buy_signals': 2,      # 最少买入信号数（放宽）
            'min_buy_ratio': 0.20      # 最低买入信号比例 20%
        },
        'stage2_technical': {
            'max_rsi': 75,             # RSI上限（放宽）
            'min_rsi': 20,             # RSI下限（超卖区）
            'require_macd_or_bb': True,# 要求MACD金叉或布林带突破
            'max_kdj_j': 90,           # KDJ的J值上限
            'min_kdj_j': 10,           # KDJ的J值下限
            'ma_trend_score': 2,       # 均线趋势评分最低要求(满分5)
            'volume_surge_threshold': 1.5,  # 成交量放大倍数
            'allow_volume_shrink': True,    # 是否允许缩量
        },
        'stage3_sentiment': {
            'min_investor_sentiment': 50,  # 股民情绪最低分（放宽）
            'min_sector_sentiment': 45     # 板块情绪最低分（放宽）
        },
        'stage4_fundamental': {
            'max_pe': 60,              # PE上限（放宽）
            'require_growth': True     # 要求营收或利润正增长
        },
        'stage5_events': {
            'positive_over_negative': True  # 利好>利空
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

    def __init__(self):
        """初始化筛选器"""
        pass

    def apply_all_filters(self, stock_data: Dict) -> Dict:
        """
        应用所有筛选阶段

        Args:
            stock_data: 股票综合数据，包含:
                - stock_code: 股票代码
                - name: 股票名称
                - scoring_result: OpportunityScorer的评分结果

        Returns:
            {
                'stock_code': '000001',
                'name': '平安银行',
                'passed': True/False,  # 是否通过所有筛选
                'eliminated_at_stage': 3,  # 在第几阶段被淘汰（如果passed=False）
                'filter_history': [
                    {
                        'stage': 1,
                        'stage_name': '量化模型初筛',
                        'passed': True,
                        'reason': '✓ 买入信号18个 (占比60%) ≥ 阈值3个',
                        'details': {
                            'buy_signals': 18,
                            'total_models': 30,
                            'buy_ratio': 0.60,
                            'threshold': 3,
                            'key_models': ['海龟交易', '多排突破']
                        }
                    },
                    # ... more stages
                ],
                'final_score': 78.5,  # 综合得分
                'rating': 'A'  # 评级
            }
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

        # 阶段1: 量化模型初筛
        stage1_result = self.stage1_quantitative_models(scoring_result)
        result['filter_history'].append(stage1_result)

        if not stage1_result['passed']:
            result['eliminated_at_stage'] = 1
            logger.info(f"✗ {result['stock_code']} 在阶段1被淘汰: {stage1_result['reason']}")
            return result

        # 阶段2: 技术面筛选
        stage2_result = self.stage2_technical_analysis(scoring_result)
        result['filter_history'].append(stage2_result)

        if not stage2_result['passed']:
            result['eliminated_at_stage'] = 2
            logger.info(f"✗ {result['stock_code']} 在阶段2被淘汰: {stage2_result['reason']}")
            return result

        # 阶段3: 情绪面评分（仅评分，不筛选）
        stage3_result = self.stage3_sentiment_score(scoring_result)
        result['filter_history'].append(stage3_result)

        # 阶段4: 基本面评分（仅评分，不筛选）
        stage4_result = self.stage4_fundamental_score(scoring_result)
        result['filter_history'].append(stage4_result)

        # 阶段5:消息面评分（仅评分，不筛选）
        stage5_result = self.stage5_events_score(scoring_result)
        result['filter_history'].append(stage5_result)

        # 阶段6: 龙虎榜评分（仅评分，不筛选）
        stage6_result = self.stage6_dragon_tiger_score(scoring_result)
        result['filter_history'].append(stage6_result)

        # 全部通过
        result['passed'] = True
        logger.info(f"✓ {result['stock_code']} 通过所有筛选！综合得分: {result['final_score']}")

        return result

    def stage1_quantitative_models(self, scoring_result: Dict) -> Dict:
        """
        阶段1: 量化模型初筛

        筛选标准:
        - 买入信号数量 ≥ 3个 OR
        - 买入信号比例 ≥ 30%

        Args:
            scoring_result: OpportunityScorer的评分结果

        Returns:
            {
                'stage': 1,
                'stage_name': '量化模型初筛',
                'passed': True/False,
                'reason': '✓ 买入信号18个 (占比60%) ≥ 阈值3个',
                'details': {...}
            }
        """
        stage_result = {
            'stage': 1,
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
            total_count = quant_details.get('total_count', 30)
            buy_ratio = quant_details.get('buy_ratio', 0)
            top_buy_models = quant_details.get('top_buy_models', [])

            # 应用筛选标准
            threshold_signals = self.STAGE_THRESHOLDS['stage1_quant']['min_buy_signals']
            threshold_ratio = self.STAGE_THRESHOLDS['stage1_quant']['min_buy_ratio']

            passed = (buy_count >= threshold_signals) or (buy_ratio >= threshold_ratio)

            stage_result['passed'] = passed
            stage_result['details'] = {
                'buy_count': buy_count,
                'total_count': total_count,
                'buy_ratio': buy_ratio,
                'threshold_signals': threshold_signals,
                'threshold_ratio': threshold_ratio,
                'top_buy_models': top_buy_models[:5]
            }

            if passed:
                display_models = [self.MODEL_DISPLAY_MAP.get(m, m) for m in top_buy_models[:3]]
                stage_result['reason'] = (
                    f"✓ 买入信号{buy_count}个 (占比{buy_ratio*100:.0f}%) "
                    f"≥ 阈值{threshold_signals}个，关键模型: {', '.join(display_models)}"
                )
            else:
                stage_result['reason'] = (
                    f"✗ 买入信号{buy_count}个 (占比{buy_ratio*100:.0f}%) "
                    f"< 阈值{threshold_signals}个且比例 < {threshold_ratio*100:.0f}%"
                )

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段1筛选异常: {str(e)}"
            logger.error(f"阶段1筛选异常: {e}", exc_info=True)

        return stage_result

    def stage2_technical_analysis(self, scoring_result: Dict) -> Dict:
        """
        阶段2: 技术面筛选（增强版）

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
          - 均线多头排列(趋势评分=5)
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
            if distance_from_high < 5:
                 stage_result['reason'] = f"✗ 接近历史高点(距高点{distance_from_high}%)，风险较高"
                 stage_result['passed'] = False
                 stage_result['details'] = {'distance_from_high': distance_from_high}
                 return stage_result

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
