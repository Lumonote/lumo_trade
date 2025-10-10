# -*- mode: python ; coding: utf-8 -*-
# Kronos macOS 打包配置

import sys
import os
from pathlib import Path

block_cipher = None

# 项目根目录
project_root = Path(__file__).parent.parent

a = Analysis(
    ['kronos_app.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        ('examples/', 'examples/'),
        ('scripts/', 'scripts/'),
        ('config/', 'config/'),
        ('webui/', 'webui/'),
        ('README.md', '.'),
        ('requirements.txt', '.'),
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
        'webbrowser',
        'os',
        'sys',
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
