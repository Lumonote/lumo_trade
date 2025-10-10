# -*- coding: utf-8 -*-
"""
PowerShell文件编码修复工具
用于修复Windows打包后PowerShell脚本的编码问题
"""

import os
import sys
import shutil
from pathlib import Path


def fix_powershell_encoding():
    """
    修复PowerShell文件的编码问题
    """
    print("🔧 修复PowerShell文件编码...")

    # 获取当前脚本所在目录
    if getattr(sys, 'frozen', False):
        # 如果是打包后的可执行文件
        base_path = Path(sys._MEIPASS)
    else:
        # 如果是开发环境
        base_path = Path(__file__).parent.parent.parent

    ps1_file = base_path / 'quick_start.ps1'

    if not ps1_file.exists():
        print(f"❌ 未找到PowerShell文件: {ps1_file}")
        return False

    try:
        # 读取原始文件内容
        with open(ps1_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 确保文件以UTF-8 BOM开头
        if not content.startswith('\ufeff'):
            content = '\ufeff' + content

        # 写入修复后的内容
        with open(ps1_file, 'w', encoding='utf-8-sig') as f:
            f.write(content)

        print(f"✅ PowerShell文件编码已修复: {ps1_file}")
        return True

    except Exception as e:
        print(f"❌ 修复PowerShell文件编码失败: {e}")
        return False


def ensure_powershell_execution():
    """
    确保PowerShell脚本可以正确执行
    """
    print("🔧 确保PowerShell执行环境...")

    # 获取当前脚本所在目录
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent.parent

    ps1_file = base_path / 'quick_start.ps1'

    if not ps1_file.exists():
        print(f"❌ 未找到PowerShell文件: {ps1_file}")
        return False

    try:
        # 创建PowerShell执行脚本
        exec_script = base_path / 'run_powershell.bat'

        with open(exec_script, 'w', encoding='utf-8') as f:
            f.write(f'''@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "{ps1_file}" %*
''')

        print(f"✅ PowerShell执行脚本已创建: {exec_script}")
        return True

    except Exception as e:
        print(f"❌ 创建PowerShell执行脚本失败: {e}")
        return False


if __name__ == '__main__':
    print("🚀 PowerShell编码修复工具")
    print("=" * 40)

    success = True
    success &= fix_powershell_encoding()
    success &= ensure_powershell_execution()

    if success:
        print("✅ PowerShell环境修复完成")
    else:
        print("❌ PowerShell环境修复失败")
        sys.exit(1)
