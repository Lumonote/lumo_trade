"""Service-layer wrapper around analysis.StockAnalysisSuite.

Responsibilities:
- Input validation (stock code format)
- JSON shape conformance with spec §5.1 / §5.2
- Stock metadata enrichment (market exchange inference + sector lookup)
- Top-level exception handling so the HTTP handler always gets a dict back
"""

from __future__ import annotations

import datetime as _dt
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from analysis.analysis_overlay import merge_overlay
from analysis.stock_analysis_suite import StockAnalysisSuite


_CODE_RE = re.compile(r"^[036][0-9]{5}$|^[68][0-9]{5}$")


def _build_institutional_providers() -> Dict[str, Any]:
    """Build institutional provider instances for StockAnalysisSuite.

    M1: All providers read from SQLite (stale) or return unavailable.
    M2: Will add real akshare fetching.
    """
    from analysis.institutional import (
        LhbProvider, HsgtProvider, HoldersProvider,
        SurveyProvider, FundHoldingsProvider, CyqProvider,
        QuantSeatRegistry,
    )
    from data_store.akshare_adapter import AkshareAdapter

    repo_root = Path(__file__).resolve().parents[2]
    registry = QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
    adapter = AkshareAdapter()
    return {
        "lhb": LhbProvider(seat_registry=registry, akshare_adapter=adapter),
        "hsgt": HsgtProvider(akshare_adapter=adapter),
        "holders": HoldersProvider(akshare_adapter=adapter),
        "survey": SurveyProvider(akshare_adapter=adapter),
        "fund": FundHoldingsProvider(akshare_adapter=adapter),
        "cyq": CyqProvider(akshare_adapter=adapter),
    }


@lru_cache(maxsize=4096)
def _resolve_sector(code: str) -> tuple[str, str]:
    """Resolve (sector_name, stock_name) for a code. Cached per process.

    Returns ("—", "") on failure so the popup degrades gracefully.
    """
    try:
        from analysis.sector_api import get_stock_sector_info

        info = get_stock_sector_info(code) or {}
        sector = (info.get("sector_name") or info.get("industry") or "").strip()
        stock_name = (info.get("stock_name") or "").strip()
        if sector and sector not in ("未知", "N/A", "nan", "None"):
            return sector, stock_name
        return "—", stock_name
    except Exception:  # noqa: BLE001
        return "—", ""


class StockSuiteService:
    def __init__(self, orchestrator: Optional[StockAnalysisSuite] = None) -> None:
        if orchestrator:
            self._suite = orchestrator
        else:
            self._suite = StockAnalysisSuite(
                institutional_providers=_build_institutional_providers()
            )

    def _validate_code(self, code: str) -> str:
        cleaned = (code or "").strip()
        if not cleaned or not _CODE_RE.match(cleaned):
            raise ValueError(f"invalid stock code: {code!r}")
        return cleaned

    def _stock_meta(self, code: str, name: str) -> Dict[str, str]:
        market = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        sector, resolved_name = _resolve_sector(code)
        return {
            "code": code,
            "name": name or resolved_name or "",
            "sector": sector,
            "market": market,
        }

    def get_suite(self, code: str, name: str = "", force_refresh: bool = False) -> Dict[str, Any]:
        code = self._validate_code(code)
        meta = self._stock_meta(code, name)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        if force_refresh:
            self._suite.invalidate(code)
        try:
            payload = self._suite.get_full_payload(code)
            # 展示层重载一致性：已审阅 overlay 的金句 override / 逐人 insight 在此 merge 进 panel，
            # 与刚生成时 trigger_panel_overlay 返回的 merged_panel 保持一致。仅在此展示边界 merge——
            # compute/cache/regenerate 仍喂原始 panel 给 LLM（否则模型会把自己上一轮的金句当基线）。
            # merge_overlay 内部深拷贝，不改写编排器缓存里按引用返回的原始 panel。
            overlay = payload.get("analysis_overlay")
            panel = payload.get("panel")
            if isinstance(overlay, dict) and overlay.get("reviewed") and isinstance(panel, dict):
                payload = {**payload, "panel": merge_overlay(panel, overlay)}
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "error": str(exc),
                "stock": meta,
                "generated_at": now,
            }
        return {
            "success": True,
            "stock": meta,
            "generated_at": now,
            "cache": {"hit": False, "expires_at": None},
            **payload,
        }

    def trigger_ai_interpretation(
        self,
        code: str,
        name: str = "",
        model_full_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_ai_interpretation(
            code,
            name=name,
            model_full_key=model_full_key,
            force_refresh=force_refresh,
        )

    def trigger_panel_overlay(
        self,
        code: str,
        tier: str = "deep",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_panel_overlay(code, tier=tier, force_refresh=force_refresh)


STOCK_SUITE_SERVICE = StockSuiteService()
