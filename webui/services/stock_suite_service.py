"""Service-layer wrapper around analysis.StockAnalysisSuite.

Responsibilities:
- Input validation (stock code format)
- JSON shape conformance with spec §5.1 / §5.2
- Stock metadata enrichment (market exchange inference + sector lookup)
- Top-level exception handling so the HTTP handler always gets a dict back
"""

from __future__ import annotations

import datetime as _dt
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from analysis.analysis_overlay import merge_overlay
from analysis.stock_analysis_suite import StockAnalysisSuite
from webui.services.capital_rankings_service import CapitalRankingsService


# 合法 A 股 6 位代码：深 0 / 创业 3 / 沪 6(含科创 688) / 北交所 8·4·92(920xxx 新代码段)。
_CODE_RE = re.compile(r"^(?:6[0-9]{5}|[03][0-9]{5}|[84][0-9]{5}|92[0-9]{4})$")


def _build_institutional_providers() -> Dict[str, Any]:
    """Build institutional provider instances for StockAnalysisSuite.

    Providers read from SQLite first; on a miss they auto-fetch from akshare
    (free source) and persist, then re-read. lhb/hsgt/holders fetch per-stock;
    survey/fund/cyq fall back to batch importers when no per-stock endpoint exists.
    """
    from analysis.institutional import (
        LhbProvider, HsgtProvider, HoldersProvider,
        SurveyProvider, FundHoldingsProvider, CyqProvider,
        QuantSeatRegistry,
    )
    from data_store.akshare_adapter import AkshareAdapter

    repo_root = Path(__file__).resolve().parents[2]
    registry = QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
    adapter = AkshareAdapter()
    return {
        "lhb": LhbProvider(seat_registry=registry, akshare_adapter=adapter),
        "hsgt": HsgtProvider(akshare_adapter=adapter),
        "holders": HoldersProvider(akshare_adapter=adapter),
        "survey": SurveyProvider(akshare_adapter=adapter),
        "fund": FundHoldingsProvider(akshare_adapter=adapter),
        "cyq": CyqProvider(akshare_adapter=adapter),
    }


@lru_cache(maxsize=4096)
def _resolve_sector(code: str) -> tuple[str, str]:
    """Resolve (sector_name, stock_name) for a code. Cached per process.

    Returns ("—", "") on failure so the popup degrades gracefully.
    """
    try:
        from analysis.sector_api import get_stock_sector_info

        info = get_stock_sector_info(code) or {}
        sector = (info.get("sector_name") or info.get("industry") or "").strip()
        stock_name = (info.get("stock_name") or "").strip()
        if sector and sector not in ("未知", "N/A", "nan", "None"):
            return sector, stock_name
        return "—", stock_name
    except Exception:  # noqa: BLE001
        return "—", ""


@lru_cache(maxsize=4096)
def _resolve_boards(code: str) -> tuple[str, ...]:
    """Resolve the stock's associated boards (industry + concepts). Cached per process.

    Returns () on failure; the header then degrades to the single sector / placeholder.
    """
    try:
        from analysis.sector_api import get_stock_boards

        return tuple(get_stock_boards(code))
    except Exception:  # noqa: BLE001
        return ()


def star_orbit_repo_rings_for(boards, star_orbit_repo) -> list:
    """从星轨图谱里找出包含这些板块的概念环。失败返回 []。"""
    try:
        names = {b.get("name") for b in (boards or []) if b.get("name")}
        m = star_orbit_repo.get_map() or {}
        out = []
        for ring in m.get("rings", []):
            concepts = [b.get("board_name") for b in ring.get("boards", [])]
            if names & set(concepts):
                out.append({"ring": ring.get("name"), "concepts": concepts})
        return out
    except Exception:  # noqa: BLE001
        return []



class StockSuiteService:
    def __init__(self, orchestrator: Optional[StockAnalysisSuite] = None) -> None:
        if orchestrator:
            self._suite = orchestrator
        else:
            self._suite = StockAnalysisSuite(
                institutional_providers=_build_institutional_providers()
            )
        # AI 解读异步任务表（按代码）。DeepSeek 推理模型单次耗时可达 ~100s，远超 WKWebView
        # 对单个 fetch 的 ~60s 强制超时，因此改为「后台线程跑 + 前端轮询」。不复用 JOB_SERVICE：
        # 那会触发全局 jobLocked() 把机会挖掘/批量分析按钮锁死整整 100s。状态仅存内存、按代码覆盖。
        self._ai_jobs: Dict[str, Dict[str, Any]] = {}
        self._ai_lock = threading.Lock()
        # 关联热点新闻异步刷新任务表（按代码，仅内存）。读路径零联网，刷新走后台线程。
        self._related_jobs: Dict[str, Dict[str, Any]] = {}
        self._related_lock = threading.Lock()
        self._capital_rankings = CapitalRankingsService()

    def _validate_code(self, code: str) -> str:
        cleaned = (code or "").strip()
        if not cleaned or not _CODE_RE.match(cleaned):
            raise ValueError(f"invalid stock code: {code!r}")
        return cleaned

    def _stock_meta(self, code: str, name: str) -> Dict[str, Any]:
        market = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        sector, resolved_name = _resolve_sector(code)
        boards = list(_resolve_boards(code))
        return {
            "code": code,
            "name": name or resolved_name or "",
            "sector": sector,
            "boards": boards,
            "market": market,
        }

    def get_suite(self, code: str, name: str = "", force_refresh: bool = False) -> Dict[str, Any]:
        code = self._validate_code(code)
        meta = self._stock_meta(code, name)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        if force_refresh:
            self._suite.invalidate(code)
        try:
            payload = self._suite.get_full_payload(code)
            # 展示层重载一致性：已审阅 overlay 的金句 override / 逐人 insight 在此 merge 进 panel，
            # 与刚生成时 trigger_panel_overlay 返回的 merged_panel 保持一致。仅在此展示边界 merge——
            # compute/cache/regenerate 仍喂原始 panel 给 LLM（否则模型会把自己上一轮的金句当基线）。
            # merge_overlay 内部深拷贝，不改写编排器缓存里按引用返回的原始 panel。
            overlay = payload.get("analysis_overlay")
            panel = payload.get("panel")
            if isinstance(overlay, dict) and overlay.get("reviewed") and isinstance(panel, dict):
                payload = {**payload, "panel": merge_overlay(panel, overlay)}
            payload = {
                **payload,
                "capital_rankings": self._safe_capital_rankings(code),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "error": str(exc),
                "stock": meta,
                "generated_at": now,
            }
        return {
            "success": True,
            "stock": meta,
            "generated_at": now,
            "cache": {"hit": False, "expires_at": None},
            **payload,
        }

    def _safe_capital_rankings(self, code: str) -> Dict[str, Any]:
        try:
            return self._capital_rankings.stock_capital_summary(code)
        except Exception as exc:  # noqa: BLE001
            return {
                "kind": "stock_capital_rankings",
                "code": code,
                "mode": "aggregate",
                "days": 5,
                "data_status": "unavailable",
                "reason": f"资金榜单读取失败：{exc}",
                "moneyflow": {"data_status": "unavailable", "reason": "资金榜单读取失败"},
                "dragon_tiger": {"data_status": "unavailable", "reason": "资金榜单读取失败"},
            }

    def get_capital_rankings(
        self,
        code: str,
        *,
        date: str | None = None,
        days: int = 5,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return {
            "success": True,
            "capital_rankings": self._capital_rankings.stock_capital_summary(
                code,
                date=date,
                days=days,
                start_date=start_date,
                end_date=end_date,
            ),
        }

    def trigger_ai_interpretation(
        self,
        code: str,
        name: str = "",
        model_full_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_ai_interpretation(
            code,
            name=name,
            model_full_key=model_full_key,
            force_refresh=force_refresh,
        )

    def start_ai_interpretation(
        self,
        code: str,
        name: str = "",
        model_full_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """启动后台 AI 解读，立即返回 {status:'running'}；结果由 get_ai_interpretation 轮询。

        同一代码已有任务在跑且非强制刷新时，直接回报 running（去重，避免重复点击叠加线程）。
        """
        code = self._validate_code(code)
        with self._ai_lock:
            existing = self._ai_jobs.get(code)
            if existing and existing.get("status") == "running" and not force_refresh:
                return {"success": True, "status": "running",
                        "started_at": existing.get("started_at")}
            started_at = _dt.datetime.now().isoformat(timespec="seconds")
            self._ai_jobs[code] = {"status": "running", "started_at": started_at}

        def _worker() -> None:
            try:
                result = self._suite.trigger_ai_interpretation(
                    code,
                    name=name,
                    model_full_key=model_full_key,
                    force_refresh=force_refresh,
                )
            except Exception as exc:  # noqa: BLE001
                result = {
                    "success": False,
                    "status": "failed",
                    "error": str(exc),
                    "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
                }
            with self._ai_lock:
                prev = self._ai_jobs.get(code) or {}
                stored = dict(result)
                stored.setdefault("started_at", prev.get("started_at"))
                self._ai_jobs[code] = stored

        threading.Thread(target=_worker, name=f"ai-interp-{code}", daemon=True).start()
        return {"success": True, "status": "running", "started_at": started_at}

    def get_ai_interpretation(self, code: str) -> Dict[str, Any]:
        """轮询接口：返回当前 AI 解读任务状态（idle/running/ready/failed）及结果。"""
        code = self._validate_code(code)
        with self._ai_lock:
            job = self._ai_jobs.get(code)
            if not job:
                return {"success": True, "status": "idle"}
            return dict(job)

    def _run_related_news_job(self, code: str) -> int:
        """同步执行一次抓取并落盘，返回写入条数。默认 collector 在此接线。"""
        from analysis.stock_context import resolve_relations
        from analysis.stock_relation_news import collect_related_news
        from analysis import sector_api
        from analysis.sector_hot_news_collector import SectorNewsCollector
        from analysis.news_sentiment_collector import NewsSentimentCollector
        from data_store import opportunity_repo, star_orbit_repo, stock_related_news_repo

        def _stock_news(c):
            col = NewsSentimentCollector(c)
            news = col.get_latest_news(limit=8) or []
            ann = col.get_latest_announcements(limit=4) or []
            return list(news) + list(ann)

        sector_col = SectorNewsCollector()

        def _sector_news(names):
            return sector_col.get_top_news_by_sectors(
                list(names), per_sector_limit=4, total_limit=8) or []

        def _hot_news(boards):
            rows = opportunity_repo.latest_hot_news() or []
            kw = [b for b in boards]
            matched = [r for r in rows
                       if not kw or any(k and k in (r.get("title") or "") for k in kw)]
            return matched or rows[:6]

        def _orbit_news(rings):
            return []  # 星轨事件源首版留空（环映射已在 relations 中体现，后续增量接入）

        relations = resolve_relations(
            code,
            boards_fn=lambda c: [{"name": n} for n in sector_api.get_stock_boards(c)],
            peers_fn=lambda c: [],   # 同行/产业链：首版留空，后续接 industry_comparison/merger
            rings_fn=lambda boards: star_orbit_repo_rings_for(boards, star_orbit_repo),
            sector_fn=sector_api.get_sector_sentiment,
        )
        items = collect_related_news(
            code, relations,
            stock_news_fn=_stock_news, sector_news_fn=_sector_news,
            hot_news_fn=_hot_news, orbit_news_fn=_orbit_news,
        )
        fetched_at = _dt.datetime.now().isoformat(timespec="seconds")
        n = stock_related_news_repo.replace_for_code(code, items, fetched_at)
        self._suite.invalidate(code)
        return n

    def refresh_related_news(self, code: str, force_refresh: bool = False) -> Dict[str, Any]:
        """启动后台抓取关联新闻，立即返回 running；结果由 get_related_news_status 轮询。"""
        code = self._validate_code(code)
        with self._related_lock:
            ex = self._related_jobs.get(code)
            if ex and ex.get("status") == "running" and not force_refresh:
                return {"success": True, "status": "running", "started_at": ex.get("started_at")}
            started_at = _dt.datetime.now().isoformat(timespec="seconds")
            self._related_jobs[code] = {"status": "running", "started_at": started_at}

        def _worker():
            try:
                n = self._run_related_news_job(code)
                res = {"status": "ready", "written": n,
                       "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            except Exception as exc:  # noqa: BLE001
                res = {"status": "failed", "error": str(exc),
                       "generated_at": _dt.datetime.now().isoformat(timespec="seconds")}
            with self._related_lock:
                prev = self._related_jobs.get(code) or {}
                res.setdefault("started_at", prev.get("started_at"))
                self._related_jobs[code] = res

        threading.Thread(target=_worker, name=f"related-news-{code}", daemon=True).start()
        return {"success": True, "status": "running", "started_at": started_at}

    def get_related_news_status(self, code: str) -> Dict[str, Any]:
        """轮询接口：返回关联新闻刷新任务状态（idle/running/ready/failed）。"""
        code = self._validate_code(code)
        with self._related_lock:
            job = self._related_jobs.get(code)
            return dict(job) if job else {"success": True, "status": "idle"}


    def trigger_panel_overlay(
        self,
        code: str,
        tier: str = "deep",
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        code = self._validate_code(code)
        return self._suite.trigger_panel_overlay(code, tier=tier, force_refresh=force_refresh)


STOCK_SUITE_SERVICE = StockSuiteService()
