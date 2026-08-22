# tests/test_opportunity_repo.py
"""opportunity_repo 的 save_run / 按天查询 / items 投影 行为。"""
from __future__ import annotations

import json
import sqlite3

import pytest

from data_store.schema import migrate


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "kronos_test.sqlite"
    c = sqlite3.connect(path, isolation_level=None)
    c.row_factory = sqlite3.Row
    migrate(c)

    _getter = lambda: c  # noqa: E731
    from data_store import connection
    monkeypatch.setattr(connection, "get_conn", _getter)
    from data_store import opportunity_repo
    monkeypatch.setattr(opportunity_repo, "get_conn", _getter)
    yield c
    c.close()


def _meta(**overrides):
    base = {
        "run_at": "2026-06-10T15:31:02",
        "source": "multi",
        "candidate_limit": 100,
        "mode": "market_scan",
        "ruleset_version": "v24",
        "config_hash": "abc123",
        "report_file": "opportunity_top10_20260610_153102.md",
        "candidates": 120,
        "analyzed": 118,
        "duration_sec": 321.5,
    }
    base.update(overrides)
    return base


def _items():
    return [
        {"code": "000001", "name": "平安银行", "total_score": 82.1, "rating": "A",
         "degraded": False, "source": "heat", "change_pct": 2.1,
         "source_detail": "热门行业 半导体 第1 · 成分第3",
         "sector": "半导体", "sector_code": "BK1001",
         "sector_rank": 1, "sector_stock_rank": 3,
         "scores": {"quantitative": 55, "sector": 70},
         "signals": {"chase": 12, "rsi": 48.2, "sell_signals": 0}},
        {"code": "300750", "name": "宁德时代", "total_score": 76.0, "rating": "B",
         "degraded": True, "source": "moneyflow", "change_pct": -1.0,
         "scores": {"quantitative": 0}, "signals": {}},
    ]


def test_migrate_creates_opportunity_tables(conn):
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "opportunity_run" in names
    assert "opportunity_item" in names


def test_save_run_roundtrip_with_rank_and_json(conn):
    from data_store import opportunity_repo as repo

    run_id = repo.save_run(_meta(), _items())
    assert run_id > 0

    runs = repo.list_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["run_date"] == "2026-06-10"  # 按天键来自 run_at
    assert run["source"] == "multi"
    assert run["ruleset_version"] == "v24"
    assert run["item_count"] == 2

    items = repo.items_for_run(run_id)
    assert [i["code"] for i in items] == ["000001", "300750"]  # 按分数降序
    assert items[0]["item_rank"] == 1
    assert items[0]["sector"] == "半导体"
    assert items[0]["sector_code"] == "BK1001"
    assert items[0]["sector_rank"] == 1
    assert items[0]["sector_stock_rank"] == 3
    assert items[0]["source_detail"].startswith("热门行业")
    assert items[1]["item_rank"] == 2
    assert items[1]["degraded"] == 1
    assert json.loads(items[0]["scores_json"])["sector"] == 70
    assert json.loads(items[0]["signals_json"])["sell_signals"] == 0


def test_list_runs_filters_by_day_and_latest_run(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), _items())
    repo.save_run(_meta(run_at="2026-06-10T09:00:00"), _items())
    rid3 = repo.save_run(_meta(run_at="2026-06-10T15:00:00"), _items())

    assert len(repo.list_runs()) == 3
    today = repo.list_runs(run_date="2026-06-10")
    assert len(today) == 2
    assert today[0]["id"] == rid3  # 同日按时间倒序

    latest = repo.latest_run()
    assert latest["id"] == rid3


def test_save_run_duplicate_codes_keep_first(conn):
    from data_store import opportunity_repo as repo

    items = _items() + [{"code": "000001", "name": "重复", "total_score": 10}]
    run_id = repo.save_run(_meta(), items)
    rows = repo.items_for_run(run_id)
    assert len(rows) == 2  # 重复 code 不炸、保留先到(高分)行


def test_build_items_projection_from_discovery_results(conn):
    from data_store import opportunity_repo as repo

    filter_results = [
        {
            "stock_code": "688343",
            "name": "云天励飞",
            "source": "heat",
            "source_detail": "热门行业 软件服务 第2 · 成分第5",
            "sector_name": "软件服务",
            "sector_code": "BK2002",
            "sector_rank": 2,
            "sector_stock_rank": 5,
            "change_pct": 5.2,
            "final_score": 79.3,
            "rating": "B",
            "scoring_result": {
                "total_score": 79.3,
                "degraded": False,
                "exclusion_flags": [],
                "scores": {"quantitative": 62, "sector": 58, "technical": 70},
                "details": {
                    "technical": {"RSI": 47.0},
                    "quantitative": {"sell_count": 1},
                    "price_changes": {"change_1d": 1.2, "change_3d": 4.0, "change_5d": 6.0},
                    "momentum": {"chase_risk_score": 30},
                },
            },
        },
        {  # 失败/降级股票也要可入库
            "stock_code": "000002",
            "name": "万科A",
            "scoring_result": {"degraded": True, "scores": {}, "details": {}},
        },
    ]
    items = repo.build_items(filter_results)
    assert items[0]["code"] == "688343"
    assert items[0]["total_score"] == pytest.approx(79.3)
    assert items[0]["rating"] == "B"
    assert items[0]["sector"] == "软件服务"
    assert items[0]["sector_code"] == "BK2002"
    assert items[0]["sector_rank"] == 2
    assert items[0]["sector_stock_rank"] == 5
    assert items[0]["source_detail"].startswith("热门行业")
    assert items[0]["signals"]["rsi"] == 47.0
    assert items[0]["signals"]["chase"] == 30
    assert items[0]["signals"]["sell_signals"] == 1
    assert items[1]["degraded"] is True

    run_id = repo.save_run(_meta(), items)
    assert len(repo.items_for_run(run_id)) == 2


def test_runs_by_day_groups_counts(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), _items())
    repo.save_run(_meta(run_at="2026-06-10T09:00:00"), _items())
    repo.save_run(_meta(run_at="2026-06-10T15:00:00"), _items())

    days = repo.runs_by_day(limit=10)
    assert [d["run_date"] for d in days] == ["2026-06-10", "2026-06-09"]
    assert days[0]["run_count"] == 2


def test_get_run_by_id_and_missing(conn):
    from data_store import opportunity_repo as repo

    rid = repo.save_run(_meta(), _items())
    run = repo.get_run(rid)
    assert run is not None
    assert run["id"] == rid
    assert run["item_count"] == 2
    assert run["source"] == "multi"

    assert repo.get_run(999999) is None
    assert repo.get_run(None) is None
    assert repo.get_run("not-an-int") is None


def test_stock_pool_uses_aggregate_aliases_for_ordering(conn):
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), _items())
    repo.save_run(_meta(run_at="2026-06-10T15:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "rating": "A+",
         "degraded": False, "sector": "银行", "change_pct": 1.5},
        {"code": "688001", "name": "芯片测试", "total_score": 91.0, "rating": "A",
         "degraded": False, "sector": "半导体", "change_pct": 4.0},
    ])

    stocks = repo.stock_pool(limit=10)

    assert [s["code"] for s in stocks] == ["000001", "688001", "300750"]
    assert stocks[0]["selections"] == 2
    assert stocks[0]["distinct_days"] == 2
    assert stocks[0]["last_seen"] == "2026-06-10T15:00:00"
    assert stocks[0]["best_score"] == pytest.approx(88.0)
    assert stocks[0]["last_rating"] == "A+"
    assert stocks[0]["days"] == ["2026-06-09", "2026-06-10"]


def test_stock_pool_filters_by_since_and_until_closed_interval(conn):
    """since/until 闭区间过滤:区间外 run 完全不参与聚合(次数/日期/最新值)。"""
    from data_store import opportunity_repo as repo

    mk = lambda score, rating: [{  # noqa: E731
        "code": "000001", "name": "平安银行", "total_score": score,
        "rating": rating, "degraded": False, "sector": "银行", "change_pct": 1.0,
    }]
    repo.save_run(_meta(run_at="2026-05-01T10:00:00"), mk(60.0, "C") + [
        {"code": "600999", "name": "只在窗外", "total_score": 95.0, "rating": "S",
         "degraded": False, "sector": "券商", "change_pct": 2.0},
    ])
    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), mk(70.0, "B"))
    repo.save_run(_meta(run_at="2026-06-10T15:00:00"), mk(80.0, "A"))
    repo.save_run(_meta(run_at="2026-07-01T10:00:00"), mk(90.0, "S"))

    # 双边闭区间: 只统计 06-09 ~ 06-10 两天
    stocks = repo.stock_pool(limit=10, since_date="2026-06-09", until_date="2026-06-10")
    assert [s["code"] for s in stocks] == ["000001"]  # 窗外股票整只消失
    row = stocks[0]
    assert row["selections"] == 2
    assert row["distinct_days"] == 2
    assert row["days"] == ["2026-06-09", "2026-06-10"]
    assert row["first_seen"] == "2026-06-09T10:00:00"  # 05-01 不算首次
    assert row["last_seen"] == "2026-06-10T15:00:00"   # 07-01 不算最近
    assert row["best_score"] == pytest.approx(80.0)    # 95/90 均在窗外
    assert row["last_rating"] == "A"                   # 最新值取窗口内最近 run

    # 单边 until: 只统计 05-01
    early = repo.stock_pool(limit=10, until_date="2026-05-31")
    assert {s["code"] for s in early} == {"000001", "600999"}
    assert next(s for s in early if s["code"] == "000001")["distinct_days"] == 1

    # 单边 since: 与既有行为一致
    late = repo.stock_pool(limit=10, since_date="2026-07-01")
    assert [s["code"] for s in late] == ["000001"]
    assert late[0]["days"] == ["2026-07-01"]
    assert late[0]["last_rating"] == "S"


def test_stock_pool_reads_moneyflow_snapshot_at_top_n_0(conn):
    """资金流向列取自全市场快照哨兵 top_n=0(而非历史误用的 top_n=1)。

    回归:此前查询 WHERE top_n=1,而真实快照写在 top_n=0,导致主力净流入/
    散户流入/总流入恒为空。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-10T15:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "rating": "A",
         "degraded": False, "sector": "银行", "change_pct": 1.5},
    ])
    # 全市场快照(哨兵 top_n=0)与候选快照(top_n=1,应被忽略)
    conn.execute(
        "INSERT INTO moneyflow_dc (trade_date, ts_code, top_n, net_amount, "
        "buy_elg_amount, buy_lg_amount, buy_md_amount, buy_sm_amount, amount_unit) "
        "VALUES ('2026-06-10', '000001.SZ', 0, 12000, 30000, 20000, 5000, 8000, '万元')"
    )
    conn.execute(
        "INSERT INTO moneyflow_dc (trade_date, ts_code, top_n, net_amount, amount_unit) "
        "VALUES ('2026-06-10', '000001.SZ', 1, 999999, '万元')"
    )

    stocks = repo.stock_pool(limit=10)
    row = next(s for s in stocks if s["code"] == "000001")
    assert row["main_net_inflow"] == 12000  # 来自 top_n=0,不是 top_n=1 的 999999
    assert row["retail_flow"] == 8000
    assert row["total_inflow"] == 63000  # 30000+20000+5000+8000
    assert row["main_net_inflow_text"] == "+12000.00万"  # 单位万元,scale=1


def test_stock_pool_computes_post_selection_return(conn):
    """入选后涨幅 = (最新收盘 - 首次入选次日开盘) / 次日开盘 * 100。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "rating": "A",
         "degraded": False, "sector": "银行", "change_pct": 1.5},
    ])
    # 首次入选日 2026-06-09;次日开盘(06-10)= 10.0;最新收盘(06-12)= 11.0 → +10%
    for ts, op, cl in [
        ("2026-06-09 00:00:00", 9.5, 9.8),   # 入选当日,不作买入基准
        ("2026-06-10 00:00:00", 10.0, 10.4),  # 次日开盘买入 = 10.0
        ("2026-06-12 00:00:00", 10.8, 11.0),  # 最新收盘 = 11.0
    ]:
        conn.execute(
            "INSERT INTO ohlcv (code, frequency, ts, open, close) VALUES (?, '1d', ?, ?, ?)",
            ("000001", ts, op, cl),
        )

    stocks = repo.stock_pool(limit=10)
    row = next(s for s in stocks if s["code"] == "000001")
    assert row["post_select_return_pct"] == pytest.approx(10.0)


def test_stock_pool_post_selection_return_none_without_prices(conn):
    """无价格数据时入选后涨幅为 None(前端显示 --),不抛错。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-10T15:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "rating": "A",
         "degraded": False, "sector": "银行", "change_pct": 1.5},
    ])
    stocks = repo.stock_pool(limit=10)
    row = next(s for s in stocks if s["code"] == "000001")
    assert row["post_select_return_pct"] is None


def test_build_items_change_pct_falls_back_to_change_1d(conn):
    """上游漏透传 change_pct 时,回退评分明细的 change_1d(同口径的当日涨跌幅)。

    回归:apply_all_filters 曾把候选阶段的 change_pct 整个丢掉,导致入库整列
    NULL、股票池「平均涨跌」恒为空。"""
    from data_store import opportunity_repo as repo

    items = repo.build_items([
        {  # 有 change_pct: 原样用
            "stock_code": "000001", "name": "平安银行", "change_pct": 5.2,
            "scoring_result": {"details": {"price_changes": {"change_1d": 1.2}}},
        },
        {  # 没有 change_pct: 回退 change_1d
            "stock_code": "000002", "name": "万科A",
            "scoring_result": {"details": {"price_changes": {"change_1d": -3.4}}},
        },
        {  # 两者都没有: None(不写 0,免得把「无数据」算进平均)
            "stock_code": "000003", "name": "无数据", "scoring_result": {"details": {}},
        },
    ])
    assert items[0]["change_pct"] == pytest.approx(5.2)
    assert items[1]["change_pct"] == pytest.approx(-3.4)
    assert items[2]["change_pct"] is None


def test_stock_pool_average_change_pct(conn):
    """平均涨跌 = 窗口内每次入选当日涨跌幅的均值;无数据时为 None。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 80.0, "change_pct": 2.0},
        {"code": "600999", "name": "无涨幅", "total_score": 70.0},
    ])
    repo.save_run(_meta(run_at="2026-06-10T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 82.0, "change_pct": -1.0},
    ])

    stocks = {s["code"]: s for s in repo.stock_pool(limit=10)}
    assert stocks["000001"]["avg_change_pct"] == pytest.approx(0.5)
    assert stocks["000001"]["last_change_pct"] == pytest.approx(-1.0)
    assert stocks["600999"]["avg_change_pct"] is None


def test_stock_pool_post_selection_return_prefers_market_daily(conn):
    """有全市场日线时走 market_daily,并带出买入基准日/现价日期。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "change_pct": 1.5},
    ])
    _seed_market_daily(conn, "20260610", extra=[("000001.SZ", 10.0, 10.2)])
    _seed_market_daily(conn, "20260612", extra=[("000001.SZ", 11.5, 12.0)])

    row = next(s for s in repo.stock_pool(limit=10) if s["code"] == "000001")
    assert row["post_select_return_pct"] == pytest.approx(20.0)  # 10.0 开盘 → 12.0 收盘
    assert row["entry_date"] == "2026-06-10"
    assert row["price_date"] == "2026-06-12"
    assert row["price_source"] == "market_daily"


def test_stock_pool_post_selection_return_ignores_index_rows(conn):
    """market_daily 里混着指数日 K(000001.SH 上证指数),不能被当成个股 000001。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "change_pct": 1.5},
    ])
    # 只有指数行 + 凑数个股行,真正的 000001.SZ 缺席 → 不该拿指数价算涨幅
    _seed_market_daily(conn, "20260610", extra=[("000001.SH", 3000.0, 3010.0)])
    _seed_market_daily(conn, "20260612", extra=[("000001.SH", 3300.0, 3600.0)])

    row = next(s for s in repo.stock_pool(limit=10) if s["code"] == "000001")
    assert row["post_select_return_pct"] is None


def test_stock_pool_post_selection_return_falls_back_to_ohlcv(conn):
    """全市场日线覆盖不到的股票(如退市/停牌)回退本地 ohlcv,并标注来源。"""
    from data_store import opportunity_repo as repo

    repo.save_run(_meta(run_at="2026-06-09T10:00:00"), [
        {"code": "000001", "name": "平安银行", "total_score": 88.0, "change_pct": 1.5},
    ])
    _seed_market_daily(conn, "20260610")   # 全市场有行情,但没有 000001
    _seed_market_daily(conn, "20260612")
    for ts, op, cl in [("2026-06-10 00:00:00", 10.0, 10.4),
                       ("2026-06-12 00:00:00", 10.8, 11.0)]:
        conn.execute(
            "INSERT INTO ohlcv (code, frequency, ts, open, close) VALUES (?, '1d', ?, ?, ?)",
            ("000001", ts, op, cl),
        )

    row = next(s for s in repo.stock_pool(limit=10) if s["code"] == "000001")
    assert row["post_select_return_pct"] == pytest.approx(10.0)
    assert row["price_source"] == "ohlcv"


def _seed_market_daily(conn, trade_date: str, extra=()):
    """造一天「全市场」日线:凑够行数门槛的填充行 + 指定的个股/指数行。"""
    rows = [(f"{600000 + i:06d}.SH", trade_date, 10.0, 10.0) for i in range(1200)]
    rows += [(ts_code, trade_date, open_, close) for ts_code, open_, close in extra]
    conn.executemany(
        "INSERT OR REPLACE INTO market_daily(ts_code, trade_date, open, close) VALUES(?,?,?,?)",
        rows,
    )


def test_latest_item_for_code_can_exclude_recent_runs(conn):
    """``before_date`` 只回看该日期**之前**的入选行。

    个股分析要拿「上一次入选」与当前并排, 当天刚入选过时必须跳过当天那行,
    否则两侧是同一天的数据, 比较退化成自己跟自己比。
    """
    from data_store import opportunity_repo as repo

    for day in ("2026-06-09", "2026-06-10", "2026-06-12"):
        repo.save_run(_meta(run_at=f"{day}T15:00:00"), [
            {"code": "000001", "name": "平安银行", "total_score": 80.0,
             "signals": {"rsi": 50.0}},
        ])

    assert repo.latest_item_for_code("000001")["run_date"] == "2026-06-12"
    assert repo.latest_item_for_code(
        "000001", before_date="2026-06-12")["run_date"] == "2026-06-10"
    assert repo.latest_item_for_code(
        "000001", before_date="2026-06-10")["run_date"] == "2026-06-09"
    # 早于全部入选记录 → 没有「上一次」
    assert repo.latest_item_for_code("000001", before_date="2026-06-09") is None
