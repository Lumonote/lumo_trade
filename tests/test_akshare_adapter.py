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


def _transient_exc():
    """模拟 requests 的代理/网络抖动（不 import requests，靠消息分类）。"""
    return ConnectionError(
        "HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): "
        "Max retries exceeded (Caused by ProxyError('Unable to connect to proxy'))"
    )


def test_transient_proxy_error_does_not_open_breaker_on_first_failure(monkeypatch):
    """单次代理/网络抖动不应立即触发 5 分钟熔断，否则数据源被误黑 5 分钟。"""
    stub = _StubClient({"stock_cyq_em": _transient_exc()})
    fake_now = {"t": 0.0}
    monkeypatch.setattr("data_store.akshare_adapter._now", lambda: fake_now["t"])
    monkeypatch.setattr("data_store.akshare_adapter._sleep", lambda s: None)
    adapter = AkshareAdapter(
        client_factory=lambda: stub, rate_limit_per_min=999, retry_per_source=1,
    )
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("cyq", symbol="600519")
    n1 = len(stub.call_log)
    # 熔断未打开 -> 第二次仍真正调用 client（而非被熔断直接 raise）
    fake_now["t"] = 5.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("cyq", symbol="600519")
    assert len(stub.call_log) > n1


def test_transient_error_opens_breaker_after_threshold(monkeypatch):
    """连续多次瞬时失败后仍应熔断，避免无意义地反复打爆已确实不可用的源。"""
    stub = _StubClient({"stock_cyq_em": _transient_exc()})
    fake_now = {"t": 0.0}
    monkeypatch.setattr("data_store.akshare_adapter._now", lambda: fake_now["t"])
    monkeypatch.setattr("data_store.akshare_adapter._sleep", lambda s: None)
    adapter = AkshareAdapter(
        client_factory=lambda: stub, rate_limit_per_min=999, retry_per_source=1,
        transient_breaker_threshold=3,
    )
    for i in range(3):
        fake_now["t"] = float(i)
        with pytest.raises(AkshareUnavailable):
            adapter.fetch("cyq", symbol="600519")
    calls_before = len(stub.call_log)
    fake_now["t"] = 3.0
    with pytest.raises(AkshareUnavailable):
        adapter.fetch("cyq", symbol="600519")
    assert len(stub.call_log) == calls_before  # 熔断已开 -> 不再调用 client


def test_success_resets_transient_failure_counter(monkeypatch):
    """瞬时失败后成功一次应清零计数，避免历史抖动累积触发误熔断。"""
    behaviors = {"stock_cyq_em": _transient_exc()}
    stub = _StubClient(behaviors)
    fake_now = {"t": 0.0}
    monkeypatch.setattr("data_store.akshare_adapter._now", lambda: fake_now["t"])
    monkeypatch.setattr("data_store.akshare_adapter._sleep", lambda s: None)
    adapter = AkshareAdapter(
        client_factory=lambda: stub, rate_limit_per_min=999, retry_per_source=1,
        transient_breaker_threshold=3,
    )
    for i in range(2):
        fake_now["t"] = float(i)
        with pytest.raises(AkshareUnavailable):
            adapter.fetch("cyq", symbol="600519")
    behaviors["stock_cyq_em"] = pd.DataFrame({"x": [1]})  # 一次成功
    fake_now["t"] = 3.0
    adapter.fetch("cyq", symbol="600519")
    behaviors["stock_cyq_em"] = _transient_exc()
    n = len(stub.call_log)
    for i in range(2):  # 计数已清零，2 次仍不应熔断
        fake_now["t"] = 4.0 + i
        with pytest.raises(AkshareUnavailable):
            adapter.fetch("cyq", symbol="600519")
    assert len(stub.call_log) > n


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
