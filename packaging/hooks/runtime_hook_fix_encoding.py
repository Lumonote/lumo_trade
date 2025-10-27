# -*- coding: utf-8 -*-
"""
PyInstaller Runtime Hook - 修复PowerShell文件编码
在程序启动时立即运行，确保quick_start.ps1具有正确的UTF-8 BOM编码
"""

import os
import sys
import codecs


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

        # 读取文件内容（使用UTF-8编码读取，忽略错误）
        try:
            with open(ps1_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except:
            # 如果UTF-8读取失败，尝试用二进制模式读取并解码
            with open(ps1_file, 'rb') as f:
                raw_content = f.read()
                # 移除可能存在的BOM
                if raw_content.startswith(b'\xef\xbb\xbf'):
                    raw_content = raw_content[3:]
                # 尝试多种编码
                for enc in ['utf-8', 'gbk', 'gb2312', 'cp936']:
                    try:
                        content = raw_content.decode(enc)
                        break
                    except:
                        continue
                else:
                    # 所有编码都失败，使用errors='replace'
                    content = raw_content.decode('utf-8', errors='replace')

        # 重新写入文件，确保UTF-8 BOM编码
        with codecs.open(ps1_file, 'w', encoding='utf-8-sig') as f:
            f.write(content)

        # 静默修复，不打印信息（避免干扰用户界面）

    except Exception as e:
        # 静默失败，不影响程序启动
        # 但在开发模式下可以看到错误
        if not getattr(sys, 'frozen', False):
            print(f"Warning: Failed to fix PowerShell encoding: {e}")
        pass


# 在模块导入时立即执行
fix_powershell_encoding()
