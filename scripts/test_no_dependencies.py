#!/usr/bin/env python3
"""
测试脚本：验证在缺少 pandas 和 tushare 依赖时的行为
"""
import sys
from pathlib import Path

# 模拟缺少依赖的情况
sys.modules['pandas'] = None
sys.modules['tushare'] = None

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

try:
    from scripts.fetch_data import MultiSourceDataFetcher

    print("✅ 成功导入 MultiSourceDataFetcher (无依赖模式)")

    # 尝试初始化
    try:
        fetcher = MultiSourceDataFetcher()
        print("✅ MultiSourceDataFetcher 初始化成功")
        print(f"📊 可用数据源: {fetcher.get_available_sources()}")
    except Exception as e:
        print(f"❌ MultiSourceDataFetcher 初始化失败: {e}")

except ImportError as e:
    print(f"❌ 导入失败: {e}")
