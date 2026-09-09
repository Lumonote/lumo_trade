"""SQLite-backed business data store.

Public surface:
- `data_store.connection.get_conn()` — process-wide thread-local connection
- repo singletons: OHLCV_REPO, SENTIMENT_REPO, DAILY_BASIC_REPO,
  CALENDAR_REPO, MONEYFLOW_REPO, KV_REPO (added by phases P1-P4)
- institutional repos (P6): dragon_tiger_repo, hsgt_repo, holders_repo,
  survey_repo, fund_hold_repo, sync_log_repo
- opportunity runs: opportunity_repo
- hot-sector snapshots: hot_sector_repo

DB path defaults to `data/lumo_data.sqlite`; override with `KRONOS_SQLITE_PATH`.
"""
from data_store.connection import get_conn, close_conn, db_path
from data_store.schema import migrate
from data_store import (
    dragon_tiger_repo,
    hsgt_repo,
    holders_repo,
    survey_repo,
    fund_hold_repo,
    opportunity_repo,
    hot_sector_repo,
    sync_log_repo,
)

__all__ = [
    "get_conn", "close_conn", "db_path", "migrate",
    "dragon_tiger_repo", "hsgt_repo", "holders_repo",
    "survey_repo", "fund_hold_repo", "opportunity_repo", "hot_sector_repo", "sync_log_repo",
]
