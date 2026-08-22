#!/usr/bin/env python3
"""全市场日线(market_daily)离线回填 —— 供股票池「入选后涨幅」取价。

默认回填「机会挖掘 run 覆盖的交易日区间」:第一次入选日之后的每个交易日都要有
全市场行情,才能给每只股票取到「次日开盘价」和「最新收盘价」。一天一次 Tushare
``daily(trade_date=...)`` 调用(约 5500 行),几十天的区间几十秒跑完。

    python scripts/backfill_market_daily.py                 # 自动区间(run 起始日→今天)
    python scripts/backfill_market_daily.py --start 2026-06-01 --end 2026-08-17
    python scripts/backfill_market_daily.py --max-days 10    # 只补最近缺的 10 天

页面侧也会按需自动补最近的交易日(webui/services 调用 ensure_dates),此脚本用于
一次性把历史区间补齐。
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_store import market_daily_fetch  # noqa: E402
from data_store.connection import get_conn  # noqa: E402


def _run_span() -> tuple[str, str]:
    """机会挖掘 run 的日期跨度(无 run 时回退最近 60 天)。"""
    row = get_conn().execute(
        "SELECT MIN(run_date), MAX(run_date) FROM opportunity_run"
    ).fetchone()
    today = dt.date.today().strftime("%Y-%m-%d")
    if row and row[0]:
        return str(row[0]), today
    return (dt.date.today() - dt.timedelta(days=60)).strftime("%Y-%m-%d"), today


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 market_daily 全市场日线")
    parser.add_argument("--start", help="起始日 YYYY-MM-DD(缺省=最早一次挖掘 run)")
    parser.add_argument("--end", help="结束日 YYYY-MM-DD(缺省=今天)")
    parser.add_argument("--max-days", type=int, default=None,
                        help="本次最多补几个交易日(缺省=全部缺失日)")
    args = parser.parse_args()

    span_start, span_end = _run_span()
    start = args.start or span_start
    end = args.end or span_end
    days = market_daily_fetch.open_days(start, end)
    if not days:
        print(f"✗ 取不到 {start}~{end} 的交易日历(Tushare Token 缺失或不可用)")
        return 1
    print(f"区间 {start} ~ {end}:{len(days)} 个交易日")
    stats = market_daily_fetch.ensure_dates(days, max_fetch=args.max_days)
    print(
        f"✓ 已有 {stats['filled']} 天 / 本次补 {stats['fetched']} 天 / "
        f"仍缺 {stats['remaining']} 天"
    )
    latest = market_daily_fetch.latest_filled_date()
    print(f"  最新可用行情日: {latest or '(无)'}")
    return 0 if stats["remaining"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
