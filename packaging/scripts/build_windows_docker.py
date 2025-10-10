#!/usr/bin/env python3
"""
Kronos Windows Docker 构建脚本
用于在Docker容器中构建Windows版本的Kronos应用
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import time


class WindowsDockerBuilder:
    def __init__(self):
        self.project_root = Path('C:/kronos')
        self.build_dir = self.project_root / 'build'
        self.dist_dir = self.project_root / 'dist'
        self.packaging_dir = self.project_root / 'packaging'

    def setup_environment(self):
        """设置构建环境"""
        print("🔧 设置Windows构建环境...")

        # 创建必要的目录
        self.build_dir.mkdir(exist_ok=True)
        self.dist_dir.mkdir(exist_ok=True)

        # 清理之前的构建
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir, ignore_errors=True)
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir, ignore_errors=True)

        print("✅ 环境设置完成")

    def create_windows_spec(self):
        """创建Windows专用的spec文件"""
        spec_content = '''# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# Windows Docker构建环境下的项目根目录
project_root = 'C:/kronos'

block_cipher = None

a = Analysis(
    [os.path.join(project_root, 'tools/launchers/kronos_modern_gui.py')],
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'finetune/license_system/'), 'finetune/license_system/') if os.path.exists(os.path.join(project_root, 'finetune/license_system/')) else (),
        (os.path.join(project_root, 'tools/'), 'tools/'),
        (os.path.join(project_root, 'scripts/'), 'scripts/'),
        (os.path.join(project_root, 'examples/'), 'examples/'),
        (os.path.join(project_root, 'config/'), 'config/'),
        (os.path.join(project_root, 'webui/'), 'webui/'),
        (os.path.join(project_root, 'model/'), 'model/'),
        (os.path.join(project_root, 'analysis/'), 'analysis/'),
        (os.path.join(project_root, 'requirements.txt'), '.'),
        (os.path.join(project_root, 'quick_start.sh'), '.'),
        (os.path.join(project_root, 'quick_start.bat'), '.'),
    ],
    hiddenimports=[
        'json', 'hashlib', 'platform', 'threading', 'subprocess',
        'pathlib', 'datetime', 'uuid', 're', 'os', 'sys',
        'tkinter', 'tkinter.ttk', 'tkinter.messagebox', 'tkinter.font',
        'tkinter.scrolledtext', 'tkinter.filedialog', 'tkinter.simpledialog',
        'tkinter.colorchooser', 'tempfile', 'webbrowser', 'asyncio',
        'concurrent.futures', '_tkinter', 'PIL', 'PIL.Image',
        'PIL.ImageTk', 'requests', 'aiohttp', 'playwright',
    ],
    hookspath=['packaging/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython', 'jupyter', 'notebook', 'test', 'tests',
        'unittest', 'pdb', 'doctest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Kronos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/kronos_ai_stock.ico' if os.path.exists('assets/kronos_ai_stock.ico') else None,
)
'''

        spec_file = self.project_root / 'kronos_windows_docker.spec'
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(spec_content)

        print("✅ Windows spec文件创建完成")
        return spec_file

    def build_application(self):
        """构建Windows应用程序"""
        print("🚀 开始构建Windows应用程序...")

        spec_file = self.create_windows_spec()

        # 运行PyInstaller
        cmd = [
            'pyinstaller',
            '--clean',
            '--noconfirm',
            str(spec_file)
        ]

        print(f"执行命令: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=1800  # 30分钟超时
            )

            if result.returncode == 0:
                print("✅ PyInstaller构建成功")
                print("构建输出:")
                print(result.stdout)
            else:
                print("❌ PyInstaller构建失败")
                print("错误输出:")
                print(result.stderr)
                return False

        except subprocess.TimeoutExpired:
            print("❌ 构建超时（30分钟）")
            return False
        except Exception as e:
            print(f"❌ 构建过程中发生错误: {e}")
            return False

        return True

    def create_installer(self):
        """创建Windows安装包"""
        print("📦 创建Windows安装包...")

        exe_file = self.dist_dir / 'Kronos.exe'
        if not exe_file.exists():
            print("❌ 找不到构建的exe文件")
            return False

        # 创建便携版目录结构
        portable_dir = self.dist_dir / 'Kronos_Windows_Portable'
        portable_dir.mkdir(exist_ok=True)

        # 复制exe文件
        shutil.copy2(exe_file, portable_dir / 'Kronos.exe')

        # 创建启动脚本
        batch_script = portable_dir / 'start_kronos.bat'
        with open(batch_script, 'w', encoding='utf-8') as f:
            f.write('''@echo off
echo 🚀 Starting Kronos...
cd /d "%~dp0"
Kronos.exe
pause
''')

        # 创建README
        readme_file = portable_dir / 'README.txt'
        with open(readme_file, 'w', encoding='utf-8') as f:
            f.write('''Kronos Windows Portable Version
================================

使用说明:
1. 双击 Kronos.exe 启动应用
2. 或者双击 start_kronos.bat 启动（会显示控制台输出）

系统要求:
- Windows 10/11 (x64)
- .NET Framework 4.8+

注意事项:
- 首次运行可能需要管理员权限
- 杀毒软件可能会误报，请添加到白名单
- 数据文件会保存到 Documents/Kronos 目录

版本信息:
- 构建时间: ''' + time.strftime('%Y-%m-%d %H:%M:%S') + '''
- 构建环境: Docker Windows Container
''')

        print(f"✅ Windows便携版创建完成: {portable_dir}")
        return True

    def run_build(self):
        """执行完整的构建流程"""
        print("🚀 Kronos Windows Docker 构建器启动")
        print("=" * 50)

        try:
            # 1. 设置环境
            self.setup_environment()

            # 2. 构建应用程序
            if not self.build_application():
                print("❌ 应用程序构建失败")
                return 1

            # 3. 创建安装包
            if not self.create_installer():
                print("❌ 安装包创建失败")
                return 1

            print("\n🎉 Windows构建完成!")
            print(f"📁 构建结果: {self.dist_dir}")

            # 列出构建产物
            if self.dist_dir.exists():
                print("\n📦 构建产物:")
                for item in self.dist_dir.iterdir():
                    if item.is_file():
                        size_mb = item.stat().st_size / (1024 * 1024)
                        print(f"  {item.name} ({size_mb:.1f} MB)")
                    elif item.is_dir():
                        print(f"  {item.name}/ (目录)")

            return 0

        except Exception as e:
            print(f"❌ 构建过程中发生错误: {e}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == '__main__':
    builder = WindowsDockerBuilder()
    exit_code = builder.run_build()
    sys.exit(exit_code)
