"""Import calendar + daily_basic from data/cache/*."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from data_store import calendar_repo, daily_basic_repo
from data_store.importers import announce


def import_calendar(cache_dir: Path) -> int:
    path = cache_dir / "calendar" / "trade_cal.csv"
    if not path.exists():
        announce(f"calendar source not found: {path}")
        return 0
    df = pd.read_csv(path, dtype=str)
    if "cal_date" not in df.columns:
        announce("calendar CSV missing cal_date column; skipping")
        return 0
    is_open = df["is_open"].astype(int).tolist() if "is_open" in df.columns else [1] * len(df)
    rows = list(zip(df["cal_date"].astype(str).tolist(), is_open))
    written = 0
    for d, op in rows:
        written += calendar_repo.upsert([d], is_open=op)
    announce(f"calendar imported: {len(rows)} rows -> total {calendar_repo.count()}")
    return written


def import_daily_basic(cache_dir: Path) -> int:
    market_dir = cache_dir / "market"
    if not market_dir.is_dir():
        announce(f"market dir not found: {market_dir}")
        return 0
    files = sorted(market_dir.glob("basic_*.csv"))
    pattern = re.compile(r"^basic_(\d{8})\.csv$")
    total = 0
    for path in files:
        if not pattern.match(path.name):
            continue
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            announce(f"skip {path.name}: read error {exc}")
            continue
        total += daily_basic_repo.upsert_df(df)
    announce(f"daily_basic imported: {len(files)} files -> rows={total}")
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", default="data/cache")
    args = parser.parse_args()
    cache_dir = Path(args.cache_dir)
    import_calendar(cache_dir)
    import_daily_basic(cache_dir)


if __name__ == "__main__":
    main()
