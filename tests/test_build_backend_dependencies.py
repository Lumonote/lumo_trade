import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_build_backend_module():
    path = ROOT / "packaging/scripts/build_backend.py"
    spec = importlib.util.spec_from_file_location("desktop_build_backend", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lite_build_installs_missing_runtime_dependencies_with_current_python(monkeypatch):
    module = _load_build_backend_module()
    missing_modules = {"plotly", "httpx", "flask", "robyn"}
    installed = False
    calls = []

    def fake_find_spec(name):
        if name in missing_modules and not installed:
            return None
        return object()

    def fake_check_call(command, **_kwargs):
        nonlocal installed
        calls.append(command)
        installed = True

    monkeypatch.setattr(module.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(module.subprocess, "check_call", fake_check_call)

    module._ensure_build_dependencies("lite")

    assert len(calls) == 1
    command = calls[0]
    assert command[:4] == [sys.executable, "-m", "pip", "install"]
    assert "plotly>=5.20.0" in command
    assert "httpx>=0.27.0" in command
    assert "flask>=3.0.0" in command
    assert "robyn>=0.84.0,<1.0" in command
    assert not any(requirement.startswith("torch") for requirement in command)


def test_full_build_installs_ml_dependencies_but_lite_build_does_not(monkeypatch):
    module = _load_build_backend_module()
    missing_modules = {"torch", "huggingface_hub", "modelscope", "safetensors", "einops"}
    installed = False
    calls = []

    def fake_find_spec(name):
        if name in missing_modules and not installed:
            return None
        return object()

    def fake_check_call(command, **_kwargs):
        nonlocal installed
        calls.append(command)
        installed = True

    monkeypatch.setattr(module.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(module.subprocess, "check_call", fake_check_call)

    module._ensure_build_dependencies("lite")
    assert calls == []

    module._ensure_build_dependencies("full")
    assert len(calls) == 1
    assert "torch>=2.5.0" in calls[0]
    assert "modelscope>=1.20.0" in calls[0]


def test_dependency_install_failure_reports_the_interpreter_and_packages(monkeypatch):
    module = _load_build_backend_module()

    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda name: None if name == "robyn" else object(),
    )

    def fail_install(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module.subprocess, "check_call", fail_install)

    with pytest.raises(RuntimeError) as exc_info:
        module._ensure_build_dependencies("lite")

    message = str(exc_info.value)
    assert sys.executable in message
    assert "robyn>=0.84.0,<1.0" in message


def test_dependency_install_rechecks_that_modules_are_available(monkeypatch):
    module = _load_build_backend_module()

    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda name: None if name == "robyn" else object(),
    )
    monkeypatch.setattr(module.subprocess, "check_call", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="robyn"):
        module._ensure_build_dependencies("lite")
