"""Orchestrates existing signals into the command-center 大屏 payload.

Pure orchestration: every data source is injected as a callable so the service
is testable without I/O. Each source degrades independently — a failing source
sets a `degraded[...]` flag and leaves its panel empty rather than crashing.

机会 items 由 core 从 SQLite(``opportunity_run``/``opportunity_item``)取出,
每条自带 ``signals``(风险信号 + 板块拥挤度分)。本服务不读任何报告文件。
"""
from analysis import risk_opportunity_engine as eng


class CommandCenterService:
    def __init__(self, *, load_report, capital_rankings, market_env, holdings, quotes,
                 hot_membership=None, news_index=None, hot_news=None,
                 market_pulse=None):
        self._load_report = load_report
        self._capital_rankings = capital_rankings
        self._market_env = market_env
        self._holdings = holdings
        self._quotes = quotes
        # 持仓·热点关联两源(纯注入)。缺省为空源 → 面板仍列出持仓但全「脱离」,不崩。
        self._hot_membership = hot_membership or (lambda *a, **k: {})
        self._news_index = news_index or (lambda *a, **k: {})
        # 东财热点新闻源(纯注入)。缺省空源 → 撮合矩阵右栏显示占位文案,不崩。
        self._hot_news = hot_news or (lambda *a, **k: [])
        # 指数风向 + 板块拐点(纯注入)。缺省空源 → 两个分区留空,不崩。
        self._market_pulse = market_pulse or (lambda *a, **k: {})

    def _safe(self, fn, default):
        try:
            return fn(), False
        except Exception:
            return default, True

    @staticmethod
    def _item_signals(item):
        sig = item.get("signals")
        return dict(sig) if isinstance(sig, dict) else {}

    def overview(self, *, quotes_only=False, report=None, available_dates=None):
        degraded = {}
        if report is None:
            report, d = self._safe(self._load_report, {"items": []})
            degraded["opportunity"] = d or not report.get("items")
        else:
            report = report or {"items": []}
            degraded["opportunity"] = not report.get("items")
        menv, d = self._safe(self._market_env, {})
        degraded["market_env"] = d
        hold, d = self._safe(self._holdings,
                             {"account": {}, "positions": [], "max_drawdown": 0.0})
        degraded["holdings"] = d
        cap, d = self._safe(self._capital_rankings, {"rows": []})
        degraded["capital"] = d

        market = eng.score_market_risk(menv)
        held_codes = {p.get("ts_code") for p in hold.get("positions", [])}

        matrix = []
        has_signals = False
        for item in report.get("items", []):
            code = item.get("code") or item.get("stock_code")
            sig = self._item_signals(item)
            has_signals = has_signals or bool(sig)
            sector_crowd = eng.score_sector_crowding(sig)
            matrix.append(eng.build_target(
                item, sig, sector_crowding=sector_crowd,
                market_backdrop=market["risk"], held=code in held_codes))

        portfolio = eng.score_portfolio_risk(
            hold.get("account", {}), hold.get("positions", []),
            max_drawdown=hold.get("max_drawdown", 0.0))

        # 持仓 · 热点关联(逐源独立降级:某源抛错只置该面板 degraded,不影响其余)。
        positions = hold.get("positions", [])
        membership, dms = self._safe(lambda: self._hot_membership(report.get("date")), {})
        degraded["hot_sector"] = dms
        news_idx, dnw = self._safe(lambda: self._news_index(positions), {})
        degraded["news"] = dnw
        holdings_relevance = eng.score_holdings_relevance(positions, membership, news_idx)

        # 东财热点新闻(撮合矩阵右栏):优先按当前报告精确读本次 run,避免回退旧热点。
        hot_news, dhn = self._safe(
            lambda: self._hot_news(report.get("date"), report_file=report.get("file")),
            [],
        )
        degraded["hot_news"] = dhn

        pulse, dmp = self._safe(self._market_pulse, {})
        degraded["market_pulse"] = dmp

        indices = {
            "market_risk": round(eng.market_risk_index(
                market["risk"], menv.get("sentiment")), 0),
            "opportunity": round(eng.opportunity_index(report.get("items", [])), 0),
            "sentiment": round(float(menv.get("sentiment") or 50), 0),
        }
        return {
            # ``sidecar`` 是前端状态条沿用的键名:结构化风险信号是否已加载。
            "as_of": {"report": report.get("file"), "count": len(matrix),
                      "sidecar": has_signals,
                      "date": report.get("date"),
                      "report_count": report.get("report_count",
                                                 1 if report.get("items") else 0)},
            "indices": indices,
            "market_env": menv,
            "matrix": matrix,
            "portfolio": portfolio,
            "holdings_relevance": holdings_relevance,
            "hot_news": hot_news,
            "rankings": {"capital": cap.get("rows", [])},
            "market_pulse": pulse,
            "available_dates": list(available_dates or []),
            "degraded": degraded,
        }
