import importlib
import sys


def test_completed_opportunity_job_is_reconciled_from_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")

    report = tmp_path / "results" / "opportunity_discovery_20260624_195735.html"
    top = tmp_path / "results" / "opportunity_top10_20260624_195735.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("<html></html>", encoding="utf-8")
    top.write_text("# top", encoding="utf-8")

    job = core.JOB_STORE.create({
        "id": "done-cleanup",
        "type": "opportunity_discovery",
        "status": "running",
        "params": {"source": "multi", "limit": 100, "workers": 10, "stock_codes": []},
        "logs": [
            "2026-06-24 19:57:37 🎉 投资机会挖掘完成！",
            f"2026-06-24 19:57:37 报表路径: {report}",
            f"2026-06-24 19:57:37 Top榜路径: {top}",
            "2026-06-24 19:57:38 ✓ 挖掘结果已入库: run_id=12 (2026-06-24)",
            "2026-06-24 19:58:23 ⏭️ 自动参数优化默认关闭，未改写评分配置",
        ],
    })

    snapshot = core._get_job_snapshot(job["id"])

    assert snapshot["status"] == "finished"
    assert snapshot["result"]["report_file"] == report.name
    assert snapshot["result"]["top_report_file"] == top.name
    assert snapshot["result"]["top_report_url"].endswith(top.name)

    sys.modules.pop("webui.core", None)


def test_opportunity_job_not_reconciled_before_db_write(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.core", None)
    core = importlib.import_module("webui.core")

    report = tmp_path / "results" / "opportunity_discovery_20260624_195735.html"
    top = tmp_path / "results" / "opportunity_top10_20260624_195735.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("<html></html>", encoding="utf-8")
    top.write_text("# top", encoding="utf-8")

    job = core.JOB_STORE.create({
        "id": "not-yet-db",
        "type": "opportunity_discovery",
        "status": "running",
        "params": {"source": "multi", "limit": 100, "workers": 10, "stock_codes": []},
        "logs": [
            "2026-06-24 19:57:37 🎉 投资机会挖掘完成！",
            f"2026-06-24 19:57:37 报表路径: {report}",
            f"2026-06-24 19:57:37 Top榜路径: {top}",
            "2026-06-24 19:58:23 ⏭️ 自动参数优化默认关闭，未改写评分配置",
        ],
    })

    snapshot = core._get_job_snapshot(job["id"])

    assert snapshot["status"] == "running"
    assert not snapshot.get("result")

    sys.modules.pop("webui.core", None)
