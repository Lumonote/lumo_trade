"""Pure risk/opportunity scoring & matching for the command-center 大屏.

No I/O. Inputs are plain dicts assembled by command_center_service; outputs are
plain dicts the frontend renders. Thresholds are module-level tunable constants
(mirrors the project's scoring-param tuning culture).
"""

OPP_BANDS = {"high": 70.0, "mid": 55.0}
RISK_BANDS = {"low": 40.0, "high": 60.0}
RISK_BLEND = {"stock": 0.55, "sector": 0.20, "market": 0.25}
STOCK_RISK_BASE = 30.0

_ACTION_TABLE = {
    ("high", "low"): ("重点出手", "act", "green"),
    ("high", "mid"): ("可做·控仓", "do", "amber"),
    ("high", "high"): ("谨慎·轻仓", "care", "orange"),
    ("mid", "low"): ("关注", "watch", "cyan"),
    ("mid", "mid"): ("观望", "watch", "blue"),
    ("mid", "high"): ("暂避", "avoid", "red"),
    ("low", "low"): ("无感", "none", "gray"),
    ("low", "mid"): ("回避", "avoid", "red"),
    ("low", "high"): ("坚决回避", "avoid", "red"),
}


def _opp_band(opp):
    if opp >= OPP_BANDS["high"]:
        return "high"
    if opp >= OPP_BANDS["mid"]:
        return "mid"
    return "low"


def _risk_band(risk):
    if risk < RISK_BANDS["low"]:
        return "low"
    if risk >= RISK_BANDS["high"]:
        return "high"
    return "mid"


def match_action(opp, risk, *, held=False):
    if risk is None:
        return {"quadrant": "unknown", "action": "风险未知", "code": "unknown",
                "color": "gray", "held_overlay": None}
    o, r = _opp_band(opp), _risk_band(risk)
    label, code, color = _ACTION_TABLE[(o, r)]
    overlay = None
    if held:
        if r == "high":
            overlay = "减仓/止盈"
        elif o == "high" and r == "low":
            overlay = "持有"
    return {"quadrant": f"{o}-{r}", "action": label, "code": code,
            "color": color, "held_overlay": overlay}
