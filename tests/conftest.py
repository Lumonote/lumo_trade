import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """提供临时 SQLite 数据库路径，测试结束自动清理。"""
    return tmp_path / "test_fingerprints.db"
