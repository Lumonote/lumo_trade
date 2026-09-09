#!/usr/local/bin/python3.11
"""
Lumo macOS原生GUI - 使用AppleScript实现原生体验
专为macOS Big Sur/Monterey设计的原生界面
"""

import sys
import os
import json
import hashlib
import platform
import subprocess
import threading
import asyncio
from datetime import datetime
from pathlib import Path
import webbrowser

# 导入Python命令检测器
sys.path.append(str(Path(__file__).parent.parent))
from python_detector import get_python_command_list

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class MacOSNativeUI:
    """macOS原生UI接口"""

    @staticmethod
    def show_dialog(title, message, buttons=["确定"], default_button=1, icon="note"):
        button_list = ', '.join([f'"{btn}"' for btn in buttons])
        script = f'''
        tell application "System Events"
            activate
            display dialog "{message}" with title "{title}" buttons {{{button_list}}} default button {default_button} with icon {icon}
            button returned of result
        end tell
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    @staticmethod
    def show_list_dialog(title, prompt, items):
        item_list = ', '.join([f'"{item}"' for item in items])
        script = f'''
        tell application "System Events"
            activate
            set itemList to {{{item_list}}}
            set userChoice to choose from list itemList with prompt "{prompt}" with title "{title}"
            if userChoice is false then return "CANCEL"
            return userChoice as string
        end tell
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip() not in ["false", "CANCEL"]:
                return result.stdout.strip()
        except:
            pass
        return None

    @staticmethod
    def get_input(title, prompt, default_answer=""):
        script = f'''
        tell application "System Events"
            activate
            display dialog "{prompt}" with title "{title}" default answer "{default_answer}" buttons {"取消", "确定"} default button 2
            text returned of result
        end tell
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass
        return None

    @staticmethod
    def show_notification(title, subtitle, message):
        script = f'''
        tell application "System Events"
            activate
            display notification "{message}" with title "{title}" subtitle "{subtitle}" sound name "Glass"
        end tell
        '''
        try:
            subprocess.run(['osascript', '-e', script], check=False)
        except:
            pass


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
        cache_dir = Path.home() / '.lumo'
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

        pattern = r'^LUMO-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$'
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


class LumoNativeMacOSApp:
    """Lumo macOS原生应用"""

    def __init__(self):
        self.ui = MacOSNativeUI()
        self.validator = LicenseValidator()

        # 显示启动画面
        self.ui.show_notification("🚀 Lumo", "金融预测系统", "正在启动...")

        # 检查授权
        if not self.check_authorization():
            return

        # 启动主界面
        self.show_main_interface()

    def check_authorization(self):
        """检查授权状态"""
        is_valid, message = self.validator.validate_license()

        if is_valid:
            return True

        device_id = self.validator.device_fp.get_device_id()

        while True:
            # 授权界面
            choice = self.ui.show_list_dialog(
                "🔐 Lumo 授权验证",
                f"欢迎使用 Lumo 金融预测系统！\\n\\n🆔 设备ID: {device_id}\\n📋 状态: {message}\\n\\n请选择操作：",
                ["🔑 激活授权码", "📱 查看设备信息", "❌ 退出程序"]
            )

            if choice == "🔑 激活授权码":
                license_code = self.ui.get_input(
                    "🔑 激活授权码",
                    "请输入您的授权码\\n\\n📝 格式: LUMO-XXXXX-XXXXX-XXXXX-XXXXX\\n\\n💡 授权码区分大小写，请准确输入"
                )

                if license_code:
                    success, msg = self.validator.activate_license(license_code)
                    if success:
                        self.ui.show_dialog("✅ 激活成功",
                                            f"🎉 恭喜！{msg}\\n\\n✨ Lumo系统已成功激活！\\n现在您可以使用所有功能。",
                                            icon="note")
                        self.ui.show_notification("✅ 激活成功", "Lumo专业版", "所有功能已解锁！")
                        return True
                    else:
                        self.ui.show_dialog("❌ 激活失败",
                                            f"激活失败：{msg}\\n\\n💡 请检查：\\n• 授权码格式是否正确\\n• 网络连接是否正常\\n• 是否为有效授权码",
                                            icon="stop")

            elif choice == "📱 查看设备信息":
                info = f"📱 设备详细信息\\n\\n🆔 设备ID: {device_id}\\n💻 操作系统: {platform.system()}\\n📋 系统版本: {platform.release()}\\n🖥️  处理器: {platform.machine()}\\n🏠 计算机名: {platform.node()}"
                self.ui.show_dialog("📱 设备信息", info)

            else:  # 退出程序
                self.ui.show_dialog("👋 再见", "感谢您对 Lumo 的关注！\\n如需授权码，请联系管理员。")
                return False

    def show_main_interface(self):
        """显示主界面"""
        self.ui.show_notification("🎉 欢迎", "Lumo专业版", "系统已就绪，欢迎使用！")

        while True:
            choice = self.ui.show_list_dialog(
                "🚀 Lumo 金融预测系统",
                "✅ 系统已授权，欢迎使用！\\n\\n📊 选择您需要的功能：",
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
                self.ui.show_dialog("👋 感谢使用", "感谢使用 Lumo 金融预测系统！\\n祝您投资顺利！")
                break

    def show_system_menu(self):
        """系统管理菜单"""
        while True:
            choice = self.ui.show_list_dialog(
                "⚙️ 系统管理",
                "🛠️ 系统管理功能：",
                [
                    "📦 一键安装依赖",
                    "🔧 配置数据源",
                    "🔍 检查环境状态",
                    "📋 查看系统状态",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📦 一键安装依赖":
                self.ui.show_dialog("📦 一键安装",
                                    "正在启动一键安装程序...\\n\\n⏱️ 预计需要5-15分钟\\n📦 将安装Python依赖、模型文件等\\n☕ 请耐心等待安装完成")
                self.run_command_with_notification("一键安装", ["bash", "quick_start.sh"], "1\\n")

            elif choice == "🔧 配置数据源":
                self.run_command_with_notification("配置向导", get_python_command_list("scripts/config_wizard.py"))

            elif choice == "🔍 检查环境状态":
                self.run_command_with_notification("环境检查", get_python_command_list("scripts/check_environment.py"))

            elif choice == "📋 查看系统状态":
                self.run_command_with_notification("系统状态", ["bash", "quick_start.sh"], "12\\n")

            else:
                break

    def show_data_menu(self):
        """数据管理菜单"""
        while True:
            choice = self.ui.show_list_dialog(
                "📊 数据管理",
                "📈 数据获取和管理功能：",
                [
                    "📈 获取单只股票数据",
                    "📊 批量获取数据",
                    "🔄 配置数据源",
                    "📁 查看数据文件",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📈 获取单只股票数据":
                self.get_single_stock()
            elif choice == "📊 批量获取数据":
                self.get_batch_stock()
            elif choice == "🔄 配置数据源":
                self.configure_data_source()
            elif choice == "📁 查看数据文件":
                self.view_data_files()
            else:
                break

    def get_single_stock(self):
        """获取单只股票数据"""
        symbol = self.ui.get_input("📈 股票代码",
                                   "请输入股票代码\\n\\n📝 格式示例：\\n• 平安银行: 000001\\n• 贵州茅台: 600519\\n• 宁德时代: 300750",
                                   "000001")

        if symbol:
            self.ui.show_dialog("📈 开始获取", f"正在获取 {symbol} 的数据...\\n\\n⏱️ 请稍候，完成后将显示结果")
            self.run_command_with_notification(f"获取{symbol}数据",
                                               get_python_command_list("scripts/fetch_data.py", "--symbol", symbol,
                                                                       "--source", "auto"))

    def get_batch_stock(self):
        """批量获取股票数据"""
        symbols = self.ui.get_input("📊 批量获取",
                                    "请输入多个股票代码（用逗号分隔）\\n\\n📝 示例：\\n000001,600519,300750",
                                    "000001,600519")

        if symbols:
            self.ui.show_dialog("📊 批量处理",
                                f"正在批量获取数据...\\n\\n⏱️ 预计需要几分钟\\n📈 完成后将生成预测报告")

            symbol_list = [s.strip() for s in symbols.split(',')]
            self.run_command_with_notification("批量获取数据",
                                               get_python_command_list("scripts/batch_fetch_enhanced.py", "--symbols",
                                                                       *symbol_list))

    def configure_data_source(self):
        """配置数据源"""
        self.run_command_with_notification("配置向导", get_python_command_list("scripts/config_wizard.py"))

    def view_data_files(self):
        """查看数据文件"""
        data_path = project_root / "data"
        if data_path.exists():
            file_count = len(list(data_path.glob("*.csv")))
            self.ui.show_dialog("📁 数据文件",
                                f"📂 数据目录: {data_path}\\n\\n📊 已保存文件: {file_count} 个\\n\\n💡 可以在Finder中打开data文件夹查看")
        else:
            self.ui.show_dialog("📁 数据文件", "📂 暂无数据文件\\n\\n请先获取股票数据")

    def show_prediction_menu(self):
        """预测分析菜单"""
        while True:
            choice = self.ui.show_list_dialog(
                "🔮 预测分析",
                "🎯 股票预测和分析功能：",
                [
                    "📊 运行预测示例",
                    "📈 批量预测分析",
                    "📋 查看预测报告",
                    "⬅️ 返回主菜单"
                ]
            )

            if choice == "📊 运行预测示例":
                example_choice = self.ui.show_list_dialog(
                    "📊 预测示例",
                    "选择预测类型：",
                    ["📈 完整预测", "📊 无成交量预测"]
                )

                if example_choice == "📈 完整预测":
                    self.run_command_with_notification("完整预测",
                                                       get_python_command_list("examples/prediction_example.py"))
                elif example_choice == "📊 无成交量预测":
                    self.run_command_with_notification("无成交量预测",
                                                       get_python_command_list("examples/prediction_wo_vol_example.py"))

            elif choice == "📈 批量预测分析":
                stock_code = self.ui.get_input("📈 批量预测",
                                               "请输入股票代码（6位数字）\\n\\n📝 示例：000001", "000001")
                if stock_code:
                    self.ui.show_dialog("📈 批量预测",
                                        f"正在为 {stock_code} 生成分析报告...\\n\\n📊 包含技术指标\\n📋 将生成HTML报告")
                    self.run_command_with_notification("批量预测",
                                                       get_python_command_list("examples/prediction_batch_example.py",
                                                                               "--stock-code", stock_code))

            elif choice == "📋 查看预测报告":
                results_path = project_root / "results"
                if results_path.exists():
                    reports = list(results_path.glob("*.html"))
                    if reports:
                        self.ui.show_dialog("📋 预测报告",
                                            f"📂 报告目录: {results_path}\\n\\n📄 HTML报告: {len(reports)} 个\\n\\n💡 可以在Finder中打开results文件夹查看")
                    else:
                        self.ui.show_dialog("📋 预测报告", "📂 暂无预测报告\\n\\n请先运行预测分析")
                else:
                    self.ui.show_dialog("📋 预测报告", "📂 暂无预测报告\\n\\n请先运行预测分析")

            else:
                break

    def start_web_interface(self):
        """启动Web界面"""
        choice = self.ui.show_dialog(
            "🌐 Web界面",
            "Web界面提供可视化的预测分析功能\\n\\n🌐 访问地址: http://localhost:7070\\n\\n是否启动？",
            ["🚀 启动", "❌ 取消"]
        )

        if choice == "🚀 启动":
            self.ui.show_notification("🌐 启动中", "Web界面", "正在启动，请稍候...")

            def start_web():
                try:
                    self.run_command_sync("Web界面", get_python_command_list("webui/app.py"))
                except:
                    pass

            threading.Thread(target=start_web, daemon=True).start()

            # 延迟打开浏览器
            def open_browser():
                import time
                time.sleep(3)
                webbrowser.open("http://localhost:7070")

            threading.Thread(target=open_browser, daemon=True).start()

    def show_license_menu(self):
        """授权管理菜单"""
        while True:
            choice = self.ui.show_list_dialog(
                "🔐 授权管理",
                "🔑 授权信息和管理：",
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

        if is_valid:
            info = self.validator.get_license_info()
            status_text = f"🔐 Lumo 授权状态\\n\\n✅ 状态: {message}\\n\\n📱 设备ID: {device_id}\\n💻 系统: {platform.system()} {platform.release()}"

            if info:
                status_text += f"\\n\\n📄 授权详情:\\n🔑 授权码: {info['license_code']}\\n📅 激活时间: {info['activation_time'][:19].replace('T', ' ')}"
        else:
            status_text = f"🔐 Lumo 授权状态\\n\\n❌ 状态: {message}\\n\\n📱 设备ID: {device_id}\\n💡 请联系管理员获取授权码"

        self.ui.show_dialog("🔐 授权状态", status_text)

    def activate_new_license(self):
        """激活新授权码"""
        license_code = self.ui.get_input("🔑 激活授权码",
                                         "请输入新的授权码\\n\\n📝 格式: LUMO-XXXXX-XXXXX-XXXXX-XXXXX")

        if license_code:
            success, message = self.validator.activate_license(license_code)
            if success:
                self.ui.show_dialog("✅ 激活成功", f"🎉 {message}\\n\\n授权已成功更新！")
                self.ui.show_notification("✅ 更新成功", "授权管理", "授权码已更新")
            else:
                self.ui.show_dialog("❌ 激活失败", f"激活失败：{message}\\n\\n请检查授权码格式", icon="stop")

    def show_device_info(self):
        """显示设备信息"""
        device_id = self.validator.device_fp.get_device_id()
        info = f"📱 设备详细信息\\n\\n🆔 设备ID: {device_id}\\n💻 操作系统: {platform.system()}\\n📋 系统版本: {platform.release()}\\n🔧 处理器: {platform.machine()}\\n🏠 计算机名: {platform.node()}\\n🐍 Python: {platform.python_version()}"

        self.ui.show_dialog("📱 设备信息", info)

    def show_help(self):
        """显示帮助信息"""
        help_text = """📖 Lumo 使用指南

🚀 快速开始：
1️⃣ 系统管理 → 一键安装依赖
2️⃣ 数据管理 → 获取股票数据
3️⃣ 预测分析 → 生成预测报告

📊 功能说明：
🏦 支持多种数据源（Tushare/爬虫）
📈 AI驱动的股票预测
🧪 技术指标分析
🌐 Web可视化界面

📞 技术支持：
如遇问题请查看README.md文档"""

        self.ui.show_dialog("📖 使用指南", help_text)

    def run_command_with_notification(self, description, command, input_text=None):
        """运行命令并显示通知"""
        self.ui.show_notification("🚀 开始执行", description, "正在执行，请稍候...")

        def run():
            try:
                if input_text:
                    result = subprocess.run(command, cwd=project_root, input=input_text,
                                            text=True, capture_output=True, timeout=300)
                else:
                    result = subprocess.run(command, cwd=project_root,
                                            capture_output=True, text=True, timeout=300)

                if result.returncode == 0:
                    self.ui.show_notification("✅ 执行完成", description, "执行成功！")
                    self.ui.show_dialog("✅ 执行完成", f"✅ {description} 执行成功！")
                else:
                    error_msg = result.stderr or result.stdout or "执行失败"
                    self.ui.show_notification("❌ 执行失败", description, "执行失败")
                    self.ui.show_dialog("❌ 执行失败",
                                        f"❌ {description} 执行失败\\n\\n错误信息：\\n{error_msg[:200]}...", icon="stop")

            except subprocess.TimeoutExpired:
                self.ui.show_notification("⏰ 执行超时", description, "执行超时")
                self.ui.show_dialog("⏰ 执行超时", f"⏰ {description} 执行超时\\n\\n请检查网络连接", icon="caution")
            except Exception as e:
                self.ui.show_notification("❌ 执行错误", description, "发生错误")
                self.ui.show_dialog("❌ 执行错误", f"❌ {description} 发生错误\\n\\n{str(e)}", icon="stop")

        threading.Thread(target=run, daemon=True).start()

    def run_command_sync(self, description, command):
        """同步运行命令"""
        return subprocess.run(command, cwd=project_root, text=True)


def main():
    """主程序入口"""
    try:
        app = LumoNativeMacOSApp()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # 使用原生macOS对话框显示错误
        subprocess.run(['osascript', '-e', f'''
            display dialog "程序启动失败: {str(e)}

请尝试以下解决方案:
1. 检查系统权限
2. 重新安装程序
3. 联系技术支持" with title "Lumo启动错误" buttons {{"确定"}} default button 1 with icon stop
        '''], check=False)


if __name__ == "__main__":
    main()
