"""应用内通知事件(轻量内存队列)。

后台动作完成(模拟盘 EOD 复盘、机会挖掘任务、自动跟单成交/平仓等)时入队,
前端通知条「系统」分类与 Tauri OS 级通知通过 /api/notifications/events 增量消费。

设计取舍:进程内 deque + 自增 id,不落库——事件是「即时提醒」而非审计日志,
App 重启后丢弃历史事件属预期行为(无事件时通知条行为与从前完全一致)。
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime


class NotificationEventService:
    def __init__(self, max_events: int = 200, now_fn=None):
        self._events = deque(maxlen=int(max_events))
        self._lock = threading.Lock()
        self._next_id = 1
        self._now_fn = now_fn or datetime.now

    def push(self, type: str, title: str, message: str = "", *,
             level: str = "info", payload: dict | None = None) -> dict:
        """入队一条事件并返回(线程安全;异常静默不抛,通知绝不阻断业务)。"""
        event = {
            "id": 0,
            "type": str(type or "info"),
            "title": str(title or ""),
            "message": str(message or ""),
            "level": str(level or "info"),
            "created_at": self._now_fn().strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload or {},
        }
        with self._lock:
            event["id"] = self._next_id
            self._next_id += 1
            self._events.append(event)
        return event

    def list(self, since_id: int = 0, limit: int = 50) -> dict:
        """返回 id > since_id 的事件(升序)与当前最新 id,供前端增量轮询。"""
        try:
            since = int(since_id or 0)
        except (TypeError, ValueError):
            since = 0
        try:
            cap = max(1, min(int(limit or 50), 200))
        except (TypeError, ValueError):
            cap = 50
        with self._lock:
            events = [dict(e) for e in self._events if e["id"] > since]
            last_id = self._next_id - 1
        return {"events": events[-cap:], "last_id": last_id}
