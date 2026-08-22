# -*- coding: utf-8 -*-
"""板块日序列历史回填 —— 把 moneyflow_dc 已有交易日逐日聚合进 sector_daily_metrics。

幂等:同 (trade_date, sector, sector_type) 覆盖写。默认跳过已有数据的日期,
``--force`` 全量重算。映射按天重建代价高,这里整轮共用一份 as_of=最新日的映射
(行业分类稳定,概念快照本身也只有最近一份)。

用法:
    python scripts/backfill_sector_series.py                # 增量
    python scripts/backfill_sector_series.py --force        # 全量重算
    python scripts/backfill_sector_series.py --days 30      # 只回填最近 30 个交易日
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import sector_series  # noqa: E402
from data_store import sector_map_repo  # noqa: E402
from data_store.connection import get_conn  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="回填板块日序列")
    parser.add_argument("--days", type=int, default=0, help="只回填最近 N 个交易日(0=全部)")
    parser.add_argument("--force", action="store_true", help="已有数据的日期也重算")
    args = parser.parse_args()

    conn = get_conn()
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM moneyflow_dc WHERE top_n=0 ORDER BY trade_date ASC")]
    if args.days:
        dates = dates[-args.days:]
    if not dates:
        print("moneyflow_dc 无 top_n=0 数据,先跑资金流回填")
        return 1

    done = set() if args.force else {
        r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM sector_daily_metrics")}
    todo = [d for d in dates if d not in done]
    print(f"资金流交易日 {len(dates)} 天,待回填 {len(todo)} 天")
    if not todo:
        return 0

    mapping = sector_map_repo.build_map(as_of=dates[-1])
    universe = [r[0] for r in conn.execute(
        "SELECT DISTINCT ts_code FROM moneyflow_dc WHERE trade_date=? AND top_n=0",
        (dates[-1],))]
    cov = sector_map_repo.coverage(mapping, universe)
    print(f"映射覆盖度 {cov['ratio']:.1%}(命中 {cov['mapped']} / 未命中 {cov['unmapped']})")
    if cov["ratio"] < 0.7:
        print("⚠️ 覆盖度低于 70%,板块序列会失真;请先补映射数据源后再回填")
        return 2

    total = 0
    for i, date in enumerate(todo, 1):
        written = sector_series.rebuild_day(date, mapping=mapping)
        total += written
        if i % 20 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] {date} → 累计 {total} 条")
    print(f"完成:{len(todo)} 天 / {total} 条板块记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
