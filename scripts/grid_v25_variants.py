#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v25 变体网格回测 —— 裁决既有规则修复与新因子力度。

变体通过原地修改 scoring_rules.RULESET(evaluate_shared_rules 与 sim-only 逻辑
共同消费的同一 dict)实现,跑完恢复。输出每变体 S/A/B/C 分层 + 近半窗 B+ +
[82,85) 段 + 单调性违例数,便于按 v13 惯例(40% 全窗 + 60% 近期)取舍。
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.scoring_rules import RULESET  # noqa: E402
from scripts.simulate_v5_backtest import apply_v8_scoring, load_backtest_data  # noqa: E402

DEFAULT_CSV = "results/backtest_rebuilt_20260407_204957.csv"

FIX4 = {"sim_tech_high_pen": 0, "sim_net_buy_gradient": 0,
        "sim_score_high_threshold": 999, "rsi_pullback_pen": 0}
NB = {"sim_net_buy_gradient": 0}

VARIANTS = [
    ("v24基线(无新因子)", {"main_outflow_pen": 0, "main_inflow_bonus": 0, "fut_bear_pen": 0}),
    ("NB+fut8", {**NB, "fut_bear_pen": 8}),
    ("NB+fut10", {**NB, "fut_bear_pen": 10}),
    ("NB+fut12", {**NB, "fut_bear_pen": 12}),
    ("NB+fut15", {**NB, "fut_bear_pen": 15}),
    ("NB+tech0+fut8", {**NB, "sim_tech_high_pen": 0, "fut_bear_pen": 8}),
    ("NB+tech0+fut10", {**NB, "sim_tech_high_pen": 0, "fut_bear_pen": 10}),
    ("NB+pullback0+fut10", {**NB, "rsi_pullback_pen": 0, "fut_bear_pen": 10}),
    ("NB+tech0+pb0+fut10", {**NB, "sim_tech_high_pen": 0, "rsi_pullback_pen": 0, "fut_bear_pen": 10}),
]


@contextmanager
def patched_ruleset(overrides: dict):
    saved = {k: RULESET[k] for k in overrides if k in RULESET}
    RULESET.update(overrides)
    try:
        yield
    finally:
        RULESET.update(saved)


def _wr(sub) -> float:
    return (sub["return_5d"] > 0).mean() * 100 if len(sub) else float("nan")


def evaluate(df: pd.DataFrame, name: str) -> dict:
    base = df[df["return_5d"].notna()]
    dates = sorted(base["report_date"].unique())
    recent = base[base["report_date"] >= dates[len(dates) // 2]]
    tiers = {t: base[base["confidence_tier"] == t] for t in "SABC"}
    bp = base[base["v8_score"] >= 70]
    bp_recent = recent[recent["v8_score"] >= 70]
    buckets = [(85, 200), (78, 85), (70, 78), (60, 70), (0, 60)]
    wrs = [_wr(base[(base["v8_score"] >= lo) & (base["v8_score"] < hi)]) for lo, hi in buckets]
    mono_bad = sum(1 for a, b in zip(wrs, wrs[1:]) if pd.notna(a) and pd.notna(b) and a < b - 1e-9)
    seg = base[(base["v8_score"] >= 82) & (base["v8_score"] < 85)]
    return {
        "变体": name,
        "S": f"{len(tiers['S'])}/{_wr(tiers['S']):.0f}%/{tiers['S']['return_5d'].mean():+.1f}",
        "A": f"{len(tiers['A'])}/{_wr(tiers['A']):.0f}%",
        "B": f"{len(tiers['B'])}/{_wr(tiers['B']):.0f}%",
        "B+wr": round(_wr(bp), 1), "B+avg": round(bp["return_5d"].mean(), 2),
        "B+n": len(bp),
        "近半B+wr": round(_wr(bp_recent), 1),
        "近半B+avg": round(bp_recent["return_5d"].mean(), 2) if len(bp_recent) else None,
        "A>B": "✓" if _wr(tiers["A"]) > _wr(tiers["B"]) else "✗",
        "82-85": f"{len(seg)}/{_wr(seg):.0f}%" if len(seg) else "0",
        "单调违例": mono_bad,
    }


def main() -> int:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    df = load_backtest_data(csv_path)
    df = df[~df["degraded"]].copy()
    rows = []
    for name, overrides in VARIANTS:
        with patched_ruleset(overrides):
            scored = apply_v8_scoring(df.copy())
        rows.append(evaluate(scored, name))
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
