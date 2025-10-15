#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成含阶段3资金流与龙虎榜标签的测试报告（使用虚拟数据）
用于快速验证UI渲染，不依赖外部数据源。
"""

import os
import sys
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from scripts.opportunity_report_generator import OpportunityReportGenerator


def build_dummy_analysis_results():
    """构造最小可用的虚拟分析结果用于报告生成"""
    now_date = datetime.now().strftime("%Y-%m-%d")

    stock1 = {
        'passed': True,
        'eliminated_at_stage': 0,
        'name': '示例股份A',
        'stock_code': '000001',
        'final_score': 82.4,
        'rating': 'A-',
        'scoring_result': {
            'scores': {
                'quantitative': 80.1,
                'technical': 78.5,
                'sentiment': 85.0,
                'sector': 72.8,
                'fundamental': 68.2,
                'events': 70.0
            },
            'weights_used': {
                'quantitative': 0.25,
                'technical': 0.20,
                'sentiment': 0.20,
                'sector': 0.15,
                'fundamental': 0.10,
                'events': 0.10
            },
            'details': {
                'quantitative': {'buy_count': 12, 'sell_count': 3, 'total_count': 20, 'buy_ratio': 0.60},
                'technical': {'RSI': 57.4, 'MACD': '金叉', 'Bollinger': '中轨上方'},
                'sentiment': {
                    'comprehensive_score': 83.3,
                    'comprehensive_sentiment': '偏乐观',
                    'guba_sentiment': {'bullish_ratio': 64.5, 'bearish_ratio': 18.2, 'neutral_ratio': 17.3},
                    'overall_market_sentiment': {'turnover_emotion': '活跃'},
                    'capital_flow': {'trend': '净流入', 'strength': '强', 'main_inflow_rate': 3.25},
                    'dragon_tiger': {'has_records': True, 'last_date': now_date, 'last_signal': '正面', 'last_reason': '机构净买入'},
                    'bonus_reasons': ['主力资金强力净流入 +3', '近期龙虎榜净买入 +3']
                },
                'sector': {'sector_name': '银行', 'change_pct': 1.23, 'turnover_rate': 3.45, 'overall': '偏强'},
                'fundamental': {'pe_ratio': 8.6, 'revenue_yoy': 12.1, 'net_profit_yoy': 15.3},
                'events': {'rating': '利好偏多', 'positive_events': 3, 'negative_events': 1}
            }
        },
        'filter_history': [
            {'stage_name': '阶段1: 量化模型筛选', 'passed': True, 'reason': '模型信号综合评分较高', 'details': {'top_buy_models': ['multi_factor_alpha','cta_trend_strategy']}},
            {'stage_name': '阶段2: 技术面筛选', 'passed': True, 'reason': '趋势向上、形态良好'},
            {'stage_name': '阶段3: 情绪面筛选', 'passed': True, 'reason': '股吧偏多，板块偏强，资金净流入，近期龙虎榜正面'},
            {'stage_name': '阶段4: 基本面筛选', 'passed': True, 'reason': '估值合理；营收和利润同比增长'},
            {'stage_name': '阶段5: 事件面筛选', 'passed': True, 'reason': '利好消息偏多'}
        ]
    }

    stock2 = {
        'passed': True,
        'eliminated_at_stage': 0,
        'name': '示例股份B',
        'stock_code': '600000',
        'final_score': 75.9,
        'rating': 'B+',
        'scoring_result': {
            'scores': {
                'quantitative': 70.0,
                'technical': 74.2,
                'sentiment': 62.0,
                'sector': 69.1,
                'fundamental': 66.0,
                'events': 68.0
            },
            'weights_used': {
                'quantitative': 0.25,
                'technical': 0.20,
                'sentiment': 0.20,
                'sector': 0.15,
                'fundamental': 0.10,
                'events': 0.10
            },
            'details': {
                'quantitative': {'buy_count': 8, 'sell_count': 6, 'total_count': 20, 'buy_ratio': 0.40},
                'technical': {'RSI': 49.8, 'MACD': '死叉', 'Bollinger': '下轨附近'},
                'sentiment': {
                    'comprehensive_score': 60.2,
                    'comprehensive_sentiment': '中性偏谨慎',
                    'guba_sentiment': {'bullish_ratio': 45.0, 'bearish_ratio': 30.0, 'neutral_ratio': 25.0},
                    'overall_market_sentiment': {'turnover_emotion': '正常'},
                    'capital_flow': {'trend': '净流出', 'strength': '强', 'main_inflow_rate': -2.15},
                    'dragon_tiger': {'has_records': True, 'last_date': now_date, 'last_signal': '负面', 'last_reason': '主力净卖出'},
                    'bonus_reasons': ['主力资金强力净流出 -3', '近期龙虎榜净卖出 -3']
                },
                'sector': {'sector_name': '证券', 'change_pct': -0.56, 'turnover_rate': 4.12, 'overall': '一般'},
                'fundamental': {'pe_ratio': 12.4, 'revenue_yoy': -3.2, 'net_profit_yoy': 1.5},
                'events': {'rating': '中性', 'positive_events': 1, 'negative_events': 2}
            }
        },
        'filter_history': [
            {'stage_name': '阶段1: 量化模型筛选', 'passed': True, 'reason': '信号数量适中', 'details': {'top_buy_models': ['statistical_quantitative']}},
            {'stage_name': '阶段2: 技术面筛选', 'passed': True, 'reason': '短期压力，等待趋势修复'},
            {'stage_name': '阶段3: 情绪面筛选', 'passed': True, 'reason': '股吧分歧，板块一般，资金净流出，近期龙虎榜负面'},
            {'stage_name': '阶段4: 基本面筛选', 'passed': True, 'reason': '估值略高；营收下滑'},
            {'stage_name': '阶段5: 事件面筛选', 'passed': True, 'reason': '消息面暂无明显利好'}
        ]
    }

    return [stock1, stock2]


def main():
    results = build_dummy_analysis_results()
    generator = OpportunityReportGenerator(output_dir=os.environ.get('KRONOS_RESULTS_DIR', 'results'))
    path = generator.generate_report(results, report_title='投资机会挖掘报告（UI预览测试）')
    print(path)


if __name__ == '__main__':
    main()