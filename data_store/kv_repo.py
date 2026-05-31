"""Generic key-value cache repository.

Used for ad-hoc JSON blobs (hot stocks snapshot, misc lookups). TTL is
recorded but enforced by the caller (mirroring sentiment_repo semantics).
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Optional, Tuple

from data_store.connection import get_conn


def get(namespace: str, key: str) -> Optional[Tuple[Any, float]]:
    row = get_conn().execute(
        "SELECT payload, updated_at FROM kv_cache WHERE namespace=? AND key=?",
        (namespace, key),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    epoch = _dt.datetime.fromisoformat(row[1]).timestamp()
    return payload, epoch


def set_(namespace: str, key: str, payload: Any, ttl_seconds: int = 0) -> None:
    get_conn().execute(
        """
        INSERT INTO kv_cache(namespace, key, payload, updated_at, ttl_seconds)
        VALUES(?,?,?,?,?)
        ON CONFLICT(namespace, key) DO UPDATE SET
          payload=excluded.payload, updated_at=excluded.updated_at,
          ttl_seconds=excluded.ttl_seconds
        """,
        (
            namespace,
            key,
            json.dumps(payload, ensure_ascii=False),
            _dt.datetime.now().isoformat(timespec="seconds"),
            int(ttl_seconds),
        ),
    )


def delete(namespace: str, key: str) -> int:
    cur = get_conn().execute(
        "DELETE FROM kv_cache WHERE namespace=? AND key=?", (namespace, key)
    )
    return cur.rowcount or 0


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM kv_cache").fetchone()
    return int(row[0]) if row else 0
