#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0数据分析器 - 分析和处理数据采集中的0数据批次问题
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging
import json

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ZeroDataAnalyzer:
    """0数据分析器"""

    def __init__(self):
        """初始化分析器"""
        self.stock_holidays = self._load_stock_holidays()
        self.suspension_periods = self._load_common_suspension_periods()

    def _load_stock_holidays(self) -> List[str]:
        """加载股市休市日期（简化版）"""
        holidays = []

        # 2024年主要节假日
        holidays_2024 = [
            # 元旦假期
            "2024-01-01",
            # 春节假期
            "2024-02-10", "2024-02-11", "2024-02-12", "2024-02-13", "2024-02-14", "2024-02-15", "2024-02-16",
            "2024-02-17",
            # 清明假期
            "2024-04-04", "2024-04-05", "2024-04-06",
            # 劳动节假期
            "2024-05-01", "2024-05-02", "2024-05-03", "2024-05-04", "2024-05-05",
            # 端午假期
            "2024-06-08", "2024-06-09", "2024-06-10",
            # 中秋假期
            "2024-09-15", "2024-09-16", "2024-09-17",
            # 国庆假期
            "2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04", "2024-10-05", "2024-10-06", "2024-10-07"
        ]

        # 2025年主要节假日（预估）
        holidays_2025 = [
            # 元旦假期
            "2025-01-01",
            # 春节假期（预估）
            "2025-01-28", "2025-01-29", "2025-01-30", "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03",
            # 清明假期（预估）
            "2025-04-05", "2025-04-06", "2025-04-07",
            # 劳动节假期（预估）
            "2025-05-01", "2025-05-02", "2025-05-03",
            # 端午假期（预估）
            "2025-05-31", "2025-06-01", "2025-06-02",
            # 中秋假期（预估）
            "2025-10-06", "2025-10-07", "2025-10-08",
            # 国庆假期（预估）
            "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04", "2025-10-05"
        ]

        holidays.extend(holidays_2024)
        holidays.extend(holidays_2025)

        return holidays

    def _load_common_suspension_periods(self) -> Dict[str, List[Dict]]:
        """加载常见的股票停牌时段"""
        return {
            # 系统维护期间
            "system_maintenance": [
                {"start": "2024-12-31", "end": "2025-01-02", "reason": "年末系统维护"},
                {"start": "2025-01-27", "end": "2025-02-04", "reason": "春节系统维护"}
            ],
            # 市场调整期间
            "market_adjustment": [
                {"start": "2024-11-01", "end": "2024-11-30", "reason": "市场调整期"},
                {"start": "2024-12-01", "end": "2024-12-31", "reason": "年末市场调整"}
            ]
        }

    def analyze_zero_data_batch(self, start_date: str, end_date: str, symbol: str = "") -> Dict[str, Any]:
        """
        分析0数据批次的原因
        
        Args:
            start_date: 批次开始日期 (YYYYMMDD)
            end_date: 批次结束日期 (YYYYMMDD)
            symbol: 股票代码
            
        Returns:
            分析结果字典
        """
        try:
            # 转换日期格式
            start_dt = datetime.strptime(start_date, '%Y%m%d')
            end_dt = datetime.strptime(end_date, '%Y%m%d')

            analysis = {
                'time_range': f"{start_dt.strftime('%Y-%m-%d')} 到 {end_dt.strftime('%Y-%m-%d')}",
                'total_days': (end_dt - start_dt).days + 1,
                'reasons': [],
                'category': 'unknown',
                'skip_recommended': False,
                'alternative_periods': []
            }

            # 检查是否为未来日期
            now = datetime.now()
            if start_dt > now:
                analysis['reasons'].append("🔮 未来日期：该时间段尚未到来")
                analysis['category'] = 'future_date'
                analysis['skip_recommended'] = True
                return analysis

            if end_dt > now:
                # 部分为未来日期
                analysis['reasons'].append("⚠️ 部分未来日期：时间段包含未来日期")
                # 建议替代时间段
                alternative_end = now.strftime('%Y-%m-%d')
                if start_dt < now:
                    analysis['alternative_periods'].append({
                        'start': start_dt.strftime('%Y-%m-%d'),
                        'end': alternative_end,
                        'reason': '调整到当前日期'
                    })

            # 检查是否包含大量节假日
            holidays_in_range = 0
            current_date = start_dt
            while current_date <= end_dt:
                date_str = current_date.strftime('%Y-%m-%d')
                # 检查周末
                if current_date.weekday() >= 5:  # 周六日
                    holidays_in_range += 1
                # 检查节假日
                elif date_str in self.stock_holidays:
                    holidays_in_range += 1
                current_date += timedelta(days=1)

            holiday_ratio = holidays_in_range / analysis['total_days']
            if holiday_ratio > 0.7:
                analysis['reasons'].append(f"🏮 节假日密集：{holiday_ratio:.1%}为休市日")
                analysis['category'] = 'holiday_period'

            # 检查是否在停牌期间
            for category, periods in self.suspension_periods.items():
                for period in periods:
                    period_start = datetime.strptime(period['start'], '%Y-%m-%d')
                    period_end = datetime.strptime(period['end'], '%Y-%m-%d')

                    # 检查时间段重叠
                    if not (end_dt < period_start or start_dt > period_end):
                        analysis['reasons'].append(f"⏸️ {period['reason']}")
                        analysis['category'] = 'suspension_period'

            # 检查股票特定情况（创业板等）
            if symbol:
                if symbol.startswith('300'):
                    # 创业板股票，检查是否在注册制改革期间
                    reform_start = datetime(2020, 8, 24)
                    if start_dt >= reform_start and end_dt <= datetime(2020, 9, 30):
                        analysis['reasons'].append("📋 创业板注册制改革期间，交易规则调整")
                        analysis['category'] = 'market_reform'

                elif symbol.startswith('688'):
                    # 科创板股票，检查上市初期
                    if start_dt >= datetime(2019, 7, 22) and end_dt <= datetime(2019, 8, 30):
                        analysis['reasons'].append("🚀 科创板上市初期，交易数据可能不完整")
                        analysis['category'] = 'new_market'

            # 如果没有明确原因，给出通用建议
            if not analysis['reasons']:
                analysis['reasons'].append("❓ 数据源可能暂时不可用或该时段无交易数据")
                analysis['category'] = 'data_unavailable'

                # 建议近期有效的时间段
                recent_start = max(start_dt, now - timedelta(days=90))
                recent_end = min(end_dt, now - timedelta(days=1))

                if recent_start < recent_end:
                    analysis['alternative_periods'].append({
                        'start': recent_start.strftime('%Y-%m-%d'),
                        'end': recent_end.strftime('%Y-%m-%d'),
                        'reason': '使用最近90天的有效交易日'
                    })

            return analysis

        except Exception as e:
            return {
                'time_range': f"{start_date} 到 {end_date}",
                'reasons': [f"❌ 分析出错: {str(e)}"],
                'category': 'error',
                'skip_recommended': True
            }

    def suggest_optimal_time_ranges(self, symbol: str, target_days: int = 365,
                                    period: str = '5m') -> List[Dict[str, Any]]:
        """
        建议最优的数据采集时间范围
        
        Args:
            symbol: 股票代码
            target_days: 目标天数
            period: 数据周期
            
        Returns:
            建议的时间范围列表
        """
        suggestions = []
        now = datetime.now()

        # 策略1: 最近的有效交易期
        recent_end = now - timedelta(days=1)  # 避免当天数据不完整
        recent_start = recent_end - timedelta(days=target_days)

        # 跳过主要节假日
        adjusted_start = self._adjust_for_holidays(recent_start, direction='forward')
        adjusted_end = self._adjust_for_holidays(recent_end, direction='backward')

        suggestions.append({
            'name': '最近有效交易期',
            'start': adjusted_start.strftime('%Y-%m-%d'),
            'end': adjusted_end.strftime('%Y-%m-%d'),
            'days': (adjusted_end - adjusted_start).days,
            'priority': 'high',
            'reason': '最新且最完整的交易数据'
        })

        # 策略2: 避开年末年初的时间段
        stable_end = datetime(now.year, 11, 30) if now.month >= 12 else recent_end
        stable_start = stable_end - timedelta(days=target_days)

        suggestions.append({
            'name': '稳定交易期',
            'start': stable_start.strftime('%Y-%m-%d'),
            'end': stable_end.strftime('%Y-%m-%d'),
            'days': (stable_end - stable_start).days,
            'priority': 'medium',
            'reason': '避开年末系统维护和节假日密集期'
        })

        # 策略3: 分季度采集
        if target_days > 180:
            quarters = []
            current_quarter_end = now - timedelta(days=1)

            for i in range(4):  # 最近4个季度
                quarter_start = current_quarter_end - timedelta(days=90)
                quarter_start = self._adjust_for_holidays(quarter_start, direction='forward')
                quarter_end = self._adjust_for_holidays(current_quarter_end, direction='backward')

                quarters.append({
                    'start': quarter_start.strftime('%Y-%m-%d'),
                    'end': quarter_end.strftime('%Y-%m-%d'),
                    'days': (quarter_end - quarter_start).days
                })

                current_quarter_end = quarter_start - timedelta(days=1)

            suggestions.append({
                'name': '分季度采集',
                'quarters': quarters,
                'total_days': sum(q['days'] for q in quarters),
                'priority': 'low',
                'reason': '分批采集，提高成功率'
            })

        return suggestions

    def _adjust_for_holidays(self, date: datetime, direction: str = 'forward') -> datetime:
        """调整日期以避开节假日"""
        adjusted_date = date
        max_adjust_days = 10  # 最大调整天数

        for _ in range(max_adjust_days):
            date_str = adjusted_date.strftime('%Y-%m-%d')

            # 检查是否为工作日且非节假日
            if (adjusted_date.weekday() < 5 and  # 非周末
                    date_str not in self.stock_holidays):  # 非节假日
                return adjusted_date

            # 根据方向调整日期
            if direction == 'forward':
                adjusted_date += timedelta(days=1)
            else:
                adjusted_date -= timedelta(days=1)

        return date  # 如果无法调整，返回原日期

    def generate_zero_data_report(self, batches_info: List[Dict]) -> str:
        """生成0数据批次分析报告"""
        if not batches_info:
            return "没有0数据批次需要分析"

        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append("📊 0数据批次分析报告")
        report_lines.append("=" * 70)

        # 分类统计
        categories = {}
        for batch in batches_info:
            category = batch.get('category', 'unknown')
            categories[category] = categories.get(category, 0) + 1

        report_lines.append(f"📈 总批次数: {len(batches_info)}")
        report_lines.append(f"📊 分类统计:")
        for category, count in categories.items():
            category_names = {
                'future_date': '未来日期',
                'holiday_period': '节假日密集',
                'suspension_period': '停牌维护期',
                'market_reform': '市场改革期',
                'new_market': '新市场初期',
                'data_unavailable': '数据不可用',
                'unknown': '未知原因'
            }
            name = category_names.get(category, category)
            report_lines.append(f"  - {name}: {count} 批次")

        # 详细分析
        report_lines.append(f"\n🔍 详细分析:")
        for i, batch in enumerate(batches_info, 1):
            report_lines.append(f"\n📦 批次 {i}: {batch['time_range']}")
            report_lines.append(f"   📅 天数: {batch['total_days']}")
            for reason in batch['reasons']:
                report_lines.append(f"   {reason}")

            if batch.get('skip_recommended'):
                report_lines.append(f"   💡 建议: 跳过此批次")

            if batch.get('alternative_periods'):
                report_lines.append(f"   🔄 替代方案:")
                for alt in batch['alternative_periods']:
                    report_lines.append(f"     - {alt['start']} 到 {alt['end']} ({alt['reason']})")

        report_lines.append(f"\n💡 总体建议:")

        # 根据分析结果给出建议
        future_count = categories.get('future_date', 0)
        holiday_count = categories.get('holiday_period', 0)

        if future_count > 0:
            report_lines.append(f"  🔮 避免请求未来日期的数据")

        if holiday_count > 0:
            report_lines.append(f"  🏮 考虑跳过节假日密集的时间段")

        report_lines.append(f"  📊 建议使用最近6个月的交易日数据")
        report_lines.append(f"  🔄 对于长时间范围，考虑分段采集")
        report_lines.append(f"  ⏰ 优先采集最近3个月的数据以确保完整性")

        report_lines.append("=" * 70)

        return "\n".join(report_lines)


def main():
    """主函数 - 演示0数据分析功能"""
    analyzer = ZeroDataAnalyzer()

    print("🔍 0数据分析器演示")
    print("=" * 50)

    # 模拟用户日志中的0数据批次
    zero_batches = [
        {"start": "20250607", "end": "20250707"},  # 未来日期
        {"start": "20250507", "end": "20250606"},  # 未来日期
        {"start": "20250406", "end": "20250506"},  # 未来日期
        {"start": "20250306", "end": "20250405"},  # 未来日期
        {"start": "20250203", "end": "20250305"},  # 未来日期
        {"start": "20250103", "end": "20250202"},  # 未来日期，包含春节
        {"start": "20241203", "end": "20250102"},  # 跨年期间
        {"start": "20241102", "end": "20241202"},  # 年末期间
        {"start": "20241002", "end": "20241101"},  # 包含国庆
        {"start": "20240907", "end": "20241001"}  # 包含中秋国庆
    ]

    # 分析每个0数据批次
    analyses = []
    for batch in zero_batches:
        analysis = analyzer.analyze_zero_data_batch(
            batch["start"], batch["end"], "300555"
        )
        analyses.append(analysis)

    # 生成报告
    report = analyzer.generate_zero_data_report(analyses)
    print(report)

    # 建议最优时间范围
    print(f"\n🎯 最优时间范围建议:")
    suggestions = analyzer.suggest_optimal_time_ranges("300555", 365, "5m")
    for i, suggestion in enumerate(suggestions, 1):
        print(f"\n{i}. {suggestion['name']} (优先级: {suggestion['priority']})")
        print(f"   📅 时间: {suggestion['start']} 到 {suggestion['end']}")
        print(f"   📊 天数: {suggestion['days']}")
        print(f"   💡 理由: {suggestion['reason']}")

        if 'quarters' in suggestion:
            print(f"   📦 分季度方案:")
            for j, quarter in enumerate(suggestion['quarters'], 1):
                print(f"     Q{j}: {quarter['start']} 到 {quarter['end']} ({quarter['days']}天)")


if __name__ == "__main__":
    main()
