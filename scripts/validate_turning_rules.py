# -*- coding: utf-8 -*-
"""板块拐点判据历史校验 —— 上线门槛(spec §8)。

做法:对 sector_daily_metrics 全历史逐日回放每条判据(仅用收盘定稿数据),
命中当日之后 N 个交易日的板块等权收益,与同期全市场等权收益比超额。

上线门槛:样本 n>=30 且 5 日超额均值 > 0 且 胜率 > 52%。
不过门槛的判据不上线,结果写入 kv_repo(market_pulse/rule_stats)供服务层读取,
并须由执行者手工记入 spec §13「已否决判据」。

年化口径复用 analysis/backtest_metrics.annualize_chained,禁止手搓算术均值取幂。

用法:
    python scripts/validate_turning_rules.py
    python scripts/validate_turning_rules.py --horizon 10 --min-n 30
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import sector_turning as st  # noqa: E402
from analysis.backtest_metrics import annualize_chained  # noqa: E402
from data_store import kv_repo  # noqa: E402
from data_store.connection import get_conn  # noqa: E402

KV_NAMESPACE = "market_pulse"
KV_KEY = "rule_stats"


def _load_panel() -> Dict[str, Any]:
    """一次性读全表 → {(sector, sector_type): [rows...]}, 以及日期列表。"""
    cols = ("trade_date", "sector", "sector_type", "member_count", "net_amount",
            "net_rate_median", "pct_chg_mean", "breadth", "amount_median",
            "excess_vs_market", "seat_count", "provisional")
    rows = get_conn().execute(
        f"SELECT {','.join(cols)} FROM sector_daily_metrics "
        "WHERE provisional=0 ORDER BY trade_date ASC").fetchall()
    panel: Dict[Any, List[Dict[str, Any]]] = {}
    dates = set()
    for row in rows:
        rec = dict(zip(cols, row))
        panel.setdefault((rec["sector"], rec["sector_type"]), []).append(rec)
        dates.add(rec["trade_date"])
    return {"panel": panel, "dates": sorted(dates)}


def _forward_return(series: List[Dict[str, Any]], idx: int, horizon: int) -> float | None:
    """第 idx 天命中 → 之后 horizon 个交易日的板块等权累计收益(%)。"""
    window = series[idx + 1: idx + 1 + horizon]
    if len(window) < horizon:
        return None
    total = 0.0
    for row in window:
        value = row.get("pct_chg_mean")
        if value is None:
            return None
        total += float(value)
    return total


def _market_forward(market_by_date: Dict[str, float], dates: List[str],
                    date: str, horizon: int) -> float | None:
    try:
        pos = dates.index(date)
    except ValueError:
        return None
    window = dates[pos + 1: pos + 1 + horizon]
    if len(window) < horizon:
        return None
    values = [market_by_date.get(d) for d in window]
    if any(v is None for v in values):
        return None
    return sum(values)


def main() -> int:
    parser = argparse.ArgumentParser(description="板块拐点判据历史校验")
    parser.add_argument("--horizon", type=int, default=5, help="前瞻交易日数")
    parser.add_argument("--min-n", type=int, default=30, help="最小样本数")
    parser.add_argument("--min-win-rate", type=float, default=52.0, help="胜率门槛(%)")
    parser.add_argument("--min-members", type=int, default=5, help="板块最小成分股数")
    parser.add_argument("--dry-run", action="store_true", help="不写 kv_repo")
    args = parser.parse_args()

    loaded = _load_panel()
    panel, dates = loaded["panel"], loaded["dates"]
    if not panel:
        print("sector_daily_metrics 为空,先跑 scripts/backfill_sector_series.py")
        return 1
    print(f"板块 {len(panel)} 条线,交易日 {len(dates)} 天 "
          f"({dates[0]} ~ {dates[-1]}),前瞻 {args.horizon} 日")

    # 全市场基准 = 当日所有板块等权涨跌幅的等权平均
    market_by_date: Dict[str, List[float]] = {}
    for series in panel.values():
        for row in series:
            value = row.get("pct_chg_mean")
            if value is not None:
                market_by_date.setdefault(row["trade_date"], []).append(float(value))
    market_mean = {d: sum(v) / len(v) for d, v in market_by_date.items() if v}

    samples: Dict[str, List[float]] = {r: [] for r in st.RULE_IDS}
    for (sector, sector_type), series in panel.items():
        if (series[-1].get("member_count") or 0) < args.min_members:
            continue
        for idx in range(st.MIN_SERIES_LEN, len(series) - args.horizon):
            window = series[: idx + 1]
            hits = st.evaluate_rules(window)
            if not hits:
                continue
            sector_fwd = _forward_return(series, idx, args.horizon)
            market_fwd = _market_forward(market_mean, dates,
                                         series[idx]["trade_date"], args.horizon)
            if sector_fwd is None or market_fwd is None:
                continue
            excess = sector_fwd - market_fwd
            for hit in hits:
                if hit["state"] == "fired":
                    samples[hit["rule"]].append(excess)

    stats: Dict[str, Any] = {}
    enabled: List[str] = []
    print()
    print(f"{'判据':<6}{'名称':<12}{'样本':>6}{'超额均值':>10}{'胜率':>8}{'年化':>10}  结论")
    print("-" * 68)
    for rule_id in st.RULE_IDS:
        values = samples[rule_id]
        n = len(values)
        if n == 0:
            stats[rule_id] = {"n": 0, "excess_mean": None, "win_rate": None,
                              "annualized": None, "passed": False}
            print(f"{rule_id:<6}{st.RULE_LABELS[rule_id]:<12}{0:>6}{'—':>10}{'—':>8}{'—':>10}  ✗ 无样本")
            continue
        excess_mean = sum(values) / n
        win_rate = sum(1 for v in values if v > 0) / n * 100
        annualized = annualize_chained(values)
        passed = (n >= args.min_n and excess_mean > 0 and win_rate > args.min_win_rate)
        stats[rule_id] = {"n": n, "excess_mean": round(excess_mean, 4),
                          "win_rate": round(win_rate, 2),
                          "annualized": None if annualized is None else round(annualized, 2),
                          "passed": passed}
        if passed:
            enabled.append(rule_id)
        ann_txt = "—" if annualized is None else f"{annualized:+.1f}%"
        print(f"{rule_id:<6}{st.RULE_LABELS[rule_id]:<12}{n:>6}"
              f"{excess_mean:>+9.2f}%{win_rate:>7.1f}%{ann_txt:>10}  "
              f"{'✓ 上线' if passed else '✗ 否决'}")

    # 权重 = 各自超额均值归一(只对通过的判据),全否决时权重为空
    weights = {}
    if enabled:
        total = sum(max(stats[r]['excess_mean'], 0.01) for r in enabled)
        weights = {r: round(max(stats[r]["excess_mean"], 0.01) / total * len(enabled), 4)
                   for r in enabled}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizon": args.horizon,
        "min_n": args.min_n,
        "min_win_rate": args.min_win_rate,
        "date_range": [dates[0], dates[-1]],
        "rules": stats,
        "enabled": enabled,
        "weights": weights,
    }
    print()
    if enabled:
        print(f"上线判据: {', '.join(enabled)}  权重 {weights}")
    else:
        print("⚠️ 全部判据未过门槛。不要硬凑 —— 如实上报,由用户决定放宽阈值或放弃板块拐点。")
    if not args.dry_run:
        kv_repo.set_(KV_NAMESPACE, KV_KEY, payload)
        print(f"已写入 kv_repo {KV_NAMESPACE}/{KV_KEY}")
    print("⚠️ 请把被否决的判据(定义 + 实测数据)手工记入 spec §13,防止后人重做。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
