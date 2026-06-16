from scripts.run_opportunity_discovery import OpportunityDiscovery


def test_fetch_hot_sector_stocks_builds_candidates_from_top_boards(monkeypatch):
    discovery = OpportunityDiscovery.__new__(OpportunityDiscovery)
    discovery.latest_hot_sector_snapshot_id = None

    def fake_clist(fs, fid="f3", limit=10, fields=""):
        if fs == "m:90+t:2":
            return [
                {"f12": "BK1001", "f14": "半导体", "f3": "4.2", "f62": "100000000"},
            ]
        if fs == "m:90+t:3":
            return [
                {"f12": "BK2001", "f14": "人工智能", "f3": "5.1", "f62": "80000000"},
            ]
        if fs == "b:BK2001":
            return [
                {"f12": "300001", "f14": "AI测试", "f2": "12.3", "f3": "6.5", "f62": "2000000"},
                {"f12": "300002", "f14": "算法测试", "f2": "8.1", "f3": "3.1", "f62": "1000000"},
            ]
        if fs == "b:BK1001":
            return [
                {"f12": "688001", "f14": "芯片测试", "f2": "20.0", "f3": "4.0", "f62": "3000000"},
                {"f12": "300001", "f14": "AI测试", "f2": "12.3", "f3": "6.5", "f62": "2000000"},
            ]
        return []

    monkeypatch.setattr(discovery, "_eastmoney_clist", fake_clist)
    monkeypatch.setattr(discovery, "_latest_lhb_by_codes", lambda codes: {
        "300001": {
            "trade_date": "2026-06-13",
            "l_buy": 120000000,
            "l_sell": 60000000,
            "net_amount": 60000000,
            "reason": "日涨幅偏离值达7%",
        }
    })
    captured = {}

    def fake_save(boards, stocks, relations, meta=None):
        captured["boards"] = boards
        captured["stocks"] = stocks
        captured["relations"] = relations
        captured["meta"] = meta
        return 88

    from data_store import hot_sector_repo
    monkeypatch.setattr(hot_sector_repo, "save_snapshot", fake_save)

    rows = discovery._fetch_hot_sector_stocks(limit=3, board_limit=2)

    assert [row["code"] for row in rows] == ["300001", "300002", "688001"]
    assert rows[0]["source"] == "sector_hot"
    assert rows[0]["sector_name"] == "人工智能"
    assert rows[0]["source_detail"].startswith("热门概念 人工智能")
    assert rows[0]["lhb_buy_amount"] == 120000000
    assert rows[2]["exchange"] == "SH"
    assert discovery.latest_hot_sector_snapshot_id == 88
    assert len(captured["stocks"]) == 4
    assert captured["relations"][0]["relation_type"] == "dragon_tiger"
