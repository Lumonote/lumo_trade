#!/usr/bin/env python3
"""市场级机构数据回填（E2，spec 2026-05-31 §6.3）。

把个股深度挖掘所需的机构数据批量灌入 sqlite，供 provider「读库优先」命中，
减少个股分析里的「数据不足」。

用法::

    # 指定股票
    python scripts/sync_institutional_data.py --codes 000001,600519
    # 已抓过 OHLCV 的自选集（ohlcv 表里的股票）
    python scripts/sync_institutional_data.py --watchlist --tables lhb,hsgt,top10,fund
    # 全市场（daily_basic 5400+ 码，耗时长，建议收盘后 cron）
    python scripts/sync_institutional_data.py --all --since 2026-03-01

表 (`--tables`，逗号分隔，默认 all):
    lhb    龙虎榜机构席位      (单股真实抓取)
    hsgt   北向持股            (单股真实抓取)
    top10  十大流通股东        ┐ 同由 holders provider 一次抓取
    gdhs   股东户数            ┘
    fund   重仓基金            (单股真实抓取 stock_fund_stock_holder)
    cyq    官方筹码分布        (单股 stock_cyq_em，30min 缓存)
    jgdy   机构调研            (按交易日全市场，单股无直拉；慢，默认仅近 N 个交易日)

退出码: 0 全部成功 / 1 部分失败 / 2 全部失败。单表/单股失败写 sync_log
(`status='failed'`) 但不阻塞其余，供 /api/diagnostics/data-sources 与前端降级文案使用。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_store import sync_log_repo

logger = logging.getLogger("sync_institutional")

# 单股真实抓取的表 → provider key（top10/gdhs 同由 holders 一次抓取，去重为一个 job）
_PROVIDER_BY_TABLE = {
    "lhb": "lhb", "hsgt": "hsgt", "fund": "fund", "cyq": "cyq",
    "top10": "holders", "gdhs": "holders",
}
_ALL_TABLES = sorted(set(_PROVIDER_BY_TABLE) | {"jgdy"})

# 机构调研列名在 akshare 不同版本间有出入，按候选解析（spec：防御式映射）。
_JGDY_DATE_CANDS = ("接待日期", "调研日期", "公告日期")
_JGDY_INST_CANDS = ("接待机构", "调研机构", "机构名称", "接待对象")


# --------------------------------------------------------------------------- helpers
def _to_ts_code(digits: str) -> str:
    """6 位代码 → ts_code（沪 .SH / 深 .SZ / 北 .BJ）。"""
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("4", "8")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _norm_code(code: str) -> str:
    c = str(code).strip().upper()
    if "." in c:
        return c
    digits = re.sub(r"\D", "", c)
    return _to_ts_code(digits) if len(digits) == 6 else c


def _to_yyyymmdd(value: Optional[str]) -> str:
    s = (value or "").strip()
    if s:
        return s.replace("-", "")
    return (_dt.date.today() - _dt.timedelta(days=90)).strftime("%Y%m%d")


def _yyyymmdd_to_iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d


def _parse_tables(spec: Optional[str]) -> List[str]:
    if not spec or spec.strip().lower() == "all":
        return list(_ALL_TABLES)
    toks = [t.strip().lower() for t in spec.split(",") if t.strip()]
    bad = [t for t in toks if t not in _ALL_TABLES]
    if bad:
        raise SystemExit(f"unknown --tables {bad}; valid: {_ALL_TABLES}")
    return toks


def _provider_jobs(tables: List[str]) -> List[str]:
    """请求的表 → 去重后的 provider key 列表（jgdy 单独走市场级路径）。"""
    jobs: List[str] = []
    for t in tables:
        key = _PROVIDER_BY_TABLE.get(t)
        if key and key not in jobs:
            jobs.append(key)
    return jobs


def _resolve_codes(args) -> List[str]:
    if args.codes:
        return [_norm_code(c) for c in args.codes.split(",") if c.strip()]
    from data_store.connection import get_conn
    if args.all:
        rows = get_conn().execute(
            "SELECT DISTINCT ts_code FROM daily_basic WHERE ts_code IS NOT NULL ORDER BY ts_code"
        ).fetchall()
        codes = [r[0] for r in rows]
    elif args.watchlist:
        rows = get_conn().execute(
            "SELECT DISTINCT code FROM ohlcv WHERE code IS NOT NULL ORDER BY code"
        ).fetchall()
        codes = [_norm_code(r[0]) for r in rows]
    else:
        return []
    if args.limit:
        codes = codes[: args.limit]
    return codes


def _trade_dates_since(since: Optional[str], cap: int) -> List[str]:
    from data_store import calendar_repo
    start = _to_yyyymmdd(since)
    days = sorted((d for d in calendar_repo.open_days() if d >= start), reverse=True)
    if cap and len(days) > cap:
        logger.warning(
            "jgdy: 区间内 %d 个交易日，按 --jgdy-max-days 截到最近 %d 个（避免全市场接口耗时过长）",
            len(days), cap,
        )
        days = days[:cap]
    return days


def _rowcount(job: str, res) -> Optional[int]:
    d = getattr(res, "data", None) or {}
    try:
        if job == "holders":
            return len((d.get("top10_floatholders") or {}).get("rows") or [])
        if job == "fund":
            return len(d.get("rows") or [])
        if job == "lhb":
            return len(d.get("history_90d") or [])
        if job in ("hsgt", "cyq"):
            return len(d.get("trend_30d") or [])
    except Exception:  # noqa: BLE001
        return None
    return None


def _normalize_jgdy(df, default_iso_date: str) -> List[Dict[str, Any]]:
    """全市场机构调研明细 → jgdy_detail 行（防御式列解析）。"""
    if df is None or getattr(df, "empty", True):
        return []
    cols = set(df.columns)
    date_col = next((c for c in _JGDY_DATE_CANDS if c in cols), None)
    inst_col = next((c for c in _JGDY_INST_CANDS if c in cols), None)
    way_col = "接待方式" if "接待方式" in cols else None
    place_col = "接待地点" if "接待地点" in cols else None
    rows: List[Dict[str, Any]] = []
    for idx, r in df.iterrows():
        digits = re.sub(r"\D", "", str(r.get("代码") or ""))
        if len(digits) != 6:
            continue
        sdate = default_iso_date
        if date_col and r.get(date_col):
            sdate = str(r.get(date_col))[:10]
        inst = str(r.get(inst_col) or "").strip() if inst_col else ""
        if not inst:
            # 无机构名时用「接待方式#序号」占位，保证 (ts_code,date,inst) 主键唯一
            inst = f"{r.get(way_col) or '调研'}#{idx}"
        rows.append({
            "ts_code": _to_ts_code(digits),
            "survey_date": sdate,
            "inst_name": inst[:120],
            "reception": str(r.get(way_col) or "") if way_col else "",
            "topic": str(r.get(place_col) or "") if place_col else "",
        })
    return rows


# --------------------------------------------------------------------------- sync
def _sync_one(job: str, providers: Dict[str, Any], ts_code: str) -> tuple[str, Optional[int], Optional[str]]:
    prov = providers.get(job)
    if prov is None:
        return "failed", None, f"no provider for {job}"
    fetch = getattr(prov, "_fetch_and_save", None)
    if callable(fetch):
        fetch(ts_code)               # 强制回填（即使库里已有也重抓最新）
    res = prov.get(ts_code)
    if getattr(res, "data_status", None) in ("fresh", "stale"):
        return "ok", _rowcount(job, res), None
    return "failed", 0, getattr(res, "reason", None)


def _sync_jgdy(adapter, since: Optional[str], cap: int, ran_at: str) -> List[str]:
    from data_store import survey_repo
    dates = _trade_dates_since(since, cap)
    if not dates:
        logger.warning("jgdy: 区间内无交易日（trade_calendar 为空？），跳过")
        return []
    statuses: List[str] = []
    for d in dates:
        try:
            df = adapter.fetch("jgdy", date=d)
            rows = _normalize_jgdy(df, _yyyymmdd_to_iso(d))
            survey_repo.upsert_rows(rows)
            sync_log_repo.append("jgdy", f"date:{d}", ran_at, "ok", rows=len(rows))
            statuses.append("ok")
            logger.info("jgdy %s -> ok (rows=%d)", d, len(rows))
        except Exception as exc:  # noqa: BLE001
            sync_log_repo.append("jgdy", f"date:{d}", ran_at, "failed", error=str(exc))
            statuses.append("failed")
            logger.warning("jgdy %s -> failed: %s", d, exc)
    return statuses


def _exit_code(statuses: List[str]) -> int:
    if not statuses:
        return 0
    oks = sum(1 for s in statuses if s == "ok")
    if oks == len(statuses):
        return 0
    return 2 if oks == 0 else 1


def run(args, providers: Optional[Dict[str, Any]] = None) -> int:
    if providers is None:
        from webui.services.stock_suite_service import _build_institutional_providers
        providers = _build_institutional_providers()

    ran_at = _dt.datetime.now().isoformat(timespec="seconds")
    tables = _parse_tables(args.tables)
    jobs = _provider_jobs(tables)
    codes = _resolve_codes(args)
    statuses: List[str] = []

    if jobs and not codes:
        logger.warning("未解析到任何股票代码（--codes/--watchlist/--all），跳过单股表")

    logger.info("开始回填：codes=%d tables=%s jobs=%s", len(codes), tables, jobs)
    for i, code in enumerate(codes, 1):
        for job in jobs:
            try:
                status, rows, err = _sync_one(job, providers, code)
            except Exception as exc:  # noqa: BLE001
                status, rows, err = "failed", 0, str(exc)
            sync_log_repo.append(job, code, ran_at, status, rows=rows, error=err)
            statuses.append(status)
        if i % 50 == 0:
            logger.info("...已处理 %d/%d", i, len(codes))

    if "jgdy" in tables:
        adapter = getattr(providers.get("survey"), "_adapter", None) or \
            getattr(providers.get("lhb"), "_adapter", None)
        if adapter is not None:
            statuses.extend(_sync_jgdy(adapter, args.since, args.jgdy_max_days, ran_at))
        else:
            logger.warning("jgdy: 无可用 adapter，跳过")

    code = _exit_code(statuses)
    ok = sum(1 for s in statuses if s == "ok")
    logger.info("完成：%d/%d ok，退出码 %d", ok, len(statuses), code)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="市场级机构数据回填 (E2)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--codes", help="逗号分隔的股票代码（600519 或 600519.SH 均可）")
    g.add_argument("--watchlist", action="store_true", help="ohlcv 表已有的股票")
    g.add_argument("--all", action="store_true", help="daily_basic 全市场（慢）")
    p.add_argument("--since", help="起始日期 YYYY-MM-DD（jgdy 用，默认近 90 天）")
    p.add_argument("--tables", default="all", help=f"逗号分隔，默认 all；可选 {_ALL_TABLES}")
    p.add_argument("--limit", type=int, help="最多处理多少只（调试/分批）")
    p.add_argument("--jgdy-max-days", type=int, default=20, dest="jgdy_max_days",
                   help="jgdy 最多回填多少个最近交易日（默认 20）")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
