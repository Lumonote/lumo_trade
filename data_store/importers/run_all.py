"""One-shot helper: run every importer in sequence.

Usage:
    python -m data_store.importers.run_all                     # default paths
    python -m data_store.importers.run_all --data-dir /custom --cache-dir /custom/cache
"""
from __future__ import annotations

import argparse
from pathlib import Path

from data_store.importers import announce
from data_store.importers.import_ohlcv import run as run_ohlcv
from data_store.importers.import_sentiment import run as run_sentiment
from data_store.importers.import_market_basic import import_calendar, import_daily_basic
from data_store.importers.import_misc import (
    import_hot_stocks,
    import_market_snapshots,
    import_moneyflow_dc,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument(
        "--sentiment-dir",
        default="cache/sentiment",
        help="Defaults to ./cache/sentiment relative to cwd.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    cache_dir = Path(args.cache_dir)
    sentiment_dir = Path(args.sentiment_dir)

    announce(f"=== OHLCV ({data_dir}) ===")
    ohlcv_stats = run_ohlcv(data_dir)

    announce(f"=== Sentiment ({sentiment_dir}) ===")
    sentiment_stats = run_sentiment(sentiment_dir)

    announce(f"=== Calendar + daily_basic ({cache_dir}) ===")
    import_calendar(cache_dir)
    import_daily_basic(cache_dir)

    announce(f"=== Moneyflow_dc ({data_dir}) ===")
    mf_rows = import_moneyflow_dc(data_dir)

    announce(f"=== hot_stocks_cache ({cache_dir}) ===")
    import_hot_stocks(cache_dir)

    announce(f"=== Market snapshots ({cache_dir}) ===")
    snap = import_market_snapshots(cache_dir)

    announce("=== Done ===")
    announce(
        f"ohlcv files={ohlcv_stats['files']} rows={ohlcv_stats['rows']}; "
        f"sentiment files={sentiment_stats['files']} imported={sentiment_stats['imported']}; "
        f"moneyflow rows={mf_rows}; "
        f"market_daily rows={snap['daily_rows']}; market_flow rows={snap['flow_rows']}"
    )


if __name__ == "__main__":
    main()
