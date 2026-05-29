"""Survey (机构调研) repository.

Table: jgdy_detail. PK: (ts_code, survey_date, inst_name).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from data_store.connection import get_conn


_FIELDS = (
    "ts_code", "survey_date", "inst_name", "reception", "topic",
)

_PK = ("ts_code", "survey_date", "inst_name")


def upsert_rows(rows: List[Dict]) -> int:
    """Insert or update rows. Returns number of rows affected."""
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_FIELDS))
    set_clause = ", ".join(
        f"{c}=excluded.{c}" for c in _FIELDS if c not in _PK
    )
    values = [
        tuple(_to_native(r.get(c)) for c in _FIELDS) for r in rows
    ]
    cur = get_conn().executemany(
        f"""
        INSERT INTO jgdy_detail({",".join(_FIELDS)}) VALUES({placeholders})
        ON CONFLICT({",".join(_PK)}) DO UPDATE SET {set_clause}
        """,
        values,
    )
    return cur.rowcount if cur.rowcount else len(values)


def get_by_code(ts_code: str, since: Optional[str] = None) -> pd.DataFrame:
    """Get survey records for a stock, optionally filtered by since date."""
    if since:
        return pd.read_sql_query(
            f"SELECT {','.join(_FIELDS)} FROM jgdy_detail "
            "WHERE ts_code=? AND survey_date>=? ORDER BY survey_date DESC",
            get_conn(), params=(ts_code, since),
        )
    return pd.read_sql_query(
        f"SELECT {','.join(_FIELDS)} FROM jgdy_detail "
        "WHERE ts_code=? ORDER BY survey_date DESC",
        get_conn(), params=(ts_code,),
    )


def _to_native(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float, str)):
        return v
    return str(v)
