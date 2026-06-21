from analysis.stock_context import resolve_relations, _safe_float


def test_safe_float_coerces_na_and_strings():
    assert _safe_float("N/A") is None
    assert _safe_float(None) is None
    assert _safe_float("") is None
    assert _safe_float("12.5") == 12.5
    assert _safe_float(3) == 3.0


def test_resolve_relations_assembles_all_dimensions():
    rel = resolve_relations(
        "601702",
        boards_fn=lambda code: [{"name": "铜箔", "bk": "BK1"}, {"name": "PCB", "bk": "BK2"}],
        peers_fn=lambda code: [{"code": "002171", "name": "楚江新材", "reason": "同行"}],
        rings_fn=lambda boards: [{"ring": "AI产业链", "concepts": ["铜箔"]}],
        sector_fn=lambda code: {"sentiment_score": 61.0, "change_pct": 2.3},
    )
    assert [b["name"] for b in rel["boards"]] == ["铜箔", "PCB"]
    assert rel["peers"][0]["name"] == "楚江新材"
    assert rel["concept_rings"][0]["ring"] == "AI产业链"
    assert rel["sector_sentiment"]["sentiment_score"] == 61.0
    assert rel["degraded"] == []


def test_resolve_relations_degrades_failing_source_only():
    def boom(*a, **k):
        raise RuntimeError("net down")

    rel = resolve_relations(
        "601702",
        boards_fn=lambda code: [{"name": "铜箔", "bk": "BK1"}],
        peers_fn=boom,                      # 同行源失败
        rings_fn=lambda boards: [],
        sector_fn=lambda code: {"sentiment_score": 50.0},
    )
    assert rel["boards"][0]["name"] == "铜箔"   # 其它维度正常
    assert rel["peers"] == []                   # 失败维度降级空
    assert "peers" in rel["degraded"]
