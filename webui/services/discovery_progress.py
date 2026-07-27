"""投资机会挖掘进度聚合器:埋点事件流 → 结构化 progress 快照(写入 JobStore.progress)。

纯逻辑、线程安全;writer 异常一律吞掉——进度展示绝不能影响挖掘主流程。
消费方:webui/core._run_opportunity_job(writer=写 JobStore)与
scripts/run_opportunity_discovery.OpportunityDiscovery(progress_hook=tracker)。
"""
from __future__ import annotations

import datetime
import threading
import time as _time

STAGES = [
    ("regime", "大盘环境"), ("candidates", "候选获取"), ("preload", "全局预载"),
    ("analyze", "并发打分"), ("funnel", "漏斗筛选"), ("llm", "LLM深度分析"),
    ("report", "报告生成"), ("persist", "结果入库"), ("backtest", "自动回测"),
]
# percent 权重:analyze 按 done/total 内部线性推进,其余阶段整段到位;
# 运行中的非 analyze 阶段按半段计,percent 只增不减(_max_percent 防回退)。
_WEIGHTS = {"regime": 3, "candidates": 8, "preload": 4, "analyze": 60,
            "funnel": 5, "llm": 10, "report": 5, "persist": 2, "backtest": 3}


class DiscoveryProgressTracker:
    def __init__(self, writer, max_workers, now=None, min_interval=0.6):
        self._writer = writer
        self._now = now or _time.time
        self._min_interval = float(min_interval)
        self._lock = threading.RLock()
        self._last_write = 0.0
        self._max_percent = 0.0
        self.max_workers = int(max_workers)
        self._stages = {k: {"key": k, "label": lbl, "status": "pending", "detail": "",
                            "done": 0, "total": 0, "started": None, "finished": None}
                        for k, lbl in STAGES}
        self._inflight: dict[str, dict] = {}
        self._counts: dict = {"candidates": 0, "analyzed": 0, "failed": 0, "sources": {}}
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
                if st["status"] == "skipped":
                    return  # skip 后的兜底 stage_done 不覆盖 skipped 状态
                st["status"], st["finished"] = "done", self._now()
                if data.get("detail"):
                    st["detail"] = str(data["detail"])
                force = True
            elif event == "stage_skip" and st:
                st["status"], st["detail"] = "skipped", str(data.get("detail") or "")
                force = True
            elif event == "candidates_source":
                src = str(data.get("source") or "?")
                self._counts["sources"][src] = int(data.get("count") or 0)
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
                return  # 未知事件:忽略,保证埋点前后兼容
        self._maybe_write(force=force)

    def finalize(self, ok=True):
        """任务终态:成功把未走到的阶段标 done(best-effort 段可能静默完成),失败标 failed。"""
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
            return {
                "v": 1,
                "current_stage": self._current,
                "percent": self._percent_locked(),
                "eta_seconds": self._eta_locked(),
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

    # OpportunityDiscovery.progress_hook 可直接传本实例
    __call__ = emit
