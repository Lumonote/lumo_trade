#!/usr/local/bin/python3.11
"""
专门用于修复tkinter打包问题的启动器
根据系统环境自动选择最佳界面
"""

import sys
import os
import subprocess


def check_tkinter():
    """检查tkinter是否可用"""
    try:
        import tkinter as tk
        import _tkinter
        # 测试创建窗口
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except ImportError:
        return False
    except Exception:
        return False


def main():
    """主程序入口"""
    # 添加项目路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sys.path.insert(0, project_root)

    # 设置环境变量尝试修复tkinter
    try:
        os.environ['TK_LIBRARY'] = '/usr/local/lib/tcl8.6'
        os.environ['TCL_LIBRARY'] = '/usr/local/lib/tcl8.6'
    except:
        pass

    if check_tkinter():
        print("✅ tkinter 可用，启动现代化 GUI 界面...")
        try:
            # 导入并运行现代化GUI  
            sys.path.insert(0, os.path.join(project_root, 'tools', 'launchers'))
            import kronos_modern_gui

            # 直接调用main函数而不是创建类实例
            kronos_modern_gui.main()
        except Exception as e:
            print(f"现代化GUI启动失败: {e}")
            print("回退到原生界面...")
            fallback_to_native()
    else:
        print("⚠️  tkinter 不可用，启动原生 macOS 界面...")
        fallback_to_native()


def fallback_to_native():
    """回退到原生界面"""
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 非 macOS 平台直接回退到命令行/基础 GUI，避免错误调用 macOS 原生界面
    if platform.system() != "Darwin":
        print("当前非 macOS 平台，回退到基础界面...")
        try:
            sys.path.insert(0, project_root)
            import kronos_app
            kronos_app.main()
            return
        except Exception as e2:
            print(f"命令行界面启动失败: {e2}")
            return

    try:
        sys.path.insert(0, os.path.join(project_root, 'tools', 'launchers'))
        import kronos_native_macos
        kronos_native_macos.main()
    except Exception as e:
        print(f"原生界面启动失败: {e}")
        print("启动命令行界面...")
        try:
            sys.path.insert(0, project_root)
            import kronos_app
            kronos_app.main()
        except Exception as e2:
            print(f"命令行界面也启动失败: {e2}")
            try:
                subprocess.run(
                    [
                        'osascript',
                        '-e',
                        f'''display dialog "Kronos 启动失败，所有界面都不可用。

错误信息: {str(e2)}

请尝试：
1. 运行一键安装脚本
2. 检查 Python 环境
3. 联系技术支持" with title "Kronos 启动错误" buttons {{"确定"}} default button 1 with icon stop''',
                    ],
                    check=False,
                )
            except Exception:
                print("无法显示错误对话框，程序退出")


if __name__ == "__main__":
    main()
