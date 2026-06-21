"""星轨图谱服务 —— 读结构(star_orbit_repo) + 叠加东财实时(板块涨跌/成分股)。

只依赖 :mod:`data_store.star_orbit_repo` 与一个自带的健壮东财 clist 抓取(避免 import
``webui.core`` 造成环)。本机 Clash 系统代理常掐 push2.eastmoney,故抓取「先直连绕过
代理、失败再走默认路由」交替重试(httpx ``trust_env=False`` 等价于绕过系统代理),与
仓库内其它东财抓取的「直连↔代理交替」一致。

- :func:`get_orbit_map` 读全图 + 给每个板块叠加实时涨跌(两次列表请求覆盖全部板块)。
  成分股不在此处批量拉(20+ 板块=20+ 请求,太重),改由 :func:`board_constituents`
  在用户点击板块时按需拉;用户钉选股始终随图返回。
- :func:`search_boards` 从东财真实概念+行业板块列表里按关键词选,保证用户加的是真 BK 码。
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

from data_store import star_orbit_repo as repo

_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
}
_BOARD_LIST_TTL = 120  # 板块列表(涨跌)缓存秒数
_board_cache: Dict[str, Any] = {}


def _fetch_clist(fs: str, fid: str = "f3", limit: int = 100, pn: int = 1) -> List[Dict[str, Any]]:
    """健壮抓东财 clist 单页。先绕过系统代理(trust_env=False)再走默认路由,失败返回 []。"""
    params = {"pn": str(pn), "pz": str(limit), "po": "1", "np": "1", "fltt": "2",
              "invt": "2", "fid": fid, "fs": fs,
              "fields": "f12,f14,f2,f3,f62"}
    url = _CLIST_URL + "?" + urllib.parse.urlencode(params)
    for trust_env in (False, True):  # 本机优先直连绕过 Clash;再兜底默认路由
        try:
            with httpx.Client(timeout=8, follow_redirects=True, trust_env=trust_env) as c:
                r = c.get(url, headers=_HEADERS)
                r.raise_for_status()
                diff = ((r.json() or {}).get("data") or {}).get("diff") or []
                if diff:
                    return diff
        except Exception:
            continue
    return []


_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
_TENCENT_URL = "https://qt.gtimg.cn/q="


def _digits6(code: str) -> str:
    return "".join(ch for ch in str(code) if ch.isdigit()).zfill(6)[-6:]


def _secid(code: str) -> str:
    """6 位代码 → 东财 ulist secid(``市场.代码``,沪/科创/沪B=1,深/创/北交所=0)。"""
    c = _digits6(code)
    sh = c[:2] != "92" and c[:1] in ("5", "6", "9")  # 92xxxx 北交所属市场 0,须先排除
    return f"{'1' if sh else '0'}.{c}"


def _tencent_symbol(code: str) -> str:
    c = _digits6(code)
    if c[:2] in ("92",) or c[:1] in ("4", "8"):
        return "bj" + c
    if c[:1] in ("5", "6", "9"):
        return "sh" + c
    return "sz" + c


def _quote_overlay(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """一篮子代码批量实时报价 ``{code: {price, change_pct, main_net_inflow}}``。

    Tushare/缓存兜底只有归属(代码)没有实时价,本函数把实时价叠加回去,避免成分股表
    「涨幅/主力买入」一片「—」。东财 ulist.np(全字段含 f62 主力净流入,绕代理)→ 腾讯
    qt.gtimg.cn(仅价/涨幅,本机即便 push2 全被掐也可达)兜底。失败返回 {}。
    """
    valid = [_digits6(c) for c in (codes or []) if str(c or "").strip()]
    if not valid:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    # 1) 东财 ulist.np —— 字段最全(含主力净流入),分批 ≤100
    for i in range(0, len(valid), 100):
        chunk = valid[i:i + 100]
        params = {"fltt": "2", "invt": "2", "fields": "f12,f2,f3,f62",
                  "secids": ",".join(_secid(c) for c in chunk)}
        url = _ULIST_URL + "?" + urllib.parse.urlencode(params)
        for trust_env in (False, True):
            try:
                with httpx.Client(timeout=6, follow_redirects=True, trust_env=trust_env) as c:
                    r = c.get(url, headers=_HEADERS)
                    r.raise_for_status()
                    diff = ((r.json() or {}).get("data") or {}).get("diff") or []
                    rows = diff.values() if isinstance(diff, dict) else diff
                    got = False
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        code = str(row.get("f12") or "").strip()
                        if not code:
                            continue
                        got = True
                        out[code] = {"price": _num(row.get("f2")),
                                     "change_pct": _num(row.get("f3")),
                                     "main_net_inflow": _num(row.get("f62"))}
                    if got:
                        break
            except Exception:
                continue
    # 2) 腾讯兜底 —— 仅价/涨幅(无主力净流入),仅当东财 ulist.np 全空时
    if not out:
        for i in range(0, len(valid), 60):
            chunk = valid[i:i + 60]
            url = _TENCENT_URL + ",".join(_tencent_symbol(c) for c in chunk)
            for trust_env in (False, True):
                try:
                    with httpx.Client(timeout=6, follow_redirects=True, trust_env=trust_env) as c:
                        r = c.get(url, headers=_HEADERS)
                        r.raise_for_status()
                        text = r.content.decode("gbk", errors="ignore")
                    got = False
                    for line in text.splitlines():
                        if "=" not in line:
                            continue
                        body = line.split("=", 1)[1].strip().rstrip(";").strip('"')
                        f = body.split("~")
                        if len(f) < 33 or not (f[2] or "").strip():
                            continue
                        got = True
                        out[f[2].strip()] = {"price": _num(f[3]),
                                             "change_pct": _num(f[32]),
                                             "main_net_inflow": None}
                    if got:
                        break
                except Exception:
                    continue
    # 3) 东财 ulist.np 不返回 f62、腾讯也无主力净流入 → Tushare moneyflow_dc 兜底
    #    (否则成分股表「主力买入」整列「—」)。仅补仍缺失的代码。
    missing = [c for c in valid if (out.get(c) or {}).get("main_net_inflow") is None]
    if missing:
        for code, yuan in _tushare_inflow(missing).items():
            slot = out.get(code)
            if slot is None:
                slot = {"price": None, "change_pct": None, "main_net_inflow": None}
                out[code] = slot
            slot["main_net_inflow"] = yuan
    return out


_INFLOW_TTL = 90  # 全市场主力净流入(Tushare moneyflow_dc)缓存秒数
_inflow_cache: Dict[str, Any] = {"ts": 0.0, "by_code": {}}


def _tushare_inflow_table() -> Dict[str, float]:
    """全市场最新交易日「主力净流入」表 ``{6位代码: 元}``(Tushare ``moneyflow_dc``)。

    东财 ``ulist.np`` 不返回 f62、``clist`` 又被限流时,这是个股主力净流入的最后兜底。
    **单位坑**: ``moneyflow_dc.net_amount`` 是**万元**(板块 ``moneyflow_ind_dc`` 却是元),
    故 ×1e4 归一到元,与 f62 / :func:`_money_text` 同口径。一次取全市场(≈5600 行)再本地
    过滤,避免传几百个 ts_code;TTL 缓存,抓空回退旧缓存。无 token/未安装 → {}。
    """
    now = time.time()
    cached = _inflow_cache["by_code"]
    if cached and (now - _inflow_cache["ts"]) < _INFLOW_TTL:
        return cached
    try:
        from data_store import tushare_client
        pro = tushare_client.get_pro()
    except Exception:
        return cached
    if pro is None:
        return cached
    dates: List[Optional[str]] = [None]  # 先试最近交易日,再回溯(盘前/节假日当日可能未出)
    try:
        dates = [d.replace("-", "") for d in tushare_client.recent_trade_dates(5)] or [None]
    except Exception:
        pass
    for td in dates:
        try:
            df = pro.moneyflow_dc(trade_date=td) if td else pro.moneyflow_dc()
        except Exception:
            continue
        if df is None or getattr(df, "empty", True):
            continue
        table: Dict[str, float] = {}
        for _, row in df.iterrows():
            c = str(row.get("ts_code") or "").split(".")[0].strip()
            amt = _num(row.get("net_amount"))
            if c and amt is not None:
                table[c] = round(amt * 1e4, 2)  # 万元 → 元
        if table:
            _inflow_cache.update(ts=now, by_code=table)
            return table
    return cached


def _tushare_inflow(codes: List[str]) -> Dict[str, float]:
    """从全市场主力净流入表里取指定代码 ``{6位代码: 元}``。无数据 → {}。"""
    valid = {_digits6(c) for c in (codes or []) if str(c or "").strip()}
    if not valid:
        return {}
    table = _tushare_inflow_table()
    return {c: table[c] for c in valid if c in table}


def _board_list(fs: str) -> List[Dict[str, Any]]:
    """全量板块列表(分页抓全,东财单页上限 100)。TTL 缓存,抓空回退旧缓存。"""
    cached = _board_cache.get(fs)
    if cached and (time.time() - cached["ts"]) < _BOARD_LIST_TTL:
        return cached["rows"]
    rows: List[Dict[str, Any]] = []
    for pn in range(1, 8):  # 概念~370/行业~90,8 页(800)足够覆盖
        page = _fetch_clist(fs, "f3", 100, pn=pn)
        if not page:
            break
        rows.extend(page)
        if len(page) < 100:
            break
    if rows:
        _board_cache[fs] = {"ts": time.time(), "rows": rows}
        return rows
    return cached["rows"] if cached else []


def _all_boards() -> Dict[str, Dict[str, Any]]:
    """{BK码: {name, change_pct, main_net_inflow, type}},概念(t:3)+行业(t:2)合并。

    东财 clist 高频限流(常 ``Server disconnected``)→ 整图板块涨跌/资金热点全空。clist 抓空
    时用 Tushare ``moneyflow_ind_dc`` 兜底(EOD 板块涨跌幅 + 主力净额,与 f62 同口径/元)。
    """
    out: Dict[str, Dict[str, Any]] = {}
    for fs, btype in (("m:90 t:3", "concept"), ("m:90 t:2", "industry")):
        for it in _board_list(fs):
            code = str(it.get("f12") or "").strip().upper()
            if not code:
                continue
            out[code] = {
                "code": code,
                "name": str(it.get("f14") or "").strip(),
                "change_pct": _num(it.get("f3")),
                "main_net_inflow": _num(it.get("f62")),
                "type": btype,
            }
    if not out:  # 东财 clist 被限流 → Tushare 兜底
        out = _tushare_boards()
    return out


def _tushare_boards() -> Dict[str, Dict[str, Any]]:
    """Tushare ``moneyflow_ind_dc`` 兜底板块涨跌/主力净额 ``{BK码: {...}}``。

    东财 clist 限流时的板块级第二来源。接口单次返回多日,按最新交易日切片去重。
    无 token / 未安装 / 无数据 → 空 dict。
    """
    try:
        from data_store import tushare_client
        pro = tushare_client.get_pro()
    except Exception:
        return {}
    if pro is None:
        return {}
    try:
        df = pro.moneyflow_ind_dc(trade_date="")
    except Exception:
        return {}
    if df is None or getattr(df, "empty", True):
        return {}
    try:
        latest = df["trade_date"].max()
        df = df[df["trade_date"] == latest]
    except Exception:
        pass
    out: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        code = str(row.get("ts_code") or "").split(".")[0].strip().upper()
        if not code.startswith("BK") or code in out:
            continue
        ctype = "concept" if str(row.get("content_type") or "") == "概念" else "industry"
        out[code] = {
            "code": code,
            "name": str(row.get("name") or "").strip(),
            "change_pct": _num(row.get("pct_change")),
            "main_net_inflow": _num(row.get("net_amount")),
            "type": ctype,
        }
    return out


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _money_text(v: Optional[float]) -> str:
    """主力净流入(元)→ 带正负号的「X.X亿/X万」。None→空串。"""
    if v is None:
        return ""
    sign = "+" if v >= 0 else "-"
    a = abs(v)
    if a >= 1e8:
        return f"{sign}{a / 1e8:.2f}亿"
    if a >= 1e4:
        return f"{sign}{a / 1e4:.0f}万"
    return f"{sign}{a:.0f}"


def _signal(change_pct: Optional[float], inflow: Optional[float]) -> Dict[str, str]:
    """量价参考信号(非完整评分模型,仅当日涨跌×主力净流入的透明规则)。

    与项目已知结论一致:主力净流入为正且涨幅温和=偏多;追高(>9%)或主力流出=偏空/谨慎。
    返回 {tag: 偏多|偏空|谨慎|中性, reason}。
    """
    c = change_pct if change_pct is not None else 0.0
    f = inflow if inflow is not None else 0.0
    if c > 9:
        return {"tag": "谨慎", "reason": "涨幅过高,追高风险"}
    if f > 0 and 0 <= c <= 7:
        return {"tag": "偏多", "reason": "主力净流入且涨幅温和"}
    if f < 0 and c < 0:
        return {"tag": "偏空", "reason": "主力流出且收跌"}
    if f < 0:
        return {"tag": "偏空", "reason": "主力净流出"}
    return {"tag": "中性", "reason": "量价信号不明确"}


_HOT_TOP_N = 30  # 资金净流入市场前 N 名视为「资金热点」
_abnormal_cache: Dict[str, Any] = {"ts": 0.0, "codes": set()}
_ABNORMAL_TTL = 60


def _abnormal_codes() -> set:
    """当日盘口异动股票代码集合(东财 push2ex getAllStockChanges,看涨异动)。失败→空集。"""
    if (time.time() - _abnormal_cache["ts"]) < _ABNORMAL_TTL and _abnormal_cache["codes"]:
        return _abnormal_cache["codes"]
    codes: set = set()
    try:  # 复用 MarketIntelligenceService(不 import core,无环);该接口本机可达
        from webui.services.market_intelligence import MarketIntelligenceService
        for it in MarketIntelligenceService().fetch_eastmoney_changes(limit=200):
            c = str(it.get("code") or "").strip()
            if c:
                codes.add(c)
    except Exception:
        pass
    if codes:
        _abnormal_cache.update(ts=time.time(), codes=codes)
        return codes
    return _abnormal_cache["codes"]


def _hot_board_codes(all_boards: Dict[str, Dict[str, Any]]) -> set:
    """资金热点板块:按主力净流入降序的市场前 _HOT_TOP_N 名(且净流入>0)。"""
    ranked = sorted(
        (b for b in all_boards.values() if (b.get("main_net_inflow") or 0) > 0),
        key=lambda b: -(b.get("main_net_inflow") or 0),
    )
    return {b["code"] for b in ranked[:_HOT_TOP_N]}


def get_orbit_map(live: bool = True) -> Dict[str, Any]:
    """读全图并(可选)叠加板块实时:涨跌/主力净流入/资金热点/量价信号。"""
    repo.seed_if_empty()
    data = repo.get_map()
    live_boards = _all_boards() if live else {}
    hot = _hot_board_codes(live_boards) if live_boards else set()
    degraded = live and not live_boards
    for ring in data["rings"]:
        for b in ring["boards"]:
            code = str(b.get("board_code") or "").upper()
            lb = live_boards.get(code)
            chg = lb["change_pct"] if lb else None
            inflow = lb["main_net_inflow"] if lb else None
            b["change_pct"] = chg
            b["main_net_inflow"] = inflow
            b["main_net_inflow_text"] = _money_text(inflow)
            b["live_name"] = lb["name"] if lb else ""
            b["hot"] = code in hot
            sig = _signal(chg, inflow)
            b["signal"] = sig["tag"]
            b["signal_reason"] = sig["reason"]
            b["pinned_count"] = len(b.get("stocks") or [])
    data["live"] = live and bool(live_boards)
    data["degraded"] = degraded
    return data


def _members_to_stocks(members: List[Dict[str, Any]], abnormal: set,
                       quotes: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """把「关联关系」缓存/Tushare 成分构造成与实时同形的条目。

    若提供 ``quotes``(批量实时报价)则叠加价/涨幅/主力净额并据此出信号、按主力净流入
    重排;无 quotes 时记 None、信号中性。
    """
    quotes = quotes or {}
    stocks: List[Dict[str, Any]] = []
    for m in members or []:
        c = str(m.get("code") or "").strip()
        if not c:
            continue
        q = quotes.get(c) or {}
        chg = q.get("change_pct")
        inflow = q.get("main_net_inflow")
        sig = _signal(chg, inflow)
        stocks.append({
            "code": c,
            "name": str(m.get("name") or "").strip(),
            "price": q.get("price"),
            "change_pct": chg,
            "main_net_inflow": inflow,
            "main_net_inflow_text": _money_text(inflow),
            "abnormal": c in abnormal,
            "signal": sig["tag"],
            "signal_reason": sig["reason"],
        })
    if quotes:  # 有实时报价则按主力净流入(无则涨幅)降序,与东财实时路径同口径
        stocks.sort(key=lambda s: (
            s["main_net_inflow"] if s["main_net_inflow"] is not None else -9e18,
            s["change_pct"] if s["change_pct"] is not None else -9e18,
        ), reverse=True)
    return stocks


def _tushare_members(board_code: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Tushare 兜底拉板块成分(dc_member,EOD 无实时价)。返回 ``[{code,name}]``。

    东财 push2 被代理/限流掐断时的第二来源;板块码补 ``.DC`` 后缀对齐 Tushare。
    无 token / 未安装 / 无数据 → 空列表(调用方再回退本地缓存)。
    """
    code = str(board_code or "").strip().upper()
    if not code.startswith("BK"):
        return []
    try:
        from data_store import tushare_client
        pro = tushare_client.get_pro()
    except Exception:
        return []
    if pro is None:
        return []
    ts_code = f"{code}.DC"
    dates: List[Optional[str]] = [None]  # 先试不带日期(取最近),再回溯近几个交易日
    try:
        dates += [d.replace("-", "") for d in tushare_client.recent_trade_dates(5)]
    except Exception:
        pass
    for td in dates:
        try:
            df = pro.dc_member(ts_code=ts_code, trade_date=td) if td else pro.dc_member(ts_code=ts_code)
        except Exception:
            continue
        if df is None or getattr(df, "empty", True):
            continue
        # dc_member 不带 trade_date 会返回近 N 个交易日的成分,每只股票重复 N 次。
        # 按代码去重(保留首次出现),否则下游按主力净流入排序会把同一只票的多份副本
        # 聚到顶部(症状:成分股面板整列都是同一只股票)。
        out: List[Dict[str, Any]] = []
        seen: set = set()
        for _, row in df.iterrows():
            c = str(row.get("con_code") or "").split(".")[0].strip()
            n = str(row.get("name") or "").strip()
            if c and c not in seen:
                seen.add(c)
                out.append({"code": c, "name": n})
            if len(out) >= limit:
                break
        if out:
            return out
    return []


def board_constituents(board_code: str, name: str = "", limit: int = 30) -> Dict[str, Any]:
    """板块实时成分股(东财 fs=b:BKxxxx, 按主力净流入排序)+ 异动徽章 + 量价参考。

    取数优先级(解决东财高频限流):
      1. 东财实时 → 成功则刷新「关联关系」缓存(star_orbit_board_member)并叠加实时价;
      2. 东财空(限流/网络) → Tushare ``dc_member`` 兜底(EOD,无实时价)并刷新缓存;
      3. 仍空 → 回退本地缓存的关联关系(上次成功的成分,标记 stale + 截至时间)。

    ``limit`` 可大到 500 以「查看全部」。非 BK 码/三层全空 → degraded。
    """
    code = str(board_code or "").strip().upper()
    if not code.startswith("BK"):
        return {"board": {"code": code, "name": name}, "stocks": [], "count": 0,
                "degraded": True, "stale": False, "source": "",
                "note": "该板块非东财来源,暂无实时成分股。"}

    abnormal = _abnormal_codes()

    # 1) 东财实时(含盘口价/涨幅/主力净额)
    stocks: List[Dict[str, Any]] = []
    for it in _fetch_clist(f"b:{code}", "f62", limit):
        c = str(it.get("f12") or "").strip()
        if not c:
            continue
        chg = _num(it.get("f3"))
        inflow = _num(it.get("f62"))
        sig = _signal(chg, inflow)
        stocks.append({
            "code": c,
            "name": str(it.get("f14") or "").strip(),
            "price": _num(it.get("f2")),
            "change_pct": chg,
            "main_net_inflow": inflow,
            "main_net_inflow_text": _money_text(inflow),
            "abnormal": c in abnormal,
            "signal": sig["tag"],
            "signal_reason": sig["reason"],
        })
    if stocks:
        try:  # 刷新关联关系缓存(只存归属,实时价不入库)
            repo.save_board_members(code, stocks, source="eastmoney")
        except Exception:
            pass
        return {"board": {"code": code, "name": name}, "stocks": stocks,
                "count": len(stocks), "degraded": False, "stale": False,
                "source": "eastmoney", "note": ""}

    # 2) Tushare 兜底(归属)+ 实时报价叠加(ulist.np→腾讯),成功则刷新缓存
    tu = _tushare_members(code, limit=max(limit, 500))
    if tu:
        try:
            repo.save_board_members(code, tu, source="tushare")
        except Exception:
            pass
        quotes = _quote_overlay([m["code"] for m in tu])
        stocks = _members_to_stocks(tu, abnormal, quotes)[:limit]
        note = ("东财成分股接口限流,已用 Tushare 关联成分 + 实时报价叠加。" if quotes
                else "东财实时暂不可用(网络/限流),已用 Tushare 成分股(收盘数据,无实时价)兜底。")
        return {"board": {"code": code, "name": name}, "stocks": stocks,
                "count": len(stocks), "degraded": False, "stale": not quotes,
                "source": "tushare", "quoted": bool(quotes), "note": note}

    # 3) 本地关联关系缓存(上次成功的成分)+ 实时报价叠加
    cached = repo.get_board_members(code, limit=max(limit, 500))
    if cached["members"]:
        quotes = _quote_overlay([m["code"] for m in cached["members"]])
        stocks = _members_to_stocks(cached["members"], abnormal, quotes)[:limit]
        as_of = cached.get("updated_at") or ""
        note = ("东财成分股接口限流,已用缓存的关联成分 + 实时报价叠加。" if quotes
                else f"东财实时暂不可用(网络/限流),已显示缓存的关联成分（截至 {as_of}），无实时价。")
        return {"board": {"code": code, "name": name}, "stocks": stocks,
                "count": len(stocks), "degraded": False, "stale": not quotes,
                "source": cached.get("source") or "cache", "quoted": bool(quotes),
                "as_of": as_of, "note": note}

    return {"board": {"code": code, "name": name}, "stocks": [], "count": 0,
            "degraded": True, "stale": False, "source": "", "quoted": False,
            "note": "东财成分股暂不可用(网络/限流)且无缓存,请稍后重试。"}


def search_boards(keyword: str, limit: int = 30) -> List[Dict[str, Any]]:
    """按关键词搜东财真实概念+行业板块,供「添加板块」选择(保证 BK 码真实)。"""
    kw = str(keyword or "").strip().upper()
    rows = list(_all_boards().values())
    if kw:
        rows = [r for r in rows if kw in r["name"].upper() or kw in r["code"]]
    rows.sort(key=lambda r: -(r["change_pct"] if r["change_pct"] is not None else -999))
    return rows[:limit]
