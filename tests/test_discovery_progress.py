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
    t.emit("stock_start", code="1", name="a")  # 10s 内普通事件 → 节流不写
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
    def boom(_):
        raise RuntimeError("db down")

    t = DiscoveryProgressTracker(writer=boom, max_workers=2, now=lambda: 0.0, min_interval=0.0)
    t.emit("stage_start", stage="regime")  # 不应抛
    t.finalize(ok=False)


def test_runner_bridges_progress_to_job_store(tmp_path, monkeypatch):
    """伪造 OpportunityDiscovery:只发埋点事件;断言 progress 落入 job 行并终态 100%。"""
    import importlib
    import sys
    import time as _t
    import types

    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_DISABLE_PATTERN_AUTOREFRESH", "1")
    monkeypatch.setenv("KRONOS_DISABLE_QUANT_RADAR_AUTOSAVE", "1")
    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")

    class FakeDiscovery:
        def __init__(self, max_workers=10, progress_hook=None):
            self.hook = progress_hook
            self.report_generator = types.SimpleNamespace(latest_top_report_path="")

        def run(self, limit=100, test_codes=None, source="multi"):
            self.hook("stage_start", stage="candidates")
            self.hook("stage_done", stage="candidates", detail="2只")
            self.hook("stage_start", stage="analyze")
            self.hook("analyze_total", total=2)
            for c in ("600977", "000001"):
                self.hook("stock_start", code=c, name="x")
                self.hook("stock_done", code=c, ok=True)
            self.hook("stage_done", stage="analyze")
            return ""

    fake_mod = types.SimpleNamespace(OpportunityDiscovery=FakeDiscovery)
    monkeypatch.setitem(sys.modules, "scripts.run_opportunity_discovery", fake_mod)

    job = core.JOB_SERVICE.start(
        "opportunity_discovery", {"limit": 5, "workers": 2}, core._run_opportunity_job
    )
    row = None
    for _ in range(200):
        row = core.JOB_STORE.get(job["id"])
        if row and row["status"] in ("finished", "failed"):
            break
        _t.sleep(0.05)
    assert row is not None and row["status"] == "finished", (row or {}).get("error")
    prog = row["progress"]
    assert prog and prog["v"] == 1
    assert prog["percent"] == 100.0
    by_key = {s["key"]: s for s in prog["stages"]}
    assert by_key["analyze"]["done"] == 2
    assert by_key["candidates"]["status"] == "done"
    sys.modules.pop("webui.core", None)
