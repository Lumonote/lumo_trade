# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the self-contained WebUI backend used by Tauri."""

from pathlib import Path

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).parents[1]
bundle_mode = os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "lite").lower()
include_ml = bundle_mode == "full"

datas = [
    (str(project_root / "analysis"), "analysis"),
    (str(project_root / "assets"), "assets"),
    (str(project_root / "config" / "crawler_config.json"), "config"),
    (str(project_root / "config" / "comprehensive_data_sources.json"), "config"),
    (str(project_root / "config" / "llm_provider_config.json"), "config"),
    (str(project_root / "config" / "related_entities.json"), "config"),
    (str(project_root / "config" / "scoring_runtime_config.json"), "config"),
    (str(project_root / "config" / "trading_client_adapters.json"), "config"),
    (str(project_root / "data_store"), "data_store"),
    (str(project_root / "examples"), "examples"),
    (str(project_root / "figures"), "figures"),
    (str(project_root / "finetune"), "finetune"),
    (str(project_root / "model"), "model"),
    (str(project_root / "resources"), "resources"),
    (str(project_root / "scripts"), "scripts"),
    (str(project_root / "tools"), "tools"),
    (str(project_root / "utils"), "utils"),
    (str(project_root / "webui"), "webui"),
    (str(project_root / "requirements.txt"), "."),
]

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
