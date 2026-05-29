# tests/test_akshare_adapter.py
"""AkshareAdapter 的 fallback、限流、熔断行为。"""
from __future__ import annotations

import time

import pandas as pd
import pytest

from data_store.akshare_adapter import (
    AkshareAdapter,
    AkshareUnavailable,
)


class _StubClient:
    """模拟 akshare 客户端：按函数名分发，每个函数可设置返回值或异常。"""

    def __init__(self, behaviors: dict):
        self.behaviors = behaviors
        self.call_log: list[str] = []

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            self.call_log.append(name)
            beh = self.behaviors.get(name, "ok")
            if isinstance(beh, BaseException):
                raise beh
            if isinstance(beh, str) and beh == "raise":
                raise RuntimeError(f"stub raise from {name}")
            if isinstance(beh, pd.DataFrame):
                return beh
            return pd.DataFrame({"col": [1]})
        return _call


def test_primary_source_success_no_fallback():
    stub = _StubClient({"stock_lhb_detail_em": pd.DataFrame({"x": [1, 2]})})
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=999)
    df = adapter.fetch("lhb_detail", symbol="000001")
    assert len(df) == 2
    assert stub.call_log == ["stock_lhb_detail_em"]


def test_fallback_chain_triggered_on_primary_failure():
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": pd.DataFrame({"y": [9]}),
    })
    adapter = AkshareAdapter(
        client_factory=lambda: stub, rate_limit_per_min=999, retry_per_source=1,
    )
    df = adapter.fetch("lhb_detail")
    assert df.iloc[0]["y"] == 9
    assert stub.call_log == ["stock_lhb_detail_em", "stock_lhb_detail_daily_sina"]


def test_all_sources_fail_raises_unavailable():
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": "raise",
    })
    adapter = AkshareAdapter(
        client_factory=lambda: stub, rate_limit_per_min=999, retry_per_source=1,
    )
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")


def test_unknown_key_raises_keyerror():
    adapter = AkshareAdapter(client_factory=lambda: _StubClient({}))
    with pytest.raises(KeyError):
        adapter.fetch("not_a_key")


def test_circuit_breaker_opens_after_failure_window(monkeypatch):
    """全链路失败后进入 5 分钟熔断，期间直接 raise AkshareUnavailable
    且不再调用 client。"""
    stub = _StubClient({
        "stock_lhb_detail_em": "raise",
        "stock_lhb_detail_daily_sina": "raise",
    })
    fake_now = {"t": 0.0}
    monkeypatch.setattr(
        "data_store.akshare_adapter._now",
        lambda: fake_now["t"],
    )
    monkeypatch.setattr(
        "data_store.akshare_adapter._sleep",
        lambda s: None,
    )
    adapter = AkshareAdapter(
        client_factory=lambda: stub,
        rate_limit_per_min=999,
        breaker_cooldown_sec=300,
        retry_per_source=1,
    )
    # 第一次：触发熔断
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    n1 = len(stub.call_log)
    # 第二次（熔断窗口内）：直接 raise，不调用 client
    fake_now["t"] = 30.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    assert len(stub.call_log) == n1
    # 熔断过期后：重新尝试
    fake_now["t"] = 400.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("lhb_detail")
    assert len(stub.call_log) > n1


def test_rate_limit_blocks_excess_requests(monkeypatch):
    """rate_limit_per_min=2 时，第三次请求应触发 sleep。"""
    sleep_calls: list[float] = []
    monkeypatch.setattr(
        "data_store.akshare_adapter._sleep",
        lambda s: sleep_calls.append(s),
    )
    fake_now = {"t": 0.0}
    monkeypatch.setattr(
        "data_store.akshare_adapter._now",
        lambda: fake_now["t"],
    )

    stub = _StubClient({"stock_lhb_detail_em": pd.DataFrame({"a": [1]})})
    adapter = AkshareAdapter(client_factory=lambda: stub, rate_limit_per_min=2)

    adapter.fetch("lhb_detail")  # t=0
    adapter.fetch("lhb_detail")  # t=0
    assert sleep_calls == []
    adapter.fetch("lhb_detail")  # t=0，应该触发限流 sleep
    assert sleep_calls and sleep_calls[0] > 0
