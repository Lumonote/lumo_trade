"""吸筹埋伏榜 API 接线测试:参数透传与非法 window 回退(payload 打桩,不建市场数据)。"""

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


def test_accumulation_route_passes_params(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    calls = []

    def fake_payload(window=40, date="", force=False, no_quant=False, **kw):
        calls.append({"window": window, "date": date, "force": force,
                      "no_quant": no_quant})
        return {"ok": True, "window": window, "count": 0, "stocks": [],
                "data_date": "", "note": "", "disclaimer": "d"}

    monkeypatch.setattr(robyn_module.quant_radar_service,
                        "accumulation_payload", fake_payload)
    with TestClient(robyn_module.app) as client:
        # robyn TestClient 按纯路径匹配路由,query 须走 query_params 参数
        resp = client.get("/api/quant-radar/accumulation",
                          query_params={"window": "20", "date": "2026-07-01", "refresh": "1"})
        resp_bad = client.get("/api/quant-radar/accumulation",
                              query_params={"window": "999"})
        resp_nq = client.get("/api/quant-radar/accumulation",
                             query_params={"no_quant": "1"})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert calls[0] == {"window": 20, "date": "2026-07-01", "force": True,
                        "no_quant": False}
    assert resp_bad.status_code == 200
    assert calls[1]["window"] == 40      # 非法 window 回退
    assert resp_nq.status_code == 200
    assert calls[2]["no_quant"] is True
