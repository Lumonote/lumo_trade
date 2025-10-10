# -*- coding: utf-8 -*-
"""
PyInstaller hook for PowerShell files
确保PowerShell文件在打包后保持正确的UTF-8编码
"""

import os
import sys
from pathlib import Path


def hook(hook_api):
    """
    PyInstaller hook to handle PowerShell files
    """
    # 获取项目根目录
    project_root = Path(hook_api.__file__).parent.parent.parent

    # 查找PowerShell文件
    ps1_files = [
        project_root / 'quick_start.ps1',
    ]

    for ps1_file in ps1_files:
        if ps1_file.exists():
            print(f"🔧 处理PowerShell文件: {ps1_file}")

            # 读取原始文件内容
            try:
                with open(ps1_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 确保文件以UTF-8 BOM开头（Windows PowerShell需要）
                if not content.startswith('\ufeff'):
                    content = '\ufeff' + content

                # 将文件添加到数据文件
                hook_api.add_datas([(str(ps1_file), '.')])

                print(f"✅ PowerShell文件已添加到打包数据: {ps1_file}")

            except Exception as e:
                print(f"❌ 处理PowerShell文件失败: {e}")
                continue
