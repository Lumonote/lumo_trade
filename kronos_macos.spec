# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None

a = Analysis(
    ['tools/launchers/kronos_modern_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('finetune/license_system/', 'finetune/license_system/') if os.path.exists('finetune/license_system/') else (),
        ('tools/', 'tools/'),
        ('scripts/', 'scripts/'),
        ('examples/', 'examples/'),
        ('config/', 'config/'),
        ('webui/', 'webui/'),
        ('model/', 'model/'),
        ('analysis/', 'analysis/'),
        ('requirements.txt', '.'),
        ('quick_start.sh', '.'),
        ('quick_start.bat', '.'),
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
    ],
    hookspath=['packaging/hooks'],
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
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Kronos',
)

app = BUNDLE(
    coll,
    name='Kronos.app',
    icon='assets/kronos_ai_stock.icns',
    bundle_identifier='ai.kronos.app',
    version='1.0.0',
    info_plist={
        'CFBundleDisplayName': 'Kronos 专业版',
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.13',
        'CFBundleDocumentTypes': [],
        'NSRequiresAquaSystemAppearance': False,
    },
)
