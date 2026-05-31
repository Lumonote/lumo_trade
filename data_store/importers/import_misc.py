"""One-shot importers for moneyflow_dc, hot_stocks kv, market_daily, market_flow."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from data_store import (
    kv_repo,
    market_snapshot_repo,
    moneyflow_repo,
)
from data_store.importers import announce


_DC_PATTERN = re.compile(r"^moneyflow_dc_(\d{8})_top(\d+)\.csv$")


def import_moneyflow_dc(data_dir: Path) -> int:
    total = 0
    files = sorted(data_dir.glob("moneyflow_dc_*_top*.csv"))
    for path in files:
        m = _DC_PATTERN.match(path.name)
        if not m:
            announce(f"skip {path.name}: pattern mismatch")
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            announce(f"skip {path.name}: {exc}")
            continue
        # 第一列名常带 BOM (﻿trade_date) 需清洗
        df.columns = [c.lstrip("﻿") for c in df.columns]
        n = moneyflow_repo.upsert_df(df, top_n=int(m.group(2)))
        total += n
        announce(f"{path.name} -> {n} rows")
    return total


def import_hot_stocks(cache_dir: Path) -> int:
    path = cache_dir / "hot_stocks_cache.json"
    if not path.exists():
        return 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    kv_repo.set_("hot_stocks", "latest", raw)
    announce(f"hot_stocks imported from {path.name}")
    return 1


def import_market_snapshots(cache_dir: Path) -> dict:
    market_dir = cache_dir / "market"
    stats = {"daily_files": 0, "daily_rows": 0, "flow_files": 0, "flow_rows": 0}
    if not market_dir.is_dir():
        return stats
    for path in sorted(market_dir.glob("daily_*.csv")):
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            announce(f"skip {path.name}: {exc}")
            continue
        n = market_snapshot_repo.upsert_daily_df(df)
        stats["daily_files"] += 1
        stats["daily_rows"] += n
    for path in sorted(market_dir.glob("flow_*.csv")):
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            announce(f"skip {path.name}: {exc}")
            continue
        n = market_snapshot_repo.upsert_flow_df(df)
        stats["flow_files"] += 1
        stats["flow_rows"] += n
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--cache-dir", default="data/cache")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    cache_dir = Path(args.cache_dir)

    mf_rows = import_moneyflow_dc(data_dir)
    announce(f"moneyflow_dc total imported rows: {mf_rows}")

    hot = import_hot_stocks(cache_dir)
    announce(f"hot_stocks imported: {hot}")

    snap = import_market_snapshots(cache_dir)
    announce(
        "market snapshots: "
        f"daily files={snap['daily_files']} rows={snap['daily_rows']}; "
        f"flow files={snap['flow_files']} rows={snap['flow_rows']}"
    )


if __name__ == "__main__":
    main()
