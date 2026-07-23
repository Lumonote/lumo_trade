# 资金榜单「无量化」过滤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 资金榜单页 4 处列表(主榜 moneyflow/龙虎榜、5日/30日窗口榜、吸筹埋伏榜)增加「无量化」过滤:后端各接口加 `no_quant=1` 参数,服务端剔除『量化资金参与』股票(量化雷达活跃度≥50 或 近5日龙虎榜量化席位,两源并集)。

**Architecture:** `quant_radar_service.quant_active_codes()`(5分钟TTL,纯本地SQLite)提供量化代码集;`capital_rankings_service` 在 `_envelope`/`_window_rankings` 中过滤(no_quant 时取数 over-fetch ×3 再截回 top_n);`accumulation_payload` 三个 return 路径统一过 `_apply_no_quant`(kv 快照与内存缓存仍存全量)。前端 desktop.html 加两个 checkbox,压缩 JS 尾部追加 IIFE 包装 `capitalParams`/`fetchJson`。

**Tech Stack:** Python (Robyn web框架) + SQLite (data_store repos) + pytest + 压缩版原生 JS (esbuild产物,尾部追加模式)。

**Spec:** `docs/superpowers/specs/2026-07-22-capital-rankings-no-quant-filter-design.md`

## Global Constraints

- **绝不执行任何 git 写操作**(commit/add/push 等)——用户自管 git。计划里没有 commit 步骤,写完文件即停。
- 所有数据读本地 SQLite,不新增网络抓取,不新增表。
- 中文界面文案;「无量化」勾选默认关闭,不持久化。
- 测试命令用 `.venv/bin/python -m pytest`(无 .venv 则 `python3 -m pytest`)。本机是 Intel Mac 无 torch,相关测试与本功能无关。
- robyn TestClient 查询串必须走 `query_params=`,不能拼 `?a=b`(路由匹配按纯路径)。
- 压缩 JS 尾部追加必须以 `;` 开头(防与压缩尾表达式粘连静默 TypeError);不要用 `innerHTML +=` 动已绑监听的容器。
- 打包 App 需重打包才生效(.py 与压缩 JS 双端改动)——完成后提示用户即可,不在本计划内。

---

### Task 1: 量化代码集 resolver `quant_active_codes()`

**Files:**
- Modify: `webui/services/quant_radar_service.py`(模块级缓存区约 L38-41 附近加缓存变量;函数放在 `_quant_seats_window` 之后,约 L684 后)
- Test: `tests/test_quant_active_codes.py`(新建)

**Interfaces:**
- Consumes: 既有 `quant_radar_service._quant_seats_window(days: int) -> Dict[str, List[dict]]`(键=6位代码);既有 `data_store.quant_radar_repo.list_dates(limit) -> List[str]`(ISO日期,最新在前)、`get_day(trade_date, limit=0, min_activity=50) -> List[dict]`(`limit<=0` 全量,item 含 `code`)。**不新增 repo 函数**(spec 原写新增 `codes_with_activity`,实施时发现 `get_day` 已支持 `min_activity`,复用之)。
- Produces: `quant_active_codes(force: bool = False) -> Dict[str, Any]`,形状 `{"codes": set[str 6位代码], "as_of": str|None, "available": bool}`。`available` = 任一数据源有数据(活跃度按日表有日期 或 席位窗口非空);两源皆空时 `codes=set()`、`available=False`。后续 Task 2/3 依赖此签名。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_quant_active_codes.py`:

```python
"""quant_active_codes:『量化资金参与』代码集 resolver(活跃度≥50 ∪ 近5日量化席位)。"""
from __future__ import annotations

import pytest


@pytest.fixture
def svc(monkeypatch):
    from webui.services import quant_radar_service as svc
    # 每个用例清缓存,互不串扰
    monkeypatch.setattr(svc, "_quant_codes_cache", {"ts": 0.0, "data": None})
    return svc


def _patch_sources(monkeypatch, svc, dates, day_items, seats):
    from data_store import quant_radar_repo
    monkeypatch.setattr(quant_radar_repo, "list_dates", lambda limit=1: dates)
    monkeypatch.setattr(
        quant_radar_repo, "get_day",
        lambda d, limit=0, min_activity=0, **kw: day_items)
    monkeypatch.setattr(svc, "_quant_seats_window", lambda days=5: seats)


def test_union_of_activity_and_seats(svc, monkeypatch):
    _patch_sources(monkeypatch, svc,
                   dates=["2026-07-21"],
                   day_items=[{"code": "600001"}, {"code": "000002"}],
                   seats={"300003": [{"inst_name": "量化基金专用"}]})
    info = svc.quant_active_codes()
    assert info["codes"] == {"600001", "000002", "300003"}
    assert info["as_of"] == "2026-07-21"
    assert info["available"] is True


def test_seats_only_still_available(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=[], day_items=[],
                   seats={"300003": [{"inst_name": "DMA席位"}]})
    info = svc.quant_active_codes()
    assert info["codes"] == {"300003"}
    assert info["as_of"] is None
    assert info["available"] is True


def test_both_sources_empty_unavailable(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=[], day_items=[], seats={})
    info = svc.quant_active_codes()
    assert info["codes"] == set()
    assert info["available"] is False


def test_ttl_cache_and_force(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=["2026-07-21"],
                   day_items=[{"code": "600001"}], seats={})
    first = svc.quant_active_codes()
    # 换数据源:缓存内不生效,force 才重算
    _patch_sources(monkeypatch, svc, dates=["2026-07-22"],
                   day_items=[{"code": "000009"}], seats={})
    assert svc.quant_active_codes() is first
    assert svc.quant_active_codes(force=True)["codes"] == {"000009"}


def test_source_exception_swallowed(svc, monkeypatch):
    from data_store import quant_radar_repo
    monkeypatch.setattr(quant_radar_repo, "list_dates",
                        lambda limit=1: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(svc, "_quant_seats_window", lambda days=5: {})
    info = svc.quant_active_codes()
    assert info["codes"] == set()
    assert info["available"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_active_codes.py -v`
Expected: FAIL — `AttributeError: ... has no attribute '_quant_codes_cache'` / `quant_active_codes`

- [ ] **Step 3: 最小实现**

`webui/services/quant_radar_service.py`。模块级缓存变量,放在既有 `_overview_cache` 声明(约 L39-41)旁:

```python
_QUANT_CODES_TTL = 300  # 「无量化」过滤代码集缓存(秒)
_QUANT_ACTIVITY_MIN = 50  # 活跃度≥50(预警等级 中/高)判定量化参与
_quant_codes_cache: Dict[str, Any] = {"ts": 0.0, "data": None}
_quant_codes_lock = threading.Lock()
```

函数放在 `_quant_seats_window` 定义之后:

```python
def quant_active_codes(force: bool = False) -> Dict[str, Any]:
    """『量化资金参与』代码集(资金榜单「无量化」过滤口径),纯本地不发网络。

    并集口径: 最近有数据交易日 activity>=50(quant_radar_stock_daily)
    ∪ 近5自然日龙虎榜量化席位。available=任一源有数据;两源皆空→过滤退化 no-op。
    返回 {"codes": set[6位代码], "as_of": 活跃度数据日|None, "available": bool}。
    """
    with _quant_codes_lock:
        hit = _quant_codes_cache["data"]
        if not force and hit is not None and time.time() - _quant_codes_cache["ts"] < _QUANT_CODES_TTL:
            return hit
    codes: set = set()
    as_of = None
    activity_ok = False
    try:
        from data_store import quant_radar_repo

        dates = quant_radar_repo.list_dates(1)
        if dates:
            as_of = dates[0]
            activity_ok = True
            for item in quant_radar_repo.get_day(as_of, limit=0,
                                                 min_activity=_QUANT_ACTIVITY_MIN):
                code = str(item.get("code") or "").strip()
                if code:
                    codes.add(code)
    except Exception:
        pass
    seats = {}
    try:
        seats = _quant_seats_window(5) or {}
        codes.update(k for k in seats if k)
    except Exception:
        pass
    data = {"codes": codes, "as_of": as_of,
            "available": bool(activity_ok or seats)}
    with _quant_codes_lock:
        _quant_codes_cache["ts"] = time.time()
        _quant_codes_cache["data"] = data
    return data
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_quant_active_codes.py -v`
Expected: 5 passed

- [ ] **Step 5: 回归既有量化雷达测试**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -q`
Expected: 与改动前相同的通过/失败集(不新增失败;既存失败清单见项目记忆,非本次引入)

---

### Task 2: 资金榜 envelope 过滤(主榜 + 5日/30日窗口榜)

**Files:**
- Modify: `webui/services/capital_rankings_service.py`(`__init__` 约 L177、`moneyflow_ranking` L183、`dragon_tiger_ranking` L214、`_envelope` L298、`_window_rankings` L406)
- Test: `tests/test_capital_rankings_service.py`(文件尾追加用例)

**Interfaces:**
- Consumes: Task 1 的 `quant_active_codes()`(lazy import,可注入替身);行 code 字段来自 `_normalize`(6位裸码 `row["code"]`)。
- Produces: `moneyflow_ranking(..., no_quant: bool = False)`、`dragon_tiger_ranking(..., no_quant: bool = False)`;envelope 新增键 `no_quant: bool`、`quant_filtered: int`、`quant_criteria_available: bool|None`、`quant_as_of: str|None`,`windows.{"5","30"}` 各新增 `quant_filtered: int`。`CapitalRankingsService.__init__(quote_provider=None, quant_codes_fn=None)`。Task 4 路由依赖 `no_quant` 形参名。

- [ ] **Step 1: 写失败测试**

在 `tests/test_capital_rankings_service.py` 文件末尾追加(复用文件既有 `conn` fixture 与 `_seed_moneyflow`/`_seed_dragon_tiger` helper):

```python
# ---------- 「无量化」过滤 ----------

_QINFO = {"codes": {"000002"}, "as_of": "2026-06-04", "available": True}


def _svc_nq(qinfo=_QINFO):
    from webui.services.capital_rankings_service import CapitalRankingsService
    return CapitalRankingsService(quote_provider=None, quant_codes_fn=lambda: qinfo)


def _seed_three(date="2026-06-04"):
    _seed_moneyflow([
        {"trade_date": date, "ts_code": "000001.SZ", "name": "甲", "net_amount": 3e7, "close": 10.0, "pct_change": 5.0},
        {"trade_date": date, "ts_code": "000002.SZ", "name": "乙", "net_amount": 9e7, "close": 20.0, "pct_change": 9.9},
        {"trade_date": date, "ts_code": "000003.SZ", "name": "丙", "net_amount": 1e7, "close": 5.0, "pct_change": 1.0},
    ])


def test_moneyflow_no_quant_filters_rows_and_windows(conn):
    _seed_three()
    res = _svc_nq().moneyflow_ranking(date="2026-06-04", top_n=10, mode="single", no_quant=True)
    codes = [r["code"] for r in res["rows"]]
    assert "000002" not in codes and set(codes) == {"000001", "000003"}
    assert res["no_quant"] is True
    assert res["quant_filtered"] == 1
    assert res["quant_criteria_available"] is True
    assert res["quant_as_of"] == "2026-06-04"
    for win in ("5", "30"):
        assert res["windows"][win]["quant_filtered"] == 1
        assert all(r["code"] != "000002" for r in res["windows"][win]["rows"])


def test_moneyflow_no_quant_overfetch_refills_top_n(conn):
    # top_n=1 且榜首 000002 是量化股:over-fetch 后仍能给出 1 行(次名 000001)
    _seed_three()
    res = _svc_nq().moneyflow_ranking(date="2026-06-04", top_n=1, mode="single", no_quant=True)
    assert [r["code"] for r in res["rows"]] == ["000001"]
    assert res["top_n"] == 1 and res["count"] == 1


def test_moneyflow_default_no_quant_off_and_lazy(conn):
    _seed_three()
    called = []
    from webui.services.capital_rankings_service import CapitalRankingsService
    svc = CapitalRankingsService(quant_codes_fn=lambda: called.append(1) or _QINFO)
    res = svc.moneyflow_ranking(date="2026-06-04", top_n=10, mode="single")
    assert res["no_quant"] is False and res["quant_filtered"] == 0
    assert {r["code"] for r in res["rows"]} == {"000001", "000002", "000003"}
    assert not called  # 未勾选时不触碰量化代码集


def test_moneyflow_no_quant_criteria_unavailable_noop(conn):
    _seed_three()
    res = _svc_nq({"codes": set(), "as_of": None, "available": False}).moneyflow_ranking(
        date="2026-06-04", top_n=10, mode="single", no_quant=True)
    assert res["quant_criteria_available"] is False
    assert res["quant_filtered"] == 0
    assert {r["code"] for r in res["rows"]} == {"000001", "000002", "000003"}


def test_dragon_tiger_no_quant(conn):
    _seed_dragon_tiger([
        {"trade_date": "2026-06-04", "ts_code": "000002.SZ", "name": "乙", "l_buy": 9e7, "l_sell": 1e7, "net_rate": 5.0},
        {"trade_date": "2026-06-04", "ts_code": "600001.SH", "name": "丁", "l_buy": 5e7, "l_sell": 2e7, "net_rate": 3.0},
    ])
    res = _svc_nq().dragon_tiger_ranking(date="2026-06-04", top_n=10, mode="single", no_quant=True)
    assert [r["code"] for r in res["rows"]] == ["600001"]
    assert res["quant_filtered"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_capital_rankings_service.py -v -k no_quant`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'quant_codes_fn'` / `'no_quant'`

- [ ] **Step 3: 实现**

`webui/services/capital_rankings_service.py`:

3a. `__init__`(约 L177)加注入口:

```python
    def __init__(self, quote_provider: Optional[Callable[[list], dict]] = None,
                 quant_codes_fn: Optional[Callable[[], dict]] = None):
        ...  # 既有赋值保持
        self._quant_codes_fn = quant_codes_fn
```

3b. 类内新增两个私有 helper(放 `_envelope` 前):

```python
    @staticmethod
    def _fetch_limit(top_n: int, no_quant: bool) -> int:
        """no_quant 时 over-fetch ×3(上限500),过滤后截回 top_n,避免榜单缩水。"""
        return min(int(top_n) * 3, 500) if no_quant else int(top_n)

    def _quant_code_info(self) -> dict:
        if self._quant_codes_fn is not None:
            return self._quant_codes_fn()
        try:
            from webui.services import quant_radar_service
            return quant_radar_service.quant_active_codes()
        except Exception:  # noqa: BLE001 — 量化口径缺失不能阻断榜单
            return {"codes": set(), "as_of": None, "available": False}
```

3c. `moneyflow_ranking` / `dragon_tiger_ranking`:签名各加 `no_quant=False`;函数体内取数 limit 全部换 `fetch_n = self._fetch_limit(top_n, no_quant)`(`get_range_aggregated(limit=fetch_n)` / `get_aggregated(limit=fetch_n)` / `get_ranking(limit=fetch_n)`;龙虎榜侧 `get_range_aggregated(top_n=fetch_n)` / `get_aggregated(top_n=fetch_n)` / `get_top_n(as_of, fetch_n)`);所有 `self._envelope(...)` 调用尾部加 `no_quant=no_quant`。

3d. `_envelope` 重构(签名加 `no_quant=False`;过滤→截断→再挂报价,报价少拉无用行):

```python
    def _envelope(self, kind, mode, as_of, days, top_n, df, with_quotes,
                  start_date=None, end_date=None, no_quant=False) -> dict:
        quant_info = self._quant_code_info() if no_quant else None
        quant_codes = (quant_info or {}).get("codes") or set()
        rows = self._normalize(df)
        quant_filtered = 0
        if quant_codes:
            before = len(rows)
            rows = [r for r in rows if r.get("code") not in quant_codes]
            quant_filtered = before - len(rows)
        rows = rows[:top_n]
        if with_quotes:
            rows = self._attach_quotes(rows)
        windows = (self._window_rankings(kind, as_of, top_n, with_quotes,
                                         quant_info=quant_info)
                   if as_of else {})
        return {
            "kind": kind,
            "mode": mode,
            "as_of": as_of,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n,
            "count": len(rows),
            "rows": rows,
            "windows": windows,
            "no_quant": bool(no_quant),
            "quant_filtered": quant_filtered,
            "quant_criteria_available": (quant_info or {}).get("available") if no_quant else None,
            "quant_as_of": (quant_info or {}).get("as_of") if no_quant else None,
        }
```

3e. `_window_rankings`(签名加 `quant_info=None`;`rank` 保留原值不重排——净流入榜 rank 表全市场排名,过滤留空洞属预期):

```python
    def _window_rankings(self, kind, as_of, top_n, with_quotes, quant_info=None) -> dict:
        quant_codes = (quant_info or {}).get("codes") or set()
        fetch_n = self._fetch_limit(top_n, bool(quant_codes))
        windows: dict[str, dict[str, Any]] = {}
        for days in (5, 30):
            if kind == "moneyflow":
                df = moneyflow_repo.get_aggregated(
                    as_of, days=days, limit=fetch_n,
                    snapshot_top_n=SNAPSHOT_TOP_N, sort_by="net_amount")
            else:
                df = dragon_tiger_list_repo.get_aggregated(
                    as_of, days=days, top_n=fetch_n, sort_by="l_buy")
            rows = self._normalize(df)
            quant_filtered = 0
            if quant_codes:
                before = len(rows)
                rows = [r for r in rows if r.get("code") not in quant_codes]
                quant_filtered = before - len(rows)
            rows = rows[:top_n]
            if with_quotes:
                rows = self._attach_quotes(rows)
            windows[str(days)] = {"days": days, "count": len(rows),
                                  "rows": rows, "quant_filtered": quant_filtered}
        return windows
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_capital_rankings_service.py -v -k no_quant`
Expected: 5 passed

- [ ] **Step 5: 全文件回归(envelope 加了新键,确认既有用例不受影响)**

Run: `.venv/bin/python -m pytest tests/test_capital_rankings_service.py tests/test_moneyflow_ranking_queries.py tests/test_moneyflow_kv_snapshot.py -q`
Expected: 与改动前相同的通过集,不新增失败

---

### Task 3: 吸筹榜 `_apply_no_quant`

**Files:**
- Modify: `webui/services/quant_radar_service.py`(`accumulation_payload` 约 L1361-1467:签名 + 3 个 return 路径;新 helper `_apply_no_quant` 放 `accumulation_payload` 定义之前)
- Test: `tests/test_quant_active_codes.py`(追加,复用 Task 1 的 fixture 文件)

**Interfaces:**
- Consumes: Task 1 `quant_active_codes()`;`accumulation_payload` 既有 payload 形状 `{"ok","window","count","stocks":[{"code",...}],...}`,三个 return 路径:内存 TTL 缓存命中(约 L1389)、历史 kv 快照命中(约 L1398)、末尾新算(L1467 `return payload`)。
- Produces: `accumulation_payload(..., no_quant: bool = False)`;开启时 payload 新增 `no_quant: True`、`quant_filtered: int`、`quant_criteria_available: bool`,`stocks`/`count` 为过滤后值;**缓存与 kv 快照始终存全量**(helper 返回浅拷贝,不动原 dict)。Task 4 路由依赖 `no_quant` 形参名。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_quant_active_codes.py`:

```python
# ---------- 吸筹榜 no_quant ----------

def test_apply_no_quant_filters_copy_not_mutate(svc, monkeypatch):
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": {"600001"}, "as_of": "2026-07-21", "available": True})
    payload = {"ok": True, "count": 2,
               "stocks": [{"code": "600001", "name": "量"}, {"code": "000002", "name": "非"}]}
    out = svc._apply_no_quant(payload, True)
    assert [s["code"] for s in out["stocks"]] == ["000002"]
    assert out["count"] == 1 and out["quant_filtered"] == 1
    assert out["no_quant"] is True and out["quant_criteria_available"] is True
    # 原 payload(=缓存/kv里的对象)不被改动
    assert payload["count"] == 2 and len(payload["stocks"]) == 2


def test_apply_no_quant_off_is_identity(svc):
    payload = {"ok": True, "count": 0, "stocks": []}
    assert svc._apply_no_quant(payload, False) is payload


def test_apply_no_quant_unavailable_noop(svc, monkeypatch):
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": set(), "as_of": None, "available": False})
    payload = {"ok": True, "count": 1, "stocks": [{"code": "600001"}]}
    out = svc._apply_no_quant(payload, True)
    assert out["count"] == 1 and out["quant_filtered"] == 0
    assert out["quant_criteria_available"] is False


def test_accumulation_payload_no_quant_wired(svc, monkeypatch):
    # 注入式离线:market_rows_fn 返回 None → items 空;只验证 no_quant 键接上了
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": set(), "as_of": None, "available": True})
    out = svc.accumulation_payload(window=40, market_rows_fn=lambda end, w: None,
                                   no_quant=True)
    assert out["no_quant"] is True and out["quant_filtered"] == 0
    out_off = svc.accumulation_payload(window=40, market_rows_fn=lambda end, w: None)
    assert "no_quant" not in out_off  # 关闭时 payload 形状与现状一致
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_active_codes.py -v -k no_quant`
Expected: FAIL — `AttributeError: ... no attribute '_apply_no_quant'`

- [ ] **Step 3: 实现**

`webui/services/quant_radar_service.py`,`accumulation_payload` 之前加:

```python
def _apply_no_quant(payload: Dict[str, Any], no_quant: bool) -> Dict[str, Any]:
    """「无量化」读时过滤:浅拷贝 payload 剔除量化参与股;缓存/kv 快照存全量不动。"""
    if not no_quant or not isinstance(payload, dict):
        return payload
    info = quant_active_codes()
    codes = info.get("codes") or set()
    stocks = list(payload.get("stocks") or [])
    kept = [s for s in stocks if str(s.get("code") or "") not in codes]
    out = dict(payload)
    out["stocks"] = kept
    out["count"] = len(kept)
    out["no_quant"] = True
    out["quant_filtered"] = len(stocks) - len(kept)
    out["quant_criteria_available"] = bool(info.get("available"))
    return out
```

`accumulation_payload` 签名尾部加 `no_quant: bool = False`(放 `fetch_quotes` 之后)。三个 return 改为:

- 内存缓存命中(约 L1389):`return hit["payload"]` → `return _apply_no_quant(hit["payload"], no_quant)`
- kv 快照命中(约 L1398):`return snap[0]` → `return _apply_no_quant(snap[0], no_quant)`
- 末尾(L1467):`return payload` → `return _apply_no_quant(payload, no_quant)`(此行在 kv/缓存写入**之后**,存的是全量)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_quant_active_codes.py -v`
Expected: 全部通过(Task 1 的 5 个 + 本任务 4 个)

- [ ] **Step 5: 回归**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py tests/test_accumulation_detector.py -q`
Expected: 与改动前相同的通过集

---

### Task 4: 路由接线(`no_quant` 参数解析)

**Files:**
- Modify: `webui/robyn_app.py`(`_capital_ranking_payload` 约 L700-730;`quant_radar_accumulation` 约 L1255-1267)
- Test: `tests/test_capital_rankings_no_quant_api.py`(新建);`tests/test_quant_radar_accumulation_api.py`(追加)

**Interfaces:**
- Consumes: Task 2 `moneyflow_ranking(..., no_quant=)` / `dragon_tiger_ranking(..., no_quant=)`;Task 3 `accumulation_payload(..., no_quant=)`。
- Produces: `/api/capital-rankings/moneyflow|dragon-tiger?no_quant=1` 与 `/api/quant-radar/accumulation?no_quant=1`。解析口径:`str 值 in ("1","true","yes")` 为真,缺省 False(向后兼容)。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_capital_rankings_no_quant_api.py`(fixture 复制自 `tests/test_quant_radar_accumulation_api.py` 的 `robyn_module` 模式):

```python
"""资金榜路由 no_quant 参数接线测试(service 打桩,不建数据)。"""

import importlib
import sys

import pytest


@pytest.fixture()
def robyn_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_DISABLE_QUANT_RADAR_AUTOSAVE", "1")
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)
    module = importlib.import_module("webui.robyn_app")
    yield module
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)


class _StubSvc:
    def __init__(self):
        self.calls = []

    def moneyflow_ranking(self, **kw):
        self.calls.append(("moneyflow", kw))
        return {"kind": "moneyflow", "rows": [], "windows": {}}

    def dragon_tiger_ranking(self, **kw):
        self.calls.append(("dragon_tiger", kw))
        return {"kind": "dragon_tiger", "rows": [], "windows": {}}


def test_capital_routes_pass_no_quant(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    stub = _StubSvc()
    monkeypatch.setattr(robyn_module.webui_core, "CAPITAL_RANKINGS_SERVICE", stub)
    with TestClient(robyn_module.app) as client:
        # robyn TestClient 按纯路径匹配路由,query 须走 query_params 参数
        r1 = client.get("/api/capital-rankings/moneyflow",
                        query_params={"no_quant": "1"})
        r2 = client.get("/api/capital-rankings/moneyflow", query_params={})
        r3 = client.get("/api/capital-rankings/dragon-tiger",
                        query_params={"no_quant": "true"})
    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert stub.calls[0][1]["no_quant"] is True
    assert stub.calls[1][1]["no_quant"] is False
    assert stub.calls[2][0] == "dragon_tiger" and stub.calls[2][1]["no_quant"] is True
```

`tests/test_quant_radar_accumulation_api.py`:给既有 `fake_payload` 签名加 `no_quant=False` 并记录,追加断言。在 `test_accumulation_route_passes_params` 中:`fake_payload` 改为

```python
    def fake_payload(window=40, date="", force=False, no_quant=False, **kw):
        calls.append({"window": window, "date": date, "force": force,
                      "no_quant": no_quant})
        return {"ok": True, "window": window, "count": 0, "stocks": [],
                "data_date": "", "note": "", "disclaimer": "d"}
```

既有断言 `assert calls[0] == {...}` 同步加 `"no_quant": False`;并在 `with TestClient` 块内追加一次请求与断言:

```python
        resp_nq = client.get("/api/quant-radar/accumulation",
                             query_params={"no_quant": "1"})
    ...
    assert resp_nq.status_code == 200
    assert calls[2]["no_quant"] is True
```

(注意 `resp_nq` 是第 3 次调用,索引 2;放在 `resp_bad` 之后。)

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_capital_rankings_no_quant_api.py tests/test_quant_radar_accumulation_api.py -v`
Expected: FAIL — stub 收到的 kwargs 里没有 `no_quant` 键(KeyError)

- [ ] **Step 3: 实现**

`webui/robyn_app.py::_capital_ranking_payload`,在 `with_quotes` 解析行(约 L710)后加:

```python
    no_quant = str(_query_value(request, "no_quant", "0")).strip().lower() in ("1", "true", "yes")
```

两个 service 调用各加 `no_quant=no_quant,` 实参。

`quant_radar_accumulation` 路由,在 `force = ...` 行后加:

```python
    no_quant = str(_query_value(request, "no_quant", "") or "").lower() in {"1", "true", "yes"}
```

`accumulation_payload(...)` 调用加 `no_quant=no_quant`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_capital_rankings_no_quant_api.py tests/test_quant_radar_accumulation_api.py -v`
Expected: 全部通过

---

### Task 5: 前端(desktop.html 两个 checkbox + 压缩 JS 尾部 IIFE)

**Files:**
- Modify: `webui/templates/desktop.html`(约 L107-109 Top N label 后;约 L222-228 吸筹榜 header 内)
- Modify: `webui/static/kronos_desktop_app.js`(**文件末尾追加**,现尾字节是 `}();`)

**Interfaces:**
- Consumes: 后端响应键 `no_quant`/`quant_filtered`/`quant_criteria_available`(Task 2/3);压缩 JS 既有顶层函数声明(可重赋值):`capitalParams()`(返回 query string,`function capitalParams(){` 唯一)、`fetchJson(t,e={})`(唯一声明)、`loadCapitalRankings()`、`loadQuantAccum`。
- Produces: `#capitalNoQuant`、`#capitalNoQuantInfo`(作用于主榜+5日+30日,同一 envelope 请求)、`#quantAccumNoQuant`、`#quantAccumNoQuantInfo`。

- [ ] **Step 1: desktop.html 主榜查询区加 checkbox**

在 `.capital-filter-grid` 内 Top N label 之后(`<input id="capitalTopN" ... />` 所在 `</label>` 之后)插入:

```html
                <label class="capital-noquant-field"><input type="checkbox" id="capitalNoQuant" /> 无量化(剔除量化参与股)</label>
```

在 `<span class="panel-meta" id="capitalRankingsMeta">--</span>`(约 L79)后插入:

```html
              <span class="panel-meta" id="capitalNoQuantInfo"></span>
```

- [ ] **Step 2: desktop.html 吸筹榜 header 加 checkbox**

在 `<span class="panel-meta" id="quantAccumMeta">--</span>` 前插入:

```html
                <label class="panel-meta"><input type="checkbox" id="quantAccumNoQuant" /> 无量化</label>
                <span class="panel-meta" id="quantAccumNoQuantInfo"></span>
```

- [ ] **Step 3: 压缩 JS 尾部追加 IIFE**

在 `webui/static/kronos_desktop_app.js` 文件**末尾**追加(整段以 `\n;` 开头——分号必须有):

```js

;(function(){"use strict";
function nq(id){var el=document.getElementById(id);return!!(el&&el.checked)}
function info(id,d){var el=document.getElementById(id);if(!el)return;if(!d||!d.no_quant){el.textContent="";return}el.textContent=d.quant_criteria_available===!1?"量化口径数据缺失,未过滤":"已过滤 "+(d.quant_filtered||0)+" 只量化参与股"}
var origParams=capitalParams;
capitalParams=function(){var s=origParams();return nq("capitalNoQuant")?s+"&no_quant=1":s};
var origFetch=fetchJson;
fetchJson=function(url,opts){
  if(typeof url==="string"&&url.indexOf("/api/quant-radar/accumulation")===0&&nq("quantAccumNoQuant"))
    url+=(url.indexOf("?")>=0?"&":"?")+"no_quant=1";
  var p=origFetch(url,opts===undefined?{}:opts);
  if(typeof url==="string"&&p&&typeof p.then==="function"){
    if(url.indexOf("/api/capital-rankings/moneyflow")===0||url.indexOf("/api/capital-rankings/dragon-tiger")===0)
      p.then(function(d){info("capitalNoQuantInfo",d)},function(){});
    else if(url.indexOf("/api/quant-radar/accumulation")===0)
      p.then(function(d){info("quantAccumNoQuantInfo",d)},function(){});
  }
  return p;
};
document.addEventListener("change",function(ev){
  var t=ev.target;if(!t||!t.id)return;
  if(t.id==="capitalNoQuant"){if(typeof loadCapitalRankings==="function")loadCapitalRankings()}
  else if(t.id==="quantAccumNoQuant"){if(typeof loadQuantAccum==="function")loadQuantAccum()}
});
})();
```

要点:`capitalParams` 原实现返回 `l.toString()`(字符串,恒非空,直接拼 `&` 安全);`fetchJson` 是顶层 `function` 声明,同一 classic script 作用域内可重赋值;`p.then(ok,fail)` 只旁观 payload 更新提示条,不改变返回的 promise;取消勾选后重查,响应无 `no_quant` 键 → 提示条自动清空。

- [ ] **Step 4: 语法校验**

Run: `node --check webui/static/kronos_desktop_app.js`
Expected: 无输出(exit 0)

- [ ] **Step 5: 引用完整性抽查**

Run: `grep -c "function capitalParams()" webui/static/kronos_desktop_app.js && grep -c "function fetchJson" webui/static/kronos_desktop_app.js && grep -c "capitalNoQuant" webui/templates/desktop.html`
Expected: `1` / `1` / `≥2`(声明各唯一;模板含 checkbox+info)

---

### Task 6: 端到端实证 + 收尾

**Files:**
- 无新改动(验证任务);如 e2e 暴露问题,回对应 Task 修

**Interfaces:**
- Consumes: 全部前序任务;dev 服务器(Robyn,端口 env `KRONOS_PORT`,默认 7070)。

- [ ] **Step 1: 相关测试全量回归**

Run: `.venv/bin/python -m pytest tests/test_quant_active_codes.py tests/test_capital_rankings_service.py tests/test_capital_rankings_no_quant_api.py tests/test_quant_radar_accumulation_api.py tests/test_quant_radar_service.py tests/test_moneyflow_ranking_queries.py tests/test_moneyflow_kv_snapshot.py -q`
Expected: 除项目记忆中的既存失败清单外全绿,无新增失败

- [ ] **Step 2: 重启 dev 服务器**

⚠️ Robyn 不响应 SIGTERM:先 `lsof -ti tcp:7070 | xargs kill -9`(端口以 `KRONOS_PORT` 实际值为准),轮询端口释放后再启动(项目既有启动方式,后台运行),轮询 `/api/` 就绪。

- [ ] **Step 3: API 实证(真库)**

```bash
curl -s "http://127.0.0.1:7070/api/capital-rankings/moneyflow?top=50" | python3 -c "import json,sys;d=json.load(sys.stdin);print('off',d['count'],d.get('no_quant'))"
curl -s "http://127.0.0.1:7070/api/capital-rankings/moneyflow?top=50&no_quant=1" | python3 -c "import json,sys;d=json.load(sys.stdin);print('on',d['count'],d['quant_filtered'],d['quant_criteria_available'],[w.get('quant_filtered') for w in d['windows'].values()])"
curl -s "http://127.0.0.1:7070/api/quant-radar/accumulation?window=40&no_quant=1" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['count'],d.get('quant_filtered'),d.get('quant_criteria_available'))"
```

Expected: `no_quant=1` 时 `quant_filtered ≥ 0` 且开/关两次的 rows 集合差 = 被剔量化股;本机库 `quant_radar_stock_daily` 有历史数据,`quant_criteria_available` 应为 `True`。开关两次 accumulation 确认 kv 快照未被过滤版污染(off 请求 count 恢复全量)。

- [ ] **Step 4: 页面实证(可选,Puppeteer/浏览器)**

打开资金榜单页:勾选「无量化」→ 主榜/5日/30日行数变化且提示「已过滤 N 只量化参与股」;切到量化 tab 吸筹榜勾选同验;取消勾选恢复。控制台无报错。

- [ ] **Step 5: 收尾说明**

向用户报告:功能完成、测试证据、**未做任何 git 操作**、打包 App 需重打包才生效。

---

## Self-Review 结论

- **Spec 覆盖**: 口径(Task 1)、主榜+窗口榜(Task 2)、吸筹榜(Task 3)、路由(Task 4)、前端(Task 5)、错误处理(两源空 no-op: Task 1/2/3 各有用例)、e2e(Task 6)——全覆盖。Spec 中「新增 repo 查询 codes_with_activity」已被「复用 get_day(limit=0, min_activity=50)」取代(spec 已同步更新)。
- **占位符**: 无 TBD;所有代码步骤含完整代码。
- **类型一致性**: `quant_active_codes()` 返回形状在 Task 1 定义、Task 2 `quant_codes_fn` 与 Task 3 `_apply_no_quant` 消费一致;`no_quant` 形参名贯穿 service→route→前端 query 参数。
- **约定**: 全计划无 git 步骤(用户约定覆盖技能模板的 commit 步骤)。
