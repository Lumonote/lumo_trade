"""One-shot importer: cache/sentiment/*.json -> sentiment_cache table.

Recognized cache_type prefixes (multi-word forms must precede single-word):
  overall_market, sector_constituents, sector_list, sector_name,
  capital_flow, dragon_tiger, moneyflow_ind_dc, moneyflow_mkt_dc, sector

For overall_market.json there is no identifier. For others, identifier is
the remaining filename stem after the prefix.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
from pathlib import Path
from typing import Tuple

from data_store import sentiment_repo
from data_store.connection import get_conn
from data_store.importers import announce


_PREFIXES = (
    "overall_market",
    "sector_constituents",
    "sector_list",
    "sector_name",
    "capital_flow",
    "dragon_tiger",
    "moneyflow_ind_dc",
    "moneyflow_mkt_dc",
    "sector",
)


def parse_filename(stem: str) -> Tuple[str, str]:
    """Return (cache_type, identifier) for a sentiment cache file stem."""
    for prefix in _PREFIXES:
        if stem == prefix:
            return prefix, ""
        if stem.startswith(prefix + "_"):
            return prefix, stem[len(prefix) + 1 :]
    return stem, ""


def _payload_with_timestamp(raw: dict) -> Tuple[dict, str]:
    """Strip the `{timestamp, data}` wrapper if present and return iso timestamp."""
    if isinstance(raw, dict) and "timestamp" in raw and "data" in raw and isinstance(raw["data"], dict):
        ts = float(raw["timestamp"])
        updated_at = _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")
        return raw["data"], updated_at
    return raw, _dt.datetime.now().isoformat(timespec="seconds")


def run(cache_dir: Path, dry_run: bool = False) -> dict:
    if not cache_dir.exists():
        announce(f"cache dir not found: {cache_dir}")
        return {"files": 0, "imported": 0, "skipped": 0}
    stats = {"files": 0, "imported": 0, "skipped": 0}
    conn = get_conn()
    for path in sorted(cache_dir.glob("*.json")):
        stats["files"] += 1
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            announce(f"skip {path.name}: parse error {exc}")
            stats["skipped"] += 1
            continue
        cache_type, identifier = parse_filename(path.stem)
        payload, updated_at = _payload_with_timestamp(raw)
        if dry_run:
            stats["imported"] += 1
            continue
        conn.execute(
            """
            INSERT INTO sentiment_cache(cache_type, identifier, payload, updated_at, ttl_seconds)
            VALUES(?,?,?,?,0)
            ON CONFLICT(cache_type, identifier) DO UPDATE SET
              payload=excluded.payload, updated_at=excluded.updated_at
            """,
            (cache_type, identifier, json.dumps(payload, ensure_ascii=False), updated_at),
        )
        stats["imported"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir",
        default=str(Path(os.environ.get("KRONOS_USER_DIR", ".")) / "cache" / "sentiment"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = Path.cwd() / cache_dir
    stats = run(cache_dir, dry_run=args.dry_run)
    by_type = sentiment_repo.count_by_type()
    announce(
        f"done: files={stats['files']} imported={stats['imported']} "
        f"skipped={stats['skipped']} by_type={by_type}"
    )


if __name__ == "__main__":
    main()
