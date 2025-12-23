#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发优化功能测试脚本
验证异步采集、评分、批处理的正确性和性能
"""

import asyncio
import time
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from analysis.async_data_collector import batch_collect_data, collect_batch_data_sync
from analysis.async_opportunity_scorer import batch_score_stocks, batch_score_stocks_sync
from analysis.batch_processor import (
    process_stocks_batch,
    process_stocks_batch_sync,
    BatchProcessor,
)


def print_section(title: str):
    """打印分隔标题"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


async def test_async_data_collection():
    """测试异步数据采集"""
    print_section("测试1：异步数据采集")

    test_stocks = ["688343", "000001", "600519"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始异步采集综合数据...")

    start = time.time()

    try:
        success_data, failed = await batch_collect_data(
            test_stocks, data_type="comprehensive", max_concurrent=2, timeout_per_stock=20
        )

        elapsed = time.time() - start

        print(f"\n✅ 采集完成:")
        print(f"  成功: {len(success_data)}/{len(test_stocks)}")
        print(f"  失败: {len(failed)}")
        print(f"  耗时: {elapsed:.2f}s")

        if success_data:
            for code in list(success_data.keys())[:1]:
                data = success_data[code]
                print(f"\n  示例数据 ({code}):")
                print(f"    - fundamental_data: {len(data.get('fundamental_data', {}))} 字段")
                print(f"    - sentiment_data: {len(data.get('sentiment_data', {}))} 字段")

        return True

    except Exception as e:
        print(f"❌ 采集失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_sync_data_collection():
    """测试同步数据采集包装"""
    print_section("测试2：同步数据采集包装")

    test_stocks = ["688343", "000001"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始同步采集基础数据...")

    start = time.time()

    try:
        success_data, failed = collect_batch_data_sync(
            test_stocks, data_type="fundamental", max_concurrent=2, timeout_per_stock=15
        )

        elapsed = time.time() - start

        print(f"\n✅ 采集完成:")
        print(f"  成功: {len(success_data)}/{len(test_stocks)}")
        print(f"  失败: {len(failed)}")
        print(f"  耗时: {elapsed:.2f}s")

        return True

    except Exception as e:
        print(f"❌ 采集失败: {str(e)}")
        return False


async def test_async_scoring():
    """测试异步评分"""
    print_section("测试3：异步打分系统")

    test_stocks = ["688343", "000001", "600519", "300750"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始并发评分...")

    start = time.time()

    try:
        passed, failed, errors = await batch_score_stocks(
            test_stocks,
            max_concurrent=2,
            timeout_per_stock=10,
            use_v4_1=False,
            filter_strategy="balanced",
        )

        elapsed = time.time() - start

        print(f"\n✅ 评分完成:")
        print(f"  通过: {len(passed)}/{len(test_stocks)}")
        print(f"  未通过: {len(failed)}")
        print(f"  异常: {len(errors)}")
        print(f"  耗时: {elapsed:.2f}s")

        if passed:
            for code in list(passed.keys())[:1]:
                score_data = passed[code]
                print(f"\n  示例评分 ({code}):")
                print(f"    - 评级: {score_data.get('rating')}")
                print(f"    - 综合评分: {score_data.get('total_score')}")
                print(f"    - 建议: {score_data.get('recommendation')}")

        return True

    except Exception as e:
        print(f"❌ 评分失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_sync_scoring():
    """测试同步评分包装"""
    print_section("测试4：同步打分包装")

    test_stocks = ["688343", "000001"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始同步评分...")

    start = time.time()

    try:
        passed, failed, errors = batch_score_stocks_sync(
            test_stocks,
            max_concurrent=2,
            timeout_per_stock=8,
            use_v4_1=False,
            filter_strategy="balanced",
        )

        elapsed = time.time() - start

        print(f"\n✅ 评分完成:")
        print(f"  通过: {len(passed)}/{len(test_stocks)}")
        print(f"  未通过: {len(failed)}")
        print(f"  异常: {len(errors)}")
        print(f"  耗时: {elapsed:.2f}s")

        return True

    except Exception as e:
        print(f"❌ 评分失败: {str(e)}")
        return False


async def test_batch_processor():
    """测试批处理管理器"""
    print_section("测试5：批处理管理器")

    test_stocks = ["688343", "000001", "600519"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始批处理...")

    start = time.time()

    try:
        processor = BatchProcessor(
            max_concurrent=2,
            collection_timeout=20,
            scoring_timeout=8,
            enable_progress_bar=True,
        )

        result_df, details, stats = await processor.process_batch(
            test_stocks,
            data_types=["comprehensive"],
            filter_strategy="balanced",
            skip_scoring=False,
        )

        elapsed = time.time() - start

        print(f"\n✅ 批处理完成:")
        print(f"  耗时: {elapsed:.2f}s")

        if not result_df.empty:
            print(f"\n📊 结果汇总:")
            print(result_df.to_string(index=False))
        else:
            print(f"\n⚠️  没有通过过滤的股票")

        return True

    except Exception as e:
        print(f"❌ 批处理失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_sync_batch_processor():
    """测试同步批处理包装"""
    print_section("测试6：同步批处理包装")

    test_stocks = ["688343", "000001"]

    print(f"📊 测试股票: {', '.join(test_stocks)}")
    print(f"🔄 开始同步批处理...")

    start = time.time()

    try:
        result_df, details, stats = process_stocks_batch_sync(
            test_stocks,
            data_types=["comprehensive"],
            filter_strategy="balanced",
            max_concurrent=2,
            collection_timeout=15,
            scoring_timeout=8,
        )

        elapsed = time.time() - start

        print(f"\n✅ 批处理完成:")
        print(f"  耗时: {elapsed:.2f}s")

        if not result_df.empty:
            print(f"\n📊 结果汇总:")
            print(result_df.to_string(index=False))
        else:
            print(f"\n⚠️  没有通过过滤的股票")

        return True

    except Exception as e:
        print(f"❌ 批处理失败: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n" + "=" * 70)
    print("  并发优化功能完整测试")
    print("=" * 70)

    results = {}

    # 测试1：异步数据采集
    print("\n⏳ 运行测试 1/6...")
    results["test1_async_collection"] = await test_async_data_collection()

    # 测试2：同步数据采集
    print("\n⏳ 运行测试 2/6...")
    results["test2_sync_collection"] = test_sync_data_collection()

    # 测试3：异步评分
    print("\n⏳ 运行测试 3/6...")
    results["test3_async_scoring"] = await test_async_scoring()

    # 测试4：同步评分
    print("\n⏳ 运行测试 4/6...")
    results["test4_sync_scoring"] = test_sync_scoring()

    # 测试5：异步批处理
    print("\n⏳ 运行测试 5/6...")
    results["test5_batch_processor"] = await test_batch_processor()

    # 测试6：同步批处理
    print("\n⏳ 运行测试 6/6...")
    results["test6_sync_batch"] = test_sync_batch_processor()

    # 总结
    print_section("测试总结")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\n📊 测试结果:")
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {name}: {status}")

    print(f"\n📈 总体: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️  {total - passed} 个测试失败")


if __name__ == "__main__":
    print("\n🚀 开始并发优化功能测试...\n")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  测试被中断")
        sys.exit(1)
