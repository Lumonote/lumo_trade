#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v25 新因子历史加载 —— 主力资金(moneyflow_dc) + 期指多空(kv futures_rank)。

sim(回测富集)/分析脚本/live(opportunity_scorer) 三方共用同一实现,
延续 scoring_rules 的双轨统一原则:因子取数逻辑只此一份。

数据来源(全部 SQLite,见 scripts/backfill_factor_history.py):
- moneyflow_dc bucket top_n=0: 全市场每日主力资金快照(net_amount 万元 / net_amount_rate %)
- kv_cache namespace ``futures_rank``: (品种,日期) 中金所前20席位排名整包,
  取 ``aggregate.summary`` 的 net(净持仓,张) / net_chg(当日净变动,张)。

因子定义:
- main_net_rate: 当日主力净流入率 %(net_amount / 成交额)
- main_net_amount: 当日主力净流入额(万元)
- main_in_days3: 近3个交易日主力净流入为正的天数(0-3;不足3天按已有天数计)
- fut_net_chg: 四品种(IF/IH/IC/IM)前20席位当日净持仓变动之和(张;>0 偏多)
- fut_net_chg_3d: 上式近3交易日滚动和(平滑单日噪声)

缺日期/缺股票 → 对应键缺失,消费方按 v24 约定「因子缺失规则不触发」。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

FUT_VARIETIES = ("IF", "IH", "IC", "IM")
_KV_NAMESPACE = "futures_rank"


def _iso(date_str: str) -> str:
    s = str(date_str or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _yyyymmdd(date_str: str) -> str:
    return _iso(date_str).replace("-", "")


def _code6(code) -> str:
    s = str(code or "").split(".")[0].strip()
    return s.zfill(6) if s.isdigit() else s


def load_moneyflow_factors(start_date: str, end_date: str,
                           codes: Optional[Iterable] = None) -> Dict[Tuple[str, str], Dict]:
    """窗口内主力资金因子 ``{(iso日期, 6位代码): {main_net_rate, main_net_amount, main_in_days3}}``。

    一次窗口查询 + 内存滚动,避免逐行回库;codes 为 None 时取全市场。
    """
    from data_store.connection import get_conn

    lo, hi = _iso(start_date), _iso(end_date)
    rows = get_conn().execute(
        "SELECT trade_date, ts_code, net_amount, net_amount_rate FROM moneyflow_dc "
        "WHERE top_n=0 AND trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (lo, hi),
    ).fetchall()
    wanted = {_code6(c) for c in codes} if codes is not None else None
    by_code: Dict[str, List[Tuple[str, float, float]]] = {}
    for trade_date, ts_code, net_amount, net_rate in rows:
        code = _code6(ts_code)
        if wanted is not None and code not in wanted:
            continue
        by_code.setdefault(code, []).append(
            (str(trade_date), net_amount, net_rate))
    out: Dict[Tuple[str, str], Dict] = {}
    for code, series in by_code.items():
        series.sort(key=lambda r: r[0])
        for idx, (day, net_amount, net_rate) in enumerate(series):
            recent = series[max(0, idx - 2):idx + 1]
            out[(day, code)] = {
                "main_net_rate": net_rate,
                "main_net_amount": net_amount,
                "main_in_days3": sum(1 for _, amt, _ in recent
                                     if amt is not None and amt > 0),
            }
    return out


def _day_regime(yyyymmdd: str) -> Optional[Dict]:
    """单日四品种 net/net_chg 合计;kv 缺该日任一品种时按已有品种合计,全缺 → None。"""
    from data_store import kv_repo

    net = chg = 0
    found = 0
    for variety in FUT_VARIETIES:
        hit = kv_repo.get(_KV_NAMESPACE, f"{variety}:{yyyymmdd}")
        if not hit or not hit[0]:
            continue
        summary = ((hit[0].get("aggregate") or {}).get("summary") or {})
        net += int(summary.get("net") or 0)
        chg += int(summary.get("net_chg") or 0)
        found += 1
    if not found:
        return None
    return {"net": net, "net_chg": chg, "varieties": found}


def load_futures_regime(dates: Iterable, max_back_days: int = 3) -> Dict[str, Dict]:
    """逐报告日期指多空因子 ``{iso日期: {fut_net_chg, fut_net_chg_3d, fut_net}}``。

    周末/节假日生成的报告底层行情是上一交易日 → 每个请求日期自动回看最多
    ``max_back_days`` 个自然日取最近已发布数据;3日滚动按「已发布日序列」计算。
    """
    import datetime as dt

    request = sorted({_iso(d) for d in dates if str(d or "").strip()})
    if not request:
        return {}
    probe = set()
    for day in request:
        try:
            base = dt.date.fromisoformat(day)
        except ValueError:
            continue
        for back in range(max_back_days + 1):
            probe.add((base - dt.timedelta(days=back)).isoformat())
    day_values: Dict[str, Dict] = {}
    for day in sorted(probe):
        regime = _day_regime(_yyyymmdd(day))
        if regime:
            day_values[day] = regime
    known = sorted(day_values)
    rolled: Dict[str, Dict] = {}
    for idx, day in enumerate(known):
        window = known[max(0, idx - 2):idx + 1]
        rolled[day] = {
            "fut_net_chg": day_values[day]["net_chg"],
            "fut_net_chg_3d": sum(day_values[d]["net_chg"] for d in window),
            "fut_net": day_values[day]["net"],
        }
    out: Dict[str, Dict] = {}
    for day in request:
        src = nearest_on_or_before(day, known, max_back_days)
        if src:
            out[day] = rolled[src]
    return out


def nearest_on_or_before(day: str, sorted_days: List[str],
                         max_back_days: int = 3) -> Optional[str]:
    """ISO 日期序列中找 ``<= day`` 的最近日期,最多回看 max_back_days 个自然日。"""
    import bisect
    import datetime as dt

    if not sorted_days:
        return None
    idx = bisect.bisect_right(sorted_days, day) - 1
    if idx < 0:
        return None
    candidate = sorted_days[idx]
    try:
        limit = (dt.date.fromisoformat(day) - dt.timedelta(days=max_back_days)).isoformat()
    except ValueError:
        return None
    return candidate if candidate >= limit else None


def enrich_frame(df, date_col: str = "report_date", code_col: str = "code6"):
    """给回测/分析 DataFrame 增加 v25 因子列(sim 与分析共用同一 join 实现)。

    新增列: main_net_rate / main_net_amount / main_in_days3 / fut_net_chg / fut_net_chg_3d。
    数据缺失处保持 None → 共享规则按约定不触发。
    """
    import datetime as dt

    df = df.copy()
    new_cols = ("main_net_rate", "main_net_amount", "main_in_days3",
                "fut_net_chg", "fut_net_chg_3d")
    dates = sorted({_iso(str(d)) for d in df[date_col].dropna()})
    if not dates:
        for col in new_cols:
            df[col] = None
        return df
    lo = (dt.date.fromisoformat(dates[0]) - dt.timedelta(days=7)).isoformat()
    mf = load_moneyflow_factors(lo, dates[-1], codes=df[code_col].unique())
    mf_days = sorted({d for d, _ in mf})
    fut = load_futures_regime(dates)

    def mf_val(day, code, key):
        src = nearest_on_or_before(_iso(str(day)), mf_days)
        if not src:
            return None
        return (mf.get((src, _code6(code))) or {}).get(key)

    for key in ("main_net_rate", "main_net_amount", "main_in_days3"):
        df[key] = [mf_val(d, c, key) for d, c in zip(df[date_col], df[code_col])]
    for key in ("fut_net_chg", "fut_net_chg_3d"):
        df[key] = [(fut.get(_iso(str(d))) or {}).get(key) for d in df[date_col]]
    return df


_LIVE_TTL_SECONDS = 600
_live_cache: Dict[str, object] = {"ts": 0.0, "fut_3d": None, "mf_date": None}


def live_extra_factors(stock_code, as_of: Optional[str] = None,
                       max_stale_days: int = 4) -> Dict[str, Optional[float]]:
    """live 打分时的 v25 增量因子。只读本地 SQLite,不发网络请求。

    - main_net_rate: 最近一个 <= as_of 的资金榜全市场快照日(bucket top_n=0)中该股
      的主力净流入率;快照超过 max_stale_days 个自然日视为过期 → None。
    - fut_net_chg_3d: kv futures_rank 最近已发布日(<= as_of)的 3 日滚动净变动;
      已发布日不足 2 天或过期 → None(单日噪声不进规则)。
    市场级因子与快照日期做 10 分钟 TTL 缓存,单股查询走 PK 索引。
    """
    import datetime as dt
    import time

    out: Dict[str, Optional[float]] = {"main_net_rate": None, "fut_net_chg_3d": None}
    try:
        from data_store.connection import get_conn
    except Exception:
        return out
    today = _iso(as_of) if as_of else dt.date.today().isoformat()
    stale_limit = (dt.date.fromisoformat(today) - dt.timedelta(days=max_stale_days)).isoformat()

    now = time.time()
    if now - float(_live_cache["ts"]) > _LIVE_TTL_SECONDS or _live_cache.get("as_of") != today:
        fut_3d = None
        try:
            base = dt.date.fromisoformat(today)
            probe = [(base - dt.timedelta(days=back)).isoformat() for back in range(10)]
            known = []
            for day in sorted(probe):
                regime = _day_regime(_yyyymmdd(day))
                if regime:
                    known.append((day, regime["net_chg"]))
            if known and known[-1][0] >= stale_limit and len(known) >= 2:
                fut_3d = sum(chg for _, chg in known[-3:])
        except Exception:
            fut_3d = None
        mf_date = None
        try:
            row = get_conn().execute(
                "SELECT MAX(trade_date) FROM moneyflow_dc WHERE top_n=0 AND trade_date<=?",
                (today,),
            ).fetchone()
            if row and row[0] and str(row[0]) >= stale_limit:
                mf_date = str(row[0])
        except Exception:
            mf_date = None
        _live_cache.update(ts=now, as_of=today, fut_3d=fut_3d, mf_date=mf_date)

    out["fut_net_chg_3d"] = _live_cache["fut_3d"]
    mf_date = _live_cache["mf_date"]
    if mf_date:
        code = _code6(stock_code)
        try:
            row = get_conn().execute(
                "SELECT net_amount_rate FROM moneyflow_dc "
                "WHERE top_n=0 AND trade_date=? AND (ts_code=? OR ts_code LIKE ?) LIMIT 1",
                (mf_date, code, f"{code}.%"),
            ).fetchone()
            if row is not None:
                out["main_net_rate"] = row[0]
        except Exception:
            pass
    return out
