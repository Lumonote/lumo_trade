# -*- mode: python ; coding: utf-8 -*-
# Kronos Windows 打包配置

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

print(f"🔍 检测到项目根目录: {project_root}")

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
        (os.path.join(project_root, 'quick_start.ps1'), '.'),
        (os.path.join(project_root, 'quick_start.bat'), '.'),
        (os.path.join(project_root, 'quick_start.sh'), '.'),
        (os.path.join(project_root, 'run_powershell.bat'), '.'),
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
    hooksconfig={},
    runtime_hooks=[],
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
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
