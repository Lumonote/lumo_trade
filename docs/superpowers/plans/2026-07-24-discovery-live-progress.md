# 挖掘引擎直播页(discovery_live)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline)。本项目铁律:**永不执行 git 写操作**——计划里没有 commit 步骤,写完停在文件系统层。

**Goal:** 投资机会挖掘新增实时直播页:结构化 progress(JobStore 新列)+ 管线埋点 + 纯 CSS/SVG 多智能体特效前端。

**Architecture:** OpportunityDiscovery 埋点(progress_hook)→ DiscoveryProgressTracker 纯聚合(节流)→ JobStore.progress 列 → 既有 /api/jobs/:id 轮询 → desktop 新页 IIFE 渲染。

**Tech Stack:** Python/Robyn/SQLite;前端零依赖(压缩 JS 尾追加 IIFE + 模板块内 scoped CSS)。

**Spec:** docs/superpowers/specs/2026-07-24-discovery-live-progress-design.md

---

### Task 1: JobStore 增加 progress 列(含存量库迁移)

**Files:** Modify `webui/services/job_store.py`;Test `tests/test_job_store.py`

- [ ] 1.1 失败测试(追加到 tests/test_job_store.py;沿用该文件既有 fixture 风格):

```python
def test_progress_roundtrip_and_migration(tmp_path):
    import sqlite3
    from webui.services.job_store import JobStore
    db = tmp_path / "jobs.sqlite"
    # 先造一个"旧 schema"库(无 progress_json),验证 ALTER 迁移
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE webui_jobs (id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL,"
        " created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, params_json TEXT NOT NULL,"
        " logs_json TEXT NOT NULL, result_json TEXT, error TEXT, updated_at TEXT NOT NULL)"
    )
    conn.commit(); conn.close()
    store = JobStore(db)
    store.create({"id": "j1", "type": "opportunity_discovery"})
    updated = store.update("j1", progress={"v": 1, "percent": 42.5})
    assert updated["progress"] == {"v": 1, "percent": 42.5}
    assert store.get("j1")["progress"]["percent"] == 42.5
    # 无 progress 的旧行读出为 None
    store.create({"id": "j2", "type": "x"})
    assert store.get("j2")["progress"] is None
```

- [ ] 1.2 跑:`pytest tests/test_job_store.py::test_progress_roundtrip_and_migration -q` → FAIL(no such column / KeyError)
- [ ] 1.3 实现:`_init_schema` 建表语句加 `progress_json TEXT`(error 之后);建表后追加迁移 `try: conn.execute("ALTER TABLE webui_jobs ADD COLUMN progress_json TEXT") except sqlite3.OperationalError: pass`;`create` 的 INSERT 列与值各加 progress_json(`row.setdefault("progress", None)`);`update` allowed_fields 加 `"progress"` 且 elif 分支序列化同 result;`_row_to_job` 加 `"progress": self._json_loads(row["progress_json"], None)`(注意旧行 row 无该键需 `row.keys()` 判断:`self._json_loads(row["progress_json"] if "progress_json" in row.keys() else None, None)`——迁移后必有列,此守卫仅防御)。
- [ ] 1.4 跑同命令 → PASS;再跑 `pytest tests/test_job_store.py -q` 全绿。

### Task 2: DiscoveryProgressTracker 纯聚合器

**Files:** Create `webui/services/discovery_progress.py`;Test `tests/test_discovery_progress.py`

- [ ] 2.1 失败测试(新文件):

```python
"""DiscoveryProgressTracker: 事件流 → progress 快照聚合的纯逻辑测试。"""
from webui.services.discovery_progress import DiscoveryProgressTracker, STAGES


def make_tracker(writes, now, workers=4, interval=0.0):
    return DiscoveryProgressTracker(
        writer=lambda p: writes.append(p), max_workers=workers,
        now=lambda: now[0], min_interval=interval,
    )


def test_stage_flow_and_percent_monotonic():
    writes, now = [], [1000.0]
    t = make_tracker(writes, now)
    t.emit("stage_start", stage="candidates")
    t.emit("candidates_source", source="heat", count=80)
    t.emit("stage_done", stage="candidates", detail="共120只")
    t.emit("stage_start", stage="analyze")
    t.emit("analyze_total", total=10)
    for i in range(10):
        code = f"60000{i}"
        t.emit("stock_start", code=code, name=f"股{i}")
        now[0] += 3
        t.emit("stock_done", code=code, ok=(i % 3 != 0))
    t.emit("stage_done", stage="analyze")
    snap = t.snapshot()
    by_key = {s["key"]: s for s in snap["stages"]}
    assert by_key["candidates"]["status"] == "done"
    assert by_key["analyze"]["status"] == "done"
    assert by_key["analyze"]["done"] == 10 and by_key["analyze"]["total"] == 10
    assert snap["counts"]["sources"] == {"heat": 80}
    assert snap["counts"]["analyzed"] == 10 and snap["counts"]["failed"] == 4
    assert snap["workers"] == []  # 全部收尾,无在途
    percents = [w["percent"] for w in writes]
    assert percents == sorted(percents)  # 单调不回退


def test_inflight_workers_tracked():
    writes, now = [], [0.0]
    t = make_tracker(writes, now)
    t.emit("stage_start", stage="analyze")
    t.emit("analyze_total", total=5)
    t.emit("stock_start", code="600977", name="浪潮信息")
    t.emit("stock_start", code="000001", name="平安银行")
    snap = t.snapshot()
    assert [w["code"] for w in snap["workers"]] == ["600977", "000001"]
    t.emit("stock_done", code="600977", ok=True)
    assert [w["code"] for w in t.snapshot()["workers"]] == ["000001"]


def test_throttle_and_stage_change_forces_write():
    writes, now = [], [0.0]
    t = DiscoveryProgressTracker(writer=lambda p: writes.append(p), max_workers=2,
                                 now=lambda: now[0], min_interval=10.0)
    t.emit("stage_start", stage="regime")     # 阶段切换 → 必写
    n1 = len(writes)
    t.emit("stage_start", stage="analyze")    # 又切换 → 必写
    t.emit("analyze_total", total=100)
    t.emit("stock_start", code="1", name="a") # 10s 内普通事件 → 节流不写
    n2 = len(writes)
    now[0] += 11
    t.emit("stock_done", code="1", ok=True)   # 超时 → 写
    assert n1 >= 1 and n2 == len(writes) - 1


def test_skip_and_finalize_and_hook_safety():
    writes, now = [], [0.0]
    t = make_tracker(writes, now)
    t.emit("stage_skip", stage="llm", detail="KRONOS_SKIP_LLM=1")
    t.emit("nonsense_event", foo=1)  # 未知事件不抛
    t.finalize(ok=True)
    snap = writes[-1]
    assert {s["key"] for s in snap["stages"]} == {k for k, _ in STAGES}
    assert snap["percent"] == 100.0
    by_key = {s["key"]: s for s in snap["stages"]}
    assert by_key["llm"]["status"] == "skipped"
    # 未启动的阶段在成功终态标记 done(best-effort 段可能静默完成)
    assert by_key["report"]["status"] in ("done", "skipped")


def test_writer_exception_swallowed():
    def boom(_): raise RuntimeError("db down")
    t = DiscoveryProgressTracker(writer=boom, max_workers=2, now=lambda: 0.0, min_interval=0.0)
    t.emit("stage_start", stage="regime")  # 不应抛
    t.finalize(ok=False)
```

- [ ] 2.2 跑:`pytest tests/test_discovery_progress.py -q` → FAIL(module 不存在)
- [ ] 2.3 实现 `webui/services/discovery_progress.py`:

```python
"""投资机会挖掘进度聚合器:埋点事件流 → 结构化 progress 快照(写入 JobStore.progress)。

纯逻辑、线程安全;writer 异常一律吞掉(进度展示绝不能影响挖掘主流程)。"""
from __future__ import annotations

import datetime
import threading

STAGES = [
    ("regime", "大盘环境"), ("candidates", "候选获取"), ("preload", "全局预载"),
    ("analyze", "并发打分"), ("funnel", "漏斗筛选"), ("llm", "LLM深度分析"),
    ("report", "报告生成"), ("persist", "结果入库"), ("backtest", "自动回测"),
]
# percent 权重:analyze 按 done/total 内部线性,其余整段到位
_WEIGHTS = {"regime": 3, "candidates": 8, "preload": 4, "analyze": 60,
            "funnel": 5, "llm": 10, "report": 5, "persist": 2, "backtest": 3}


class DiscoveryProgressTracker:
    def __init__(self, writer, max_workers, now=None, min_interval=0.6):
        import time
        self._writer = writer
        self._now = now or time.time
        self._min_interval = float(min_interval)
        self._lock = threading.RLock()
        self._last_write = 0.0
        self._max_percent = 0.0
        self.max_workers = int(max_workers)
        self._stages = {k: {"key": k, "label": lbl, "status": "pending", "detail": "",
                            "done": 0, "total": 0, "started": None, "finished": None}
                        for k, lbl in STAGES}
        self._inflight: dict[str, dict] = {}
        self._counts = {"candidates": 0, "analyzed": 0, "failed": 0, "sources": {}}
        self._current = None
        self._analyze_t0 = None

    # ---- 事件入口(线程安全;未知事件忽略) ----
    def emit(self, event, **data):
        force = False
        with self._lock:
            st = self._stages.get(str(data.get("stage") or ""))
            if event == "stage_start" and st:
                st["status"], st["started"] = "running", self._now()
                self._current = st["key"]
                if st["key"] == "analyze":
                    self._analyze_t0 = self._now()
                force = True
            elif event == "stage_done" and st:
                st["status"], st["finished"] = "done", self._now()
                if data.get("detail"):
                    st["detail"] = str(data["detail"])
                force = True
            elif event == "stage_skip" and st:
                st["status"], st["detail"] = "skipped", str(data.get("detail") or "")
                force = True
            elif event == "candidates_source":
                src = str(data.get("source") or "?")
                cnt = int(data.get("count") or 0)
                self._counts["sources"][src] = cnt
                self._stages["candidates"]["detail"] = " · ".join(
                    f"{k}:{v}" for k, v in self._counts["sources"].items())
            elif event == "candidates_total":
                self._counts["candidates"] = int(data.get("total") or 0)
            elif event == "analyze_total":
                self._stages["analyze"]["total"] = int(data.get("total") or 0)
                self._counts["candidates"] = self._counts["candidates"] or self._stages["analyze"]["total"]
            elif event == "stock_start":
                code = str(data.get("code") or "")
                if code:
                    self._inflight[code] = {"code": code, "name": str(data.get("name") or ""),
                                            "since_ts": self._now()}
            elif event == "stock_done":
                self._inflight.pop(str(data.get("code") or ""), None)
                self._stages["analyze"]["done"] += 1
                self._counts["analyzed"] += 1
                if not data.get("ok", True):
                    self._counts["failed"] += 1
            else:
                return  # 未知事件:忽略
        self._maybe_write(force=force)

    def finalize(self, ok=True):
        with self._lock:
            for st in self._stages.values():
                if ok and st["status"] in ("pending", "running"):
                    st["status"] = "done"
                elif not ok and st["status"] == "running":
                    st["status"] = "failed"
            if ok:
                self._max_percent = 100.0
        self._maybe_write(force=True)

    # ---- 快照 ----
    def snapshot(self):
        with self._lock:
            pct = self._percent_locked()
            eta = self._eta_locked()
            return {
                "v": 1,
                "current_stage": self._current,
                "percent": pct,
                "eta_seconds": eta,
                "max_workers": self.max_workers,
                "stages": [dict(self._stages[k]) for k, _ in STAGES],
                "workers": sorted(self._inflight.values(), key=lambda w: w["since_ts"]),
                "counts": {**self._counts, "sources": dict(self._counts["sources"])},
                "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            }

    def _percent_locked(self):
        acc = 0.0
        for key, weight in _WEIGHTS.items():
            st = self._stages[key]
            if st["status"] in ("done", "skipped"):
                acc += weight
            elif st["status"] == "running" and key == "analyze" and st["total"]:
                acc += weight * min(1.0, st["done"] / st["total"])
            elif st["status"] == "running":
                acc += weight * 0.5
        self._max_percent = max(self._max_percent, round(min(acc, 99.5), 1))
        return self._max_percent

    def _eta_locked(self):
        st = self._stages["analyze"]
        if st["status"] != "running" or not st["done"] or not st["total"] or not self._analyze_t0:
            return None
        rate = (self._now() - self._analyze_t0) / st["done"]
        return round(rate * (st["total"] - st["done"]), 1)

    def _maybe_write(self, force=False):
        with self._lock:
            now = self._now()
            if not force and (now - self._last_write) < self._min_interval:
                return
            self._last_write = now
            snap = self.snapshot()
        try:
            self._writer(snap)
        except Exception:  # noqa: BLE001 — 进度写出失败不影响主流程
            pass

    # OpportunityDiscovery.progress_hook 直接可调用
    __call__ = emit
```

  注意 `snapshot()` 在 `_maybe_write` 锁内调用而 snapshot 又拿锁 → RLock 可重入,OK。
- [ ] 2.4 跑 `pytest tests/test_discovery_progress.py -q` → PASS(percent 单调断言依赖 `_max_percent` 防回退——failed 计数不降 done,skip 段权重直接计入,故成立)。

### Task 3: OpportunityDiscovery 埋点

**Files:** Modify `scripts/run_opportunity_discovery.py`(`__init__` ~61、`run()` 1349-2100、`_analyze_single_stock_with_timeout` 2268)

- [ ] 3.1 `__init__(self, max_workers: int = 10, progress_hook=None)`;`self.progress_hook = progress_hook`;新增方法:

```python
    def _emit(self, event, **data):
        """进度埋点(可选)。任何异常吞掉:进度展示绝不影响挖掘主流程。"""
        hook = getattr(self, 'progress_hook', None)
        if hook is None:
            return
        try:
            hook(event, **data)
        except Exception:
            pass
```

- [ ] 3.2 `run()` 阶段边界插桩(全部一行式,不动既有逻辑):
  - 步骤0 前后:`self._emit('stage_start', stage='regime')` / `stage_done`(1366/1373 附近)
  - 步骤1 进入(1375 前)`stage_start:candidates`;multi 各子源计数处(1413/1435/1439/1443/1447)`self._emit('candidates_source', source='heat', count=len(hot_stocks))` 等;候选定稿处(1554 附近、`_preload_global_data` 调用前)`self._emit('candidates_total', total=len(hot_stocks))` + `stage_done:candidates`
  - 步骤1.5 (1557/1559):`stage_start:preload` / `stage_done`
  - 步骤2 (1562):`stage_start:analyze` + `self._emit('analyze_total', total=total_count)`;完成(1644):`stage_done:analyze`
  - 步骤3 (1649/1659):`stage_start:funnel` / `stage_done`
  - 步骤3.5 (1743):`stage_start:llm`;skip 分支(1748)`stage_skip:llm`;完成(1804 与异常 1816)`stage_done:llm`
  - 步骤4 (2000/生成后):`stage_start:report` / `stage_done`
  - 步骤4.6 (2044):`stage_start:persist` / `stage_done`
  - 步骤5 (2068 try 内/2093 后):`stage_start:backtest` / `stage_done`
- [ ] 3.3 `_analyze_single_stock_with_timeout` 开头/结尾:

```python
        code = str(hot_stock.get('code') or '')
        self._emit('stock_start', code=code, name=str(hot_stock.get('name') or ''))
        ok = False
        try:
            ...  # 既有逻辑,result 正常返回前 ok = True
        finally:
            self._emit('stock_done', code=code, ok=ok)
```

  (以既有函数体为准包裹;两个执行分支共用此函数=单点覆盖。)
- [ ] 3.4 验证不破坏 CLI:`python -c "from scripts.run_opportunity_discovery import OpportunityDiscovery; OpportunityDiscovery(max_workers=2)"` 正常;`pytest tests/test_opportunity_job_reconciliation.py -q` 仍绿。

### Task 4: runner 桥接(webui/core.py `_run_opportunity_job` 3938)

**Files:** Modify `webui/core.py:3958-3967`;Test `tests/test_discovery_progress.py` 追加 wiring 测试

- [ ] 4.1 失败测试(追加):

```python
def test_runner_bridges_progress_to_job_store(tmp_path, monkeypatch):
    """伪造 OpportunityDiscovery:只发埋点事件;断言 progress 落入 job 行。"""
    import importlib, sys, types
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")

    class FakeDiscovery:
        def __init__(self, max_workers=10, progress_hook=None):
            self.hook = progress_hook
            self.report_generator = types.SimpleNamespace(latest_top_report_path='')
        def run(self, limit=100, test_codes=None, source='multi'):
            self.hook('stage_start', stage='candidates')
            self.hook('stage_done', stage='candidates', detail='2只')
            self.hook('stage_start', stage='analyze')
            self.hook('analyze_total', total=2)
            for c in ('600977', '000001'):
                self.hook('stock_start', code=c, name='x')
                self.hook('stock_done', code=c, ok=True)
            self.hook('stage_done', stage='analyze')
            return ''

    fake_mod = types.SimpleNamespace(OpportunityDiscovery=FakeDiscovery)
    monkeypatch.setitem(sys.modules, 'scripts.run_opportunity_discovery', fake_mod)
    job = core.JOB_SERVICE.start('opportunity_discovery', {'limit': 5, 'workers': 2}, core._run_opportunity_job)
    import time as _t
    for _ in range(100):
        row = core.JOB_STORE.get(job['id'])
        if row and row['status'] in ('finished', 'failed'):
            break
        _t.sleep(0.05)
    assert row['status'] == 'finished'
    prog = row['progress']
    assert prog and prog['percent'] == 100.0
    by_key = {s['key']: s for s in prog['stages']}
    assert by_key['analyze']['done'] == 2
    sys.modules.pop("webui.core", None)
```

  (JOB_SERVICE.start 若为后台线程执行则轮询等待;若同步直接断言。以 background_jobs.py 实际行为为准微调。)
- [ ] 4.2 跑 → FAIL(progress 为 None)
- [ ] 4.3 实现:`_run_opportunity_job` 在 `try:` 内 import 后加:

```python
        from webui.services.discovery_progress import DiscoveryProgressTracker

        tracker = DiscoveryProgressTracker(
            writer=lambda p: _update_job(job_id, progress=p),
            max_workers=workers,
        )
        with _JobLogCapture(job_id, ['scripts.run_opportunity_discovery']):
            discovery = OpportunityDiscovery(max_workers=workers, progress_hook=tracker)
            ...
```

  finished 分支 `_update_job(...)` 前加 `tracker.finalize(ok=True)`;except 分支加 `tracker.finalize(ok=False)`(tracker 需在 try 外先置 None 再赋值,except 里判空)。注意 `_update_job` → JOB_SERVICE.update 需透传 progress:检查 `webui/services/background_jobs.py` 的 update 白名单,若有同样的 allowed_fields 需同步加 `progress`。
- [ ] 4.4 跑 → PASS;`pytest tests/test_background_jobs.py tests/test_analysis_jobs.py -q` 回归绿。

### Task 5: 页面注册 + 模板块

**Files:** Modify `webui/core.py:4759 DESKTOP_PAGES`(workbench 之后插入)、`webui/templates/desktop.html`(星轨块 890 前后插入新块);Test `tests/test_robyn_app.py` 追加路由测试

- [ ] 5.1 失败测试:

```python
def test_robyn_desktop_discovery_live_page(robyn_module):
    from robyn.testing import TestClient
    with TestClient(robyn_module.app) as client:
        resp = client.get("/desktop/discovery_live")
    assert resp.status_code == 200
    assert b'id="dlvRoot"' in resp.content
```

- [ ] 5.2 DESKTOP_PAGES 在 `'workbench'` 条目后加:

```python
    'discovery_live': {
        'title': '挖掘引擎',
        'subtitle': '投资机会挖掘实时直播:多智能体并行流水线、阶段进度、现场日志与结果直达',
    },
```

- [ ] 5.3 模板块(`{% if active_page == 'star_orbit' %}` 之前插入;骨架+scoped 样式,内容 JS 填充):

```html
        {% if active_page == 'discovery_live' %}
        <style>
          .dlv-wrap{display:flex;flex-direction:column;gap:14px}
          .dlv-card{background:var(--panel-bg,#141a24);border:1px solid rgba(120,150,200,.16);border-radius:12px;padding:14px}
          .dlv-rail{display:flex;align-items:center;gap:0;overflow-x:auto;padding:6px 2px}
          .dlv-node{min-width:86px;text-align:center;position:relative}
          .dlv-dot{width:34px;height:34px;border-radius:50%;margin:0 auto 6px;display:flex;align-items:center;justify-content:center;font-size:15px;background:#1d2534;border:2px solid #2d3950;color:#8fa3c8;transition:all .3s}
          .dlv-node.running .dlv-dot{border-color:#4da3ff;color:#eaf3ff;box-shadow:0 0 14px rgba(77,163,255,.55);animation:dlvPulse 1.6s ease-in-out infinite}
          .dlv-node.done .dlv-dot{border-color:#2ecc8f;color:#2ecc8f;background:rgba(46,204,143,.12)}
          .dlv-node.skipped .dlv-dot{border-color:#5a6478;color:#5a6478;opacity:.55}
          .dlv-node.failed .dlv-dot{border-color:#ff5d5d;color:#ff5d5d}
          .dlv-node small{display:block;color:#9db0d0;font-size:11px;white-space:nowrap}
          .dlv-node .dlv-detail{color:#6d7f9f;font-size:10px;max-width:110px;margin:2px auto 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
          .dlv-link{flex:1 0 34px;height:3px;min-width:24px;margin:0 2px 22px;background:#232d40;border-radius:2px;position:relative;overflow:hidden}
          .dlv-link.flow::after{content:'';position:absolute;inset:0;background:linear-gradient(90deg,transparent,#4da3ff,transparent);animation:dlvFlow 1.2s linear infinite}
          .dlv-link.done{background:rgba(46,204,143,.4)}
          @keyframes dlvFlow{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
          @keyframes dlvPulse{0%,100%{box-shadow:0 0 8px rgba(77,163,255,.35)}50%{box-shadow:0 0 20px rgba(77,163,255,.75)}}
          .dlv-mid{display:grid;grid-template-columns:minmax(220px,300px) 1fr;gap:14px}
          .dlv-ring-box{display:flex;flex-direction:column;align-items:center;gap:8px}
          .dlv-chips{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
          .dlv-chip{font-size:11px;color:#9db0d0;background:#1b2332;border:1px solid #2b374d;border-radius:10px;padding:2px 8px}
          .dlv-agents{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
          .dlv-agent{border:1px solid #263248;border-radius:10px;padding:8px 10px;background:#151c29;min-height:56px;position:relative;overflow:hidden}
          .dlv-agent.idle{opacity:.45;animation:dlvBreath 3s ease-in-out infinite}
          .dlv-agent.busy{border-color:#4da3ff}
          .dlv-agent.busy::after{content:'';position:absolute;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#4da3ff,transparent);animation:dlvScan 1.6s linear infinite}
          @keyframes dlvScan{from{top:0}to{top:100%}}
          @keyframes dlvBreath{0%,100%{opacity:.35}50%{opacity:.55}}
          .dlv-agent b{color:#eaf3ff;font-size:13px}
          .dlv-agent small{display:block;color:#8fa3c8;font-size:11px;margin-top:2px}
          .dlv-logs{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:#9db0d0;max-height:180px;overflow-y:auto;white-space:pre-wrap;line-height:1.55}
          .dlv-logs .new{color:#cfe2ff;animation:dlvIn .5s ease}
          @keyframes dlvIn{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
          .dlv-done-burst{animation:dlvPulse 1s ease 3}
          .dlv-form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
          .dlv-form select,.dlv-form input{background:#101724;border:1px solid #2b374d;border-radius:8px;color:#dfe9ff;padding:6px 8px;font-size:12px}
          .dlv-hint{color:#6d7f9f;font-size:11px}
        </style>
        <div class="dlv-wrap" id="dlvRoot">
          <div class="dlv-card" id="dlvStatusCard">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <div><b id="dlvTitle" style="color:#eaf3ff">挖掘引擎待命</b><span class="dlv-hint" id="dlvSub" style="margin-left:8px"></span></div>
              <div class="dlv-form" id="dlvStartForm">
                <select id="dlvSource"><option value="multi">多源综合</option><option value="heat">仅热度榜</option><option value="moneyflow_dc">资金流向榜</option><option value="sector_hot">热门板块</option></select>
                <input id="dlvLimit" type="number" min="5" max="500" value="100" style="width:70px" title="候选数量">
                <input id="dlvWorkers" type="number" min="1" max="32" value="10" style="width:56px" title="并发智能体数">
                <input id="dlvCodes" placeholder="指定代码,逗号分隔(可空)" style="width:190px">
                <button class="btn primary" id="dlvStartBtn">启动挖掘</button>
              </div>
            </div>
          </div>
          <div class="dlv-card"><div class="dlv-rail" id="dlvRail"></div></div>
          <div class="dlv-mid">
            <div class="dlv-card dlv-ring-box">
              <svg width="132" height="132" viewBox="0 0 132 132">
                <circle cx="66" cy="66" r="56" fill="none" stroke="#232d40" stroke-width="10"/>
                <circle id="dlvRing" cx="66" cy="66" r="56" fill="none" stroke="#4da3ff" stroke-width="10"
                        stroke-linecap="round" stroke-dasharray="351.86" stroke-dashoffset="351.86"
                        transform="rotate(-90 66 66)" style="transition:stroke-dashoffset .6s"/>
                <text id="dlvPct" x="66" y="62" text-anchor="middle" fill="#eaf3ff" font-size="22" font-weight="700">--</text>
                <text id="dlvEta" x="66" y="82" text-anchor="middle" fill="#8fa3c8" font-size="10"></text>
              </svg>
              <div class="dlv-chips" id="dlvChips"></div>
              <div class="dlv-hint" id="dlvResultBox"></div>
            </div>
            <div class="dlv-card">
              <div class="dlv-hint" style="margin-bottom:8px">并行智能体现场 <span id="dlvAgentStat"></span></div>
              <div class="dlv-agents" id="dlvAgents"></div>
            </div>
          </div>
          <div class="dlv-card"><div class="dlv-hint" style="margin-bottom:6px">现场日志</div><div class="dlv-logs" id="dlvLogs">等待任务…</div></div>
        </div>
        {% endif %}
```

- [ ] 5.4 跑路由测试 → PASS。侧栏是否数据驱动自动出现:检查 desktop.html 侧栏循环(若手写菜单需按 star_orbit 先例加一个 `<a>` 项,data-short「掘」)。

### Task 6: 前端 IIFE(kronos_desktop_app.js 尾部追加)

**Files:** Modify `webui/static/kronos_desktop_app.js`(仅尾部追加,前置 `;`)

- [ ] 6.1 追加(轮询/渲染;复用全局 esc?——压缩文件里工具名不可靠,自带小工具):

```js
;(function(){
  if(document.body.dataset.page!=="discovery_live")return;
  const $id=(i)=>document.getElementById(i);
  const esc=(s)=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const STAGE_ICONS={regime:"🌐",candidates:"📡",preload:"🧰",analyze:"🤖",funnel:"🫙",llm:"🧠",report:"📝",persist:"💾",backtest:"📈"};
  let jobId=null,timer=null,lastLogCount=0,doneFlash=false;
  const CIRC=351.86;
  function stageNode(s,idx,arr){
    const cls=s.status==="running"?"running":s.status==="done"?"done":s.status==="skipped"?"skipped":s.status==="failed"?"failed":"";
    const link=idx<arr.length-1?`<div class="dlv-link ${s.status==="done"?"done":s.status==="running"?"flow":""}"></div>`:"";
    const count=s.total?` ${s.done}/${s.total}`:"";
    return `<div class="dlv-node ${cls}"><div class="dlv-dot">${STAGE_ICONS[s.key]||"•"}</div><small>${esc(s.label)}${count}</small><div class="dlv-detail" title="${esc(s.detail)}">${esc(s.detail)}</div></div>${link}`;
  }
  function render(job){
    const p=job.progress;
    const st=job.status;
    $id("dlvTitle").textContent=st==="running"?"挖掘进行中":st==="finished"?"挖掘完成":st==="failed"?"挖掘失败":st==="queued"?"排队中":"挖掘引擎待命";
    $id("dlvSub").textContent=(job.params&&`来源 ${job.params.source||"multi"} · 条数 ${job.params.limit||"-"} · 智能体 ${job.params.workers||"-"}`)||"";
    $id("dlvStartForm").style.display=(st==="running"||st==="queued")?"none":"flex";
    const logs=(job.logs||[]).slice(-12);
    const logBox=$id("dlvLogs");
    if(logs.length!==lastLogCount){lastLogCount=logs.length;
      logBox.innerHTML=logs.map((l,i)=>`<div class="${i===logs.length-1?"new":""}">${esc(typeof l==="string"?l:(l&&l.message)||"")}</div>`).join("")||"…";
      logBox.scrollTop=logBox.scrollHeight;}
    if(!p){ $id("dlvRail").innerHTML='<span class="dlv-hint">此任务无结构化进度(历史任务),以上为日志回放。</span>';renderAgents([],0);setRing(st==="finished"?100:null,null);renderResult(job);return; }
    const nodes=p.stages.map(stageNode).join("");
    $id("dlvRail").innerHTML=nodes;
    setRing(p.percent,p.eta_seconds);
    const chips=[];const c=p.counts||{};
    if(c.candidates)chips.push(`候选 ${c.candidates}`);
    Object.entries(c.sources||{}).forEach(([k,v])=>chips.push(`${k} ${v}`));
    if(c.analyzed)chips.push(`已析 ${c.analyzed}`);
    if(c.failed)chips.push(`失败 ${c.failed}`);
    $id("dlvChips").innerHTML=chips.map(x=>`<span class="dlv-chip">${esc(x)}</span>`).join("");
    renderAgents(p.workers||[],p.max_workers||0);
    renderResult(job);
    if(st==="finished"&&!doneFlash){doneFlash=true;$id("dlvStatusCard").classList.add("dlv-done-burst");}
  }
  function renderAgents(workers,max){
    const nowS=Date.now()/1000;
    const busy=workers.map(w=>`<div class="dlv-agent busy"><b>${esc(w.code)}</b> <small>${esc(w.name)} · ${Math.max(0,Math.round(nowS-(w.since_ts||nowS)))}s</small></div>`);
    const idleCount=Math.max(0,(max||0)-workers.length);
    const idle=Array.from({length:idleCount},(_,i)=>`<div class="dlv-agent idle"><b>Agent ${workers.length+i+1}</b><small>待命</small></div>`);
    $id("dlvAgents").innerHTML=busy.concat(idle).join("")||'<span class="dlv-hint">尚未进入并发打分阶段</span>';
    $id("dlvAgentStat").textContent=max?`(${workers.length}/${max} 在岗)`:"";
  }
  function setRing(pct,eta){
    $id("dlvPct").textContent=pct==null?"--":`${Math.round(pct)}%`;
    $id("dlvRing").style.strokeDashoffset=pct==null?CIRC:String(CIRC*(1-Math.min(100,pct)/100));
    $id("dlvEta").textContent=eta?`约剩 ${eta>90?Math.round(eta/60)+" 分":Math.round(eta)+" 秒"}`:"";
  }
  function renderResult(job){
    const r=job.result||{};const box=$id("dlvResultBox");
    if(job.status==="finished"&&(r.top_report_url||r.report_url)){
      box.innerHTML=`<a class="btn" href="${esc(r.top_report_url||r.report_url)}" target="_blank">打开 Top 报告</a> <a class="btn" href="/desktop/workbench">工作台复盘</a>`;
    }else if(job.status==="failed"){box.innerHTML=`<span style="color:#ff5d5d">${esc(job.error||"任务失败")}</span>`;}
    else box.innerHTML="";
  }
  async function tick(){
    try{
      if(!jobId){
        const list=(await(await fetch("/api/jobs")).json());
        const jobs=Array.isArray(list)?list:(list.jobs||[]);
        const mine=jobs.filter(j=>j.type==="opportunity_discovery");
        const active=mine.find(j=>j.status==="running"||j.status==="queued")||mine[0];
        if(!active){$id("dlvLogs").textContent="暂无挖掘任务:用上方「启动挖掘」开始,或在分析工作台发起。";return;}
        jobId=active.id;
      }
      const data=await(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`)).json();
      const job=data.job||data;
      render(job);
      if(job.status==="finished"||job.status==="failed"){clearInterval(timer);timer=null;}
    }catch(e){/* 保持上一帧,下轮重试 */}
  }
  function startPolling(){if(timer)clearInterval(timer);lastLogCount=0;doneFlash=false;timer=setInterval(()=>{if(!document.hidden)tick();},1500);tick();}
  $id("dlvStartBtn").addEventListener("click",async()=>{
    const codes=($id("dlvCodes").value||"").split(/[,，\s]+/).map(s=>s.trim()).filter(Boolean);
    const body={source:$id("dlvSource").value,limit:Number($id("dlvLimit").value)||100,workers:Number($id("dlvWorkers").value)||10};
    if(codes.length)body.stock_codes=codes;
    try{
      const resp=await(await fetch("/api/opportunity-discovery/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
      jobId=(resp.job&&resp.job.id)||resp.job_id||null;
      startPolling();
    }catch(e){$id("dlvLogs").textContent="启动失败:"+e;}
  });
  startPolling();
})();
```

  (启动响应字段以 robyn_app.py:717 实际返回为准核对;`/api/jobs` 列表返回形状以 `_get_job_snapshot` 实际为准核对后微调。)
- [ ] 6.2 语法验证:`node --check webui/static/kronos_desktop_app.js` → 无输出即通过。

### Task 7: 实证(e2e)

- [ ] 7.1 `pytest tests/test_job_store.py tests/test_discovery_progress.py tests/test_background_jobs.py tests/test_analysis_jobs.py tests/test_robyn_app.py -q` 全绿(仅既存 template_static 失败例外)。
- [ ] 7.2 dev 服起(遵循 Robyn 重启铁律 kill -9):`KRONOS_PORT=7071 KRONOS_SKIP_LLM=1 KRONOS_DISABLE_PATTERN_AUTOREFRESH=1 .venv/bin/python webui/app.py`(run_in_background);`curl /desktop/discovery_live` 含 dlvRoot;POST start(stock_codes=600977,000001, workers=2)→ 轮询 /api/jobs/:id 观测 progress:candidates→analyze(workers 现场非空)→…→finished percent=100。
- [ ] 7.3 杀干净 dev 服;报告 + 记忆沉淀(打包 App 需重打包提醒)。

## Self-Review
- Spec 覆盖:JobStore 列(T1)/Tracker(T2)/埋点(T3)/桥接(T4)/页面(T5)/特效 JS(T6)/降级与空态(T6 render 无 progress 分支+空态文案)/e2e(T7) ✅
- 无占位符;类型/字段名前后一致(stage keys、workers[].since_ts、counts.sources)✅
- 与工作约定一致:无 git 步骤;progress 存 SQLite ✅
