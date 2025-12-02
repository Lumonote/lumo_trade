#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.crawler import CrawlerManager


async def test_crawler():
    """简单测试爬虫功能"""
    print("🚀 开始测试爬虫功能...")

    try:
        crawler_manager = CrawlerManager()
        print("✅ 爬虫管理器创建成功")

        available_sources = crawler_manager.get_available_sources()
        print(f"📊 可用数据源: {available_sources}")

        if not available_sources:
            print("❌ 没有可用的数据源")
            return

        print("\n🔧 检查域映射配置:")
        for src in ['eastmoney', 'tonghuashun', 'xueqiu']:
            for act in ['realtime', 'kline', 'minute']:
                dom = crawler_manager._get_domain_for_source(src, act)
                print(f"- {src}:{act} -> {dom}")

        test_symbol = "000001"
        print(f"\n📈 测试获取股票 {test_symbol} 的K线数据...")

        kline_data = await crawler_manager.get_kline_data(test_symbol, period='5')

        if kline_data:
            print(f"✅ 成功获取K线数据，数据量: {len(kline_data)}")
            print(f"📊 第一条数据: {kline_data[0]}")
        else:
            print("❌ 获取K线数据失败")

    except Exception as e:
        print(f"❌ 测试过程中出现异常: {e}")
        import traceback
        traceback.print_exc()

    print("\n🏁 测试完成")


if __name__ == "__main__":
    asyncio.run(test_crawler())
