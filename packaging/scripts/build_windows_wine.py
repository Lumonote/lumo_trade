#!/usr/bin/env python3
"""
使用Wine在Linux容器中构建Windows版本的Kronos
当无法使用原生Windows容器时的备选方案
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import time


class WineWindowsBuilder:
    def __init__(self):
        self.project_root = Path('/kronos')
        self.build_dir = self.project_root / 'build'
        self.dist_dir = self.project_root / 'dist'
        self.wine_python = "wine /root/.wine/drive_c/Program Files/Python311/python.exe"

    def setup_wine_environment(self):
        """设置Wine环境"""
        print("🍷 设置Wine环境...")

        # 启动虚拟显示器
        try:
            subprocess.Popen(['Xvfb', ':99', '-screen', '0', '1024x768x16'])
            time.sleep(2)
            print("✅ 虚拟显示器已启动")
        except Exception as e:
            print(f"⚠️  虚拟显示器启动失败: {e}")

        # 检查Wine Python安装
        try:
            result = subprocess.run(
                self.wine_python.split() + ['--version'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                print(f"✅ Wine Python: {result.stdout.strip()}")
            else:
                raise Exception("Wine Python检查失败")
        except Exception as e:
            print(f"❌ Wine Python环境问题: {e}")
            return False

        return True

    def install_wine_dependencies(self):
        """在Wine环境中安装Python依赖"""
        print("📦 在Wine环境中安装依赖...")

        # 升级pip
        try:
            cmd = self.wine_python.split() + ['-m', 'pip', 'install', '--upgrade', 'pip']
            result = subprocess.run(cmd, timeout=300)
            if result.returncode == 0:
                print("✅ Wine pip已升级")
            else:
                print("⚠️  Wine pip升级失败")
        except Exception as e:
            print(f"⚠️  Wine pip升级异常: {e}")

        # 安装PyInstaller
        try:
            cmd = self.wine_python.split() + ['-m', 'pip', 'install', 'pyinstaller==6.16.0']
            result = subprocess.run(cmd, timeout=600)
            if result.returncode == 0:
                print("✅ Wine PyInstaller已安装")
            else:
                print("❌ Wine PyInstaller安装失败")
                return False
        except Exception as e:
            print(f"❌ Wine PyInstaller安装异常: {e}")
            return False

        # 安装项目依赖
        requirements_file = self.project_root / 'requirements.txt'
        if requirements_file.exists():
            try:
                cmd = self.wine_python.split() + ['-m', 'pip', 'install', '-r', str(requirements_file)]
                result = subprocess.run(cmd, timeout=1800)  # 30分钟
                if result.returncode == 0:
                    print("✅ Wine项目依赖已安装")
                else:
                    print("⚠️  部分Wine依赖安装失败，继续构建...")
            except Exception as e:
                print(f"⚠️  Wine依赖安装异常: {e}")

        return True

    def create_wine_spec(self):
        """创建Wine构建的spec文件"""
        spec_content = '''# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# Wine构建环境下的项目根目录
project_root = '/kronos'

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
        'concurrent.futures', '_tkinter',
    ],
    hookspath=['/kronos/packaging/hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython', 'jupyter', 'notebook', 'test', 'tests',
        'unittest', 'pdb', 'doctest', 'matplotlib', 'numpy',
        'pandas', 'torch',
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
    upx=False,  # 在Wine环境中禁用UPX
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''

        spec_file = self.project_root / 'kronos_wine.spec'
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(spec_content)

        print("✅ Wine spec文件创建完成")
        return spec_file

    def build_with_wine(self):
        """使用Wine构建Windows应用"""
        print("🚀 使用Wine构建Windows应用...")

        spec_file = self.create_wine_spec()

        # 清理之前的构建
        if self.dist_dir.exists():
            shutil.rmtree(self.dist_dir)
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)

        # 运行PyInstaller
        cmd = self.wine_python.split() + [
            '-m', 'PyInstaller',
            '--clean',
            '--noconfirm',
            str(spec_file)
        ]

        print(f"执行命令: {' '.join(cmd)}")

        try:
            # 设置Wine环境变量
            env = os.environ.copy()
            env['DISPLAY'] = ':99'
            env['WINEPREFIX'] = '/root/.wine'

            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                env=env,
                timeout=3600  # 1小时超时
            )

            if result.returncode == 0:
                print("✅ Wine构建成功")
                return True
            else:
                print("❌ Wine构建失败")
                return False

        except subprocess.TimeoutExpired:
            print("❌ Wine构建超时（1小时）")
            return False
        except Exception as e:
            print(f"❌ Wine构建异常: {e}")
            return False

    def create_portable_package(self):
        """创建便携版包"""
        print("📦 创建便携版包...")

        exe_file = self.dist_dir / 'Kronos.exe'
        if not exe_file.exists():
            print("❌ 找不到构建的exe文件")
            return False

        # 创建便携版目录
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
            f.write('''Kronos Windows Portable Version (Wine Build)
==============================================

使用说明:
1. 双击 Kronos.exe 启动应用
2. 或者双击 start_kronos.bat 启动（会显示控制台输出）

系统要求:
- Windows 10/11 (x64)
- .NET Framework 4.8+

注意事项:
- 本版本使用Wine在Linux环境中构建
- 首次运行可能需要管理员权限
- 杀毒软件可能会误报，请添加到白名单
- 数据文件会保存到 Documents/Kronos 目录

构建信息:
- 构建时间: ''' + time.strftime('%Y-%m-%d %H:%M:%S') + '''
- 构建环境: Wine on Linux Container
- 构建方式: Docker + Wine
''')

        print(f"✅ 便携版包创建完成: {portable_dir}")
        return True

    def run_build(self):
        """执行完整的构建流程"""
        print("🍷 Kronos Wine Windows 构建器启动")
        print("=" * 50)

        try:
            # 1. 设置Wine环境
            if not self.setup_wine_environment():
                return 1

            # 2. 安装Wine依赖
            if not self.install_wine_dependencies():
                return 1

            # 3. 构建应用
            if not self.build_with_wine():
                return 1

            # 4. 创建便携版包
            if not self.create_portable_package():
                return 1

            print("\n🎉 Wine Windows构建完成!")
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
    builder = WineWindowsBuilder()
    exit_code = builder.run_build()
    sys.exit(exit_code)
