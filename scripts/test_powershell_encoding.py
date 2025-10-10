# -*- coding: utf-8 -*-
"""
PowerShell编码测试脚本
用于测试Windows打包后PowerShell脚本的编码是否正确
"""

import os
import sys
import subprocess
import platform
from pathlib import Path


def test_powershell_encoding():
    """
    测试PowerShell脚本的编码
    """
    print("🧪 测试PowerShell脚本编码...")

    # 获取当前脚本所在目录
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent

    ps1_file = base_path / 'quick_start.ps1'

    if not ps1_file.exists():
        print(f"❌ 未找到PowerShell文件: {ps1_file}")
        return False

    try:
        # 测试PowerShell脚本语法
        print(f"📝 测试PowerShell文件: {ps1_file}")

        # 使用PowerShell检查语法
        cmd = [
            'powershell',
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-Command',
            f'Get-Content "{ps1_file}" -Encoding UTF8 | Out-Null; Write-Host "PowerShell文件编码测试通过"'
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

        if result.returncode == 0:
            print("✅ PowerShell文件编码测试通过")
            print(f"输出: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ PowerShell文件编码测试失败")
            print(f"错误: {result.stderr}")
            return False

    except Exception as e:
        print(f"❌ 测试PowerShell编码时出错: {e}")
        return False


def test_powershell_execution():
    """
    测试PowerShell脚本执行
    """
    print("🚀 测试PowerShell脚本执行...")

    # 获取当前脚本所在目录
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent

    ps1_file = base_path / 'quick_start.ps1'
    run_script = base_path / 'run_powershell.bat'

    if not ps1_file.exists():
        print(f"❌ 未找到PowerShell文件: {ps1_file}")
        return False

    try:
        # 测试执行PowerShell脚本（只测试帮助选项，不实际安装）
        print("📝 测试PowerShell脚本执行...")

        if run_script.exists():
            # 使用批处理脚本执行
            cmd = [str(run_script), '11']  # 11是帮助选项
        else:
            # 直接执行PowerShell
            cmd = [
                'powershell',
                '-NoProfile',
                '-ExecutionPolicy', 'Bypass',
                '-Command',
                f'chcp 65001; & "{ps1_file}" 11'
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)

        if result.returncode == 0:
            print("✅ PowerShell脚本执行测试通过")
            print(f"输出: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ PowerShell脚本执行测试失败")
            print(f"错误: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("❌ PowerShell脚本执行超时")
        return False
    except Exception as e:
        print(f"❌ 测试PowerShell执行时出错: {e}")
        return False


def main():
    """
    主测试函数
    """
    print("🔧 PowerShell编码修复测试")
    print("=" * 50)

    if platform.system() != "Windows":
        print("⚠️ 此测试仅在Windows系统上有效")
        return

    success = True
    success &= test_powershell_encoding()
    success &= test_powershell_execution()

    print("\n" + "=" * 50)
    if success:
        print("✅ 所有测试通过！PowerShell编码修复成功")
    else:
        print("❌ 部分测试失败，需要进一步修复")
        sys.exit(1)


if __name__ == '__main__':
    main()
