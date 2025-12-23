#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合评分阈值筛选器 - P1优化版本

核心改进：从硬筛（单一维度卡阈值）改为综合评分阈值筛选
支持：
1. 基于综合评分的等级筛选
2. 多维度权衡（不再是一票否决）
3. 自适应阈值调整
4. 快速调整界面
"""

import os
import sys
from typing import Dict, List, Optional, Tuple
import logging

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ComprehensiveScoreFilter:
    """
    综合评分阈值筛选器 v4.2
    
    核心改进（P1优化）：
    1. 放弃硬筛，改为综合评分阈值
    2. 支持快速调整筛选标准
    3. 多维度权衡决策
    4. 增强筛选灵活性
    """
    
    # 默认筛选阈值配置
    DEFAULT_THRESHOLDS = {
        # 基于等级的筛选
        'rating_filter': {
            'S': True,          # S级始终通过
            'A+': True,         # A+级始终通过
            'A': True,          # A级默认通过
            'B': False,         # B级默认不通过
            'C': False,         # C级始终不通过
        },
        
        # 基于综合评分的筛选
        'score_based': {
            'min_total_score': 62,          # 综合评分最低门槛（A级下限）
            'min_rating': 'A',              # 最低要求评级
        },
        
        # 基于维度的筛选（可选，如果启用则需要满足）
        'dimension_based': {
            'min_quantitative': 50,         # 量化模型最低分
            'min_position_timing': 45,      # 位置时机最低分
            'min_volume_health': 45,        # 量价健康最低分
        },
        
        # 风险排除规则（软化版，允许其他维度补偿）
        'soft_exclusion': {
            'max_distance_from_high': 3,    # 距离年内高点 >= 3%才通过
            'max_change_60d': 70,           # 60日涨幅 <= 70%
            'max_consecutive_up': 6,        # 连涨 <= 6天
        },
    }
    
    # 快速调整预设
    PRESETS = {
        # 保守策略：只要S和A+级别
        'conservative': {
            'min_total_score': 72,
            'rating_filter': {'S': True, 'A+': True, 'A': False, 'B': False, 'C': False},
            'soft_exclusion': {
                'max_distance_from_high': 5,
                'max_change_60d': 50,
                'max_consecutive_up': 4,
            },
        },
        
        # 均衡策略：S/A+/A都可以（默认）
        'balanced': {
            'min_total_score': 62,
            'rating_filter': {'S': True, 'A+': True, 'A': True, 'B': False, 'C': False},
            'soft_exclusion': {
                'max_distance_from_high': 3,
                'max_change_60d': 70,
                'max_consecutive_up': 6,
            },
        },
        
        # 激进策略：A级别也接受，容许更多风险
        'aggressive': {
            'min_total_score': 55,
            'rating_filter': {'S': True, 'A+': True, 'A': True, 'B': True, 'C': False},
            'soft_exclusion': {
                'max_distance_from_high': 2,
                'max_change_60d': 80,
                'max_consecutive_up': 7,
            },
        },
        
        # 底部启动策略：降低综合评分门槛，但强化位置要求
        'bottom_hunting': {
            'min_total_score': 50,
            'rating_filter': {'S': True, 'A+': True, 'A': True, 'B': True, 'C': False},
            'dimension_based': {
                'min_quantitative': 40,
                'min_position_timing': 35,
                'min_volume_health': 40,
            },
            'soft_exclusion': {
                'max_distance_from_high': 20,  # 要求距离高点至少20%（即在底部区域）
                'max_change_60d': 100,         # 允许60日大幅下跌
                'max_consecutive_up': 5,
            },
        },
    }
    
    def __init__(self, strategy: str = 'balanced', custom_thresholds: Optional[Dict] = None):
        """
        初始化筛选器
        
        Args:
            strategy: 预设策略名称 (conservative/balanced/aggressive/bottom_hunting)
                     或 'custom' 使用自定义阈值
            custom_thresholds: 自定义阈值配置 (strategy='custom'时使用)
        """
        if strategy in self.PRESETS:
            self.thresholds = self.PRESETS[strategy].copy()
            self.strategy = strategy
            logger.info(f"✓ 使用预设策略: {strategy}")
        elif strategy == 'custom' and custom_thresholds:
            self.thresholds = custom_thresholds
            self.strategy = 'custom'
            logger.info(f"✓ 使用自定义阈值")
        else:
            self.thresholds = self.DEFAULT_THRESHOLDS.copy()
            self.strategy = 'balanced'
            logger.info(f"✓ 使用默认均衡策略")
        
        # 验证阈值配置
        self._validate_thresholds()
    
    def _validate_thresholds(self):
        """验证阈值配置的有效性"""
        required_keys = ['min_total_score', 'rating_filter']
        for key in required_keys:
            if key not in self.thresholds:
                logger.warning(f"⚠️ 缺失关键阈值: {key}，使用默认值")
                self.thresholds[key] = self.DEFAULT_THRESHOLDS.get(key)
    
    def filter(self, scoring_result: Dict) -> Tuple[bool, str, Dict]:
        """
        综合筛选
        
        Args:
            scoring_result: 打分系统返回的结果字典
        
        Returns:
            (passed: bool, reason: str, details: dict)
        """
        try:
            total_score = scoring_result.get('total_score', 0)
            rating = scoring_result.get('rating', 'C')
            scores = scoring_result.get('scores', {})
            details = scoring_result.get('details', {})
            
            # Step 1: 检查等级过滤
            rating_filter = self.thresholds.get('rating_filter', {})
            if not rating_filter.get(rating, False):
                return False, f"等级{rating}不在通过列表中", {'filter_stage': 'rating'}
            
            # Step 2: 检查综合评分
            min_score = self.thresholds.get('min_total_score', 62)
            if total_score < min_score:
                return False, f"综合评分{total_score:.2f}低于最低门槛{min_score}", {'filter_stage': 'score', 'total_score': total_score}
            
            # Step 3: 检查维度要求（可选）
            dimension_based = self.thresholds.get('dimension_based')
            if dimension_based:
                for dim, min_val in dimension_based.items():
                    dim_key = dim.replace('min_', '')
                    dim_score = scores.get(dim_key, 0)
                    if dim_score < min_val:
                        return False, f"维度{dim_key}得分{dim_score:.2f}低于{min_val}", {
                            'filter_stage': 'dimension',
                            'dimension': dim_key,
                            'score': dim_score,
                            'threshold': min_val
                        }
            
            # Step 4: 检查软化风险规则
            soft_exclusion = self.thresholds.get('soft_exclusion', {})
            momentum_details = details.get('momentum', {})
            
            # 4.1 距离高点检查
            if 'max_distance_from_high' in soft_exclusion:
                distance = momentum_details.get('distance_from_high', 50)
                max_distance = soft_exclusion['max_distance_from_high']
                if distance < max_distance:
                    return False, f"距离年内高点仅{distance:.1f}%，低于要求{max_distance}%", {
                        'filter_stage': 'soft_exclusion',
                        'rule': 'distance_from_high',
                        'value': distance,
                        'threshold': max_distance
                    }
            
            # 4.2 60日涨幅检查
            if 'max_change_60d' in soft_exclusion:
                change_60d = momentum_details.get('change_60d', 0)
                max_change = soft_exclusion['max_change_60d']
                if change_60d > max_change:
                    return False, f"60日涨幅{change_60d:.1f}%超过要求{max_change}%", {
                        'filter_stage': 'soft_exclusion',
                        'rule': 'change_60d',
                        'value': change_60d,
                        'threshold': max_change
                    }
            
            # 4.3 连涨天数检查
            if 'max_consecutive_up' in soft_exclusion:
                consecutive = momentum_details.get('consecutive_up_days', 0)
                max_consecutive = soft_exclusion['max_consecutive_up']
                if consecutive > max_consecutive:
                    return False, f"连涨{consecutive}天超过要求{max_consecutive}天", {
                        'filter_stage': 'soft_exclusion',
                        'rule': 'consecutive_up',
                        'value': consecutive,
                        'threshold': max_consecutive
                    }
            
            # 所有检查通过
            return True, "✓ 通过综合评分筛选", {
                'filter_stage': 'passed',
                'total_score': total_score,
                'rating': rating,
                'strategy': self.strategy,
            }
            
        except Exception as e:
            logger.error(f"筛选过程出错: {e}")
            return False, f"筛选过程出错: {e}", {'error': str(e)}
    
    def batch_filter(self, scoring_results: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        批量筛选
        
        Args:
            scoring_results: 打分结果列表
        
        Returns:
            (passed_stocks, filtered_out_stocks)
        """
        passed = []
        filtered = []
        
        for result in scoring_results:
            is_passed, reason, filter_details = self.filter(result)
            if is_passed:
                result['filter_reason'] = reason
                result['filter_details'] = filter_details
                passed.append(result)
            else:
                result['filter_reason'] = reason
                result['filter_details'] = filter_details
                filtered.append(result)
        
        return passed, filtered
    
    def adjust_threshold(self, key: str, value):
        """
        快速调整阈值
        
        Args:
            key: 要调整的阈值路径 (支持嵌套，用'.'分隔)
            value: 新的阈值值
        """
        try:
            keys = key.split('.')
            current = self.thresholds
            
            # 导航到目标（除了最后一个key）
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            
            # 设置值
            current[keys[-1]] = value
            logger.info(f"✓ 阈值已调整: {key} = {value}")
            
        except Exception as e:
            logger.error(f"阈值调整失败: {e}")
    
    def get_current_config(self) -> Dict:
        """获取当前配置"""
        return {
            'strategy': self.strategy,
            'thresholds': self.thresholds,
        }
    
    def set_strategy(self, strategy: str) -> bool:
        """
        快速切换策略
        
        Args:
            strategy: 策略名称
        
        Returns:
            是否成功切换
        """
        if strategy not in self.PRESETS:
            logger.error(f"❌ 未知策略: {strategy}")
            return False
        
        self.thresholds = self.PRESETS[strategy].copy()
        self.strategy = strategy
        logger.info(f"✓ 已切换到策略: {strategy}")
        return True
    
    def get_available_strategies(self) -> List[str]:
        """获取所有可用策略"""
        return list(self.PRESETS.keys())
    
    def print_current_config(self):
        """打印当前配置"""
        print(f"\n📋 当前筛选策略: {self.strategy}")
        print("="*50)
        print("核心筛选标准:")
        print(f"  - 最低综合评分: {self.thresholds.get('min_total_score', 62)}")
        print(f"  - 通过的评级: {[k for k, v in self.thresholds.get('rating_filter', {}).items() if v]}")
        
        soft_exclusion = self.thresholds.get('soft_exclusion', {})
        if soft_exclusion:
            print("软化风险规则:")
            for rule, threshold in soft_exclusion.items():
                print(f"  - {rule}: {threshold}")


if __name__ == '__main__':
    # 测试代码
    print("\n" + "="*60)
    print("综合评分阈值筛选器 - 测试")
    print("="*60)
    
    # 创建虚拟打分结果
    mock_result = {
        'stock_code': '000001',
        'total_score': 75.5,
        'rating': 'A',
        'scores': {
            'quantitative': 85.0,
            'technical': 72.0,
            'position_timing': 65.0,
            'volume_health': 70.0,
        },
        'details': {
            'momentum': {
                'distance_from_high': 15.0,
                'change_60d': 45.0,
                'consecutive_up_days': 3,
            }
        }
    }
    
    # 测试不同策略
    for strategy in ['conservative', 'balanced', 'aggressive']:
        print(f"\n【{strategy.upper()}策略】")
        filter_obj = ComprehensiveScoreFilter(strategy=strategy)
        filter_obj.print_current_config()
        
        passed, reason, details = filter_obj.filter(mock_result)
        print(f"筛选结果: {'✓ 通过' if passed else '✗ 未通过'}")
        print(f"原因: {reason}")
        print(f"详情: {details}")
