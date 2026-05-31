"""Sentiment cache repository.

Stores arbitrary JSON-serializable payloads keyed by (cache_type, identifier).
TTL is enforced by callers — repo just records `updated_at`.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Dict, Iterable, Optional, Tuple

from data_store.connection import get_conn


def get(cache_type: str, identifier: str = "") -> Optional[Tuple[dict, float]]:
    """Return (payload_dict, updated_at_epoch_seconds) or None if absent."""
    row = get_conn().execute(
        "SELECT payload, updated_at FROM sentiment_cache WHERE cache_type=? AND identifier=?",
        (cache_type, identifier),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row[0])
    except json.JSONDecodeError:
        return None
    epoch = _dt.datetime.fromisoformat(row[1]).timestamp()
    return payload, epoch


def set_(cache_type: str, data: dict, identifier: str = "") -> None:
    """Upsert payload. `data` will be JSON-encoded."""
    get_conn().execute(
        """
        INSERT INTO sentiment_cache(cache_type, identifier, payload, updated_at, ttl_seconds)
        VALUES(?,?,?,?,0)
        ON CONFLICT(cache_type, identifier) DO UPDATE SET
          payload=excluded.payload, updated_at=excluded.updated_at
        """,
        (
            cache_type,
            identifier,
            json.dumps(data, ensure_ascii=False),
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )


def delete(cache_type: str, identifier: str = "") -> int:
    cur = get_conn().execute(
        "DELETE FROM sentiment_cache WHERE cache_type=? AND identifier=?",
        (cache_type, identifier),
    )
    return cur.rowcount or 0


def clear_all() -> int:
    cur = get_conn().execute("DELETE FROM sentiment_cache")
    return cur.rowcount or 0


def clear_expired(ttl_by_type: Dict[str, int], default_ttl: int = 600) -> int:
    """Delete rows older than per-type TTL. Returns number removed."""
    now = _dt.datetime.now()
    removed = 0
    conn = get_conn()
    types = {r[0] for r in conn.execute("SELECT DISTINCT cache_type FROM sentiment_cache")}
    for ctype in types:
        ttl = int(ttl_by_type.get(ctype, default_ttl))
        threshold = (now - _dt.timedelta(seconds=ttl)).isoformat(timespec="seconds")
        cur = conn.execute(
            "DELETE FROM sentiment_cache WHERE cache_type=? AND updated_at < ?",
            (ctype, threshold),
        )
        removed += cur.rowcount or 0
    return removed


def count() -> int:
    row = get_conn().execute("SELECT COUNT(*) FROM sentiment_cache").fetchone()
    return int(row[0]) if row else 0


def count_by_type() -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in get_conn().execute(
        "SELECT cache_type, COUNT(*) FROM sentiment_cache GROUP BY cache_type"
    ):
        out[row[0]] = int(row[1])
    return out
