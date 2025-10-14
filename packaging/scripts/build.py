#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 跨平台打包工具
支持 Windows 和 macOS 平台的自动化打包
"""

import os
import sys
import platform
import subprocess
import json
from pathlib import Path
import shutil

# 添加tools目录到Python路径
sys.path.append(str(Path(__file__).parent.parent.parent / "tools"))
from python_detector import get_python_detector, verify_python_environment


class KronosPackager:
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.builds_dir = self.project_root / "packaging" / "builds"
        self.current_os = platform.system()
        # 版本配置默认值
        self.version_config = {}
        self.version = "1.0.0"
        self.short_version = "1.0"
        self.channel = "stable"
        self.artifact_template = "Kronos_v{version}_{platform}_{timestamp}"
        self.notes_file = None

        # 确保构建目录存在
        self.builds_dir.mkdir(parents=True, exist_ok=True)

        print("🚀 Kronos 跨平台打包工具")
        print(f"📁 项目根目录: {self.project_root}")
        print(f"💻 当前系统: {self.current_os}")
        print(f"📦 构建输出目录: {self.builds_dir}")
        print("=" * 50)

        # 加载版本配置
        self.load_version_config()

    def check_requirements(self):
        """检查打包环境要求"""
        print("🔍 检查打包环境...")

        if not self.check_python():
            print("❌ Python环境检查失败")
            return False

        if not self.check_pyinstaller():
            print("❌ PyInstaller检查失败")
            return False

        if not (self.project_root / "tools" / "launchers" / "kronos_modern_gui.py").exists():
            print("❌ 主程序文件不存在")
            return False

        print("✅ 环境检查通过")
        return True

    def check_python(self):
        """检查Python版本和环境"""
        print("🐍 检查Python环境...")

        try:
            detector = get_python_detector()
            if not detector:
                print("❌ 无法检测到Python环境")
                return False

            python_cmd = detector.get_command()
            print(f"✅ 检测到Python: {python_cmd}")

            # 验证Python环境
            try:
                result = subprocess.run([python_cmd, '--version'],
                                        capture_output=True, text=True, check=True)
                version = result.stdout.strip()
                print(f"✅ Python版本: {version}")

                # 检查Python版本是否符合要求 (>= 3.8)
                import re
                version_match = re.search(r'Python (\d+)\.(\d+)', version)
                if version_match:
                    major, minor = int(version_match.group(1)), int(version_match.group(2))
                    if major < 3 or (major == 3 and minor < 8):
                        print(f"❌ Python版本过低，需要Python 3.8+，当前版本: {major}.{minor}")
                        return False

                return True

            except subprocess.CalledProcessError:
                print("❌ Python命令执行失败")
                return False
        except Exception as e:
            print(f"❌ Python环境检查出错: {e}")
            return False

    def check_pyinstaller(self):
        """检查PyInstaller是否可用"""
        print("📦 检查PyInstaller...")

        try:
            detector = get_python_detector()
            python_cmd = detector.get_command()

            # 检查PyInstaller是否已安装
            result = subprocess.run([python_cmd, '-m', 'PyInstaller', '--version'],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                version = result.stdout.strip()
                print(f"✅ PyInstaller版本: {version}")
                return True
            else:
                print("⚠️ PyInstaller未安装，尝试安装...")
        except Exception:
            print("⚠️ PyInstaller未安装，尝试安装...")

        # 尝试安装PyInstaller
        try:
            detector = get_python_detector()
            python_cmd = detector.get_command()
            subprocess.run([python_cmd, '-m', 'pip', 'install', 'pyinstaller'], check=True)
            print("✅ PyInstaller安装成功")
            return True
        except subprocess.CalledProcessError:
            print("❌ PyInstaller安装失败")
            return False

    def load_version_config(self):
        """加载 packaging/version.json 版本配置"""
        try:
            cfg_path = self.project_root / "packaging" / "version.json"
            if not cfg_path.exists():
                print("⚠️ 未找到版本配置文件 packaging/version.json，使用默认版本设置")
                return
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                self.version_config = cfg
                self.version = cfg.get('version', self.version)
                self.short_version = cfg.get('short_version', self.short_version)
                self.channel = cfg.get('channel', self.channel)
                self.artifact_template = cfg.get('artifact_template', self.artifact_template)
                self.notes_file = cfg.get('notes_file')
                print(f"✅ 已加载版本配置: version={self.version}, short_version={self.short_version}, channel={self.channel}")
        except Exception as e:
            print(f"⚠️ 加载版本配置失败，使用默认值: {e}")

    def create_spec_file(self, platform_type):
        """创建spec文件"""
        print(f"📝 创建{platform_type}平台spec文件...")

        spec_content = self.get_spec_template(platform_type)
        spec_filename = f"kronos_{platform_type.lower()}.spec"
        # 将spec文件创建在packaging/specs目录下
        specs_dir = self.project_root / "packaging" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_path = specs_dir / spec_filename

        with open(spec_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)

        print(f"✅ Spec文件已创建: {spec_path}")
        return spec_path

    def get_spec_template(self, platform_type):
        """获取spec模板"""
        is_windows = platform_type.lower() == 'windows'
        console_mode = 'False'  # 两个平台都使用窗口模式

        # 根据平台类型确定脚本文件扩展名
        primary_ext = 'bat' if is_windows else 'sh'
        backup_ext = 'sh' if is_windows else 'bat'

        return f"""# -*- mode: python ; coding: utf-8 -*-
# Kronos {platform_type} 打包配置

import sys
import os
from pathlib import Path

block_cipher = None

# 动态获取项目根目录
import os
import sys

# 获取spec文件的绝对路径
spec_file_path = os.path.abspath(__file__ if '__file__' in globals() else sys.argv[0])
spec_dir = os.path.dirname(spec_file_path)

# 从 packaging/specs 目录向上找到项目根目录
# spec文件在 packaging/specs/ 下，所以项目根目录是上两级
project_root = os.path.dirname(os.path.dirname(spec_dir))

print(f"🔍 检测到项目根目录: {{project_root}}")

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
        # 根据平台类型包含相应的启动脚本（优先级顺序）
        (os.path.join(project_root, 'quick_start.{primary_ext}'), '.'),
        (os.path.join(project_root, 'quick_start.{backup_ext}'), '.'),
    ],
    hiddenimports=[
        'json',
        'hashlib', 
        'platform',
        'threading',
        'subprocess',
        'pathlib',
        'datetime',
        'uuid',
        're',
        'os',
        'sys',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.font',
        'tkinter.scrolledtext',
        'tkinter.filedialog',
        'tkinter.simpledialog',
        'tkinter.colorchooser',
        'tempfile',
        'webbrowser',
        'asyncio',
        'concurrent.futures',
    ],
    hookspath=[os.path.join(project_root, 'packaging/hooks')],
    hooksconfig={{}},
    runtime_hooks=[os.path.join(project_root, 'packaging/hooks/runtime_hook_fix_encoding.py')],
    excludes=[
        'IPython',
        'jupyter',
        'notebook',
        'test',
        'tests', 
        'unittest',
        'pdb',
        'doctest',
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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console={console_mode},
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
"""

    def validate_version_info(self):
        """验证版本信息文件的语法正确性"""
        version_file = os.path.join(self.project_root, 'docs', 'version_info.txt')
        if not os.path.exists(version_file):
            print("⚠️ 版本信息文件不存在，跳过验证")
            return True

        try:
            import ast
            with open(version_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # 移除注释行并验证语法
                lines = [line for line in content.split('\n')
                         if not line.strip().startswith('#') and line.strip()]
                code = '\n'.join(lines)
                ast.parse(code)
                print("✅ 版本信息文件语法验证通过")
                return True
        except SyntaxError as e:
            print(f"❌ 版本信息文件语法错误: {e}")
            print(f"错误位置: 第{e.lineno}行")
            print("💡 提示: 检查是否有Python 2.x的长整数后缀'L'需要移除")
            return False
        except Exception as e:
            print(f"❌ 验证版本信息文件时出错: {e}")
            return False

    def build_windows(self):
        """构建Windows版本"""
        print("🏢 开始打包Windows版本...")

        if self.current_os != 'Windows':
            print("⚠️  当前系统不是Windows，建议在Windows系统上打包")

        # 验证版本信息文件
        if not self.validate_version_info():
            print("❌ 版本信息文件验证失败，停止构建")
            return False

        # 创建spec文件
        spec_file = self.create_spec_file('Windows')

        # 清理旧的构建文件
        self.clean_build_dirs()

        # 执行PyInstaller
        try:
            detector = get_python_detector()
            python_cmd = detector.get_command()

            cmd = [python_cmd, '-m', 'PyInstaller', '--clean', str(spec_file)]
            print(f"🔧 执行命令: {' '.join(cmd)}")

            result = subprocess.run(cmd, cwd=self.project_root, check=True)
            print("✅ Windows可执行文件创建成功！")

            # 创建安装包
            self.create_windows_installer()

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ Windows打包失败: {e}")
            return False

    def build_macos(self):
        """构建macOS版本"""
        print("🍎 开始打包macOS版本...")

        if self.current_os != 'Darwin':
            print("⚠️  当前系统不是macOS，建议在macOS系统上打包")

        # 创建spec文件
        spec_file = self.create_spec_file('macOS')

        # 清理旧的构建文件
        self.clean_build_dirs()

        # 执行PyInstaller
        try:
            detector = get_python_detector()
            python_cmd = detector.get_command()

            cmd = [python_cmd, '-m', 'PyInstaller', '--clean', str(spec_file)]
            print(f"🔧 执行命令: {' '.join(cmd)}")

            result = subprocess.run(cmd, cwd=self.project_root, check=True)
            print("✅ macOS可执行文件创建成功！")

            # 创建App包
            self.create_macos_app()

            # 创建DMG安装包
            self.create_macos_dmg()

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ macOS打包失败: {e}")
            return False

    def create_windows_installer(self):
        """创建Windows安装包"""
        print("📦 创建Windows安装包...")

        # 查找生成的EXE文件
        dist_dir = self.project_root / "dist"

        # 可能的EXE文件名
        possible_names = ["Kronos_Modern.exe", "Kronos.exe", "kronos_modern_gui.exe"]
        exe_file = None

        for name in possible_names:
            if (dist_dir / name).exists():
                exe_file = dist_dir / name
                print(f"✅ 找到EXE文件: {exe_file}")
                break

        if not exe_file:
            print(f"❌ 未找到Windows EXE文件，检查的位置:")
            for name in possible_names:
                print(f"   - {dist_dir / name}")
            print(f"📁 dist目录内容:")
            if dist_dir.exists():
                for item in dist_dir.iterdir():
                    print(f"   - {item.name}")
            else:
                print("   dist目录不存在")
            return False

        # 复制到统一 builds 目录并按版本配置命名（包含时间戳）
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        build_name = self.artifact_template.format(version=self.version, platform='Windows', timestamp=timestamp) + ".exe"
        final_path = self.builds_dir / build_name
        shutil.copy2(exe_file, final_path)

        # 显示文件信息
        size = final_path.stat().st_size / (1024 * 1024)  # MB

        print(f"✅ Windows版本已保存: {final_path}")
        print(f"📊 文件大小: {size:.1f} MB")
        return True

    def create_macos_app(self):
        """创建macOS App包结构"""
        print("📱 创建macOS App包结构...")

        dist_dir = self.project_root / "dist"
        if not (dist_dir / "Kronos").exists():
            print("❌ 未找到Kronos可执行文件")
            return False

        # 创建App包结构
        app_dir = dist_dir / "Kronos.app"
        contents_dir = app_dir / "Contents"
        macos_dir = contents_dir / "MacOS"
        resources_dir = contents_dir / "Resources"

        # 创建目录结构
        macos_dir.mkdir(parents=True, exist_ok=True)
        resources_dir.mkdir(parents=True, exist_ok=True)

        # 移动可执行文件
        if (macos_dir / "Kronos").exists():
            (macos_dir / "Kronos").unlink()
        shutil.move(str(dist_dir / "Kronos"), str(macos_dir / "Kronos"))

        # 创建Info.plist
        info_plist = contents_dir / "Info.plist"
        with open(info_plist, 'w') as f:
            f.write(self.get_macos_info_plist())

        # 设置可执行权限
        os.chmod(macos_dir / "Kronos", 0o755)

        print("✅ macOS App包创建成功！")
        return True

    def get_macos_info_plist(self):
        """获取macOS Info.plist内容"""
        return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDisplayName</key>
    <string>Kronos</string>
    <key>CFBundleExecutable</key>
    <string>Kronos</string>
    <key>CFBundleIdentifier</key>
    <string>com.kronos.financial</string>
    <key>CFBundleName</key>
    <string>Kronos</string>
    <key>CFBundleShortVersionString</key>
    <string>{self.short_version}</string>
    <key>CFBundleVersion</key>
    <string>{self.version}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppleScriptEnabled</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>"""

    def create_macos_dmg(self):
        """创建macOS DMG安装包"""
        print("💿 创建macOS DMG安装包...")

        dist_dir = self.project_root / "dist"
        app_dir = dist_dir / "Kronos.app"

        if not app_dir.exists():
            print("❌ App包不存在")
            return False

        # 生成带版本与时间戳的DMG名称
        import datetime
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        dmg_name = self.artifact_template.format(version=self.version, platform='macOS', timestamp=timestamp) + ".dmg"
        dmg_path = self.builds_dir / dmg_name

        # 删除已存在的DMG文件
        if dmg_path.exists():
            dmg_path.unlink()

        try:
            cmd = [
                'hdiutil', 'create',
                '-volname', 'Kronos',
                '-srcfolder', str(app_dir),
                '-ov',
                '-format', 'UDZO',
                str(dmg_path)
            ]

            result = subprocess.run(cmd, check=True, capture_output=True)

            print(f"✅ DMG安装包创建成功: {dmg_path}")

            # 显示文件大小
            size_mb = dmg_path.stat().st_size / (1024 * 1024)
            print(f"📏 安装包大小: {size_mb:.1f}M")

            return True

        except subprocess.CalledProcessError as e:
            print(f"❌ DMG创建失败: {e}")
            return False

    def clean_build_dirs(self):
        """清理构建目录"""
        print("🧹 清理构建目录...")

        dirs_to_clean = ['build', 'dist']
        for dir_name in dirs_to_clean:
            dir_path = self.project_root / dir_name
            if dir_path.exists():
                shutil.rmtree(dir_path)

        print("✅ 构建目录清理完成")

    def show_results(self):
        """显示打包结果"""
        print("\n" + "=" * 50)
        print("🎯 打包结果")
        print("=" * 50)

        builds_dir = self.builds_dir
        if builds_dir.exists():
            files = list(builds_dir.glob("*"))
            if files:
                print("📦 生成的安装包:")
                for file in files:
                    size_mb = file.stat().st_size / (1024 * 1024)
                    print(f"  📁 {file.name} ({size_mb:.1f}M)")

                print(f"\n📁 安装包位置: {builds_dir}")
            else:
                print("❌ 未找到生成的安装包")
        else:
            print("❌ 构建目录不存在")

    def run(self):
        """运行打包流程"""
        try:
            # 检查环境
            if not self.check_requirements():
                return False

            while True:
                print("\n请选择打包选项:")
                print("1. 打包当前系统版本")
                print("2. 打包Windows版本")
                print("3. 打包macOS版本")
                print("4. 打包所有平台版本")
                print("5. 清理构建文件")
                print("6. 退出")

                choice = input("\n请选择 (1-6): ").strip()

                success = False

                if choice == '1':
                    if self.current_os == 'Windows':
                        success = self.build_windows()
                    elif self.current_os == 'Darwin':
                        success = self.build_macos()
                    else:
                        print(f"❌ 不支持的操作系统: {self.current_os}")

                elif choice == '2':
                    success = self.build_windows()

                elif choice == '3':
                    success = self.build_macos()

                elif choice == '4':
                    print("🚀 开始打包所有平台版本...")
                    win_success = self.build_windows()
                    mac_success = self.build_macos()
                    success = win_success or mac_success

                elif choice == '5':
                    self.clean_build_dirs()
                    print("✅ 构建文件清理完成")
                    return True

                elif choice == '6':
                    print("👋 退出打包工具")
                    return True

                else:
                    print("❌ 无效选择")
                    return False

                if success:
                    self.show_results()
                    print("\n🎉 打包完成！")
                else:
                    print("\n❌ 打包失败！")

                return success

        except KeyboardInterrupt:
            print("\n👋 用户取消打包")
            return False
        except Exception as e:
            print(f"\n❌ 打包过程中发生错误: {e}")
            return False


def main():
    """主函数"""
    packager = KronosPackager()
    packager.run()


if __name__ == "__main__":
    main()
