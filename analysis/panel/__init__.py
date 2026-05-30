"""多空评审团 panel 引擎（纯规则，无 LLM）。Phase 1。"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict

from analysis.panel.engine import (
    classify_panel_style, compute_consensus, compute_great_divide,
    compute_schools, evaluate_all,
)
from analysis.panel.features import extract_features
from analysis.panel.indicators import build_indicators
from analysis.panel.registry import load_personas

# 决定 panel 整体 data_status 的关键数据源段
_KEY_SECTIONS = ("main_force_deep", "chip_control", "quant_matrix")


def _overall_status(inputs: Dict[str, Any], sections: Dict[str, Any]) -> str:
    has_ohlcv = inputs.get("ohlcv") is not None and len(inputs.get("ohlcv")) >= 35
    has_fundamental = bool(inputs.get("fundamental"))
    statuses = [(sections.get(k) or {}).get("data_status") for k in _KEY_SECTIONS]
    any_fresh = has_ohlcv or has_fundamental or any(s == "fresh" for s in statuses)
    any_stale = any(s == "stale" for s in statuses)
    if any_fresh:
        return "fresh"
    if any_stale:
        return "stale"
    return "unavailable"


def build_panel(inputs: Dict[str, Any], sections: Dict[str, Any]) -> Dict[str, Any]:
    """从既有 inputs + 已装配 payload 段构建多空评审团 panel。"""
    inputs = inputs or {}
    sections = sections or {}
    features = extract_features(inputs, sections)
    personas = load_personas()
    analysts = evaluate_all(personas, features)
    style = classify_panel_style(features)
    return {
        "data_status": _overall_status(inputs, sections),
        "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
        "style": style,
        "consensus": compute_consensus(analysts, style),
        "great_divide": compute_great_divide(analysts),
        "schools": compute_schools(analysts),
        "analysts": analysts,
        "indicators": build_indicators(features),
    }
