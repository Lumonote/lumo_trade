"""同类图形回测引擎。

给定一条「查询形态」曲线与一组候选股票，对每只股票拉取约一年的日 K，
用滑动窗口在历史里扫描与查询形态相似的片段（皮尔逊相关 ≥ 阈值），
记录每次命中后 5/10/20 日的收盘价前向收益，最后汇总胜率 / 平均涨幅 /
中位数 / 最佳最差，以及命中样本最多的股票。

设计要点
--------
* **纯逻辑 + 可注入 fetch**：``backtest_patterns`` 接收 ``fetch_klines`` 回调
  （签名同 ``scripts.build_pattern_fingerprints.fetch_recent_klines``，返回
  ``(name, klines)``），因此可离线单测、不依赖网络。
* **相似度**：复用 ``analysis.pattern_matcher`` 的 ``normalize_curve`` +
  ``pearson_similarity``；皮尔逊对线性缩放不敏感，只比形状。
* **去重**：命中后跳过 ``min_gap_days`` 个交易日，避免高度重叠的窗口被
  当成多个独立样本，污染胜率统计。
"""

from __future__ import annotations

import concurrent.futures
import statistics
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from analysis.pattern_matcher import normalize_curve, pearson_similarity

DEFAULT_HORIZONS: Tuple[int, ...] = (5, 10, 20)
DEFAULT_WINDOW_DAYS = 30
DEFAULT_SIMILARITY_THRESHOLD = 0.85
DEFAULT_HISTORY_DAYS = 250
DEFAULT_MIN_GAP_DAYS = 5
DEFAULT_MAX_WORKERS = 6
DEFAULT_TOP_STOCKS = 8
MAX_ERRORS_KEPT = 20

# fetch 回调签名： (symbol, limit) -> (name, klines)
FetchKlines = Callable[[str, int], Tuple[str, List[Any]]]


def parse_close_series(klines: Sequence[Any]) -> List[float]:
    """从原始日 K 结构解析收盘价序列（按时间升序，丢弃非法/0 值）。

    兼容三种形状：Sina dict（``{"close": ...}``）、Tencent list
    （``[date, open, close, high, low, volume]``）、CSV 字符串（``date,open,close,...``）。
    """
    closes: List[float] = []
    for item in klines or []:
        try:
            if isinstance(item, dict):
                close = float(item.get("close") or 0)
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                close = float(item[2])
            else:
                parts = str(item).split(",")
                if len(parts) < 3:
                    continue
                close = float(parts[2])
        except (TypeError, ValueError):
            continue
        if close > 0:
            closes.append(close)
    return closes


def scan_series(
    closes: Sequence[float],
    query_curve: Sequence[float],
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    min_gap_days: int = DEFAULT_MIN_GAP_DAYS,
) -> List[Dict[str, Any]]:
    """在单只股票的收盘序列里滑窗扫描与 ``query_curve`` 相似的片段。

    返回命中样本列表 ``[{"similarity", "end_index", "returns": {h: ret}}]``。
    只有至少能算出一个 horizon 前向收益的命中才会被记录。
    """
    query_norm = normalize_curve(query_curve)
    if query_norm is None or len(query_norm) < 2:
        return []
    target_length = len(query_norm)

    horizons = [int(h) for h in horizons if int(h) > 0]
    if not horizons:
        return []

    closes = [float(c) for c in closes]
    n = len(closes)
    window_days = max(2, int(window_days))
    gap = max(1, int(min_gap_days))

    samples: List[Dict[str, Any]] = []
    i = 0
    while i + window_days <= n:
        window = closes[i:i + window_days]
        cand_norm = normalize_curve(window, target_length=target_length)
        if cand_norm is None:
            i += 1
            continue
        sim = pearson_similarity(query_norm, cand_norm)
        if sim >= similarity_threshold:
            end_idx = i + window_days - 1  # 窗口最后一日（形态完成日）
            base = closes[end_idx]
            returns: Dict[int, float] = {}
            if base > 0:
                for h in horizons:
                    fut = end_idx + h
                    if fut < n:
                        returns[h] = closes[fut] / base - 1.0
            if returns:
                samples.append({
                    "similarity": float(sim),
                    "end_index": end_idx,
                    "returns": returns,
                })
                i += gap
                continue
            # 命中但无足够未来数据（接近序列末端）：继续右移，别卡死。
        i += 1
    return samples


def _summarise_horizon(horizon: int, returns: List[float]) -> Dict[str, Any]:
    wins = sum(1 for r in returns if r > 0)
    count = len(returns)
    return {
        "horizon": horizon,
        "count": count,
        "win_rate": round(wins / count, 4) if count else 0.0,
        "avg_return": round(statistics.fmean(returns), 6) if count else 0.0,
        "median_return": round(statistics.median(returns), 6) if count else 0.0,
        "best": round(max(returns), 6) if count else 0.0,
        "worst": round(min(returns), 6) if count else 0.0,
    }


def backtest_patterns(
    query_curve: Sequence[float],
    candidates: Sequence[Dict[str, Any]],
    fetch_klines: FetchKlines,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    history_days: int = DEFAULT_HISTORY_DAYS,
    min_gap_days: int = DEFAULT_MIN_GAP_DAYS,
    max_workers: int = DEFAULT_MAX_WORKERS,
    top_stocks: int = DEFAULT_TOP_STOCKS,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """对一组候选股票联网回测查询形态，返回汇总统计。

    ``candidates`` 每项需含 ``stock_code`` 与 ``symbol``（Sina 代码，如 ``sh600519``），
    可选 ``stock_name``。``fetch_klines(symbol, limit)`` 返回 ``(name, klines)``。
    """
    def _log(message: str) -> None:
        if progress_callback:
            try:
                progress_callback(message)
            except Exception:  # noqa: BLE001 — 日志失败不影响回测
                pass

    query_norm = normalize_curve(query_curve)
    if query_norm is None or len(query_norm) < 2:
        return {"ok": False, "error": "查询形态数据不足（至少需要 2 个有效点）"}

    candidates = [c for c in (candidates or []) if c.get("symbol")]
    if not candidates:
        return {"ok": False, "error": "没有可回测的候选股票"}

    horizons = [int(h) for h in horizons if int(h) > 0] or list(DEFAULT_HORIZONS)
    history_days = max(window_days + max(horizons) + 5, int(history_days))

    returns_by_horizon: Dict[int, List[float]] = {h: [] for h in horizons}
    per_stock_count: Dict[str, Dict[str, Any]] = {}
    errors: List[Dict[str, str]] = []
    scanned = 0
    sample_count = 0
    total = len(candidates)
    _log(f"开始回测：{total} 只候选股票 · 近 {history_days} 个交易日 · 窗口 {window_days} 日")

    def _work(candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Optional[str]]:
        symbol = str(candidate.get("symbol") or "")
        try:
            _name, klines = fetch_klines(symbol, history_days)
            closes = parse_close_series(klines)
            if len(closes) < window_days + max(horizons):
                return candidate, [], None  # 数据太短：算 0 样本，但不算错误
            samples = scan_series(
                closes,
                query_curve,
                window_days=window_days,
                horizons=horizons,
                similarity_threshold=similarity_threshold,
                min_gap_days=min_gap_days,
            )
            return candidate, samples, None
        except Exception as exc:  # noqa: BLE001 — 单股失败不阻断整体
            return candidate, None, str(exc)

    workers = max(1, min(int(max_workers), total))
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for candidate, samples, error in pool.map(_work, candidates):
            done += 1
            code = str(candidate.get("stock_code") or candidate.get("symbol") or "")
            if error is not None:
                if len(errors) < MAX_ERRORS_KEPT:
                    errors.append({"stock_code": code, "error": error})
                _log(f"[{done}/{total}] {code} 拉取失败：{error}")
                continue
            scanned += 1
            hit = len(samples or [])
            if hit:
                sample_count += hit
                per_stock_count[code] = {
                    "stock_code": code,
                    "stock_name": str(candidate.get("stock_name") or ""),
                    "count": hit,
                }
                for sample in samples:
                    for h, ret in sample["returns"].items():
                        if h in returns_by_horizon:
                            returns_by_horizon[h].append(ret)
            _log(f"[{done}/{total}] {code} 命中 {hit} 个相似样本")

    horizon_stats = [_summarise_horizon(h, returns_by_horizon[h]) for h in horizons]
    top = sorted(
        per_stock_count.values(),
        key=lambda r: (-r["count"], r["stock_code"]),
    )[:max(1, int(top_stocks))]

    _log(f"回测完成：命中 {sample_count} 个样本，成功扫描 {scanned}/{total} 只股票")
    return {
        "ok": True,
        "sample_count": sample_count,
        "candidates_total": total,
        "candidates_scanned": scanned,
        "window_days": int(window_days),
        "similarity_threshold": round(float(similarity_threshold), 4),
        "history_days": int(history_days),
        "horizons": horizon_stats,
        "top_stocks": top,
        "errors": errors,
    }
