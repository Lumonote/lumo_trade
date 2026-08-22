"""评分算法健康度服务。

数据源优先级(2026-07-09「全部走 SQLite」):
1. SQLite ``backtest_recommendation`` 表(与 auto_backtest 写侧同库);
2. 表空时回退扫描 results 目录(results_dir() + 额外搜索目录)中最新一份
   存量回测 CSV:``backtest_rebuilt_*.csv`` 或 ``backtest/recommendations.csv``。

计算:

- S/A/B/C 分档样本数、5 日胜率、平均收益(全量 + 最近 20 个交易日两组)
- 降级 run 占比(quant_score==0 或 score<50;降级=取数失败封顶,污染样本)
- 数据日期范围 / 基线胜率
- 逐日与滚动年化收益:口径见 ``analysis.backtest_metrics``(与报告「年化估算」
  同一实现——当日等权组合取算术均值,跨报告日几何链乘复利)

两处都无数据时返回 ``{"available": False}`` 的明确空态,前端显示「暂无回测数据」。
"""
from __future__ import annotations

import calendar
from pathlib import Path

import pandas as pd

from analysis.backtest_metrics import annualize_chained, annualize_cycle_return
from webui.services.paths import results_dir

TIER_ORDER = ("S", "A", "B", "C")
# 与报告/记忆中的置信度档位一致:S>=85, A>=78, B>=70, C<70
TIER_THRESHOLDS = ((85.0, "S"), (78.0, "A"), (70.0, "B"))
RECENT_DAYS = 20
RECENT_MONTH_DAYS = 31
B_RECENT_WINRATE_WARN = 0.45
# 与 opportunity_report_generator「历史回测表现」同口径:预留最近 N 个交易日
REPORT_RESERVE_TRADE_DAYS = 10


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


def _calendar_trade_days(anchor: pd.Timestamp) -> list[str]:
    """交易日历(YYYY-MM-DD 升序, <= anchor);拿不到或过陈旧(落后 anchor 20 天以上)返回 []。"""
    try:
        from data.cache.data_cache import get_trade_calendar

        anchor_ymd = anchor.strftime("%Y%m%d")
        days = sorted(str(d) for d in get_trade_calendar() if str(d) <= anchor_ymd)
        if days and days[-1] >= (anchor - pd.Timedelta(days=20)).strftime("%Y%m%d"):
            return [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in days]
    except Exception:  # noqa: BLE001 — 无缓存上下文时回退样本日代理
        pass
    return []


def _shift_one_month_back(anchor: pd.Timestamp) -> pd.Timestamp:
    """与报告生成器 _shift_one_month_back 一致:回退一个日历月,月末夹紧。"""
    year, month = anchor.year, anchor.month - 1
    if month == 0:
        year, month = year - 1, 12
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return pd.Timestamp(year=year, month=month, day=day)


def _report_window_block(df: pd.DataFrame) -> dict | None:
    """markdown 报告「历史回测表现」同口径统计块。

    以最新样本日为锚,预留最近 10 个交易日得 cutoff(等 5/10 日收益验证完),
    再向前回看 1 个自然月;分档沿用 canonical S/A/B/C。交易日历不可用时以
    样本日期为交易日代理(报告每个交易日落一批推荐,近似成立)。
    """
    valid = df[df["_report_dt"].notna()]
    if valid.empty:
        return None
    anchor = valid["_report_dt"].max()
    trade_days = _calendar_trade_days(anchor)
    if not trade_days:
        trade_days = sorted(valid["_report_dt"].dt.strftime("%Y-%m-%d").unique())
    if len(trade_days) <= REPORT_RESERVE_TRADE_DAYS:
        return None
    cutoff = pd.Timestamp(trade_days[-(REPORT_RESERVE_TRADE_DAYS + 1)])
    window_start = _shift_one_month_back(cutoff)
    sub = valid[(valid["_report_dt"] >= window_start) & (valid["_report_dt"] <= cutoff)]
    return {
        "window_start": window_start.strftime("%Y-%m-%d"),
        "cutoff": cutoff.strftime("%Y-%m-%d"),
        "reserve_trade_days": REPORT_RESERVE_TRADE_DAYS,
        "baseline": _stats(sub),
        "tiers": [{"tier": tier, "stats": _stats(sub[sub["tier"] == tier])} for tier in TIER_ORDER],
    }


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
        # 报告同口径块在任何用户区间过滤之前、按全量数据计算(口径固定,便于对数)
        report_window = _report_window_block(df)
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

        tiers = []
        for tier in TIER_ORDER:
            tiers.append({
                "tier": tier,
                "full": _stats(df[df["tier"] == tier]),
                "recent": _stats(recent[recent["tier"] == tier]),
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
                    "annualized_return": annualize_cycle_return(avg_return),
                    "avg_score": round(float(group["score"].mean()), 2) if len(group) else None,
                })
            # 滚动年化:窗口取最近 RECENT_DAYS 个「报告日」(无样本的空天照样占位,
            # 旧值不会因为中间空天而赖在窗口里),窗口内按可评估样本数加权几何链乘。
            # 当日 5 日收益尚未走完时不出数,否则前端会把上一日的陈旧值画成假平线。
            for index, row in enumerate(rows):
                if row["avg_return"] is None:
                    row["rolling_annualized_return"] = None
                    continue
                window = rows[max(0, index + 1 - RECENT_DAYS):index + 1]
                row["rolling_annualized_return"] = annualize_chained(
                    [item["avg_return"] for item in window],
                    [item["evaluable"] for item in window],
                )
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
            "rolling_window_days": RECENT_DAYS,
            "filter": {
                "start_date": filter_start.strftime("%Y-%m-%d") if filter_start is not None else "",
                "end_date": filter_end.strftime("%Y-%m-%d") if filter_end is not None else "",
                "window": "recent_month" if recent_month and start_date is None and end_date is None else ("custom" if filtered_by_range else "all"),
            },
            "total_rows": int(len(df)),
            "baseline": {"full": _stats(df), "recent": _stats(recent)},
            "tiers": tiers,
            "report_window": report_window,
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
