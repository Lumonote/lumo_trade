"""Orchestrates existing signals into the command-center 大屏 payload.

Pure orchestration: every data source is injected as a callable so the service
is testable without I/O. Each source degrades independently — a failing source
sets a `degraded[...]` flag and leaves its panel empty rather than crashing.
"""
import json
from pathlib import Path

from analysis import risk_opportunity_engine as eng


class CommandCenterService:
    def __init__(self, *, load_report, capital_rankings, market_env, holdings, quotes):
        self._load_report = load_report
        self._capital_rankings = capital_rankings
        self._market_env = market_env
        self._holdings = holdings
        self._quotes = quotes

    def _safe(self, fn, default):
        try:
            return fn(), False
        except Exception:
            return default, True

    def _load_sidecar(self, report_path):
        if not report_path:
            return {}
        side = Path(report_path).with_suffix("").with_suffix(".signals.json")
        if not side.is_file():
            return {}
        try:
            data = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for row in data:
            sig = dict(row.get("risk_signals") or {})
            if row.get("sector_score") is not None:
                sig["sector_score"] = row["sector_score"]
            out[row.get("code")] = sig
        return out

    def overview(self, *, quotes_only=False):
        degraded = {}
        report, d = self._safe(self._load_report, {"items": [], "report_path": None})
        degraded["opportunity"] = d or not report.get("items")
        menv, d = self._safe(self._market_env, {})
        degraded["market_env"] = d
        hold, d = self._safe(self._holdings,
                             {"account": {}, "positions": [], "max_drawdown": 0.0})
        degraded["holdings"] = d
        cap, d = self._safe(self._capital_rankings, {"rows": []})
        degraded["capital"] = d

        market = eng.score_market_risk(menv)
        held_codes = {p.get("ts_code") for p in hold.get("positions", [])}
        sidecar = self._load_sidecar(report.get("report_path"))

        matrix = []
        for item in report.get("items", []):
            code = item.get("code") or item.get("stock_code")
            sig = sidecar.get(code, {})
            sector_crowd = eng.score_sector_crowding(sig)
            matrix.append(eng.build_target(
                item, sig, sector_crowding=sector_crowd,
                market_backdrop=market["risk"], held=code in held_codes))

        portfolio = eng.score_portfolio_risk(
            hold.get("account", {}), hold.get("positions", []),
            max_drawdown=hold.get("max_drawdown", 0.0))

        indices = {
            "market_risk": round(eng.market_risk_index(
                market["risk"], menv.get("sentiment")), 0),
            "opportunity": round(eng.opportunity_index(report.get("items", [])), 0),
            "sentiment": round(float(menv.get("sentiment") or 50), 0),
        }
        return {
            "as_of": {"report": report.get("file"), "count": len(matrix),
                      "sidecar": bool(sidecar)},
            "indices": indices,
            "market_env": menv,
            "matrix": matrix,
            "portfolio": portfolio,
            "rankings": {"capital": cap.get("rows", [])},
            "degraded": degraded,
        }
