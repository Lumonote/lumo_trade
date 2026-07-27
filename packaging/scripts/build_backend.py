#!/usr/bin/env python3
"""Build the self-contained WebUI backend used by Tauri packages."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = PROJECT_ROOT / "packaging" / "scripts" / "kronos_webui_backend.spec"
DIST_PATH = PROJECT_ROOT / "packaging" / "backend"
WORK_PATH = PROJECT_ROOT / "build" / "pyinstaller_backend"
CONFIG_PATH = PROJECT_ROOT / "build" / "pyinstaller_config"
MPL_CONFIG_PATH = PROJECT_ROOT / "build" / "matplotlib_config"
XDG_CACHE_PATH = PROJECT_ROOT / "build" / "xdg_cache"

# 打包产物里不允许残留明文源码的后缀（模块已编译进 PYZ，留 .py 等于泄漏）。
_PLAINTEXT_SOURCE_SUFFIXES = (".py", ".pyi", ".pyc", ".pyo")
# 运行期无意义、白白增加体积/暴露信息的文件名/后缀。
_DEV_DOC_SUFFIXES = (".md", ".rst", ".spec", ".log")
_DEV_DOC_NAMES = {".DS_Store", "requirements.txt", "LICENSE", "LICENSE.txt"}
# 仅扫除「本项目自有源码目录」下的残留；第三方包目录保持原样避免误伤。
_PROJECT_SOURCE_DIRS = ("analysis", "scripts", "webui", "model", "utils", "tools", "examples", "finetune", "resources")
# 打包版配置里必须清空的敏感字段路径（点分）；用户运行时在 user_root/config 自行填入。
_SECRET_CONFIG_PATHS = {
    "config/tushare_config.json": ("tushare", "token"),
}

TORCH_DYLIBS = {
    "libc10.dylib",
    "libomp.dylib",
    "libshm.dylib",
    "libtorch.dylib",
    "libtorch_cpu.dylib",
    "libtorch_python.dylib",
}

# PyInstaller only warns when a hidden import is unavailable and can still
# produce an unusable executable. Keep this list aligned with requirements.txt
# and the modules collected by kronos_webui_backend.spec so the build fails (or
# installs the missing wheel) before spending minutes creating the bundle.
_LITE_BUILD_REQUIREMENTS = (
    ("PyInstaller", "pyinstaller"),
    ("numpy", "numpy>=2.1.0"),
    ("pandas", "pandas>=2.2.3"),
    ("pytz", "pytz>=2022.1"),
    ("matplotlib", "matplotlib>=3.9.0"),
    ("tqdm", "tqdm"),
    ("requests", "requests>=2.31.0"),
    ("httpx", "httpx>=0.27.0"),
    ("aiohttp", "aiohttp>=3.11.0"),
    ("bs4", "beautifulsoup4"),
    ("fake_useragent", "fake-useragent"),
    ("tushare", "tushare>=1.4.0"),
    ("akshare", "akshare>=1.16.0"),
    ("baostock", "baostock"),
    ("robyn", "robyn>=0.84.0,<1.0"),
    ("jinja2", "jinja2>=3.1.0"),
    ("plotly", "plotly>=5.20.0"),
    ("flask", "flask>=3.0.0"),
    ("flask_cors", "flask-cors>=4.0.0"),
    ("playwright", "playwright>=1.49.0"),
    ("yaml", "pyyaml>=6.0"),
)

_FULL_BUILD_REQUIREMENTS = (
    ("torch", "torch>=2.5.0"),
    ("einops", "einops"),
    ("huggingface_hub", "huggingface_hub>=0.33.1"),
    ("modelscope", "modelscope>=1.20.0"),
    ("safetensors", "safetensors"),
)


def _build_requirements(mode: str) -> tuple[tuple[str, str], ...]:
    if mode == "full":
        return _LITE_BUILD_REQUIREMENTS + _FULL_BUILD_REQUIREMENTS
    return _LITE_BUILD_REQUIREMENTS


def _missing_build_requirements(mode: str) -> list[tuple[str, str]]:
    return [
        (module_name, requirement)
        for module_name, requirement in _build_requirements(mode)
        if importlib.util.find_spec(module_name) is None
    ]


def _ensure_build_dependencies(mode: str) -> None:
    missing = _missing_build_requirements(mode)
    if not missing:
        print(f"[DEPS] Backend build dependencies are ready ({mode}).")
        return

    module_names = ", ".join(module_name for module_name, _requirement in missing)
    requirements = [requirement for _module_name, requirement in missing]
    command = [sys.executable, "-m", "pip", "install", *requirements]
    print(f"[DEPS] Missing backend build dependencies: {module_names}")
    print(f"[DEPS] Installing with: {sys.executable}")
    try:
        subprocess.check_call(command, cwd=str(PROJECT_ROOT))
    except (OSError, subprocess.CalledProcessError) as exc:
        install_command = subprocess.list2cmdline(command)
        raise RuntimeError(
            "Failed to install desktop backend dependencies with the Python "
            f"used for this build. Run this command and retry:\n{install_command}"
        ) from exc

    importlib.invalidate_caches()
    still_missing = _missing_build_requirements(mode)
    if still_missing:
        unresolved = ", ".join(module_name for module_name, _requirement in still_missing)
        raise RuntimeError(
            "pip completed, but these desktop backend modules are still unavailable "
            f"to {sys.executable}: {unresolved}"
        )


def _install_name_tool_available() -> bool:
    return shutil.which("install_name_tool") is not None


def _run_install_name_tool(*args: str) -> None:
    subprocess.run(["install_name_tool", *args], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fix_macos_torch_rpaths(bundle_dir: Path) -> None:
    """Keep PyTorch dylibs loadable from one canonical torch/lib path."""
    if sys.platform != "darwin" or not _install_name_tool_available():
        return

    internal_dir = bundle_dir / "_internal"
    torch_dir = internal_dir / "torch"
    torch_lib_dir = torch_dir / "lib"
    if not torch_lib_dir.exists():
        return

    torch_exts = list(torch_dir.glob("_C*.so"))
    for ext in torch_exts:
        _run_install_name_tool("-delete_rpath", "@loader_path/..", str(ext))
        _run_install_name_tool("-add_rpath", "@loader_path/lib", str(ext))

    for dylib in torch_lib_dir.glob("*.dylib"):
        _run_install_name_tool("-delete_rpath", "@loader_path/../..", str(dylib))
        _run_install_name_tool("-add_rpath", "@loader_path", str(dylib))

    for name in TORCH_DYLIBS:
        root_link = internal_dir / name
        if root_link.is_symlink():
            root_link.unlink()


def _adhoc_codesign_macos(bundle_dir: Path) -> None:
    # install_name_tool invalidates PyInstaller's ad-hoc signatures, and macOS
    # 26 refuses to dlopen any binary with a stale signature. Re-sign every
    # dylib/.so plus the bootloader so dyld accepts them at runtime.
    if sys.platform != "darwin" or not shutil.which("codesign"):
        return
    targets = list(bundle_dir.rglob("*.dylib")) + list(bundle_dir.rglob("*.so"))
    main_exe = bundle_dir / "kronos_webui_backend"
    if main_exe.exists():
        targets.append(main_exe)
    for target in targets:
        if not target.is_file():
            continue
        subprocess.run(
            ["codesign", "--force", "--sign", "-", "--timestamp=none", str(target)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _strip_plaintext_source(bundle_dir: Path) -> int:
    """扫除产物里本项目自有目录下残留的明文源码/开发文档。

    spec 已用 _project_data_files() 只搬数据文件，这里做兜底：万一某子目录
    整目录被 collect 进来（或第三方 hook 带入），仍把 .py/.pyi/.pyc/README
    等抹掉，确保只余字节码（在 PYZ 内）与运行期数据文件。返回删除文件数。
    """
    removed = 0
    internal = bundle_dir / "_internal"
    if not internal.exists():
        return 0
    scan_roots = [internal / d for d in _PROJECT_SOURCE_DIRS if (internal / d).exists()]
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name
            if name in _DEV_DOC_NAMES or path.suffix in _PLAINTEXT_SOURCE_SUFFIXES or path.suffix in _DEV_DOC_SUFFIXES:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    # _internal 顶层也清掉 requirements.txt / README* 等泄漏信息。
    for name in ("requirements.txt", "README.md", "README.rst", "LICENSE", "LICENSE.txt"):
        victim = internal / name
        if victim.exists():
            try:
                victim.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _strip_secrets_from_config(bundle_dir: Path) -> int:
    """把打包版配置中的真实 token 清空。

    用户运行时由 configuration_service 从 user_root/config 覆盖（首启会从打包
    版 bootstrap 一份到用户目录），所以打包配置应为「空 token 模板」。返回清
    空的字段数。源码目录 config/tushare_config.json 本身保留开发者本机用的
    token（不进包），这里只处理 bundle 内的拷贝。
    """
    import json

    internal = bundle_dir / "_internal"
    cleaned = 0
    for rel, key_path in _SECRET_CONFIG_PATHS.items():
        cfg = internal / rel
        if not cfg.exists():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            continue
        node = data
        ok = True
        for k in key_path[:-1]:
            if not isinstance(node, dict) or k not in node:
                ok = False
                break
            node = node[k]
        if ok and isinstance(node, dict) and key_path[-1] in node:
            if node[key_path[-1]]:
                node[key_path[-1]] = ""
                cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                cleaned += 1
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description="Build bundled Kronos WebUI backend")
    parser.add_argument("--clean", action="store_true", help="remove previous backend build first")
    parser.add_argument(
        "--mode",
        choices=("lite", "full"),
        default=os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "lite"),
        help="bundle mode: lite excludes torch/modelscope; full includes ML inference dependencies",
    )
    args = parser.parse_args()

    _ensure_build_dependencies(args.mode)

    if args.clean:
        shutil.rmtree(DIST_PATH / "kronos_webui_backend", ignore_errors=True)
        shutil.rmtree(WORK_PATH, ignore_errors=True)
        shutil.rmtree(CONFIG_PATH, ignore_errors=True)

    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    MPL_CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    XDG_CACHE_PATH.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(DIST_PATH),
        "--workpath",
        str(WORK_PATH),
        str(SPEC_PATH),
    ]
    env = os.environ.copy()
    env.setdefault("PYINSTALLER_CONFIG_DIR", str(CONFIG_PATH))
    env.setdefault("MPLCONFIGDIR", str(MPL_CONFIG_PATH))
    env.setdefault("XDG_CACHE_HOME", str(XDG_CACHE_PATH))
    env.setdefault("PYTHONUTF8", "1")
    env["KRONOS_BACKEND_BUNDLE_MODE"] = args.mode
    env.setdefault("KRONOS_WEB_SERVER", os.environ.get("KRONOS_WEB_SERVER", "robyn"))

    subprocess.check_call(cmd, cwd=str(PROJECT_ROOT), env=env)

    bundle_dir = DIST_PATH / "kronos_webui_backend"
    if args.mode == "full":
        _fix_macos_torch_rpaths(bundle_dir)
    _adhoc_codesign_macos(bundle_dir)

    # 源码保护（务实级）：扫除残留明文 .py 源码 + 清空打包配置中的真实 token。
    removed_src = _strip_plaintext_source(bundle_dir)
    removed_secret = _strip_secrets_from_config(bundle_dir)
    if removed_src or removed_secret:
        print(f"安全清理: 移除明文/开发文件 {removed_src} 个, 清空敏感字段 {removed_secret} 处")

    executable = bundle_dir / (
        "kronos_webui_backend.exe" if sys.platform == "win32" else "kronos_webui_backend"
    )
    if not executable.exists():
        raise FileNotFoundError(f"backend executable was not produced: {executable}")
    (bundle_dir / ".bundle_mode").write_text(args.mode + "\n", encoding="utf-8")
    (bundle_dir / ".web_server").write_text(env["KRONOS_WEB_SERVER"] + "\n", encoding="utf-8")
    print(f"Bundled backend built ({args.mode}): {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
