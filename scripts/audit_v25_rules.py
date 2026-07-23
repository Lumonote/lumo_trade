#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v24 既有规则 + v25 新规则 全量审计。

对回测框架逐行重放 evaluate_shared_rules,统计每条规则:
触发数 / 触发组胜率与均收益 / 相对未触发组的差值 / 前后半窗方向 → 判定:
  ✅有效(惩罚组更差或奖励组更好,双半窗同向) / ⚠️失效(方向反转) / 💤低频(n<15) / ~中性。
另输出: sim-only 规则审计、S/A/B/C 分层表(v24因子 vs v25因子)、评分桶单调性。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.scoring_rules import evaluate_shared_rules  # noqa: E402
from scripts.simulate_v5_backtest import apply_v8_scoring, load_backtest_data  # noqa: E402

DEFAULT_CSV = "results/backtest_rebuilt_20260407_204957.csv"
FACTOR_KEYS = ("rsi", "chase_risk", "change_3d", "change_5d", "day_change",
               "quant_score", "tech_score", "sector_score", "buy_signals",
               "sell_signals", "main_net_rate", "fut_net_chg_3d")


def _wr(sub: pd.DataFrame) -> float:
    return (sub["return_5d"] > 0).mean() * 100


def rule_audit(df: pd.DataFrame) -> pd.DataFrame:
    hits_per_row = []
    for _, row in df.iterrows():
        factors = {k: row.get(k) for k in FACTOR_KEYS}
        hits_per_row.append({h.rule for h in evaluate_shared_rules(factors)})
    df = df.assign(_hits=hits_per_row)
    base = df[df["return_5d"].notna()]
    mid = base["report_date"].sort_values().iloc[len(base) // 2]
    first, second = base["report_date"] < mid, base["report_date"] >= mid
    all_rules = sorted(set().union(*hits_per_row)) if hits_per_row else []
    rows = []
    for rule in all_rules:
        mask = base["_hits"].map(lambda s: rule in s)
        hit, rest = base[mask], base[~mask]
        if not len(hit):
            continue
        delta = _wr(hit) - _wr(rest)
        half_deltas = []
        for part in (first, second):
            h, r = base[mask & part], base[~mask & part]
            half_deltas.append(_wr(h) - _wr(r) if len(h) >= 8 and len(r) else float("nan"))
        is_pen = rule not in {"rsi_golden", "rsi_oversold", "qs_low_gated", "sell0",
                              "zt_low_chase", "strong_low_chase", "momentum_start",
                              "low_risk_momentum", "main_inflow"}
        d1, d2 = half_deltas
        if len(hit) < 15:
            verdict = "💤低频"
        elif is_pen:
            ok = [d for d in (d1, d2) if d == d]
            verdict = ("✅有效" if all(d < 0 for d in ok) and ok
                       else "⚠️反转" if all(d > 2 for d in ok) and ok else "~混合")
        else:
            ok = [d for d in (d1, d2) if d == d]
            verdict = ("✅有效" if all(d > 0 for d in ok) and ok
                       else "⚠️反转" if all(d < -2 for d in ok) and ok else "~混合")
        rows.append({"rule": rule, "类型": "罚" if is_pen else "奖", "n": len(hit),
                     "wr触发": round(_wr(hit), 1), "wr未触发": round(_wr(rest), 1),
                     "Δ": round(delta, 1), "Δ前半": round(d1, 1) if d1 == d1 else None,
                     "Δ后半": round(d2, 1) if d2 == d2 else None,
                     "avg5触发": round(hit["return_5d"].mean(), 2), "判定": verdict})
    return pd.DataFrame(rows).sort_values(["类型", "Δ"])


def sim_only_audit(df: pd.DataFrame) -> None:
    base = df[df["return_5d"].notna()]
    print("\n===== sim-only 规则审计 =====")
    for name, mask in (
        ("score>=76 渐进罚", base["score"] >= 76),
        ("tech>=80 罚3", base["tech_score"] >= 80),
        ("net_buy>=4 梯度奖", (base["buy_signals"] - base["sell_signals"]) >= 4),
        ("net_buy>=10 高档奖", (base["buy_signals"] - base["sell_signals"]) >= 10),
    ):
        hit, rest = base[mask], base[~mask]
        if not len(hit):
            continue
        print(f"  {name}: n={len(hit)} wr={_wr(hit):.1f}% (未触发 {_wr(rest):.1f}%) "
              f"avg5={hit['return_5d'].mean():+.2f}%")


def tier_table(df: pd.DataFrame, label: str) -> None:
    base = df[df["return_5d"].notna()]
    print(f"\n===== 分层表 [{label}] =====")
    for tier in ("S", "A", "B", "C"):
        sub = base[base["confidence_tier"] == tier]
        if not len(sub):
            print(f"  {tier}: 0")
            continue
        print(f"  {tier}: n={len(sub):>4} wr={_wr(sub):.1f}% avg5={sub['return_5d'].mean():+.2f}% "
              f"avg10={sub['return_10d'].mean():+.2f}%")
    bp = base[base["v8_score"] >= 70]
    print(f"  B+合计: n={len(bp)} wr={_wr(bp):.1f}% avg5={bp['return_5d'].mean():+.2f}%")
    print("  评分桶单调性:")
    for lo, hi in ((85, 200), (82, 85), (78, 82), (74, 78), (70, 74), (60, 70), (0, 60)):
        sub = base[(base["v8_score"] >= lo) & (base["v8_score"] < hi)]
        if len(sub) >= 5:
            print(f"    [{lo},{hi}): n={len(sub):>4} wr={_wr(sub):.1f}% avg5={sub['return_5d'].mean():+.2f}%")


def main() -> int:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    df = load_backtest_data(csv_path)
    df = df[~df["degraded"]].copy()

    v24 = df.copy()
    v24["main_net_rate"] = None
    v24["fut_net_chg_3d"] = None
    v24 = apply_v8_scoring(v24)
    v25 = apply_v8_scoring(df.copy())

    print("\n===== 共享规则逐条审计 (v25 因子富集后) =====")
    print(rule_audit(v25).to_string(index=False))
    sim_only_audit(v25)
    tier_table(v24, "v24 基线(无新因子)")
    tier_table(v25, "v25 (主力资金+期指)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
