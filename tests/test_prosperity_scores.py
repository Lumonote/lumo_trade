from analysis.stock_analysis_suite import (
    compute_industry_prosperity_score,
    compute_business_prosperity_score,
)


def test_industry_prosperity_all_none_returns_none():
    assert compute_industry_prosperity_score(None, None, None, None) is None


def test_industry_prosperity_high_when_strong_sector():
    # 板块+3%、资金净流入、PE便宜(分位20)、行业排名靠前(80)
    s = compute_industry_prosperity_score(3.0, 5.0e8, 20.0, 80.0)
    assert s is not None and s >= 70


def test_industry_prosperity_low_when_weak_sector():
    s = compute_industry_prosperity_score(-4.0, -3.0e8, 90.0, 10.0)
    assert s is not None and s < 40


def test_business_prosperity_all_none_returns_none():
    assert compute_business_prosperity_score(None, None, None, None) is None


def test_business_prosperity_expansion_high():
    # 营收+40% 净利+60% 毛利率改善+2pct ROE 18
    s = compute_business_prosperity_score(40.0, 60.0, 2.0, 18.0)
    assert s is not None and s >= 75


def test_business_prosperity_deterioration_low():
    s = compute_business_prosperity_score(-20.0, -50.0, -3.0, 2.0)
    assert s is not None and s < 35
