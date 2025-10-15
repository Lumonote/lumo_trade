# -*- mode: python ; coding: utf-8 -*-
import sys
import os

# 获取项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH)))

block_cipher = None

a = Analysis(
    ['kronos_launcher.py'],
    pathex=[project_root],
    binaries=[],
    datas=[
        (os.path.join(project_root, 'tools'), 'tools'),
        (os.path.join(project_root, 'assets'), 'assets'),
        (os.path.join(project_root, 'config'), 'config'),
        (os.path.join(project_root, 'scripts'), 'scripts'),
        (os.path.join(project_root, 'examples'), 'examples'),
        (os.path.join(project_root, 'model'), 'model'),
        (os.path.join(project_root, 'analysis'), 'analysis'),
        (os.path.join(project_root, 'resources'), 'resources'),
        (os.path.join(project_root, 'quick_start.sh'), '.'),
        (os.path.join(project_root, 'requirements.txt'), '.'),
    ],
    hiddenimports=[
        'json',
        'base64',
        'hashlib',
        'platform',
        'threading',
        'time',
        'subprocess',
        'psutil',
        'webbrowser',
        'http.server',
        'urllib.parse',
        'python_detector',
        'tkinter',
        'tkinter.ttk',
        'tkinter.font',
        'tkinter.scrolledtext',
        '_tkinter',
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
    [],
    exclude_binaries=True,
    name='Kronos_Ultra',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    name='Kronos_Ultra',
)

app = BUNDLE(
    coll,
    name='Kronos_Ultra.app',
    icon=os.path.join(project_root, 'assets/kronos_ai_stock.icns') if os.path.exists(os.path.join(project_root, 'assets/kronos_ai_stock.icns')) else None,
    bundle_identifier='com.kronos.app',
)
