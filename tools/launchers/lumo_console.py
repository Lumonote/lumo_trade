#!/usr/local/bin/python3.11
"""
Lumo 无GUI版本 - 解决tkinter不可用的问题
使用纯命令行界面，集成所有 quick_start.sh 功能
"""

import os
import sys
import subprocess
import platform
import time
import json
import hashlib
from pathlib import Path


class LumoConsoleApp:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent.absolute()
        self.setup_colors()

    def setup_colors(self):
        """设置控制台颜色"""
        if platform.system() != 'Windows':
            self.colors = {
                'RED': '\033[0;31m',
                'GREEN': '\033[0;32m',
                'YELLOW': '\033[1;33m',
                'BLUE': '\033[0;34m',
                'CYAN': '\033[0;36m',
                'WHITE': '\033[1;37m',
                'NC': '\033[0m'  # No Color
            }
        else:
            self.colors = {key: '' for key in ['RED', 'GREEN', 'YELLOW', 'BLUE', 'CYAN', 'WHITE', 'NC']}

    def print_colored(self, message, color='WHITE'):
        """打印彩色文本"""
        print(f"{self.colors[color]}{message}{self.colors['NC']}")

    def show_banner(self):
        """显示启动横幅"""
        os.system('clear' if platform.system() != 'Windows' else 'cls')
        self.print_colored("=" * 50, 'BLUE')
        self.print_colored("    Lumo 金融预测系统 🚀", 'CYAN')
        self.print_colored("=" * 50, 'BLUE')
        self.print_colored(f"系统: {platform.system()} {platform.release()}", 'WHITE')
        self.print_colored(f"Python: {sys.version.split()[0]}", 'WHITE')
        print()

    def show_menu(self):
        """显示主菜单"""
        self.print_colored("功能菜单:", 'YELLOW')
        print()
        self.print_colored("📦 系统设置", 'YELLOW')
        print("1. 一键安装所有依赖")
        print("2. 配置数据源向导")
        print("3. 检查环境状态")
        print()
        self.print_colored("📊 数据获取", 'YELLOW')
        print("4. 获取股票数据 (Tushare)")
        print("5. 获取股票数据 (爬虫)")
        print("6. 批量获取数据及预测")
        print()
        self.print_colored("🔐 授权管理", 'YELLOW')
        print("7. 检查授权状态")
        print("8. 激活授权码")
        print()
        self.print_colored("🔮 预测功能", 'YELLOW')
        print("9. 运行预测示例")
        print("10. 测试爬虫功能")
        print()
        print("11. 退出程序")
        print()

    def get_user_choice(self):
        """获取用户选择"""
        while True:
            try:
                choice = input("请选择功能 (1-11): ").strip()
                choice_num = int(choice)
                if 1 <= choice_num <= 11:
                    return choice_num
                else:
                    self.print_colored("❌ 请输入1-11之间的数字", 'RED')
            except (ValueError, KeyboardInterrupt):
                self.print_colored("❌ 输入无效，请输入数字", 'RED')
            except EOFError:
                return 11  # 退出

    def run_command(self, command, description):
        """运行命令并显示输出"""
        self.print_colored(f"🔄 开始执行: {description}", 'BLUE')
        print("-" * 50)

        try:
            if isinstance(command, list):
                process = subprocess.Popen(
                    command,
                    cwd=self.project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1
                )
            else:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=self.project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1
                )

            # 实时显示输出
            for line in iter(process.stdout.readline, ''):
                line = line.rstrip()
                if line:
                    # 根据内容设置颜色
                    if "✅" in line or "完成" in line or "成功" in line:
                        self.print_colored(line, 'GREEN')
                    elif "❌" in line or "错误" in line or "失败" in line or "ERROR" in line:
                        self.print_colored(line, 'RED')
                    elif "⚠️" in line or "警告" in line or "WARNING" in line:
                        self.print_colored(line, 'YELLOW')
                    elif "🔄" in line or "正在" in line or "Installing" in line:
                        self.print_colored(line, 'BLUE')
                    else:
                        print(line)

            process.wait()

            print("-" * 50)
            if process.returncode == 0:
                self.print_colored(f"✅ {description} 完成", 'GREEN')
            else:
                self.print_colored(f"❌ {description} 失败 (退出码: {process.returncode})", 'RED')

            return process.returncode == 0

        except Exception as e:
            self.print_colored(f"❌ 执行异常: {str(e)}", 'RED')
            return False

    def wait_for_enter(self):
        """等待用户按回车"""
        print()
        input("按回车键继续...")

    # ===== 功能实现方法 =====

    def install_dependencies(self):
        """一键安装所有依赖"""
        commands = [
            'pip3 install -r requirements.txt',
            'pip3 install playwright',
            'playwright install chromium',
            'pip3 install modelscope'
        ]

        for i, cmd in enumerate(commands, 1):
            self.print_colored(f"步骤 {i}/{len(commands)}: {cmd.split()[2] if len(cmd.split()) > 2 else cmd}", 'CYAN')
            success = self.run_command(cmd, f"执行步骤{i}")
            if not success and i == 1:  # requirements.txt 是必须的
                self.print_colored("❌ 核心依赖安装失败，无法继续", 'RED')
                break

    def config_wizard(self):
        """配置数据源向导"""
        self.run_command(['python3', str(self.project_root / 'scripts/config_wizard.py')], "配置数据源向导")

    def check_environment(self):
        """检查环境状态"""
        self.run_command(['python3', str(self.project_root / 'scripts/check_environment.py')], "环境状态检查")

    def fetch_tushare_data(self):
        """获取Tushare数据"""
        print("请输入股票代码 (格式: 000001.SZ):")
        symbol = input("股票代码: ").strip()
        if symbol:
            self.run_command(
                ['python3', str(self.project_root / 'scripts/fetch_data.py'), '--symbol', symbol, '--source',
                 'tushare'],
                f"获取 {symbol} 数据 (Tushare)")
        else:
            self.print_colored("❌ 未输入股票代码", 'RED')

    def fetch_crawler_data(self):
        """获取爬虫数据"""
        print("请输入股票代码 (格式: 000001):")
        symbol = input("股票代码: ").strip()
        if symbol:
            self.run_command(
                ['python3', str(self.project_root / 'scripts/fetch_data.py'), '--symbol', symbol, '--source', 'auto'],
                f"获取 {symbol} 数据 (爬虫)")
        else:
            self.print_colored("❌ 未输入股票代码", 'RED')

    def batch_prediction(self):
        """批量预测"""
        print("请输入股票代码 (多个用逗号分隔，例如: 000001.SZ,600000.SH):")
        symbols = input("股票代码: ").strip()
        if not symbols:
            self.print_colored("❌ 未输入股票代码", 'RED')
            return

        print("选择数据源:")
        print("1. 自动选择 (推荐)")
        print("2. Tushare")
        print("3. 网络爬虫")

        source_choice = input("请选择 (1-3, 默认1): ").strip() or "1"
        source_map = {"1": "auto", "2": "tushare", "3": "crawler"}
        source = source_map.get(source_choice, "auto")

        days = input("获取天数 (默认365): ").strip() or "365"

        self.run_command(['python3', str(self.project_root / 'scripts/batch_fetch_enhanced.py'),
                          '--symbols', symbols.replace(',', ' '), '--source', source, '--min-days', days],
                         "批量数据获取和预测")

    def check_license(self):
        """检查授权状态"""
        self.run_command(['python3', '-c', '''
import sys
sys.path.append(str(Path(__file__).parent.parent.parent / 'finetune/license_system'))
try:
    from license_validator import LicenseValidator
    import os
    
    data_dir = str(Path(__file__).parent.parent.parent / 'finetune/license_system/data')
    validator = LicenseValidator(data_dir)
    
    print("=" * 60)
    print("           Lumo 授权状态检查")
    print("=" * 60)
    
    is_valid, message = validator.validate_license()
    
    if is_valid:
        print(f"✅ {message}")
        info = validator.get_license_info()
        if info:
            print(f"")
            print(f"📋 授权信息:")
            print(f"   授权码: {info['license_code']}")
            print(f"   激活时间: {info['activation_time'][:19].replace('T', ' ')}")
            print(f"   设备ID: {info['device_id']}")
            print(f"   系统: {info['system_info']['system']} {info['system_info']['release']}")
            print(f"   授权类型: 永久授权")
    else:
        print(f"❌ {message}")
        print(f"")
        print(f"💡 请使用激活授权码功能进行激活")
        
except ImportError:
    print("❌ 授权系统文件不存在")
except Exception as e:
    print(f"❌ 授权检查异常: {e}")
        '''], "授权状态检查")

    def activate_license(self):
        """激活授权码"""
        print("请输入授权码 (格式: LUMO-XXXXX-XXXXX-XXXXX-XXXXX):")
        license_code = input("授权码: ").strip().upper()

        if not license_code:
            self.print_colored("❌ 未输入授权码", 'RED')
            return

        # 验证格式
        import re
        pattern = r'^LUMO-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$'
        if not re.match(pattern, license_code):
            self.print_colored("❌ 授权码格式错误", 'RED')
            return

        # 模拟激活过程
        self.print_colored("🔄 正在激活授权码...", 'BLUE')
        time.sleep(2)

        try:
            # 创建授权缓存
            import uuid
            device_info = {
                'system': platform.system(),
                'node': platform.node(),
                'machine': platform.machine(),
                'processor': platform.processor()[:50],
                'mac': format(uuid.getnode(), '012x')
            }
            device_id = hashlib.sha256(json.dumps(device_info, sort_keys=True).encode()).hexdigest()[:16].upper()

            # 创建缓存目录
            if platform.system() == 'Windows':
                cache_dir = os.path.expandvars('%APPDATA%\\.lumo')
            else:
                cache_dir = os.path.expanduser('~/.lumo')

            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, '.license_cache')

            from datetime import datetime
            cache_data = {
                'license_code': license_code,
                'device_id': device_id,
                'device_info': device_info,
                'activation_time': datetime.now().isoformat()
            }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)

            self.print_colored("✅ 授权激活成功！", 'GREEN')
            self.print_colored(f"设备ID: {device_id}", 'CYAN')

        except Exception as e:
            self.print_colored(f"❌ 激活失败: {e}", 'RED')

    def run_prediction(self):
        """运行预测示例"""
        self.run_command(['python3', str(self.project_root / 'examples/prediction_example.py')], "预测示例运行")

    def test_crawler(self):
        """测试爬虫功能"""
        self.run_command(['python3', '-c', '''
import asyncio
try:
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from scripts.crawler import CrawlerManager
    asyncio.run(CrawlerManager().test_connection())
except ImportError:
    print("❌ 爬虫模块不存在")
except Exception as e:
    print(f"❌ 爬虫测试失败: {e}")
        '''], "爬虫功能测试")

    def run(self):
        """运行主程序"""
        try:
            while True:
                self.show_banner()
                self.show_menu()

                choice = self.get_user_choice()

                if choice == 1:
                    self.install_dependencies()
                elif choice == 2:
                    self.config_wizard()
                elif choice == 3:
                    self.check_environment()
                elif choice == 4:
                    self.fetch_tushare_data()
                elif choice == 5:
                    self.fetch_crawler_data()
                elif choice == 6:
                    self.batch_prediction()
                elif choice == 7:
                    self.check_license()
                elif choice == 8:
                    self.activate_license()
                elif choice == 9:
                    self.run_prediction()
                elif choice == 10:
                    self.test_crawler()
                elif choice == 11:
                    self.print_colored("👋 感谢使用 Lumo 系统！", 'GREEN')
                    break

                if choice != 11:
                    self.wait_for_enter()

        except KeyboardInterrupt:
            self.print_colored("\\n👋 程序被用户中断", 'YELLOW')
        except Exception as e:
            self.print_colored(f"❌ 程序异常: {e}", 'RED')


def main():
    """主程序入口"""
    app = LumoConsoleApp()
    app.run()


if __name__ == "__main__":
    main()
