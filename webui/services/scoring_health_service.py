"""评分算法健康度服务。

数据源优先级(2026-07-09「全部走 SQLite」):
1. SQLite ``backtest_recommendation`` 表(与 auto_backtest 写侧同库);
2. 表空时回退扫描 results 目录(results_dir() + 额外搜索目录)中最新一份
   存量回测 CSV:``backtest_rebuilt_*.csv`` 或 ``backtest/recommendations.csv``。

计算:

- S/A/B/C 分档样本数、5 日胜率、平均收益(全量 + 最近 20 个交易日两组)
- 降级 run 占比(quant_score==0 或 score<50;降级=取数失败封顶,污染样本)
- 数据日期范围 / 基线胜率

两处都无数据时返回 ``{"available": False}`` 的明确空态,前端显示「暂无回测数据」。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from webui.services.paths import results_dir

TIER_ORDER = ("S", "A", "B", "C")
# 与报告/记忆中的置信度档位一致:S>=85, A>=78, B>=70, C<70
TIER_THRESHOLDS = ((85.0, "S"), (78.0, "A"), (70.0, "B"))
RECENT_DAYS = 20
RECENT_MONTH_DAYS = 31
B_RECENT_WINRATE_WARN = 0.45


def _tier(score: float) -> str:
    for threshold, name in TIER_THRESHOLDS:
        if score >= threshold:
            return name
    return "C"


def _clean_cell(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _clean_code(value) -> str:
    text = _clean_cell(value)
    if not text:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if 1 <= len(digits) <= 6:
        return digits.zfill(6)
    return text


def _annualized_from_5d_return(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        ret = float(value) / 100.0
    except (TypeError, ValueError):
        return None
    if ret <= -1:
        return None
    return round((((1 + ret) ** (252 / 5)) - 1) * 100, 2)


class ScoringHealthService:
    def __init__(self, search_dirs=None):
        # 默认仅 results_dir()(桌面/打包/CLI 的统一报告目录);调用方可附加目录。
        self._search_dirs = [Path(p) for p in (search_dirs or [results_dir()])]

    def latest_csv(self) -> Path | None:
        candidates: list[Path] = []
        for directory in self._search_dirs:
            try:
                if directory.exists():
                    candidates.extend(p for p in directory.glob("backtest_rebuilt_*.csv") if p.is_file())
                    recommendations = directory / "backtest" / "recommendations.csv"
                    if recommendations.is_file():
                        candidates.append(recommendations)
            except OSError:
                continue
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _load_frame(self):
        """加载回测样本帧:SQLite 优先,空表回退存量 CSV。

        Returns:
            (df, src) — src 是 {"file","path","source"};两处都没有时 (None, None)。
            CSV 读取失败时抛出原异常由调用方降级。
        """
        try:
            from data_store import backtest_recommendation_repo as _btr
            from data_store import connection as _db_conn
            db_df = _btr.load_df()
            if len(db_df) > 0:
                return db_df, {
                    "file": "backtest_recommendation",
                    "path": str(_db_conn.db_path()),
                    "source": "sqlite",
                }
        except Exception:  # noqa: BLE001 — 无 data_store 上下文时按 CSV 兜底
            pass
        path = self.latest_csv()
        if path is None:
            return None, None
        df = pd.read_csv(path, encoding="utf-8-sig")
        return df, {
            "file": path.name,
            "path": str(path),
            "source": "recommendations" if path.name == "recommendations.csv" else "rebuilt",
        }

    def health(self, start_date: str | None = None, end_date: str | None = None,
               recent_month: bool = False) -> dict:
        try:
            df, src = self._load_frame()
        except Exception as exc:  # noqa: BLE001 — 读取失败按空态降级
            return {"available": False, "message": f"回测数据读取失败: {exc}"}
        if df is None:
            return {"available": False, "message": "暂无回测数据(SQLite backtest_recommendation 为空,且未找到 backtest_rebuilt_*.csv 或 backtest/recommendations.csv)"}
        required = {"report_date", "score", "return_5d"}
        if df.empty or not required.issubset(df.columns):
            return {"available": False, "message": "回测数据缺少必需列(report_date/score/return_5d)"}

        df = df.copy()
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
        df["return_5d"] = pd.to_numeric(df["return_5d"], errors="coerce")
        if "quant_score" in df.columns:
            df["quant_score"] = pd.to_numeric(df["quant_score"], errors="coerce")
        else:
            df["quant_score"] = pd.NA
        df = df[df["score"].notna()]
        if df.empty:
            return {"available": False, "message": "回测数据无有效评分行"}
        df["tier"] = df["score"].apply(_tier)
        df["degraded"] = (df["quant_score"].fillna(-1) == 0) | (df["score"] < 50)

        df["report_date"] = df["report_date"].astype(str)
        df["_report_dt"] = pd.to_datetime(df["report_date"], errors="coerce")
        all_dates = sorted(str(d) for d in df["report_date"].dropna().unique())
        all_valid_dates = df["_report_dt"].dropna()
        requested_start = pd.to_datetime(start_date, errors="coerce") if start_date else pd.NaT
        requested_end = pd.to_datetime(end_date, errors="coerce") if end_date else pd.NaT
        filter_start = requested_start if pd.notna(requested_start) else None
        filter_end = requested_end if pd.notna(requested_end) else None
        if recent_month and filter_start is None and filter_end is None and not all_valid_dates.empty:
            filter_end = all_valid_dates.max()
            filter_start = filter_end - pd.Timedelta(days=RECENT_MONTH_DAYS)

        filtered_by_range = filter_start is not None or filter_end is not None
        explicit_range = (start_date is not None or end_date is not None)
        if filter_start is not None:
            df = df[df["_report_dt"].notna() & (df["_report_dt"] >= filter_start)]
        if filter_end is not None:
            df = df[df["_report_dt"].notna() & (df["_report_dt"] <= filter_end)]
        if df.empty:
            return {
                "available": False,
                "message": "所选区间无有效回测样本",
                "file": src["file"],
                "source": src["source"],
                "available_date_range": {
                    "start": all_dates[0] if all_dates else None,
                    "end": all_dates[-1] if all_dates else None,
                    "days": len(all_dates),
                },
                "filter": {
                    "start_date": filter_start.strftime("%Y-%m-%d") if filter_start is not None else "",
                    "end_date": filter_end.strftime("%Y-%m-%d") if filter_end is not None else "",
                    "window": "recent_month" if recent_month else "custom",
                },
            }
        dates = sorted(str(d) for d in df["report_date"].dropna().unique())
        valid_dates = df["_report_dt"].dropna()
        if filtered_by_range:
            recent = df
        elif not valid_dates.empty:
            recent_start = valid_dates.max() - pd.Timedelta(days=RECENT_MONTH_DAYS)
            recent = df[df["_report_dt"].notna() & (df["_report_dt"] >= recent_start)]
        else:
            recent_dates = set(dates[-RECENT_DAYS:])
            recent = df[df["report_date"].isin(recent_dates)]

        def _stats(frame: pd.DataFrame) -> dict:
            evaluable = frame[frame["return_5d"].notna()]
            n = int(len(evaluable))
            if n == 0:
                return {"n": int(len(frame)), "evaluable": 0, "win_rate": None, "avg_return": None}
            return {
                "n": int(len(frame)),
                "evaluable": n,
                "win_rate": round(float((evaluable["return_5d"] > 0).mean()), 4),
                "avg_return": round(float(evaluable["return_5d"].mean()), 4),
            }

        tiers = []
        for tier in TIER_ORDER:
            full = _stats(df[df["tier"] == tier])
            rec = _stats(recent[recent["tier"] == tier])
            tiers.append({
                "tier": tier,
                "full": full,
                "recent": rec,
            })

        b_recent = next(t for t in tiers if t["tier"] == "B")["recent"]
        b_recent_wr = b_recent.get("win_rate")
        degraded_count = int(df["degraded"].sum())
        recent_degraded = int(recent["degraded"].sum()) if len(recent) else 0

        def _daily(frame: pd.DataFrame) -> list[dict]:
            rows = []
            for date, group in frame.groupby(frame["report_date"].astype(str), sort=True):
                stats = _stats(group)
                avg_return = stats["avg_return"]
                rows.append({
                    "date": date,
                    "n": stats["n"],
                    "evaluable": stats["evaluable"],
                    "win_rate": stats["win_rate"],
                    "avg_return": avg_return,
                    "annualized_return": _annualized_from_5d_return(avg_return),
                    "avg_score": round(float(group["score"].mean()), 2) if len(group) else None,
                })
            rolling_values: list[float] = []
            for row in rows:
                value = row.get("avg_return")
                if value is not None:
                    rolling_values.append(float(value))
                if rolling_values:
                    window = rolling_values[-RECENT_DAYS:]
                    row["rolling_annualized_return"] = _annualized_from_5d_return(sum(window) / len(window))
                else:
                    row["rolling_annualized_return"] = None
            return rows

        top_rows = (
            recent[recent["return_5d"].notna()]
            .sort_values("return_5d", ascending=False)
            .head(8)
        )
        lag_rows = (
            recent[recent["return_5d"].notna()]
            .sort_values("return_5d", ascending=True)
            .head(8)
        )

        def _sample_rows(frame: pd.DataFrame) -> list[dict]:
            out = []
            for _, row in frame.iterrows():
                code = _clean_code(row.get("code"))
                name = _clean_cell(row.get("name"))
                out.append({
                    "date": str(row.get("report_date") or ""),
                    "code": code,
                    "name": name or code,
                    "score": round(float(row.get("score")), 2) if pd.notna(row.get("score")) else None,
                    "tier": str(row.get("tier") or ""),
                    "return_5d": round(float(row.get("return_5d")), 4) if pd.notna(row.get("return_5d")) else None,
                })
            return out

        return {
            "available": True,
            "file": src["file"],
            "path": src["path"],
            "source": src["source"],
            "available_date_range": {
                "start": all_dates[0] if all_dates else None,
                "end": all_dates[-1] if all_dates else None,
                "days": len(all_dates),
            },
            "date_range": {
                "start": dates[0] if dates else None,
                "end": dates[-1] if dates else None,
                "days": len(dates),
            },
            "recent_window_days": int(recent["report_date"].nunique()) if len(recent) else 0,
            "recent_window_label": "所选区间" if explicit_range else "最近1个月",
            "filter": {
                "start_date": filter_start.strftime("%Y-%m-%d") if filter_start is not None else "",
                "end_date": filter_end.strftime("%Y-%m-%d") if filter_end is not None else "",
                "window": "recent_month" if recent_month and start_date is None and end_date is None else ("custom" if filtered_by_range else "all"),
            },
            "total_rows": int(len(df)),
            "baseline": {"full": _stats(df), "recent": _stats(recent)},
            "tiers": tiers,
            "degraded": {
                "count": degraded_count,
                "ratio": round(degraded_count / len(df), 4) if len(df) else 0.0,
                "recent_count": recent_degraded,
                "recent_ratio": round(recent_degraded / len(recent), 4) if len(recent) else 0.0,
            },
            "daily": _daily(df),
            "top_recent": _sample_rows(top_rows),
            "lag_recent": _sample_rows(lag_rows),
            "warnings": {
                # B 级近 20 日胜率 < 45% → 退化警示(前端显示徽章)
                "b_tier_recent_degraded": bool(b_recent_wr is not None and b_recent_wr < B_RECENT_WINRATE_WARN),
            },
        }
