"""资金榜路由 no_quant 参数接线测试(service 打桩,不建数据)。"""

import importlib
import sys

import pytest


@pytest.fixture()
def robyn_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_DISABLE_QUANT_RADAR_AUTOSAVE", "1")
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)
    module = importlib.import_module("webui.robyn_app")
    yield module
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)


class _StubSvc:
    def __init__(self):
        self.calls = []

    def moneyflow_ranking(self, **kw):
        self.calls.append(("moneyflow", kw))
        return {"kind": "moneyflow", "rows": [], "windows": {}}

    def dragon_tiger_ranking(self, **kw):
        self.calls.append(("dragon_tiger", kw))
        return {"kind": "dragon_tiger", "rows": [], "windows": {}}


def test_capital_routes_pass_no_quant(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    stub = _StubSvc()
    monkeypatch.setattr(robyn_module.webui_core, "CAPITAL_RANKINGS_SERVICE", stub)
    with TestClient(robyn_module.app) as client:
        # robyn TestClient 按纯路径匹配路由,query 须走 query_params 参数
        r1 = client.get("/api/capital-rankings/moneyflow",
                        query_params={"no_quant": "1"})
        r2 = client.get("/api/capital-rankings/moneyflow", query_params={})
        r3 = client.get("/api/capital-rankings/dragon-tiger",
                        query_params={"no_quant": "true"})
    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert stub.calls[0][1]["no_quant"] is True
    assert stub.calls[1][1]["no_quant"] is False
    assert stub.calls[2][0] == "dragon_tiger" and stub.calls[2][1]["no_quant"] is True
