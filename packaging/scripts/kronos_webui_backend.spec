# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the self-contained WebUI backend used by Tauri.

源码保护说明（务实级）
========================
PyInstaller 把 *模块*（.py 源码）通过 hiddenimports 收集后编译进 PYZ
（字节码，_internal/base_library.zip + PYZ-00.pyz），而 datas 仅承载运行期
*数据文件*（模板/静态资源/配置/权重等）。

历史版本曾把 analysis/ scripts/ webui/ model/ 等整目录原样塞进 datas，导致
opportunity_scorer.py、kronos.py 等核心算法的 .py 明文随包发行，可被直接打开
阅读。本 spec 改用 _project_data_files() 只收集非源码数据文件，源码一律走
hiddenimports → PYZ 字节码。build_backend.py 还会在打包后扫除残留 .py/.pyi。
"""

from pathlib import Path

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).parents[1]
bundle_mode = os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "lite").lower()
include_ml = bundle_mode == "full"

# 源码/构建产物后缀：这些一律 *不* 作为 datas 进包（模块走 PYZ 字节码，
# 开发文档与缓存对运行无意义）。.py 进包 = 明文泄漏，是本修复要消除的根因。
_SOURCE_SUFFIXES = {".py", ".pyc", ".pyi", ".pyo"}
_DEV_SUFFIXES = {".md", ".rst", ".toml", ".cfg", ".ini", ".spec", ".log", ".sh", ".bat", ".ps1", ".lock"}
_SKIP_NAMES = {".DS_Store", "requirements.txt", "Thumbs.db", ".gitkeep", ".gitignore", "LICENSE", "LICENSE.txt"}
_SKIP_DIRS = {"__pycache__", "tests", "test", "__tests__", ".pytest_cache", ".mypy_cache", ".git"}


def _project_data_files(rel_dir, dest=None, extra_skip=()):
    """收集项目目录下的运行期 *数据文件*，绝不带 .py 源码。

    返回 [(src_abs, dest_rel_dir), ...]，仅供 Analysis(datas=...) 使用。
    Python 模块由 hiddenimports 收集编译进 PYZ；这里只挑出运行期真正需要
    读文件的非源码资源（templates/static/config/权重/json 等）。.DS_Store、
    requirements.txt、安装脚本等开发/系统杂物一并不进包。
    """
    src_dir = project_root / rel_dir
    dest = dest or rel_dir
    out = []
    if not src_dir.exists():
        return out
    skip_suffixes = _SOURCE_SUFFIXES | _DEV_SUFFIXES | set(extra_skip)
    for path in src_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name in _SKIP_NAMES:
            continue
        if path.suffix in skip_suffixes:
            continue
        rel = path.relative_to(src_dir)
        out.append((str(path), str(Path(dest) / rel.parent)))
    return out


# 仅运行期数据文件进包；源码模块走 hiddenimports → PYZ。
# 注意：tushare_config.json 的真实 token 在打包前须由 build_backend.py 清空
# （见 _strip_secrets_from_config），此处只负责搬运文件。
datas = []
datas += _project_data_files("webui")          # templates/ static/（.html/.js/.css/.json）
datas += _project_data_files("analysis")       # 量化模型/规则附带的 .json/.yaml 数据
datas += _project_data_files("config")         # 运行期配置（token 已清空）
datas += _project_data_files("data_store")     # sqlite/json 数据底座
datas += _project_data_files("assets")         # 图标/图片
datas += _project_data_files("model")          # 模型权重/.json（不含 .py）
# resources/ utils/ scripts/ 的非 .py 文件仅为安装脚本/文档，运行期不需要，不打包。
# examples/ finetune/ figures/ tools/ 为开发期产物，整体不打包。

datas += collect_data_files("plotly")
datas += collect_data_files("robyn")

hiddenimports = [
    "flask",
    "flask_cors",
    "jinja2",
    "httpx",
    "robyn",
    "numpy",
    "pandas",
    "plotly",
    "requests",
    "aiohttp",
    "playwright",
    "tushare",
    "baostock",
    "bs4",
    "fake_useragent",
    # 设备验证: license_service 函数内延迟导入设备指纹模块(finetune 是 PEP420
    # 命名空间包, 不在下方 collect_submodules 之列), 需显式收进 PYZ。
    "finetune.license_system.device_fingerprint",
    "scripts.run_opportunity_discovery",
    "scripts.hot_stocks_fetcher",
    "scripts.stock_filter_utils",
    "scripts.opportunity_report_generator",
    "scripts.auto_backtest",
    "scripts.fetch_data",
    "scripts.crawler",
    "scripts.eastmoney_crawler",
    "scripts.tonghuashun_crawler",
    "scripts.xueqiu_crawler",
    "scripts.data_processor",
    "scripts.anti_crawler",
    "scripts.anti_crawler_helper",
    "scripts.browser_manager",
    "scripts.simulate_v5_backtest",
    "scripts.generate_xueqiu_article",
    "scripts.build_pattern_fingerprints",
]
if include_ml:
    datas += collect_data_files("modelscope", excludes=["**/test/**", "**/tests/**", "**/examples/**"])
    hiddenimports += [
        "torch",
        "huggingface_hub",
        "modelscope",
        "safetensors",
        "einops",
    ]
hiddenimports += collect_submodules("webui")
hiddenimports += collect_submodules("analysis")
hiddenimports += collect_submodules("data_store")
hiddenimports += collect_submodules("httpx")
hiddenimports += collect_submodules("robyn")
if include_ml:
    hiddenimports += collect_submodules("model")


a = Analysis(
    [str(project_root / "packaging" / "scripts" / "kronos_webui_backend.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(project_root / "packaging" / "hooks")],
    hooksconfig={},
    runtime_hooks=[str(project_root / "packaging" / "hooks" / "runtime_hook_torch_macos.py")],
    excludes=[
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "tests",
        "unittest",
        "doctest",
        *([] if include_ml else [
            "torch",
            "modelscope",
            "huggingface_hub",
            "safetensors",
            "einops",
            "transformers",
            "sympy",
        ]),
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kronos_webui_backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="kronos_webui_backend",
)
