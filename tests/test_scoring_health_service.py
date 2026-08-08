# tests/test_scoring_health_service.py
"""ScoringHealthService：分档统计正确性(全量 + 最近1个月) / 降级run占比 /
B级退化警示 / 空态(无CSV、坏CSV)。构造临时 backtest_rebuilt_*.csv 离线验证。

2026-07-09 起数据源 SQLite 优先(backtest_recommendation 表),表空回退 CSV;
故所有 CSV 用例先隔离到空临时库,另有 DB 优先用例。
"""
from __future__ import annotations

import pytest

from data_store import backtest_recommendation_repo as btr
from data_store import connection as conn_mod
from webui.services.scoring_health_service import ScoringHealthService


@pytest.fixture(autouse=True)
def _isolated_empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "health.sqlite"))
    conn_mod.reset_for_testing()
    yield
    conn_mod.reset_for_testing()


CSV_HEADER = "report_date,filename,rank,code,name,score,quant_score,return_5d\n"


def _write_csv(directory, name, rows):
    directory.mkdir(parents=True, exist_ok=True)
    lines = [CSV_HEADER]
    for r in rows:
        lines.append(
            f"{r['date']},f.md,1,{r.get('code', '600000')},X,{r['score']},"
            f"{'' if r.get('quant') is None else r['quant']},"
            f"{'' if r.get('ret') is None else r['ret']}\n"
        )
    path = directory / name
    path.write_text("".join(lines), encoding="utf-8")
    return path


def _tier_map(health):
    return {t["tier"]: t for t in health["tiers"]}


def test_empty_dir_returns_explicit_unavailable(tmp_path):
    svc = ScoringHealthService([tmp_path / "results"])
    health = svc.health()
    assert health["available"] is False
    assert "暂无回测数据" in health["message"]


def test_sqlite_takes_priority_over_csv(tmp_path):
    """backtest_recommendation 表有数据时优先于目录里的 CSV。"""
    _write_csv(tmp_path / "backtest", "recommendations.csv",
               [{"date": "2026-01-01", "score": 40, "quant": 0, "ret": -9.0}])
    btr.upsert_rows([{
        'report_date': '2026-07-01', 'rank': 1, 'code': '600519', 'name': 'X',
        'score': 90, 'quant_score': 80, 'return_5d': 4.0,
    }])

    health = ScoringHealthService([tmp_path]).health()
    assert health["available"] is True
    assert health["source"] == "sqlite"
    assert health["file"] == "backtest_recommendation"
    assert health["total_rows"] == 1
    assert health["date_range"]["start"] == "2026-07-01"
    assert health["baseline"]["full"]["avg_return"] == pytest.approx(4.0)


def test_falls_back_to_backtest_recommendations_csv(tmp_path):
    rows = [
        {"date": "2026-06-10", "score": 90, "quant": 80, "ret": 3.0},
        {"date": "2026-06-10", "score": 72, "quant": 60, "ret": -1.0},
    ]
    _write_csv(tmp_path / "backtest", "recommendations.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    assert health["available"] is True
    assert health["file"] == "recommendations.csv"
    assert health["source"] == "recommendations"
    assert health["total_rows"] == 2
    assert health["baseline"]["full"]["win_rate"] == pytest.approx(0.5)
    assert health["daily"][0]["date"] == "2026-06-10"
    assert health["daily"][0]["annualized_return"] is not None
    assert health["daily"][0]["rolling_annualized_return"] is not None
    assert health["top_recent"][0]["return_5d"] == pytest.approx(3.0)


def test_prefers_newer_recommendations_over_older_rebuilt_csv(tmp_path):
    import os

    old_rebuilt = _write_csv(
        tmp_path,
        "backtest_rebuilt_20260401_000000.csv",
        [{"date": "2026-04-01", "score": 72, "quant": 60, "ret": -5.0}],
    )
    recommendations = _write_csv(
        tmp_path / "backtest",
        "recommendations.csv",
        [{"date": "2026-07-02", "score": 90, "quant": 80, "ret": 4.0}],
    )
    os.utime(old_rebuilt, (1, 1))
    os.utime(recommendations, (2, 2))

    health = ScoringHealthService([tmp_path]).health()

    assert health["source"] == "recommendations"
    assert health["file"] == "recommendations.csv"
    assert health["date_range"]["start"] == "2026-07-02"
    assert health["baseline"]["full"]["avg_return"] == pytest.approx(4.0)


def test_sample_rows_clean_nan_name_and_pad_code(tmp_path):
    path = tmp_path / "backtest" / "recommendations.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "report_date,code,name,score,quant_score,return_5d\n"
        "2026-06-10,2183,,90,80,3.0\n",
        encoding="utf-8",
    )

    health = ScoringHealthService([tmp_path]).health()

    assert health["top_recent"][0]["code"] == "002183"
    assert health["top_recent"][0]["name"] == "002183"


def test_tier_stats_full_and_recent_window(tmp_path):
    rows = []
    # 30 个交易日,每天一条 B 级(score=72):前 10 天亏,后 20 天赚
    for i in range(30):
        rows.append({
            "date": f"2026-01-{i + 1:02d}" if i < 27 else f"2026-02-{i - 26:02d}",
            "score": 72, "quant": 60, "ret": -1.0 if i < 10 else 2.0,
        })
    # 全量再加: S(88,+5) A(80,-2) C(40,+1,且 score<50 → 降级)
    rows.append({"date": "2026-01-01", "score": 88, "quant": 70, "ret": 5.0})
    rows.append({"date": "2026-01-01", "score": 80, "quant": 70, "ret": -2.0})
    rows.append({"date": "2026-01-01", "score": 40, "quant": 0, "ret": 1.0})
    _write_csv(tmp_path, "backtest_rebuilt_20260101_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    assert health["available"] is True
    assert health["total_rows"] == 33
    assert health["date_range"]["days"] == 30
    tiers = _tier_map(health)

    # S: 1 条全胜
    assert tiers["S"]["full"]["n"] == 1
    assert tiers["S"]["full"]["win_rate"] == pytest.approx(1.0)
    # A: 1 条全亏
    assert tiers["A"]["full"]["win_rate"] == pytest.approx(0.0)
    # B 全量: 30 条,20 胜 → 2/3
    assert tiers["B"]["full"]["n"] == 30
    assert tiers["B"]["full"]["win_rate"] == pytest.approx(20 / 30, abs=1e-4)
    # B 最近1个月(按最后日期向前31天): i=2..29,20胜/28条
    assert health["recent_window_label"] == "最近1个月"
    assert tiers["B"]["recent"]["n"] == 28
    assert tiers["B"]["recent"]["win_rate"] == pytest.approx(20 / 28, abs=1e-4)
    assert tiers["B"]["recent"]["avg_return"] == pytest.approx(32 / 28, abs=1e-4)
    # C: 1 条
    assert tiers["C"]["full"]["n"] == 1
    # 降级: quant=0 一条 + score<50 同一条 → 1/33
    assert health["degraded"]["count"] == 1
    assert health["degraded"]["ratio"] == pytest.approx(1 / 33, abs=1e-4)
    # B 最近1个月胜率高于阈值 → 无退化警示
    assert health["warnings"]["b_tier_recent_degraded"] is False


def test_health_can_filter_custom_date_range(tmp_path):
    rows = [
        {"date": "2026-05-01", "score": 90, "quant": 80, "ret": 5.0},
        {"date": "2026-06-01", "score": 72, "quant": 60, "ret": -2.0},
    ]
    _write_csv(tmp_path, "backtest_rebuilt_20260601_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health(start_date="2026-06-01", end_date="2026-06-30")

    assert health["available"] is True
    assert health["total_rows"] == 1
    assert health["date_range"]["start"] == "2026-06-01"
    assert health["available_date_range"]["start"] == "2026-05-01"
    assert health["recent_window_label"] == "所选区间"
    assert health["filter"]["window"] == "custom"
    assert _tier_map(health)["B"]["full"]["n"] == 1


def test_health_recent_month_filter_uses_latest_available_date(tmp_path):
    rows = [
        {"date": "2026-04-01", "score": 90, "quant": 80, "ret": 5.0},
        {"date": "2026-06-01", "score": 72, "quant": 60, "ret": -2.0},
    ]
    _write_csv(tmp_path, "backtest_rebuilt_20260601_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health(recent_month=True)

    assert health["available"] is True
    assert health["total_rows"] == 1
    assert health["date_range"]["start"] == "2026-06-01"
    assert health["available_date_range"]["days"] == 2
    assert health["filter"]["window"] == "recent_month"


def test_b_tier_recent_degraded_warning(tmp_path):
    rows = [{"date": f"2026-03-{i + 1:02d}", "score": 72, "quant": 60, "ret": -1.0}
            for i in range(10)]
    _write_csv(tmp_path, "backtest_rebuilt_20260301_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    assert health["tiers"][2]["tier"] == "B"
    assert health["warnings"]["b_tier_recent_degraded"] is True


def test_rows_without_returns_are_counted_but_not_evaluated(tmp_path):
    rows = [
        {"date": "2026-04-01", "score": 72, "quant": 60, "ret": 3.0},
        {"date": "2026-04-01", "score": 72, "quant": 60, "ret": None},  # 5日收益未出
    ]
    _write_csv(tmp_path, "backtest_rebuilt_20260401_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    b = _tier_map(health)["B"]
    assert b["full"]["n"] == 2
    assert b["full"]["evaluable"] == 1
    assert b["full"]["win_rate"] == pytest.approx(1.0)


def test_picks_latest_csv_by_mtime(tmp_path):
    import os
    old = _write_csv(tmp_path, "backtest_rebuilt_20260101_000000.csv",
                     [{"date": "2026-01-01", "score": 90, "quant": 70, "ret": 1.0}])
    new = _write_csv(tmp_path, "backtest_rebuilt_20260501_000000.csv",
                     [{"date": "2026-05-01", "score": 72, "quant": 60, "ret": 1.0}])
    os.utime(old, (1, 1))

    health = ScoringHealthService([tmp_path]).health()
    assert health["file"] == new.name
    assert _tier_map(health)["B"]["full"]["n"] == 1
    assert _tier_map(health)["S"]["full"]["n"] == 0


def test_invalid_csv_degrades_to_unavailable(tmp_path):
    (tmp_path / "backtest_rebuilt_20260601_000000.csv").write_text(
        "foo,bar\n1,2\n", encoding="utf-8")
    health = ScoringHealthService([tmp_path]).health()
    assert health["available"] is False


def test_report_window_parity_block(tmp_path, monkeypatch):
    """report_window = markdown 报告「历史回测表现」同口径:
    以最新样本日为锚,预留最近10个交易日得 cutoff,再向前回看1个自然月;
    分档用 canonical S≥85/A 78-85/B 70-78/C<70。"""
    import webui.services.scoring_health_service as svc_mod
    monkeypatch.setattr(svc_mod, "_calendar_trade_days", lambda anchor: [])

    rows = []
    # 20 个样本日(交易日历不可用时以样本日作交易日代理)
    for i in range(20):
        rows.append({
            "date": f"2026-04-{i + 1:02d}",
            "score": 88, "quant": 70,
            "ret": -1.0 if i == 9 else 1.0,
        })
    # 80 分在报告口径下应落 A 档(78-85),而不是旧报告的 80-85 之外
    rows.append({"date": "2026-04-05", "score": 80, "quant": 70, "ret": 2.0})
    _write_csv(tmp_path, "backtest_rebuilt_20260420_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    rw = health["report_window"]
    assert rw is not None
    # 20 日预留最后 10 日 → cutoff = 第 11 个自然样本日
    assert rw["cutoff"] == "2026-04-10"
    assert rw["window_start"] == "2026-03-10"
    tiers = {t["tier"]: t["stats"] for t in rw["tiers"]}
    # 窗口内 S = 04-01..04-10 共 10 条(9 胜 1 负),04-11 之后被预留期排除
    assert tiers["S"]["n"] == 10
    assert tiers["S"]["win_rate"] == pytest.approx(0.9)
    assert tiers["S"]["avg_return"] == pytest.approx(0.8)
    assert tiers["A"]["n"] == 1
    assert tiers["A"]["win_rate"] == pytest.approx(1.0)
    assert rw["baseline"]["n"] == 11


def test_report_window_absent_when_history_too_short(tmp_path, monkeypatch):
    """样本日不足以预留 10 个交易日时不产出 report_window(与报告行为一致)。"""
    import webui.services.scoring_health_service as svc_mod
    monkeypatch.setattr(svc_mod, "_calendar_trade_days", lambda anchor: [])

    rows = [{"date": f"2026-04-{i + 1:02d}", "score": 88, "quant": 70, "ret": 1.0}
            for i in range(5)]
    _write_csv(tmp_path, "backtest_rebuilt_20260405_000000.csv", rows)

    health = ScoringHealthService([tmp_path]).health()
    assert health["available"] is True
    assert health["report_window"] is None
