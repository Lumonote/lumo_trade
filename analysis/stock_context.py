"""个股关联解析器：code → 板块 / 同行 / 概念环 / 板块情绪。

纯逻辑：所有外部数据源通过可注入函数传入，默认实现在 service 层接线，
便于单测。任一源异常只降级该维度，绝不影响其它维度。
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def _safe_float(v: Any) -> Optional[float]:
    """把 'N/A'/None/空串/非数字字符串安全转 float；失败返回 None。"""
    if v is None:
        return None
    try:
        s = str(v).strip()
        if not s or s.upper() == "N/A":
            return None
        return float(s)
    except (TypeError, ValueError):
        return None


def resolve_relations(
    code: str,
    *,
    boards_fn: Optional[Callable[[str], list]] = None,
    peers_fn: Optional[Callable[[str], list]] = None,
    rings_fn: Optional[Callable[[list], list]] = None,
    sector_fn: Optional[Callable[[str], dict]] = None,
) -> dict:
    degraded: list[str] = []

    def _try(name: str, fn, *args, default):
        if fn is None:
            return default
        try:
            return fn(*args)
        except Exception:  # noqa: BLE001
            degraded.append(name)
            return default

    boards = _try("boards", boards_fn, code, default=[]) or []
    peers = _try("peers", peers_fn, code, default=[]) or []
    rings = _try("concept_rings", rings_fn, boards, default=[]) or []
    sector = _try("sector_sentiment", sector_fn, code, default={}) or {}

    return {
        "boards": boards,
        "peers": peers,
        "concept_rings": rings,
        "sector_sentiment": sector,
        "degraded": degraded,
    }
