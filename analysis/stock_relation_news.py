"""关联新闻聚合：5 层(直接/板块/同行/题材/星轨)，去重保留最高优先级层。"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse
from typing import Any, Callable, Dict, List, Optional

RELATION_TIERS = ("direct", "board", "peer", "theme", "orbit")
_TIER_RANK = {t: i for i, t in enumerate(RELATION_TIERS)}


def content_hash(title: str, url: str) -> str:
    t = re.sub(r"\s+", "", (title or "")).lower()
    try:
        host = urlparse(url or "").netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return hashlib.sha1(f"{t}|{host}".encode("utf-8")).hexdigest()


def _norm(raw: dict, tier: str, reason: str) -> dict:
    title = raw.get("title") or ""
    url = raw.get("url")
    return {
        "title": title,
        "url": url,
        "source": raw.get("source"),
        "published_at": raw.get("published_at"),
        "tier": tier,
        "relation_reason": reason,
        "sentiment": raw.get("sentiment"),
        "content_hash": content_hash(title, url or ""),
    }


def collect_related_news(
    code: str,
    relations: dict,
    *,
    stock_news_fn: Optional[Callable[[str], list]] = None,
    sector_news_fn: Optional[Callable[[list], list]] = None,
    hot_news_fn: Optional[Callable[[list], list]] = None,
    orbit_news_fn: Optional[Callable[[list], list]] = None,
    per_tier_limit: int = 8,
) -> List[Dict[str, Any]]:
    boards = relations.get("boards") or []
    peers = relations.get("peers") or []
    rings = relations.get("concept_rings") or []
    board_names = [b.get("name") for b in boards if b.get("name")]

    def _safe(fn, *args):
        if fn is None:
            return []
        try:
            return fn(*args) or []
        except Exception:  # noqa: BLE001
            return []

    staged: list[tuple[str, str, dict]] = []
    for raw in _safe(stock_news_fn, code)[:per_tier_limit]:
        staged.append(("direct", "名称/代码命中", raw))
    for raw in _safe(sector_news_fn, board_names)[:per_tier_limit]:
        staged.append(("board", f"所属板块：{'、'.join(board_names[:2])}", raw))
    peer_names = [p.get("name") for p in peers if p.get("name")]
    if peer_names:
        for raw in _safe(sector_news_fn, peer_names)[:per_tier_limit]:
            staged.append(("peer", f"同行/产业链：{peer_names[0]}", raw))
    for raw in _safe(hot_news_fn, board_names)[:per_tier_limit]:
        staged.append(("theme", "题材/政策", raw))
    for raw in _safe(orbit_news_fn, rings)[:per_tier_limit]:
        staged.append(("orbit", "星轨概念环", raw))

    best: Dict[str, Dict[str, Any]] = {}
    for tier, reason, raw in staged:
        item = _norm(raw, tier, reason)
        if not item["title"]:
            continue
        h = content_hash(item["title"], item["url"] or "")
        prev = best.get(h)
        if prev is None or _TIER_RANK[tier] < _TIER_RANK[prev["tier"]]:
            best[h] = item
    return sorted(best.values(), key=lambda it: _TIER_RANK[it["tier"]])
