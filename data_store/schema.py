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
    (
        7,
        # 资金榜单(龙虎榜单,含游资净额) + 模拟盘台账 (P5)
        """
        -- 龙虎榜单(Tushare top_list 口径:个股/日,net_amount 含游资净买入额)。
        -- 同一股票同日可因多条「上榜原因」出现多行,故 reason 进主键。
        CREATE TABLE IF NOT EXISTS dragon_tiger_list (
          trade_date    TEXT NOT NULL,
          ts_code       TEXT NOT NULL,
          name          TEXT,
          close         REAL,
          pct_change    REAL,
          turnover_rate REAL,
          amount        REAL,   -- 当日总成交额
          l_buy         REAL,   -- 龙虎榜买入额
          l_sell        REAL,   -- 龙虎榜卖出额
          l_amount      REAL,   -- 龙虎榜成交额
          net_amount    REAL,   -- 龙虎榜净买入额(含游资) ← 排序键
          net_rate      REAL,
          amount_rate   REAL,
          reason        TEXT NOT NULL DEFAULT '',  -- 上榜原因
          PRIMARY KEY (trade_date, ts_code, reason)
        );
        CREATE INDEX IF NOT EXISTS idx_dtl_date_net ON dragon_tiger_list(trade_date, net_amount DESC);
        CREATE INDEX IF NOT EXISTS idx_dtl_code     ON dragon_tiger_list(ts_code, trade_date);

        -- 模拟盘单账户(id 恒为 1)
        CREATE TABLE IF NOT EXISTS paper_account (
          id           INTEGER PRIMARY KEY CHECK(id=1),
          initial_cash REAL NOT NULL,
          cash         REAL NOT NULL,
          created_at   TEXT NOT NULL,
          updated_at   TEXT NOT NULL
        );

        -- 委托(即时单直接 filled;open/close/limit 进 pending 等撮合)
        CREATE TABLE IF NOT EXISTS paper_order (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          ts_code       TEXT NOT NULL,
          name          TEXT,
          side          TEXT NOT NULL CHECK(side IN ('buy','sell')),
          price_type    TEXT NOT NULL CHECK(price_type IN ('market','open','close','limit')),
          limit_price   REAL,
          qty           INTEGER,
          amount_budget REAL,
          status        TEXT NOT NULL CHECK(status IN ('pending','filled','cancelled','rejected')),
          created_at    TEXT NOT NULL,
          created_date  TEXT NOT NULL,
          filled_at     TEXT,
          filled_price  REAL,
          filled_qty    INTEGER,
          fee           REAL,
          note          TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_porder_status ON paper_order(status, ts_code);

        -- 持仓(含费摊薄均价)
        CREATE TABLE IF NOT EXISTS paper_position (
          ts_code    TEXT PRIMARY KEY,
          name       TEXT,
          qty        INTEGER NOT NULL,
          avg_cost   REAL NOT NULL,
          opened_at  TEXT,
          updated_at TEXT
        );

        -- 成交流水(每笔 fill;卖出结算 realized_pnl)
        CREATE TABLE IF NOT EXISTS paper_trade (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id     INTEGER,
          ts_code      TEXT NOT NULL,
          name         TEXT,
          side         TEXT NOT NULL,
          price        REAL NOT NULL,
          qty          INTEGER NOT NULL,
          gross        REAL NOT NULL,
          fee          REAL NOT NULL,
          realized_pnl REAL,
          traded_at    TEXT NOT NULL,
          trade_date   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ptrade_code ON paper_trade(ts_code, traded_at);

        -- 每日权益曲线(回撤/收益率)
        CREATE TABLE IF NOT EXISTS paper_equity_curve (
          trade_date     TEXT PRIMARY KEY,
          cash           REAL,
          position_value REAL,
          total_equity   REAL,
          daily_pnl      REAL
        );

        -- 费用等配置(键值)
        CREATE TABLE IF NOT EXISTS paper_settings (
          key   TEXT PRIMARY KEY,
          value TEXT
        );
        """,
    ),
    (
        8,
        # 保留资金榜接口原始列,用于前端展开展示非标准字段。
        "",
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


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row or column in _table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_v8_raw_json(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "moneyflow_dc", "raw_json", "raw_json TEXT")
    _add_column_if_missing(conn, "dragon_tiger_list", "raw_json", "raw_json TEXT")


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
        if version == 8:
            _migrate_v8_raw_json(conn)
        elif sql.strip():
            conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES(?, ?)",
            (version, _dt.datetime.now().isoformat(timespec="seconds")),
        )
        current = version
    return current
