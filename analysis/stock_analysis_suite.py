"""Stock Analysis Suite orchestrator — single entry per stock code, 5-min LRU cache."""

from __future__ import annotations

import datetime as _dt
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


_DEFAULT_TTL_SECONDS = 300  # 5 minutes per spec §3


_REGIME_BASE = {"bull": 50, "sideways": 35, "bear": 15}


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


def compute_volume_price_game_score(buy_signal_count: int, total_models: int = 30) -> int:
    """5维评分③. Spec §4 ③."""
    if total_models <= 0:
        return 0
    return int(round(buy_signal_count / total_models * 100.0))


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


def _missing(label: str = "数据不足", reason: str = "数据采集失败") -> Dict[str, Any]:
    return {"score": None, "label": label, "reason": reason}


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
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._lock = RLock()
        self._reports_root = Path(reports_root) if reports_root else Path("reports/stock_suite")

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

    def _compute_full_payload(self, code: str) -> Dict[str, Any]:
        """Assemble overview / risk_control / cached_reports + AI stub. Spec §5.1."""
        warnings_: list = []
        try:
            overview = self.compute_overview(code)
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
            ],
            "warnings": warnings_,
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
            total = inputs["models"].get("total", 30)
            score = compute_volume_price_game_score(buy_count, total)
            radar["volume_price_game"] = {
                "score": score,
                "label": self._label_vp(score),
                "reason": f"{total} 模型中 {buy_count} 个买入信号",
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
            score = compute_performance_score(
                pe_percentile_rank=fundam.get("pe_industry_rank"),
                roe_pct=fundam.get("roe"),
                yoy_growth_pct=fundam.get("net_profit_yoy"),
            )
            if score is None:
                radar["performance"] = _missing()
            else:
                pe = fundam.get("pe")
                roe = fundam.get("roe")
                reason = f"PE {pe}，ROE {roe}%" if pe is not None and roe is not None else "基本面"
                radar["performance"] = {
                    "score": score,
                    "label": self._label_perf(score),
                    "reason": reason,
                }
        except (KeyError, TypeError, ValueError):
            radar["performance"] = _missing()
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
                "roe": fi.get("roe"),
                "pe_industry_rank": ic.get("pe_rank"),
                "net_profit_yoy": fr.get("net_profit_yoy"),
            }
        except Exception as exc:  # noqa: BLE001
            out["fundamental_error"] = str(exc)
        return out

    def compute_overview(self, code: str) -> Dict[str, Any]:
        inputs = self._collect_inputs(code)
        radar = self._compute_radar(inputs)
        return {
            "radar": radar,
            "key_signals": self._build_key_signals(inputs, radar),
            "deep_signals": self._build_deep_signals(inputs),
            "scenario_probability": self._build_scenario_probability(inputs),
        }

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

        prompt = "\n".join([
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
        ])
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
        conf = ((inputs.get("sentiment") or {}).get("confidence_label")) or "—"
        result.append({"label": "可信度", "value": conf, "tone": "neutral"})
        quality = inputs.get("quality") or {}
        result.append({"label": "量能质量", "value": quality.get("volume_label", "—"), "tone": "info"})
        result.append({"label": "筹码集中度", "value": quality.get("chip_label", "—"), "tone": "neutral"})
        return result

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

    def _load_ohlcv(self, code: str) -> pd.DataFrame:
        """Load OHLCV CSV from data/.

        Tries day-level first (data/{XSHE|XSHG}_day_{code}.csv) then 5min.
        """
        data_dir = Path(os.environ.get("KRONOS_DATA_DIR", "data"))
        exchange = "XSHE" if code.startswith(("0", "3")) else "XSHG"
        for suffix in (f"{exchange}_day_{code}.csv", f"{exchange}_5min_{code}.csv"):
            path = data_dir / suffix
            if path.exists():
                df = pd.read_csv(path, parse_dates=["timestamps"])
                if len(df) >= 60:
                    return df
        raise FileNotFoundError(f"no OHLCV file for {code} in {data_dir}")

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
        models = QuantitativeModels(df)
        models.run_all_models()
        buy = sell = hold = 0
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
        return {
            "buy_signal_count": buy,
            "sell_signal_count": sell,
            "hold_signal_count": hold,
            "total": buy + sell + hold,
        }

    def collect_cached_reports(self, code: str, base_dir: "Path | None" = None) -> Dict[str, Any]:
        base = Path(base_dir) if base_dir is not None else Path("reports")
        opp = _latest_match(base, ["opportunity_top10_*.md", "opportunity_top10_*.html"])
        batch = _latest_match(base, [f"batch_analysis_{code}_*.md", f"batch_analysis_*{code}*.json"])
        return {
            "opportunity": _report_entry(opp),
            "batch_analysis": _report_entry(batch),
        }

    def compute_risk_control(self, code: str) -> Dict[str, Any]:
        try:
            df = self._load_ohlcv(code)
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "reason": f"数据不足，建议先补齐数据 ({exc})"}
        if df is None or len(df) < 60:
            return {"available": False, "reason": "数据不足，建议先补齐数据"}

        close = df["close"].to_numpy()
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        current = float(close[-1])
        atr_series = TechnicalAnalysis.calculate_atr(df["high"], df["low"], df["close"], period=20)
        if hasattr(atr_series, "__len__") and len(atr_series) > 0:
            last_atr = atr_series.iloc[-1] if hasattr(atr_series, "iloc") else atr_series[-1]
            atr = float(last_atr) if not np.isnan(last_atr) else 0.0
        else:
            atr = 0.0

        stop_price = round(current - atr * 1.5, 2)
        drop_pct = round((current - stop_price) / current * 100, 1) if current else 0.0
        recent_high = float(max(close[-60:])) if len(close) >= 60 else float(max(close))
        expected_return_pct = round((recent_high - current) / current * 100, 1) if current else 0.0
        rr_ratio = round(expected_return_pct / max(0.1, drop_pct), 1)

        scaled = [
            {"label": "现价建仓",   "price": round(current, 2),          "position_pct": 10},
            {"label": "浅回调加仓", "price": round(current - atr * 0.25, 2), "position_pct": 20},
            {"label": "中度回调加仓","price": round(current - atr * 0.5, 2),  "position_pct": 30},
            {"label": "深度回调加仓","price": round(current - atr * 1.0, 2),  "position_pct": 25},
            {"label": "极限加仓",   "price": round(current - atr * 1.25, 2), "position_pct": 15},
        ]
        take_profit = [
            {"label": "第一止盈(前高)", "price": round(recent_high, 2),     "sell_pct": 30},
            {"label": "第二止盈(+15%)", "price": round(current * 1.15, 2),  "sell_pct": 30},
            {"label": "第三止盈(+30%)", "price": round(current * 1.30, 2),  "sell_pct": 25},
            {"label": "终极止盈(+50%)", "price": round(current * 1.50, 2),  "sell_pct": 15},
        ]

        return {
            "available": True,
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
                wclose = close[-window:]
                wpeak = float(max(wclose))
                wdd = round((float(min(wclose)) - wpeak) / wpeak * 100, 1) if wpeak > 0 else 0.0
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
        return "主力撤离"

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
