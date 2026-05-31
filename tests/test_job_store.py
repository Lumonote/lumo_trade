from webui.services.job_store import JobStore


def test_create_update_and_load_job(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite", max_logs=3)
    job = store.create(
        {
            "id": "abc123",
            "type": "batch_analysis",
            "status": "queued",
            "created_at": "2026-05-20T10:00:00",
            "params": {"stock_codes": ["600000"]},
            "logs": ["任务已进入队列"],
        }
    )

    assert job["id"] == "abc123"
    loaded = store.get("abc123")
    assert loaded is not None
    assert loaded["params"]["stock_codes"] == ["600000"]

    updated = store.update(
        "abc123",
        status="finished",
        finished_at="2026-05-20T10:05:00",
        result={"rows": 1},
    )
    assert updated is not None
    assert updated["status"] == "finished"
    assert updated["result"] == {"rows": 1}


def test_append_log_keeps_recent_entries(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite", max_logs=3)
    store.create(
        {
            "id": "abc123",
            "type": "pattern_refresh",
            "status": "queued",
            "created_at": "2026-05-20T10:00:00",
            "params": {},
            "logs": [],
        }
    )

    for index in range(5):
        store.append_log("abc123", f"log-{index}")

    loaded = store.get("abc123")
    assert loaded is not None
    assert loaded["logs"] == ["log-2", "log-3", "log-4"]


def test_list_recent_orders_by_created_at(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    store.create(
        {
            "id": "older",
            "type": "batch_analysis",
            "created_at": "2026-05-20T09:00:00",
            "params": {},
        }
    )
    store.create(
        {
            "id": "newer",
            "type": "batch_analysis",
            "created_at": "2026-05-20T10:00:00",
            "params": {},
        }
    )

    jobs = store.list_recent()
    assert [job["id"] for job in jobs] == ["newer", "older"]


def test_list_by_status_filters_active_jobs(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite")
    store.create({"id": "running", "type": "sample", "status": "running", "params": {}})
    store.create({"id": "queued", "type": "sample", "status": "queued", "params": {}})
    store.create({"id": "done", "type": "sample", "status": "finished", "params": {}})

    jobs = store.list_by_status(("queued", "running"))

    assert {job["id"] for job in jobs} == {"queued", "running"}
