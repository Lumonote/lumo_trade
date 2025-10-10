#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos Tushare配置设置工具
帮助用户快速配置Tushare API Token和相关设置
"""

import os
import sys
import json
import getpass
from pathlib import Path
from typing import Dict, Any


def get_project_root() -> Path:
    """获取项目根目录"""
    current = Path(__file__).parent
    while current != current.parent:
        if (current / 'README.md').exists() or (current / 'requirements.txt').exists():
            return current
        current = current.parent
    return Path(__file__).parent.parent


def load_config(config_path: str) -> Dict[str, Any]:
    """加载配置文件"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ 配置文件不存在: {config_path}")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ 配置文件格式错误: {e}")
        return {}


def save_config(config: Dict[str, Any], config_path: str) -> bool:
    """保存配置文件"""
    try:
        # 确保目录存在
        Path(config_path).parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ 保存配置失败: {e}")
        return False


def test_tushare_connection(token: str) -> bool:
    """测试Tushare连接"""
    try:
        import tushare as ts

        # 设置token
        ts.set_token(token)
        pro = ts.pro_api()

        # 测试获取基础信息
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')

        if df is not None and not df.empty:
            print(f"✅ Tushare连接成功! 获取到 {len(df)} 只股票信息")
            return True
        else:
            print("❌ Tushare连接失败: 未获取到数据")
            return False

    except ImportError:
        print("❌ 未安装tushare包，请先运行: pip install tushare")
        return False
    except Exception as e:
        print(f"❌ Tushare连接失败: {e}")
        return False


def setup_tushare_token():
    """设置Tushare Token"""
    print("🔧 Tushare API Token 配置")
    print("=" * 50)

    # 获取项目根目录和配置文件路径
    project_root = get_project_root()
    config_path = project_root / 'config' / 'tushare_config.json'

    print(f"📁 项目根目录: {project_root}")
    print(f"📄 配置文件: {config_path}")

    # 加载现有配置
    config = load_config(str(config_path))

    # 检查是否已有token
    current_token = config.get('tushare', {}).get('token', '')
    if current_token and current_token != 'your_tushare_token_here':
        print(f"\n🔍 发现现有Token: {current_token[:10]}...{current_token[-4:]}")

        # 测试现有token
        print("\n🧪 测试现有Token连接...")
        if test_tushare_connection(current_token):
            choice = input("\n✅ 现有Token工作正常，是否要更换? (y/N): ").strip().lower()
            if choice not in ['y', 'yes']:
                print("✅ 保持现有配置")
                return True

    # 获取新token
    print("\n📝 请输入您的Tushare API Token:")
    print("💡 如果还没有Token，请访问: https://tushare.pro/register")
    print("💡 注册后在用户中心获取Token")

    while True:
        token = getpass.getpass("🔑 Token (输入时不显示): ").strip()

        if not token:
            print("❌ Token不能为空")
            continue

        if len(token) < 20:
            print("❌ Token长度似乎不正确，请检查")
            continue

        # 测试token
        print("\n🧪 测试Token连接...")
        if test_tushare_connection(token):
            # 保存到配置
            if 'tushare' not in config:
                config['tushare'] = {}
            config['tushare']['token'] = token

            if save_config(config, str(config_path)):
                print(f"\n✅ Token配置成功并保存到: {config_path}")
                return True
            else:
                print("\n❌ 保存配置失败")
                return False
        else:
            retry = input("\n❌ Token测试失败，是否重新输入? (Y/n): ").strip().lower()
            if retry in ['n', 'no']:
                return False


def setup_data_settings():
    """配置数据设置"""
    print("\n📊 数据获取设置配置")
    print("=" * 50)

    project_root = get_project_root()
    config_path = project_root / 'config' / 'tushare_config.json'

    config = load_config(str(config_path))

    # 数据目录设置
    current_dir = config.get('data_settings', {}).get('output_dir', './data/')
    print(f"\n📁 当前数据目录: {current_dir}")

    new_dir = input(f"📁 新数据目录 (回车保持 '{current_dir}'): ").strip()
    if new_dir:
        if 'data_settings' not in config:
            config['data_settings'] = {}
        config['data_settings']['output_dir'] = new_dir

        # 创建目录
        try:
            Path(project_root / new_dir).mkdir(parents=True, exist_ok=True)
            print(f"✅ 数据目录已创建: {project_root / new_dir}")
        except Exception as e:
            print(f"⚠️  创建目录失败: {e}")

    # 默认获取参数
    print("\n⚙️  默认获取参数设置:")

    defaults = config.get('default_params', {})

    # 频率设置
    current_freq = defaults.get('freq', '5min')
    print(f"\n⏱️  当前默认频率: {current_freq}")
    print("可选: 1min, 5min, 15min, 30min, 60min, D")
    new_freq = input(f"⏱️  新默认频率 (回车保持 '{current_freq}'): ").strip()
    if new_freq and new_freq in ['1min', '5min', '15min', '30min', '60min', 'D']:
        if 'default_params' not in config:
            config['default_params'] = {}
        config['default_params']['freq'] = new_freq

    # 复权设置
    current_adj = defaults.get('adj', 'qfq')
    print(f"\n📈 当前默认复权: {current_adj}")
    print("可选: qfq (前复权), hfq (后复权), None (不复权)")
    new_adj = input(f"📈 新默认复权 (回车保持 '{current_adj}'): ").strip()
    if new_adj and new_adj in ['qfq', 'hfq', 'None']:
        if 'default_params' not in config:
            config['default_params'] = {}
        config['default_params']['adj'] = None if new_adj == 'None' else new_adj

    # 保存配置
    if save_config(config, str(config_path)):
        print(f"\n✅ 数据设置配置成功")
        return True
    else:
        print("\n❌ 保存配置失败")
        return False


def setup_stock_lists():
    """配置股票列表"""
    print("\n📋 股票列表配置")
    print("=" * 50)

    project_root = get_project_root()
    config_path = project_root / 'config' / 'tushare_config.json'

    config = load_config(str(config_path))

    if 'stock_lists' not in config:
        config['stock_lists'] = {}

    # 显示当前列表
    current_stocks = config['stock_lists'].get('popular_stocks', [])
    print(f"\n📊 当前热门股票列表 ({len(current_stocks)} 只):")
    if current_stocks:
        for i, stock in enumerate(current_stocks, 1):
            print(f"  {i:2d}. {stock}")
    else:
        print("  (空)")

    # 操作选择
    print("\n🔧 操作选项:")
    print("  1. 添加股票")
    print("  2. 删除股票")
    print("  3. 清空列表")
    print("  4. 使用预设列表")
    print("  0. 跳过")

    choice = input("\n选择操作 (0-4): ").strip()

    if choice == '1':
        # 添加股票
        print("\n➕ 添加股票 (输入股票代码，用空格或逗号分隔):")
        new_stocks = input("股票代码: ").strip()
        if new_stocks:
            # 解析输入
            import re
            stocks = re.split(r'[,\s]+', new_stocks)
            stocks = [s.strip() for s in stocks if s.strip()]

            # 添加到列表
            for stock in stocks:
                if stock not in current_stocks:
                    current_stocks.append(stock)
                    print(f"  ✅ 添加: {stock}")
                else:
                    print(f"  ⚠️  已存在: {stock}")

            config['stock_lists']['popular_stocks'] = current_stocks

    elif choice == '2':
        # 删除股票
        if not current_stocks:
            print("\n❌ 列表为空，无法删除")
        else:
            print("\n➖ 删除股票 (输入序号或股票代码):")
            to_remove = input("要删除的股票: ").strip()

            if to_remove.isdigit():
                # 按序号删除
                idx = int(to_remove) - 1
                if 0 <= idx < len(current_stocks):
                    removed = current_stocks.pop(idx)
                    print(f"  ✅ 删除: {removed}")
                    config['stock_lists']['popular_stocks'] = current_stocks
                else:
                    print(f"  ❌ 无效序号: {to_remove}")
            else:
                # 按代码删除
                if to_remove in current_stocks:
                    current_stocks.remove(to_remove)
                    print(f"  ✅ 删除: {to_remove}")
                    config['stock_lists']['popular_stocks'] = current_stocks
                else:
                    print(f"  ❌ 未找到: {to_remove}")

    elif choice == '3':
        # 清空列表
        confirm = input("\n⚠️  确认清空所有股票? (y/N): ").strip().lower()
        if confirm in ['y', 'yes']:
            config['stock_lists']['popular_stocks'] = []
            print("  ✅ 列表已清空")

    elif choice == '4':
        # 使用预设列表
        presets = {
            '1': {
                'name': '沪深300成分股 (部分)',
                'stocks': ['000001.SZ', '000002.SZ', '000858.SZ', '000895.SZ', '600000.SH',
                           '600036.SH', '600519.SH', '600887.SH', '000858.SZ', '002415.SZ']
            },
            '2': {
                'name': '科技龙头股',
                'stocks': ['000002.SZ', '002415.SZ', '300059.SZ', '300750.SZ', '600570.SH',
                           '002230.SZ', '000725.SZ', '002241.SZ', '300496.SZ', '688981.SH']
            },
            '3': {
                'name': '银行股',
                'stocks': ['600000.SH', '600036.SH', '601166.SH', '000001.SZ', '002142.SZ',
                           '600015.SH', '601328.SH', '601398.SH', '601939.SH', '600016.SH']
            }
        }

        print("\n📋 预设列表:")
        for key, preset in presets.items():
            print(f"  {key}. {preset['name']} ({len(preset['stocks'])} 只)")

        preset_choice = input("\n选择预设 (1-3): ").strip()
        if preset_choice in presets:
            preset = presets[preset_choice]
            config['stock_lists']['popular_stocks'] = preset['stocks']
            print(f"  ✅ 已设置为: {preset['name']}")

    # 保存配置
    if choice in ['1', '2', '3', '4']:
        if save_config(config, str(config_path)):
            print(f"\n✅ 股票列表配置成功")
            return True
        else:
            print("\n❌ 保存配置失败")
            return False

    return True


def show_current_config():
    """显示当前配置"""
    print("\n📋 当前配置信息")
    print("=" * 50)

    project_root = get_project_root()
    config_path = project_root / 'config' / 'tushare_config.json'

    config = load_config(str(config_path))

    if not config:
        print("❌ 未找到配置文件")
        return

    # Tushare设置
    tushare_config = config.get('tushare', {})
    token = tushare_config.get('token', '')
    if token and token != 'your_tushare_token_here':
        print(f"🔑 Tushare Token: {token[:10]}...{token[-4:]} (已配置)")
    else:
        print("🔑 Tushare Token: 未配置")

    # 数据设置
    data_settings = config.get('data_settings', {})
    print(f"📁 数据目录: {data_settings.get('output_dir', './data/')}")
    print(f"📄 文件格式: {data_settings.get('file_format', 'csv')}")

    # 默认参数
    defaults = config.get('default_params', {})
    print(f"⏱️  默认频率: {defaults.get('freq', '5min')}")
    print(f"📈 默认复权: {defaults.get('adj', 'qfq')}")

    # 股票列表
    stock_lists = config.get('stock_lists', {})
    popular_stocks = stock_lists.get('popular_stocks', [])
    print(f"📊 热门股票: {len(popular_stocks)} 只")
    if popular_stocks:
        print(f"   {', '.join(popular_stocks[:5])}{'...' if len(popular_stocks) > 5 else ''}")


def main():
    """主函数"""
    print("🚀 Kronos Tushare配置工具")
    print("=" * 50)

    while True:
        print("\n🔧 配置选项:")
        print("  1. 设置Tushare API Token")
        print("  2. 配置数据获取设置")
        print("  3. 管理股票列表")
        print("  4. 查看当前配置")
        print("  0. 退出")

        choice = input("\n请选择 (0-4): ").strip()

        if choice == '1':
            setup_tushare_token()
        elif choice == '2':
            setup_data_settings()
        elif choice == '3':
            setup_stock_lists()
        elif choice == '4':
            show_current_config()
        elif choice == '0':
            print("\n👋 配置完成，感谢使用!")
            break
        else:
            print("\n❌ 无效选择，请重试")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        sys.exit(1)
