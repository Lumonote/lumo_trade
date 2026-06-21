from scripts.run_opportunity_discovery import OpportunityDiscovery


def _mk_board(board_type, name, change_pct, net=0.0):
    return {"code": name, "name": name, "type": board_type,
            "change_pct": change_pct, "main_net_inflow": net}


def test_select_hot_boards_prioritizes_concepts():
    """以概念为主：席位充足时概念占 70%(默认)，行业仅补足剩余。"""
    boards = [_mk_board("概念", f"C{i}", 10 - i) for i in range(12)]
    boards += [_mk_board("行业", f"I{i}", 9 - i) for i in range(12)]

    selected = OpportunityDiscovery._select_hot_boards(boards, board_limit=10)

    assert len(selected) == 10
    assert sum(b["type"] == "概念" for b in selected) == 7  # round(10*0.7)
    assert sum(b["type"] == "行业" for b in selected) == 3
    # 最终按涨跌幅降序排列
    chgs = [b["change_pct"] for b in selected]
    assert chgs == sorted(chgs, reverse=True)


def test_select_hot_boards_backfills_when_one_type_short():
    """概念不足时由行业回填，行业不足时由配额外概念回填，总数仍补满。"""
    # 仅 2 个概念 -> 概念 2 + 行业 8
    boards = [_mk_board("概念", f"C{i}", 10 - i) for i in range(2)]
    boards += [_mk_board("行业", f"I{i}", 9 - i) for i in range(12)]
    sel = OpportunityDiscovery._select_hot_boards(boards, board_limit=10)
    assert len(sel) == 10 and sum(b["type"] == "概念" for b in sel) == 2

    # 仅 2 个行业 -> 概念回填到 8 + 行业 2
    boards = [_mk_board("概念", f"C{i}", 10 - i) for i in range(12)]
    boards += [_mk_board("行业", f"I{i}", 9 - i) for i in range(2)]
    sel = OpportunityDiscovery._select_hot_boards(boards, board_limit=10)
    assert len(sel) == 10 and sum(b["type"] == "概念" for b in sel) == 8


def test_select_hot_boards_ratio_env_override(monkeypatch):
    """KRONOS_HOT_SECTOR_CONCEPT_RATIO 可调节概念占比。"""
    monkeypatch.setenv("KRONOS_HOT_SECTOR_CONCEPT_RATIO", "0.9")
    boards = [_mk_board("概念", f"C{i}", 10 - i) for i in range(12)]
    boards += [_mk_board("行业", f"I{i}", 9 - i) for i in range(12)]
    sel = OpportunityDiscovery._select_hot_boards(boards, board_limit=10)
    assert sum(b["type"] == "概念" for b in sel) == 9


def test_fetch_hot_sector_stocks_builds_candidates_from_top_boards(monkeypatch):
    discovery = OpportunityDiscovery.__new__(OpportunityDiscovery)
    discovery.latest_hot_sector_snapshot_id = None

    def fake_clist(fs, fid="f3", limit=10, fields="", attempts=3):
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


def test_fetch_hot_sector_stocks_falls_back_to_tushare(monkeypatch):
    """东财路径未入库快照时，编排方法应回退 Tushare(板块热度+关联股票池)并入库。"""
    import pandas as pd

    discovery = OpportunityDiscovery.__new__(OpportunityDiscovery)
    discovery.latest_hot_sector_snapshot_id = None

    # 模拟东财因代理/限流失败：无候选、未入库快照(latest_hot_sector_snapshot_id 不变)。
    monkeypatch.setattr(
        discovery, "_fetch_hot_sector_stocks_eastmoney",
        lambda limit, board_limit: [],
    )
    monkeypatch.setattr(discovery, "_load_tushare_token", lambda: "fake-token")
    monkeypatch.setattr(discovery, "_latest_lhb_by_codes", lambda codes: {})

    class FakePro:
        def moneyflow_ind_dc(self, trade_date=None):
            return pd.DataFrame([
                {"ts_code": "BK1592.DC", "name": "通信线缆及配套", "content_type": "行业",
                 "pct_change": 7.58, "net_amount": 3.4e9, "rank": 4},
                {"ts_code": "BK1005.DC", "name": "专精特新", "content_type": "概念",
                 "pct_change": 1.62, "net_amount": 6.8e9, "rank": 1},
                {"ts_code": "BK9999.DC", "name": "某地域板块", "content_type": "地域",
                 "pct_change": 9.9, "net_amount": 1e9, "rank": 1},
            ])

        def dc_member(self, trade_date=None, ts_code=None):
            members = {
                "BK1592.DC": [("688143.SH", "长盈通"), ("600487.SH", "亨通光电")],
                "BK1005.DC": [("300780.SZ", "德恩精工")],
            }
            return pd.DataFrame([
                {"trade_date": trade_date, "ts_code": ts_code, "con_code": c, "name": n}
                for c, n in members.get(ts_code, [])
            ])

    import tushare as ts
    monkeypatch.setattr(ts, "pro_api", lambda token: FakePro())

    captured = {}

    def fake_save(boards, stocks, relations, meta=None):
        captured.update(boards=boards, stocks=stocks, relations=relations, meta=meta)
        return 77

    from data_store import hot_sector_repo
    monkeypatch.setattr(hot_sector_repo, "save_snapshot", fake_save)

    rows = discovery._fetch_hot_sector_stocks(limit=10, board_limit=5)

    # 地域板块被过滤(尽管涨幅最高)；按涨幅降序 -> 通信线缆在专精特新之前；.DC 后缀去除。
    assert [b["code"] for b in captured["boards"]] == ["BK1592", "BK1005"]
    assert captured["boards"][0]["type"] == "行业"
    assert captured["meta"]["source"] == "sector_hot_tushare"
    assert discovery.latest_hot_sector_snapshot_id == 77
    # con_code 去交易所后缀；成分股归属对应板块、来源标记 tushare。
    codes = [s["code"] for s in rows]
    assert "688143" in codes and "300780" in codes
    assert all(s["source"] == "sector_hot_tushare" for s in rows)
    s0 = next(s for s in rows if s["code"] == "688143")
    assert s0["sector_code"] == "BK1592"
    assert s0["exchange"] == "SH"
