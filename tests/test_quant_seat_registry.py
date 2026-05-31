# tests/test_quant_seat_registry.py
"""量化席位注册表加载 + 分类 + 热加载。"""
from __future__ import annotations

import json

from analysis.institutional.quant_seat_registry import QuantSeatRegistry


def test_classify_high_confidence(tmp_path):
    cfg = tmp_path / "quant_seats.json"
    cfg.write_text(json.dumps({
        "high_confidence": ["华泰证券股份有限公司总部"],
        "medium_confidence": ["招商证券股份有限公司深圳蛇口工业八路证券营业部"],
        "notes": "test",
    }, ensure_ascii=False), encoding="utf-8")

    reg = QuantSeatRegistry(cfg)
    is_q, conf = reg.classify("华泰证券股份有限公司总部")
    assert is_q is True and conf == "high"

    is_q, conf = reg.classify("招商证券股份有限公司深圳蛇口工业八路证券营业部")
    assert is_q is True and conf == "medium"

    is_q, conf = reg.classify("某不知名小券商营业部")
    assert is_q is False and conf is None


def test_reload_picks_up_changes(tmp_path):
    cfg = tmp_path / "quant_seats.json"
    cfg.write_text(json.dumps({"high_confidence": [], "medium_confidence": []}), encoding="utf-8")
    reg = QuantSeatRegistry(cfg)
    assert reg.classify("新席位 A") == (False, None)

    cfg.write_text(json.dumps({
        "high_confidence": ["新席位 A"], "medium_confidence": [],
    }, ensure_ascii=False), encoding="utf-8")
    reg.reload()
    assert reg.classify("新席位 A") == (True, "high")


def test_default_config_path_loads_ship_seat_list():
    """ship 默认 config/quant_seats.json 至少包含 5 个 high + 2 个 medium。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    reg = QuantSeatRegistry(repo_root / "config" / "quant_seats.json")
    assert len(reg._high) >= 5  # noqa: SLF001
    assert len(reg._medium) >= 2  # noqa: SLF001
