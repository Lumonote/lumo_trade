#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据完整性检查和补全工具
在采集新数据前，先检查现有数据文件的完整性，判断是否需要补全
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import glob
import argparse

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))


class DataCompletenessChecker:
    """数据完整性检查器"""

    def __init__(self, data_dir: str = 'data'):
        """初始化检查器"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        # 支持的数据周期和对应的交易时间
        self.period_info = {
            '5min': {'points_per_day': 50, 'trading_minutes': 240},  # A股交易时间: 上午25点+下午25点
            '1min': {'points_per_day': 240, 'trading_minutes': 240},  # 4小时 * 60点/小时
            '15min': {'points_per_day': 16, 'trading_minutes': 240},  # 4小时 * 4点/小时
            '30min': {'points_per_day': 8, 'trading_minutes': 240},  # 4小时 * 2点/小时
            '1h': {'points_per_day': 4, 'trading_minutes': 240},  # 4小时 * 1点/小时
            'D': {'points_per_day': 1, 'trading_minutes': 240}  # 日线数据
        }

    def scan_data_files(self) -> List[Dict[str, Any]]:
        """扫描data目录下的所有数据文件"""
        files_info = []

        # 查找符合标准格式的文件: EXCHANGE_PERIOD_CODE.csv
        pattern = str(self.data_dir / "*.csv")
        csv_files = glob.glob(pattern)

        for file_path in csv_files:
            file_name = os.path.basename(file_path)

            # 解析文件名: XSHG_5min_600977.csv
            parts = file_name.replace('.csv', '').split('_')
            if len(parts) >= 3:
                exchange = parts[0]
                period = parts[1]
                stock_code = parts[2]

                # 检查文件基本信息
                file_stat = os.stat(file_path)
                file_size = file_stat.st_size
                last_modified = datetime.fromtimestamp(file_stat.st_mtime)

                files_info.append({
                    'file_path': file_path,
                    'file_name': file_name,
                    'exchange': exchange,
                    'period': period,
                    'stock_code': stock_code,
                    'file_size': file_size,
                    'last_modified': last_modified
                })

        return files_info

    def analyze_data_file(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """分析单个数据文件的完整性"""
        file_path = file_info['file_path']
        period = file_info['period']
        stock_code = file_info['stock_code']

        try:
            # 读取数据文件
            df = pd.read_csv(file_path)

            if df.empty:
                return {
                    'status': 'empty',
                    'issue': '文件为空',
                    'records': 0,
                    'recommendation': '重新采集完整数据'
                }

            # 检查必要列
            required_columns = ['timestamps', 'open', 'high', 'low', 'close']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                return {
                    'status': 'invalid',
                    'issue': f'缺少必要列: {missing_columns}',
                    'records': len(df),
                    'recommendation': '重新采集完整数据'
                }

            # 解析时间戳
            df['timestamps'] = pd.to_datetime(df['timestamps'])
            df = df.sort_values('timestamps').reset_index(drop=True)

            # 基本统计信息
            total_records = len(df)
            start_time = df['timestamps'].min()
            end_time = df['timestamps'].max()
            time_span_days = (end_time - start_time).days + 1

            # 计算数据密度和完整性
            analysis = {
                'status': 'valid',
                'records': total_records,
                'start_time': start_time,
                'end_time': end_time,
                'time_span_days': time_span_days,
                'data_age_days': (datetime.now() - end_time).days,
            }

            # 检查数据新鲜度
            if analysis['data_age_days'] > 7:
                analysis['freshness'] = 'outdated'
                analysis['freshness_issue'] = f"数据过期 {analysis['data_age_days']} 天"
            elif analysis['data_age_days'] > 2:
                analysis['freshness'] = 'stale'
                analysis['freshness_issue'] = f"数据较旧 {analysis['data_age_days']} 天"
            else:
                analysis['freshness'] = 'fresh'
                analysis['freshness_issue'] = None

            # 周期特定分析
            if period in self.period_info:
                expected_points_per_day = self.period_info[period]['points_per_day']

                # 计算交易日数量（排除周末）
                trading_days = self._count_trading_days(start_time.date(), end_time.date())
                expected_total_points = trading_days * expected_points_per_day

                # 数据完整性评估
                completeness_ratio = total_records / expected_total_points if expected_total_points > 0 else 0

                analysis.update({
                    'trading_days': trading_days,
                    'expected_total_points': expected_total_points,
                    'completeness_ratio': completeness_ratio,
                    'avg_points_per_day': total_records / max(time_span_days, 1)
                })

                # 数据完整性判断
                if completeness_ratio >= 0.9:
                    analysis['completeness'] = 'excellent'
                    analysis['completeness_issue'] = None
                elif completeness_ratio >= 0.7:
                    analysis['completeness'] = 'good'
                    analysis['completeness_issue'] = f"数据完整度 {completeness_ratio:.1%}，可能有部分缺失"
                elif completeness_ratio >= 0.5:
                    analysis['completeness'] = 'fair'
                    analysis['completeness_issue'] = f"数据完整度 {completeness_ratio:.1%}，有较多缺失"
                else:
                    analysis['completeness'] = 'poor'
                    analysis['completeness_issue'] = f"数据完整度 {completeness_ratio:.1%}，严重不完整"

            # 数据质量检查
            quality_issues = []

            # 检查价格数据有效性
            price_cols = ['open', 'high', 'low', 'close']
            for col in price_cols:
                if col in df.columns:
                    zero_count = (df[col] == 0).sum()
                    null_count = df[col].isnull().sum()
                    if zero_count > 0:
                        quality_issues.append(f"{col}列有{zero_count}个零值")
                    if null_count > 0:
                        quality_issues.append(f"{col}列有{null_count}个空值")

            # 检查时间序列连续性
            time_gaps = []
            if len(df) > 1:
                time_diffs = df['timestamps'].diff().dropna()
                # 对于分钟级数据，检查异常的时间间隔
                if period in ['1min', '5min', '15min', '30min']:
                    expected_interval = int(period.replace('min', ''))
                    normal_interval = timedelta(minutes=expected_interval)

                    large_gaps = time_diffs[time_diffs > normal_interval * 3]  # 超过3倍正常间隔
                    if len(large_gaps) > 0:
                        time_gaps.append(f"发现{len(large_gaps)}个异常时间间隔")

            analysis['quality_issues'] = quality_issues + time_gaps

            # 生成建议
            recommendations = []

            if analysis.get('freshness') == 'outdated':
                recommendations.append("更新最新数据")
            elif analysis.get('freshness') == 'stale':
                recommendations.append("补充最近几天的数据")

            if analysis.get('completeness') in ['poor', 'fair']:
                recommendations.append("重新采集完整历史数据")
            elif analysis.get('completeness') == 'good':
                recommendations.append("补充缺失的数据点")

            if quality_issues:
                recommendations.append("修复数据质量问题")

            if not recommendations:
                recommendations.append("数据状态良好，无需处理")

            analysis['recommendations'] = recommendations

            return analysis

        except Exception as e:
            return {
                'status': 'error',
                'issue': f'文件读取失败: {str(e)}',
                'records': 0,
                'recommendation': '检查文件格式或重新采集'
            }

    def _count_trading_days(self, start_date, end_date) -> int:
        """计算指定日期范围内的交易日数量（排除周末）"""
        trading_days = 0
        current_date = start_date

        while current_date <= end_date:
            # 周一到周五为交易日
            if current_date.weekday() < 5:
                trading_days += 1
            current_date += timedelta(days=1)

        return trading_days

    def generate_completion_plan(self, analysis_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """根据分析结果生成数据补全计划"""
        plan = {
            'total_files': len(analysis_results),
            'need_update': [],
            'need_complete': [],
            'need_reacquire': [],
            'good_files': [],
            'actions': []
        }

        for result in analysis_results:
            file_info = result['file_info']
            analysis = result['analysis']

            if analysis['status'] in ['empty', 'invalid', 'error']:
                plan['need_reacquire'].append(file_info)
                plan['actions'].append({
                    'action': 'reacquire',
                    'file': file_info['file_name'],
                    'reason': analysis.get('issue', 'Unknown'),
                    'priority': 'high'
                })

            elif analysis.get('freshness') == 'outdated':
                plan['need_update'].append(file_info)
                plan['actions'].append({
                    'action': 'update',
                    'file': file_info['file_name'],
                    'reason': f"数据过期 {analysis['data_age_days']} 天",
                    'priority': 'high'
                })

            elif analysis.get('completeness') in ['poor', 'fair']:
                plan['need_complete'].append(file_info)
                plan['actions'].append({
                    'action': 'complete',
                    'file': file_info['file_name'],
                    'reason': f"数据完整度 {analysis.get('completeness_ratio', 0):.1%}",
                    'priority': 'medium'
                })

            elif analysis.get('freshness') == 'stale':
                plan['need_update'].append(file_info)
                plan['actions'].append({
                    'action': 'update',
                    'file': file_info['file_name'],
                    'reason': f"数据较旧 {analysis['data_age_days']} 天",
                    'priority': 'medium'
                })

            else:
                plan['good_files'].append(file_info)

        return plan

    def check_all_files(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """检查所有数据文件并生成补全计划"""
        print(f"🔍 开始扫描数据目录: {self.data_dir.absolute()}")

        # 扫描文件
        files_info = self.scan_data_files()
        print(f"📁 发现 {len(files_info)} 个数据文件")

        if not files_info:
            print("⚠️ 未发现任何数据文件")
            return [], {'total_files': 0, 'actions': []}

        # 分析每个文件
        analysis_results = []
        for i, file_info in enumerate(files_info, 1):
            print(f"  📊 [{i}/{len(files_info)}] 分析文件: {file_info['file_name']}")
            analysis = self.analyze_data_file(file_info)
            analysis_results.append({
                'file_info': file_info,
                'analysis': analysis
            })

        # 生成补全计划
        plan = self.generate_completion_plan(analysis_results)

        return analysis_results, plan

    def print_analysis_report(self, analysis_results: List[Dict[str, Any]], plan: Dict[str, Any]):
        """打印数据完整性分析报告"""
        print(f"\n{'=' * 80}")
        print(f"📊 数据完整性检查报告")
        print(f"{'=' * 80}")

        if not analysis_results:
            print("❌ 未发现任何数据文件")
            print("💡 建议：使用数据采集脚本获取股票数据")
            return

        print(f"📁 总文件数: {plan['total_files']}")
        print(f"✅ 状态良好: {len(plan['good_files'])} 个")
        print(f"🔄 需要更新: {len(plan['need_update'])} 个")
        print(f"📈 需要补全: {len(plan['need_complete'])} 个")
        print(f"❌ 需要重新采集: {len(plan['need_reacquire'])} 个")

        # 详细文件状态
        print(f"\n📋 详细分析结果:")
        print(f"{'序号':<4} {'文件名':<30} {'状态':<12} {'记录数':<8} {'数据范围':<20} {'建议':<20}")
        print(f"{'-' * 100}")

        for i, result in enumerate(analysis_results, 1):
            file_info = result['file_info']
            analysis = result['analysis']

            status = analysis['status']
            records = analysis.get('records', 0)

            # 状态显示
            if status == 'valid':
                if analysis.get('freshness') == 'fresh' and analysis.get('completeness') == 'excellent':
                    status_display = "✅ 优秀"
                elif analysis.get('freshness') in ['stale', 'outdated'] or analysis.get('completeness') in ['good',
                                                                                                            'fair']:
                    status_display = "⚠️ 需要处理"
                else:
                    status_display = "❌ 问题较多"
            else:
                status_display = "❌ 错误"

            # 数据范围
            if 'start_time' in analysis and 'end_time' in analysis:
                date_range = f"{analysis['start_time'].strftime('%m-%d')} ~ {analysis['end_time'].strftime('%m-%d')}"
            else:
                date_range = "无效"

            # 主要建议
            recommendations = analysis.get('recommendations', [])
            main_recommendation = recommendations[0] if recommendations else "无"
            if len(main_recommendation) > 18:
                main_recommendation = main_recommendation[:15] + "..."

            print(
                f"{i:<4} {file_info['file_name']:<30} {status_display:<12} {records:<8} {date_range:<20} {main_recommendation:<20}")

        # 操作建议
        if plan['actions']:
            print(f"\n🔧 建议执行的操作:")

            # 按优先级分组
            high_priority = [a for a in plan['actions'] if a['priority'] == 'high']
            medium_priority = [a for a in plan['actions'] if a['priority'] == 'medium']

            if high_priority:
                print(f"\n🚨 高优先级操作 ({len(high_priority)} 个):")
                for i, action in enumerate(high_priority, 1):
                    print(f"  {i}. {action['action']} - {action['file']} ({action['reason']})")

            if medium_priority:
                print(f"\n⚠️ 中优先级操作 ({len(medium_priority)} 个):")
                for i, action in enumerate(medium_priority, 1):
                    print(f"  {i}. {action['action']} - {action['file']} ({action['reason']})")
        else:
            print(f"\n🎉 所有数据文件状态良好，无需额外操作!")

        print(f"\n{'=' * 80}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='数据完整性检查工具')
    parser.add_argument('--data-dir', default='data', help='数据目录路径')
    parser.add_argument('--export-report', help='导出报告到指定文件')

    args = parser.parse_args()

    print("🔍 数据完整性检查工具")
    print(f"📁 数据目录: {args.data_dir}")

    checker = DataCompletenessChecker(args.data_dir)
    analysis_results, plan = checker.check_all_files()

    # 显示报告
    checker.print_analysis_report(analysis_results, plan)

    # 导出报告（可选）
    if args.export_report:
        try:
            import json
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'data_dir': args.data_dir,
                'analysis_results': analysis_results,
                'completion_plan': plan
            }

            with open(args.export_report, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)

            print(f"📄 报告已导出到: {args.export_report}")
        except Exception as e:
            print(f"❌ 报告导出失败: {e}")

    return 0 if len(plan['actions']) == 0 else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
