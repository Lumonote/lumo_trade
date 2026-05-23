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


def test_get_suite_returns_jsonable_dict():
    fake = _FakeSuite()
    svc = StockSuiteService(orchestrator=fake)
    out = svc.get_suite("000001", name="平安银行")
    assert out["success"] is True
    assert out["stock"] == {"code": "000001", "name": "平安银行", "sector": "—", "market": "XSHE"}
    assert "overview" in out
    assert out["ai_interpretation"]["trigger_endpoint"] == "/api/stock-analysis-suite/000001/ai"


def test_get_suite_for_shanghai_market():
    """600/688/8 prefixes should map to XSHG."""
    svc = StockSuiteService(orchestrator=_FakeSuite())
    out = svc.get_suite("600519", name="贵州茅台")
    assert out["stock"]["market"] == "XSHG"


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
