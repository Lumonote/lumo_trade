#!/usr/bin/env python3
"""Build the self-contained WebUI backend used by Tauri packages."""

from __future__ import annotations

import argparse
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

TORCH_DYLIBS = {
    "libc10.dylib",
    "libomp.dylib",
    "libshm.dylib",
    "libtorch.dylib",
    "libtorch_cpu.dylib",
    "libtorch_python.dylib",
}


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

    if args.clean:
        shutil.rmtree(DIST_PATH / "kronos_webui_backend", ignore_errors=True)
        shutil.rmtree(WORK_PATH, ignore_errors=True)
        shutil.rmtree(CONFIG_PATH, ignore_errors=True)

    CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    MPL_CONFIG_PATH.mkdir(parents=True, exist_ok=True)
    XDG_CACHE_PATH.mkdir(parents=True, exist_ok=True)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

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
