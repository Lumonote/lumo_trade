#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资机会挖掘系统使用示例 - v2.2
展示更新后的功能
"""

import sys
import os

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from analysis.opportunity_scorer import OpportunityScorer
from analysis.opportunity_filter import OpportunityFilter


def example_usage():
    """使用示例"""
    print("=" * 80)
    print("投资机会挖掘系统 v2.2 - 使用示例")
    print("=" * 80)

    # 股票代码示例
    stock_code = "000001"

    print(f"\n分析股票: {stock_code}")
    print("-" * 80)

    # 步骤1: 计算综合评分
    print("\n步骤1: 计算综合评分...")
    scorer = OpportunityScorer()
    scoring_result = scorer.calculate_comprehensive_score(stock_code)

    print(f"\n综合评分结果:")
    print(f"  总分: {scoring_result['total_score']:.2f}")
    print(f"  评级: {scoring_result['rating']}")
    print(f"  建议: {scoring_result['recommendation']}")

    print(f"\n各维度得分:")
    weights = scoring_result.get('weights_used', scorer.DIMENSION_WEIGHTS)
    for dim in ['quantitative', 'technical', 'sentiment', 'sector', 'fundamental', 'events', 'dragon_tiger']:
        score = scoring_result['scores'].get(dim, 0)
        weight = weights.get(dim, 0)
        print(f"  {dim:15s}: {score:5.1f}分 (权重 {weight*100:.0f}%)")

    # 步骤2: 应用筛选器
    print("\n" + "-" * 80)
    print("步骤2: 应用筛选器...")

    filter_engine = OpportunityFilter()
    stock_data = {
        'stock_code': stock_code,
        'name': scoring_result.get('stock_code', stock_code),
        'scoring_result': scoring_result
    }

    filter_result = filter_engine.apply_all_filters(stock_data)

    print(f"\n筛选结果:")
    print(f"  通过: {'✓ 是' if filter_result['passed'] else '✗ 否'}")
    if not filter_result['passed']:
        print(f"  淘汰于: 阶段{filter_result['eliminated_at_stage']}")

    print(f"\n筛选历程:")
    for stage in filter_result['filter_history']:
        status = "✓" if stage['passed'] else "✗"
        print(f"  {status} 阶段{stage['stage']}: {stage['stage_name']}")
        print(f"     {stage['reason'][:70]}...")

    # 重点展示龙虎榜信息
    print("\n" + "-" * 80)
    print("龙虎榜信息:")
    dragon_tiger_details = scoring_result['details'].get('dragon_tiger', {})
    if 'error' in dragon_tiger_details:
        print(f"  {dragon_tiger_details['error']}")
    else:
        on_list = dragon_tiger_details.get('on_list', False)
        if on_list:
            print(f"  ✓ 已上榜")
            print(f"  上榜原因: {dragon_tiger_details.get('reason_type', '未知')}")
            net_buy = dragon_tiger_details.get('net_buy_amount', 0)
            print(f"  净买入金额: {net_buy/10000:.2f}万元")
            print(f"  龙虎榜得分: {dragon_tiger_details.get('score', 50):.1f}")
        else:
            print(f"  未上榜 (得分: {dragon_tiger_details.get('score', 50):.1f})")

    print("\n" + "=" * 80)
    print("分析完成")
    print("=" * 80)


def show_system_info():
    """显示系统信息"""
    print("\n" + "=" * 80)
    print("系统信息")
    print("=" * 80)

    scorer = OpportunityScorer()

    print("\n权重配置:")
    for dim, weight in scorer.DIMENSION_WEIGHTS.items():
        print(f"  {dim:15s}: {weight*100:5.1f}%")

    total_weight = sum(scorer.DIMENSION_WEIGHTS.values())
    print(f"  {'总计':15s}: {total_weight*100:5.1f}%")

    print("\n动态权重模式:")
    for mode_name, weights in scorer.DYNAMIC_WEIGHT_PROFILES.items():
        print(f"  {mode_name}:")
        for dim, weight in weights.items():
            print(f"    {dim:15s}: {weight*100:5.1f}%")

    print("\n筛选阶段:")
    stages = [
        "阶段1: 量化模型初筛 (筛选)",
        "阶段2: 技术面筛选 (筛选)",
        "阶段3: 情绪面评分 (仅评分)",
        "阶段4: 基本面评分 (仅评分)",
        "阶段5: 消息面评分 (仅评分)",
        "阶段6: 龙虎榜评分 (仅评分)"
    ]
    for i, stage in enumerate(stages, 1):
        print(f"  {stage}")


if __name__ == "__main__":
    show_system_info()
    print("\n" + "=" * 80)
    input("按Enter键开始分析示例股票...")
    example_usage()
