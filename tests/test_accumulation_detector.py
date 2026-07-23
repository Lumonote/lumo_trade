"""吸筹识别纯函数测试 —— 离线,不联网,不建库。

覆盖 :mod:`analysis.accumulation_detector`:判定三条件(流入持续性/力度/量价背离)、
时间与量统计(吸筹天数/最长连续/跨度/累计吸筹量)、埋伏评分、状态与单位归一。
设计 spec: docs/superpowers/specs/2026-07-16-accumulation-ambush-design.md
"""

from analysis import accumulation_detector as ad


def _row(date, net, rate=0.5, elg=None, lg=0.0, close=10.0, pct=0.1, unit="万元"):
    return {"trade_date": date, "net_amount": net, "net_amount_rate": rate,
            "buy_elg_amount": elg if elg is not None else net * 0.6,
            "buy_lg_amount": lg, "close": close, "pct_change": pct,
            "amount_unit": unit}


def _dates(n):
    # 40 个以内的合成交易日(6月30天 + 7月),保证字典序==时间序
    out = []
    for i in range(n):
        m, d = (6, i + 1) if i < 30 else (7, i - 29)
        out.append(f"2026-{m:02d}-{d:02d}")
    return out


def _accum_rows(n=30, inflow_days=24, close_start=10.0, close_end=10.5):
    """典型吸筹序列:前 inflow_days 天净流入,其余净流出;价格缓慢爬升。"""
    dates = _dates(n)
    rows = []
    for i, date in enumerate(dates):
        close = close_start + (close_end - close_start) * i / max(1, n - 1)
        if i < inflow_days:
            rows.append(_row(date, net=3000.0, rate=0.6, close=round(close, 3)))
        else:
            rows.append(_row(date, net=-1000.0, rate=-0.2, close=round(close, 3)))
    return rows


def test_typical_accumulation_qualifies_with_full_stats():
    result = ad.detect(_accum_rows(), window=40)
    assert result is not None
    assert result["qualified"] is True
    assert result["window"] == 40
    assert result["coverage_days"] == 30
    assert result["accum_days"] == 24
    assert result["accum_ratio"] == 0.8
    assert result["max_streak"] == 24          # 前24天连续净流入
    assert result["span_days"] == 24           # 首个→最近净流入日
    assert result["total_net_wan"] == 24 * 3000.0 - 6 * 1000.0
    assert result["status"] == "吸筹中"
    assert result["score"] >= 50
    assert abs(result["window_pct_chg"] - 5.0) < 0.2   # 10.0 → 10.5
    assert any("净流入" in r for r in result["reasons"])
    assert len(result["daily"]) == 30
    assert set(result["daily"][0]) == {"date", "net_wan", "pct"}


def test_distribution_fails_ratio_condition():
    rows = [_row(d, net=-2000.0, rate=-0.5, pct=-0.3) for d in _dates(30)]
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert result["accum_days"] == 0
    assert any("占比" in r for r in result["reasons"])


def test_pumped_stock_fails_price_divergence():
    rows = _accum_rows(close_start=10.0, close_end=13.0)   # 窗口 +30%
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert any("量价背离" in r or "涨跌幅" in r for r in result["reasons"])


def test_weak_inflow_fails_rate_condition():
    rows = [_row(d, net=10.0, rate=0.01) for d in _dates(30)]  # 天天微量流入
    result = ad.detect(rows, window=40)
    assert result["qualified"] is False
    assert any("力度" in r for r in result["reasons"])


def test_insufficient_coverage_returns_none():
    assert ad.detect(_accum_rows(n=10), window=40) is None
    assert ad.detect([], window=40) is None
    assert ad.detect(None, window=40) is None


def test_recent_kick_marks_launching_status():
    rows = _accum_rows()
    for r, pct in zip(rows[-3:], (2.0, 2.0, 2.0)):   # 近3日累计 +6%
        r["pct_change"] = pct
    result = ad.detect(rows, window=40)
    assert result["qualified"] is True
    assert result["status"] == "疑似启动"
    assert any("启动" in r for r in result["reasons"])


def test_institutional_elg_share_bonus():
    rows = _accum_rows()
    plain = ad.detect([{**r, "buy_elg_amount": 0.0} for r in rows], window=40)
    inst = ad.detect(rows, window=40)   # elg = 0.6*net → 占比 > 0.7(净流出日也为负贡献)
    assert inst["elg_share"] is not None
    if inst["elg_share"] >= 0.7:
        assert inst["score"] >= plain["score"] + 5
        assert any("机构" in r for r in inst["reasons"])


def test_amount_unit_yuan_normalized_to_wan():
    rows = [_row(d, net=3000.0 * 1e4, rate=0.6, unit="元") for d in _dates(20)]
    result = ad.detect(rows, window=20)
    assert result is not None
    assert abs(result["total_net_wan"] - 20 * 3000.0) < 1e-6
    assert result["daily"][0]["net_wan"] == 3000.0


def test_window_slices_latest_rows_and_sorts_input():
    rows = list(reversed(_accum_rows(n=30)))   # 倒序输入,函数内部应排序
    r40 = ad.detect(rows, window=40)
    r20 = ad.detect(rows, window=20)
    assert r40["coverage_days"] == 30
    assert r20["coverage_days"] == 20          # 只取最近 20 行
    assert r20["window"] == 20


def test_invalid_window_falls_back_to_40():
    result = ad.detect(_accum_rows(), window=37)
    assert result["window"] == 40
