#!/usr/bin/env python3
"""Preflight checks for the Python 3.12/3.13 dependency upgrade."""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import os
import platform
import re
import sys
import tempfile
from dataclasses import dataclass
from typing import Iterable


MIN_PYTHON = (3, 11)
VALIDATED_PYTHON_MAX = (3, 13)


@dataclass(frozen=True)
class PackageCheck:
    display: str
    distribution: str
    import_name: str
    minimum: str | None = None
    required: bool = True


CORE_PACKAGES = [
    PackageCheck("numpy", "numpy", "numpy", "2.1.0"),
    PackageCheck("pandas", "pandas", "pandas", "2.2.3"),
    PackageCheck("torch", "torch", "torch", "2.5.0"),
    PackageCheck("matplotlib", "matplotlib", "matplotlib", "3.9.0"),
    PackageCheck("huggingface_hub", "huggingface_hub", "huggingface_hub", "0.33.1"),
    PackageCheck("safetensors", "safetensors", "safetensors"),
    PackageCheck("einops", "einops", "einops"),
    PackageCheck("requests", "requests", "requests", "2.31.0"),
    PackageCheck("aiohttp", "aiohttp", "aiohttp", "3.11.0"),
    PackageCheck("playwright", "playwright", "playwright", "1.49.0"),
    PackageCheck("modelscope", "modelscope", "modelscope", "1.20.0"),
]

WEBUI_PACKAGES = [
    PackageCheck("plotly", "plotly", "plotly", "5.17.0"),
    PackageCheck("httpx", "httpx", "httpx", "0.27.0"),
    PackageCheck("robyn", "robyn", "robyn", "0.84.0"),
]

DATA_SOURCE_PACKAGES = [
    PackageCheck("tushare", "tushare", "tushare", "1.4.0", required=False),
    PackageCheck("baostock", "baostock", "baostock", required=False),
    PackageCheck("beautifulsoup4", "beautifulsoup4", "bs4", required=False),
    PackageCheck("fake-useragent", "fake-useragent", "fake_useragent", required=False),
]


def parse_version(version: str | None) -> tuple[int, ...]:
    """Extract numeric version parts from a PEP 440-ish version string."""
    if not version:
        return ()
    match = re.match(r"(\d+(?:\.\d+)*)", version)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def version_at_least(actual: str, minimum: str) -> bool:
    actual_parts = parse_version(actual)
    minimum_parts = parse_version(minimum)
    width = max(len(actual_parts), len(minimum_parts))
    return actual_parts + (0,) * (width - len(actual_parts)) >= minimum_parts + (0,) * (width - len(minimum_parts))


def check_python() -> int:
    version = sys.version_info
    current = f"{version.major}.{version.minor}.{version.micro}"
    print(f"Python: {current} ({platform.platform()})")

    if version[:2] < MIN_PYTHON:
        print(f"  FAIL: Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]} is required")
        return 1

    if version[:2] > VALIDATED_PYTHON_MAX:
        print("  WARN: this Python version is newer than the validated 3.13 target")
    else:
        print("  OK")
    return 0


def check_packages(packages: Iterable[PackageCheck], title: str) -> int:
    print(f"\n{title}:")
    failures = 0

    for package in packages:
        try:
            installed_version = metadata.version(package.distribution)
        except metadata.PackageNotFoundError:
            status = "FAIL" if package.required else "WARN"
            print(f"  {status}: {package.display} is not installed")
            failures += int(package.required)
            continue

        try:
            importlib.import_module(package.import_name)
        except Exception as exc:
            status = "FAIL" if package.required else "WARN"
            print(f"  {status}: {package.display} {installed_version} import failed: {exc}")
            failures += int(package.required)
            continue

        if package.minimum and not version_at_least(installed_version, package.minimum):
            status = "FAIL" if package.required else "WARN"
            print(
                f"  {status}: {package.display} {installed_version} "
                f"< required {package.minimum}"
            )
            failures += int(package.required)
            continue

        print(f"  OK: {package.display} {installed_version}")

    return failures


def main() -> int:
    os.environ.setdefault(
        "MPLCONFIGDIR",
        os.path.join(tempfile.gettempdir(), "kronos_matplotlib_config"),
    )
    os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

    failures = check_python()
    failures += check_packages(CORE_PACKAGES, "Core packages")
    failures += check_packages(WEBUI_PACKAGES, "WebUI packages")
    failures += check_packages(DATA_SOURCE_PACKAGES, "Data source packages")

    print("\nRecommended follow-up smoke tests:")
    print("  python scripts/check_environment.py")
    print("  python scripts/validate_models.py")
    print("  python -m pytest tests/test_pattern_store.py tests/test_pattern_matcher.py")

    if failures:
        print(f"\nFAIL: {failures} required runtime checks failed")
        return 1

    print("\nOK: runtime upgrade preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
