import json
from analysis.opportunity_scorer import write_signals_sidecar


def test_write_signals_sidecar(tmp_path):
    results = [
        {"code": "603986", "name": "兆易创新", "total_score": 88, "rating": "S",
         "risk_signals": {"chase": 30, "rsi": 58, "change_3d": 6,
                          "sell_signals": 0, "quant_score": 62},
         "scores": {"sector": 50}},
    ]
    path = write_signals_sidecar(results, tmp_path / "opportunity_top10_20260608.md")
    assert path.name == "opportunity_top10_20260608.signals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["code"] == "603986"
    assert data[0]["risk_signals"]["rsi"] == 58
    assert data[0]["sector_score"] == 50
