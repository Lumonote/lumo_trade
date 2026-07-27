import time

from webui.services.background_jobs import BackgroundJobService
from webui.services.job_store import JobStore


def test_create_update_snapshot_and_logs(tmp_path):
    service = BackgroundJobService(JobStore(tmp_path / "jobs.sqlite", max_logs=2))

    job = service.create("batch_analysis", {"stock_codes": ["600000"]})
    assert job["type"] == "batch_analysis"
    assert job["status"] == "queued"

    service.append_log(job["id"], "first")
    service.append_log(job["id"], "second")
    service.append_log(job["id"], "third")
    service.update(job["id"], status="finished", result={"rows": 1})

    snapshot = service.snapshot(job["id"])
    assert snapshot["status"] == "finished"
    assert snapshot["result"] == {"rows": 1}
    assert len(snapshot["logs"]) == 2
    assert snapshot["logs"][0].endswith("second")
    assert snapshot["logs"][-1].endswith("third")


def test_start_runs_worker(tmp_path):
    service = BackgroundJobService(JobStore(tmp_path / "jobs.sqlite"))

    def worker(job_id, params):
        service.update(job_id, status="finished", result={"value": params["value"]})

    job = service.start("sample", {"value": 7}, worker)

    for _ in range(100):
        snapshot = service.snapshot(job["id"])
        if snapshot["status"] == "finished":
            break
        time.sleep(0.01)

    assert service.snapshot(job["id"])["result"] == {"value": 7}


def test_mark_interrupted_jobs_closes_stale_active_jobs(tmp_path):
    service = BackgroundJobService(JobStore(tmp_path / "jobs.sqlite"))
    running = service.create("pattern_refresh", {})
    queued = service.create("opportunity_discovery", {})
    service.update(running["id"], status="running")

    count = service.mark_interrupted_jobs("测试中断")

    assert count == 2
    assert service.snapshot(running["id"])["status"] == "failed"
    assert service.snapshot(queued["id"])["status"] == "failed"
    assert service.snapshot(running["id"])["error"] == "测试中断"


def test_interrupt_marking_moved_off_import_and_gated(tmp_path, monkeypatch):
    """import webui.core 不得误杀共享库里 running 的任务(曾误杀打包 App 在跑的挖掘);
    只有 mark_interrupted_jobs_on_boot()(robyn 启动钩子)才标记,且受
    KRONOS_SKIP_INTERRUPT_MARK 开关控制(dev 与打包 App 并行场景)。"""
    import importlib
    import sys

    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_DISABLE_PATTERN_AUTOREFRESH", "1")
    monkeypatch.setenv("KRONOS_DISABLE_QUANT_RADAR_AUTOSAVE", "1")
    db = tmp_path / "data" / "webui_jobs.sqlite"
    db.parent.mkdir(parents=True, exist_ok=True)
    from webui.services.job_store import JobStore

    JobStore(db).create({"id": "victim", "type": "opportunity_discovery", "status": "running", "params": {}})

    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")
    assert core.JOB_STORE.get("victim")["status"] == "running"  # import 期不再误杀

    monkeypatch.setenv("KRONOS_SKIP_INTERRUPT_MARK", "1")
    assert core.mark_interrupted_jobs_on_boot() == 0
    assert core.JOB_STORE.get("victim")["status"] == "running"  # 开关生效

    monkeypatch.delenv("KRONOS_SKIP_INTERRUPT_MARK")
    assert core.mark_interrupted_jobs_on_boot() >= 1
    assert core.JOB_STORE.get("victim")["status"] == "failed"  # 真启动才标记
    sys.modules.pop("webui.core", None)
