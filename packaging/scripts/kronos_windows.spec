# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from pathlib import Path
from datetime import datetime

# 动态获取项目根目录 - 使用更可靠的方法
try:
    # 尝试使用__file__
    spec_dir = Path(__file__).parent
    project_root = str(spec_dir.parent.parent)
except NameError:
    # 如果__file__未定义，使用当前工作目录的相对路径
    spec_dir = Path(os.getcwd()) / 'packaging' / 'scripts'
    project_root = str(spec_dir.parent.parent)

print(f"🔍 检测到项目根目录: {project_root}")
print(f"🔍 Spec文件目录: {spec_dir}")

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
        (os.path.join(project_root, 'resources/'), 'resources/'),
        (os.path.join(project_root, 'requirements.txt'), '.'),
        (os.path.join(project_root, 'quick_start.sh'), '.'),
        (os.path.join(project_root, 'quick_start.ps1'), '.'),
        (os.path.join(project_root, 'quick_start.bat'), '.'),
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
        '_tkinter',
        'torch',
        'torch.nn',
        'torch.nn.functional',
        'torch.optim',
        'numpy',
        'pandas',
        'matplotlib',
    ],
    hookspath=['packaging/hooks'],
    hooksconfig={},
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

_dist_dir = Path('dist')
_default_name = 'Kronos_Ultra'
_default_path = _dist_dir / f'{_default_name}.exe'

# 尝试删除已存在的同名EXE（保持统一命名 Kronos.exe）
_exe_name = _default_name
try:
    if _default_path.exists():
        print(f"⚠️ 检测到已存在EXE: {_default_path}，尝试删除以覆盖...")
        _default_path.unlink()
except Exception as _e:
    print(f"⚠️ 无法删除旧EXE（可能被占用）：{_e}，请确保未运行 Kronos.exe")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=_exe_name,
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
    version=os.path.join(project_root, 'docs/version_info.txt') if os.path.exists(os.path.join(project_root, 'docs/version_info.txt')) else None,
    icon=os.path.join(project_root, 'assets/kronos_ai_stock.ico') if os.path.exists(os.path.join(project_root, 'assets/kronos_ai_stock.ico')) else None,
)

# 打印构建完成信息
print(f"🎉 Windows EXE构建完成!")
print(f"📁 输出文件: dist/{_exe_name}.exe")
print(f"📊 预期最终位置: packaging/builds/Kronos_Ultra_v<version>_Windows_<timestamp>.zip")