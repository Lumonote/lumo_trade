# tests/test_notification_events.py
"""NotificationEventService：入队自增 id / since 增量消费 / 上限截断。"""
from __future__ import annotations

from webui.services.notification_events import NotificationEventService


def test_push_assigns_incrementing_ids_and_list_filters_by_since():
    svc = NotificationEventService()
    first = svc.push("paper_eod", "复盘完成", "当日盈亏 +100")
    second = svc.push("opportunity_done", "挖掘完成")

    assert (first["id"], second["id"]) == (1, 2)

    full = svc.list()
    assert [e["id"] for e in full["events"]] == [1, 2]
    assert full["last_id"] == 2

    delta = svc.list(since_id=1)
    assert [e["id"] for e in delta["events"]] == [2]
    assert delta["events"][0]["title"] == "挖掘完成"


def test_max_events_ring_buffer():
    svc = NotificationEventService(max_events=3)
    for i in range(5):
        svc.push("t", f"e{i}")
    data = svc.list()
    assert [e["title"] for e in data["events"]] == ["e2", "e3", "e4"]
    assert data["last_id"] == 5
