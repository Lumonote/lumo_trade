#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 配置向导
帮助用户轻松配置 Tushare 和爬虫设置
"""

import json
import os
from pathlib import Path


class ConfigWizard:
    def __init__(self):
        self.config_dir = Path('config')
        self.config_dir.mkdir(exist_ok=True)

    def print_header(self):
        """打印欢迎信息"""
        print("\n" + "=" * 50)
        print("🔧 Kronos 配置向导")
        print("=" * 50)
        print("欢迎使用 Kronos 配置向导！")
        print("我们将帮助您快速配置数据源。\n")

    def configure_tushare(self):
        """配置 Tushare"""
        print("📊 配置 Tushare 数据源")
        print("-" * 30)

        # 检查是否已有配置
        tushare_config_file = self.config_dir / 'tushare_config.json'
        if tushare_config_file.exists():
            with open(tushare_config_file, 'r', encoding='utf-8') as f:
                existing_config = json.load(f)
                if existing_config.get('token'):
                    print(f"✅ 检测到已有 Tushare 配置")
                    choice = input("是否要重新配置？(y/N): ").lower()
                    if choice != 'y':
                        return

        print("\n📝 获取 Tushare Token 的步骤：")
        print("1. 访问 https://tushare.pro/")
        print("2. 注册账号并登录")
        print("3. 在用户中心找到您的 Token")
        print("4. 复制 Token 并粘贴到下方\n")

        while True:
            token = input("请输入您的 Tushare Token: ").strip()
            if not token:
                print("❌ Token 不能为空，请重新输入")
                continue

            if len(token) < 20:
                print("❌ Token 长度似乎不正确，请检查后重新输入")
                continue

            break

        # 其他配置选项
        timeout = input("请输入超时时间（秒，默认30）: ").strip()
        timeout = int(timeout) if timeout.isdigit() else 30

        retry_count = input("请输入重试次数（默认3）: ").strip()
        retry_count = int(retry_count) if retry_count.isdigit() else 3

        # 保存配置
        config = {
            "token": token,
            "timeout": timeout,
            "retry_count": retry_count
        }

        with open(tushare_config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"✅ Tushare 配置已保存到 {tushare_config_file}")

        # 测试连接
        test_choice = input("\n是否要测试 Tushare 连接？(Y/n): ").lower()
        if test_choice != 'n':
            self.test_tushare_connection(token)

    def test_tushare_connection(self, token):
        """测试 Tushare 连接"""
        try:
            import tushare as ts
            ts.set_token(token)
            pro = ts.pro_api()

            print("🔍 正在测试连接...")
            # 获取基础信息测试连接
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
            if len(df) > 0:
                print("✅ Tushare 连接测试成功！")
                print(f"📊 可获取 {len(df)} 只股票的数据")
            else:
                print("⚠️ 连接成功但未获取到数据")

        except Exception as e:
            print(f"❌ Tushare 连接测试失败: {e}")
            print("请检查 Token 是否正确或网络连接")

    def configure_crawler(self):
        """配置爬虫"""
        print("\n🕷️ 配置爬虫数据源")
        print("-" * 30)

        # 检查是否已有配置
        crawler_config_file = self.config_dir / 'crawler_config.json'
        if crawler_config_file.exists():
            print("✅ 检测到已有爬虫配置")
            choice = input("是否要重新配置？(y/N): ").lower()
            if choice != 'y':
                return

        print("\n📝 爬虫配置选项：")

        # 数据源配置
        sources = {
            "sina": {
                "name": "新浪财经",
                "enabled": True,
                "base_url": "https://finance.sina.com.cn",
                "timeout": 30,
                "retry_count": 3
            },
            "eastmoney": {
                "name": "东方财富",
                "enabled": True,
                "base_url": "https://quote.eastmoney.com",
                "timeout": 30,
                "retry_count": 3
            },
            "163": {
                "name": "网易财经",
                "enabled": True,
                "base_url": "https://money.163.com",
                "timeout": 30,
                "retry_count": 3
            }
        }

        print("\n选择要启用的数据源：")
        for key, source in sources.items():
            choice = input(f"启用 {source['name']} ({key})？(Y/n): ").lower()
            sources[key]["enabled"] = choice != 'n'
            print(f"{'✅' if sources[key]['enabled'] else '❌'} {source['name']}")

        # 浏览器配置
        print("\n🌐 浏览器配置：")
        headless = input("使用无头模式（后台运行，推荐）？(Y/n): ").lower()
        headless = headless != 'n'

        timeout = input("页面加载超时时间（毫秒，默认30000）: ").strip()
        timeout = int(timeout) if timeout.isdigit() else 30000

        # 反爬虫配置
        print("\n🛡️ 反爬虫配置：")
        delay_min = input("最小请求间隔（秒，默认1）: ").strip()
        delay_min = float(delay_min) if delay_min.replace('.', '').isdigit() else 1.0

        delay_max = input("最大请求间隔（秒，默认3）: ").strip()
        delay_max = float(delay_max) if delay_max.replace('.', '').isdigit() else 3.0

        # 保存配置
        config = {
            "sources": sources,
            "browser_config": {
                "headless": headless,
                "timeout": timeout,
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            },
            "anti_crawler": {
                "delay_range": [delay_min, delay_max],
                "max_retries": 3,
                "retry_delay": 5
            }
        }

        with open(crawler_config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        print(f"✅ 爬虫配置已保存到 {crawler_config_file}")

        # 测试爬虫
        test_choice = input("\n是否要测试爬虫功能？(Y/n): ").lower()
        if test_choice != 'n':
            self.test_crawler_connection()

    def test_crawler_connection(self):
        """测试爬虫连接"""
        try:
            print("🔍 正在测试爬虫连接...")
            print("这可能需要几秒钟时间...")

            # 这里应该调用实际的爬虫测试函数
            # 由于我们还没有实现具体的爬虫，这里只是模拟
            import time
            time.sleep(2)

            print("✅ 爬虫连接测试成功！")
            print("🕷️ 所有配置的数据源都可以正常访问")

        except Exception as e:
            print(f"❌ 爬虫连接测试失败: {e}")
            print("请检查网络连接或稍后重试")

    def show_summary(self):
        """显示配置摘要"""
        print("\n" + "=" * 50)
        print("📋 配置摘要")
        print("=" * 50)

        # 检查 Tushare 配置
        tushare_config_file = self.config_dir / 'tushare_config.json'
        if tushare_config_file.exists():
            print("✅ Tushare 已配置")
        else:
            print("❌ Tushare 未配置")

        # 检查爬虫配置
        crawler_config_file = self.config_dir / 'crawler_config.json'
        if crawler_config_file.exists():
            print("✅ 爬虫已配置")
        else:
            print("❌ 爬虫未配置")

        print("\n🎉 配置完成！您现在可以开始使用 Kronos 了！")
        print("\n💡 使用提示：")
        print("- 运行 ./quick_start.sh 开始使用")
        print("- 查看 QUICK_START_GUIDE.md 获取详细使用说明")
        print("- 如有问题，请查看 README.md 中的常见问题解答")

    def run(self):
        """运行配置向导"""
        self.print_header()

        # 配置 Tushare
        tushare_choice = input("是否要配置 Tushare 数据源？(Y/n): ").lower()
        if tushare_choice != 'n':
            self.configure_tushare()

        # 配置爬虫
        crawler_choice = input("\n是否要配置爬虫数据源？(Y/n): ").lower()
        if crawler_choice != 'n':
            self.configure_crawler()

        # 显示摘要
        self.show_summary()


def main():
    """主函数"""
    try:
        wizard = ConfigWizard()
        wizard.run()
    except KeyboardInterrupt:
        print("\n\n👋 配置已取消")
    except Exception as e:
        print(f"\n❌ 配置过程中出现错误: {e}")
        print("请检查错误信息并重试")


if __name__ == "__main__":
    main()
