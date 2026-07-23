#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v25 候选因子(主力资金/期指多空)在回测框架上的信号评估。

在 v24 基线(simulate_v5_backtest.apply_v8_scoring)之上,把 analysis.factor_history
的新因子 join 到回测行,分桶看 5/10 日胜率与均收益,并做前后半窗稳定性检验。
只打印诊断表,不落任何文件;规则入选标准(与 v24 优化沿例一致):
  n>=80、胜率差>=3pp、前后半窗方向一致。

用法:
    python scripts/analyze_v25_factor_candidates.py [回测CSV路径]
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.factor_history import load_futures_regime, load_moneyflow_factors  # noqa: E402
from scripts.simulate_v5_backtest import apply_v8_scoring, load_backtest_data  # noqa: E402

DEFAULT_CSV = "results/backtest_rebuilt_20260407_204957.csv"


def _bucket_table(df: pd.DataFrame, col: str, bins, labels) -> pd.DataFrame:
    work = df[df[col].notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["bucket"] = pd.cut(work[col], bins=bins, labels=labels)
    rows = []
    for label, grp in work.groupby("bucket", observed=True):
        sub = grp[grp["return_5d"].notna()]
        if not len(sub):
            continue
        rows.append({
            "bucket": label, "n": len(sub),
            "wr5": round((sub["return_5d"] > 0).mean() * 100, 1),
            "avg5": round(sub["return_5d"].mean(), 2),
            "avg10": round(sub["return_10d"].mean(), 2) if "return_10d" in sub else None,
        })
    return pd.DataFrame(rows)


def _stability(df: pd.DataFrame, mask, name: str) -> None:
    """前/后半窗方向一致性检验(按 report_date 中位数切分)。"""
    sub = df[mask & df["return_5d"].notna()]
    base = df[df["return_5d"].notna()]
    if len(sub) < 30:
        print(f"  [{name}] n={len(sub)} 样本过小,跳过稳定性检验")
        return
    mid = base["report_date"].sort_values().iloc[len(base) // 2]
    for tag, part_mask in (("前半", base["report_date"] < mid), ("后半", base["report_date"] >= mid)):
        s = sub[part_mask.reindex(sub.index, fill_value=False)]
        b = base[part_mask]
        if len(s) < 15:
            print(f"  [{name}|{tag}] n={len(s)} 过小")
            continue
        print(f"  [{name}|{tag}] n={len(s)} wr={((s['return_5d'] > 0).mean() * 100):.1f}% "
              f"avg={s['return_5d'].mean():+.2f}% | 基线 wr={((b['return_5d'] > 0).mean() * 100):.1f}% "
              f"avg={b['return_5d'].mean():+.2f}%")


def main() -> int:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    df = load_backtest_data(csv_path)
    df = apply_v8_scoring(df)
    df["code6"] = df["code"].map(lambda c: str(c).split(".")[0].strip().zfill(6))
    df = df[~df["degraded"]].copy()
    print(f"基线(剔degraded): {len(df)} 行, {df['report_date'].nunique()} 个报告日, "
          f"窗口 {df['report_date'].min()}~{df['report_date'].max()}")

    # ---------- 主力资金 ----------
    mf = load_moneyflow_factors(df["report_date"].min(), df["report_date"].max(),
                                codes=df["code6"].unique())
    for key in ("main_net_rate", "main_net_amount", "main_in_days3"):
        df[key] = [mf.get((d, c), {}).get(key) for d, c in zip(df["report_date"], df["code6"])]
    cov = df["main_net_rate"].notna().mean() * 100
    print(f"\n===== 主力资金因子 (join 覆盖率 {cov:.1f}%) =====")
    print("--- 当日主力净流入率 % ---")
    print(_bucket_table(df, "main_net_rate", [-100, -5, -2, 0, 2, 5, 100],
                        ["<-5", "-5~-2", "-2~0", "0~2", "2~5", ">5"]).to_string(index=False))
    print("--- 当日主力净流入额(万元) ---")
    print(_bucket_table(df, "main_net_amount", [-1e9, -10000, -3000, 0, 3000, 10000, 1e9],
                        ["<-1亿", "-1亿~-3k万", "-3k万~0", "0~3k万", "3k万~1亿", ">1亿"]).to_string(index=False))
    print("--- 近3日主力净流入天数 ---")
    print(_bucket_table(df, "main_in_days3", [-0.5, 0.5, 1.5, 2.5, 3.5],
                        ["0", "1", "2", "3"]).to_string(index=False))

    bplus = df["v8_score"] >= 70
    print("\n--- B+ 档内(v8>=70)主力净流入率 ---")
    print(_bucket_table(df[bplus], "main_net_rate", [-100, -5, -2, 0, 2, 5, 100],
                        ["<-5", "-5~-2", "-2~0", "0~2", "2~5", ">5"]).to_string(index=False))
    print("\n稳定性(候选规则):")
    _stability(df, df["main_net_rate"] <= -5, "主力大幅流出<=-5%")
    _stability(df, (df["main_net_rate"] >= 2) & (df["chase_risk"] < 40), "主力流入>=2%+低chase")
    _stability(df, df["main_in_days3"] >= 3, "3日连续净流入")
    _stability(df, (df["main_net_rate"] <= -3) & (df["day_change"] >= 5), "大涨且主力流出<=-3%")

    # ---------- 期指多空 ----------
    fut = load_futures_regime(df["report_date"].unique())
    for key in ("fut_net_chg", "fut_net_chg_3d"):
        df[key] = df["report_date"].map(lambda d: (fut.get(d) or {}).get(key))
    cov = df["fut_net_chg"].notna().mean() * 100
    print(f"\n===== 期指多空因子 (join 覆盖率 {cov:.1f}%, {len(fut)} 个日期) =====")
    if df["fut_net_chg"].notna().any():
        qs = df["fut_net_chg"].dropna().quantile([0, .2, .4, .6, .8, 1.0]).tolist()
        qs = sorted(set(qs))
        print("--- 当日四品种前20净持仓变动合计(张, 五分位) ---")
        print(_bucket_table(df, "fut_net_chg", qs, [f"Q{i+1}" for i in range(len(qs) - 1)]).to_string(index=False))
        qs3 = df["fut_net_chg_3d"].dropna().quantile([0, .2, .4, .6, .8, 1.0]).tolist()
        qs3 = sorted(set(qs3))
        print("--- 3日滚动净变动合计(五分位) ---")
        print(_bucket_table(df, "fut_net_chg_3d", qs3, [f"Q{i+1}" for i in range(len(qs3) - 1)]).to_string(index=False))
        neg = df["fut_net_chg_3d"] <= df["fut_net_chg_3d"].dropna().quantile(0.2)
        pos = df["fut_net_chg_3d"] >= df["fut_net_chg_3d"].dropna().quantile(0.8)
        print("\n稳定性(候选规则):")
        _stability(df, neg, "期指3日净空加深(底部20%)")
        _stability(df, pos, "期指3日净多回补(顶部20%)")
        _stability(df, neg & (df["chase_risk"] >= 60), "净空加深×追高>=60")
        _stability(df, neg & (df["day_change"] >= 7), "净空加深×当日大涨")
    else:
        print("(kv 中该窗口期指数据尚未回填完成)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
