# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

a = Analysis(
    ['kronos_debug.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('finetune/license_system/', 'finetune/license_system/') if os.path.exists('finetune/license_system/') else (),
        ('kronos_with_license.py', '.'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog', 
        'tkinter.messagebox',
        'json',
        'base64',
        'hashlib',
        'platform',
        'threading',
        'time',
        'subprocess',
        'psutil',
        'traceback',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.serialization', 
        'cryptography.hazmat.primitives.asymmetric.padding',
    ],
    hookspath=[],
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
        'matplotlib',
        'numpy',
        'pandas',
        'torch',
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
    name='KronosDebug',
    debug=True,  # 启用调试模式
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 强制显示控制台
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)