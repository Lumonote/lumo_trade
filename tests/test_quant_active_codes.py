"""quant_active_codes:『量化资金参与』代码集 resolver(活跃度≥50 ∪ 近5日量化席位)。"""
from __future__ import annotations

import pytest


@pytest.fixture
def svc(monkeypatch):
    from webui.services import quant_radar_service as svc
    # 每个用例清缓存,互不串扰
    monkeypatch.setattr(svc, "_quant_codes_cache", {"ts": 0.0, "data": None})
    return svc


def _patch_sources(monkeypatch, svc, dates, day_items, seats):
    from data_store import quant_radar_repo
    monkeypatch.setattr(quant_radar_repo, "list_dates", lambda limit=1: dates)
    monkeypatch.setattr(
        quant_radar_repo, "get_day",
        lambda d, limit=0, min_activity=0, **kw: day_items)
    monkeypatch.setattr(svc, "_quant_seats_window", lambda days=5: seats)


def test_union_of_activity_and_seats(svc, monkeypatch):
    _patch_sources(monkeypatch, svc,
                   dates=["2026-07-21"],
                   day_items=[{"code": "600001"}, {"code": "000002"}],
                   seats={"300003": [{"inst_name": "量化基金专用"}]})
    info = svc.quant_active_codes()
    assert info["codes"] == {"600001", "000002", "300003"}
    assert info["as_of"] == "2026-07-21"
    assert info["available"] is True


def test_seats_only_still_available(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=[], day_items=[],
                   seats={"300003": [{"inst_name": "DMA席位"}]})
    info = svc.quant_active_codes()
    assert info["codes"] == {"300003"}
    assert info["as_of"] is None
    assert info["available"] is True


def test_both_sources_empty_unavailable(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=[], day_items=[], seats={})
    info = svc.quant_active_codes()
    assert info["codes"] == set()
    assert info["available"] is False


def test_ttl_cache_and_force(svc, monkeypatch):
    _patch_sources(monkeypatch, svc, dates=["2026-07-21"],
                   day_items=[{"code": "600001"}], seats={})
    first = svc.quant_active_codes()
    # 换数据源:缓存内不生效,force 才重算
    _patch_sources(monkeypatch, svc, dates=["2026-07-22"],
                   day_items=[{"code": "000009"}], seats={})
    assert svc.quant_active_codes() is first
    assert svc.quant_active_codes(force=True)["codes"] == {"000009"}


def test_source_exception_swallowed(svc, monkeypatch):
    from data_store import quant_radar_repo
    monkeypatch.setattr(quant_radar_repo, "list_dates",
                        lambda limit=1: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(svc, "_quant_seats_window", lambda days=5: {})
    info = svc.quant_active_codes()
    assert info["codes"] == set()
    assert info["available"] is False


# ---------- 吸筹榜 no_quant ----------

def test_apply_no_quant_filters_copy_not_mutate(svc, monkeypatch):
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": {"600001"}, "as_of": "2026-07-21", "available": True})
    payload = {"ok": True, "count": 2,
               "stocks": [{"code": "600001", "name": "量"}, {"code": "000002", "name": "非"}]}
    out = svc._apply_no_quant(payload, True)
    assert [s["code"] for s in out["stocks"]] == ["000002"]
    assert out["count"] == 1 and out["quant_filtered"] == 1
    assert out["no_quant"] is True and out["quant_criteria_available"] is True
    # 原 payload(=缓存/kv里的对象)不被改动
    assert payload["count"] == 2 and len(payload["stocks"]) == 2


def test_apply_no_quant_off_is_identity(svc):
    payload = {"ok": True, "count": 0, "stocks": []}
    assert svc._apply_no_quant(payload, False) is payload


def test_apply_no_quant_unavailable_noop(svc, monkeypatch):
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": set(), "as_of": None, "available": False})
    payload = {"ok": True, "count": 1, "stocks": [{"code": "600001"}]}
    out = svc._apply_no_quant(payload, True)
    assert out["count"] == 1 and out["quant_filtered"] == 0
    assert out["quant_criteria_available"] is False


def test_accumulation_payload_no_quant_wired(svc, monkeypatch):
    # 注入式离线:market_rows_fn 返回 None → items 空;只验证 no_quant 键接上了
    monkeypatch.setattr(svc, "quant_active_codes",
                        lambda force=False: {"codes": set(), "as_of": None, "available": True})
    out = svc.accumulation_payload(window=40, market_rows_fn=lambda end, w: None,
                                   no_quant=True)
    assert out["no_quant"] is True and out["quant_filtered"] == 0
    out_off = svc.accumulation_payload(window=40, market_rows_fn=lambda end, w: None)
    assert "no_quant" not in out_off  # 关闭时 payload 形状与现状一致
