#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试一体化深度发现系统
"""

import os
import sys
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.integrated_discovery_engine import IntegratedDiscoveryEngine


def test_integrated_system():
    """测试一体化系统"""
    print("🚀 测试Kronos v3.0 一体化深度发现系统")
    print("=" * 60)
    
    try:
        # 创建发现引擎
        engine = IntegratedDiscoveryEngine(output_dir="test_integrated_results")
        
        print("开始测试 - 使用快速模式以节省时间...")
        
        # 运行快速测试
        results = engine.run_integrated_discovery(
            discovery_mode=1,  # 关键词模式
            drill_depth='intermediate',  # 中等深度，节省时间
            quality_threshold=0.6  # 降低阈值以便测试
        )
        
        if results:
            print(f"\n✅ 测试完成！")
            print(f"发现机会数量: {results.get('total_discoveries', 0)}")
            print(f"高等级机会: {results.get('high_grade_count', 0)}")
            print(f"分析耗时: {results.get('analysis_duration', 0):.1f}秒")
            
            # 显示前3个发现
            discoveries = results.get('discoveries', [])
            if discoveries:
                print(f"\n🏆 TOP 3 发现:")
                for idx, discovery in enumerate(discoveries[:3], 1):
                    stock_code = discovery.get('stock_code', '')
                    final_score = discovery.get('final_score', 0)
                    grade = discovery.get('investment_grade', 'C级')
                    print(f"  {idx}. {stock_code} - {grade} ({final_score:.1f}分)")
            
            return True
        else:
            print("❌ 测试失败 - 未返回结果")
            return False
            
    except Exception as e:
        print(f"❌ 测试错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deep_drill_analyzer():
    """测试深度钻取分析器"""
    print("\n🔬 测试深度钻取分析器")
    print("-" * 40)
    
    try:
        from analysis.deep_drill_analyzer import DeepDrillAnalyzer
        
        analyzer = DeepDrillAnalyzer()
        
        test_info = {
            'title': '002930 重组消息深度分析',
            'content': '公司发布重组预案，涉及资产收购',
            'confidence_score': 75
        }
        
        result = analyzer.perform_deep_drill(
            stock_code='002930',
            initial_info=test_info,
            drill_depth=2,  # 中等深度
            verification_rounds=2  # 2轮验证
        )
        
        if result:
            quality = result.get('quality_assessment', {}).get('overall_quality', {})
            print(f"✅ 深度钻取测试完成")
            print(f"质量评分: {quality.get('score', 0):.1f}")
            print(f"质量等级: {quality.get('grade', 'N/A')}")
            print(f"分析耗时: {result.get('analysis_duration', 0):.1f}秒")
            return True
        else:
            print("❌ 深度钻取测试失败")
            return False
            
    except Exception as e:
        print(f"❌ 深度钻取测试错误: {e}")
        return False


def main():
    """主测试函数"""
    print("🧪 Kronos v3.0 系统功能测试")
    print("时间:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print("=" * 60)
    
    results = []
    
    # 测试1: 一体化发现系统
    print("\n测试1: 一体化发现系统")
    results.append(("一体化发现系统", test_integrated_system()))
    
    # 测试2: 深度钻取分析器
    print("\n测试2: 深度钻取分析器")
    results.append(("深度钻取分析器", test_deep_drill_analyzer()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
    
    print(f"\n总体结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！v3.0系统运行正常")
    elif passed >= total * 0.5:
        print("⚠️  大部分测试通过，系统基本正常")
    else:
        print("❌ 多个测试失败，需要检查系统配置")
    
    print("\n测试完成时间:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


if __name__ == '__main__':
    main()