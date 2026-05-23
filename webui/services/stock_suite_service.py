"""Service-layer wrapper around analysis.StockAnalysisSuite.

Responsibilities:
- Input validation (stock code format)
- JSON shape conformance with spec §5.1 / §5.2
- Stock metadata enrichment (market exchange inference)
- Top-level exception handling so the HTTP handler always gets a dict back
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, Optional

from analysis.stock_analysis_suite import StockAnalysisSuite


_CODE_RE = re.compile(r"^[036][0-9]{5}$|^[68][0-9]{5}$")


class StockSuiteService:
    def __init__(self, orchestrator: Optional[StockAnalysisSuite] = None) -> None:
        self._suite = orchestrator or StockAnalysisSuite()

    def _validate_code(self, code: str) -> str:
        cleaned = (code or "").strip()
        if not cleaned or not _CODE_RE.match(cleaned):
            raise ValueError(f"invalid stock code: {code!r}")
        return cleaned

    def _stock_meta(self, code: str, name: str) -> Dict[str, str]:
        market = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        return {"code": code, "name": name or "", "sector": "—", "market": market}

    def get_suite(self, code: str, name: str = "") -> Dict[str, Any]:
        code = self._validate_code(code)
        meta = self._stock_meta(code, name)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            payload = self._suite.get_full_payload(code)
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


STOCK_SUITE_SERVICE = StockSuiteService()
