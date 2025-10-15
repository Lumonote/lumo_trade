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
            'require_macd_or_bb': True # 要求MACD金叉或布林带突破
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

        # 阶段3: 情绪面筛选
        stage3_result = self.stage3_sentiment_filter(scoring_result)
        result['filter_history'].append(stage3_result)

        if not stage3_result['passed']:
            result['eliminated_at_stage'] = 3
            logger.info(f"✗ {result['stock_code']} 在阶段3被淘汰: {stage3_result['reason']}")
            return result

        # 阶段4: 基本面筛选
        stage4_result = self.stage4_fundamental_filter(scoring_result)
        result['filter_history'].append(stage4_result)

        if not stage4_result['passed']:
            result['eliminated_at_stage'] = 4
            logger.info(f"✗ {result['stock_code']} 在阶段4被淘汰: {stage4_result['reason']}")
            return result

        # 阶段5: 事件面筛选
        stage5_result = self.stage5_events_filter(scoring_result)
        result['filter_history'].append(stage5_result)

        if not stage5_result['passed']:
            result['eliminated_at_stage'] = 5
            logger.info(f"✗ {result['stock_code']} 在阶段5被淘汰: {stage5_result['reason']}")
            return result

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
        阶段2: 技术面筛选

        筛选标准:
        - RSI < 70 (不在超买区) AND
        - (MACD金叉 OR 布林带突破/接近下轨)

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

            rsi = tech_details.get('RSI', 50)
            macd = tech_details.get('MACD', '')
            bollinger = tech_details.get('Bollinger', '')

            # 应用筛选标准
            max_rsi = self.STAGE_THRESHOLDS['stage2_technical']['max_rsi']

            rsi_ok = rsi < max_rsi
            macd_ok = '金叉' in str(macd)
            bb_ok = '下轨' in str(bollinger) or '突破' in str(bollinger)

            passed = rsi_ok and (macd_ok or bb_ok)

            stage_result['passed'] = passed
            stage_result['details'] = {
                'RSI': rsi,
                'MACD': macd,
                'Bollinger': bollinger,
                'max_rsi': max_rsi,
                'rsi_ok': rsi_ok,
                'macd_ok': macd_ok,
                'bb_ok': bb_ok
            }

            # 构建理由
            reasons = []
            if not rsi_ok:
                reasons.append(f"RSI={rsi:.1f} ≥ {max_rsi} (超买)")
            else:
                reasons.append(f"RSI={rsi:.1f} < {max_rsi}")

            if macd_ok:
                reasons.append("MACD金叉")
            elif bb_ok:
                reasons.append(f"布林带{bollinger}")
            else:
                reasons.append("无MACD金叉或布林带信号")

            if passed:
                stage_result['reason'] = f"✓ " + ", ".join(reasons)
            else:
                stage_result['reason'] = f"✗ " + ", ".join(reasons)

        except Exception as e:
            stage_result['reason'] = f"✗ 阶段2筛选异常: {str(e)}"
            logger.error(f"阶段2筛选异常: {e}", exc_info=True)

        return stage_result

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
        阶段5: 事件面筛选

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
