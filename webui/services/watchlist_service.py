"""用户自选股：JSON 持久化（USER_ROOT/config/watchlist.json）+ 东方财富实时行情。

- 落库走原子写（临时文件 + replace），与 RuntimeConfigurationService 口径一致。
- 实时行情走东方财富 ulist.np 批量报价接口，可对任意一篮子代码取价。
- 纯本地单用户，无并发写竞争；列表读写均以磁盘为准，避免与桌面多页状态漂移。
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from webui.services.http_client import request_json, request_text

_VALID_CODE = re.compile(r"^(?:6[0-9]{5}|[03][0-9]{5}|[84][0-9]{5}|92[0-9]{4})$")
_MAX_ITEMS = 200
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_QUOTE_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
}
# 腾讯行情（东财 ulist.np 在部分网络/本机被断开时的回退源；返回 GBK 文本，无主力净流入字段）。
_TENCENT_HEADERS = {"User-Agent": _UA, "Referer": "https://gu.qq.com/"}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, "", "-", "—", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_code(raw: Any) -> str:
    """'SH600000' / '600000.SH' / '600000' → '600000'；非法输入原样返回（交由校验拒绝）。"""
    text = str(raw or "").strip().upper().split(".")[0]
    digits = re.sub(r"\D", "", text)
    if not digits:
        return text
    return digits.zfill(6) if len(digits) <= 6 else digits


def _eastmoney_secid(code: str) -> str:
    """6 位代码 → 东方财富 secid（沪市前缀 1，深/北前缀 0）。"""
    if code.startswith("92"):  # 北交所 920xxx 新代码段：东财归市场 0，须先于 9→1 判断
        return f"0.{code}"
    prefix = "1" if code[:1] in ("5", "6", "9") else "0"
    return f"{prefix}.{code}"


def _tencent_symbol(code: str) -> str:
    """6 位代码 → 腾讯行情 symbol（沪 sh / 深 sz / 北 bj）。"""
    if code.startswith("92"):  # 北交所 920xxx 新代码段，须先于 9→sh 判断
        return f"bj{code}"
    head = code[:1]
    if head in ("5", "6", "9"):
        return f"sh{code}"
    if head in ("4", "8"):
        return f"bj{code}"
    return f"sz{code}"


class WatchlistService:
    def __init__(self, store_path: Path):
        self.store_path = Path(store_path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _read(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = data.get("items") if isinstance(data, dict) else data
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                code = normalize_code(it.get("code"))
                if not _VALID_CODE.match(code) or code in seen:
                    continue
                seen.add(code)
                out.append({
                    "code": code,
                    "name": str(it.get("name") or "").strip(),
                    "added_at": str(it.get("added_at") or _now()),
                })
        return out

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.store_path.name}.", suffix=".tmp", dir=str(self.store_path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"items": items, "updated_at": _now()}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            Path(tmp_name).replace(self.store_path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # 增删查
    # ------------------------------------------------------------------
    def list_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read()

    def add(self, code: Any, name: Any = "") -> tuple[dict[str, Any], int]:
        norm = normalize_code(code)
        if not _VALID_CODE.match(norm):
            return {"error": "无效的股票代码"}, 400
        with self._lock:
            items = self._read()
            if any(it["code"] == norm for it in items):
                return {"items": items, "added": False, "code": norm}, 200
            if len(items) >= _MAX_ITEMS:
                return {"error": f"自选数量已达上限 {_MAX_ITEMS}"}, 400
            items.insert(0, {"code": norm, "name": str(name or "").strip(), "added_at": _now()})
            self._write(items)
            return {"items": items, "added": True, "code": norm}, 200

    def remove(self, code: Any) -> tuple[dict[str, Any], int]:
        norm = normalize_code(code)
        with self._lock:
            items = self._read()
            kept = [it for it in items if it["code"] != norm]
            if len(kept) == len(items):
                return {"items": items, "removed": False, "code": norm}, 200
            self._write(kept)
            return {"items": kept, "removed": True, "code": norm}, 200

    def is_member(self, code: Any) -> bool:
        norm = normalize_code(code)
        with self._lock:
            return any(it["code"] == norm for it in self._read())

    # ------------------------------------------------------------------
    # 实时行情
    # ------------------------------------------------------------------
    def quotes(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        valid: list[str] = []
        seen: set[str] = set()
        for raw in codes or []:
            code = normalize_code(raw)
            if _VALID_CODE.match(code) and code not in seen:
                seen.add(code)
                valid.append(code)
        if not valid:
            return {}
        # 东财 ulist.np 字段最全（含主力净流入），但在部分网络/本机会被直接断开；
        # 取不到时回退腾讯行情（qt.gtimg.cn，无主力净流入字段），保证自选行情可用。
        try:
            out = self._quotes_eastmoney(valid)
        except Exception:  # noqa: BLE001 — 行情失败时降级，不应阻断自选列表
            out = {}
        if out:
            return out
        try:
            return self._quotes_tencent(valid)
        except Exception:  # noqa: BLE001
            return {}

    def _quotes_eastmoney(self, valid: list[str]) -> dict[str, dict[str, Any]]:
        secids = ",".join(_eastmoney_secid(c) for c in valid)
        url = (
            "https://push2.eastmoney.com/api/qt/ulist.np/get?"
            "fltt=2&invt=2&fields=f12,f14,f2,f3,f4,f62&secids=" + secids
        )
        payload = request_json(url, headers=_QUOTE_HEADERS, timeout=4, retries=2)
        diff = ((payload or {}).get("data") or {}).get("diff") or []
        rows = diff.values() if isinstance(diff, dict) else diff
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("f12") or "").strip()
            if not code:
                continue
            out[code] = {
                "name": str(row.get("f14") or "").strip(),
                "price": _safe_float(row.get("f2")),
                "change_pct": round(_safe_float(row.get("f3")) or 0.0, 2),
                "change_amount": _safe_float(row.get("f4")),
                "main_net_inflow": _safe_float(row.get("f62")),
            }
        return out

    def _quotes_tencent(self, valid: list[str]) -> dict[str, dict[str, Any]]:
        symbols = ",".join(_tencent_symbol(c) for c in valid)
        text = request_text(
            "https://qt.gtimg.cn/q=" + symbols,
            headers=_TENCENT_HEADERS,
            timeout=4,
            encoding="gbk",
            errors="ignore",
            retries=2,
        )
        out: dict[str, dict[str, Any]] = {}
        for line in text.splitlines():
            line = line.strip()
            if "=" not in line:
                continue
            body = line.split("=", 1)[1].strip().rstrip(";").strip('"')
            if not body:
                continue
            fields = body.split("~")
            if len(fields) < 33:  # 行情未返回（停牌/无效代码）时字段会被截断
                continue
            code = (fields[2] or "").strip()
            if not code:
                continue
            out[code] = {
                "name": (fields[1] or "").strip(),
                "price": _safe_float(fields[3]),
                "change_pct": round(_safe_float(fields[32]) or 0.0, 2),
                "change_amount": _safe_float(fields[31]),
                "main_net_inflow": None,  # 腾讯基础行情不含主力净流入
            }
        return out

    def list_with_quotes(self) -> dict[str, Any]:
        with self._lock:
            items = self._read()
        quote_map = self.quotes([it["code"] for it in items]) if items else {}
        merged: list[dict[str, Any]] = []
        for it in items:
            quote = quote_map.get(it["code"], {})
            merged.append({
                "code": it["code"],
                "name": it["name"] or quote.get("name") or it["code"],
                "added_at": it["added_at"],
                "price": quote.get("price"),
                "change_pct": quote.get("change_pct"),
                "change_amount": quote.get("change_amount"),
                "main_net_inflow": quote.get("main_net_inflow"),
            })
        return {
            "items": merged,
            "count": len(merged),
            "quoted": bool(quote_map),
            "updated_at": _now(),
        }
