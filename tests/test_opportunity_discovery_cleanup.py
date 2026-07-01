import time

from scripts.run_opportunity_discovery import OpportunityDiscovery


def test_cleanup_timeout_does_not_block_job_completion(monkeypatch):
    monkeypatch.setenv("KRONOS_RESOURCE_CLOSE_TIMEOUT", "0.05")

    def slow_cleanup():
        time.sleep(0.5)

    started = time.monotonic()
    ok = OpportunityDiscovery._run_cleanup_with_timeout("slow resource", slow_cleanup)
    elapsed = time.monotonic() - started

    assert ok is False
    assert elapsed < 0.25


def test_cleanup_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("KRONOS_RESOURCE_CLOSE_TIMEOUT", "1")

    def failing_cleanup():
        raise RuntimeError("close failed")

    assert OpportunityDiscovery._run_cleanup_with_timeout("bad resource", failing_cleanup) is False
