"""One-shot importer: legacy OHLCV CSVs -> ohlcv table.

Sources scanned (under KRONOS_DATA_DIR or ./data):
- data/{freq}_{code}.csv   — current fetch_data.py output (e.g. 1d_688343.csv)
- data/cache/ohlcv/{code}.csv — older daily cache (timestamps column = date)
- data/XSHE_day_{code}.csv / XSHG_day_{code}.csv / XSHE_5min_*.csv / XSHG_5min_*.csv — legacy

Files with the wrong header (e.g. 5m_688110.csv uses 'timestamp' singular and ts_code)
are skipped with a warning so a bad file never aborts the bulk import.

Usage:
    python -m data_store.importers.import_ohlcv
    python -m data_store.importers.import_ohlcv --data-dir /custom/data --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Iterator, Tuple

import pandas as pd

from data_store import ohlcv_repo
from data_store.importers import announce


_NEW_FMT = re.compile(r"^(1d|5m|15m|30m|60m)_([0-9]{6})\.csv$")
_LEGACY_FMT = re.compile(r"^(XSHE|XSHG)_(day|5min|15min|30min|60min)_([0-9]{6})\.csv$")
_LEGACY_PERIOD = {"day": "1d", "5min": "5m", "15min": "15m", "30min": "30m", "60min": "60m"}


def iter_csv_targets(data_dir: Path) -> Iterator[Tuple[Path, str, str]]:
    """Yield (path, code, frequency) for every recognized OHLCV CSV under data_dir."""
    for p in sorted(data_dir.glob("*.csv")):
        m = _NEW_FMT.match(p.name)
        if m:
            yield p, m.group(2), m.group(1)
            continue
        m = _LEGACY_FMT.match(p.name)
        if m:
            yield p, m.group(3), _LEGACY_PERIOD[m.group(2)]
            continue

    cache_dir = data_dir / "cache" / "ohlcv"
    if cache_dir.is_dir():
        for p in sorted(cache_dir.glob("*.csv")):
            code = p.stem
            if code.isdigit():
                yield p, code, "1d"


def _read_csv_safely(path: Path) -> "pd.DataFrame | None":
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        announce(f"skip {path.name}: read error {exc}")
        return None
    if "timestamps" not in df.columns:
        # cache/ohlcv format uses 'timestamps' too; legacy 5m_688110 uses 'timestamp'
        if "timestamp" in df.columns:
            df = df.rename(columns={"timestamp": "timestamps"})
        else:
            announce(f"skip {path.name}: no timestamps column (cols={list(df.columns)})")
            return None
    return df


def import_file(path: Path, code: str, frequency: str, dry_run: bool) -> int:
    df = _read_csv_safely(path)
    if df is None or df.empty:
        return 0
    if dry_run:
        return len(df)
    return ohlcv_repo.upsert_df(code, frequency, df)


def run(data_dir: Path, dry_run: bool = False) -> dict:
    stats = {"files": 0, "rows": 0, "skipped": 0}
    for path, code, freq in iter_csv_targets(data_dir):
        n = import_file(path, code, freq, dry_run)
        if n <= 0:
            stats["skipped"] += 1
            continue
        stats["files"] += 1
        stats["rows"] += n
        announce(f"{path.name} -> {code}/{freq}: {n} rows{' (dry)' if dry_run else ''}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=os.environ.get("KRONOS_DATA_DIR", "data"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"data dir not found: {data_dir}")
    stats = run(data_dir, dry_run=args.dry_run)
    announce(f"done: files={stats['files']} rows={stats['rows']} skipped={stats['skipped']}")


if __name__ == "__main__":
    main()
