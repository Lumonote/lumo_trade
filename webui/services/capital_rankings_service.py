"""资金榜单服务:主力买入榜(moneyflow)+ 龙虎榜(dragon_tiger_list)。

提供单日 / 多日聚合查询、可选叠加实时报价、回填 N 天。报价(quote_provider)
与取数(fetcher / dates)均可注入,便于离线测试与数据源切换。

资金榜全市场快照统一落 moneyflow_dc 的哨兵 top_n=0,隔离 opportunity
discovery 写入的正 top_n 快照。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

import pandas as pd

from data_store import dragon_tiger_list_repo, dragon_tiger_repo, moneyflow_repo

logger = logging.getLogger(__name__)

SNAPSHOT_TOP_N = 0  # 资金榜全市场快照哨兵
MONEYFLOW_AMOUNT_UNIT = "万元"
_TS_INST_SIDE = {"0": "buy", "1": "sell", "buy": "buy", "sell": "sell"}
_QUANT_KEYWORDS = ("量化", "DMA", "程序化", "算法")


def _bare_code(ts_code: str) -> str:
    return str(ts_code or "").split(".")[0].strip()


def _to_iso(d) -> str:
    """'YYYYMMDD' / Timestamp / 'YYYY-MM-DD' → 'YYYY-MM-DD'。"""
    if d is None:
        return ""
    s = str(d).strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return s


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _str(v) -> str:
    try:
        if v is None or pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)


def _json_value(v):
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, TypeError):
            pass
    return v if isinstance(v, (str, int, float, bool)) else str(v)


def _sum_nums(*values):
    nums = [_num(v) for v in values]
    nums = [v for v in nums if v is not None]
    return sum(nums) if nums else None


def _inst_amount_total(row: dict[str, Any]) -> float:
    buy = _num(row.get("buy_amount")) or 0.0
    sell = _num(row.get("sell_amount")) or 0.0
    return buy + sell


def _inst_name_is_generic(name: str) -> bool:
    return bool(re.fullmatch(r"机构(买入|卖出)\(\d+家\)", str(name or "").strip()))


def _classify_quant_name(name: str) -> tuple[int, float]:
    is_quant = int(any(k in (name or "") for k in _QUANT_KEYWORDS))
    return is_quant, 0.6 if is_quant else 0.0


def _inst_side(value) -> str:
    text = _str(value).strip()
    mapped = _TS_INST_SIDE.get(text)
    if mapped:
        return mapped
    n = _num(value)
    if n == 0:
        return "buy"
    if n == 1:
        return "sell"
    return text or "buy"


def _moneyflow_like(cols: set[str]) -> bool:
    return bool(
        {"buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount", "amount_unit"} & cols
    )


def _raw_payload(raw_json) -> dict[str, Any]:
    raw = _str(raw_json).strip()
    if not raw:
        return {}
    merged: dict[str, Any] = {}
    for payload in _raw_payload_rows(raw):
        for key, value in payload.items():
            if key not in merged or merged.get(key) in (None, ""):
                merged[key] = value
    return merged


def _raw_payload_rows(raw_json) -> list[dict[str, Any]]:
    raw = _str(raw_json).strip()
    if not raw:
        return []
    rows: list[dict[str, Any]] = []
    for part in raw.splitlines():
        part = part.strip()
        if not part:
            continue
        try:
            payload = json.loads(part)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            rows.append({str(k): _json_value(v) for k, v in payload.items()})
    return rows


def backfill_outcome(summary: dict) -> dict:
    """把各 kind 的回填结果汇总成 job 级判定。

    返回 ``{"rows": 总入库行数, "errors": 去重后的错误列表, "ok": bool}``。
    全部 0 行且有错误 → ``ok=False``(让无效 Token / 取数失败在「任务」里显形,
    不再静默成「回填完成 0 行」);只要有任意行入库即视为成功(部分日期失败仅记日志)。
    """
    total = 0
    errors: list[str] = []
    for kind, s in (summary or {}).items():
        s = s or {}
        total += int(s.get("rows") or 0)
        total += int(s.get("inst_rows") or 0)
        for item in s.get("errors") or []:
            msg = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else str(item)
            label = f"{kind}: {msg}" if msg else str(kind)
            if label not in errors:
                errors.append(label)
        for item in s.get("inst_errors") or []:
            msg = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else str(item)
            label = f"{kind}机构席位: {msg}" if msg else f"{kind}机构席位"
            if label not in errors:
                errors.append(label)
    return {"rows": total, "errors": errors, "ok": not (total == 0 and bool(errors))}


class CapitalRankingsService:
    def __init__(self, quote_provider: Optional[Callable[[list], dict]] = None):
        # quote_provider(codes:list[str]) -> {bare_code: {price, change_pct, main_net_inflow,...}}
        self._quote_provider = quote_provider

    # ---------------- 查询 ----------------

    def moneyflow_ranking(
        self,
        date=None,
        days=1,
        top_n=50,
        mode="single",
        with_quotes=True,
        start_date=None,
        end_date=None,
    ) -> dict:
        if mode == "aggregate" and start_date and end_date:
            as_of = end_date
            df = moneyflow_repo.get_range_aggregated(
                start_date,
                end_date,
                limit=top_n,
                snapshot_top_n=SNAPSHOT_TOP_N,
                sort_by="main_buy_amount",
            )
            return self._envelope("moneyflow", mode, as_of, days, top_n, df, with_quotes, start_date, end_date)
        if mode == "aggregate":
            as_of = date or moneyflow_repo.latest_date(SNAPSHOT_TOP_N)
            df = (moneyflow_repo.get_aggregated(as_of, days=days, limit=top_n,
                                                snapshot_top_n=SNAPSHOT_TOP_N)
                  if as_of else None)
        else:
            as_of = date or moneyflow_repo.latest_date(SNAPSHOT_TOP_N)
            df = (moneyflow_repo.get_ranking(as_of, limit=top_n, snapshot_top_n=SNAPSHOT_TOP_N)
                  if as_of else None)
        return self._envelope("moneyflow", mode, as_of, days, top_n, df, with_quotes)

    def dragon_tiger_ranking(
        self,
        date=None,
        days=1,
        top_n=50,
        mode="single",
        with_quotes=True,
        start_date=None,
        end_date=None,
    ) -> dict:
        if mode == "aggregate" and start_date and end_date:
            as_of = end_date
            df = dragon_tiger_list_repo.get_range_aggregated(
                start_date,
                end_date,
                top_n=top_n,
                sort_by="l_buy",
            )
            return self._envelope("dragon_tiger", mode, as_of, days, top_n, df, with_quotes, start_date, end_date)
        if mode == "aggregate":
            as_of = date or dragon_tiger_list_repo.latest_date()
            df = (dragon_tiger_list_repo.get_aggregated(as_of, days=days, top_n=top_n)
                  if as_of else None)
        else:
            as_of = date or dragon_tiger_list_repo.latest_date()
            df = dragon_tiger_list_repo.get_top_n(as_of, top_n) if as_of else None
        return self._envelope("dragon_tiger", mode, as_of, days, top_n, df, with_quotes)

    def _envelope(self, kind, mode, as_of, days, top_n, df, with_quotes, start_date=None, end_date=None) -> dict:
        rows = self._normalize(df)
        if with_quotes:
            rows = self._attach_quotes(rows)
        windows = self._window_rankings(kind, as_of, top_n, with_quotes) if as_of else {}
        return {
            "kind": kind,
            "mode": mode,
            "as_of": as_of,
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n,
            "count": len(rows),
            "rows": rows,
            "windows": windows,
        }

    def _window_rankings(self, kind, as_of, top_n, with_quotes) -> dict:
        windows: dict[str, dict[str, Any]] = {}
        for days in (5, 30):
            if kind == "moneyflow":
                df = moneyflow_repo.get_aggregated(
                    as_of,
                    days=days,
                    limit=top_n,
                    snapshot_top_n=SNAPSHOT_TOP_N,
                    sort_by="main_buy_amount",
                )
            else:
                df = dragon_tiger_list_repo.get_aggregated(
                    as_of,
                    days=days,
                    top_n=top_n,
                    sort_by="l_buy",
                )
            rows = self._normalize(df)
            if with_quotes:
                rows = self._attach_quotes(rows)
            windows[str(days)] = {"days": days, "count": len(rows), "rows": rows}
        return windows

    def _normalize(self, df) -> list:
        rows: list[dict[str, Any]] = []
        if df is None or getattr(df, "empty", True):
            return rows
        cols = set(df.columns)
        has_lc = "list_count" in cols
        institution_cache: dict[str, pd.DataFrame] = {}
        for i, (_, r) in enumerate(df.iterrows(), start=1):
            ts_code = _str(r.get("ts_code"))
            raw = {c: _json_value(r.get(c)) for c in df.columns}
            detail_rows = _raw_payload_rows(r.get("raw_json"))
            raw.update({k: _json_value(v) for k, v in _raw_payload(r.get("raw_json")).items()})
            moneyflow_row = _moneyflow_like(cols)
            amount_unit = _str(r.get("amount_unit")) if "amount_unit" in cols else ""
            if not amount_unit and moneyflow_row:
                amount_unit = MONEYFLOW_AMOUNT_UNIT
            if amount_unit and not raw.get("amount_unit"):
                raw["amount_unit"] = amount_unit
            if moneyflow_row:
                for detail in detail_rows:
                    if not detail.get("amount_unit") and not detail.get("_amount_unit"):
                        detail["amount_unit"] = amount_unit or MONEYFLOW_AMOUNT_UNIT
            main_buy_amount = (
                _num(r.get("main_buy_amount")) if "main_buy_amount" in cols
                else _sum_nums(r.get("buy_elg_amount"), r.get("buy_lg_amount"))
            )
            retail_buy_amount = (
                _num(r.get("retail_buy_amount")) if "retail_buy_amount" in cols
                else _sum_nums(r.get("buy_md_amount"), r.get("buy_sm_amount"))
            )
            row = {
                "rank": i,
                "code": _bare_code(ts_code),
                "ts_code": ts_code,
                "name": _str(r.get("name")),
                "trade_date": _str(r.get("trade_date")) if "trade_date" in cols else None,
                "net_amount": _num(r.get("net_amount")),
                "net_amount_rate": _num(r.get("net_amount_rate")) if "net_amount_rate" in cols else None,
                "buy_elg_amount": _num(r.get("buy_elg_amount")) if "buy_elg_amount" in cols else None,
                "buy_elg_amount_rate": _num(r.get("buy_elg_amount_rate")) if "buy_elg_amount_rate" in cols else None,
                "buy_lg_amount": _num(r.get("buy_lg_amount")) if "buy_lg_amount" in cols else None,
                "buy_lg_amount_rate": _num(r.get("buy_lg_amount_rate")) if "buy_lg_amount_rate" in cols else None,
                "buy_md_amount": _num(r.get("buy_md_amount")) if "buy_md_amount" in cols else None,
                "buy_md_amount_rate": _num(r.get("buy_md_amount_rate")) if "buy_md_amount_rate" in cols else None,
                "buy_sm_amount": _num(r.get("buy_sm_amount")) if "buy_sm_amount" in cols else None,
                "buy_sm_amount_rate": _num(r.get("buy_sm_amount_rate")) if "buy_sm_amount_rate" in cols else None,
                "main_buy_amount": main_buy_amount,
                "retail_buy_amount": retail_buy_amount,
                "amount_unit": amount_unit,
                "close": _num(r.get("close")) if "close" in cols else None,
                "pct_change": _num(r.get("pct_change")) if "pct_change" in cols else None,
                "list_count": (int(r["list_count"]) if has_lc and not pd.isna(r["list_count"]) else None),
                "first_date": _str(r.get("first_date")) if "first_date" in cols else None,
                "last_date": _str(r.get("last_date")) if "last_date" in cols else None,
                "turnover_rate": _num(r.get("turnover_rate")) if "turnover_rate" in cols else None,
                "amount": _num(r.get("amount")) if "amount" in cols else None,
                "l_buy": _num(r.get("l_buy")) if "l_buy" in cols else None,
                "l_sell": _num(r.get("l_sell")) if "l_sell" in cols else None,
                "l_amount": _num(r.get("l_amount")) if "l_amount" in cols else None,
                "net_rate": _num(r.get("net_rate")) if "net_rate" in cols else None,
                "amount_rate": _num(r.get("amount_rate")) if "amount_rate" in cols else None,
                "reason_count": (int(r["reason_count"]) if "reason_count" in cols and not pd.isna(r["reason_count"]) else None),
                "reason": _str(r.get("reason")) if "reason" in cols else "",
                "last_price": None,
                "change_pct": None,
                "quoted": False,
                "detail_rows": detail_rows,
                "raw": raw,
            }
            row.update(self._institution_summary(row, institution_cache))
            rows.append(row)
        return rows

    def _institution_summary(self, row: dict[str, Any], cache: dict[str, pd.DataFrame]) -> dict[str, Any]:
        ts_code = row.get("ts_code") or row.get("code")
        if not ts_code:
            return {"institution_rows": []}
        start = _to_iso(row.get("trade_date") or row.get("first_date") or "")
        end = _to_iso(row.get("trade_date") or row.get("last_date") or row.get("first_date") or "")
        if not start and not end:
            return {"institution_rows": []}
        try:
            df = cache.get(str(ts_code))
            if df is None:
                df = dragon_tiger_repo.get_by_code(str(ts_code))
                cache[str(ts_code)] = df
        except Exception as exc:  # noqa: BLE001 - 机构席位缺失不能阻断榜单
            logger.warning("capital rankings institution attach failed %s: %s", ts_code, exc)
            return {"institution_rows": []}
        if df is None or getattr(df, "empty", True):
            return {"institution_rows": []}

        work = df.copy()
        if "trade_date" in work.columns:
            work["trade_date"] = work["trade_date"].map(_to_iso)
        if start and end:
            work = work[(work["trade_date"] >= start) & (work["trade_date"] <= end)]
        elif start:
            work = work[work["trade_date"] >= start]
        elif end:
            work = work[work["trade_date"] <= end]
        if work.empty:
            return {"institution_rows": []}

        records: list[dict[str, Any]] = []
        for _, inst in work.sort_values(
            by=["trade_date", "buy_amount", "net_amount"],
            ascending=[False, False, False],
            na_position="last",
        ).iterrows():
            buy = _num(inst.get("buy_amount"))
            sell = _num(inst.get("sell_amount"))
            net = _num(inst.get("net_amount"))
            quant_confidence = _num(inst.get("quant_confidence"))
            if quant_confidence is None:
                quant_text = _str(inst.get("quant_confidence")).strip()
                quant_confidence = quant_text or None
            if net is None and (buy is not None or sell is not None):
                net = (buy or 0.0) - (sell or 0.0)
            records.append({
                "trade_date": _to_iso(inst.get("trade_date")),
                "inst_name": _str(inst.get("inst_name")),
                "side": _str(inst.get("side")),
                "buy_amount": buy,
                "sell_amount": sell,
                "net_amount": net,
                "is_quant": int(_num(inst.get("is_quant")) or 0),
                "quant_confidence": quant_confidence,
                "reason": _str(inst.get("reason")),
            })
        if not records:
            return {"institution_rows": []}

        buy_total = sum((_num(r.get("buy_amount")) or 0.0) for r in records)
        sell_total = sum((_num(r.get("sell_amount")) or 0.0) for r in records)
        net_total = sum((_num(r.get("net_amount")) or 0.0) for r in records)
        amount_total = buy_total + sell_total
        daily_rows = self._institution_daily_summary(records)

        by_name: dict[str, dict[str, Any]] = {}
        for inst in records:
            name = _str(inst.get("inst_name")).strip()
            if not name:
                continue
            item = by_name.setdefault(name, {"name": name, "buy": 0.0, "net": 0.0, "amount": 0.0})
            item["buy"] += _num(inst.get("buy_amount")) or 0.0
            item["net"] += _num(inst.get("net_amount")) or 0.0
            item["amount"] += _inst_amount_total(inst)
        name_items = list(by_name.values())
        specific_names = [item for item in name_items if not _inst_name_is_generic(item["name"])]
        if specific_names:
            name_items = specific_names
        name_items.sort(key=lambda x: (x["buy"], x["net"], x["amount"], x["name"]), reverse=True)
        display_names = [item["name"] for item in name_items[:8]]
        if len(name_items) > 8:
            display_names.append(f"等{len(name_items)}家")

        return {
            "institution_rows": records,
            "institution_daily_rows": daily_rows,
            "institution_buy_amount": buy_total,
            "institution_sell_amount": sell_total,
            "institution_net_amount": net_total,
            "institution_amount": amount_total,
            "institution_count": len(by_name),
            "main_institution_names": " / ".join(display_names),
        }

    @staticmethod
    def _institution_daily_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_date: dict[str, dict[str, Any]] = {}
        names_by_date: dict[str, set[str]] = {}
        buy_names_by_date: dict[str, set[str]] = {}
        for inst in records:
            trade_date = _str(inst.get("trade_date")).strip()
            if not trade_date:
                continue
            item = by_date.setdefault(trade_date, {
                "trade_date": trade_date,
                "institution_buy_amount": 0.0,
                "institution_sell_amount": 0.0,
                "institution_net_amount": 0.0,
                "institution_amount": 0.0,
                "institution_count": 0,
                "buy_institution_count": 0,
            })
            buy = _num(inst.get("buy_amount")) or 0.0
            sell = _num(inst.get("sell_amount")) or 0.0
            net = _num(inst.get("net_amount")) or (buy - sell)
            item["institution_buy_amount"] += buy
            item["institution_sell_amount"] += sell
            item["institution_net_amount"] += net
            item["institution_amount"] += buy + sell
            name = _str(inst.get("inst_name")).strip()
            if name:
                names_by_date.setdefault(trade_date, set()).add(name)
                if buy > 0:
                    buy_names_by_date.setdefault(trade_date, set()).add(name)
        for trade_date, item in by_date.items():
            item["institution_count"] = len(names_by_date.get(trade_date, set()))
            item["buy_institution_count"] = len(buy_names_by_date.get(trade_date, set()))
        return sorted(by_date.values(), key=lambda x: x["trade_date"], reverse=True)

    def _attach_quotes(self, rows: list) -> list:
        if not self._quote_provider or not rows:
            return rows
        codes = [r["code"] for r in rows if r["code"]]
        try:
            qmap = self._quote_provider(codes) or {}
        except Exception as exc:  # noqa: BLE001 — 报价失败降级,不阻断榜单
            logger.warning("capital rankings quote attach failed: %s", exc)
            return rows
        for r in rows:
            q = qmap.get(r["code"])
            if not q:
                continue
            r["last_price"] = _num(q.get("price"))
            r["change_pct"] = _num(q.get("change_pct"))
            mni = _num(q.get("main_net_inflow"))
            if mni is not None:
                r["live_main_net_inflow"] = mni
            r["quoted"] = True
        return rows

    # ---------------- 回填 ----------------

    def backfill(self, kinds=("moneyflow", "dragon_tiger"), days=30, *, dates=None,
                 moneyflow_fetcher=None, dragon_tiger_fetcher=None,
                 dragon_tiger_inst_fetcher=None, pro=None) -> dict:
        explicit_dates = dates is not None
        if dates is None:
            from data_store import tushare_client
            dates = tushare_client.recent_trade_dates(days) or []
        if not dates:
            # 拿不到任何交易日:多半是 Token 无效(trade_cal 被拒)或没配 Token。
            # 显式报错而非静默 0 行,否则 UI 只会看到「回填完成」却「暂无数据」。
            from data_store import tushare_client
            reason = (
                "Tushare Token 无效或 trade_cal 调用失败,无法获取交易日历。请在「设置」中检查 Tushare Token。"
                if tushare_client.available()
                else "Tushare 未配置或不可用(缺少 Token)。请在「设置」中配置有效的 Tushare Token。"
            )
            return {k: {"dates": 0, "ok_dates": 0, "rows": 0, "errors": [("", reason)]}
                    for k in kinds}
        summary: dict[str, Any] = {}
        if "moneyflow" in kinds:
            mf_dates = dates
            mf_skipped: list[str] = []
            if not explicit_dates:
                existing = moneyflow_repo.existing_dates(dates, SNAPSHOT_TOP_N)
                mf_dates = [d for d in dates if _to_iso(d) not in existing]
                mf_skipped = [d for d in dates if _to_iso(d) in existing]
            summary["moneyflow"] = self._backfill_moneyflow(mf_dates, moneyflow_fetcher, pro)
            summary["moneyflow"]["requested_dates"] = len(dates)
            summary["moneyflow"]["skipped_dates"] = len(mf_skipped)
        if "dragon_tiger" in kinds:
            from analysis.institutional import dragon_tiger_list_provider
            summary["dragon_tiger"] = dragon_tiger_list_provider.backfill_recent(
                dates=dates, fetcher=dragon_tiger_fetcher, pro=pro, skip_existing=not explicit_dates,
            )
            inst_summary = self._backfill_dragon_tiger_inst(
                dates,
                fetcher=dragon_tiger_inst_fetcher,
                pro=pro,
                skip_when_list_fetcher_injected=dragon_tiger_fetcher is not None,
            )
            if inst_summary:
                summary["dragon_tiger"]["inst_rows"] = inst_summary.get("rows", 0)
                summary["dragon_tiger"]["inst_ok_dates"] = inst_summary.get("ok_dates", 0)
                summary["dragon_tiger"]["inst_errors"] = inst_summary.get("errors", [])
        return summary

    def _backfill_moneyflow(self, dates, fetcher, pro) -> dict:
        if fetcher is None:
            if pro is None:
                from data_store import tushare_client
                pro = tushare_client.get_pro()
            if pro is None:
                return {"dates": 0, "ok_dates": 0, "rows": 0,
                        "errors": [("", "tushare pro unavailable")]}

            def fetcher(d):  # noqa: E306
                if hasattr(pro, "moneyflow_dc"):
                    return pro.moneyflow_dc(trade_date=d)
                return pro.moneyflow_ths(trade_date=d)

        total_rows = 0
        ok = 0
        errors: list[tuple[str, str]] = []
        for d in dates:
            try:
                df = fetcher(d)
            except Exception as exc:  # noqa: BLE001
                errors.append((str(d), str(exc)))
                logger.warning("moneyflow_dc fetch failed %s: %s", d, exc)
                continue
            ok += 1
            if df is None or len(df) == 0:
                continue
            work = df.copy()
            if "trade_date" in work.columns:
                work["trade_date"] = work["trade_date"].map(_to_iso)
            else:
                work["trade_date"] = _to_iso(d)
            if "_amount_unit" not in work.columns and "amount_unit" not in work.columns:
                work["_amount_unit"] = MONEYFLOW_AMOUNT_UNIT
            total_rows += moneyflow_repo.upsert_df(work, top_n=SNAPSHOT_TOP_N)

        from data_store import sync_log_repo
        status = "ok" if not errors else ("partial" if ok else "failed")
        sync_log_repo.append("capital_moneyflow", "", status=status, rows=total_rows,
                             error=("; ".join(f"{dt}:{m}" for dt, m in errors) or None))
        return {"dates": len(dates), "ok_dates": ok, "rows": total_rows, "errors": errors}

    def _backfill_dragon_tiger_inst(
        self,
        dates,
        *,
        fetcher=None,
        pro=None,
        skip_when_list_fetcher_injected: bool = False,
    ) -> dict | None:
        """同步 Tushare top_inst 机构席位,让榜单明细能列出机构名称和买卖额。"""
        if fetcher is None:
            if pro is None:
                if skip_when_list_fetcher_injected:
                    return None
                from data_store import tushare_client
                pro = tushare_client.get_pro()
            if pro is None or not hasattr(pro, "top_inst"):
                return None

            def fetcher(d):  # noqa: E306
                return pro.top_inst(trade_date=d)

        total_rows = 0
        ok = 0
        errors: list[tuple[str, str]] = []
        for d in dates:
            try:
                df = fetcher(d)
            except Exception as exc:  # noqa: BLE001
                errors.append((str(d), str(exc)))
                logger.warning("top_inst fetch failed %s: %s", d, exc)
                continue
            ok += 1
            if df is None or len(df) == 0:
                continue
            rows: list[dict[str, Any]] = []
            for _, r in df.iterrows():
                code = _str(r.get("ts_code")).strip()
                inst_name = (_str(r.get("exalter")).strip() or _str(r.get("inst_name")).strip())
                if not code or not inst_name:
                    continue
                is_quant = _num(r.get("is_quant"))
                quant_confidence = _num(r.get("quant_confidence"))
                if is_quant is None:
                    is_quant, fallback_conf = _classify_quant_name(inst_name)
                    if quant_confidence is None:
                        quant_confidence = fallback_conf
                rows.append({
                    "ts_code": code,
                    "trade_date": _to_iso(r.get("trade_date") or d),
                    "inst_name": inst_name,
                    "side": _inst_side(r.get("side")),
                    "net_amount": _num(r.get("net_buy")) if "net_buy" in df.columns else _num(r.get("net_amount")),
                    "buy_amount": _num(r.get("buy")) if "buy" in df.columns else _num(r.get("buy_amount")),
                    "sell_amount": _num(r.get("sell")) if "sell" in df.columns else _num(r.get("sell_amount")),
                    "is_quant": int(is_quant or 0),
                    "quant_confidence": quant_confidence,
                    "reason": _str(r.get("reason")),
                })
            total_rows += dragon_tiger_repo.upsert_rows(rows)
        return {"dates": len(dates), "ok_dates": ok, "rows": total_rows, "errors": errors}
