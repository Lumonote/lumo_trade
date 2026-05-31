"""DDL + version-tracked migrations for kronos_data.sqlite.

Each migration is an (version, sql) pair. `migrate()` applies any version
strictly greater than the current `schema_version.MAX(version)` and records
the new version. Safe to call repeatedly.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
from typing import List, Tuple


_MIGRATIONS: List[Tuple[int, str]] = [
    (
        1,
        # OHLCV time-series (P1)
        """
        CREATE TABLE IF NOT EXISTS ohlcv (
          code       TEXT NOT NULL,
          frequency  TEXT NOT NULL CHECK(frequency IN ('1d','5m','15m','30m','60m')),
          ts         TEXT NOT NULL,
          open       REAL,
          high       REAL,
          low        REAL,
          close      REAL,
          volume     REAL,
          amount     REAL,
          PRIMARY KEY (code, frequency, ts)
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS idx_ohlcv_code_freq_ts ON ohlcv(code, frequency, ts DESC);
        """,
    ),
    (
        2,
        # Sentiment cache (P2)
        """
        CREATE TABLE IF NOT EXISTS sentiment_cache (
          cache_type   TEXT NOT NULL,
          identifier   TEXT NOT NULL DEFAULT '',
          payload      TEXT NOT NULL,
          updated_at   TEXT NOT NULL,
          ttl_seconds  INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (cache_type, identifier)
        );
        """,
    ),
    (
        3,
        # daily_basic + trade_calendar (P3)
        """
        CREATE TABLE IF NOT EXISTS daily_basic (
          ts_code         TEXT NOT NULL,
          trade_date      TEXT NOT NULL,
          close           REAL,
          turnover_rate   REAL,
          turnover_rate_f REAL,
          volume_ratio    REAL,
          pe              REAL,
          pe_ttm          REAL,
          pb              REAL,
          ps              REAL,
          ps_ttm          REAL,
          dv_ratio        REAL,
          dv_ttm          REAL,
          total_share     REAL,
          float_share     REAL,
          free_share      REAL,
          total_mv        REAL,
          circ_mv         REAL,
          PRIMARY KEY (ts_code, trade_date)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS trade_calendar (
          cal_date TEXT PRIMARY KEY,
          is_open  INTEGER NOT NULL DEFAULT 1
        );
        """,
    ),
    (
        4,
        # moneyflow_dc + kv_cache (P4)
        """
        CREATE TABLE IF NOT EXISTS moneyflow_dc (
          trade_date          TEXT NOT NULL,
          ts_code             TEXT NOT NULL,
          top_n               INTEGER NOT NULL,
          name                TEXT,
          pct_change          REAL,
          close               REAL,
          net_amount          REAL,
          net_amount_rate     REAL,
          buy_elg_amount      REAL,
          buy_elg_amount_rate REAL,
          buy_lg_amount       REAL,
          buy_lg_amount_rate  REAL,
          buy_md_amount       REAL,
          buy_md_amount_rate  REAL,
          buy_sm_amount       REAL,
          buy_sm_amount_rate  REAL,
          amount_unit         TEXT,
          PRIMARY KEY (trade_date, ts_code, top_n)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS kv_cache (
          namespace   TEXT NOT NULL,
          key         TEXT NOT NULL,
          payload     TEXT NOT NULL,
          updated_at  TEXT NOT NULL,
          ttl_seconds INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (namespace, key)
        );
        """,
    ),
    (
        5,
        # Full-market daily snapshots: market_daily + market_flow_daily (P4)
        """
        CREATE TABLE IF NOT EXISTS market_daily (
          ts_code   TEXT NOT NULL,
          trade_date TEXT NOT NULL,
          open  REAL, high REAL, low REAL, close REAL, pre_close REAL,
          change REAL, pct_chg REAL,
          vol    REAL, amount REAL,
          PRIMARY KEY (ts_code, trade_date)
        ) WITHOUT ROWID;

        CREATE TABLE IF NOT EXISTS market_flow_daily (
          trade_date          TEXT NOT NULL,
          ts_code             TEXT NOT NULL,
          name                TEXT,
          pct_change          REAL,
          close               REAL,
          net_amount          REAL,
          net_amount_rate     REAL,
          buy_elg_amount      REAL,
          buy_elg_amount_rate REAL,
          buy_lg_amount       REAL,
          buy_lg_amount_rate  REAL,
          buy_md_amount       REAL,
          buy_md_amount_rate  REAL,
          buy_sm_amount       REAL,
          buy_sm_amount_rate  REAL,
          PRIMARY KEY (trade_date, ts_code)
        ) WITHOUT ROWID;
        """,
    ),
    (
        6,
        """
        CREATE TABLE IF NOT EXISTS dragon_tiger_inst (
          ts_code          TEXT NOT NULL,
          trade_date       TEXT NOT NULL,
          inst_name        TEXT NOT NULL,
          side             TEXT NOT NULL,
          net_amount       REAL,
          buy_amount       REAL,
          sell_amount      REAL,
          is_quant         INTEGER DEFAULT 0,
          quant_confidence TEXT,
          reason           TEXT,
          PRIMARY KEY (ts_code, trade_date, inst_name, side)
        );
        CREATE INDEX IF NOT EXISTS idx_lhbi_code_date
          ON dragon_tiger_inst(ts_code, trade_date);
        CREATE INDEX IF NOT EXISTS idx_lhbi_quant
          ON dragon_tiger_inst(is_quant, trade_date);

        CREATE TABLE IF NOT EXISTS hsgt_individual (
          ts_code     TEXT NOT NULL,
          trade_date  TEXT NOT NULL,
          hold_vol    REAL,
          hold_ratio  REAL,
          market_cap  REAL,
          PRIMARY KEY (ts_code, trade_date)
        );

        CREATE TABLE IF NOT EXISTS top10_floatholders (
          ts_code       TEXT NOT NULL,
          end_date      TEXT NOT NULL,
          holder_rank   INTEGER NOT NULL,
          holder_name   TEXT NOT NULL,
          hold_amount   REAL,
          hold_ratio    REAL,
          change_type   TEXT,
          change_amount REAL,
          PRIMARY KEY (ts_code, end_date, holder_rank)
        );

        CREATE TABLE IF NOT EXISTS stk_holdernumber (
          ts_code     TEXT NOT NULL,
          end_date    TEXT NOT NULL,
          holder_num  INTEGER,
          avg_hold    REAL,
          pct_change  REAL,
          PRIMARY KEY (ts_code, end_date)
        );

        CREATE TABLE IF NOT EXISTS jgdy_detail (
          ts_code      TEXT NOT NULL,
          survey_date  TEXT NOT NULL,
          inst_name    TEXT NOT NULL,
          reception    TEXT,
          topic        TEXT,
          PRIMARY KEY (ts_code, survey_date, inst_name)
        );

        CREATE TABLE IF NOT EXISTS fund_hold_detail (
          ts_code      TEXT NOT NULL,
          end_date     TEXT NOT NULL,
          fund_code    TEXT NOT NULL,
          fund_name    TEXT,
          hold_shares  REAL,
          market_value REAL,
          nv_ratio     REAL,
          PRIMARY KEY (ts_code, end_date, fund_code)
        );

        CREATE TABLE IF NOT EXISTS sync_log (
          source    TEXT NOT NULL,
          ts_code   TEXT NOT NULL DEFAULT '',
          ran_at    TEXT NOT NULL,
          status    TEXT NOT NULL,
          rows      INTEGER,
          error     TEXT,
          PRIMARY KEY (source, ts_code, ran_at)
        );
        CREATE INDEX IF NOT EXISTS idx_synclog_source_ran
          ON sync_log(source, ran_at DESC);
        """,
    ),
]


def _current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
          version    INTEGER PRIMARY KEY,
          applied_at TEXT NOT NULL
        )
        """
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the final version.

    Each migration script uses IF NOT EXISTS, so a partial failure followed
    by re-run lands in the same final state. We do not wrap in a transaction
    because `executescript` auto-commits any pending transaction in
    autocommit-mode connections.
    """
    current = _current_version(conn)
    for version, sql in _MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
            (version, _dt.datetime.now().isoformat(timespec="seconds")),
        )
        current = version
    return current
