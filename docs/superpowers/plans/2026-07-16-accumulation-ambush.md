# 吸筹埋伏(Accumulation Ambush)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 量化雷达 tab 新增「吸筹埋伏榜」+ 个股深评吸筹分析:识别主力持续净流入且股价横盘的吸筹行为,统计吸筹时间/吸筹量/埋伏评分。

**Architecture:** 纯函数检测模块(`analysis/accumulation_detector.py`)消费 `moneyflow_dc` 逐日资金流;`moneyflow_repo.get_market_window` 一次取全市场窗口;`quant_radar_service.accumulation_payload` 组装榜单(TTL+kv 按日快照,历史回看纯本地);新 API + 前端追加式改造(压缩 JS 末尾追加可读代码,函数绑定重赋值挂钩,零原位字节编辑)。

**Tech Stack:** Python 3.13(`.venv`)/ pandas / SQLite(data_store)/ Robyn / 原生 JS(esbuild 压缩产物)

**Spec:** `docs/superpowers/specs/2026-07-16-accumulation-ambush-design.md`

## Global Constraints

- **禁止一切 git 写操作**(commit/add/push 等)——用户自管提交;本计划所有任务到「测试通过」为止,不含 commit 步骤。
- 所有持久化走 SQLite(kv_repo / 既有表),不落 CSV。
- 测试命令统一用 `.venv/bin/python -m pytest`(本机 Homebrew Python 受 PEP 668 限制)。
- `webui/static/kronos_desktop_app.js` 是 esbuild 压缩单行文件:**只允许在文件末尾追加可读代码**,通过函数绑定重赋值(顶层 `function` 声明可重赋值)挂钩既有逻辑,不做压缩区原位编辑。
- UI 文案中文,统一「疑似/公开数据代理指标/不构成投资建议」免责口径。
- `moneyflow_dc` 金额单位以 `amount_unit` 为准(万元/元),模块内统一归一到**万元**。
- 服务函数不 import `webui.core`(避免环),外部数据经参数注入以便离线测试(与 `overview()` 同套路)。

---

### Task 1: 吸筹检测纯函数模块

**Files:**
- Create: `analysis/accumulation_detector.py`
- Test: `tests/test_accumulation_detector.py`

**Interfaces:**
- Produces: `detect(rows: List[Dict], window: int = 40) -> Optional[Dict]`;常量 `WINDOWS = (20, 40, 60)`。
  - 输入行字段:`trade_date, net_amount, net_amount_rate, buy_elg_amount, buy_lg_amount, close, pct_change, amount_unit`(即 `moneyflow_dc` 行,顺序不限,函数内部按 `trade_date` 升序排)。
  - 返回 None(覆盖不足)或 dict:`qualified, window, coverage_days, accum_days, accum_ratio, max_streak, span_days, total_net_wan, avg_rate, elg_share, window_pct_chg, score, status, reasons, daily`;`daily` 为 `[{date, net_wan, pct}]`。

- [ ] **Step 1: 写失败测试**

```python
"""吸筹识别纯函数测试 —— 离线,不联网,不建库。

覆盖 :mod:`analysis.accumulation_detector`:判定三条件(流入持续性/力度/量价背离)、
时间与量统计(吸筹天数/最长连续/跨度/累计吸筹量)、埋伏评分、状态与单位归一。
设计 spec: docs/superpowers/specs/2026-07-16-accumulation-ambush-design.md
"""

from analysis import accumulation_detector as ad


def _row(date, net, rate=0.5, elg=None, lg=0.0, close=10.0, pct=0.1, unit="万元"):
    return {"trade_date": date, "net_amount": net, "net_amount_rate": rate,
            "buy_elg_amount": elg if elg is not None else net * 0.6,
            "buy_lg_amount": lg, "close": close, "pct_change": pct,
            "amount_unit": unit}


def _dates(n):
    # 40 个以内的合成交易日(6月30天 + 7月),保证字典序==时间序
    out = []
    for i in range(n):
        m, d = (6, i + 1) if i < 30 else (7, i - 29)
        out.append(f"2026-{m:02d}-{d:02d}")
    return out


def _accum_rows(n=30, inflow_days=24, close_start=10.0, close_end=10.5):
    """典型吸筹序列:前 inflow_days 天净流入,其余净流出;价格缓慢爬升。"""
    dates = _dates(n)
    rows = []
    for i, date in enumerate(dates):
        close = close_start + (close_end - close_start) * i / max(1, n - 1)
        if i < inflow_days:
            rows.append(_row(date, net=3000.0, rate=0.6, close=round(close, 3)))
        else:
            rows.append(_row(date, net=-1000.0, rate=-0.2, close=round(close, 3)))
    return rows


def test_typical_accumulation_qualifies_with_full_stats():
    result = ad.detect(_accum_rows(), window=40)
    assert result is not None
    assert result["qualified"] is True
    assert result["window"] == 40
    assert result["coverage_days"] == 30
    assert result["accum_days"] == 24
    assert result["accum_ratio"] == 0.8
    assert result["max_streak"] == 24          # 前24天连续净流入
    assert result["span_days"] == 24           # 首个→最近净流入日
    assert result["total_net_wan"] == 24 * 3000.0 - 6 * 1000.0
    assert result["status"] == "吸筹中"
    assert result["score"] >= 50
    assert abs(result["window_pct_chg"] - 5.0) < 0.2   # 10.0 → 10.5
    assert any("净流入" in r for r in result["reasons"])
    assert len(result["daily"]) == 30
    assert set(result["daily"][0]) == {"date", "net_wan", "pct"}


def test_distribution_fails_ratio_condition():
    rows = [_row(d, net=-2000.0, rate=-0.5, pct=-0.3) for d in _dates(30)]
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert result["accum_days"] == 0
    assert any("占比" in r for r in result["reasons"])


def test_pumped_stock_fails_price_divergence():
    rows = _accum_rows(close_start=10.0, close_end=13.0)   # 窗口 +30%
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert any("量价背离" in r or "涨跌幅" in r for r in result["reasons"])


def test_weak_inflow_fails_rate_condition():
    rows = [_row(d, net=10.0, rate=0.01) for d in _dates(30)]  # 天天微量流入
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert any("力度" in r for r in result["reasons"])


def test_insufficient_coverage_returns_none():
    assert ad.detect(_accum_rows(n=10), window=40) is None
    assert ad.detect([], window=40) is None
    assert ad.detect(None, window=40) is None


def test_recent_kick_marks_launching_status():
    rows = _accum_rows()
    for r, pct in zip(rows[-3:], (2.0, 2.0, 2.0)):   # 近3日累计 +6%
        r["pct_change"] = pct
    result = ad.detect(rows, window=40)
    assert result["qualified"] is True
    assert result["status"] == "疑似启动"
    assert any("启动" in r for r in result["reasons"])


def test_institutional_elg_share_bonus():
    rows = _accum_rows()
    plain = ad.detect([{**r, "buy_elg_amount": 0.0} for r in rows], window=40)
    inst = ad.detect(rows, window=40)   # elg = 0.6*net → 占比 > 0.7(净流出日也为负贡献)
    assert inst["elg_share"] is not None
    if inst["elg_share"] >= 0.7:
        assert inst["score"] >= plain["score"] + 5
        assert any("机构" in r for r in inst["reasons"])


def test_amount_unit_yuan_normalized_to_wan():
    rows = [_row(d, net=3000.0 * 1e4, rate=0.6, unit="元") for d in _dates(20)]
    result = ad.detect(rows, window=20)
    assert result is not None
    assert abs(result["total_net_wan"] - 20 * 3000.0) < 1e-6
    assert result["daily"][0]["net_wan"] == 3000.0


def test_window_slices_latest_rows_and_sorts_input():
    rows = list(reversed(_accum_rows(n=30)))   # 倒序输入,函数内部应排序
    r40 = ad.detect(rows, window=40)
    r20 = ad.detect(rows, window=20)
    assert r40["coverage_days"] == 30
    assert r20["coverage_days"] == 20          # 只取最近 20 行
    assert r20["window"] == 20


def test_invalid_window_falls_back_to_40():
    result = ad.detect(_accum_rows(), window=37)
    assert result["window"] == 40
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_accumulation_detector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.accumulation_detector'`

- [ ] **Step 3: 实现模块**

```python
"""吸筹识别与统计 —— 主力资金持续净流入 + 量价背离(纯函数,离线可测)。

数据源:``moneyflow_dc`` top_n=0 全市场快照行(取数在 repo/service 层,本模块零 IO)。
判定口径(spec §2.3,三条同时满足):流入持续性(净流入天数占比≥55%)、
流入力度(累计净流入>0 且日均净流入率≥0.2%)、量价背离(窗口涨跌幅在 ±15% 内)。
「疑似」口径:主力净流入为公开数据代理指标,不构成吸筹行为认定与投资建议。
设计 spec: docs/superpowers/specs/2026-07-16-accumulation-ambush-design.md
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

WINDOWS = (20, 40, 60)

# 判定与评分阈值(集中放置便于调参)
RATIO_MIN = 0.55                 # 净流入天数占比下限
DAILY_RATE_MIN = 0.2             # 日均净流入率下限(%)
PRICE_BAND = 15.0                # 量价背离:窗口区间涨跌幅绝对值上限(%)
KICK_3D_PCT = 5.0                # 疑似启动:近3日累计涨幅(%)
RATE_CAP = 1.0                   # 评分用日均净流入率封顶(%)
ELG_SHARE_INSTITUTIONAL = 0.7    # 超大+大单占比 ≥ 该值记机构型加成


def _num(v: Any) -> Optional[float]:
    try:
        if v in (None, "", "-"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize(rows: List[Dict[str, Any]], window: int) -> List[Dict[str, Any]]:
    """原始行 → 升序、单位归一(万元)、剔除无净额行,截取窗口末端。"""
    srt = sorted((r for r in rows or [] if r.get("trade_date")),
                 key=lambda r: str(r["trade_date"]))
    days: List[Dict[str, Any]] = []
    for r in srt:
        net = _num(r.get("net_amount"))
        if net is None:
            continue
        mult = 1e-4 if str(r.get("amount_unit") or "万元") == "元" else 1.0
        days.append({
            "date": str(r["trade_date"]),
            "net": net * mult,
            "rate": _num(r.get("net_amount_rate")),
            "elg_lg": ((_num(r.get("buy_elg_amount")) or 0.0)
                       + (_num(r.get("buy_lg_amount")) or 0.0)) * mult,
            "close": _num(r.get("close")),
            "pct": _num(r.get("pct_change")),
        })
    return days[-window:]


def detect(rows: Optional[List[Dict[str, Any]]], window: int = 40) -> Optional[Dict[str, Any]]:
    """单只股票吸筹检测:``moneyflow_dc`` 行序列 → 判定 + 时间/量统计 + 埋伏评分。

    覆盖天数 < max(12, window//2) → None(新股/长停牌自然排除)。
    ``qualified`` 与否都返回统计,未通过时 ``reasons`` 为未通过原因。
    """
    window = int(window) if window in WINDOWS else 40
    days = _normalize(rows or [], window)
    coverage = len(days)
    if coverage < max(12, window // 2):
        return None

    inflow = [d["net"] > 0 for d in days]
    accum_days = sum(inflow)
    accum_ratio = round(accum_days / coverage, 3)
    max_streak = cur = 0
    for flag in inflow:
        cur = cur + 1 if flag else 0
        max_streak = max(max_streak, cur)
    idx = [i for i, flag in enumerate(inflow) if flag]
    span_days = (idx[-1] - idx[0] + 1) if idx else 0
    total_net_wan = round(sum(d["net"] for d in days), 2)
    rates = [d["rate"] for d in days if d["rate"] is not None]
    avg_rate = round(sum(rates) / coverage, 3) if rates else 0.0
    elg_lg_net = sum(d["elg_lg"] for d in days)
    elg_share = round(elg_lg_net / total_net_wan, 3) if total_net_wan > 0 else None

    closes = [d["close"] for d in days if d["close"]]
    if len(closes) >= 2 and closes[0] > 0:
        window_pct_chg = (closes[-1] / closes[0] - 1) * 100
    else:  # close 缺失时用逐日涨跌幅合计近似
        window_pct_chg = sum(d["pct"] or 0.0 for d in days)
    window_pct_chg = round(window_pct_chg, 2)

    fails: List[str] = []
    if accum_ratio < RATIO_MIN:
        fails.append(f"净流入天数占比 {accum_ratio:.0%} 不足 {RATIO_MIN:.0%}")
    if not (total_net_wan > 0 and avg_rate >= DAILY_RATE_MIN):
        fails.append(f"流入力度不足(日均净流入率 {avg_rate:.2f}%,"
                     f"累计 {total_net_wan:.0f} 万元)")
    if abs(window_pct_chg) > PRICE_BAND:
        fails.append(f"窗口涨跌幅 {window_pct_chg:+.1f}% 超出 ±{PRICE_BAND:.0f}%,"
                     "量价背离不成立(或已拉升)")
    qualified = not fails

    score = (30 * _clip01((accum_ratio - RATIO_MIN) / (1 - RATIO_MIN))
             + 2 * min(max_streak, 10)
             + 25 * _clip01((avg_rate - DAILY_RATE_MIN) / (RATE_CAP - DAILY_RATE_MIN))
             + 15 * _clip01((PRICE_BAND - abs(window_pct_chg)) / PRICE_BAND))
    institutional = elg_share is not None and elg_share >= ELG_SHARE_INSTITUTIONAL
    if institutional:
        score += 10
    score = int(round(max(0.0, min(100.0, score))))

    kick = sum(d["pct"] or 0.0 for d in days[-3:])
    status = ("疑似启动" if kick >= KICK_3D_PCT else "吸筹中") if qualified else ""

    if qualified:
        reasons = [
            f"近{coverage}个交易日 {accum_days} 天主力净流入"
            f"(占比 {accum_ratio:.0%}),最长连续 {max_streak} 天",
            f"累计净流入 {total_net_wan / 1e4:.2f} 亿元,日均净流入率 {avg_rate:.2f}%",
            f"期间股价仅 {window_pct_chg:+.1f}%,资金持续进而价未动,疑似吸筹",
        ]
        if institutional:
            reasons.append(f"超大+大单贡献 {elg_share:.0%},机构型吸筹特征")
        if status == "疑似启动":
            reasons.append(f"近3日累计上涨 {kick:+.1f}%,吸筹后疑似启动")
    else:
        reasons = fails

    return {
        "qualified": qualified,
        "window": window,
        "coverage_days": coverage,
        "accum_days": accum_days,
        "accum_ratio": accum_ratio,
        "max_streak": max_streak,
        "span_days": span_days,
        "total_net_wan": total_net_wan,
        "avg_rate": avg_rate,
        "elg_share": elg_share,
        "window_pct_chg": window_pct_chg,
        "score": score,
        "status": status,
        "reasons": reasons,
        "daily": [{"date": d["date"], "net_wan": round(d["net"], 2), "pct": d["pct"]}
                  for d in days],
    }
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `.venv/bin/python -m pytest tests/test_accumulation_detector.py -v`
Expected: 全部 PASS。若 `test_typical_accumulation_qualifies_with_full_stats` 的 score 断言失败,核对评分公式各分项而非放宽断言。

---

### Task 2: `moneyflow_repo.get_market_window` 全市场窗口取数

**Files:**
- Modify: `data_store/moneyflow_repo.py`(在 `get_stock_rows` 之后追加)
- Test: `tests/test_moneyflow_ranking_queries.py`(文件末尾追加;复用该文件既有 DB fixture——先读文件确认 fixture 名,若与 `tests/test_quant_radar_service.py` 的 `tmp_db` 不同,按该文件现名使用)

**Interfaces:**
- Produces: `get_market_window(end_date: str, days: int, snapshot_top_n: int = 0) -> pd.DataFrame` — `trade_date <= end_date` 的最近 `days` 个 distinct 交易日的全市场行,**按 trade_date 升序**;days 上限 250;无数据返回空 DataFrame。

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_moneyflow_ranking_queries.py`,`import pandas as pd` 按需补)

```python
def _window_df(dates, codes, net=1000.0):
    import pandas as pd

    rows = []
    for d in dates:
        for c in codes:
            rows.append({"trade_date": d, "ts_code": c, "name": "股" + c[:6],
                         "pct_change": 0.5, "close": 10.0,
                         "net_amount": net, "net_amount_rate": 0.5,
                         "buy_elg_amount": net * 0.6, "buy_elg_amount_rate": 0.3,
                         "buy_lg_amount": 0.0, "buy_lg_amount_rate": 0.0,
                         "buy_md_amount": 0.0, "buy_md_amount_rate": 0.0,
                         "buy_sm_amount": 0.0, "buy_sm_amount_rate": 0.0,
                         "amount_unit": "万元"})
    return pd.DataFrame(rows)


def test_get_market_window_returns_recent_days_ascending(tmp_db):
    from data_store import moneyflow_repo as repo

    dates = ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]
    repo.upsert_df(_window_df(dates, ["600000.SH", "000001.SZ"]), top_n=0)
    repo.upsert_df(_window_df(["2026-07-10"], ["600000.SH"]), top_n=20)  # 其它桶不串

    df = repo.get_market_window("2026-07-10", 3)
    assert sorted(df["trade_date"].unique()) == ["2026-07-08", "2026-07-09", "2026-07-10"]
    assert list(df["trade_date"]) == sorted(df["trade_date"])          # 升序
    assert len(df) == 6                                                # 3日 × 2股
    # as-of 回看:end_date 早于最新日
    df_past = repo.get_market_window("2026-07-08", 2)
    assert sorted(df_past["trade_date"].unique()) == ["2026-07-07", "2026-07-08"]
    # 兼容 YYYYMMDD 输入与空库
    assert len(repo.get_market_window("20260710", 1)["trade_date"].unique()) == 1
    assert repo.get_market_window("2020-01-01", 5).empty
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_moneyflow_ranking_queries.py -k market_window -v`
Expected: FAIL — `AttributeError: ... has no attribute 'get_market_window'`

- [ ] **Step 3: 实现**(`data_store/moneyflow_repo.py`,`get_stock_rows` 后追加)

```python
def get_market_window(end_date: str, days: int, snapshot_top_n: int = 0) -> pd.DataFrame:
    """近 N 个交易日(<= end_date)的全市场资金流行,按 trade_date 升序。

    供吸筹检测按窗口批量扫描(约 5000 股 × N 日);days 上限 250。
    """
    end_iso = _date_key(end_date)
    n = max(1, min(int(days or 1), 250))
    if not end_iso:
        return pd.DataFrame()
    dates = [r[0] for r in get_conn().execute(
        """
        SELECT DISTINCT trade_date FROM moneyflow_dc
        WHERE top_n=? AND trade_date<=? ORDER BY trade_date DESC LIMIT ?
        """,
        (int(snapshot_top_n), end_iso, n),
    )]
    if not dates:
        return pd.DataFrame()
    placeholders = ",".join("?" for _ in dates)
    return pd.read_sql_query(
        f"""
        SELECT {','.join(_FIELDS)} FROM moneyflow_dc
        WHERE top_n=? AND trade_date IN ({placeholders})
        ORDER BY trade_date ASC
        """,
        get_conn(),
        params=(int(snapshot_top_n), *dates),
    )
```

- [ ] **Step 4: 跑测试确认通过 + 该文件全量回归**

Run: `.venv/bin/python -m pytest tests/test_moneyflow_ranking_queries.py -v`
Expected: 新增测试 PASS,既有测试不回归。

---

### Task 3: `accumulation_payload` 全市场吸筹榜服务

**Files:**
- Modify: `webui/services/quant_radar_service.py`(「对外入口」区块内、`overview` 之前插入新节)
- Test: `tests/test_quant_radar_service.py`(末尾追加)

**Interfaces:**
- Consumes: Task 1 `accumulation_detector.detect` / `WINDOWS`;Task 2 `moneyflow_repo.get_market_window`;既有 `_fetch_tencent_quotes`、`_industry_map`、`_quant_seats_window`、`_load_recent_snapshot`、`_current_trade_date_key`、`_norm_date_key`、`_iso`、`knowledge_payload`、`kv_repo`。
- Produces: `accumulation_payload(window=40, date="", force=False, market_rows_fn=None, changes_agg_fn=None, seats_fn=None, fetch_quotes=None) -> Dict`
  - payload: `{ok, window, data_date, updated_at, count, stocks, note, disclaimer}`;`stocks` 项 = detect 结果(**剔除 daily**)+ `{code, name, industry, price, change_pct}`,score 降序;
  - 辅助纯函数 `_accum_series_from_df(df) -> Dict[str, List[Dict]]`、`_accum_bonus(agg, seats, change_pct) -> Tuple[int, List[str]]`。

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_quant_radar_service.py`)

```python
# ----------------------------- 吸筹埋伏榜 -----------------------------

def _accum_market_df(codes_spec):
    """codes_spec: {ts_code: (net, close_start, close_end)} → 30日全市场窗口 DataFrame。"""
    import pandas as pd

    rows = []
    dates = [f"2026-06-{i + 1:02d}" for i in range(30)]
    for ts_code, (net, c0, c1) in codes_spec.items():
        for i, d in enumerate(dates):
            close = c0 + (c1 - c0) * i / 29
            rows.append({"trade_date": d, "ts_code": ts_code, "name": "股" + ts_code[:6],
                         "net_amount": net, "net_amount_rate": 0.6 if net > 0 else -0.3,
                         "buy_elg_amount": net * 0.8, "buy_lg_amount": 0.0,
                         "close": round(close, 3), "pct_change": 0.15,
                         "amount_unit": "万元"})
    return pd.DataFrame(rows)


def test_accumulation_payload_ranks_qualified_stocks(tmp_db):
    df = _accum_market_df({
        "600000.SH": (3000.0, 10.0, 10.5),   # 吸筹:持续流入+横盘
        "000001.SZ": (-2000.0, 10.0, 9.8),   # 派发:不入榜
        "300750.SZ": (8000.0, 50.0, 51.0),   # 吸筹且力度更大
    })
    payload = qr.accumulation_payload(window=40, market_rows_fn=lambda end, days: df,
                                      changes_agg_fn=lambda: {}, seats_fn=lambda: {},
                                      fetch_quotes=lambda codes: {})
    assert payload["ok"] is True
    assert payload["window"] == 40
    assert payload["data_date"] == "2026-06-30"
    codes = [s["code"] for s in payload["stocks"]]
    assert "000001" not in codes
    assert set(codes) == {"600000", "300750"}
    scores = [s["score"] for s in payload["stocks"]]
    assert scores == sorted(scores, reverse=True)
    top = payload["stocks"][0]
    assert "daily" not in top                      # 榜单不携带逐日序列(控体积)
    assert top["qualified"] is True
    assert top["accum_days"] == 30
    assert top["status"] in ("吸筹中", "疑似启动")
    assert payload["disclaimer"]


def test_accumulation_payload_applies_intraday_bonus_and_cap(tmp_db):
    df = _accum_market_df({"600000.SH": (3000.0, 10.0, 10.5)})
    base = qr.accumulation_payload(window=40, market_rows_fn=lambda end, days: df,
                                   changes_agg_fn=lambda: {}, seats_fn=lambda: {},
                                   fetch_quotes=lambda codes: {})
    boosted = qr.accumulation_payload(
        window=40, market_rows_fn=lambda end, days: df,
        changes_agg_fn=lambda: {"600000": {"counts": {"big_sell": 3, "sell_queue": 1},
                                           "total": 4, "bull": 0, "bear": 4}},
        seats_fn=lambda: {"600000": [{"side": "buy", "inst_name": "某量化"}]},
        fetch_quotes=lambda codes: {"600000": {"price": 10.8, "change_pct": 0.2}})
    b, s = base["stocks"][0], boosted["stocks"][0]
    assert s["score"] == min(100, b["score"] + 10)   # 盘口+5 席位+5
    assert any("压单吸筹" in r or "大单" in r for r in s["reasons"])
    assert any("量化席位" in r for r in s["reasons"])
    assert s["price"] == 10.8                        # 实时报价覆盖


def test_accum_bonus_rules():
    agg = {"counts": {"big_sell": 3, "sell_queue": 1}}
    bonus, reasons = qr._accum_bonus(agg, [], change_pct=0.2)
    assert bonus == 5 and reasons
    bonus2, _ = qr._accum_bonus(agg, [], change_pct=-3.0)   # 压单且真跌 → 不加分
    assert bonus2 == 0
    bonus3, _ = qr._accum_bonus({"counts": {"big_buy": 4}},
                                [{"side": "buy"}], change_pct=None)
    assert bonus3 == 10
    assert qr._accum_bonus({}, [{"side": "sell"}], None) == (0, [])


def test_accumulation_payload_invalid_window_falls_back(tmp_db):
    df = _accum_market_df({"600000.SH": (3000.0, 10.0, 10.5)})
    payload = qr.accumulation_payload(window=33, market_rows_fn=lambda end, days: df,
                                      changes_agg_fn=lambda: {}, seats_fn=lambda: {},
                                      fetch_quotes=lambda codes: {})
    assert payload["window"] == 40


def test_accumulation_payload_historical_reads_kv_snapshot(tmp_db):
    from data_store import kv_repo

    canned = {"ok": True, "window": 40, "data_date": "2026-07-01", "count": 1,
              "stocks": [{"code": "600000", "score": 88}], "note": "", "disclaimer": "d"}
    kv_repo.set_(qr._KV_NAMESPACE, "accum:20260701:40", canned)
    payload = qr.accumulation_payload(window=40, date="2026-07-01")
    assert payload["stocks"][0]["code"] == "600000"
    assert payload["data_date"] == "2026-07-01"


def test_accumulation_payload_empty_market_notes(tmp_db):
    import pandas as pd

    payload = qr.accumulation_payload(window=40,
                                      market_rows_fn=lambda end, days: pd.DataFrame(),
                                      changes_agg_fn=lambda: {}, seats_fn=lambda: {},
                                      fetch_quotes=lambda codes: {})
    assert payload["ok"] is True
    assert payload["stocks"] == []
    assert payload["note"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -k accum -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'accumulation_payload'`

- [ ] **Step 3: 实现**(`quant_radar_service.py`;新节插在 `# ----------------------------- 对外入口 -----------------------------` 与 `_smashed_rows` 之间)

```python
# ----------------------------- 吸筹埋伏榜(买入侧;spec 2026-07-16) -----------------------------

_ACCUM_TTL = 600
_accum_cache: Dict[str, Dict[str, Any]] = {}
_accum_lock = threading.Lock()


def _accum_series_from_df(df: Any) -> Dict[str, List[Dict[str, Any]]]:
    """get_market_window DataFrame → ``{6位代码: 升序逐日行}``(纯转换)。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
    if df is None or getattr(df, "empty", True):
        return out
    for row in df.to_dict("records"):
        code = str(row.get("ts_code") or "").split(".")[0].strip()
        if len(code) == 6 and code.isdigit():
            out.setdefault(code, []).append(row)
    return out


def _accum_bonus(agg: Optional[Dict[str, Any]],
                 seats: Iterable[Dict[str, Any]],
                 change_pct: Optional[float]) -> Tuple[int, List[str]]:
    """当日盘口/席位对吸筹判定的佐证加分(spec §2.6):压单吸筹或大买单 +5,量化席位买方 +5。"""
    counts = (agg or {}).get("counts") or {}
    bonus, reasons = 0, []
    sell_wall = counts.get("big_sell", 0) + counts.get("sell_queue", 0)
    absorbing = sell_wall >= 3 and (change_pct is None or change_pct >= -0.5)
    if absorbing or counts.get("big_buy", 0) >= 3:
        bonus += 5
        reasons.append("当日盘口大单异动佐证(压单吸筹/大笔买入)")
    if any(str(s.get("side")) == "buy" for s in seats or ()):
        bonus += 5
        reasons.append("近30日龙虎榜量化席位现身买方")
    return bonus, reasons


def accumulation_payload(window: int = 40, date: str = "", force: bool = False,
                         market_rows_fn: Optional[Callable[[str, int], Any]] = None,
                         changes_agg_fn: Optional[Callable[[], Dict[str, Any]]] = None,
                         seats_fn: Optional[Callable[[], Dict[str, List[Dict[str, Any]]]]] = None,
                         fetch_quotes: Optional[Callable[[List[str]], Dict[str, Dict[str, Any]]]] = None,
                         ) -> Dict[str, Any]:
    """吸筹埋伏榜:全市场扫描主力持续净流入且股价横盘的疑似吸筹股(买入埋伏侧)。

    数据源 ``moneyflow_dc`` 本地库(不发网络取历史);当日增强 = 腾讯实时报价覆盖 +
    行业映射 + 盘口/席位佐证加分。传 ``date`` 且非当前交易日 → kv 快照优先,缺则
    as-of 重算(纯本地)。``*_fn`` 参数供离线测试注入(注入即视为离线,不发网络)。
    """
    from analysis import accumulation_detector as det

    try:
        window = int(window)
    except (TypeError, ValueError):
        window = 40
    if window not in det.WINDOWS:
        window = 40
    requested = _norm_date_key(date)
    current_key = _current_trade_date_key()
    historical = bool(requested and requested != current_key)
    injected = any((market_rows_fn, changes_agg_fn, seats_fn, fetch_quotes))
    cache_key = f"{window}:{requested or current_key}"
    if not injected and not force:
        with _accum_lock:
            hit = _accum_cache.get(cache_key)
            if hit and time.time() - hit["ts"] < _ACCUM_TTL:
                return hit["payload"]
    if historical and not injected:
        try:
            from data_store import kv_repo

            snap = kv_repo.get(_KV_NAMESPACE, f"accum:{requested}:{window}")
            if snap and snap[0]:
                return snap[0]
        except Exception:
            pass

    end_iso = _iso(requested) if requested else _dt.date.today().isoformat()
    if market_rows_fn is not None:
        df = market_rows_fn(end_iso, window)
    else:
        from data_store import moneyflow_repo

        df = moneyflow_repo.get_market_window(end_iso, window)
    series = _accum_series_from_df(df)
    data_date = max((rows[-1].get("trade_date") for rows in series.values()),
                    default="") if series else ""

    items: List[Dict[str, Any]] = []
    for code, rows in series.items():
        result = det.detect(rows, window=window)
        if not result or not result.get("qualified"):
            continue
        last = rows[-1]
        items.append({"code": code, "name": str(last.get("name") or ""), "industry": "",
                      "price": _num(last.get("close")), "change_pct": _num(last.get("pct_change")),
                      **{k: v for k, v in result.items() if k != "daily"}})

    if items and not historical:  # 当日增强:实时报价 + 行业 + 佐证加分
        codes = [i["code"] for i in items]
        quotes = (fetch_quotes(codes) if fetch_quotes
                  else ({} if injected
                        else _with_deadline(15, _fetch_tencent_quotes, codes) or {}))
        industry = {} if injected else _industry_map()
        if changes_agg_fn is not None:
            changes_agg = changes_agg_fn() or {}
        else:
            _d, snap = _load_recent_snapshot([current_key])
            changes_agg = (snap or {}).get("changes_agg") or {}
        seats_map = (seats_fn() if seats_fn is not None
                     else ({} if injected else _quant_seats_window(30)))
        for item in items:
            quote = quotes.get(item["code"]) or {}
            for key in ("price", "change_pct"):
                if quote.get(key) is not None:
                    item[key] = quote[key]
            if not item["industry"]:
                item["industry"] = industry.get(item["code"]) or ""
            bonus, extra = _accum_bonus(changes_agg.get(item["code"]),
                                        seats_map.get(item["code"]) or [],
                                        item.get("change_pct"))
            if bonus:
                item["score"] = min(100, (item.get("score") or 0) + bonus)
                item["reasons"] = list(item.get("reasons") or []) + extra

    items.sort(key=lambda x: (-(x.get("score") or 0), -(x.get("accum_ratio") or 0)))
    payload = {
        "ok": True, "window": window, "data_date": str(data_date or ""),
        "updated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "count": len(items), "stocks": items,
        "note": "" if items else "窗口内无满足吸筹判定的股票(或本地资金流历史不足,可先运行资金榜单回填)",
        "disclaimer": knowledge_payload()["disclaimer"],
    }
    if not injected:
        if not historical and items:
            try:
                from data_store import kv_repo

                kv_repo.set_(_KV_NAMESPACE, f"accum:{current_key}:{window}", payload)
            except Exception:
                pass
        with _accum_lock:
            _accum_cache[cache_key] = {"ts": time.time(), "payload": payload}
    return payload
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -k accum -v`
Expected: 全部 PASS。注意 `test_accumulation_payload_historical_reads_kv_snapshot` 不注入 fn(走 kv 路径),其 kv key 日期 `20260701` 必须早于当前交易日(2026-07 之后运行天然成立)。

---

### Task 4: `stock_analysis` 个股吸筹区块

**Files:**
- Modify: `webui/services/quant_radar_service.py`(`stock_analysis` 函数体内)
- Test: `tests/test_quant_radar_service.py`(末尾追加)

**Interfaces:**
- Consumes: Task 1 `detect`;既有 `moneyflow_repo.get_stock_rows`(倒序返回,detect 内部排序兜底)。
- Produces: `stock_analysis` payload 新增 `"accumulation"` 键 —— detect 完整结果(**含 daily**),数据不足时为 None 且 `notes` 追加提示。

- [ ] **Step 1: 写失败测试**

```python
def test_stock_analysis_includes_accumulation_block(tmp_db):
    from data_store import moneyflow_repo

    moneyflow_repo.upsert_df(_accum_market_df({"600000.SH": (3000.0, 10.0, 10.5)}), top_n=0)
    payload = qr.stock_analysis("600000",
                                kline_fetcher=lambda code, limit: [],
                                fetch_changes=lambda: [])
    accum = payload["accumulation"]
    assert accum is not None
    assert accum["qualified"] is True
    assert accum["accum_days"] == 30
    assert accum["daily"] and accum["daily"][0]["date"] == "2026-06-01"


def test_stock_analysis_accumulation_none_without_flow_history(tmp_db):
    payload = qr.stock_analysis("300999",
                                kline_fetcher=lambda code, limit: [],
                                fetch_changes=lambda: [])
    assert payload["accumulation"] is None
    assert any("吸筹" in n for n in payload["notes"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -k "accumulation_block or without_flow_history" -v`
Expected: FAIL — `KeyError: 'accumulation'`

- [ ] **Step 3: 实现**

`stock_analysis` 内、`history` 读取块(`history: List[Dict[str, Any]] = []`)之前插入:

```python
    accumulation: Optional[Dict[str, Any]] = None
    try:
        from analysis import accumulation_detector as _accum_det
        from data_store import moneyflow_repo

        _end = _dt.date.today()
        _start = _end - _dt.timedelta(days=120)   # 40交易日 ≈ 58自然日,留双倍余量
        _df = moneyflow_repo.get_stock_rows(code, _start.isoformat(), _end.isoformat(),
                                            snapshot_top_n=0)
        if _df is not None and not getattr(_df, "empty", True):
            accumulation = _accum_det.detect(_df.to_dict("records"), window=40)
    except Exception:
        accumulation = None
    if accumulation is None:
        notes.append("吸筹分析暂缺(本地资金流历史不足 12 个交易日)")
```

返回 dict 中 `"flow": flow,` 之后加一行:

```python
        "accumulation": accumulation,
```

- [ ] **Step 4: 跑本文件全量回归**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -v`
Expected: 新旧全部 PASS(`test_stock_analysis_degrades_without_any_data` 等既有用例对 notes 只断言非空,不受新增提示影响)。

---

### Task 5: API 路由 `/api/quant-radar/accumulation`

**Files:**
- Modify: `webui/robyn_app.py`(`quant_radar_stock` 路由之后插入)
- Test: `tests/test_quant_radar_accumulation_api.py`(新建;fixture 套路照抄 `tests/test_open_url_endpoint.py`)

**Interfaces:**
- Consumes: Task 3 `quant_radar_service.accumulation_payload(window, date, force)`。
- Produces: `GET /api/quant-radar/accumulation?window=40&date=&refresh=` → payload JSON。

- [ ] **Step 1: 写失败测试**

```python
"""吸筹埋伏榜 API 接线测试:参数透传与非法 window 回退(payload 打桩,不建市场数据)。"""

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


def test_accumulation_route_passes_params(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    calls = []

    def fake_payload(window=40, date="", force=False, **kw):
        calls.append({"window": window, "date": date, "force": force})
        return {"ok": True, "window": window, "count": 0, "stocks": [],
                "data_date": "", "note": "", "disclaimer": "d"}

    monkeypatch.setattr(robyn_module.quant_radar_service,
                        "accumulation_payload", fake_payload)
    with TestClient(robyn_module.app) as client:
        resp = client.get("/api/quant-radar/accumulation?window=20&date=2026-07-01&refresh=1")
        resp_bad = client.get("/api/quant-radar/accumulation?window=999")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert calls[0] == {"window": 20, "date": "2026-07-01", "force": True}
    assert resp_bad.status_code == 200
    assert calls[1]["window"] == 40      # 非法 window 回退
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_accumulation_api.py -v`
Expected: FAIL — 404(路由不存在;robyn TestClient 对未注册路径返回 404)或 `calls` 为空。

- [ ] **Step 3: 实现路由**(`webui/robyn_app.py`,`quant_radar_stock` 之后)

```python
@_native_get("/api/quant-radar/accumulation")
def quant_radar_accumulation(request: Request) -> Response:
    """吸筹埋伏榜:主力持续净流入+量价背离的疑似吸筹股(``?window=20/40/60&date=&refresh=1``)。

    date 留空 = 最新交易日(实时增强);传历史日期走 kv 快照/本地 as-of 重算,不发网络。
    """
    window = webui_core._safe_int(_query_value(request, "window"), 40,
                                  minimum=20, maximum=60) or 40
    if window not in (20, 40, 60):
        window = 40
    date = (_query_value(request, "date", "") or "").strip()
    force = str(_query_value(request, "refresh", "") or "").lower() in {"1", "true", "yes"}
    return _json_response(quant_radar_service.accumulation_payload(
        window=window, date=date, force=force))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_accumulation_api.py -v`
Expected: PASS。

---

### Task 6: 前端 —— 吸筹埋伏榜面板 + 个股吸筹区块

**Files:**
- Modify: `webui/templates/desktop.html`(quantRadarSection 内,「量化活跃股票榜」panel 之后、`quantStockPanel` 之前)
- Modify: `webui/static/kronos_desktop_app.js`(**仅文件末尾追加**,不动压缩区)
- Modify: `webui/static/kronos_desktop.css`(末尾追加)
- Test: `tests/test_quant_radar_service.py` 的 `test_desktop_template_has_quant_tab`(追加断言)+ 新增 JS 挂钩断言测试

**Interfaces:**
- Consumes: Task 5 API;JS 既有顶层助手 `$`, `fetchJson`, `html`, `empty`, `showToast`, `quantState`, `quantPageState`, `quantPageSlice`, `quantPagerHtml`, `quantBindPager`, `quantAnalyzeStock`, `quantNum`;既有顶层函数声明 `renderQuantRadar`、`quantStockDetailHtml`(顶层 `function` 声明绑定可重赋值,末尾包装后压缩区内的调用点自动走新实现)。
- Produces: DOM 节点 `#quantAccumTable` `#quantAccumMeta` `#quantAccumWindows`;JS 函数 `loadQuantAccum` `renderQuantAccum` `quantAccumDetailHtml` `quantAccumState`。

- [ ] **Step 1: 写失败测试**(修改 `test_desktop_template_has_quant_tab`,并在其后追加新测试)

`test_desktop_template_has_quant_tab` 末尾追加断言:

```python
    # 吸筹埋伏榜挂载点与窗口切换
    assert 'quantAccumTable' in html
    assert 'quantAccumWindows' in html
    assert 'data-accum-win="40"' in html
```

新测试:

```python
def test_desktop_js_wires_accumulation_panel():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "webui" / "static"
          / "kronos_desktop_app.js").read_text(encoding="utf-8")
    assert "/api/quant-radar/accumulation" in js
    assert "function loadQuantAccum" in js
    assert "function renderQuantAccum" in js
    assert "function quantAccumDetailHtml" in js
    # 挂钩:总览渲染后刷新吸筹榜;个股深评追加吸筹区块
    assert "renderQuantRadar=(" in js.replace(" ", "")
    assert "quantStockDetailHtml=(" in js.replace(" ", "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -k "desktop_template or desktop_js" -v`
Expected: FAIL(两处断言均未满足)。

- [ ] **Step 3: desktop.html 插入面板**

锚点:`<div class="capital-table-wrap" id="quantStocksTable"></div>` 所在 panel 的关闭 `</div>` 之后、`<div class="panel" id="quantStockPanel" hidden>` 之前,插入:

```html
            <div class="panel">
              <div class="panel-header">
                <h2 class="panel-title">吸筹埋伏榜 · 主力持续吸筹</h2>
                <div class="actions" id="quantAccumWindows">
                  <button class="button secondary compact" type="button" data-accum-win="20">20日</button>
                  <button class="button compact" type="button" data-accum-win="40">40日</button>
                  <button class="button secondary compact" type="button" data-accum-win="60">60日</button>
                </div>
                <span class="panel-meta" id="quantAccumMeta">--</span>
              </div>
              <div class="capital-table-wrap" id="quantAccumTable"></div>
              <p class="panel-meta control-help">吸筹=窗口内主力资金持续净流入且股价横盘(±15%),公开数据代理指标、「疑似」口径,不构成投资建议;点击行查看个股量化行为深评。</p>
            </div>
```

- [ ] **Step 4: kronos_desktop_app.js 末尾追加**(整块追加,前面留一个换行;不改压缩区任何字节)

```js

// ---------------- 吸筹埋伏榜(主力持续净流入+量价背离;spec 2026-07-16) ----------------
function quantAccumState(){const t=quantState();return t.accum||(t.accum={window:40,loading:false,data:null}),t.accum}
async function loadQuantAccum(force){
  const st=quantAccumState(),wrap=$("#quantAccumTable");
  if(!wrap||st.loading)return;
  st.loading=true;
  if(!st.data)empty(wrap,"加载中…");
  try{
    const qs=["window="+st.window],view=quantState().viewDate;
    if(view)qs.push("date="+encodeURIComponent(view));
    if(force)qs.push("refresh=1");
    st.data=await fetchJson("/api/quant-radar/accumulation?"+qs.join("&"));
    renderQuantAccum();
  }catch(e){empty(wrap,"加载失败: "+e.message)}
  finally{st.loading=false}
}
function renderQuantAccum(){
  const st=quantAccumState(),wrap=$("#quantAccumTable"),meta=$("#quantAccumMeta");
  if(!wrap)return;
  document.querySelectorAll('#quantAccumWindows [data-accum-win]').forEach(b=>{
    b.classList.toggle("secondary",Number(b.dataset.accumWin)!==st.window);
  });
  const d=st.data;
  if(!d)return;
  if(meta)meta.textContent=`${d.count||0} 只 · 窗口${d.window}日 · 数据截至 ${d.data_date||"--"}`;
  const rows=d.stocks||[];
  if(!rows.length)return void empty(wrap,d.note||"暂无满足吸筹判定的股票");
  const {page,slice}=quantPageSlice(rows,"accum",15);
  wrap.innerHTML=`<table class="capital-table"><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>现价</th><th>涨跌%</th><th>埋伏评分</th><th>吸筹天数</th><th>最长连续</th><th>吸筹跨度</th><th>累计吸筹(亿)</th><th>日均净流率%</th><th>窗口涨幅%</th><th>状态</th></tr></thead><tbody>${slice.map(r=>`<tr class="quant-accum-row" data-accum-code="${html(r.code)}" title="${html((r.reasons||[]).join("；"))}"><td>${html(r.code)}</td><td>${html(r.name||"--")}</td><td>${html(r.industry||"--")}</td><td>${quantNum(r.price,2)}</td><td>${quantNum(r.change_pct,2)}</td><td><b>${r.score}</b></td><td>${r.accum_days}(${Math.round((r.accum_ratio||0)*100)}%)</td><td>${r.max_streak}天</td><td>${r.span_days}日</td><td>${quantNum((r.total_net_wan||0)/1e4,2)}</td><td>${quantNum(r.avg_rate,2)}</td><td>${quantNum(r.window_pct_chg,1)}</td><td><span class="quant-type-tag ${r.status==="疑似启动"?"hot":""}">${html(r.status||"--")}</span></td></tr>`).join("")}</tbody></table>${quantPagerHtml("accum",rows.length,page,15)}`;
  quantBindPager(wrap,"accum",renderQuantAccum);
  wrap.querySelectorAll("[data-accum-code]").forEach(tr=>tr.addEventListener("click",()=>quantAnalyzeStock(tr.dataset.accumCode)));
}
function quantAccumDetailHtml(a){
  if(!a)return"";
  const bars=(a.daily||[]).slice(-40),maxAbs=Math.max(1,...bars.map(x=>Math.abs(x.net_wan||0)));
  const chart=bars.length?`<div class="quant-accum-chart">${bars.map(x=>`<span class="quant-accum-bar ${(x.net_wan||0)>=0?"in":"out"}" style="height:${Math.max(4,Math.round(Math.abs(x.net_wan||0)/maxAbs*46))}px" title="${html(x.date)} 主力净流入 ${quantNum(x.net_wan,0)} 万(当日 ${quantNum(x.pct,2)}%)"></span>`).join("")}</div><p class="muted">近${bars.length}个交易日主力净流入(红=流入 绿=流出,悬停看明细)</p>`:"";
  const head=a.qualified
    ?`<span class="quant-type-tag hot">${html(a.status||"吸筹中")}</span><b class="quant-activity-big">${a.score}</b><span class="muted">埋伏评分(0-100,${a.window}日窗口)</span>`
    :`<span class="quant-type-tag">未达吸筹判定(${a.window}日窗口)</span>`;
  return`<p class="quant-know-sub">吸筹埋伏分析</p><div class="quant-detail-head">${head}</div><div class="quant-badges"><span class="quant-type-tag">吸筹 ${a.accum_days}/${a.coverage_days} 天(${Math.round((a.accum_ratio||0)*100)}%)</span><span class="quant-type-tag">最长连续 ${a.max_streak} 天</span><span class="quant-type-tag">跨度 ${a.span_days} 交易日</span><span class="quant-type-tag">累计 ${quantNum((a.total_net_wan||0)/1e4,2)} 亿</span><span class="quant-type-tag">日均净流率 ${quantNum(a.avg_rate,2)}%</span><span class="quant-type-tag">窗口涨幅 ${quantNum(a.window_pct_chg,1)}%</span>${a.elg_share!=null?`<span class="quant-type-tag">超大+大单占比 ${Math.round(a.elg_share*100)}%</span>`:""}</div>${(a.reasons||[]).map(t=>`<div class="quant-reason">· ${html(t)}</div>`).join("")}${chart}`;
}
document.querySelectorAll('#quantAccumWindows [data-accum-win]').forEach(b=>b.addEventListener("click",()=>{
  const st=quantAccumState();
  st.window=Number(b.dataset.accumWin)||40;st.data=null;
  quantPageState().pages.accum=1;
  loadQuantAccum(true).catch(()=>{});
}));
// 挂钩既有渲染链:总览每次渲染(含切换回看日期)后同步刷新吸筹榜;个股深评末尾追加吸筹区块。
// 顶层 function 声明绑定可重赋值,压缩区内的调用点自动走包装后的实现。
renderQuantRadar=(orig=>function(){orig();loadQuantAccum().catch(()=>{})})(renderQuantRadar);
quantStockDetailHtml=(orig=>function(t){return orig(t)+quantAccumDetailHtml(t&&t.accumulation)})(quantStockDetailHtml);
```

- [ ] **Step 5: kronos_desktop.css 末尾追加**

```css

/* 吸筹埋伏榜(2026-07-16) */
.quant-accum-row{cursor:pointer}
.quant-accum-chart{display:flex;align-items:flex-end;gap:2px;height:52px;margin-top:8px}
.quant-accum-bar{flex:1 1 4px;max-width:10px;min-width:2px;border-radius:2px 2px 0 0}
.quant-accum-bar.in{background:#d9544f}
.quant-accum-bar.out{background:#3aa370}
```

- [ ] **Step 6: 跑模板/JS 断言测试**

Run: `.venv/bin/python -m pytest tests/test_quant_radar_service.py -k "desktop_template or desktop_js" -v`
Expected: PASS。

- [ ] **Step 7: 端到端人工验证(dev 服务)**

1. 重启 dev 后端(Robyn 不响应 SIGTERM,须 `kill -9` 旧进程后再起;端口被占会 fail-fast):`lsof -ti:7070 | xargs kill -9 2>/dev/null; sleep 1; .venv/bin/python webui/run.py` (run_in_background)。
2. `curl -s "http://127.0.0.1:7070/api/quant-radar/accumulation?window=40" | python3 -m json.tool | head -50` — 确认 `ok:true`、`stocks` 非空(本地 moneyflow 有 164 日数据)且行含 `accum_days/span_days/total_net_wan/score`。
3. 浏览器打开资金榜单页 → 量化交易分析 tab:吸筹埋伏榜渲染、窗口 20/40/60 切换、分页、点击行打开个股深评且末尾出现「吸筹埋伏分析」区块与净流入条形图。
4. 验证后停掉后台服务。

---

### Task 7: 全量回归

**Files:** 无新改动;只跑测试。

- [ ] **Step 1: 跑本次涉及的全部测试文件**

Run: `.venv/bin/python -m pytest tests/test_accumulation_detector.py tests/test_moneyflow_ranking_queries.py tests/test_quant_radar_service.py tests/test_quant_radar_accumulation_api.py -v`
Expected: 全部 PASS。

- [ ] **Step 2: 相邻回归**

Run: `.venv/bin/python -m pytest tests/test_moneyflow_kv_snapshot.py tests/test_board_stocks_payload.py tests/test_futures_service.py -q`
Expected: 与主分支基线一致(仓库存在与本功能无关的既存失败清单,见项目记忆;若失败项不在本次触碰路径且与基线相同,记录并放行)。

- [ ] **Step 3: 汇报**

汇总:新增/修改文件清单、测试结果、端到端验证证据。**不执行任何 git 操作**,提交交由用户。

---

## Self-Review 记录

- **Spec 覆盖**:§2 检测算法→Task 1;§3.1 repo→Task 2;§3.2 payload+个股区块→Task 3/4;§3.3 API→Task 5;§4 前端三文件→Task 6;§5 测试→各任务内嵌+Task 7;§6 不做的事已在约束中体现(无新表、无 CSV)。
- **占位符**:无 TBD/TODO;所有代码步骤含完整代码。
- **类型一致性**:`detect` 返回键与 Task 3 榜单项、Task 4 payload 键、Task 6 JS 读取键(`accum_days/accum_ratio/max_streak/span_days/total_net_wan/avg_rate/elg_share/window_pct_chg/score/status/reasons/daily→net_wan`)逐一核对一致;`get_market_window(end_date, days)` 与 `market_rows_fn(end_iso, window)` 签名一致。
- **已知注意点**:Task 3 历史 kv 测试依赖「20260701 早于当前交易日」,长期成立;Task 6 依赖顶层 function 绑定可重赋值(已在 JS 文件头尾确认无 IIFE 包裹)。
