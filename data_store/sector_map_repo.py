# -*- coding: utf-8 -*-
"""个股 → 板块映射(行业 + 概念),供板块日序列聚合使用。

两个来源各补一半(实测覆盖):
- 行业: ``quant_radar_stock_daily.industry`` —— 5246/6005 只股票有值(87%),
  且按日存量,行业分类稳定,取 <= as_of 的最近一条即可。
- 概念: ``hot_sector_stock`` × ``hot_sector_board`` 东财板块快照 —— 只覆盖 3322 只,
  但它是概念维度的唯一来源(206 个板块)。快照式、日期不连续,取最近一份快照。

映射不到板块的股票**不进任何板块序列**,由 :func:`coverage` 显式报缺口,
绝不静默丢弃(spec §4.4)。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from data_store.connection import get_conn

logger = logging.getLogger(__name__)

INDUSTRY = "行业"
CONCEPT = "概念"
SECTOR_TYPES = (INDUSTRY, CONCEPT)

# 地域板块对「板块机会」无解释力(spec §4.4 已知坑),命中即剔除。
_REGION_PATTERN = re.compile(r"(板块|地区|区域)$|^(北京|上海|天津|重庆|广东|江苏|浙江|山东|河南|"
                             r"四川|湖北|湖南|福建|安徽|河北|陕西|辽宁|山西|江西|广西|云南|贵州|"
                             r"黑龙江|吉林|甘肃|内蒙古|新疆|宁夏|青海|西藏|海南)$")

_DIGITS = re.compile(r"(\d{6})")


def bare_code(value: Any) -> str:
    """任意代码写法 → 裸 6 位码。取不出数字返回空串。"""
    match = _DIGITS.search(str(value or ""))
    return match.group(1) if match else ""


def _is_region(name: str) -> bool:
    return bool(_REGION_PATTERN.search(name or ""))


def build_map(*, as_of: str | None = None) -> Dict[str, List[Tuple[str, str]]]:
    """裸码 → [(板块名, 板块类型)]。任一来源失败只丢该来源,不抛。"""
    result: Dict[str, List[Tuple[str, str]]] = {}

    def _add(code: str, sector: str, sector_type: str) -> None:
        code = bare_code(code)
        sector = (sector or "").strip()
        if not code or not sector or _is_region(sector):
            return
        entry = (sector, sector_type)
        bucket = result.setdefault(code, [])
        if entry not in bucket:
            bucket.append(entry)

    conn = get_conn()
    end = (as_of or "9999-12-31").strip()

    # --- 行业: 每只股票取 <= as_of 的最近一条非空 industry
    try:
        rows = conn.execute(
            """
            SELECT code, industry FROM quant_radar_stock_daily q
             WHERE trade_date <= ?
               AND industry IS NOT NULL AND industry <> ''
               AND trade_date = (SELECT MAX(trade_date) FROM quant_radar_stock_daily
                                  WHERE code = q.code AND trade_date <= ?
                                    AND industry IS NOT NULL AND industry <> '')
            """,
            (end, end),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — 单源失败不拖垮映射
        logger.debug("build_map 行业源失败: %s", exc)
        rows = []
    for row in rows:
        _add(row[0], row[1], INDUSTRY)

    # --- 概念: 取 <= as_of 的最近一份热门板块快照
    try:
        snap = conn.execute(
            "SELECT id FROM hot_sector_snapshot WHERE COALESCE(trade_date, created_at) <= ? "
            "ORDER BY COALESCE(trade_date, created_at) DESC, id DESC LIMIT 1",
            (end,),
        ).fetchone()
        board_rows = conn.execute(
            """
            SELECT s.code, b.board_name, b.board_type
              FROM hot_sector_stock s
              JOIN hot_sector_board b
                ON b.snapshot_id = s.snapshot_id AND b.board_code = s.board_code
             WHERE s.snapshot_id = ?
            """,
            (snap[0],),
        ).fetchall() if snap else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("build_map 概念源失败: %s", exc)
        board_rows = []
    for code, board_name, board_type in board_rows:
        # 东财 board_type 只有「行业」「概念」两种;行业已由 quant_radar 覆盖,
        # 这里同样 _add,由去重保证不重复。
        _add(code, board_name, CONCEPT if str(board_type or "") == CONCEPT else INDUSTRY)

    return result


def coverage(mapping: Mapping[str, Any], universe: Iterable[str]) -> Dict[str, Any]:
    """映射覆盖度。universe 为参与聚合的全部代码(任意写法)。"""
    codes = {bare_code(c) for c in universe or []}
    codes.discard("")
    if not codes:
        return {"mapped": 0, "unmapped": 0, "ratio": 0.0}
    mapped = sum(1 for c in codes if mapping.get(c))
    return {
        "mapped": mapped,
        "unmapped": len(codes) - mapped,
        "ratio": round(mapped / len(codes), 4),
    }
