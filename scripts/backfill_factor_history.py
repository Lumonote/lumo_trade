#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""因子历史回填 —— 主力资金(moneyflow_dc) + 期指多空(kv futures_rank),全部入 SQLite。

为机会挖掘算法 v25 因子(主力资金/期指多空)提供回测窗口(2025-11~2026-03)历史数据:

- 主力资金: Tushare ``moneyflow_dc`` 按日全市场快照,经 moneyflow_repo 写入
  bucket ``top_n=0``(资金榜全市场快照哨兵,与资金榜页共用,回填对页面同样有益)。
  已存在的日期自动跳过(``existing_dates``),幂等可重跑。
- 期指多空: 复用 ``webui.services.futures_service._load_day_rank``(中金所 CSV →
  Tushare fut_holding 兜底,带 deadline 防护),按 (品种,日期) 整包写 kv_cache
  namespace ``futures_rank``;kv 命中即跳过,幂等。

用法(token 在用户配置目录,CLI 需显式指定):
    KRONOS_CONFIG_DIR="$HOME/Library/Application Support/com.lumo.app/config" \
        python scripts/backfill_factor_history.py --start 20251105 --only all
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _trade_dates(pro, start: str, end: str) -> list:
    df = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    return sorted(str(d) for d in df["cal_date"].tolist())


def backfill_moneyflow(pro, dates: list, throttle: float) -> None:
    from data_store import moneyflow_repo

    have = moneyflow_repo.existing_dates([_iso(d) for d in dates], snapshot_top_n=0)
    todo = [d for d in dates if _iso(d) not in have]
    print(f"[moneyflow] 全窗口 {len(dates)} 天, 已有 {len(dates) - len(todo)}, 待回填 {len(todo)}", flush=True)
    written = 0
    for n, d in enumerate(todo, 1):
        try:
            df = pro.moneyflow_dc(trade_date=d)
        except Exception as exc:  # noqa: BLE001 限流/网络抖动: 记日志继续,幂等可重跑
            print(f"[moneyflow] {d} FAIL: {exc}", flush=True)
            time.sleep(max(throttle, 2.0))
            continue
        if df is None or df.empty:
            print(f"[moneyflow] {d} 空数据(源无当日)", flush=True)
            continue
        work = df.copy()
        work["_amount_unit"] = "万元"
        written += moneyflow_repo.upsert_df(work, top_n=0)
        if n % 10 == 0 or n == len(todo):
            print(f"[moneyflow] {n}/{len(todo)} 天, 累计写入 {written} 行", flush=True)
        time.sleep(throttle)


def backfill_futures(dates: list, throttle: float) -> None:
    from webui.services import futures_service as fs

    ok = miss = 0
    for n, d in enumerate(dates, 1):
        for variety in fs.VARIETIES:
            try:
                if fs._load_day_rank(variety, d):
                    ok += 1
                else:
                    miss += 1
            except Exception as exc:  # noqa: BLE001
                miss += 1
                print(f"[futures] {variety}:{d} FAIL: {exc}", flush=True)
            time.sleep(throttle)
        if n % 10 == 0 or n == len(dates):
            print(f"[futures] {n}/{len(dates)} 天, 命中 {ok} / 缺失 {miss}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="主力资金+期指多空 因子历史回填(SQLite)")
    parser.add_argument("--start", default="20251105", help="起始交易日 YYYYMMDD(默认回测窗口前10个交易日)")
    parser.add_argument("--end", default=dt.date.today().strftime("%Y%m%d"), help="结束交易日 YYYYMMDD(默认今天)")
    parser.add_argument("--only", choices=["moneyflow", "futures", "all"], default="all")
    parser.add_argument("--throttle", type=float, default=0.3, help="每次外部请求间隔秒")
    args = parser.parse_args()

    from data_store.connection import get_conn
    from data_store import tushare_client

    for row in get_conn().execute("PRAGMA database_list").fetchall():
        print(f"[db] {row[1]} -> {row[2]}", flush=True)

    pro = tushare_client.get_pro()
    if pro is None:
        print("❌ 无 Tushare token(需 KRONOS_CONFIG_DIR 指向用户配置目录)", flush=True)
        return 1
    dates = _trade_dates(pro, args.start, args.end)
    print(f"[calendar] {args.start}~{args.end} 共 {len(dates)} 个交易日", flush=True)

    if args.only in ("moneyflow", "all"):
        backfill_moneyflow(pro, dates, args.throttle)
    if args.only in ("futures", "all"):
        backfill_futures(dates, max(args.throttle, 0.1))
    print("[done]", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
