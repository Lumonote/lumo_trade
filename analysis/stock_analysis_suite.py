"""Stock Analysis Suite orchestrator — single entry per stock code, 5-min LRU cache."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import time
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from analysis.advanced_analysis import ChipAnalyzer, CapitalFlowAnalyzer
from analysis.fundamental_data_collector import FundamentalDataCollector
from analysis.investor_sentiment import InvestorSentimentAnalyzer
from analysis.llm_service import LLMAnalyzer
from analysis.technical_analysis import QuantitativeModels, TechnicalAnalysis
from analysis.analysis_overlay import build_overlay, merge_overlay
from analysis.limit_up_patterns import RECENT_DAYS, backtest_all, bars_from_dataframe, detect_all
from analysis import outcome_markers
from data_store import kv_repo


logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 300  # 5 minutes per spec §3
_OVERLAY_NS = "analysis_overlay"
# 按需补偿日线时的回溯窗口（~2 年）。覆盖 MA60 / 120 日回撤 / 60 日年化波动率所需历史，
# Eastmoney 一次请求即返回，命中后写库缓存，后续读取不再触网。
_FETCH_LOOKBACK_DAYS = 730


_REGIME_BASE = {"bull": 50, "sideways": 35, "bear": 15}

# 「入选后表现标记」本地推导用的评分器:懒加载 + 全局缓存(构造要读运行时评分配置,
# 每次个股分析都新建纯属浪费)。失败只降级为"技术分/追高风险缺失",绝不影响套件装配。
_MARKER_SCORER: Any = None
_MARKER_SCORER_UNAVAILABLE = False
_MARKER_SCORER_LOCK = RLock()


def _marker_scorer():
    """返回共享的 OpportunityScorer 实例;不可用时返回 None。"""
    global _MARKER_SCORER, _MARKER_SCORER_UNAVAILABLE
    if _MARKER_SCORER is not None or _MARKER_SCORER_UNAVAILABLE:
        return _MARKER_SCORER
    with _MARKER_SCORER_LOCK:
        if _MARKER_SCORER is not None or _MARKER_SCORER_UNAVAILABLE:
            return _MARKER_SCORER
        try:
            from analysis.opportunity_scorer import OpportunityScorer
            _MARKER_SCORER = OpportunityScorer()
        except Exception as exc:  # noqa: BLE001
            _MARKER_SCORER_UNAVAILABLE = True
            logger.warning("标记因子评分器不可用，技术分/追高风险按缺失处理: %s", exc)
        return _MARKER_SCORER


def compute_main_force_phase_score(
    control_degree: float,
    recent_main_positive_days: int,
    main_net: float,
    retail_net: float,
) -> int:
    """5维评分①. Spec §4 ①.

    0.5 * control_degree + 0.3 * continuity_score + 0.2 * retail_normalized
    """
    continuity = min(100.0, recent_main_positive_days * 20.0)
    # NOTE: Symmetric formula `abs(retail/main)` instead of spec §4 ① prose
    # `max(0, -retail/|main|)`. Symmetric form captures both 吸筹 and 派发 phases
    # (spec design-doc §4 ① to be amended in follow-up doc commit).
    if main_net == 0:
        retail_norm = 0.0
    else:
        retail_norm = abs(retail_net) / abs(main_net) * 100.0
    score = 0.5 * control_degree + 0.3 * continuity + 0.2 * min(100.0, retail_norm)
    return int(round(score))


def compute_market_cycle_score(regime: str, capital_flow_ratio: float) -> int:
    """5维评分②. Spec §4 ②. regime ∈ {bull, sideways, bear}."""
    base = _REGIME_BASE.get(regime, 35)
    score = base + 30.0 * max(0.0, min(1.0, capital_flow_ratio))
    return int(round(min(100.0, score)))


def compute_volume_price_game_score(
    buy_signal_count: int,
    total_models: int = 30,
    sell_signal_count: int = 0,
) -> int:
    """5维评分③. Spec §4 ③.

    量化模型经常以「观望」为主。旧实现只看买入票数，4 多 / 5 空 / 21 观望
    会被压成 13 分并误标「空头占优」。这里改用多空净差归一到 0–100：
    50 为多空均衡，大量观望不会天然等同于空头。
    """
    if total_models <= 0:
        return 0
    net = (buy_signal_count - sell_signal_count) / total_models
    score = 50.0 + net * 50.0
    return int(round(max(0.0, min(100.0, score))))


def count_quant_signals(df: "pd.DataFrame") -> Dict[str, Any]:
    """在一段 OHLCV 行情上跑 30 个量化模型，统计末根 K 的多/空/观望票数。

    与 ``StockAnalysisSuite._run_quant_models`` 同口径（信号末值 1→多 / -1→空 /
    其余→观望），抽成模块级纯函数，便于投资机会挖掘等链路在不实例化完整套件
    （及其网络/缓存依赖）的前提下复用。``df`` 至少需 ``open/high/low/close/volume``
    五列，其余指标由 ``QuantitativeModels`` 自行派生。
    """
    models = QuantitativeModels(df)
    models.run_all_models()
    perf = getattr(models, "models_performance", {}) or {}
    buy = sell = hold = 0
    per_model: list = []
    for _name, signal_series in (models.signals or {}).items():
        try:
            last = signal_series[-1] if hasattr(signal_series, "__getitem__") else signal_series
            if hasattr(last, "iloc"):
                last = last.iloc[-1] if len(last) else 0
        except Exception:  # noqa: BLE001
            last = 0
        try:
            last_val = int(last)
        except (TypeError, ValueError):
            last_val = 0
        if last_val == 1:
            buy += 1
        elif last_val == -1:
            sell += 1
        else:
            hold += 1
        name_cn = (perf.get(_name) or {}).get("中文名称")
        per_model.append({
            "model": str(_name),
            "name_cn": str(name_cn) if name_cn else None,
            "signal": last_val,
        })
    return {
        "buy_signal_count": buy,
        "sell_signal_count": sell,
        "hold_signal_count": hold,
        "total": buy + sell + hold,
        "per_model": per_model,
    }


def compute_chip_structure_score(concentration_pct: float, profit_ratio_pct: float) -> int:
    """5维评分④. Spec §4 ④.

    clip(100 - concentration*2, 0, 100) * 0.5 + (100 - |profit_ratio - 50|) * 0.5
    """
    a = max(0.0, min(100.0, 100.0 - concentration_pct * 2.0)) * 0.5
    b = (100.0 - abs(profit_ratio_pct - 50.0)) * 0.5
    return int(round(a + b))


def compute_performance_score(
    pe_percentile_rank: Optional[float],
    roe_pct: Optional[float],
    yoy_growth_pct: Optional[float],
) -> Optional[int]:
    """5维评分⑤. Spec §4 ⑤. Returns None if all three inputs None."""
    if pe_percentile_rank is None and roe_pct is None and yoy_growth_pct is None:
        return None
    pe_score = (100.0 - (pe_percentile_rank or 50.0)) if pe_percentile_rank is not None else 50.0
    if roe_pct is None:
        roe_score = 50.0
    elif roe_pct >= 15:
        roe_score = 100.0
    elif roe_pct <= 5:
        roe_score = 0.0
    else:
        roe_score = (roe_pct - 5.0) / 10.0 * 100.0
    if yoy_growth_pct is None:
        growth_score = 50.0
    elif yoy_growth_pct >= 50:
        growth_score = 100.0
    elif yoy_growth_pct <= 0:
        growth_score = max(0.0, 50.0 + yoy_growth_pct)  # 负增长扣分到 0
    else:
        growth_score = 50.0 + yoy_growth_pct
    return int(round(pe_score * 0.35 + roe_score * 0.35 + growth_score * 0.30))


def compute_industry_prosperity_score(
    sector_chg_pct: "float | None",
    sector_moneyflow_net: "float | None",
    pe_industry_percentile: "float | None",
    rank_in_industry_pct: "float | None",
) -> "int | None":
    """行业景气度 0-100；全 None 返回 None。
    板块涨跌 0.30 + 板块资金 0.30 + PE便宜度 0.20 + 行业排名 0.20。"""
    if all(v is None for v in (sector_chg_pct, sector_moneyflow_net,
                               pe_industry_percentile, rank_in_industry_pct)):
        return None
    chg_score = max(0.0, min(100.0, 50.0 + (sector_chg_pct or 0.0) * 5.0))
    # 资金：±3 亿映射到 ±50 分，封顶
    mf = (sector_moneyflow_net or 0.0) / 3.0e8
    mf_score = max(0.0, min(100.0, 50.0 + mf * 50.0))
    pe_score = (100.0 - pe_industry_percentile) if pe_industry_percentile is not None else 50.0
    rank_score = rank_in_industry_pct if rank_in_industry_pct is not None else 50.0
    score = chg_score * 0.30 + mf_score * 0.30 + pe_score * 0.20 + rank_score * 0.20
    return int(round(max(0.0, min(100.0, score))))


def compute_business_prosperity_score(
    revenue_yoy_pct: "float | None",
    profit_yoy_pct: "float | None",
    gross_margin_trend: "float | None",
    roe_pct: "float | None",
) -> "int | None":
    """个股业务景气度 0-100；全 None 返回 None。
    营收YoY 0.30 + 净利YoY 0.35 + 毛利率趋势 0.15 + ROE 0.20。"""
    if all(v is None for v in (revenue_yoy_pct, profit_yoy_pct,
                               gross_margin_trend, roe_pct)):
        return None

    def _yoy(v):  # -50%→0, 0%→50, +50%→100
        if v is None:
            return 50.0
        return max(0.0, min(100.0, 50.0 + v))

    rev_score = _yoy(revenue_yoy_pct)
    profit_score = _yoy(profit_yoy_pct)
    # 毛利率趋势：±5pct 映射 ±50
    gm = gross_margin_trend
    gm_score = 50.0 if gm is None else max(0.0, min(100.0, 50.0 + gm * 10.0))
    if roe_pct is None:
        roe_score = 50.0
    elif roe_pct >= 15:
        roe_score = 100.0
    elif roe_pct <= 0:
        roe_score = 0.0
    else:
        roe_score = roe_pct / 15.0 * 100.0
    score = rev_score * 0.30 + profit_score * 0.35 + gm_score * 0.15 + roe_score * 0.20
    return int(round(max(0.0, min(100.0, score))))


def _unavailable_section(reason: str) -> dict:
    return {
        "data_status": "unavailable",
        "last_updated": None,
        "reason": reason,
    }


def _missing(label: str = "数据不足", reason: str = "数据采集失败") -> Dict[str, Any]:
    return {"score": None, "label": label, "reason": reason}


def _to_optional_float(v) -> Optional[float]:
    """把 'N/A'/None/非数值统一成 None，数值（含纯数字字符串）转 float、NaN 也归 None。

    radar 各维度评分函数签名均为 Optional[float]，但真实采集器常回 'N/A' 字符串；
    不归一会让 `'N/A' >= 15` 等比较抛 TypeError 被 except 吞成「数据不足」（E4 假阴性）。
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return None if f != f else f  # NaN → None
    try:
        f = float(str(v).strip())
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _latest_match(base: Path, patterns: list) -> "Path | None":
    if not base.exists():
        return None
    candidates: list = []
    for pattern in patterns:
        candidates.extend(base.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _report_entry(path: "Path | None") -> Dict[str, Any]:
    if path is None:
        return {"found": False, "path": None, "updated_at": None}
    return {
        "found": True,
        "path": str(path),
        "updated_at": _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
    }


class StockAnalysisSuite:
    """Orchestrates per-stock analysis (overview / risk_control / AI payload).

    Thread-safe in-memory LRU cache keyed by stock_code. Cache value is the full
    suite payload as a JSON-serializable dict.
    """

    def __init__(
        self,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        reports_root: Optional[Path] = None,
        institutional_providers: Optional[Dict[str, Any]] = None,
        auto_fetch: bool = True,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._lock = RLock()
        self._reports_root = Path(reports_root) if reports_root else Path("reports/stock_suite")
        self._inst_providers = institutional_providers or {}
        # 本地 OHLCV 不足时是否按需向数据源补偿（spec §6.7 + 用户「立马补偿数据」要求）。
        # 生产默认开启；单测验证纯本地降级阶梯时关闭以保持离线/幂等。
        self._auto_fetch = bool(auto_fetch)
        # code → 上次补偿尝试的 monotonic 时刻，用于去重：同一 payload 内 _load_ohlcv 被
        # _collect_inputs + compute_risk_control 调两次，且失败时避免逐请求反复打网络。
        self._fetch_attempts: Dict[str, float] = {}

    def get_full_payload(self, code: str) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(code)
            if cached and now - cached[0] < self._ttl:
                return cached[1]
        payload = self._compute_full_payload(code)
        with self._lock:
            self._cache[code] = (now, payload)
        return payload

    def invalidate(self, code: str) -> None:
        with self._lock:
            self._cache.pop(code, None)

    def trigger_ai_interpretation(
        self,
        code: str,
        name: str = "",
        model_full_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """Run LLM interpretation and persist markdown to reports/stock_suite/."""
        if force_refresh:
            self.invalidate(code)
        suite_data = self.get_full_payload(code)
        payload = self.build_llm_payload(code, name or code, suite_data)
        analyzer = LLMAnalyzer()
        ok, text, tokens = analyzer.interpret_stock_markdown(payload, model_full_key)
        now_iso = _dt.datetime.now().isoformat(timespec="seconds")
        if not ok:
            return {
                "success": False,
                "status": "failed",
                "error": text,
                "generated_at": now_iso,
            }
        self._reports_root.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._reports_root / f"{code}_{ts}.md"
        path.write_text(text, encoding="utf-8")
        return {
            "success": True,
            "status": "ready",
            "report": text,
            "token_usage": tokens,
            "generated_at": now_iso,
            "cached_path": str(path),
        }

    def trigger_panel_overlay(
        self,
        code: str,
        tier: str = "deep",
        *,
        llm_caller=None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """按需生成多空评审团 LLM 覆盖层（spec §7 P0-A）。
        lite 不调 LLM；medium/deep 生成 + 校验 + 持久化到 kv_repo（可审计/回滚）。
        返回 {success, overlay, merged_panel}；失败也返回结构化 overlay（reviewed=False）。"""
        if force_refresh:
            self.invalidate(code)
        suite_data = self.get_full_payload(code)
        panel = suite_data.get("panel") or {}
        overlay = build_overlay(panel, suite_data, tier, llm_caller=llm_caller)
        try:
            kv_repo.set_(_OVERLAY_NS, str(code), overlay)
        except Exception:  # noqa: BLE001
            pass
        return {
            "success": bool(overlay.get("reviewed")),
            "overlay": overlay,
            "merged_panel": merge_overlay(panel, overlay),
        }

    def _compute_full_payload(self, code: str) -> Dict[str, Any]:
        """Assemble overview / risk_control / cached_reports + AI stub. Spec §5.1."""
        warnings_: list = []
        inputs: Dict[str, Any] = {}
        try:
            inputs = self._collect_inputs(code)
            overview = self.compute_overview(code, inputs=inputs)
        except Exception as exc:  # noqa: BLE001
            overview = None
            warnings_.append(f"overview 装配失败：{exc}")
        try:
            risk = self.compute_risk_control(code)
        except Exception as exc:  # noqa: BLE001
            risk = {"available": False, "reason": str(exc)}
            warnings_.append(f"risk_control 装配失败：{exc}")
        try:
            cached = self.collect_cached_reports(code)
        except Exception as exc:  # noqa: BLE001
            cached = {"opportunity": _report_entry(None), "batch_analysis": _report_entry(None)}
            warnings_.append(f"cached_reports 读取失败：{exc}")
        # 机构深度挖掘顶层 key。chip_control 透传本地已算的控盘度（spec §0.1）；
        # main_force_deep / institutional_holdings 经 provider 自动拉取 akshare 写库。
        main_force_deep = self._collect_main_force_deep(code)
        institutional_holdings = self._collect_institutional_holdings(code)
        chip_control = self._collect_chip_control(code, chip=inputs.get("chip"))
        quant_matrix = self._collect_quant_matrix(code, models=inputs.get("models"))
        limit_up_screening = self._collect_limit_up_patterns(code, inputs)
        panel = self._collect_panel(code, inputs, {
            "main_force_deep": main_force_deep,
            "institutional_holdings": institutional_holdings,
            "chip_control": chip_control,
            "quant_matrix": quant_matrix,
            "limit_up_screening": limit_up_screening,
            "overview": overview,
        })
        return {
            "overview": overview,
            "risk_control": risk,
            "cached_reports": cached,
            "ai_interpretation": {
                "status": "not_generated",
                "report": None,
                "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai",
            },
            "stub_tabs": [
                "market_cycle", "main_force_phase", "volume_price_game",
                "chip_structure", "performance", "probability", "limit_up_screening",
                "related_news",
            ],
            "warnings": warnings_,
            "main_force_deep": main_force_deep,
            "institutional_holdings": institutional_holdings,
            "chip_control": chip_control,
            "quant_matrix": quant_matrix,
            "limit_up_screening": limit_up_screening,
            "related_news": self._collect_related_news(code),
            "outcome_markers": self._collect_outcome_markers(code, inputs),
            "panel": panel,
            "analysis_overlay": self._collect_analysis_overlay(code),
        }

    def _collect_outcome_markers(self, code: str, inputs: dict | None) -> dict:
        """入选后表现标记(见 analysis/outcome_markers.py)。

        取数优先级:
        1. 该股**最近一次机会挖掘入选**时已入库的标记 —— 与报告口径逐字一致, 不重算;
        2. 从未入选(或旧版 run 未存标记)时, 用个股分析本地可得的因子现场计算。
           技术分/追高风险由机会挖掘评分链路产出, 不在本链路, 故按缺失处理并在
           ``missing_factors`` 中显式列出, 避免"没触发"被误读成"没风险"。
        """
        stored = None
        try:
            from data_store import opportunity_repo
            stored = opportunity_repo.latest_item_for_code(code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取 %s 最近入选标记失败: %s", code, exc)

        if stored:
            try:
                signals = json.loads(stored.get("signals_json") or "{}")
            except Exception:  # noqa: BLE001
                signals = {}
            markers = signals.get("markers")
            if markers is not None:
                constitution = signals.get("constitution") or outcome_markers.constitution([])
                stored_description = signals.get("marker_description") or ""
                return {
                    "available": bool(markers),
                    "source": "opportunity_run",
                    "as_of": stored.get("run_date"),
                    "partial": False,
                    "missing_factors": [],
                    "version": signals.get("markers_version") or outcome_markers.MARKERS_VERSION,
                    "markers": markers,
                    "constitution": constitution,
                    "description": stored_description,
                    # 入库标记是**入选当天**的口径,不能拿今天的走势去讲当天的标记,
                    # 故沿用入库时的叙述;旧版 run 没存则退回逐条描述。
                    "narrative": signals.get("marker_narrative") or stored_description,
                    "baseline": outcome_markers.BASELINE,
                    "note": f"复用 {stored.get('run_date')} 该股入选机会挖掘时的标记，与报告口径一致",
                }

        factors, context = self._local_marker_inputs(code, inputs)
        missing = [label for label, key in (("技术分", "tech_score"), ("追高风险", "chase_risk"),
                                            ("RSI", "rsi"), ("板块情绪分", "sector_score"),
                                            ("卖出信号", "sell_signals"), ("5日涨幅", "change_5d"))
                   if factors.get(key) is None]
        payload = outcome_markers.marker_payload(factors, context)
        base_note = "该股无机会挖掘入选记录，标记由个股分析本地因子按机会挖掘同口径推导"
        return {
            "available": bool(payload["markers"]),
            "source": "local",
            "as_of": None,
            "partial": bool(missing),
            "missing_factors": missing,
            "version": payload["version"],
            "markers": payload["markers"],
            "constitution": payload["constitution"],
            "description": payload["description"],
            "narrative": payload["narrative"],
            "baseline": outcome_markers.BASELINE,
            "note": (f"{base_note}；缺失因子：{'、'.join(missing)}" if missing
                     else f"{base_note}（因子完整）"),
        }

    def _local_marker_inputs(self, code: str, inputs: dict | None) -> tuple[dict, dict]:
        """本地可得的标记因子 + 这只票的走势上下文(拿不到的一律留 None, 不伪造)。

        技术分/追高风险/RSI/5日涨幅 与位置、涨幅、连涨节奏等走势明细都走
        ``OpportunityScorer.marker_inputs_from_ohlcv``, 与机会挖掘同一套代码
        同一套口径(标记阈值就是按那套分布标定的); 板块情绪分/卖出信号/板块名
        沿用本链路已经取到的结果。
        """
        inputs = inputs or {}
        factors: dict = {"tech_score": None, "chase_risk": None, "rsi": None,
                         "sector_score": None, "sell_signals": None, "change_5d": None}
        context: dict = {}

        sector = inputs.get("sector") or {}
        if sector.get("sentiment_score") is not None:
            factors["sector_score"] = sector.get("sentiment_score")
        sector_name = sector.get("name") or sector.get("sector") or inputs.get("industry")
        if sector_name:
            context["sector_name"] = sector_name
        models = inputs.get("models") or {}
        if models.get("total"):
            factors["sell_signals"] = models.get("sell_signal_count")

        df = inputs.get("ohlcv")
        scorer = _marker_scorer()
        if scorer is not None and df is not None and not getattr(df, "empty", True):
            try:
                derived = scorer.marker_inputs_from_ohlcv(code, df)
                for key, value in (derived.get("factors") or {}).items():
                    if value is not None:
                        factors[key] = value
                for key, value in (derived.get("context") or {}).items():
                    if value is not None:
                        context.setdefault(key, value)
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s: 标记因子(评分器口径)计算失败: %s", code, exc)

        # 评分器不可用/数据不足时的最后兜底: RSI 与 5 日涨幅本链路自己也能算。
        if factors["rsi"] is None or factors["change_5d"] is None:
            self._fallback_price_factors(factors, df)
        context.setdefault("change_5d", factors.get("change_5d"))
        return factors, context

    def _local_marker_factors(self, code: str, inputs: dict | None) -> dict:
        """只要因子时的薄封装, 见 ``_local_marker_inputs``。"""
        return self._local_marker_inputs(code, inputs)[0]

    def _fallback_price_factors(self, factors: dict, df) -> None:
        """评分器拿不到时,用本链路自己的收盘价序列补 RSI / 5 日涨幅。"""
        if df is None or "close" not in getattr(df, "columns", []) or len(df) < 15:
            return
        try:
            close = df["close"]
            if factors["rsi"] is None:
                factors["rsi"] = self._last_indicator_value(
                    TechnicalAnalysis.calculate_rsi(close))
            if factors["change_5d"] is None:
                base = float(close.iloc[-6])
                if base > 0:
                    factors["change_5d"] = (float(close.iloc[-1]) - base) / base * 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("本地标记因子计算失败: %s", exc)

    def _collect_limit_up_patterns(self, code: str, inputs: dict | None) -> dict:
        """Rule-based strong limit-up pattern section for the stock suite."""
        inputs = inputs or {}
        df = inputs.get("ohlcv")
        if df is None or getattr(df, "empty", True):
            return {
                **_unavailable_section(inputs.get("ohlcv_error") or "OHLCV 数据不足，无法识别涨停强势形态"),
                "matches": [],
                "pattern_stats": {},
                "summary": {"detected_count": 0, "best": None},
            }
        try:
            bars = bars_from_dataframe(df)
            matches = inputs.get("lp_matches")
            if matches is None:
                matches = detect_all(bars, code=code, recent_days=RECENT_DAYS)
            stats = backtest_all(bars, code=code)
            best = None
            for match in matches:
                horizons = (stats.get(match.get("pattern")) or {}).get("horizons") or {}
                for horizon, row in horizons.items():
                    win_rate = row.get("win_rate")
                    count = row.get("count") or 0
                    if win_rate is None or count <= 0:
                        continue
                    if best is None or win_rate > best["win_rate"]:
                        best = {"name": match.get("name"), "win_rate": win_rate, "horizon": horizon}
            return {
                "data_status": "fresh",
                "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
                "reason": None,
                "matches": matches,
                "pattern_stats": stats,
                "summary": {"detected_count": len(matches), "best": best},
            }
        except Exception as exc:  # noqa: BLE001
            return {
                **_unavailable_section(f"涨停强势形态识别失败：{exc}"),
                "matches": [],
                "pattern_stats": {},
                "summary": {"detected_count": 0, "best": None},
            }

    def _collect_panel(self, code: str, inputs: dict | None, sections: dict) -> dict:
        """多空评审团：60 persona 规则裁决 + 16 指标 + 共识/大分歧（spec §0/§11 Phase 1）。
        纯规则，无 LLM。任何异常降级 unavailable，不影响其它 Tab。"""
        try:
            from analysis.panel import build_panel
            return build_panel(inputs or {}, sections)
        except Exception as exc:  # noqa: BLE001
            return {
                **_unavailable_section(f"panel 计算失败：{exc}"),
                "consensus": None, "great_divide": None,
                "schools": [], "analysts": [], "indicators": [],
            }

    def _collect_analysis_overlay(self, code: str) -> dict:
        """读取已持久化的 LLM 覆盖层（spec §7 P0-A）。
        有历史 → 原样返回但 data_status 置 stale；无 → unavailable/reviewed=False（前端回退规则文案）。
        任何异常都降级，不影响其它 Tab。"""
        try:
            hit = kv_repo.get(_OVERLAY_NS, str(code))
        except Exception:  # noqa: BLE001
            hit = None
        if not hit:
            return {
                "data_status": "unavailable", "last_updated": None, "reviewed": False,
                "tier": "lite", "great_divide_override": None, "risks": [],
                "panel_insights": {}, "buy_zones": None, "narrative_override": None,
                "reason": "尚未生成 AI 覆盖层（点击「AI 深度点评」生成）",
            }
        overlay, _epoch = hit
        if isinstance(overlay, dict):
            overlay = {**overlay, "data_status": "stale"}  # 读历史 → stale
        return overlay

    def _collect_main_force_deep(self, ts_code: str) -> dict:
        """主力深度：龙虎榜 + 陆股通。provider 查库为空时自动经 akshare 拉取写库，仍无则降级 unavailable。"""
        lhb = self._inst_providers.get("lhb")
        hsgt = self._inst_providers.get("hsgt")
        if not lhb and not hsgt:
            return _unavailable_section("no provider configured")
        lhb_res = lhb.get(ts_code) if lhb else None
        hsgt_res = hsgt.get(ts_code) if hsgt else None
        results = [r for r in (lhb_res, hsgt_res) if r is not None]
        if not results:
            return _unavailable_section("no provider configured")
        statuses = [r.data_status for r in results]
        overall = "unavailable" if all(s == "unavailable" for s in statuses) else "stale"
        last_updated = max((r.last_updated or "" for r in results), default=None) or None
        reasons = [r.reason for r in results if r.reason]
        return {
            "data_status": overall,
            "last_updated": last_updated,
            "reason": "; ".join(reasons) if reasons else None,
            "dragon_tiger": lhb_res.data if (lhb_res and lhb_res.data) else None,
            "hsgt": hsgt_res.data if (hsgt_res and hsgt_res.data) else None,
            "stage_timeline": None,        # M3 填充
            "quant_signature": None,       # M3 填充
        }

    def _collect_institutional_holdings(self, ts_code: str) -> dict:
        """机构持仓：Top10 股东 + 股东户数（akshare 自动拉取）+ 调研/基金（留待批量导入）。"""
        holders = self._inst_providers.get("holders")
        survey = self._inst_providers.get("survey")
        fund = self._inst_providers.get("fund")
        providers = [(name, p) for name, p in
                     (("holders", holders), ("survey", survey), ("fund", fund)) if p]
        if not providers:
            return _unavailable_section("no provider configured")
        results = [(name, p.get(ts_code)) for name, p in providers]
        statuses = [r.data_status for _, r in results]
        overall = "unavailable" if all(s == "unavailable" for s in statuses) else "stale"
        last_updated = max((r.last_updated or "" for _, r in results), default=None) or None
        reasons = [r.reason for _, r in results if r.reason]
        out = {
            "data_status": overall,
            "last_updated": last_updated,
            "reason": "; ".join(reasons) if reasons else None,
            "top10_floatholders": None,
            "holder_number": None,
            "surveys": None,
            "fund_holds": None,
        }
        for name, r in results:
            if r.data:
                if name == "holders":
                    out["top10_floatholders"] = r.data.get("top10_floatholders")
                    out["holder_number"] = r.data.get("holder_number")
                elif name == "survey":
                    out["surveys"] = r.data
                elif name == "fund":
                    out["fund_holds"] = r.data
        return out

    def _collect_related_news(self, code: str) -> dict:
        from analysis.stock_relation_news import RELATION_TIERS
        from data_store import stock_related_news_repo
        try:
            snap = stock_related_news_repo.latest_for_code(code)
        except Exception as exc:  # noqa: BLE001 — 表缺失/DB 异常不应拖垮整页
            return {"data_status": "unavailable", "last_updated": None,
                    "reason": f"关联新闻读取失败：{exc}", "tiers": {}}
        if not snap.get("fetched_at"):
            return {"data_status": "unavailable", "last_updated": None,
                    "reason": "未抓取，点击「刷新关联新闻」", "tiers": {}}
        try:
            age = (_dt.datetime.now()
                   - _dt.datetime.fromisoformat(snap["fetched_at"])).total_seconds()
        except Exception:  # noqa: BLE001
            age = 0
        status = "fresh" if age < 6 * 3600 else "stale"
        tiers: dict = {}
        for it in snap["items"]:
            tiers.setdefault(it.get("tier"), []).append(it)
        return {"data_status": status, "last_updated": snap["fetched_at"],
                "reason": None, "tiers": tiers,
                "tier_order": list(RELATION_TIERS)}

    def _collect_chip_control(self, ts_code: str, chip: dict | None = None) -> dict:
        """筹码控盘度：透传 ChipAnalyzer 的控盘度/集中度（已计算，spec §0.1），
        官方 cyq 分布留待 M2。chip 为 ChipAnalyzer.analyze 输出；为 None 时降级。"""
        details = (chip or {}).get("details") if chip else None
        control = details.get("main_force_control") if details else None
        if control is not None:
            conc_90 = details.get("concentration_90")
            cyq = self._inst_providers.get("cyq")
            cyq_res = cyq.get(ts_code) if cyq else None
            cyq_data = cyq_res.data if (cyq_res and cyq_res.data) else None
            return {
                "data_status": "fresh",
                "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
                "reason": None,
                "control_degree": int(round(control)),
                "control_label": self._label_control(control),
                "concentration_90": conc_90,
                "concentration_70": (cyq_data or {}).get("concentration_70_pct"),  # 官方 cyq 补全
                "concentration_50": None,   # cyq_em 无 50 集中度
                "top10_concentration": None,
                "cyq_distribution": cyq_data,
            }
        # 无本地控盘度：回落到 cyq provider 的状态
        cyq = self._inst_providers.get("cyq")
        if not cyq:
            return {**_unavailable_section("no provider configured"),
                    "control_degree": None, "control_label": None,
                    "concentration_90": None, "concentration_70": None,
                    "concentration_50": None, "top10_concentration": None,
                    "cyq_distribution": None}
        cyq_res = cyq.get(ts_code)
        cyq_data = cyq_res.data if cyq_res.data else None
        return {
            "data_status": cyq_res.data_status,
            "last_updated": cyq_res.last_updated,
            "reason": cyq_res.reason,
            "control_degree": None,
            "control_label": None,
            "concentration_90": (cyq_data or {}).get("concentration_90_pct"),
            "concentration_70": (cyq_data or {}).get("concentration_70_pct"),
            "concentration_50": None,
            "top10_concentration": None,
            "cyq_distribution": cyq_data,
        }

    def _collect_quant_matrix(self, ts_code: str, models: dict | None = None) -> dict:
        """量化矩阵：30 模型投票本地已算（spec §0.1/§3.6）。本期产出日线信号矩阵 +
        多周期共振计数 + 当前态势；多周期热力列(3/10/30 日)与 30 日历史命中率需回测
        数据，留 M4。models 为 _run_quant_models 输出；缺失时降级 unavailable。"""
        if not models or int(models.get("total", 0)) <= 0:
            return _unavailable_section("M4: 量化模型未产出信号（OHLCV 不足或加载失败）")
        buy = int(models.get("buy_signal_count", 0))
        sell = int(models.get("sell_signal_count", 0))
        hold = int(models.get("hold_signal_count", 0))
        total = buy + sell + hold
        signals_matrix = [
            {"model": m.get("name_cn") or m.get("model"),
             "model_key": m.get("model"),
             "period": "daily", "signal": m.get("signal"),
             "confidence": None}
            for m in (models.get("per_model") or [])
        ]
        return {
            "data_status": "fresh",
            "last_updated": _dt.datetime.now().isoformat(timespec="seconds"),
            "reason": None,
            "signals_matrix": signals_matrix,
            "hit_rate_30d": None,       # M4: 需回测历史命中率
            "multi_period_resonance": {"bull": buy, "bear": sell, "neutral": hold},
            "current_posture": self._label_posture(buy, sell, total),
        }

    @staticmethod
    def _label_posture(buy: int, sell: int, total: int) -> str:
        """当前态势（spec §3.6）。按多空净差分 5 档，并识别观望主导。"""
        if total <= 0:
            return "震荡"
        score = compute_volume_price_game_score(buy, total, sell)
        neutral_ratio = max(0.0, (total - buy - sell) / total)
        if neutral_ratio >= 0.6 and 40 <= score <= 60:
            return "观望主导"
        if score >= 80: return "强势多头"
        if score >= 60: return "震荡偏多"
        if score > 40: return "震荡"
        if score > 20: return "震荡偏空"
        return "强势空头"

    def _build_payload_with_institutional(self, code: str) -> dict:
        """Build only the institutional portion of the payload (for testing)."""
        mfd = self._collect_main_force_deep(code)
        ih = self._collect_institutional_holdings(code)
        cc = self._collect_chip_control(code)
        qm = self._collect_quant_matrix(code)
        return {
            "main_force_deep": mfd,
            "institutional_holdings": ih,
            "chip_control": cc,
            "quant_matrix": qm,
            "panel": self._collect_panel(code, {}, {
                "main_force_deep": mfd, "institutional_holdings": ih,
                "chip_control": cc, "quant_matrix": qm, "overview": None,
            }),
        }

    def _compute_radar(self, inputs: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Compute 5 radar dimensions from pre-fetched analyzer outputs.

        `inputs` is a dict with optional keys: chip, capital_flow, market_regime,
        capital_flow_ratio, models, fundamental, sentiment, quality. Each entry
        may be absent if its analyzer failed.
        """
        radar: Dict[str, Dict[str, Any]] = {}
        try:
            chip = inputs["chip"]["details"]
            cap = inputs["capital_flow"]["details"]["order_analysis"]
            positive_days = inputs["capital_flow"]["details"].get("positive_days_5d", 0)
            score = compute_main_force_phase_score(
                control_degree=chip["main_force_control"],
                recent_main_positive_days=positive_days,
                main_net=cap["main_net_inflow"],
                retail_net=cap["retail_net_inflow"],
            )
            radar["main_force_phase"] = {
                "score": score,
                "label": self._label_main_force(score),
                "reason": f"主力近5日{positive_days}日净流入",
            }
        except (KeyError, TypeError, ValueError):
            radar["main_force_phase"] = _missing()
        try:
            regime = inputs["market_regime"]
            ratio = inputs.get("capital_flow_ratio", 0.0)
            score = compute_market_cycle_score(regime, ratio)
            radar["market_cycle"] = {
                "score": score,
                "label": self._label_regime(regime),
                "reason": f"大盘资金流入比 {ratio:.2f}",
            }
        except (KeyError, TypeError, ValueError):
            radar["market_cycle"] = _missing()
        try:
            buy_count = inputs["models"]["buy_signal_count"]
            sell_count = inputs["models"].get("sell_signal_count", 0)
            total = inputs["models"].get("total", 30)
            score = compute_volume_price_game_score(buy_count, total, sell_count)
            radar["volume_price_game"] = {
                "score": score,
                "label": self._label_vp(score),
                "reason": f"{total} 模型中 {buy_count} 个买入信号、{sell_count} 个卖出信号",
            }
        except (KeyError, TypeError, ValueError):
            radar["volume_price_game"] = _missing()
        try:
            chip_details = inputs["chip"]["details"]
            concentration = chip_details["concentration_90"]
            profit_ratio = chip_details.get("profit_ratio", 50.0)
            score = compute_chip_structure_score(concentration, profit_ratio)
            radar["chip_structure"] = {
                "score": score,
                "label": self._label_chip(score),
                "reason": f"90% 成本集中度 {concentration:.1f}%",
            }
        except (KeyError, TypeError, ValueError):
            radar["chip_structure"] = _missing()
        try:
            fundam = inputs["fundamental"]
            # E4：'N/A'/字符串等非数值强制为 None，避免流进 compute_performance_score
            # 触发 `'N/A' >= 15` 之类 TypeError 被吞成「数据不足」（假阴性）。
            roe = _to_optional_float(fundam.get("roe"))
            score = compute_performance_score(
                pe_percentile_rank=_to_optional_float(fundam.get("pe_industry_rank")),
                roe_pct=roe,
                yoy_growth_pct=_to_optional_float(fundam.get("net_profit_yoy")),
            )
            if score is None:
                radar["performance"] = _missing()
            else:
                pe = _to_optional_float(fundam.get("pe"))
                reason = f"PE {pe}，ROE {roe}%" if pe is not None and roe is not None else "基本面"
                radar["performance"] = {
                    "score": score,
                    "label": self._label_perf(score),
                    "reason": reason,
                    "industry_prosperity": self._build_industry_prosperity(inputs),
                    "business_prosperity": self._build_business_prosperity(fundam),
                }
        except (KeyError, TypeError, ValueError):
            radar["performance"] = _missing()
        # 控盘度：透传 ChipAnalyzer.main_force_control（spec §0.1/§3.6）。
        # 无 chip 数据时回落 0（向后兼容空 inputs 调用）。
        try:
            control = inputs["chip"]["details"]["main_force_control"]
            radar["control_degree"] = {
                "score": int(round(control)),
                "label": self._label_control(control),
            }
        except (KeyError, TypeError, ValueError):
            radar["control_degree"] = {"score": 0, "label": "未知"}
        # 量化活跃度：M3（quant_signature_detector）填充，暂默认 0
        radar["quant_activity"] = {"score": 0, "label": "未知"}
        return radar

    def _collect_inputs(self, code: str) -> Dict[str, Any]:
        """Fetch raw analyzer outputs from chip / capital_flow / quant / market / fundamental."""
        out: Dict[str, Any] = {}
        try:
            df = self._load_ohlcv(code)
            out["ohlcv"] = df
        except Exception as exc:  # noqa: BLE001
            out["ohlcv_error"] = str(exc)
            df = None
        if df is not None:
            try:
                out["chip"] = ChipAnalyzer().analyze(code, df)
            except Exception as exc:  # noqa: BLE001
                out["chip_error"] = str(exc)
            try:
                out["capital_flow"] = CapitalFlowAnalyzer().analyze(code, df)
            except Exception as exc:  # noqa: BLE001
                out["capital_flow_error"] = str(exc)
            try:
                out["models"] = self._run_quant_models(code, df)
            except Exception as exc:  # noqa: BLE001
                out["models_error"] = str(exc)
            try:
                bars = bars_from_dataframe(df)
                out["lp_matches"] = detect_all(bars, code=code, recent_days=RECENT_DAYS)
            except Exception as exc:  # noqa: BLE001
                out["lp_matches"] = []
                out["lp_error"] = str(exc)
        try:
            regime, ratio = self._classify_market_regime()
            out["market_regime"] = regime
            out["capital_flow_ratio"] = ratio
        except Exception as exc:  # noqa: BLE001
            out["market_error"] = str(exc)
        try:
            fundam_raw = FundamentalDataCollector(code, minimal_api_mode=True).get_comprehensive_data() or {}
            fi = fundam_raw.get("financial_indicators") or {}
            fr = fundam_raw.get("financial_reports") or {}
            ic = fundam_raw.get("industry_comparison") or {}
            out["fundamental"] = {
                "pe": fi.get("pe"),
                "pb": fi.get("pb"),  # panel features 消费 pb,此前漏传导致估值类 persona「数据不足」
                "roe": fi.get("roe"),
                "pe_industry_rank": ic.get("pe_rank"),
                "net_profit_yoy": fr.get("net_profit_yoy"),
                "revenue_yoy": fr.get("revenue_yoy"),
                "gross_margin": fr.get("gross_margin"),
                "gross_margin_prev": fr.get("gross_margin_prev"),
                "industry_rank_pct": ic.get("industry_rank"),
            }
        except Exception as exc:  # noqa: BLE001
            out["fundamental_error"] = str(exc)
        try:
            from analysis.sector_api import get_sector_sentiment
            sec = get_sector_sentiment(code) or {}
            out["sector"] = {
                "change_pct": sec.get("change_pct") or sec.get("avg_change_pct"),
                "moneyflow_net": sec.get("moneyflow_net") or sec.get("main_net_inflow"),
                "sentiment_score": sec.get("sentiment_score"),
                "sector_name": sec.get("sector_name"),
            }
        except Exception as exc:  # noqa: BLE001
            out["sector_error"] = str(exc)
        self._augment_fundamental_from_local(code, out)
        return out

    @staticmethod
    def _augment_fundamental_from_local(code: str, out: Dict[str, Any]) -> None:
        """PE/PB 本地兜底:采集失败或字段缺失时读 data_store.daily_basic 最近一行。

        联网基本面采集(同花顺/腾讯/tushare)在代理/限流环境下经常整组失败,
        panel 的估值特征(pe/pb)随之全空 → persona 大面积「数据不足」。库内
        daily_basic 是离线快照,至少把估值两项补上(roe/净利同比无本地源仍可能缺)。
        """
        try:
            fundam = out.get("fundamental") or {}
            if fundam.get("pe") is not None and fundam.get("pb") is not None:
                return

            from data_store import daily_basic_repo
            from data_store.tushare_client import to_ts_code

            df = daily_basic_repo.get_for_code(to_ts_code(code), limit=1)
            if df is None or df.empty:
                return
            row = df.iloc[0]

            def _first_valid(*keys):
                for key in keys:
                    v = _to_optional_float(row.get(key))
                    if v is not None:
                        return v
                return None

            if fundam.get("pe") is None:
                fundam["pe"] = _first_valid("pe_ttm", "pe")
            if fundam.get("pb") is None:
                fundam["pb"] = _first_valid("pb")
            out["fundamental"] = fundam
        except Exception:  # noqa: BLE001 — 兜底失败保持原状
            pass

    def compute_overview(self, code: str, inputs: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if inputs is None:
            inputs = self._collect_inputs(code)
        radar = self._compute_radar(inputs)
        overview = {
            "radar": radar,
            "key_signals": self._build_key_signals(inputs, radar),
            "deep_signals": self._build_deep_signals(inputs),
            "scenario_probability": self._build_scenario_probability(inputs),
        }
        overview["strong_patterns"] = self._build_strong_patterns_summary(inputs)
        return overview

    def _build_strong_patterns_summary(self, inputs: Dict[str, Any]) -> dict:
        matches = inputs.get("lp_matches") or []
        items = []
        for match in matches[:5]:
            items.append({
                "name": match.get("name"),
                "strength": match.get("strength"),
                "tone": match.get("tone"),
                "days_ago": match.get("days_ago"),
                "best_win_rate": None,
            })
        return {"items": items, "detected_count": len(matches)}

    def build_llm_payload(
        self, code: str, name: str, suite_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble LLM prompt covering 7 sections per spec §5.2."""
        overview = (suite_data or {}).get("overview") or {}
        radar = overview.get("radar") or {}
        risk = (suite_data or {}).get("risk_control") or {}

        def _fmt_radar(key: str) -> str:
            entry = radar.get(key) or {}
            score = entry.get("score")
            label = entry.get("label", "—")
            return f"{label}({score if score is not None else '—'}分)"

        lines = [
            f"# 股票深度分析任务：{name}（{code}）",
            "",
            "请按以下 7 个小节输出 Markdown 报告（保留小节标题，每节 3-5 段）：",
            "## 1. 核心定性",
            "## 2. 价值与安全边际",
            "## 3. 主力博弈解析",
            "## 4. 多因子量化评估",
            "## 5. 情绪周期与市场定位",
            "## 6. 预期差挖掘",
            "## 7. 操盘建议",
            "",
            "## 输入数据",
            (
                f"- 5维评分：主力阶段 {_fmt_radar('main_force_phase')}；"
                f"市场周期 {_fmt_radar('market_cycle')}；"
                f"量价博弈 {_fmt_radar('volume_price_game')}；"
                f"筹码结构 {_fmt_radar('chip_structure')}；"
                f"业绩预期 {_fmt_radar('performance')}"
            ),
            f"- 关键信号：{overview.get('key_signals')}",
            f"- 深度信号：{overview.get('deep_signals')}",
            f"- 情景概率：{overview.get('scenario_probability')}",
            f"- 风控数据：{risk}",
        ]

        # spec §4.3.4: 仅纳入 data_status=fresh/stale 的深度字段，unavailable 跳过避免编造。
        chip = (suite_data or {}).get("chip_control") or {}
        if chip.get("data_status") in ("fresh", "stale") and chip.get("control_degree") is not None:
            lines.append(
                f"- 控盘度：{chip.get('control_label')}（{chip.get('control_degree')}），"
                f"90% 筹码集中度 {chip.get('concentration_90')}"
            )
        qm = (suite_data or {}).get("quant_matrix") or {}
        if qm.get("data_status") in ("fresh", "stale") and qm.get("current_posture"):
            reso = qm.get("multi_period_resonance") or {}
            lines.append(
                f"- 量化矩阵：当前态势 {qm.get('current_posture')}，"
                f"多空共振 看多{reso.get('bull', 0)}/看空{reso.get('bear', 0)}/观望{reso.get('neutral', 0)}"
            )

        prompt = "\n".join(lines)
        return {"prompt": prompt, "model_full_key": None}

    def _build_key_signals(self, inputs: Dict[str, Any], radar: Dict[str, Any]) -> list:
        result = []
        regime = inputs.get("market_regime")
        if regime == "bull":
            tone = "info"
        elif regime in ("sideways", "bear"):
            tone = "warn"
        else:  # missing or unknown
            tone = "neutral"
        result.append({
            "label": "大盘周期",
            "value": self._label_regime(regime or "sideways"),
            "tone": tone,
        })
        cap_ratio = inputs.get("capital_flow_ratio", 0.0)
        position_cap = max(20, min(80, int(cap_ratio * 100)))
        result.append({"label": "仓位上限", "value": f"{position_cap}%", "tone": "warn"})
        mf_label = (radar.get("main_force_phase") or {}).get("label", "—")
        result.append({"label": "主力阶段", "value": mf_label, "tone": "info"})
        # 可信度 / 量能质量 / 筹码集中度:历史上只读 inputs["sentiment"]/["quality"],而
        # _collect_inputs 从不填充这两个键 → 综合总览这三项恒为「—」(空)。改为优先读这两个
        # 键(未来管线若填充则采用),否则从已采集的 inputs/radar 实时派生,真无数据才回落「—」。
        sentiment = inputs.get("sentiment") or {}
        conf = sentiment.get("confidence_label") or self._data_confidence_label(inputs)
        result.append({"label": "可信度", "value": conf, "tone": "neutral"})
        quality = inputs.get("quality") or {}
        vp_label = (radar.get("volume_price_game") or {}).get("label")
        vol_label = quality.get("volume_label") or (vp_label if vp_label and vp_label != "未知" else "—")
        result.append({"label": "量能质量", "value": vol_label, "tone": "info"})
        chip_label = quality.get("chip_label") or self._chip_concentration_label(inputs)
        # 该指标实为 90% 成本分布宽度((p95-p5)/mid)，可 >100%，越小越集中。
        # 旧标签「筹码集中度」会让 >100% 被误读成「极度分散=出货」。
        result.append({"label": "筹码分布宽度", "value": chip_label, "tone": "neutral"})
        tech = self._build_technical_trend_signal(inputs)
        if tech:
            result.append(tech)
        return result

    @staticmethod
    def _data_confidence_label(inputs: Dict[str, Any]) -> str:
        """可信度:关键数据源到位程度(chip/capital_flow/models/fundamental 成功几项)。"""
        n = sum(1 for k in ("chip", "capital_flow", "models", "fundamental") if inputs.get(k))
        if n >= 4:
            return "高"
        if n >= 2:
            return "中"
        if n >= 1:
            return "低"
        return "—"

    @staticmethod
    def _chip_concentration_label(inputs: Dict[str, Any]) -> str:
        """筹码集中度:由 90% 成本集中度派生(越小越集中)。无数据回落「—」。"""
        try:
            c = float(((inputs.get("chip") or {}).get("details") or {}).get("concentration_90"))
        except (TypeError, ValueError):
            return "—"
        if c <= 0:
            return "—"
        if c < 10:
            return f"高度集中({c:.0f}%)"
        if c < 20:
            return f"较集中({c:.0f}%)"
        if c < 30:
            return f"适中({c:.0f}%)"
        return f"分散({c:.0f}%)"

    @staticmethod
    def _last_indicator_value(series: Any) -> Optional[float]:
        """Return the latest non-NaN numeric value from a pandas-like series."""
        if series is None:
            return None
        try:
            work = series.dropna() if hasattr(series, "dropna") else pd.Series(series).dropna()
            if len(work) == 0:
                return None
            return float(work.iloc[-1])
        except Exception:  # noqa: BLE001
            return None

    def _build_technical_trend_signal(self, inputs: Dict[str, Any]) -> Optional[dict]:
        """Expose MA alignment in overview key signals when enough OHLCV exists."""
        df = inputs.get("ohlcv")
        if df is None or "close" not in getattr(df, "columns", []) or len(df) < 20:
            return None
        try:
            close = df["close"]
            ma5 = self._last_indicator_value(TechnicalAnalysis.calculate_ma(close, 5))
            ma10 = self._last_indicator_value(TechnicalAnalysis.calculate_ma(close, 10))
            ma20 = self._last_indicator_value(TechnicalAnalysis.calculate_ma(close, 20))
        except Exception:  # noqa: BLE001
            return None
        if None in (ma5, ma10, ma20):
            return None
        if ma5 > ma10 > ma20:
            return {"label": "技术趋势", "value": "多头排列", "tone": "info"}
        if ma5 < ma10 < ma20:
            return {"label": "技术趋势", "value": "空头排列", "tone": "warn"}
        return {"label": "技术趋势", "value": "均线交织", "tone": "neutral"}

    def _build_deep_signals(self, inputs: Dict[str, Any]) -> list:
        signals: list = []
        chip_sigs = ((inputs.get("chip") or {}).get("signals")) or []
        for sig in chip_sigs[:3]:
            signals.append({"text": str(sig), "tone": "info", "tag": "筹码"})
        cap_sigs = ((inputs.get("capital_flow") or {}).get("signals")) or []
        for sig in cap_sigs[:3]:
            signals.append({"text": str(sig), "tone": "info", "tag": "资金"})
        return signals

    def _build_scenario_probability(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        models = inputs.get("models") or {}
        buy = int(models.get("buy_signal_count", 0))
        sell = int(models.get("sell_signal_count", 0))
        hold = int(models.get("hold_signal_count", 0))
        raw_total = buy + sell + hold
        if raw_total <= 0:
            return {
                "bullish": None,
                "bearish": None,
                "sideways": None,
                "source": "数据不足 — 量化模型未产出信号",
            }
        total = raw_total
        bullish = int(round(buy / total * 100))
        bearish = int(round(sell / total * 100))
        sideways = 100 - bullish - bearish
        return {
            "bullish": bullish,
            "bearish": bearish,
            "sideways": sideways,
            "source": "30 量化模型多空票数归一化",
        }

    def _ensure_ohlcv_daily(self, code: str) -> bool:
        """本地 OHLCV 不足 → 立即从 Eastmoney（免 token）补偿日线并写库。

        每实例按冷却窗口去重：同一 payload 内 _load_ohlcv 的两次调用、以及连续失败的
        逐请求重试都不会重复打网络（补偿成功后数据已入库，重扫即命中，不再走到此分支）。
        返回 True 仅当本次确有发起补偿且数据源回了非空数据。
        """
        now = time.monotonic()
        cooldown = max(self._ttl, 30.0)  # 即便 ttl 配得极小，也保证 payload 内双调用只补偿一次
        with self._lock:
            last = self._fetch_attempts.get(code)
            if last is not None and (now - last) < cooldown:
                return False
            self._fetch_attempts[code] = now
        try:
            from data_store.ohlcv_fetch import ensure_daily

            today = _dt.date.today()
            start = (today - _dt.timedelta(days=_FETCH_LOOKBACK_DAYS)).strftime("%Y%m%d")
            end = today.strftime("%Y%m%d")
            df = ensure_daily(str(code).zfill(6), start, end)
            return df is not None and not df.empty
        except Exception:  # noqa: BLE001 — 补偿尽力而为，失败回退到分级降级路径
            return False

    def _load_ohlcv(self, code: str, min_rows: int = 35) -> pd.DataFrame:
        """Load OHLCV from data_store.ohlcv_repo (SQLite)，按需补偿 + 分级降级（E6/§6.7）。

        读取顺序：优先返回 ≥60 行的频率（指标充足，保留旧的 1d→5m 偏好）。本地不足 60
        行时**立即按需补偿**（``_ensure_ohlcv_daily`` 走 Eastmoney 免 token 拉日线写库），
        再重扫一次；补偿后仍 <60 才回到分级降级：返回最长且 ≥``min_rows`` 行的序列
        （35–59 日为「短历史降级」，指标交由下游 + 标注低置信）；都 <``min_rows`` 才抛
        FileNotFoundError，message 带「当前行数 + 需 ≥N 交易日」并给出补齐数据的操作指引
        （仅在确实补偿无果时显示），避免级联多面板泛化「数据不足」。
        """
        from data_store import ohlcv_repo

        def _scan() -> "tuple[pd.DataFrame | None, pd.DataFrame | None]":
            """返回 (ideal≥60, best<60)。命中 ideal 即可直接用；best 为最长的不足序列。"""
            best: "pd.DataFrame | None" = None
            for frequency in ("1d", "5m"):
                df = ohlcv_repo.load_dataframe(code, frequency)
                if df is not None and len(df) >= 60:
                    return df, best
                if df is not None and (best is None or len(df) > len(best)):
                    best = df
            return None, best

        ideal, best = _scan()
        if ideal is not None:
            return ideal
        # 本地 <60 行 → 立即补偿，再重扫一次（补偿成功则此处命中 ≥60）。
        if self._auto_fetch and self._ensure_ohlcv_daily(code):
            ideal, best = _scan()
            if ideal is not None:
                return ideal
        # 补偿后（或未开启补偿）仍 <60：短历史降级（≥min_rows 可算指标，下游标注低置信）。
        if best is not None and len(best) >= min_rows:
            return best
        have = len(best) if best is not None else 0
        msg = f"OHLCV 历史不足：{code} 最长仅 {have} 行（需 ≥{min_rows} 交易日）"
        if self._auto_fetch:
            msg += (
                f"；已自动补偿但数据源仍未返回足量数据，请确认代码正确且未停牌/退市，"
                f"或手动运行 `python scripts/fetch_data.py --symbol {code} --source auto` 补齐"
            )
        raise FileNotFoundError(msg)

    def _classify_market_regime(self) -> "tuple[str, float]":
        """Map sentiment-analyzer overall market reading → (regime, capital_flow_ratio).

        regime ∈ {bull, sideways, bear}; ratio clamped to [0, 1].
        """
        try:
            analyzer = InvestorSentimentAnalyzer("000001")  # 任意代码触发整体大盘信息
            overall = analyzer.get_overall_market_sentiment() or {}
            score = float(overall.get("sentiment_score", 50))
            change_pct = float(overall.get("average_change_pct", 0))
            ratio = max(0.0, min(1.0, (score / 100.0) * 0.5 + (max(-2.0, min(2.0, change_pct)) + 2) / 4 * 0.5))
            if score >= 65 or change_pct >= 1.0:
                regime = "bull"
            elif score <= 35 or change_pct <= -1.0:
                regime = "bear"
            else:
                regime = "sideways"
            return regime, ratio
        except Exception:  # noqa: BLE001
            return "sideways", 0.0

    def _run_quant_models(self, code: str, df: pd.DataFrame) -> Dict[str, int]:
        # 模型中文名来自 technical_analysis 各模型定义的 models_performance['中文名称']
        # (30 个模型全部定义),作为权威来源透传,避免在前端/Excel 各自维护一份英文→中文映射。
        # 统计逻辑抽到模块级 count_quant_signals,供机会挖掘等链路在不实例化套件时复用。
        return count_quant_signals(df)

    def collect_cached_reports(self, code: str, base_dir: "Path | None" = None) -> Dict[str, Any]:
        base = Path(base_dir) if base_dir is not None else Path("reports")
        opp = _latest_match(base, ["opportunity_top10_*.md", "opportunity_top10_*.html"])
        batch = _latest_match(base, [f"batch_analysis_{code}_*.md", f"batch_analysis_*{code}*.json"])
        return {
            "opportunity": _report_entry(opp),
            "batch_analysis": _report_entry(batch),
        }

    def compute_risk_control(
        self,
        code: str,
        current_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            df = self._load_ohlcv(code)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": f"数据不足，建议先补齐数据 ({exc})"}
        if df is None or len(df) < 60:
            have = 0 if df is None else len(df)
            return {"available": False,
                    "reason": f"数据不足：风控需 ≥60 交易日，当前仅 {have} 日"}

        ohlcv_close = float(df["close"].iloc[-1])
        price_scale = 1.0
        price_source = "ohlcv"
        try:
            realtime_price = float(current_price) if current_price is not None else None
        except (TypeError, ValueError):
            realtime_price = None
        if (
            realtime_price is not None
            and np.isfinite(realtime_price)
            and realtime_price > 0
            and np.isfinite(ohlcv_close)
            and ohlcv_close > 0
        ):
            price_scale = realtime_price / ohlcv_close
            price_source = "realtime_quote"

        close_series = df["close"].astype(float) * price_scale
        high_series = df["high"].astype(float) * price_scale
        low_series = df["low"].astype(float) * price_scale
        close = close_series.to_numpy()
        current = float(realtime_price) if price_source == "realtime_quote" else float(close[-1])
        atr_series = TechnicalAnalysis.calculate_atr(high_series, low_series, close_series, period=20)
        if hasattr(atr_series, "__len__") and len(atr_series) > 0:
            last_atr = atr_series.iloc[-1] if hasattr(atr_series, "iloc") else atr_series[-1]
            atr = float(last_atr) if not np.isnan(last_atr) else 0.0
        else:
            atr = 0.0

        stop_price = round(current - atr * 1.5, 2)
        drop_pct = round((current - stop_price) / current * 100, 1) if current else 0.0
        recent_high = float(max(close[-60:])) if len(close) >= 60 else float(max(close))
        # 上行目标：取「近 60 日高点」与「现价 + 1.5×ATR 顺势投影」的较大者。
        # 仅用近高点会让创新高的强势股目标=现价→期望收益 0%/盈亏比 1:0.0，系统性错杀突破股。
        upside_target = round(max(recent_high, current + atr * 1.5), 2)
        expected_return_pct = round((upside_target - current) / current * 100, 1) if current else 0.0
        rr_ratio = round(expected_return_pct / max(0.1, drop_pct), 1)

        scaled = [
            {"label": "现价建仓",   "price": round(current, 2),          "position_pct": 10},
            {"label": "浅回调加仓", "price": round(current - atr * 0.25, 2), "position_pct": 20},
            {"label": "中度回调加仓","price": round(current - atr * 0.5, 2),  "position_pct": 30},
            {"label": "深度回调加仓","price": round(current - atr * 1.0, 2),  "position_pct": 25},
            {"label": "极限加仓",   "price": round(current - atr * 1.25, 2), "position_pct": 15},
        ]
        take_profit = [
            {"label": "第一止盈(目标位)", "price": upside_target,           "sell_pct": 30},
            {"label": "第二止盈(+15%)", "price": round(current * 1.15, 2),  "sell_pct": 30},
            {"label": "第三止盈(+30%)", "price": round(current * 1.30, 2),  "sell_pct": 25},
            {"label": "终极止盈(+50%)", "price": round(current * 1.50, 2),  "sell_pct": 15},
        ]

        return {
            "available": True,
            "price_basis": {
                "source": price_source,
                "current_price": round(current, 2),
                "ohlcv_close": round(ohlcv_close, 2),
            },
            "execution_plan": {
                "stop_loss": {"price": stop_price, "drop_pct": drop_pct, "basis": "ATR(20)×1.5 下沿"},
                "risk_reward": {"ratio": f"1:{rr_ratio}", "expected_return_pct": expected_return_pct},
            },
            "scaled_entry": scaled,
            "tiered_take_profit": take_profit,
            "deep_signals": self._build_risk_deep_signals(close),
            "hidden_risks": [],  # 留给后续任务填充
        }

    def _build_risk_deep_signals(self, close: "np.ndarray") -> list:
        signals: list = []
        cur = float(close[-1])
        peak = float(max(close))
        cur_drawdown = round((cur - peak) / peak * 100, 1) if peak > 0 else 0.0
        signals.append({
            "text": f"最大回撤：当前 {cur_drawdown}%",
            "tone": "warn" if cur_drawdown < -15 else "info",
        })
        for window, label in ((60, "60日"), (120, "120日")):
            if len(close) >= window:
                wclose = np.asarray(close[-window:], dtype=float)
                # 真实最大回撤：峰值之后的最大跌幅（运行峰值 → 后续低点）。
                # 不能用 (min-max)/max，否则单边上涨(min 在前、max 在后)会被算成巨幅"回撤"。
                running_peak = np.maximum.accumulate(wclose)
                dd_series = np.where(running_peak > 0, (wclose - running_peak) / running_peak, 0.0)
                wdd = round(float(dd_series.min()) * 100, 1) if len(dd_series) else 0.0
                signals.append({
                    "text": f"{label}最大回撤 {wdd}%",
                    "tone": "warn" if wdd < -15 else "info",
                })
        if len(close) >= 60:
            log_returns = np.diff(np.log(close[-60:]))
            sigma = float(np.std(log_returns, ddof=1)) * np.sqrt(252)
            signals.append({
                "text": f"波动率(60日年化) {sigma*100:.1f}%",
                "tone": "info",
            })
            mean_return = float(np.mean(log_returns)) * 252
            sharpe = round(mean_return / max(0.0001, sigma), 2)
            signals.append({
                "text": f"夏普比率(60日年化) {sharpe}",
                "tone": "danger" if sharpe < 0 else "info",
            })
        return signals

    @staticmethod
    def _label_main_force(score: int) -> str:
        if score >= 70: return "强势主导"
        if score >= 50: return "中等偏强"
        if score >= 30: return "弱势承接"
        # 低分多由高波动/高换手压低 control_degree 所致，并非必然在出货。
        # 仅描述「控盘薄弱」，不断言「主力撤离」(派发)，避免下游误读成逃顶。
        return "主力控盘弱"

    @staticmethod
    def _label_regime(regime: str) -> str:
        return {"bull": "牛市趋势", "sideways": "震荡期", "bear": "熊市风险"}.get(regime, "震荡期")

    @staticmethod
    def _label_vp(score: int) -> str:
        if score >= 60: return "多头占优"
        if score >= 40: return "多空胶着"
        return "空头占优"

    @staticmethod
    def _label_chip(score: int) -> str:
        if score >= 60: return "结构健康"
        if score >= 35: return "结构一般"
        return "结构偏差"

    @staticmethod
    def _label_perf(score: int) -> str:
        if score >= 70: return "估值修复"
        if score >= 50: return "基本面稳健"
        if score >= 30: return "基本面承压"
        return "基本面恶化"

    @staticmethod
    def _label_prosperity(score: "int | None") -> str:
        if score is None:
            return "—"
        if score >= 70: return "高景气"
        if score >= 55: return "回暖"
        if score >= 40: return "平淡"
        return "退潮"

    def _build_industry_prosperity(self, inputs: dict) -> dict:
        from analysis.stock_context import _safe_float
        fundam = inputs.get("fundamental") or {}
        sector = inputs.get("sector") or {}
        chg = _safe_float(sector.get("change_pct"))
        mf = _safe_float(sector.get("moneyflow_net"))
        pe_pct = _safe_float(fundam.get("pe_industry_rank"))
        rank = _safe_float(fundam.get("industry_rank_pct"))
        score = compute_industry_prosperity_score(chg, mf, pe_pct, rank)
        if score is None:
            return _unavailable_section("行业景气度：无板块/行业数据")
        return {
            "score": score,
            "label": self._label_prosperity(score),
            "data_status": "fresh",
            "reason": None,
            "rows": [
                {"label": "板块涨跌", "value": f"{chg}%" if chg is not None else "—", "tone": "info"},
                {"label": "板块资金净流入", "value": f"{mf/1e8:.2f}亿" if mf is not None else "—",
                 "tone": "danger" if (mf is not None and mf < 0) else "info"},
                {"label": "PE行业分位", "value": f"{pe_pct:.0f}%" if pe_pct is not None else "—", "tone": "neutral"},
                {"label": "行业内排名分位", "value": f"{rank:.0f}%" if rank is not None else "—", "tone": "neutral"},
            ],
        }

    def _build_business_prosperity(self, fundam: dict) -> dict:
        from analysis.stock_context import _safe_float
        rev = _safe_float(fundam.get("revenue_yoy"))
        prof = _safe_float(fundam.get("net_profit_yoy"))
        gm = _safe_float(fundam.get("gross_margin"))
        gm_prev = _safe_float(fundam.get("gross_margin_prev"))
        gm_trend = (gm - gm_prev) if (gm is not None and gm_prev is not None) else None
        roe = _safe_float(fundam.get("roe"))
        score = compute_business_prosperity_score(rev, prof, gm_trend, roe)
        if score is None:
            return _unavailable_section("业务景气度：无财报数据")
        return {
            "score": score,
            "label": self._label_prosperity(score),
            "data_status": "fresh",
            "reason": None,
            "rows": [
                {"label": "营收YoY", "value": f"{rev}%" if rev is not None else "—",
                 "tone": "danger" if (rev is not None and rev < 0) else "info"},
                {"label": "净利YoY", "value": f"{prof}%" if prof is not None else "—",
                 "tone": "danger" if (prof is not None and prof < 0) else "info"},
                {"label": "毛利率", "value": f"{gm}%" if gm is not None else "—", "tone": "neutral"},
                {"label": "ROE", "value": f"{roe}%" if roe is not None else "—", "tone": "neutral"},
            ],
        }

    @staticmethod
    def _label_control(control_degree: float) -> str:
        """控盘度标签（spec §3.6: 低控/中控/高控）。与 ChipAnalyzer 阈值一致。"""
        if control_degree > 70: return "高控"
        if control_degree > 50: return "中控"
        return "低控"
