#!/usr/bin/env python3
"""
Kronos 跨平台GUI应用程序
支持 Windows、macOS、Linux
"""

import sys
import os
import json
import hashlib
import platform
import subprocess
import threading
from datetime import datetime
from pathlib import Path

# 导入Python命令检测器
sys.path.append(str(Path(__file__).parent / "tools"))
from python_detector import get_python_command_list

# 根据系统选择GUI实现
current_os = platform.system()

# 尝试导入tkinter
HAS_TKINTER = False
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    from tkinter.scrolledtext import ScrolledText

    HAS_TKINTER = True
except ImportError:
    pass

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


class SystemDialog:
    """系统原生对话框包装器"""

    @staticmethod
    def show_info(title, message):
        """显示信息对话框"""
        if current_os == 'Darwin':  # macOS
            script = f'''
            display dialog "{message}" with title "{title}" buttons {{"确定"}} default button 1 with icon note
            '''
            subprocess.run(['osascript', '-e', script], check=False)
        elif current_os == 'Windows':  # Windows
            subprocess.run(['powershell', '-Command',
                            f'[System.Windows.Forms.MessageBox]::Show("{message}", "{title}", "OK", "Information")'],
                           check=False)
        else:  # Linux
            try:
                subprocess.run(['zenity', '--info', f'--title={title}', f'--text={message}'], check=False)
            except:
                print(f"[INFO] {title}: {message}")

    @staticmethod
    def show_error(title, message):
        """显示错误对话框"""
        if current_os == 'Darwin':  # macOS
            script = f'''
            display dialog "{message}" with title "{title}" buttons {{"确定"}} default button 1 with icon stop
            '''
            subprocess.run(['osascript', '-e', script], check=False)
        elif current_os == 'Windows':  # Windows
            subprocess.run(['powershell', '-Command',
                            f'[System.Windows.Forms.MessageBox]::Show("{message}", "{title}", "OK", "Error")'],
                           check=False)
        else:  # Linux
            try:
                subprocess.run(['zenity', '--error', f'--title={title}', f'--text={message}'], check=False)
            except:
                print(f"[ERROR] {title}: {message}")

    @staticmethod
    def show_choice(title, message, choices):
        """显示选择对话框"""
        if current_os == 'Darwin':  # macOS
            choice_list = ', '.join([f'"{choice}"' for choice in choices])
            script = f'''
            set choiceList to {{{choice_list}}}
            set userChoice to choose from list choiceList with prompt "{message}" with title "{title}"
            if userChoice is false then return "CANCEL"
            return userChoice as string
            '''
            try:
                result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
                if result.returncode == 0 and result.stdout.strip() not in ["false", "CANCEL"]:
                    return result.stdout.strip()
            except:
                pass
        elif current_os == 'Windows':  # Windows  
            # Windows使用简单的输入框模拟选择
            choices_text = "\\n".join([f"{i + 1}. {choice}" for i, choice in enumerate(choices)])
            script = f'''
            Add-Type -AssemblyName Microsoft.VisualBasic
            $result = [Microsoft.VisualBasic.Interaction]::InputBox("{message}\\n\\n{choices_text}\\n\\n请输入选项编号:", "{title}", "1")
            if ($result -eq "") {{ exit 1 }}
            Write-Output $result
            '''
            try:
                result = subprocess.run(['powershell', '-Command', script],
                                        capture_output=True, text=True)
                if result.returncode == 0:
                    choice_num = int(result.stdout.strip()) - 1
                    if 0 <= choice_num < len(choices):
                        return choices[choice_num]
            except:
                pass
        else:  # Linux
            try:
                zenity_choices = []
                for choice in choices:
                    zenity_choices.extend(['--list', choice])
                result = subprocess.run(['zenity', '--list', f'--title={title}', f'--text={message}'] + zenity_choices,
                                        capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                # 命令行fallback
                print(f"{title}: {message}")
                for i, choice in enumerate(choices, 1):
                    print(f"{i}. {choice}")
                try:
                    choice_num = int(input("请选择 (输入编号): ")) - 1
                    if 0 <= choice_num < len(choices):
                        return choices[choice_num]
                except:
                    pass
        return None

    @staticmethod
    def get_input(title, prompt, default_answer=""):
        """获取用户输入"""
        if current_os == 'Darwin':  # macOS
            script = f'''
            display dialog "{prompt}" with title "{title}" default answer "{default_answer}" buttons {{"取消", "确定"}} default button 2
            text returned of result
            '''
            try:
                result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                pass
        elif current_os == 'Windows':  # Windows
            script = f'''
            Add-Type -AssemblyName Microsoft.VisualBasic
            $result = [Microsoft.VisualBasic.Interaction]::InputBox("{prompt}", "{title}", "{default_answer}")
            if ($result -eq "") {{ exit 1 }}
            Write-Output $result
            '''
            try:
                result = subprocess.run(['powershell', '-Command', script],
                                        capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                pass
        else:  # Linux
            try:
                result = subprocess.run(['zenity', '--entry', f'--title={title}',
                                         f'--text={prompt}', f'--entry-text={default_answer}'],
                                        capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                # 命令行fallback
                return input(f"{prompt} [{default_answer}]: ") or default_answer
        return None


class DeviceFingerprint:
    """设备指纹管理"""

    def get_device_id(self):
        """获取设备ID"""
        try:
            import uuid
            info = {
                'system': platform.system(),
                'node': platform.node(),
                'machine': platform.machine(),
                'processor': platform.processor()[:50] if platform.processor() else 'unknown',
                'mac': format(uuid.getnode(), '012x')
            }
            combined = json.dumps(info, sort_keys=True)
            device_id = hashlib.sha256(combined.encode()).hexdigest()[:16].upper()
            return device_id
        except Exception:
            fallback_id = hashlib.md5(platform.node().encode()).hexdigest()[:16].upper()
            return fallback_id


class LicenseValidator:
    """授权验证管理"""

    def __init__(self):
        self.device_fp = DeviceFingerprint()
        self.cache_file = self._get_cache_path()

    def _get_cache_path(self):
        """获取缓存文件路径"""
        if current_os == 'Windows':
            cache_dir = Path.home() / '.kronos'
        else:
            cache_dir = Path.home() / '.kronos'

        cache_dir.mkdir(exist_ok=True)
        return cache_dir / '.license_cache'

    def validate_license(self):
        """验证授权状态"""
        if not self.cache_file.exists():
            return False, "设备未激活"

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            current_device_id = self.device_fp.get_device_id()
            stored_device_id = cache_data.get('device_id')

            if current_device_id != stored_device_id:
                return False, "设备硬件发生变更"

            return True, "授权有效"

        except Exception:
            return False, "授权文件损坏"

    def activate_license(self, license_code):
        """激活授权码"""
        import re

        pattern = r'^KRONOS-[A-F0-9]{5}-[A-F0-9]{5}-[A-F0-9]{5}-[A-F0-9]{5}$'
        if not re.match(pattern, license_code.upper()):
            return False, "授权码格式错误"

        device_id = self.device_fp.get_device_id()

        cache_data = {
            'license_code': license_code.upper(),
            'device_id': device_id,
            'activation_time': datetime.now().isoformat(),
            'system_info': {
                'system': platform.system(),
                'release': platform.release()
            }
        }

        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            return True, "授权激活成功"
        except Exception as e:
            return False, f"激活失败: {e}"

    def get_license_info(self):
        """获取授权信息"""
        if not self.cache_file.exists():
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return None


class KronosApp:
    """Kronos主应用程序"""

    def __init__(self):
        self.validator = LicenseValidator()
        self.dialog = SystemDialog()

        # 启动时检查授权
        if not self.check_authorization():
            return

        # 根据是否有tkinter选择界面类型
        if HAS_TKINTER:
            self.show_gui_interface()
        else:
            self.show_native_interface()

    def check_authorization(self):
        """检查授权状态"""
        is_valid, message = self.validator.validate_license()

        if is_valid:
            return True

        device_id = self.validator.device_fp.get_device_id()

        while True:
            choice = self.dialog.show_choice(
                "🔐 Kronos 授权验证",
                f"欢迎使用 Kronos 金融预测系统！\\n\\n设备ID: {device_id}\\n状态: {message}\\n\\n请选择操作：",
                ["🔑 激活授权码", "📱 查看设备信息", "❌ 退出程序"]
            )

            if choice == "🔑 激活授权码":
                license_code = self.dialog.get_input(
                    "🔑 激活授权码",
                    "请输入您的授权码\\n\\n格式: KRONOS-XXXXX-XXXXX-XXXXX-XXXXX\\n\\n💡 授权码区分大小写，请准确输入",
                    ""
                )

                if license_code:
                    success, msg = self.validator.activate_license(license_code)
                    if success:
                        self.dialog.show_info("✅ 激活成功",
                                              f"恭喜！{msg}\\n\\n🎉 Kronos系统已成功激活！\\n现在您可以使用所有功能。")
                        return True
                    else:
                        self.dialog.show_error("❌ 激活失败",
                                               f"激活失败：{msg}\\n\\n💡 请检查：\\n• 授权码格式是否正确\\n• 网络连接是否正常\\n• 是否为有效授权码")
                        continue

            elif choice == "📱 查看设备信息":
                info = f"📱 设备信息\\n\\n🆔 设备ID: {device_id}\\n💻 操作系统: {platform.system()}\\n📋 系统版本: {platform.release()}\\n🖥️  处理器: {platform.machine()}\\n🏠 计算机名: {platform.node()}"
                self.dialog.show_info("📱 设备信息", info)
                continue

            else:  # 退出程序
                self.dialog.show_info("👋 再见", "感谢您对 Kronos 的关注！\\n如需授权码，请联系管理员。")
                return False

    def show_gui_interface(self):
        """显示GUI界面"""
        try:
            from .gui_interface import KronosGUI
            gui = KronosGUI(self.validator)
            gui.run()
        except:
            self.show_native_interface()

    def show_native_interface(self):
        """显示原生界面"""
        while True:
            choice = self.dialog.show_choice(
                "🚀 Kronos 金融预测系统",
                "✅ 系统已授权，欢迎使用！\\n\\n请选择您需要的功能：",
                [
                    "⚙️ 系统管理",
                    "📊 数据管理",
                    "🔮 预测分析",
                    "🌐 Web界面",
                    "🔐 授权管理",
                    "📖 使用帮助",
                    "❌ 退出程序"
                ]
            )

            if choice == "⚙️ 系统管理":
                self.show_system_menu()
            elif choice == "📊 数据管理":
                self.show_data_menu()
            elif choice == "🔮 预测分析":
                self.show_prediction_menu()
            elif choice == "🌐 Web界面":
                self.start_web_interface()
            elif choice == "🔐 授权管理":
                self.show_license_menu()
            elif choice == "📖 使用帮助":
                self.show_help()
            else:
                self.dialog.show_info("👋 感谢使用", "感谢使用 Kronos 金融预测系统！\\n祝您投资顺利！")
                break

    def show_system_menu(self):
        """系统管理菜单"""
        while True:
            choice = self.dialog.show_choice(
                "⚙️ 系统管理",
                "系统管理功能：",
                [
                    "📦 一键安装依赖",
                    "🔧 配置向导",
                    "🔍 环境检查",
                    "📋 系统状态",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📦 一键安装依赖":
                self.dialog.show_info("📦 一键安装",
                                      "正在启动一键安装程序...\\n\\n⏱️ 预计需要5-15分钟\\n📦 将安装Python依赖、模型文件等\\n☕ 请耐心等待安装完成")
                self.run_command_async("一键安装", ["bash", "quick_start.sh"], input_text="1\\n")

            elif choice == "🔧 配置向导":
                self.run_command_async("配置向导", get_python_command_list("scripts/config_wizard.py"))

            elif choice == "🔍 环境检查":
                self.run_command_async("环境检查", get_python_command_list("scripts/check_environment.py"))

            elif choice == "📋 系统状态":
                self.run_command_async("系统状态", ["bash", "quick_start.sh"], input_text="12\\n")

            else:
                break

    def show_data_menu(self):
        """数据管理菜单"""
        while True:
            choice = self.dialog.show_choice(
                "📊 数据管理",
                "数据获取和管理功能：",
                [
                    "📈 获取单只股票数据",
                    "📊 批量获取股票数据",
                    "🔄 数据源配置",
                    "📁 数据文件管理",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📈 获取单只股票数据":
                self.get_single_stock_data()
            elif choice == "📊 批量获取股票数据":
                self.get_batch_stock_data()
            elif choice == "🔄 数据源配置":
                self.configure_data_source()
            elif choice == "📁 数据文件管理":
                self.manage_data_files()
            else:
                break

    def get_single_stock_data(self):
        """获取单只股票数据"""
        # 选择数据源
        source_choice = self.dialog.show_choice(
            "📈 选择数据源",
            "请选择数据源类型：",
            ["🔄 自动选择最佳", "🏦 Tushare API", "🕷️ 网络爬虫"]
        )

        if not source_choice:
            return

        source_map = {"🔄 自动选择最佳": "auto", "🏦 Tushare API": "tushare", "🕷️ 网络爬虫": "crawler"}
        source = source_map[source_choice]

        # 获取股票代码
        if source == "tushare":
            symbol = self.dialog.get_input("🏦 Tushare股票代码",
                                           "请输入股票代码\\n\\n格式说明：\\n• 深交所: 000001.SZ\\n• 上交所: 600000.SH\\n• 创业板: 300001.SZ",
                                           "000001.SZ")
        else:
            symbol = self.dialog.get_input("📈 股票代码",
                                           "请输入6位股票代码\\n\\n示例：\\n• 平安银行: 000001\\n• 贵州茅台: 600519\\n• 宁德时代: 300750",
                                           "000001")

        if symbol:
            self.dialog.show_info("📈 开始获取", f"正在获取 {symbol} 的股票数据...\\n\\n数据源: {source_choice}")
            self.run_command_async(f"获取{symbol}数据",
                                   get_python_command_list("scripts/fetch_data.py", "--symbol", symbol, "--source",
                                                           source))

    def get_batch_stock_data(self):
        """批量获取股票数据"""
        symbols = self.dialog.get_input("📊 批量获取",
                                        "请输入多个股票代码（用逗号分隔）\\n\\n示例：\\n000001.SZ,600519.SH,300750.SZ\\n\\n💡 支持混合格式",
                                        "000001.SZ,600519.SH")

        if symbols:
            symbols_display = symbols.replace(',', '\\n')
            self.dialog.show_info("📊 批量处理",
                                  f"正在批量获取以下股票数据：\\n{symbols_display}\\n\\n⏱️ 预计需要几分钟时间\\n📈 完成后将自动生成预测报告")

            symbol_list = [s.strip() for s in symbols.split(',')]
            self.run_command_async("批量获取数据",
                                   get_python_command_list("scripts/batch_fetch_enhanced.py", "--symbols", *symbol_list,
                                                           "--source", "auto", "--min-days", "365"))

    def configure_data_source(self):
        """配置数据源"""
        choice = self.dialog.show_choice(
            "🔄 数据源配置",
            "请选择要配置的数据源：",
            ["🏦 配置Tushare", "🕷️ 配置爬虫", "🔧 运行配置向导"]
        )

        if choice == "🔧 运行配置向导":
            self.run_command_async("配置向导", get_python_command_list("scripts/config_wizard.py"))
        else:
            self.dialog.show_info("🔧 配置", "请使用配置向导进行详细配置")

    def manage_data_files(self):
        """数据文件管理"""
        data_path = project_root / "data"
        if data_path.exists():
            file_count = len(list(data_path.glob("*.csv")))
            self.dialog.show_info("📁 数据文件",
                                  f"数据目录: {data_path}\\n\\n📊 已保存数据文件: {file_count} 个\\n\\n💡 可以直接打开data文件夹查看")
        else:
            self.dialog.show_info("📁 数据文件", "暂无数据文件\\n\\n请先获取股票数据")

    def show_prediction_menu(self):
        """预测分析菜单"""
        while True:
            choice = self.dialog.show_choice(
                "🔮 预测分析",
                "股票预测和分析功能：",
                [
                    "📊 运行预测示例",
                    "📈 批量预测分析",
                    "🧪 技术指标分析",
                    "📋 查看预测报告",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📊 运行预测示例":
                example_choice = self.dialog.show_choice(
                    "📊 预测示例",
                    "选择预测示例类型：",
                    ["📈 完整预测", "📊 无成交量预测"]
                )

                if example_choice == "📈 完整预测":
                    self.run_command_async("完整预测示例", get_python_command_list("examples/prediction_example.py"))
                elif example_choice == "📊 无成交量预测":
                    self.run_command_async("无成交量预测",
                                           get_python_command_list("examples/prediction_wo_vol_example.py"))

            elif choice == "📈 批量预测分析":
                stock_code = self.dialog.get_input("📈 批量预测",
                                                   "请输入要预测的股票代码（6位数字）\\n\\n示例：000001", "000001")
                if stock_code:
                    self.dialog.show_info("📈 批量预测",
                                          f"正在为 {stock_code} 生成预测分析报告...\\n\\n📊 包含技术指标分析\\n📋 完成后将生成HTML报告")
                    self.run_command_async("批量预测分析",
                                           get_python_command_list("examples/prediction_batch_example.py",
                                                                   "--stock-code", stock_code))

            elif choice == "🧪 技术指标分析":
                self.dialog.show_info("🧪 技术指标", "技术指标分析已集成在批量预测中\\n\\n请使用'批量预测分析'功能")

            elif choice == "📋 查看预测报告":
                results_path = project_root / "results"
                if results_path.exists():
                    reports = list(results_path.glob("*.html"))
                    if reports:
                        self.dialog.show_info("📋 预测报告",
                                              f"报告目录: {results_path}\\n\\n📄 HTML报告: {len(reports)} 个\\n\\n💡 可以直接打开results文件夹查看")
                    else:
                        self.dialog.show_info("📋 预测报告", "暂无预测报告\\n\\n请先运行预测分析")
                else:
                    self.dialog.show_info("📋 预测报告", "暂无预测报告\\n\\n请先运行预测分析")

            else:
                break

    def start_web_interface(self):
        """启动Web界面"""
        choice = self.dialog.show_choice(
            "🌐 Web界面",
            "Web界面提供可视化的股票预测和分析功能\\n\\n是否启动Web界面？",
            ["🚀 启动Web界面", "❌ 取消"]
        )

        if choice == "🚀 启动Web界面":
            self.dialog.show_info("🌐 启动中",
                                  "Web界面正在启动...\\n\\n请在桌面窗口中继续使用。")

            # 启动web界面
            def start_web():
                self.run_command_async("Web界面", get_python_command_list("webui/app.py"))

            threading.Thread(target=start_web, daemon=True).start()

    def show_license_menu(self):
        """授权管理菜单"""
        while True:
            choice = self.dialog.show_choice(
                "🔐 授权管理",
                "授权信息和管理功能：",
                [
                    "📋 查看授权状态",
                    "🔑 激活新授权码",
                    "📱 显示设备信息",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📋 查看授权状态":
                self.show_license_status()
            elif choice == "🔑 激活新授权码":
                self.activate_new_license()
            elif choice == "📱 显示设备信息":
                self.show_device_info()
            else:
                break

    def show_license_status(self):
        """显示授权状态"""
        is_valid, message = self.validator.validate_license()
        device_id = self.validator.device_fp.get_device_id()

        status_text = f"🔐 Kronos 授权状态\\n\\n"
        status_text += f"📱 设备ID: {device_id}\\n"
        status_text += f"💻 操作系统: {platform.system()} {platform.release()}\\n"
        status_text += f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n\\n"

        if is_valid:
            status_text += f"✅ 授权状态: {message}\\n\\n"

            info = self.validator.get_license_info()
            if info:
                status_text += f"📄 授权详情:\\n"
                status_text += f"🔑 授权码: {info['license_code']}\\n"
                status_text += f"📅 激活时间: {info['activation_time'][:19].replace('T', ' ')}\\n"
                status_text += f"🏷️  授权类型: 永久授权\\n"
                status_text += f"📊 状态: 正常使用"
        else:
            status_text += f"❌ 授权状态: {message}\\n\\n"
            status_text += "💡 请联系管理员获取授权码"

        self.dialog.show_info("🔐 授权状态", status_text)

    def activate_new_license(self):
        """激活新授权码"""
        license_code = self.dialog.get_input("🔑 激活授权码",
                                             "请输入新的授权码\\n\\n格式: KRONOS-XXXXX-XXXXX-XXXXX-XXXXX\\n\\n💡 授权码区分大小写",
                                             "")

        if license_code:
            success, message = self.validator.activate_license(license_code)
            if success:
                self.dialog.show_info("✅ 激活成功", f"🎉 {message}\\n\\n授权已成功更新！")
            else:
                self.dialog.show_error("❌ 激活失败", f"激活失败：{message}\\n\\n请检查授权码格式是否正确")

    def show_device_info(self):
        """显示设备信息"""
        device_id = self.validator.device_fp.get_device_id()
        info = f"📱 设备详细信息\\n\\n"
        info += f"🆔 设备ID: {device_id}\\n"
        info += f"💻 操作系统: {platform.system()}\\n"
        info += f"📋 系统版本: {platform.release()}\\n"
        info += f"🔧 处理器架构: {platform.machine()}\\n"
        info += f"🏠 计算机名称: {platform.node()}\\n"
        info += f"🐍 Python版本: {platform.python_version()}\\n\\n"
        info += f"💡 设备ID用于授权绑定，请妥善保管"

        self.dialog.show_info("📱 设备信息", info)

    def show_help(self):
        """显示帮助信息"""
        help_text = """📖 Kronos 使用指南

🚀 快速开始：
1️⃣ 首次使用请执行"系统管理" → "一键安装依赖"
2️⃣ 使用"数据管理"获取股票数据
3️⃣ 使用"预测分析"进行股票预测

📊 数据源说明：
🏦 Tushare: 专业金融数据API（需注册）
🕷️ 网络爬虫: 免费获取实时数据
🔄 自动选择: 智能选择最佳数据源

📈 股票代码格式：
• Tushare格式: 000001.SZ, 600519.SH
• 爬虫格式: 000001, 600519 (6位数字)

🔮 预测功能：
📊 基础预测: 标准OHLCV数据预测
📈 批量预测: 多只股票批量分析
🧪 技术指标: RSI、MACD、布林带等

🌐 Web界面：
提供可视化的操作界面和图表分析

📞 技术支持：
如遇问题请查看README.md或联系技术支持"""

        self.dialog.show_info("📖 使用指南", help_text)

    def run_command_async(self, description, command, input_text=None):
        """异步运行命令"""

        def run():
            try:
                if input_text:
                    result = subprocess.run(command, cwd=project_root, input=input_text,
                                            text=True, capture_output=True, timeout=300)
                else:
                    result = subprocess.run(command, cwd=project_root,
                                            capture_output=True, text=True, timeout=300)

                if result.returncode == 0:
                    self.dialog.show_info("✅ 执行完成", f"✅ {description} 执行成功！")
                else:
                    error_msg = result.stderr or result.stdout or "执行失败"
                    self.dialog.show_error("❌ 执行失败",
                                           f"❌ {description} 执行失败\\n\\n错误信息：\\n{error_msg[:200]}...")

            except subprocess.TimeoutExpired:
                self.dialog.show_error("⏰ 执行超时", f"⏰ {description} 执行超时\\n\\n请检查网络连接或稍后重试")
            except Exception as e:
                self.dialog.show_error("❌ 执行错误", f"❌ {description} 执行时发生错误\\n\\n{str(e)}")

        # 显示开始提示
        self.dialog.show_info("🚀 开始执行", f"🚀 正在执行: {description}\\n\\n⏳ 请稍候，执行完成后将显示结果...")

        # 在后台线程运行
        threading.Thread(target=run, daemon=True).start()


def main():
    """主程序入口"""
    try:
        app = KronosApp()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"程序启动失败: {e}")
        SystemDialog.show_error("❌ 启动失败", f"程序启动失败：{e}\\n\\n请检查Python环境或联系技术支持")


if __name__ == "__main__":
    main()
