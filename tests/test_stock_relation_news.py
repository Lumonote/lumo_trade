from analysis.stock_relation_news import collect_related_news, content_hash, RELATION_TIERS


def test_content_hash_stable_and_host_based():
    h1 = content_hash("某股大涨", "http://a.com/1")
    h2 = content_hash("某股大涨 ", "http://a.com/2")  # 同标题同host → 同hash
    assert h1 == h2


def test_collect_classifies_and_dedups_by_priority():
    relations = {
        "boards": [{"name": "铜箔"}],
        "peers": [{"name": "楚江新材", "reason": "同行"}],
        "concept_rings": [{"ring": "AI产业链", "concepts": ["铜箔"]}],
    }
    dup = {"title": "铜箔涨价", "url": "http://x.com/1", "source": "东财",
           "published_at": "2026-06-20"}
    items = collect_related_news(
        "601702", relations,
        stock_news_fn=lambda code: [dict(dup)],                     # direct
        sector_news_fn=lambda names: [dict(dup)],                   # board（与 direct 重复）
        hot_news_fn=lambda boards: [{"title": "政策利好新能源", "url": "http://y/2",
                                      "source": "金十", "published_at": "2026-06-20"}],
        orbit_news_fn=lambda rings: [],
    )
    by_hash = {}
    for it in items:
        by_hash.setdefault(content_hash(it["title"], it["url"]), it)
    # 重复新闻只保留最高优先级 direct
    dup_item = by_hash[content_hash(dup["title"], dup["url"])]
    assert dup_item["tier"] == "direct"
    assert any(it["tier"] == "theme" for it in items)
    assert all(it["tier"] in RELATION_TIERS for it in items)
    assert all(it["content_hash"] == content_hash(it["title"], it["url"] or "") for it in items)


def test_collect_skips_failing_source():
    def boom(*a, **k):
        raise RuntimeError("net")
    items = collect_related_news(
        "601702", {"boards": [{"name": "铜箔"}], "peers": [], "concept_rings": []},
        stock_news_fn=boom,                                  # direct 源挂
        sector_news_fn=lambda names: [{"title": "板块新闻", "url": "http://z/9",
                                       "source": "同花顺", "published_at": "2026-06-20"}],
        hot_news_fn=lambda boards: [], orbit_news_fn=lambda rings: [],
    )
    assert [it["tier"] for it in items] == ["board"]   # direct 跳过，board 正常
