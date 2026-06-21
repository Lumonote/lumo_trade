import time
from webui.services.stock_suite_service import StockSuiteService


def test_refresh_runs_and_persists(monkeypatch):
    svc = StockSuiteService()
    writes = {}
    monkeypatch.setattr(svc, "_run_related_news_job",
                        lambda code: writes.update({code: 3}) or 3)
    r = svc.refresh_related_news("601702")
    assert r["status"] == "running"
    for _ in range(50):
        if svc.get_related_news_status("601702").get("status") in ("ready", "failed"):
            break
        time.sleep(0.02)
    st = svc.get_related_news_status("601702")
    assert st["status"] == "ready"
    assert writes["601702"] == 3


def test_status_idle_when_never_run():
    svc = StockSuiteService()
    assert svc.get_related_news_status("000000")["status"] == "idle"
