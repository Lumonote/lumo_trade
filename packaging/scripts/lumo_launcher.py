#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Lumo macOS 应用启动器
"""

import sys
import os
from pathlib import Path

# 获取正确的资源路径
if getattr(sys, 'frozen', False):
    # 打包后的应用
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 临时目录
        bundle_dir = Path(sys._MEIPASS)
    else:
        # .app 包
        bundle_dir = Path(sys.executable).parent.parent / "Resources"
else:
    # 开发环境
    bundle_dir = Path(__file__).parent.parent.parent

# 添加到 Python 路径
sys.path.insert(0, str(bundle_dir))
sys.path.insert(0, str(bundle_dir / "tools"))
sys.path.insert(0, str(bundle_dir / "tools" / "launchers"))

# 设置工作目录
os.chdir(str(bundle_dir))

if __name__ == "__main__":
    try:
        # 导入并运行现代化GUI
        from tools.launchers import lumo_modern_gui

        lumo_modern_gui.main()
    except Exception as e:
        import traceback

        error_msg = f"启动失败: {e}\n{traceback.format_exc()}"
        print(error_msg)

        # 尝试显示错误对话框
        try:
            import subprocess

            subprocess.run(['osascript', '-e', f'''
                display dialog "Lumo 启动失败:\\n\\n{str(e)}" with title "错误" buttons {{"确定"}} default button 1 with icon stop
            '''], check=False)
        except:
            pass

        sys.exit(1)
