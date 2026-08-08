import pytest
from webui.services.stock_suite_service import StockSuiteService


class _FakeSuite:
    def __init__(self):
        self.calls = []

    def get_full_payload(self, code):
        self.calls.append(("get", code))
        return {
            "overview": {"radar": {}},
            "risk_control": {"available": True},
            "cached_reports": {},
            "ai_interpretation": {
                "status": "not_generated",
                "report": None,
                "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": f"/api/stock-analysis-suite/{code}/ai",
            },
            "stub_tabs": [],
            "warnings": [],
        }

    def trigger_ai_interpretation(self, code, name, model_full_key=None, force_refresh=False):
        self.calls.append(("ai", code, force_refresh))
        return {
            "success": True,
            "status": "ready",
            "report": "## md",
            "token_usage": 100,
            "generated_at": "2026-05-23T14:32:05",
            "cached_path": "reports/stock_suite/000001_x.md",
        }


def test_get_suite_returns_jsonable_dict(monkeypatch):
    # Pin sector resolution to its graceful-degradation default so the assertion
    # does not depend on Tushare cache availability in the test environment.
    monkeypatch.setattr(
        "webui.services.stock_suite_service._resolve_sector",
        lambda code: ("—", ""),
    )
    monkeypatch.setattr(
        "webui.services.stock_suite_service._resolve_boards",
        lambda code: (),
    )
    fake = _FakeSuite()
    svc = StockSuiteService(orchestrator=fake)
    out = svc.get_suite("000001", name="平安银行")
    assert out["success"] is True
    assert out["stock"] == {
        "code": "000001",
        "name": "平安银行",
        "sector": "—",
        "boards": [],
        "market": "XSHE",
    }
    assert "overview" in out
    assert out["ai_interpretation"]["trigger_endpoint"] == "/api/stock-analysis-suite/000001/ai"
    assert "capital_rankings" in out


def test_get_suite_recomputes_risk_control_with_realtime_price():
    class _PriceAwareSuite(_FakeSuite):
        def compute_risk_control(self, code, current_price=None):
            self.calls.append(("risk", code, current_price))
            return {
                "available": True,
                "scaled_entry": [{"label": "现价建仓", "price": current_price}],
            }

    fake = _PriceAwareSuite()
    svc = StockSuiteService(orchestrator=fake)

    out = svc.get_suite("000001", name="平安银行", current_price=66.66)

    assert ("risk", "000001", 66.66) in fake.calls
    assert out["risk_control"]["scaled_entry"][0]["price"] == 66.66


def test_get_suite_for_shanghai_market():
    """600/688/8 prefixes should map to XSHG."""
    svc = StockSuiteService(orchestrator=_FakeSuite())
    out = svc.get_suite("600519", name="贵州茅台")
    assert out["stock"]["market"] == "XSHG"


def test_get_suite_accepts_beijing_920_code():
    """北交所新代码段 920xxx 应通过校验（修复 'invalid stock code' → 数据源暂不可用）。"""
    svc = StockSuiteService(orchestrator=_FakeSuite())
    out = svc.get_suite("920161", name="某北交所股")
    assert out["success"] is True
    assert out["stock"]["code"] == "920161"


def test_trigger_ai_proxies_to_orchestrator():
    fake = _FakeSuite()
    svc = StockSuiteService(orchestrator=fake)
    out = svc.trigger_ai_interpretation("000001", name="平安银行", force_refresh=True)
    assert out["success"] is True
    assert fake.calls[0] == ("ai", "000001", True)


def test_get_suite_validates_code():
    svc = StockSuiteService(orchestrator=_FakeSuite())
    with pytest.raises(ValueError):
        svc.get_suite("")
    with pytest.raises(ValueError):
        svc.get_suite("INVALID")
    with pytest.raises(ValueError):
        svc.get_suite("12345")  # too short


def test_get_suite_handles_orchestrator_error():
    class _ErrSuite:
        def get_full_payload(self, code):
            raise RuntimeError("boom")

    svc = StockSuiteService(orchestrator=_ErrSuite())
    out = svc.get_suite("000001", name="x")
    assert out["success"] is False
    assert "boom" in out["error"]
    assert out["stock"]["code"] == "000001"


def test_get_capital_rankings_returns_stock_summary():
    captured = {}

    class _FakeCapital:
        def stock_capital_summary(self, code, **kwargs):
            captured["code"] = code
            captured["kwargs"] = kwargs
            return {"code": code, "data_status": "fresh"}

    svc = StockSuiteService(orchestrator=_FakeSuite())
    svc._capital_rankings = _FakeCapital()

    out = svc.get_capital_rankings(
        "000001",
        date="2026-06-04",
        days=10,
        start_date="2026-06-01",
        end_date="2026-06-04",
    )

    assert out["success"] is True
    assert out["capital_rankings"]["code"] == "000001"
    assert captured == {
        "code": "000001",
        "kwargs": {
            "date": "2026-06-04",
            "days": 10,
            "start_date": "2026-06-01",
            "end_date": "2026-06-04",
        },
    }


def test_get_suite_degrades_when_capital_rankings_fail():
    class _FailingCapital:
        def stock_capital_summary(self, code, **kwargs):
            raise RuntimeError("db locked")

    svc = StockSuiteService(orchestrator=_FakeSuite())
    svc._capital_rankings = _FailingCapital()

    out = svc.get_suite("000001", name="x")

    assert out["success"] is True
    assert out["capital_rankings"]["data_status"] == "unavailable"
    assert "db locked" in out["capital_rankings"]["reason"]


# --- 重载一致性：已审阅 overlay 在展示层 merge 进 panel（spec §7 P0-A 终检补强）---
# 重载走 GET→get_suite→get_full_payload，拿到的是「原始 panel + 已审阅 overlay（reviewed=True）」。
# 若不在展示层 merge，则持久化的金句 override / 逐人 insight 不可见，且与「刚点重生成」时
# trigger_panel_overlay 返回的 merged_panel 不一致。merge 只能落在 get_suite 这个展示边界——
# compute/cache/regenerate 仍须喂原始 panel 给 LLM（否则模型会看到自己上一轮的金句作基线）。


def _baseline_panel():
    """规则基线 panel：punchline 为规则文案，analysts 无 insight。"""
    return {
        "data_status": "fresh",
        "great_divide": {
            "bull": {"id": "zhao", "name": "赵老哥"},
            "bear": {"id": "graham", "name": "格雷厄姆"},
            "punchline": "规则基线金句",
        },
        "analysts": [
            {"id": "zhao", "name": "赵老哥", "headline": "量化席位活跃"},
            {"id": "graham", "name": "格雷厄姆", "headline": "估值偏贵"},
        ],
    }


def _reviewed_overlay():
    """已审阅历史 overlay：金句 override + 逐人 insight。重载读历史 → data_status=stale，reviewed 保留 True。"""
    return {
        "data_status": "stale",
        "reviewed": True,
        "tier": "deep",
        "great_divide_override": {"punchline": "LLM 升档金句"},
        "panel_insights": {"zhao": "量化席位进场，打板情绪高"},
        "risks": ["估值透支"],
        "buy_zones": {"value": [], "growth": [], "technical": [], "youzi": []},
        "narrative_override": "多头占优但防估值",
    }


class _OverlaySuite:
    """get_full_payload 按引用返回同一 payload（模拟编排器 5 分钟缓存按引用返回 cached[1]）。"""

    def __init__(self, panel, overlay):
        self.payload = {
            "overview": {"radar": {}},
            "risk_control": {"available": True},
            "cached_reports": {},
            "ai_interpretation": {
                "status": "not_generated", "report": None, "token_usage": None,
                "generated_at": None,
                "trigger_endpoint": "/api/stock-analysis-suite/000001/ai",
            },
            "stub_tabs": [], "warnings": [],
            "panel": panel,
            "analysis_overlay": overlay,
        }

    def get_full_payload(self, code):
        return self.payload


def test_get_suite_merges_reviewed_overlay_into_panel_on_reload():
    """重载时，已审阅 overlay 的金句/逐人 insight 应在展示层 merge 进 panel。"""
    panel = _baseline_panel()
    fake = _OverlaySuite(panel, _reviewed_overlay())
    svc = StockSuiteService(orchestrator=fake)
    out = svc.get_suite("000001", name="x")
    # 金句被 override
    assert out["panel"]["great_divide"]["punchline"] == "LLM 升档金句"
    # 逐人 insight 挂到对应 analyst
    zhao = next(a for a in out["panel"]["analysts"] if a["id"] == "zhao")
    assert zhao["insight"] == "量化席位进场，打板情绪高"
    # 源 panel（缓存对象）不被原地改写 —— 否则会污染下次重生成喂给 LLM 的规则基线
    assert panel["great_divide"]["punchline"] == "规则基线金句"
    assert all("insight" not in a for a in panel["analysts"])


def test_get_suite_leaves_panel_raw_when_overlay_not_reviewed():
    """未生成/未审阅 overlay（reviewed=False）时不 merge，panel 保持规则基线（向后兼容）。"""
    panel = _baseline_panel()
    overlay = {
        "data_status": "unavailable", "reviewed": False, "tier": "lite",
        "great_divide_override": None, "panel_insights": {}, "risks": [],
        "buy_zones": None, "narrative_override": None,
    }
    svc = StockSuiteService(orchestrator=_OverlaySuite(panel, overlay))
    out = svc.get_suite("000001", name="x")
    assert out["panel"]["great_divide"]["punchline"] == "规则基线金句"
    assert all("insight" not in a for a in out["panel"]["analysts"])
