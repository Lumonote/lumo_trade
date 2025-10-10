#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能数据采集策略 - 处理0数据问题的完整解决方案
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import logging

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

try:
    from scripts.eastmoney_crawler import EastMoneyCrawler
    from analysis.data_processor import DataProcessor

    MODULES_AVAILABLE = True
except ImportError as e:
    MODULES_AVAILABLE = False
    print(f"模块不可用: {e}")


class SmartDataCollectionStrategy:
    """智能数据采集策略 - 专门解决0数据问题"""

    def __init__(self, data_dir: str = 'data'):
        """初始化智能采集策略"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        if MODULES_AVAILABLE:
            self.crawler = EastMoneyCrawler()
            self.data_processor = DataProcessor()

        # 定义有效的交易时段
        self.valid_periods = self._define_valid_periods()

    def _define_valid_periods(self) -> List[Dict[str, str]]:
        """定义有效的数据采集时段"""
        now = datetime.now()
        periods = []

        # 最近3个月（最可靠）
        end_date = now - timedelta(days=1)  # 避免当天数据不完整
        start_date = end_date - timedelta(days=90)
        periods.append({
            'name': '最近3个月',
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
            'priority': 'high',
            'expected_data': True,
            'reason': '最新且最完整的交易数据'
        })

        # 最近6个月（较可靠）
        start_date = end_date - timedelta(days=180)
        periods.append({
            'name': '最近6个月',
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
            'priority': 'medium',
            'expected_data': True,
            'reason': '较长时间范围，包含更多市场周期'
        })

        # 去年同期（参考用）
        last_year_end = datetime(now.year - 1, now.month, now.day)
        last_year_start = last_year_end - timedelta(days=90)
        periods.append({
            'name': '去年同期',
            'start': last_year_start.strftime('%Y-%m-%d'),
            'end': last_year_end.strftime('%Y-%m-%d'),
            'priority': 'low',
            'expected_data': True,
            'reason': '历史同期数据，用于对比分析'
        })

        return periods

    def analyze_zero_data_causes(self, batch_info: Dict) -> Dict[str, Any]:
        """分析0数据的具体原因"""
        start_str = batch_info.get('start_date', '')
        end_str = batch_info.get('end_date', '')

        try:
            # 转换日期格式
            start_dt = datetime.strptime(start_str, '%Y%m%d') if len(start_str) == 8 else datetime.strptime(start_str,
                                                                                                            '%Y-%m-%d')
            end_dt = datetime.strptime(end_str, '%Y%m%d') if len(end_str) == 8 else datetime.strptime(end_str,
                                                                                                      '%Y-%m-%d')
            now = datetime.now()

            causes = []

            # 检查未来日期
            if start_dt > now:
                causes.append({
                    'type': 'future_date',
                    'description': '🔮 完全是未来日期，数据尚不存在',
                    'severity': 'critical',
                    'action': '跳过此时间段'
                })
            elif end_dt > now:
                causes.append({
                    'type': 'partial_future',
                    'description': '⚠️ 包含未来日期，部分数据不可用',
                    'severity': 'warning',
                    'action': f'调整结束日期到 {now.strftime("%Y-%m-%d")}'
                })

            # 检查节假日密集期
            holidays_count = self._count_holidays_in_range(start_dt, end_dt)
            total_days = (end_dt - start_dt).days + 1
            if holidays_count / total_days > 0.5:
                causes.append({
                    'type': 'holiday_period',
                    'description': f'🏮 节假日密集期，{holidays_count}/{total_days}天为休市日',
                    'severity': 'medium',
                    'action': '考虑选择其他时间段'
                })

            # 检查年末年初系统维护期
            if self._is_system_maintenance_period(start_dt, end_dt):
                causes.append({
                    'type': 'maintenance',
                    'description': '🔧 系统维护期间，数据可能不完整',
                    'severity': 'medium',
                    'action': '选择稳定交易期'
                })

            # 检查历史数据过远
            days_from_now = (now - end_dt).days
            if days_from_now > 365:
                causes.append({
                    'type': 'too_old',
                    'description': f'📅 历史数据过远（{days_from_now}天前），可能不可用',
                    'severity': 'low',
                    'action': '优先使用最近一年的数据'
                })

            if not causes:
                causes.append({
                    'type': 'unknown',
                    'description': '❓ 原因不明，可能是数据源临时问题',
                    'severity': 'low',
                    'action': '稍后重试或更换时间段'
                })

            return {
                'time_range': f"{start_dt.strftime('%Y-%m-%d')} 到 {end_dt.strftime('%Y-%m-%d')}",
                'causes': causes,
                'recommended_skip': any(c['severity'] == 'critical' for c in causes)
            }

        except Exception as e:
            return {
                'time_range': f"{start_str} 到 {end_str}",
                'causes': [{'type': 'error', 'description': f'❌ 分析出错: {e}', 'severity': 'critical'}],
                'recommended_skip': True
            }

    def _count_holidays_in_range(self, start_dt: datetime, end_dt: datetime) -> int:
        """计算时间范围内的节假日数量"""
        holidays = 0
        current = start_dt

        while current <= end_dt:
            # 周末
            if current.weekday() >= 5:
                holidays += 1
            # 主要节假日（简化判断）
            elif (current.month == 1 and current.day == 1) or \
                    (current.month == 2 and 10 <= current.day <= 17) or \
                    (current.month == 4 and 4 <= current.day <= 6) or \
                    (current.month == 5 and 1 <= current.day <= 5) or \
                    (current.month == 10 and 1 <= current.day <= 7):
                holidays += 1

            current += timedelta(days=1)

        return holidays

    def _is_system_maintenance_period(self, start_dt: datetime, end_dt: datetime) -> bool:
        """检查是否为系统维护期"""
        # 年末年初
        if ((start_dt.month == 12 and start_dt.day >= 25) or
                (start_dt.month == 1 and start_dt.day <= 7) or
                (end_dt.month == 12 and end_dt.day >= 25) or
                (end_dt.month == 1 and end_dt.day <= 7)):
            return True

        # 春节期间
        if start_dt.month == 2 or end_dt.month == 2:
            return True

        return False

    async def smart_collect_with_fallback(self, symbol: str, period: str = '5m',
                                          target_days: int = 365) -> Dict[str, Any]:
        """智能采集，遇到0数据自动切换策略"""
        if not MODULES_AVAILABLE:
            return {'success': False, 'error': '必需模块不可用'}

        print(f"🎯 启动智能数据采集: {symbol}")
        print(f"⚡ 目标: {target_days} 天的 {period} 数据")

        collection_results = []
        total_collected = 0

        # 尝试各个有效时段
        for period_info in self.valid_periods:
            if total_collected >= target_days * 0.8:  # 达到80%目标即可停止
                print(f"✅ 已收集足够数据，停止采集")
                break

            print(f"\\n📦 尝试采集: {period_info['name']}")
            print(f"📅 时间范围: {period_info['start']} 到 {period_info['end']}")
            print(f"🔍 优先级: {period_info['priority']}")

            try:
                # 使用东方财富爬虫采集
                data = await self.crawler.get_kline_data(
                    symbol=symbol,
                    period=period,
                    start_date=period_info['start'].replace('-', ''),
                    end_date=period_info['end'].replace('-', '')
                )

                if data and data.get('rc') == 0:
                    klines = data.get('data', {}).get('klines', [])
                    if klines:
                        # 处理数据
                        df = self.data_processor.process_eastmoney_data(data, symbol)
                        if df is not None and not df.empty:
                            period_collected = len(df)
                            total_collected += period_collected

                            collection_results.append({
                                'period': period_info['name'],
                                'start': period_info['start'],
                                'end': period_info['end'],
                                'records': period_collected,
                                'data': df,
                                'success': True
                            })

                            print(f"✅ 成功采集 {period_collected} 条数据")

                            # 保存每个时段的数据
                            await self._save_period_data(df, symbol, period, period_info['name'])
                        else:
                            print(f"⚠️ 数据处理失败")
                    else:
                        print(f"⚠️ API响应成功但无数据")
                        # 分析0数据原因
                        analysis = self.analyze_zero_data_causes({
                            'start_date': period_info['start'],
                            'end_date': period_info['end']
                        })
                        print(f"🔍 分析结果: {analysis['time_range']}")
                        for cause in analysis['causes']:
                            print(f"   {cause['description']}")
                else:
                    error_code = data.get('rc', 'Unknown') if data else 'No Response'
                    print(f"❌ API调用失败: {error_code}")

            except Exception as e:
                print(f"❌ 采集异常: {e}")
                collection_results.append({
                    'period': period_info['name'],
                    'success': False,
                    'error': str(e)
                })

            # 添加延时
            await asyncio.sleep(2)

        # 合并所有成功采集的数据
        if collection_results:
            successful_results = [r for r in collection_results if r['success']]
            if successful_results:
                # 合并DataFrame
                all_dfs = [r['data'] for r in successful_results]
                combined_df = pd.concat(all_dfs, ignore_index=True)

                # 去重和排序
                if 'timestamps' in combined_df.columns:
                    combined_df['timestamps'] = pd.to_datetime(combined_df['timestamps'])
                    combined_df = combined_df.drop_duplicates(subset=['timestamps']).reset_index(drop=True)
                    combined_df = combined_df.sort_values('timestamps').reset_index(drop=True)

                # 保存合并后的数据
                final_filepath = await self._save_final_data(combined_df, symbol, period)

                return {
                    'success': True,
                    'total_records': len(combined_df),
                    'periods_collected': len(successful_results),
                    'collection_results': collection_results,
                    'final_file': final_filepath,
                    'data_range': f"{combined_df['timestamps'].min()} 到 {combined_df['timestamps'].max()}"
                }

        return {
            'success': False,
            'error': '所有时段采集都失败',
            'collection_results': collection_results
        }

    async def _save_period_data(self, df: pd.DataFrame, symbol: str,
                                period: str, period_name: str) -> str:
        """保存单个时段的数据"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{symbol}_{period}_{period_name.replace(' ', '_')}_{timestamp}.csv"
        filepath = self.data_dir / filename

        df.to_csv(filepath, index=False)
        print(f"💾 已保存 {period_name} 数据: {filepath}")
        return str(filepath)

    async def _save_final_data(self, df: pd.DataFrame, symbol: str, period: str) -> str:
        """保存最终合并的数据"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{symbol}_{period}_智能采集_{timestamp}.csv"
        filepath = self.data_dir / filename

        df.to_csv(filepath, index=False)
        print(f"🎉 最终数据已保存: {filepath}")
        print(f"📊 总记录数: {len(df)}")
        print(f"📅 时间范围: {df['timestamps'].min()} 到 {df['timestamps'].max()}")

        return str(filepath)

    def generate_collection_report(self, result: Dict[str, Any]) -> str:
        """生成采集报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("📊 智能数据采集报告")
        lines.append("=" * 70)

        if result['success']:
            lines.append(f"✅ 采集成功")
            lines.append(f"📈 总记录数: {result['total_records']:,}")
            lines.append(f"📦 成功时段数: {result['periods_collected']}")
            lines.append(f"📅 数据范围: {result['data_range']}")
            lines.append(f"💾 最终文件: {result['final_file']}")
        else:
            lines.append(f"❌ 采集失败: {result['error']}")

        lines.append(f"\\n📋 详细结果:")
        for i, res in enumerate(result['collection_results'], 1):
            status = "✅" if res['success'] else "❌"
            lines.append(f"{i:2}. {status} {res['period']}")
            if res['success']:
                lines.append(f"     📊 记录数: {res['records']:,}")
                lines.append(f"     📅 范围: {res['start']} 到 {res['end']}")
            else:
                lines.append(f"     ❌ 错误: {res.get('error', 'Unknown')}")

        lines.append("=" * 70)
        return "\\n".join(lines)


async def main():
    """主函数 - 演示智能采集策略"""
    print("🚀 智能数据采集策略演示")
    print("🎯 专门解决0数据问题")

    strategy = SmartDataCollectionStrategy()

    # 测试股票
    test_symbol = "300555"  # 路通视信

    # 执行智能采集
    result = await strategy.smart_collect_with_fallback(
        symbol=test_symbol,
        period='5m',
        target_days=180
    )

    # 生成并显示报告
    report = strategy.generate_collection_report(result)
    print(f"\\n{report}")

    if result['success']:
        return 0
    else:
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
