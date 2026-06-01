import datetime

from analysis.pattern_store import Fingerprint
from webui.services.pattern_search_service import PatternSearchService


def test_status_reports_unavailable_for_empty_store(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")

    status = service.status()

    assert status["available"] is False
    assert status["total_stocks"] == 0
    assert status["warning"] == "指纹库尚未生成，请先点击刷新"


def test_match_validates_curve_shape(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")

    result, status = service.match({"curve": [1, 2, 3]})

    assert status == 400
    assert "curve 必须" in result["error"]


def test_search_stocks_and_stock_curve(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")
    store = service.get_store()
    store.upsert_fingerprints(
        [
            Fingerprint(
                stock_code="600000",
                stock_name="浦发银行",
                market="SH",
                industry="银行",
                normalized_curve=[0.0, 0.2, 0.4, 1.0],
                mean_slope=0.2,
                latest_close=10.5,
                latest_change_pct=1.2,
                snapshot_date=datetime.date(2026, 5, 20),
            )
        ]
    )

    search = service.search_stocks("600", limit=5)
    curve, status = service.stock_curve("600000")

    assert search["count"] == 1
    assert search["stocks"][0]["stock_code"] == "600000"
    assert status == 200
    assert curve["stock_name"] == "浦发银行"
    assert curve["snapshot_date"] == "2026-05-20"


def test_refresh_params_are_capped():
    service = PatternSearchService("unused.sqlite")

    params = service.refresh_params({"limit": "99999", "workers": "999"})

    assert params == {"limit": 10000, "workers": 64, "data_source": "auto"}


def test_refresh_params_accept_data_source_alias():
    service = PatternSearchService("unused.sqlite")

    params = service.refresh_params({"source": "tushare", "workers": "2"})

    assert params == {"limit": None, "workers": 2, "data_source": "tushare"}


def test_save_and_list_saved_patterns(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")

    saved, status = service.save_pattern(
        {"normalized_curve": [0.0, 0.3, 0.7, 1.0], "name": "突破形态", "window_days": 30}
    )

    assert status == 200
    assert saved["pattern"]["id"] >= 1
    assert saved["pattern"]["name"] == "突破形态"
    assert saved["pattern"]["normalized_curve"] == [0.0, 0.3, 0.7, 1.0]

    listing = service.list_saved_patterns()
    assert listing["count"] == 1
    assert listing["patterns"][0]["id"] == saved["pattern"]["id"]


def test_save_pattern_validates_curve(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")

    too_short, status = service.save_pattern({"normalized_curve": [1.0]})
    assert status == 400
    assert "normalized_curve" in too_short["error"]

    non_numeric, status = service.save_pattern({"normalized_curve": ["a", "b"]})
    assert status == 400


def test_save_pattern_auto_names_when_blank(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")

    saved, status = service.save_pattern({"normalized_curve": [0.0, 0.5, 1.0]})

    assert status == 200
    assert saved["pattern"]["name"].startswith("形态 ")


def test_get_and_delete_saved_pattern(tmp_path):
    service = PatternSearchService(tmp_path / "patterns.sqlite")
    saved, _ = service.save_pattern({"normalized_curve": [0.0, 0.4, 1.0], "name": "待删"})
    pid = saved["pattern"]["id"]

    one, status = service.get_saved_pattern(pid)
    assert status == 200 and one["pattern"]["name"] == "待删"

    missing, status = service.get_saved_pattern(999999)
    assert status == 404

    deleted, status = service.delete_saved_pattern(pid)
    assert status == 200 and deleted["deleted"] is True

    again, status = service.delete_saved_pattern(pid)
    assert status == 404


# ---- 兜底搜索：指纹库未覆盖时回退全 A 索引，消除「没有匹配股票」假阴性 ----

_FAKE_UNIVERSE = [
    {"stock_code": "688111", "stock_name": "金山办公", "market": "沪市", "industry": "软件服务"},
    {"stock_code": "600519", "stock_name": "贵州茅台", "market": "沪市", "industry": "白酒"},
]


def test_search_stocks_falls_back_to_universe_on_fingerprint_miss(tmp_path):
    """指纹库为空 → 名称/代码均应命中全 A 索引（兜底源被调用）。"""
    calls: list = []

    def provider():
        calls.append(1)
        return list(_FAKE_UNIVERSE)

    service = PatternSearchService(tmp_path / "patterns.sqlite", universe_provider=provider)

    by_name = service.search_stocks("金山", limit=5)
    assert by_name["count"] == 1
    assert by_name["stocks"][0]["stock_code"] == "688111"
    assert by_name["stocks"][0]["in_fingerprint"] is False

    by_code = service.search_stocks("688111", limit=5)
    assert by_code["stocks"][0]["stock_name"] == "金山办公"
    assert calls  # 兜底数据源确被调用


def test_search_stocks_valid_code_passthrough_when_universe_unavailable(tmp_path):
    """全 A 索引取不到（离线）时，合法 6 位代码仍直接放行；非代码关键词不造假阳性。"""
    service = PatternSearchService(tmp_path / "patterns.sqlite", universe_provider=lambda: [])

    out = service.search_stocks("688111", limit=5)
    assert out["count"] == 1
    assert out["stocks"][0]["stock_code"] == "688111"
    assert out["stocks"][0]["in_fingerprint"] is False

    empty = service.search_stocks("不存在的名字XYZ", limit=5)
    assert empty["count"] == 0


def test_search_stocks_prefers_fingerprint_and_skips_universe(tmp_path):
    """指纹命中时绝不触发兜底（优先级 + 不做多余网络）。"""
    called: list = []

    def provider():
        called.append(1)
        return list(_FAKE_UNIVERSE)

    service = PatternSearchService(tmp_path / "patterns.sqlite", universe_provider=provider)
    service.get_store().upsert_fingerprints([
        Fingerprint(
            stock_code="600000", stock_name="浦发银行", market="SH", industry="银行",
            normalized_curve=[0.0, 0.2, 0.4, 1.0], mean_slope=0.2, latest_close=10.5,
            latest_change_pct=1.2, snapshot_date=datetime.date(2026, 5, 20),
        )
    ])

    out = service.search_stocks("600000", limit=5)
    assert out["count"] == 1
    assert out["stocks"][0]["stock_code"] == "600000"
    assert called == []  # 指纹库已命中，不触发兜底

