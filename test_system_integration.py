#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统集成测试脚本
===============

测试Kronos系统的核心功能模块：
1. 并购重组全方位关联性分析
2. 超前瞻性深度事件发现
3. 关键词驱动论坛挖掘
"""

import os
import sys
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_merger_analyzer():
    """测试并购重组分析器"""
    print("=" * 60)
    print("🔍 测试并购重组全方位关联性分析")
    print("=" * 60)
    
    try:
        from analysis.merger_association_analyzer import MergerAssociationAnalyzer
        
        analyzer = MergerAssociationAnalyzer()
        
        # 快速测试
        print("正在分析002932与300062的并购关联性...")
        result = analyzer.analyze_merger_association(
            target_code='002932',
            acquirer_hints=['300062'],
            analysis_depth='basic'  # 使用基础模式提高速度
        )
        
        if result and result.get('top_acquirer'):
            top_code, top_result = result['top_acquirer']
            print(f"✓ 测试成功！")
            print(f"  - 最佳匹配: {top_code}")
            print(f"  - 综合得分: {top_result.get('overall_score', 0):.1f}")
            print(f"  - 成功概率: {top_result.get('success_probability', {}).get('probability_percentage', '未知')}")
            return True
        else:
            print("✗ 测试失败：未能生成分析结果")
            return False
            
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False

def test_keyword_miner():
    """测试关键词论坛挖掘"""
    print("\n" + "=" * 60)
    print("🔍 测试关键词驱动论坛挖掘")
    print("=" * 60)
    
    try:
        from analysis.keyword_forum_miner import KeywordForumMiner
        
        miner = KeywordForumMiner()
        
        # 测试单个关键词搜索
        print("正在测试关键词搜索功能...")
        results = miner.mine_by_keywords(keyword_limit=2, post_limit_per_keyword=3)
        
        if results and len(results) > 0:
            print(f"✓ 测试成功！发现 {len(results)} 个投资机会")
            
            # 显示前3个结果
            for idx, result in enumerate(results[:3], 1):
                stock_code = result.get('stock_code', '未知')
                confidence = result.get('confidence_score', 0)
                print(f"  {idx}. {stock_code} - 置信度: {confidence}")
            
            return True
        else:
            print("✗ 测试失败：未发现有效结果")
            return False
            
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False

def test_deep_event_miner():
    """测试深度事件挖掘（简化版）"""
    print("\n" + "=" * 60)
    print("🔍 测试深度事件挖掘")
    print("=" * 60)
    
    try:
        from analysis.deep_event_miner import DeepEventMiner
        
        miner = DeepEventMiner()
        
        # 简化测试：仅测试信号收集
        print("正在测试信号收集功能...")
        signals = miner._collect_multidimensional_signals(time_horizon=1)
        
        total_signals = sum(len(signal_list) for signal_list in signals.values())
        
        if total_signals > 0:
            print(f"✓ 测试成功！收集到 {total_signals} 个多维度信号")
            
            for signal_type, signal_list in signals.items():
                if signal_list:
                    print(f"  - {signal_type}: {len(signal_list)} 个信号")
            
            return True
        else:
            print("✗ 测试失败：未收集到有效信号")
            return False
            
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False

def test_report_generator():
    """测试报告生成器"""
    print("\n" + "=" * 60)
    print("🔍 测试报告生成器")
    print("=" * 60)
    
    try:
        from analysis.major_positive_news_report_generator import MajorPositiveNewsReportGenerator
        
        generator = MajorPositiveNewsReportGenerator("test_output")
        
        # 模拟测试数据
        test_data = [{
            'stock_code': '000001',
            'stock_name': '测试股票',
            'confidence_score': 85,
            'confidence_rating': 'A级',
            'news_type_name': '重大重组',
            'news_title': '测试重组消息',
            'news_content': '测试内容',
            'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'news_source': '系统测试',
            'news_url': 'test_url',
            'investment_advice': '建议关注',
            'risk_warning': '投资有风险',
            'confidence': {
                'scores': {
                    'source_reliability': 85,
                    'timeliness': 90,
                    'content_quality': 80,
                    'market_validation': 75,
                    'historical_accuracy': 70,
                    'technical_alignment': 85
                }
            }
        }]
        
        # 生成CSV报告
        csv_path = generator.generate_csv_report(test_data)
        
        if os.path.exists(csv_path):
            print(f"✓ 测试成功！CSV报告已生成: {csv_path}")
            return True
        else:
            print("✗ 测试失败：CSV报告生成失败")
            return False
            
    except Exception as e:
        print(f"✗ 测试失败：{e}")
        return False

def main():
    """主测试函数"""
    print("🚀 Kronos系统集成测试开始")
    print("时间:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    results = []
    
    # 运行各项测试
    results.append(("并购重组分析", test_merger_analyzer()))
    results.append(("关键词挖掘", test_keyword_miner()))
    results.append(("深度事件挖掘", test_deep_event_miner()))
    results.append(("报告生成", test_report_generator()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总体结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！系统功能正常")
    elif passed >= total * 0.5:
        print("⚠️  大部分测试通过，系统基本正常")
    else:
        print("❌ 多个测试失败，需要检查系统配置")
    
    print("\n测试完成时间:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

if __name__ == '__main__':
    main()