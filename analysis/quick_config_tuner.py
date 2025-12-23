#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速配置调整工具
支持快速调整评级阈值、基础分、维度权重等参数
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
import sys
import logging

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


@dataclass
class ScoringConfig:
    """打分系统配置"""

    # 评级阈值
    rating_thresholds: Dict[str, int] = field(
        default_factory=lambda: {
            'S': 82,
            'A+': 72,
            'A': 62,
            'B': 48,
            'C': 0
        }
    )

    # 维度权重
    dimension_weights: Dict[str, float] = field(
        default_factory=lambda: {
            'position_timing': 0.16,
            'volume_health': 0.14,
            'technical': 0.12,
            'quantitative': 0.35,
            'liquidity': 0.08,
            'sector': 0.06,
            'dragon_tiger': 0.04,
            'fundamental': 0.03,
            'events': 0.02,
            'sentiment': 0.00
        }
    )

    # 一票否决规则
    exclusion_rules: Dict[str, float] = field(
        default_factory=lambda: {
            'max_change_60d': 80,
            'max_change_20d': 50,
            'max_distance_from_high': 5,
            'max_consecutive_up': 7,
            'min_profit_yoy': -70
        }
    )

    # 过滤策略参数
    filter_strategies: Dict[str, Dict] = field(
        default_factory=lambda: {
            'conservative': {'min_rating': 'A+', 'min_score': 75},
            'balanced': {'min_rating': 'A', 'min_score': 65},
            'aggressive': {'min_rating': 'B', 'min_score': 55},
            'bottom_hunting': {'min_rating': 'B', 'min_score': 45}
        }
    )

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'ScoringConfig':
        """从字典创建"""
        return cls(**data)


class QuickConfigTuner:
    """快速配置调整工具"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置调整工具

        Args:
            config_path: 配置文件路径（JSON格式）
        """
        self.config_path = config_path
        self.config = ScoringConfig()

        if config_path and Path(config_path).exists():
            self.load_config(config_path)

    def load_config(self, config_path: str):
        """加载配置"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.config = ScoringConfig.from_dict(data)
            logger.info(f"✅ 配置已加载: {config_path}")
        except Exception as e:
            logger.error(f"❌ 加载配置失败: {str(e)}")

    def save_config(self, config_path: Optional[str] = None):
        """保存配置"""
        path = config_path or self.config_path
        if not path:
            raise ValueError("未指定配置文件路径")

        try:
            Path(path).parent.mkdir(exist_ok=True, parents=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2, ensure_ascii=False)
            logger.info(f"✅ 配置已保存: {path}")
        except Exception as e:
            logger.error(f"❌ 保存配置失败: {str(e)}")

    # ==================== 评级阈值调整 ====================

    def adjust_rating_threshold(self, rating: str, new_score: int) -> bool:
        """
        调整单个评级阈值

        Args:
            rating: 评级 (S/A+/A/B/C)
            new_score: 新的分数门槛

        Returns:
            是否调整成功
        """
        if rating not in self.config.rating_thresholds:
            logger.error(f"❌ 无效的评级: {rating}")
            return False

        old_score = self.config.rating_thresholds[rating]
        self.config.rating_thresholds[rating] = new_score

        logger.info(f"✅ 评级阈值已调整: {rating} {old_score}→{new_score}")
        return True

    def adjust_all_rating_thresholds(self, thresholds: Dict[str, int]) -> bool:
        """
        批量调整所有评级阈值

        Args:
            thresholds: 评级→分数 映射

        Returns:
            是否调整成功
        """
        try:
            for rating, score in thresholds.items():
                if rating not in self.config.rating_thresholds:
                    logger.warning(f"⚠️  忽略无效评级: {rating}")
                    continue
                self.config.rating_thresholds[rating] = score

            logger.info(f"✅ 所有评级阈值已调整: {thresholds}")
            return True
        except Exception as e:
            logger.error(f"❌ 调整评级阈值失败: {str(e)}")
            return False

    def increase_rating_threshold(self, rating: str, increase: int) -> bool:
        """
        提高评级阈值（更严格）

        Args:
            rating: 评级
            increase: 增加的分数

        Returns:
            是否调整成功
        """
        if rating not in self.config.rating_thresholds:
            return False

        new_score = self.config.rating_thresholds[rating] + increase
        return self.adjust_rating_threshold(rating, new_score)

    def decrease_rating_threshold(self, rating: str, decrease: int) -> bool:
        """
        降低评级阈值（更宽松）

        Args:
            rating: 评级
            decrease: 减少的分数

        Returns:
            是否调整成功
        """
        return self.increase_rating_threshold(rating, -decrease)

    # ==================== 维度权重调整 ====================

    def adjust_dimension_weight(self, dimension: str, new_weight: float) -> bool:
        """
        调整单个维度权重

        Args:
            dimension: 维度名称
            new_weight: 新的权重值 (0-1)

        Returns:
            是否调整成功
        """
        if dimension not in self.config.dimension_weights:
            logger.error(f"❌ 无效的维度: {dimension}")
            return False

        if not 0 <= new_weight <= 1:
            logger.error(f"❌ 权重值必须在0-1之间: {new_weight}")
            return False

        old_weight = self.config.dimension_weights[dimension]
        self.config.dimension_weights[dimension] = new_weight

        # 检查总权重
        total_weight = sum(self.config.dimension_weights.values())
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(
                f"⚠️  权重总和不为1: {total_weight:.3f}（"
                f"为维度权重标准化调整）"
            )

        logger.info(
            f"✅ 维度权重已调整: {dimension} {old_weight:.3f}→{new_weight:.3f}"
        )
        return True

    def normalize_weights(self) -> bool:
        """
        标准化所有维度权重（和为1）

        Returns:
            是否标准化成功
        """
        try:
            total = sum(self.config.dimension_weights.values())
            if abs(total - 1.0) < 0.01:
                logger.info("✅ 权重已正常化（总和为1）")
                return True

            # 按比例缩放
            for dim in self.config.dimension_weights:
                self.config.dimension_weights[dim] /= total

            logger.info(f"✅ 权重已标准化（之前总和: {total:.3f}）")
            return True
        except Exception as e:
            logger.error(f"❌ 标准化权重失败: {str(e)}")
            return False

    def boost_dimension(self, dimension: str, boost_factor: float) -> bool:
        """
        提升某个维度的权重

        Args:
            dimension: 维度名称
            boost_factor: 提升因子 (>1 表示提升, <1 表示降低)

        Returns:
            是否提升成功
        """
        if dimension not in self.config.dimension_weights:
            return False

        old_weight = self.config.dimension_weights[dimension]
        new_weight = old_weight * boost_factor

        return self.adjust_dimension_weight(dimension, min(new_weight, 1.0))

    # ==================== 一票否决规则调整 ====================

    def adjust_exclusion_rule(self, rule: str, new_value: float) -> bool:
        """
        调整一票否决规则

        Args:
            rule: 规则名称
            new_value: 新的阈值

        Returns:
            是否调整成功
        """
        if rule not in self.config.exclusion_rules:
            logger.error(f"❌ 无效的规则: {rule}")
            return False

        old_value = self.config.exclusion_rules[rule]
        self.config.exclusion_rules[rule] = new_value

        logger.info(f"✅ 否决规则已调整: {rule} {old_value}→{new_value}")
        return True

    def relax_exclusion_rules(self, relaxation_factor: float = 0.9) -> bool:
        """
        放宽所有一票否决规则（降低严格程度）

        Args:
            relaxation_factor: 放宽因子 (<1 表示放宽)

        Returns:
            是否放宽成功
        """
        try:
            for rule in self.config.exclusion_rules:
                old_value = self.config.exclusion_rules[rule]
                # 对于"上升"类规则，降低阈值；对于"下降"类规则，提高阈值
                if 'max' in rule or 'min_profit' in rule:
                    new_value = old_value * relaxation_factor
                else:
                    new_value = old_value / relaxation_factor

                self.config.exclusion_rules[rule] = new_value

            logger.info(f"✅ 否决规则已放宽（因子: {relaxation_factor}）")
            return True
        except Exception as e:
            logger.error(f"❌ 放宽规则失败: {str(e)}")
            return False

    # ==================== 过滤策略调整 ====================

    def adjust_filter_strategy(
        self, strategy_name: str, min_rating: Optional[str] = None, min_score: Optional[int] = None
    ) -> bool:
        """
        调整过滤策略参数

        Args:
            strategy_name: 策略名称 ('conservative', 'balanced', 'aggressive', 'bottom_hunting')
            min_rating: 最低评级
            min_score: 最低评分

        Returns:
            是否调整成功
        """
        if strategy_name not in self.config.filter_strategies:
            logger.error(f"❌ 无效的策略: {strategy_name}")
            return False

        strategy = self.config.filter_strategies[strategy_name]

        if min_rating:
            strategy['min_rating'] = min_rating

        if min_score:
            strategy['min_score'] = min_score

        logger.info(f"✅ 过滤策略已调整: {strategy_name} → {strategy}")
        return True

    # ==================== 预设快速方案 ====================

    def apply_preset(self, preset_name: str) -> bool:
        """
        应用预设配置方案

        Args:
            preset_name: 预设名称

        Returns:
            是否应用成功
        """
        presets = {
            'aggressive': self._preset_aggressive,
            'conservative': self._preset_conservative,
            'balanced': self._preset_balanced,
            'high_volatility': self._preset_high_volatility,
            'low_volatility': self._preset_low_volatility,
        }

        if preset_name not in presets:
            logger.error(f"❌ 无效的预设: {preset_name}")
            return False

        try:
            presets[preset_name]()
            logger.info(f"✅ 预设已应用: {preset_name}")
            return True
        except Exception as e:
            logger.error(f"❌ 应用预设失败: {str(e)}")
            return False

    def _preset_aggressive(self):
        """激进预设：降低评分门槛，强调量化信号"""
        self.adjust_all_rating_thresholds({'S': 75, 'A+': 65, 'A': 55, 'B': 40, 'C': 0})
        self.adjust_dimension_weight('quantitative', 0.40)
        self.relax_exclusion_rules(relaxation_factor=0.85)

    def _preset_conservative(self):
        """保守预设：提高评分门槛，强调基本面"""
        self.adjust_all_rating_thresholds({'S': 90, 'A+': 80, 'A': 70, 'B': 55, 'C': 0})
        self.adjust_dimension_weight('fundamental', 0.08)
        self.relax_exclusion_rules(relaxation_factor=1.15)

    def _preset_balanced(self):
        """均衡预设：标准配置"""
        self.adjust_all_rating_thresholds({'S': 82, 'A+': 72, 'A': 62, 'B': 48, 'C': 0})
        self.adjust_dimension_weight('quantitative', 0.35)
        self.config.exclusion_rules = {
            'max_change_60d': 80,
            'max_change_20d': 50,
            'max_distance_from_high': 5,
            'max_consecutive_up': 7,
            'min_profit_yoy': -70
        }

    def _preset_high_volatility(self):
        """高波动预设：强调技术面和位置"""
        self.adjust_dimension_weight('position_timing', 0.20)
        self.adjust_dimension_weight('technical', 0.18)
        self.adjust_dimension_weight('volume_health', 0.16)
        self.normalize_weights()

    def _preset_low_volatility(self):
        """低波动预设：强调基本面和量化"""
        self.adjust_dimension_weight('fundamental', 0.10)
        self.adjust_dimension_weight('quantitative', 0.40)
        self.normalize_weights()

    # ==================== 配置查询 ====================

    def print_config(self):
        """打印当前配置"""
        print("\n" + "=" * 60)
        print("📋 当前打分系统配置")
        print("=" * 60)

        print("\n【评级阈值】")
        for rating, score in sorted(
            self.config.rating_thresholds.items(),
            key=lambda x: (-x[1], x[0])
        ):
            print(f"  {rating:3s}: {score:3d}分")

        print("\n【维度权重】(总和: {:.3f})".format(sum(self.config.dimension_weights.values())))
        for dim, weight in sorted(
            self.config.dimension_weights.items(),
            key=lambda x: -x[1]
        ):
            bar = '█' * int(weight * 50)
            print(f"  {dim:20s}: {weight:.3f} {bar}")

        print("\n【一票否决规则】")
        for rule, value in self.config.exclusion_rules.items():
            print(f"  {rule:25s}: {value}")

        print("\n【过滤策略】")
        for strategy, params in self.config.filter_strategies.items():
            print(f"  {strategy:20s}: {params}")

        print("\n" + "=" * 60 + "\n")

    def get_config_summary(self) -> Dict:
        """获取配置摘要"""
        return {
            'rating_thresholds': self.config.rating_thresholds,
            'dimension_weights': self.config.dimension_weights,
            'weights_sum': sum(self.config.dimension_weights.values()),
            'exclusion_rules': self.config.exclusion_rules,
            'filter_strategies': self.config.filter_strategies,
        }


def create_quick_tuner_cli():
    """创建交互式CLI工具"""
    tuner = QuickConfigTuner()

    print("\n" + "=" * 60)
    print("快速配置调整工具 - 交互模式")
    print("=" * 60)

    while True:
        print("\n请选择操作:")
        print("1. 显示当前配置")
        print("2. 调整评级阈值")
        print("3. 调整维度权重")
        print("4. 应用预设方案")
        print("5. 保存配置")
        print("6. 退出")

        choice = input("\n请输入选择 (1-6): ").strip()

        if choice == '1':
            tuner.print_config()
        elif choice == '2':
            rating = input("输入评级 (S/A+/A/B): ").strip()
            try:
                score = int(input("输入新的分数阈值: "))
                tuner.adjust_rating_threshold(rating, score)
            except ValueError:
                print("❌ 输入无效")
        elif choice == '3':
            dim = input("输入维度名称: ").strip()
            try:
                weight = float(input("输入新的权重 (0-1): "))
                tuner.adjust_dimension_weight(dim, weight)
            except ValueError:
                print("❌ 输入无效")
        elif choice == '4':
            print("\n可用预设:")
            presets = ['aggressive', 'conservative', 'balanced', 'high_volatility', 'low_volatility']
            for i, p in enumerate(presets, 1):
                print(f"{i}. {p}")
            try:
                preset_idx = int(input("请选择预设 (1-5): ")) - 1
                tuner.apply_preset(presets[preset_idx])
            except (ValueError, IndexError):
                print("❌ 选择无效")
        elif choice == '5':
            path = input("输入配置文件路径 (默认: config/scoring_config.json): ").strip()
            if not path:
                path = "config/scoring_config.json"
            tuner.save_config(path)
        elif choice == '6':
            print("👋 再见!")
            break


if __name__ == "__main__":
    # 测试快速调整工具
    print("\n快速配置调整工具 - 测试模式\n")

    tuner = QuickConfigTuner()

    # 显示原始配置
    print("【原始配置】")
    tuner.print_config()

    # 测试调整操作
    print("【测试操作】")
    tuner.adjust_rating_threshold('S', 85)
    tuner.adjust_dimension_weight('quantitative', 0.40)
    tuner.apply_preset('aggressive')

    print("\n【调整后配置】")
    tuner.print_config()

    # 保存配置
    tuner.save_config("config/scoring_config_test.json")
    print("✅ 测试完成")
