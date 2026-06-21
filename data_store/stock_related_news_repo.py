"""个股关联新闻缓存：每次刷新整体替换该 code 的记录（缓存优先+按需刷新）。"""
from __future__ import annotations

from typing import Any, Dict, List

from data_store.connection import get_conn

_TIER_ORDER = {"direct": 0, "board": 1, "peer": 2, "theme": 3, "orbit": 4}


def replace_for_code(code: str, items: List[Dict[str, Any]], fetched_at: str) -> int:
    conn = get_conn()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM stock_related_news WHERE code=?", (code,))
        n = 0
        for it in items:
            conn.execute(
                """INSERT OR IGNORE INTO stock_related_news
                   (code, tier, title, url, source, published_at,
                    relation_reason, sentiment, content_hash, fetched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (code, it.get("tier"), it.get("title"), it.get("url"),
                 it.get("source"), it.get("published_at"), it.get("relation_reason"),
                 it.get("sentiment"), it.get("content_hash"), fetched_at),
            )
            n += 1
        conn.execute("COMMIT")
        return n
    except Exception:
        conn.execute("ROLLBACK")
        raise


def latest_for_code(code: str) -> Dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM stock_related_news WHERE code=? ", (code,)
    ).fetchall()
    if not rows:
        return {"items": [], "fetched_at": None}
    items = [dict(r) for r in rows]
    items.sort(key=lambda r: _TIER_ORDER.get(r.get("tier"), 9))
    return {"items": items, "fetched_at": items[0].get("fetched_at")}
