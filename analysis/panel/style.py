"""股票风格分类 + 流派×风格 权重矩阵加载。"""
from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "panel_style_weights.json"

STYLES = ("baima", "growth", "cyclic", "small_spec", "dividend", "turnaround", "quant")


def classify_style(f: Dict[str, Any]) -> str:
    """按特征启发式分到 7 风格之一。优先级：小盘投机 > 量化活跃 > 高成长 > 白马。"""
    control = f.get("control_degree")
    vol = f.get("volume_ratio")
    seats = f.get("quant_seat_appearances")
    roe = f.get("roe")
    yoy = f.get("net_profit_yoy")
    model_ratio = f.get("model_bull_ratio")

    # 小盘投机：高控盘 + 放量 + 龙虎榜活跃 + 基本面缺位
    if (control is not None and control >= 70) and (vol is not None and vol >= 1.8) \
            and (seats is not None and seats >= 1):
        return "small_spec"
    # 量化活跃：模型共振极端 + 放量
    if model_ratio is not None and (model_ratio >= 0.7 or model_ratio <= 0.2) \
            and (vol is not None and vol >= 1.5):
        return "quant"
    # 高成长
    if yoy is not None and yoy >= 30:
        return "growth"
    # 白马：高 ROE
    if roe is not None and roe >= 15:
        return "baima"
    return "baima"


@functools.lru_cache(maxsize=1)
def load_style_weights() -> Dict[str, Any]:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"default": 1.0, "matrix": {}}


def school_style_weight(school: str, style: str, weights: Dict[str, Any]) -> float:
    default = float(weights.get("default", 1.0))
    row = (weights.get("matrix") or {}).get(style) or {}
    try:
        return float(row.get(school, default))
    except (TypeError, ValueError):
        return default
