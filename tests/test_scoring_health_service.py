# tests/test_scoring_health_service.py
"""ScoringHealthService：分档统计正确性(全量 + 最近1个月) / 降级run占比 /
B级退化警示 / 空态(无CSV、坏CSV)。构造临时 backtest_rebuilt_*.csv 离线验证。
"""
from __future__ import annotations

import pytest

from webui.services.scoring_health_service import ScoringHealthService


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
