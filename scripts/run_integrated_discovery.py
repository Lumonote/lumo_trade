#\!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一体化深度发现系统启动脚本
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from analysis.integrated_discovery_engine import IntegratedDiscoveryEngine


def main():
    print("\n" + "=" * 80)
    print("🚀 Lumo 一体化深度发现引擎")
    print("=" * 80)
    
    try:
        print("\n请选择发现模式:")
        print("  1. 关键词深度模式 - 基于权重关键词体系的深度挖掘")
        print("  2. 论坛深度模式 - 基于多平台论坛的深度舆情分析")
        print("  3. 新闻深度模式 - 基于新闻媒体的深度事件分析")
        print("  4. 多平台全网挖掘模式 (推荐) - 全方位挖掘东方财富、雪球、财联社、巨潮资讯、韭研公社、新浪财经等主流平台")
        
        mode_input = input("\n请选择模式 (1-4, 默认4): ").strip()
        discovery_mode = int(mode_input) if mode_input and mode_input.isdigit() else 4
        if discovery_mode not in [1, 2, 3, 4]:
            discovery_mode = 4
        
        print("\n钻取深度选项:")
        print("  1. 表层分析 (快速, 1-2分钟)")
        print("  2. 中等深度 (平衡, 3-5分钟)")
        print("  3. 深度分析 (推荐, 5-8分钟)")
        print("  4. 全面深度 (最详细, 10-15分钟)")
        
        depth_input = input("\n请选择钻取深度 (1-4, 默认3): ").strip()
        depth_mapping = {
            '1': 'surface',
            '2': 'intermediate',
            '3': 'deep',
            '4': 'comprehensive'
        }
        drill_depth = depth_mapping.get(depth_input, 'deep')
        
        quality_input = input("\n请设置质量阈值 (0.5-0.9, 默认0.7): ").strip()
        try:
            quality_threshold = float(quality_input) if quality_input else 0.7
            quality_threshold = max(0.5, min(0.9, quality_threshold))
        except:
            quality_threshold = 0.7
        
        print("\n" + "=" * 80)
        mode_names = ['', '关键词深度模式', '论坛深度模式', '新闻深度模式', '多平台全网挖掘模式']
        print(f"📊 发现模式: {mode_names[discovery_mode]}")
        print(f"🔍 钻取深度: {drill_depth}")
        print(f"⚡ 质量阈值: {quality_threshold}")
        print("=" * 80)
        
        confirm = input("\n确认开始分析? (Y/n): ").strip().lower()
        if confirm == 'n':
            print("已取消分析")
            return
        
    except KeyboardInterrupt:
        print("\n用户取消操作")
        return
    
    output_dir = os.path.join(project_root, "integrated_results")
    engine = IntegratedDiscoveryEngine(output_dir=output_dir)
    
    try:
        results = engine.run_integrated_discovery(
            discovery_mode=discovery_mode,
            drill_depth=drill_depth,
            quality_threshold=quality_threshold
        )
        
        if results:
            total = results.get('total_discoveries', 0)
            high_grade = results.get('high_grade_count', 0)
            print(f"\n✅ 发现完成！共发现 {total} 个投资机会，其中高等级 {high_grade} 个")
            print(f"📁 报告已保存至: {output_dir}")
        else:
            print("\n❌ 未发现符合条件的投资机会")
            
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断分析过程")
    except Exception as e:
        print(f"\n❌ 系统错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
