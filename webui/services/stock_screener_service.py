"""条件选股(Stock Screener)服务 —— 组合既有数据接口做全市场筛选,输出命中列表。

零新抓取原则:全部维度复用项目既有数据面——
- 行情基座: 大盘云图全市场快照(路由注入 ``market_rows_fn`` → webui.core._market_cloud_payload,
  覆盖度择优 东财/Tushare/新浪,~5500只);为空时回退本地 moneyflow_dc 最新日全市场行。
- 资金: 本地 ``moneyflow_dc``(主力净流入/净流入率/连续净流入天数,哨兵 top_n=0 全市场)。
- 盘口异动/量化活跃: 本地 ``quant_radar_stock_daily`` 最新交易日(活跃度/方向/异动笔数)。
- 吸筹: :func:`quant_radar_service.accumulation_payload`(kv 快照+TTL,窗口 20/40/60)。
- 龙虎榜: 本地 ``dragon_tiger_list``(近N日上榜聚合) + ``dragon_tiger_inst`` 量化席位。
- 机会分: 本地 ``opportunity_run/item`` 最新一次挖掘评分。
- 技术形态: 路由注入 ``kline_fetcher``(STOCK_KLINE_SERVICE,60s TTL);候选 ≤ TECH_CAP
  才评估(全市场逐股拉日K不可行),超出按当前排序截前 TECH_CAP 只并在 notes 说明。

条件全部可选,激活的维度之间 AND;缺数据的股票在激活维度上按「不命中」处理,
维度级缺数据(整表空)记入 notes。所有条件评估为纯函数,数据源可注入离线单测。
"""
from __future__ import annotations

import datetime as _dt
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional

TECH_CAP = 300          # 技术/量化模型条件最多评估的候选数(逐股日K成本约束)
FLOW_STREAK_WINDOW = 10  # 连续净流入天数的回看窗口(交易日)

SORT_KEYS = {"main_net_wan", "change_pct", "activity", "accum_score", "opp_score",
             "dragon_net_wan", "turnover", "quant_buy", "rsi"}

BOARD_PREFIX = {
    "main": ("60", "00"),      # 沪深主板
    "chinext": ("30",),        # 创业板
    "star": ("688", "689"),    # 科创板
    "bse": ("4", "8"),         # 北交所
}
_LIMIT_UP_PCT = {"chinext": 19.8, "star": 19.8, "bse": 29.8, "main": 9.8}


def _num(v: Any, ndigits: int = 2) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return round(float(v), ndigits)
    except (TypeError, ValueError):
        return None


def _code6(value: Any) -> str:
    """'600000.SH'/'sh600000'/'600000' → 6位代码;非法 → ''。"""
    s = str(value or "").strip()
    if "." in s:
        s = s.split(".")[0]
    s = s.lstrip("shzbj").lstrip("SHZBJ") if not s[:1].isdigit() else s
    return s if len(s) == 6 and s.isdigit() else ""


def _board_of(code: str) -> str:
    for board, prefixes in BOARD_PREFIX.items():
        if any(code.startswith(p) for p in prefixes):
            return board
    return "main"


def _active(cond: Any) -> bool:
    """维度条件是否激活:dict 且至少一个非空/非False值。"""
    if not isinstance(cond, dict):
        return False
    return any(v not in (None, "", False, []) for v in cond.values())


# ----------------------------- 默认数据源(全部可注入) -----------------------------

def _default_flow_window(days: int) -> List[Dict[str, Any]]:
    """moneyflow_dc 近N交易日全市场行(升序)。失败 → []。"""
    try:
        from data_store import moneyflow_repo

        end = moneyflow_repo.latest_date(top_n=0)
        if not end:
            return []
        df = moneyflow_repo.get_market_window(str(end), days, snapshot_top_n=0)
        if df is None or df.empty:
            return []
        return df.to_dict("records")
    except Exception:
        return []


def _default_radar_rows() -> List[Dict[str, Any]]:
    """quant_radar_stock_daily 最新交易日全量行。失败 → []。"""
    try:
        from data_store import quant_radar_repo

        dates = quant_radar_repo.list_dates(limit=1)
        return quant_radar_repo.get_day(dates[0], limit=0) if dates else []
    except Exception:
        return []


def _default_accum(window: int) -> Dict[str, Any]:
    try:
        from webui.services import quant_radar_service

        return quant_radar_service.accumulation_payload(window=window) or {}
    except Exception:
        return {}


def _default_dragon(days: int) -> List[Dict[str, Any]]:
    """dragon_tiger_list 近N日按股聚合(净买额/上榜次数)。失败 → []。"""
    try:
        from data_store import dragon_tiger_list_repo as repo

        end = repo.latest_date()
        if not end:
            return []
        df = repo.get_aggregated(str(end), days, top_n=2000)
        if df is None or df.empty:
            return []
        return df.to_dict("records")
    except Exception:
        return []


def _default_quant_seats(days: int) -> Dict[str, bool]:
    """近N日出现过量化席位的股票集合。失败 → {}。"""
    try:
        from data_store import dragon_tiger_repo

        end = _dt.date.today()
        start = end - _dt.timedelta(days=max(days, 1) * 2 + 3)
        df = dragon_tiger_repo.get_quant_by_date(start.isoformat(), end.isoformat())
        if df is None or df.empty:
            return {}
        out: Dict[str, bool] = {}
        for ts_code in df.get("ts_code", []):
            code = _code6(ts_code)
            if code:
                out[code] = True
        return out
    except Exception:
        return {}


def _default_opportunity() -> Dict[str, Any]:
    """最新一次机会挖掘 run 的 {code: {score, tier}} + run 日期。失败 → {}。"""
    try:
        from data_store import opportunity_repo

        run = opportunity_repo.latest_run()
        if not run:
            return {}
        items = opportunity_repo.items_for_run(run.get("id"))
        by_code: Dict[str, Dict[str, Any]] = {}
        for it in items or []:
            code = _code6(it.get("stock_code") or it.get("code"))
            if not code:
                continue
            by_code[code] = {"score": _num(it.get("total_score") if it.get("total_score") is not None
                                           else it.get("score")),
                             "tier": str(it.get("rating") or it.get("tier") or "")}
        return {"date": str(run.get("run_date") or run.get("run_at") or ""), "by_code": by_code}
    except Exception:
        return {}


# ----------------------------- 纯函数:维度地图构建 -----------------------------

def build_flow_map(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """moneyflow 窗口行(升序) → {code: {main_net_wan, net_rate, streak, streak_out, date}}。

    streak/streak_out = 以最新日为端点的连续净流入/净流出天数;amount_unit 万元。
    """
    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows or []:
        code = _code6(r.get("ts_code") or r.get("code"))
        if code:
            by_code.setdefault(code, []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for code, items in by_code.items():
        items.sort(key=lambda r: str(r.get("trade_date")))
        last = items[-1]
        streak = streak_out = 0
        for r in reversed(items):
            net = _num(r.get("net_amount"))
            if net is not None and net > 0 and streak_out == 0:
                streak += 1
            elif net is not None and net < 0 and streak == 0:
                streak_out += 1
            else:
                break
        out[code] = {
            "main_net_wan": _num(last.get("net_amount")),
            "net_rate": _num(last.get("net_amount_rate")),
            "streak": streak,
            "streak_out": streak_out,
            "date": str(last.get("trade_date") or ""),
            "name": str(last.get("name") or ""),
            "close": _num(last.get("close")),
            "change_pct": _num(last.get("pct_change")),
        }
    return out


def build_radar_map(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        code = _code6(r.get("code"))
        if not code:
            continue
        out[code] = {
            "activity": _num(r.get("activity"), 0),
            "level": str(r.get("level") or ""),
            "direction": str(r.get("direction") or ""),
            "changes_total": int(r.get("changes_total") or 0),
            "industry": str(r.get("industry") or ""),
            "date": str(r.get("trade_date") or ""),
        }
    return out


def build_accum_map(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for s in (payload or {}).get("stocks") or []:
        code = _code6(s.get("code"))
        if not code:
            continue
        out[code] = {
            "score": _num(s.get("score"), 1),
            "qualified": bool(s.get("qualified", True)),
            "accum_days": int(s.get("accum_days") or 0),
            "total_net_wan": _num(s.get("total_net_wan")),
        }
    return out


def build_dragon_map(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows or []:
        code = _code6(r.get("ts_code") or r.get("code"))
        if not code:
            continue
        net = _num(r.get("net_amount"))
        out[code] = {
            # dragon_tiger_list net_amount 单位为元(实证 App 库) → 万元
            "net_wan": round(net / 1e4, 2) if net is not None else None,
            "days": int(r.get("list_count") or r.get("days") or 0) or 1,
        }
    return out


# ----------------------------- 纯函数:技术条件 -----------------------------

def tech_features(bars: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """日K(≥21根升序) → 均线/新高/量比 + RSI/MACD金叉/KDJ金叉(机会挖掘同源指标)。

    指标计算复用 :mod:`analysis.technical_analysis`;金叉口径=最近3根内上穿。
    不足 21 根 → None;指标子集失败单独置 None(条件按不命中)。
    """
    rows = sorted((b for b in bars or [] if _num(b.get("close")) is not None),
                  key=lambda b: str(b.get("date")))
    if len(rows) < 21:
        return None
    closes = [float(b["close"]) for b in rows]
    vols = [float(b.get("volume") or 0.0) for b in rows]

    def ma(n: int) -> float:
        return sum(closes[-n:]) / n

    last = closes[-1]
    vol_ratio = None
    if len(vols) >= 6 and vols[-1] > 0:
        base = sum(vols[-6:-1]) / 5
        vol_ratio = round(vols[-1] / base, 2) if base > 0 else None
    rsi_val = macd_golden = kdj_golden = None
    try:
        import pandas as pd

        from analysis.technical_analysis import TechnicalAnalysis as TA

        close_s = pd.Series(closes, dtype=float)
        rsi_s = TA.calculate_rsi(close_s)
        if len(rsi_s) and pd.notna(rsi_s.iloc[-1]):
            rsi_val = round(float(rsi_s.iloc[-1]), 1)

        def _golden(diff_s) -> Optional[bool]:
            d = diff_s.dropna()
            if len(d) < 4:
                return None
            return bool(d.iloc[-1] > 0 and (d.iloc[-4:-1] <= 0).any())

        macd_line, signal_line, _hist = TA.calculate_macd(close_s)
        macd_golden = _golden(macd_line - signal_line)
        high_s = pd.Series([float(b.get("high") or b["close"]) for b in rows], dtype=float)
        low_s = pd.Series([float(b.get("low") or b["close"]) for b in rows], dtype=float)
        k, d, _j = TA.calculate_kdj(high_s, low_s, close_s)
        kdj_golden = _golden(k - d)
    except Exception:
        pass
    return {
        "above_ma20": last >= ma(20),
        "ma_bull": ma(5) > ma(10) > ma(20),
        "new_high_20": last >= max(closes[-20:]),  # 收盘创20日收盘新高
        "vol_ratio": vol_ratio,
        "rsi": rsi_val,
        "macd_golden": macd_golden,
        "kdj_golden": kdj_golden,
    }


def _quant_signals(bars: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    """30量化模型末根K多空票数(机会挖掘同源 count_quant_signals)。数据不足/失败 → None。"""
    rows = sorted((b for b in bars or [] if _num(b.get("close")) is not None),
                  key=lambda b: str(b.get("date")))
    if len(rows) < 30:
        return None
    try:
        import pandas as pd

        from analysis.stock_analysis_suite import count_quant_signals

        df = pd.DataFrame([{
            "open": float(b.get("open") or b["close"]),
            "high": float(b.get("high") or b["close"]),
            "low": float(b.get("low") or b["close"]),
            "close": float(b["close"]),
            "volume": float(b.get("volume") or 0.0),
        } for b in rows])
        out = count_quant_signals(df) or {}
        return {"buy": int(out.get("buy_signal_count") or 0),
                "sell": int(out.get("sell_signal_count") or 0)}
    except Exception:
        return None


def _tech_pass(feat: Optional[Dict[str, Any]], cond: Dict[str, Any]) -> (bool, List[str]):
    if feat is None:
        return False, []
    hits: List[str] = []
    if cond.get("above_ma20"):
        if not feat["above_ma20"]:
            return False, []
        hits.append("站上MA20")
    if cond.get("ma_bull"):
        if not feat["ma_bull"]:
            return False, []
        hits.append("均线多头")
    if cond.get("new_high_20"):
        if not feat["new_high_20"]:
            return False, []
        hits.append("创20日新高")
    vr_min = _num(cond.get("vol_ratio_min"))
    if vr_min is not None:
        if feat["vol_ratio"] is None or feat["vol_ratio"] < vr_min:
            return False, []
        hits.append(f"量能放大{feat['vol_ratio']}x")
    rsi_min, rsi_max = _num(cond.get("rsi_min")), _num(cond.get("rsi_max"))
    if rsi_min is not None and (feat.get("rsi") is None or feat["rsi"] < rsi_min):
        return False, []
    if rsi_max is not None and (feat.get("rsi") is None or feat["rsi"] > rsi_max):
        return False, []
    if (rsi_min is not None or rsi_max is not None) and feat.get("rsi") is not None:
        hits.append(f"RSI {feat['rsi']}")
    if cond.get("macd_golden"):
        if not feat.get("macd_golden"):
            return False, []
        hits.append("MACD金叉")
    if cond.get("kdj_golden"):
        if not feat.get("kdj_golden"):
            return False, []
        hits.append("KDJ金叉")
    return True, hits


# ----------------------------- 主入口 -----------------------------

def screen(conditions: Optional[Dict[str, Any]] = None,
           market_rows_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
           flow_window_fn: Optional[Callable[[int], List[Dict[str, Any]]]] = None,
           radar_rows_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
           accum_fn: Optional[Callable[[int], Dict[str, Any]]] = None,
           dragon_fn: Optional[Callable[[int], List[Dict[str, Any]]]] = None,
           quant_seats_fn: Optional[Callable[[int], Dict[str, bool]]] = None,
           opportunity_fn: Optional[Callable[[], Dict[str, Any]]] = None,
           kline_fetcher: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
           ) -> Dict[str, Any]:
    """按条件选股:激活维度 AND 过滤,返回命中列表 + 数据新鲜度 meta。"""
    cond = conditions or {}
    notes: List[str] = []
    applied: List[str] = []
    dates: Dict[str, str] = {}

    # ---------- 基座:全市场行情 ----------
    market_rows = (market_rows_fn or (lambda: []))() or []
    flow_rows = (flow_window_fn or _default_flow_window)(FLOW_STREAK_WINDOW)
    flow_map = build_flow_map(flow_rows)
    if flow_map:
        dates["flow"] = next(iter(flow_map.values()))["date"]
    base: Dict[str, Dict[str, Any]] = {}
    for r in market_rows:
        code = _code6(r.get("code") or r.get("ts_code"))
        if not code:
            continue
        base[code] = {
            "code": code,
            "name": str(r.get("name") or ""),
            "price": _num(r.get("price") or r.get("close")),
            "change_pct": _num(r.get("change_pct") or r.get("pct_change")),
            "turnover": _num(r.get("turnover_rate") or r.get("turnover")),
            "industry": str(r.get("industry") or ""),
        }
    if not base and flow_map:  # 云图不可用:退化用资金流最新日做基座
        notes.append("行情快照不可用,基座退化为资金流覆盖股票(约5000只)")
        for code, f in flow_map.items():
            base[code] = {"code": code, "name": f.get("name") or "",
                          "price": f.get("close"), "change_pct": f.get("change_pct"),
                          "turnover": None, "industry": ""}
    if not base:
        return {"ok": False, "error": "无可用行情/资金流数据,无法选股",
                "stocks": [], "meta": {"notes": notes}}
    if not flow_map:
        notes.append("本地资金流数据为空,资金维度不可用(可先打开资金榜单页回补)")

    radar_rows = (radar_rows_fn or _default_radar_rows)()
    radar_map = build_radar_map(radar_rows)
    if radar_map:
        dates["radar"] = next(iter(radar_map.values()))["date"]
    elif _active(cond.get("radar")):
        notes.append("量化雷达按日数据为空,盘口异动维度按不命中处理(可先打开量化雷达页)")

    # ---------- 逐维过滤 ----------
    survivors: List[str] = list(base)

    mkt = cond.get("market") or {}
    if _active(mkt):
        applied.append("market")
        boards = [b for b in (mkt.get("boards") or []) if b in BOARD_PREFIX]
        pct_min, pct_max = _num(mkt.get("pct_min")), _num(mkt.get("pct_max"))
        price_min, price_max = _num(mkt.get("price_min")), _num(mkt.get("price_max"))
        turnover_min = _num(mkt.get("turnover_min"))
        kept = []
        for code in survivors:
            row = base[code]
            pct, price = row["change_pct"], row["price"]
            if boards and _board_of(code) not in boards:
                continue
            if mkt.get("exclude_st") and "ST" in row["name"].upper():
                continue
            if pct_min is not None and (pct is None or pct < pct_min):
                continue
            if pct_max is not None and (pct is None or pct > pct_max):
                continue
            if price_min is not None and (price is None or price < price_min):
                continue
            if price_max is not None and (price is None or price > price_max):
                continue
            if turnover_min is not None and (row["turnover"] is None
                                             or row["turnover"] < turnover_min):
                continue
            if mkt.get("exclude_limit_up") and pct is not None \
                    and pct >= _LIMIT_UP_PCT[_board_of(code)]:
                continue
            kept.append(code)
        survivors = kept

    flow_cond = cond.get("flow") or {}
    if _active(flow_cond):
        applied.append("flow")
        main_min = _num(flow_cond.get("main_net_min"))
        rate_min = _num(flow_cond.get("net_rate_min"))
        streak_min = int(_num(flow_cond.get("streak_days")) or 0)
        kept = []
        for code in survivors:
            f = flow_map.get(code)
            if not f:
                continue
            if main_min is not None and (f["main_net_wan"] is None
                                         or f["main_net_wan"] < main_min):
                continue
            if rate_min is not None and (f["net_rate"] is None or f["net_rate"] < rate_min):
                continue
            if streak_min and f["streak"] < streak_min:
                continue
            kept.append(code)
        survivors = kept

    radar_cond = cond.get("radar") or {}
    if _active(radar_cond):
        applied.append("radar")
        act_min = _num(radar_cond.get("activity_min"))
        chg_min = int(_num(radar_cond.get("changes_min")) or 0)
        direction = str(radar_cond.get("direction") or "")
        kept = []
        for code in survivors:
            q = radar_map.get(code)
            if not q:
                continue
            if act_min is not None and (q["activity"] or 0) < act_min:
                continue
            if chg_min and q["changes_total"] < chg_min:
                continue
            if direction == "排除砸盘":
                if q["direction"] == "砸盘":
                    continue
            elif direction and q["direction"] != direction:
                continue
            kept.append(code)
        survivors = kept

    accum_cond = cond.get("accum") or {}
    accum_map: Dict[str, Dict[str, Any]] = {}
    if _active(accum_cond):
        applied.append("accum")
        window = int(_num(accum_cond.get("window")) or 40)
        payload = (accum_fn or _default_accum)(window)
        accum_map = build_accum_map(payload)
        if payload.get("data_date"):
            dates["accum"] = str(payload.get("data_date"))
        if not accum_map:
            notes.append("吸筹榜数据为空,吸筹维度全部不命中(本地资金流历史不足)")
        score_min = _num(accum_cond.get("score_min"))
        kept = []
        for code in survivors:
            a = accum_map.get(code)
            if not a:
                continue
            if accum_cond.get("qualified_only") and not a["qualified"]:
                continue
            if score_min is not None and (a["score"] is None or a["score"] < score_min):
                continue
            kept.append(code)
        survivors = kept

    dragon_cond = cond.get("dragon") or {}
    dragon_map: Dict[str, Dict[str, Any]] = {}
    seats_map: Dict[str, bool] = {}
    if _active(dragon_cond):
        applied.append("dragon")
        days = int(_num(dragon_cond.get("days")) or 5)
        dragon_map = build_dragon_map((dragon_fn or _default_dragon)(days))
        if dragon_cond.get("quant_seat"):
            seats_map = (quant_seats_fn or _default_quant_seats)(days)
        if not dragon_map:
            notes.append("龙虎榜数据为空,龙虎榜维度全部不命中(可先在资金榜单页回补)")
        net_min = _num(dragon_cond.get("net_min_wan"))
        kept = []
        for code in survivors:
            d = dragon_map.get(code)
            if not d:
                continue
            if net_min is not None and (d["net_wan"] is None or d["net_wan"] < net_min):
                continue
            if dragon_cond.get("quant_seat") and not seats_map.get(code):
                continue
            kept.append(code)
        survivors = kept

    opp_cond = cond.get("opportunity") or {}
    opp: Dict[str, Any] = {}
    if _active(opp_cond):
        applied.append("opportunity")
        opp = (opportunity_fn or _default_opportunity)() or {}
        by_code = opp.get("by_code") or {}
        if opp.get("date"):
            dates["opportunity"] = opp["date"]
        if not by_code:
            notes.append("本地无机会挖掘结果,机会分维度全部不命中(先在工作台跑一次挖掘)")
        score_min = _num(opp_cond.get("score_min"))
        kept = []
        for code in survivors:
            o = by_code.get(code)
            if not o:
                continue
            if score_min is not None and (o["score"] is None or o["score"] < score_min):
                continue
            kept.append(code)
        survivors = kept

    # ---------- 技术条件 + 量化模型信号(共用日K,候选封顶) ----------
    tech_cond = cond.get("tech") or {}
    quant_cond = cond.get("quant") or {}
    tech_active, quant_active = _active(tech_cond), _active(quant_cond)
    tech_map: Dict[str, Dict[str, Any]] = {}
    quant_map: Dict[str, Dict[str, int]] = {}
    if tech_active or quant_active:
        applied.extend([d for d, a in (("tech", tech_active), ("quant", quant_active)) if a])
        if kline_fetcher is None:
            notes.append("未接入日K服务,技术/量化模型条件被跳过")
        else:
            if len(survivors) > TECH_CAP:
                survivors.sort(key=lambda c: -(flow_map.get(c, {}).get("main_net_wan") or -1e18))
                notes.append(f"技术/量化模型条件仅评估按主力净流入排序的前 {TECH_CAP} 只候选"
                             f"(原候选 {len(survivors)} 只),请先用其他条件收窄")
                survivors = survivors[:TECH_CAP]

            def _one(code: str):
                try:
                    bars = kline_fetcher(code, 120) or []
                except Exception:
                    return code, None, None
                return (code,
                        tech_features(bars) if tech_active else None,
                        _quant_signals(bars) if quant_active else None)

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(_one, survivors))
            kept = []
            for code, feat, qs in results:
                hits: List[str] = []
                if tech_active:
                    ok, hits = _tech_pass(feat, tech_cond)
                    if not ok:
                        continue
                if quant_active:
                    if qs is None:
                        continue
                    buy_min = int(_num(quant_cond.get("buy_min")) or 0)
                    sell_max = _num(quant_cond.get("sell_max"))
                    if buy_min and qs["buy"] < buy_min:
                        continue
                    if sell_max is not None and qs["sell"] > sell_max:
                        continue
                    quant_map[code] = qs
                    hits.append(f"量化买入{qs['buy']}票")
                    if qs["sell"] == 0:
                        hits.append("无卖出信号")
                tech_map[code] = {"hits": hits, **(feat or {})}
                kept.append(code)
            survivors = kept

    # ---------- 组装结果 ----------
    stocks: List[Dict[str, Any]] = []
    for code in survivors:
        row = base[code]
        f = flow_map.get(code) or {}
        q = radar_map.get(code) or {}
        a = accum_map.get(code) or {}
        d = dragon_map.get(code) or {}
        o = (opp.get("by_code") or {}).get(code) or {}
        hits: List[str] = []
        if "flow" in applied:
            if f.get("main_net_wan") is not None:
                hits.append(f"主力净流入{f['main_net_wan']:.0f}万")
            if f.get("streak"):
                hits.append(f"连续净流入{f['streak']}日")
        if "radar" in applied and q:
            hits.append(f"量化活跃{q['activity']:.0f}" + (f"·{q['direction']}" if q.get("direction") else ""))
        if "accum" in applied and a:
            hits.append(f"吸筹{a['accum_days']}天" + (f"·评分{a['score']:.0f}" if a.get("score") is not None else ""))
        if "dragon" in applied and d:
            hits.append(f"龙虎榜净买{d['net_wan']:.0f}万" if d.get("net_wan") is not None else "近5日上榜")
            if seats_map.get(code):
                hits.append("量化席位")
        if "opportunity" in applied and o:
            hits.append(f"机会分{o['score']:.0f}" + (f"·{o['tier']}" if o.get("tier") else ""))
        hits.extend((tech_map.get(code) or {}).get("hits") or [])
        stocks.append({
            "code": code,
            "name": row["name"] or f.get("name") or "",
            "industry": row["industry"] or q.get("industry") or "",
            "price": row["price"],
            "change_pct": row["change_pct"],
            "turnover": row["turnover"],
            "main_net_wan": f.get("main_net_wan"),
            "net_rate": f.get("net_rate"),
            "streak": f.get("streak") or 0,
            "activity": q.get("activity"),
            "direction": q.get("direction") or "",
            "changes_total": q.get("changes_total") or 0,
            "accum_score": a.get("score"),
            "accum_days": a.get("accum_days"),
            "accum_total_wan": a.get("total_net_wan"),
            "dragon_net_wan": d.get("net_wan"),
            "quant_seat": bool(seats_map.get(code)),
            "opp_score": o.get("score"),
            "opp_tier": o.get("tier") or "",
            "vol_ratio": (tech_map.get(code) or {}).get("vol_ratio"),
            "rsi": (tech_map.get(code) or {}).get("rsi"),
            "quant_buy": (quant_map.get(code) or {}).get("buy"),
            "quant_sell": (quant_map.get(code) or {}).get("sell"),
            "hits": hits,
        })

    sort_key = str(cond.get("sort") or "main_net_wan")
    if sort_key not in SORT_KEYS:
        sort_key = "main_net_wan"
    stocks.sort(key=lambda s: -(s.get(sort_key) if isinstance(s.get(sort_key), (int, float)) else -1e18))
    total = len(stocks)
    limit = int(_num(cond.get("limit")) or 0)  # 0/缺省 = 全量返回(前端分页展示)
    if limit > 0:
        stocks = stocks[:limit]

    return {
        "ok": True,
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "applied": applied,
        "base_count": len(base),
        "total_matched": total,
        "returned": len(stocks),
        "stocks": stocks,
        "dates": dates,
        "notes": notes,
        "disclaimer": "选股结果为公开数据规则筛选,不构成投资建议;涨跌幅/资金口径以各源最新可得交易日为准。",
    }


def watchlist_alerts(items: List[Dict[str, Any]],
                     kline_fetcher: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None,
                     flow_window_fn: Optional[Callable[[int], List[Dict[str, Any]]]] = None,
                     radar_rows_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
                     accum_fn: Optional[Callable[[int], Dict[str, Any]]] = None,
                     quant_seats_fn: Optional[Callable[[int], Dict[str, bool]]] = None,
                     ) -> Dict[str, Any]:
    """自选股智能提醒:逐股跑 :mod:`analysis.watchlist_alerts` 规则(超跌反弹/超买/超卖/
    量化介入/主力出逃/收割预警/放量异动),复用条件选股同一批本地数据面。

    ``items`` = WATCHLIST_SERVICE.list_items()(或任意 [{code,name}]);自选一般 ≤60 只,
    日K 逐股拉取走 STOCK_KLINE_SERVICE 60s TTL,8 线程并行。
    """
    from analysis import watchlist_alerts as _wa

    flow_map = build_flow_map((flow_window_fn or _default_flow_window)(FLOW_STREAK_WINDOW))
    radar_map = build_radar_map((radar_rows_fn or _default_radar_rows)())
    accum_map = build_accum_map((accum_fn or _default_accum)(40))
    seats_map = (quant_seats_fn or _default_quant_seats)(10)
    norm = [{"code": _code6(it.get("code")), "name": str(it.get("name") or "")}
            for it in items or []]
    norm = [it for it in norm if it["code"]]

    def _one(it: Dict[str, str]) -> Dict[str, Any]:
        code = it["code"]
        bars: List[Dict[str, Any]] = []
        if kline_fetcher is not None:
            try:
                bars = kline_fetcher(code, 60) or []
            except Exception:
                bars = []
        alerts = _wa.detect(bars=bars, flow=flow_map.get(code), radar=radar_map.get(code),
                            accum=accum_map.get(code), quant_seat=bool(seats_map.get(code)))
        return {"code": code, "name": it["name"] or (flow_map.get(code) or {}).get("name") or code,
                "alerts": alerts}

    if norm:
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(_one, norm))
    else:
        rows = []
    flow_date = next(iter(flow_map.values()))["date"] if flow_map else ""
    radar_date = next(iter(radar_map.values()))["date"] if radar_map else ""
    return {
        "ok": True,
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "items": rows,
        "alert_count": sum(len(r["alerts"]) for r in rows),
        "checked": len(rows),
        "dates": {"flow": flow_date, "radar": radar_date},
        "notes": ([] if flow_map else ["本地资金流数据为空,主力出逃/进场提醒不可用"])
                 + ([] if radar_map else ["量化雷达按日数据为空,量化介入/收割预警提醒不可用"]),
        "disclaimer": "提醒为公开数据启发式信号,「疑似」口径,不构成投资建议。",
    }


def meta() -> Dict[str, Any]:
    """各维度数据新鲜度(日期+覆盖行数),供选股页顶部展示与条件可用性提示。"""
    out: Dict[str, Any] = {"ok": True, "dims": {}}
    try:
        from data_store import moneyflow_repo

        d = moneyflow_repo.latest_date(top_n=0)
        rows = 0
        if d:
            df = moneyflow_repo.get_ranking(str(d), limit=100000, snapshot_top_n=0)
            rows = 0 if df is None or getattr(df, "empty", True) else int(len(df))
        out["dims"]["flow"] = {"date": str(d or ""), "rows": rows}
    except Exception:
        out["dims"]["flow"] = {"date": "", "rows": 0}
    try:
        from data_store import quant_radar_repo

        dates = quant_radar_repo.list_dates(limit=1)
        out["dims"]["radar"] = {"date": dates[0] if dates else "",
                                "rows": len(quant_radar_repo.get_day(dates[0], limit=0)) if dates else 0}
    except Exception:
        out["dims"]["radar"] = {"date": "", "rows": 0}
    try:
        from data_store import dragon_tiger_list_repo as dtl

        d = dtl.latest_date()
        out["dims"]["dragon"] = {"date": str(d or ""), "rows": int(dtl.count() or 0)}
    except Exception:
        out["dims"]["dragon"] = {"date": "", "rows": 0}
    opp = _default_opportunity()
    out["dims"]["opportunity"] = {"date": str(opp.get("date") or ""),
                                  "rows": len(opp.get("by_code") or {})}
    return out
