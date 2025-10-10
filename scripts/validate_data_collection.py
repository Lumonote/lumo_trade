#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据采集验证脚本
验证和确保所有采集的数据都正确保存到data目录
"""

import os
import sys
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import List, Dict, Any, Optional

# 添加项目根目录到路径
sys.path.append(str(Path(__file__).parent.parent))

try:
    from scripts.enhanced_fetch_data import EnhancedDataFetcher

    ENHANCED_FETCHER_AVAILABLE = True
except ImportError:
    ENHANCED_FETCHER_AVAILABLE = False
    print("❌ 增强版数据获取器不可用")


class DataCollectionValidator:
    """数据采集验证器"""

    def __init__(self, data_dir: str = 'data'):
        """初始化验证器"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.fetcher = EnhancedDataFetcher() if ENHANCED_FETCHER_AVAILABLE else None

        print(f"📁 数据目录: {self.data_dir.absolute()}")

    def validate_data_directory(self) -> Dict[str, Any]:
        """验证数据目录状态"""
        stats = {
            'directory_exists': self.data_dir.exists(),
            'directory_writable': os.access(self.data_dir, os.W_OK),
            'file_count': 0,
            'total_size': 0,
            'files': []
        }

        if stats['directory_exists']:
            csv_files = list(self.data_dir.glob('*.csv'))
            stats['file_count'] = len(csv_files)

            for file_path in csv_files:
                try:
                    file_size = file_path.stat().st_size
                    stats['total_size'] += file_size

                    # 尝试读取文件验证数据完整性
                    df = pd.read_csv(file_path)

                    file_info = {
                        'name': file_path.name,
                        'size': file_size,
                        'records': len(df),
                        'valid': True,
                        'columns': list(df.columns)
                    }

                    # 检查必需列
                    required_cols = ['timestamps', 'open', 'high', 'low', 'close']
                    missing_cols = [col for col in required_cols if col not in df.columns]
                    if missing_cols:
                        file_info['valid'] = False
                        file_info['missing_columns'] = missing_cols

                    stats['files'].append(file_info)

                except Exception as e:
                    stats['files'].append({
                        'name': file_path.name,
                        'size': file_path.stat().st_size,
                        'valid': False,
                        'error': str(e)
                    })

        return stats

    async def test_data_collection_and_saving(self, symbol: str = '300622',
                                              period: str = '5m',
                                              days: int = 30) -> Dict[str, Any]:
        """测试数据采集和保存"""
        if not self.fetcher:
            return {'success': False, 'error': '增强版数据获取器不可用'}

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        print(f"🔄 测试数据采集: {symbol}")
        print(f"📅 时间范围: {start_date} 到 {end_date}")
        print(f"⏰ 周期: {period}")

        try:
            # 采集前检查文件数量
            before_files = len(list(self.data_dir.glob('*.csv')))

            # 执行数据采集
            df = await self.fetcher.fetch_data(
                symbol=symbol,
                source='auto',
                period=period,
                start_date=start_date,
                end_date=end_date,
                target_days=days
            )

            result = {
                'success': df is not None and not df.empty,
                'records_collected': len(df) if df is not None else 0,
                'before_files': before_files
            }

            if result['success']:
                # 保存数据到data目录
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{symbol}_{period}_validation_{timestamp}.csv"
                filepath = self.data_dir / filename

                try:
                    df.to_csv(filepath, index=False)

                    # 验证保存结果
                    if filepath.exists():
                        file_size = filepath.stat().st_size
                        result['file_saved'] = True
                        result['file_path'] = str(filepath)
                        result['file_size'] = file_size

                        # 验证数据完整性
                        verification_df = pd.read_csv(filepath)
                        result['verification_records'] = len(verification_df)
                        result['data_integrity'] = len(verification_df) == len(df)

                        print(f"✅ 数据已保存并验证: {filepath}")
                        print(f"📊 记录数: {result['records_collected']}")
                        print(f"💾 文件大小: {file_size:,} 字节")
                        print(f"🔍 数据完整性: {'通过' if result['data_integrity'] else '失败'}")

                    else:
                        result['file_saved'] = False
                        result['error'] = '文件保存失败'

                except Exception as save_error:
                    result['file_saved'] = False
                    result['error'] = f'保存异常: {save_error}'
            else:
                result['error'] = '数据采集失败'

            # 采集后检查文件数量
            after_files = len(list(self.data_dir.glob('*.csv')))
            result['after_files'] = after_files
            result['files_added'] = after_files - before_files

            return result

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def print_validation_report(self, dir_stats: Dict[str, Any],
                                test_result: Dict[str, Any] = None):
        """打印验证报告"""
        print(f"\n{'=' * 60}")
        print(f"📋 数据采集验证报告")
        print(f"{'=' * 60}")

        # 目录状态
        print(f"📁 数据目录状态:")
        print(f"  - 目录存在: {'✅' if dir_stats['directory_exists'] else '❌'}")
        print(f"  - 目录可写: {'✅' if dir_stats['directory_writable'] else '❌'}")
        print(f"  - 文件数量: {dir_stats['file_count']}")
        print(f"  - 总大小: {dir_stats['total_size']:,} 字节")

        # 文件详情
        if dir_stats['files']:
            print(f"\n📄 现有数据文件:")
            for i, file_info in enumerate(dir_stats['files'], 1):
                status = '✅' if file_info.get('valid', False) else '❌'
                print(f"  {i:2}. {status} {file_info['name']}")
                print(f"      大小: {file_info['size']:,} 字节")
                if 'records' in file_info:
                    print(f"      记录: {file_info['records']:,} 条")
                if 'missing_columns' in file_info:
                    print(f"      缺失列: {file_info['missing_columns']}")
                if 'error' in file_info:
                    print(f"      错误: {file_info['error']}")

        # 测试结果
        if test_result:
            print(f"\n🧪 数据采集测试:")
            print(f"  - 采集成功: {'✅' if test_result['success'] else '❌'}")
            if test_result['success']:
                print(f"  - 采集记录: {test_result['records_collected']:,} 条")
                print(f"  - 文件保存: {'✅' if test_result.get('file_saved', False) else '❌'}")
                if test_result.get('file_saved'):
                    print(f"  - 保存路径: {test_result.get('file_path', 'N/A')}")
                    print(f"  - 文件大小: {test_result.get('file_size', 0):,} 字节")
                    print(f"  - 数据完整性: {'✅' if test_result.get('data_integrity', False) else '❌'}")
                print(f"  - 新增文件: {test_result.get('files_added', 0)} 个")
            else:
                print(f"  - 错误信息: {test_result.get('error', 'Unknown')}")

        print(f"\n💡 建议:")
        if not dir_stats['directory_exists']:
            print(f"  - 创建数据目录: mkdir -p {self.data_dir}")
        elif not dir_stats['directory_writable']:
            print(f"  - 检查目录权限: chmod 755 {self.data_dir}")
        elif dir_stats['file_count'] == 0:
            print(f"  - 运行数据采集脚本获取数据")
        else:
            print(f"  - 数据目录状态正常")

        print(f"{'=' * 60}")


async def main():
    """主函数"""
    print(f"🚀 数据采集验证器启动")

    # 创建验证器
    validator = DataCollectionValidator()

    # 验证数据目录
    print(f"\n🔍 检查数据目录状态...")
    dir_stats = validator.validate_data_directory()

    # 测试数据采集和保存
    print(f"\n🧪 测试数据采集和保存...")
    test_result = await validator.test_data_collection_and_saving()

    # 打印验证报告
    validator.print_validation_report(dir_stats, test_result)

    # 返回状态码
    if test_result and test_result['success']:
        print(f"\n🎉 验证通过！数据采集和保存功能正常")
        return 0
    else:
        print(f"\n❌ 验证失败！请检查配置和权限")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
