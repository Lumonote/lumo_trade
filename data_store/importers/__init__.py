"""Shared helpers for one-shot importer scripts."""
from __future__ import annotations

from data_store.connection import get_conn


def announce(msg: str) -> None:
    print(f"[importer] {msg}")
