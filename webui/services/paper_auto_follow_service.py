"""模拟盘自动跟单服务(机会报告 → 模拟盘前向验证闭环)。

机会挖掘报告生成后,按配置档位(默认 A 级 score>=78)对达档股票自动以
「次日开盘价」在模拟盘建仓;EOD 引擎里按持有天数(默认 5 个交易日)到期后
挂次日开盘价卖单平仓。等于给评分算法装上持续 walk-forward 前向验证。

幂等:同一报告日期 + 股票代码只下一次单(状态台账落 JSON 文件,key=
"YYYY-MM-DD:code"),重复解析同一报告/重跑同日挖掘不会重复建仓。

依赖注入:PaperTradingService、配置 loader(callable → dict)、事件服务均由
调用方注入,可离线测试(参照 tests/test_paper_auto_follow.py)。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = {
    "enabled": False,        # 默认关
    "min_score": 78.0,       # 最低档位:A 级
    "per_stock_amount": 20000.0,  # 单票金额(元)
    "hold_days": 5,          # 持有交易日数
    "price_type": "open",    # 买入方式:次日开盘价
}


def normalize_config(raw: dict | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    raw = raw or {}
    cfg["enabled"] = str(raw.get("enabled", cfg["enabled"])).strip().lower() in ("1", "true", "yes", "on")
    try:
        cfg["min_score"] = float(raw.get("min_score", cfg["min_score"]))
    except (TypeError, ValueError):
        pass
    try:
        amount = float(raw.get("per_stock_amount", cfg["per_stock_amount"]))
        if amount > 0:
            cfg["per_stock_amount"] = amount
    except (TypeError, ValueError):
        pass
    try:
        hold = int(raw.get("hold_days", cfg["hold_days"]))
        if hold > 0:
            cfg["hold_days"] = hold
    except (TypeError, ValueError):
        pass
    price_type = str(raw.get("price_type") or cfg["price_type"]).strip().lower()
    if price_type in ("open", "close"):
        cfg["price_type"] = price_type
    return cfg


def _report_date_from_filename(filename: str) -> str | None:
    match = re.search(r"_(\d{4})(\d{2})(\d{2})_\d{6}\.md$", str(filename or ""))
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


class PaperAutoFollowService:
    def __init__(self, paper_service, config_loader, state_path, *, events=None, now_fn=None):
        self._paper = paper_service
        self._config_loader = config_loader
        self._state_path = Path(state_path)
        self._events = events
        self._now_fn = now_fn or datetime.now
        self._lock = threading.Lock()

    # ----------------------------- 配置 / 状态 -----------------------------

    def config(self) -> dict:
        try:
            return normalize_config(self._config_loader() or {})
        except Exception:  # noqa: BLE001 — 配置读取失败按默认(关闭)处理
            return dict(DEFAULT_CONFIG)

    def _load_state(self) -> dict:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"entries": {}}

    def _save_state(self, state: dict) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._state_path)

    def entries(self) -> list[dict]:
        state = self._load_state()
        return sorted(state["entries"].values(), key=lambda e: str(e.get("created_at") or ""), reverse=True)

    def _emit(self, type_, title, message="", level="info", payload=None) -> None:
        if self._events is None:
            return
        try:
            self._events.push(type_, title, message, level=level, payload=payload)
        except Exception:  # noqa: BLE001 — 通知绝不阻断交易流程
            pass

    # ----------------------------- 报告跟单 -----------------------------

    def follow_report(self, report: dict, *, report_file: str | None = None) -> dict:
        """机会报告解析结果(_parse_opportunity_report 输出)→ 对达档股票建仓。

        返回 {"enabled", "placed", "skipped", "orders": [...]}; 开关关闭时不下单。
        """
        cfg = self.config()
        if not cfg["enabled"]:
            return {"enabled": False, "placed": 0, "skipped": 0, "orders": []}
        report = report or {}
        filename = report_file or report.get("file") or ""
        report_date = _report_date_from_filename(filename) or self._now_fn().strftime("%Y-%m-%d")
        placed, skipped, orders = 0, 0, []
        with self._lock:
            state = self._load_state()
            entries = state["entries"]
            for item in report.get("items") or []:
                code = str(item.get("code") or item.get("stock_code") or "").strip()
                try:
                    score = float(item.get("score") or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                if not re.fullmatch(r"\d{6}", code) or score < cfg["min_score"]:
                    continue
                key = f"{report_date}:{code}"
                if key in entries:   # 幂等:同一报告日期同一股票不重复下单
                    skipped += 1
                    continue
                order = self._paper.place_order(
                    code, "buy", cfg["price_type"],
                    amount=cfg["per_stock_amount"],
                    name=str(item.get("name") or item.get("stock_name") or ""),
                )
                entry = {
                    "key": key,
                    "report_date": report_date,
                    "report_file": filename,
                    "code": code,
                    "name": str(item.get("name") or item.get("stock_name") or ""),
                    "score": score,
                    "rating": item.get("rating") or "",
                    "buy_order_id": order.get("id"),
                    "sell_order_id": None,
                    "status": "rejected" if order.get("status") == "rejected" else "open",
                    "buy_fill_date": None,
                    "filled_qty": None,
                    "hold_days": cfg["hold_days"],
                    "created_at": self._now_fn().strftime("%Y-%m-%d %H:%M:%S"),
                    "note": order.get("note") or "",
                }
                entries[key] = entry
                if entry["status"] == "open":
                    placed += 1
                    orders.append({"code": code, "order_id": order.get("id"), "score": score})
            self._save_state(state)
        if placed:
            self._emit(
                "auto_follow_buy",
                f"自动跟单已建仓 {placed} 只",
                f"报告 {report_date} 达档(≥{cfg['min_score']:.0f}分)股票已挂次日开盘价买单",
                payload={"report_date": report_date, "orders": orders},
            )
        return {"enabled": True, "placed": placed, "skipped": skipped, "orders": orders}

    # ----------------------------- EOD 到期平仓 -----------------------------

    def process_eod(self, date=None, *, ohlcv_loader=None) -> dict:
        """EOD 钩子:同步买单成交状态 → 到期持仓挂次日开盘卖单 → 收尾已平仓单。

        即使开关已关闭,也继续管理既有在途仓位(只停新开仓,不弃既有持仓)。"""
        date = str(date) if date else self._now_fn().strftime("%Y-%m-%d")
        exits_placed, closed, synced = 0, 0, 0
        with self._lock:
            state = self._load_state()
            for entry in state["entries"].values():
                try:
                    before = entry.get("status")
                    self._sync_entry(entry, date, ohlcv_loader)
                    after = entry.get("status")
                    if before != after:
                        synced += 1
                    if after == "closing" and before in ("open",):
                        exits_placed += 1
                    if after == "closed" and before != "closed":
                        closed += 1
                except Exception:  # noqa: BLE001 — 单票异常不影响其余跟单单
                    continue
            self._save_state(state)
        return {"date": date, "exits_placed": exits_placed, "closed": closed, "changed": synced}

    def _sync_entry(self, entry: dict, date: str, ohlcv_loader) -> None:
        status = entry.get("status")
        if status in ("closed", "rejected"):
            return
        if status == "open":
            order = self._paper.get_order(entry.get("buy_order_id")) if entry.get("buy_order_id") else None
            if not order:
                entry["status"] = "rejected"
                return
            if order.get("status") == "rejected":
                entry["status"] = "rejected"
                entry["note"] = order.get("note") or "买单被拒"
                return
            if order.get("status") != "filled":
                return   # 仍在等开盘撮合
            entry["buy_fill_date"] = str(order.get("filled_at") or "")[:10] or None
            entry["filled_qty"] = int(order.get("filled_qty") or 0)
            held = self._trading_days_held(entry["code"], entry["buy_fill_date"], date, ohlcv_loader)
            if held is not None and held >= int(entry.get("hold_days") or 0) and entry["filled_qty"] >= 100:
                sell = self._paper.place_order(
                    entry["code"], "sell", "open",
                    qty=entry["filled_qty"], name=entry.get("name") or "",
                )
                entry["sell_order_id"] = sell.get("id")
                if sell.get("status") == "rejected":
                    # 持仓已被手动卖出等情形:无可平仓位,直接收尾
                    entry["status"] = "closed"
                    entry["note"] = sell.get("note") or "卖单被拒"
                else:
                    entry["status"] = "closing"
                    self._emit(
                        "auto_follow_exit",
                        f"自动跟单到期平仓 {entry.get('name') or entry['code']}",
                        f"持有 {held} 个交易日到期,已挂次日开盘价卖单({entry['filled_qty']}股)",
                        payload={"code": entry["code"], "order_id": sell.get("id")},
                    )
            return
        if status == "closing":
            sell = self._paper.get_order(entry.get("sell_order_id")) if entry.get("sell_order_id") else None
            if not sell:
                entry["status"] = "closed"
                return
            if sell.get("status") == "rejected":
                entry["status"] = "closed"
                entry["note"] = sell.get("note") or "卖单被拒"
                return
            if sell.get("status") == "filled":
                entry["status"] = "closed"
                entry["sell_fill_date"] = str(sell.get("filled_at") or "")[:10] or None
                realized = self._realized_for_order(sell.get("id"))
                if realized is not None:
                    entry["realized_pnl"] = realized
                self._emit(
                    "auto_follow_closed",
                    f"自动跟单已平仓 {entry.get('name') or entry['code']}",
                    (f"已实现盈亏 {realized:+,.2f} 元" if realized is not None else "卖单已成交"),
                    level=("info" if (realized or 0) >= 0 else "warn"),
                    payload={"code": entry["code"], "realized_pnl": realized},
                )

    def _trading_days_held(self, code, buy_date, as_of, ohlcv_loader) -> int | None:
        """买入成交日之后(严格)至 as_of(含)之间该股的交易日根数;无日K返回 None。"""
        if not buy_date:
            return None
        loader = ohlcv_loader
        if loader is None:
            from webui.services.paper_trading_service import _load_daily
            loader = _load_daily
        try:
            df = loader(code)
        except Exception:  # noqa: BLE001
            return None
        if df is None or len(df) == 0:
            return None
        held = 0
        for ts in df["timestamps"]:
            day = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
            if buy_date < day <= as_of:
                held += 1
        return held

    def _realized_for_order(self, order_id) -> float | None:
        if not order_id:
            return None
        try:
            for trade in self._paper.trades(limit=200):
                if trade.get("order_id") == order_id and trade.get("realized_pnl") is not None:
                    return float(trade["realized_pnl"])
        except Exception:  # noqa: BLE001
            return None
        return None
