#!/usr/bin/env python3
"""Packaged WebUI backend entry for the Tauri desktop shell."""

from __future__ import annotations

import os
import sys
import types
from importlib import metadata
from pathlib import Path

CANONICAL_USER_DIR_NAME = "com.kronos.app"


def _torch_disabled() -> bool:
    if os.environ.get("KRONOS_BACKEND_BUNDLE_MODE", "lite").lower() == "lite":
        return True
    return os.environ.get("KRONOS_DISABLE_TORCH", "0").lower() in {"1", "true", "yes"}


def _server_mode() -> str:
    return os.environ.get("KRONOS_WEB_SERVER", "robyn").strip().lower() or "robyn"


def _install_disabled_ml_modules() -> None:
    model_module = types.ModuleType("model")

    def _raise_disabled(*_args, **_kwargs):
        raise ImportError("Kronos model dependencies are disabled in this backend bundle")

    model_module.__all__ = ["Kronos", "KronosTokenizer", "KronosPredictor"]

    def _model_getattr(name):
        if name in model_module.__all__:
            _raise_disabled()
        raise AttributeError(name)

    model_module.__getattr__ = _model_getattr

    modelscope_module = types.ModuleType("modelscope")
    modelscope_module.snapshot_download = _raise_disabled

    sys.modules["model"] = model_module
    sys.modules["modelscope"] = modelscope_module


def _resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _project_root() -> Path:
    configured = os.environ.get("KRONOS_PROJECT_ROOT")
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    return _resource_root()


def _default_user_dir() -> Path:
    if os.environ.get("KRONOS_USER_DIR"):
        return Path(os.environ["KRONOS_USER_DIR"]).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / CANONICAL_USER_DIR_NAME
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / CANONICAL_USER_DIR_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / CANONICAL_USER_DIR_NAME


def _configure_runtime() -> Path:
    root = _project_root()
    user_dir = _default_user_dir()
    cache_dir = user_dir / "cache"
    os.environ["KRONOS_PROJECT_ROOT"] = str(root)
    os.environ.setdefault("KRONOS_USER_DIR", str(user_dir))
    os.environ.setdefault("KRONOS_DESKTOP", "tauri")
    os.environ.setdefault("KRONOS_HOST", "127.0.0.1")
    os.environ.setdefault("KRONOS_PORT", "7070")
    os.environ.setdefault("FLASK_DEBUG", "0")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if _torch_disabled():
        os.environ.setdefault("KRONOS_DISABLE_TORCH", "1")
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir / "xdg"))
    os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(cache_dir / "huggingface" / "hub"))
    os.environ.setdefault("MODELSCOPE_CACHE", str(cache_dir / "modelscope"))
    os.environ.setdefault("MODELSCOPE_CREDENTIALS_PATH", str(user_dir / "config" / "modelscope_credentials"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir / "matplotlib"))
    os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch"))

    for path in (
        user_dir,
        cache_dir,
        Path(os.environ["HF_HOME"]),
        Path(os.environ["HUGGINGFACE_HUB_CACHE"]),
        Path(os.environ["MODELSCOPE_CACHE"]),
        Path(os.environ["MPLCONFIGDIR"]),
        Path(os.environ["TORCH_HOME"]),
        Path(os.environ["MODELSCOPE_CREDENTIALS_PATH"]).parent,
    ):
        path.mkdir(parents=True, exist_ok=True)

    _seed_sqlite_if_missing(root, user_dir)

    sys.path.insert(0, str(root))
    os.chdir(str(root))
    return root


def _seed_sqlite_if_missing(resource_root: Path, user_dir: Path) -> None:
    """Copy the bundled kronos_data.sqlite to user_dir on first launch.

    The packaged app ships a snapshot of the analyzed database under
    `<bundle>/data/kronos_data.sqlite`. The user-facing DB lives under
    `<user_dir>/data/kronos_data.sqlite`. We copy the bundle copy once if the
    destination is missing or empty so a fresh install has data to render.
    Subsequent launches keep whatever the user has accumulated.
    """
    dest_dir = user_dir / "data"
    dest = dest_dir / "kronos_data.sqlite"
    src = resource_root / "data" / "kronos_data.sqlite"

    if not src.exists():
        return

    needs_seed = (not dest.exists()) or dest.stat().st_size < 4096
    if not needs_seed:
        return

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(src, dest)
        print(f"[seed] kronos_data.sqlite -> {dest}", flush=True)
    except Exception as exc:
        print(f"[seed] copy failed: {exc}", flush=True)


def _run_import_check() -> int:
    _configure_runtime()
    distribution_names = {
        "modelscope.snapshot_download": "modelscope",
        "webui.app": None,
        "model": None,
    }

    def version_for(module_name: str, loaded: object) -> str:
        if loaded == "disabled":
            return "disabled"
        distribution_name = distribution_names.get(module_name, module_name.split(".", 1)[0])
        if distribution_name:
            try:
                return metadata.version(distribution_name)
            except metadata.PackageNotFoundError:
                pass
        return str(getattr(loaded, "__version__", "ok"))

    checks = [
        ("numpy", lambda: __import__("numpy")),
        ("pandas", lambda: __import__("pandas")),
        ("plotly", lambda: __import__("plotly")),
        ("httpx", lambda: __import__("httpx")),
        ("flask", lambda: __import__("flask")),
        ("robyn", lambda: __import__("robyn")),
        ("webui.app", lambda: __import__("webui.app", fromlist=["app"])),
    ]
    if _server_mode() == "robyn":
        checks.append(("webui.robyn_app", lambda: __import__("webui.robyn_app", fromlist=["app"])))
    if _torch_disabled():
        checks.append(("torch", lambda: "disabled"))
        checks.append(("modelscope.snapshot_download", lambda: "disabled"))
        checks.append(("model", lambda: "disabled"))
        _install_disabled_ml_modules()
    else:
        checks.extend([
            ("torch", lambda: __import__("torch")),
            ("modelscope.snapshot_download", lambda: getattr(__import__("modelscope", fromlist=["snapshot_download"]), "snapshot_download")),
            ("model", lambda: __import__("model")),
        ])
    failed = False
    for module_name, loader in checks:
        try:
            module = loader()
            print(f"{module_name}: {version_for(module_name, module)}")
        except Exception as exc:
            failed = True
            print(f"{module_name}: FAILED {type(exc).__name__}: {exc}")
    return 1 if failed else 0


def main() -> None:
    if "--import-check" in sys.argv:
        raise SystemExit(_run_import_check())

    _configure_runtime()
    if _torch_disabled():
        _install_disabled_ml_modules()
    from webui.robyn_app import run_server

    run_server()


if __name__ == "__main__":
    main()
