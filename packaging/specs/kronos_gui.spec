# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

a = Analysis(
    ['kronos_gui_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('finetune/license_system/', 'finetune/license_system/') if os.path.exists('finetune/license_system/') else (),
        ('scripts/', 'scripts/') if os.path.exists('scripts/') else (),
        ('examples/', 'examples/') if os.path.exists('examples/') else (),
        ('requirements.txt', '.'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog', 
        'tkinter.messagebox',
        'tkinter.simpledialog',
        'tkinter.scrolledtext',
        'json',
        'base64',
        'hashlib',
        'platform',
        'threading',
        'time',
        'subprocess',
        'queue',
        'pathlib',
        'psutil',
        'uuid',
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
    name='Kronos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI应用
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)