# -*- coding: utf-8 -*-
"""
PyInstaller Runtime Hook - 修复PowerShell文件编码
在程序启动时立即运行，确保quick_start.ps1具有正确的UTF-8 BOM编码
"""

import os
import sys


def fix_powershell_encoding():
    """修复PowerShell文件的UTF-8 BOM编码"""
    try:
        # 获取程序运行目录（PyInstaller会将文件解压到这里）
        if getattr(sys, 'frozen', False):
            # 打包后运行
            base_dir = sys._MEIPASS
        else:
            # 开发环境
            return

        # 需要修复的PowerShell文件
        ps1_file = os.path.join(base_dir, 'quick_start.ps1')

        if not os.path.exists(ps1_file):
            return

        # 读取文件内容（二进制模式）
        with open(ps1_file, 'rb') as f:
            content = f.read()

        # 检查是否已有UTF-8 BOM
        if content.startswith(b'\xef\xbb\xbf'):
            # 已经有BOM，无需修复
            return

        # 添加UTF-8 BOM并写回文件
        with open(ps1_file, 'wb') as f:
            f.write(b'\xef\xbb\xbf')  # UTF-8 BOM
            f.write(content)

        # 静默修复，不打印信息（避免干扰用户界面）

    except Exception:
        # 静默失败，不影响程序启动
        pass


# 在模块导入时立即执行
fix_powershell_encoding()
