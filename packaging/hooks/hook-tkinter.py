# PyInstaller hook to ensure tkinter is properly included
import os
import sys


def get_hook_dirs():
    return []


def get_hook_modules():
    return ['tkinter', '_tkinter']


hiddenimports = [
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.font',
    'tkinter.scrolledtext',
    'tkinter.filedialog',
    'tkinter.simpledialog',
    'tkinter.colorchooser',
    '_tkinter',
]

# Collect tkinter data files
datas = []

# Find tkinter directory
try:
    import tkinter

    tkinter_dir = os.path.dirname(tkinter.__file__)

    # Include tcl library files
    tcl_lib_dirs = [
        '/usr/local/lib/tcl8.6',
        '/usr/local/lib/tk8.6',
        '/usr/local/opt/tcl-tk/lib/tcl8.6',
        '/usr/local/opt/tcl-tk/lib/tk8.6',
    ]

    for tcl_dir in tcl_lib_dirs:
        if os.path.exists(tcl_dir):
            datas.append((tcl_dir, os.path.basename(tcl_dir)))

except ImportError:
    pass
