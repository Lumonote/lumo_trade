"""Trade calendar repository (Shanghai exchange canonical)."""
from __future__ import annotations

from typing import Iterable, List

from data_store.connection import get_conn


def upsert(dates: Iterable[str], is_open: int = 1) -> int:
    """Upsert calendar entries. `dates` are strings like '20260524'."""
    rows = [(str(d), int(is_open)) for d in dates if d]
    if not rows:
        return 0
    cur = get_conn().executemany(
        """
        INSERT INTO trade_calendar(cal_date, is_open) VALUES(?, ?)
        ON CONFLICT(cal_date) DO UPDATE SET is_open=excluded.is_open
        """,
        rows,
    )
    return cur.rowcount if cur.rowcount is not None else len(rows)


def open_days() -> List[str]:
    return [
        row[0]
        for row in get_conn().execute(
            "SELECT cal_date FROM trade_calendar WHERE is_open=1 ORDER BY cal_date ASC"
        )
    ]


def has_data() -> bool:
    row = get_conn().execute("SELECT COUNT(*) FROM trade_calendar").fetchone()
    return bool(row and row[0])


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM trade_calendar").fetchone()
    return int(row[0]) if row else 0
