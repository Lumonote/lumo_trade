# tests/test_llm_service.py
"""OpenAIProvider 的网络韧性:瞬时连接级错误(SSL EOF / 重置 / 超时)必须自动重试,
即使用户没在配置里打开 retry_enabled;而确定性错误(HTTP 400 / 解析失败)不重试。

复现用户线上报错:
    LLM 调用失败:[DeepSeek官方] API调用失败: HTTPSConnectionPool(...): Max retries
    exceeded ... SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF
    occurred in violation of protocol (_ssl.c:1032)'))

全程 mock requests.post / time.sleep,不触网、不睡眠。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from analysis.llm_service import OpenAIProvider


def _success_response(content: str = "这是一段分析结论。"):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _provider():
    return OpenAIProvider({"base_url": "https://api.deepseek.com", "api_style": "openai"}, "DeepSeek官方")


def _model_cfg(**overrides):
    cfg = {
        "api_key": "sk-test",
        "model_id": "deepseek-v4-pro",
        "endpoint": "/chat/completions",
        "timeout": 5,
    }
    cfg.update(overrides)
    return cfg


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_transient_ssl_eof_is_retried_without_retry_enabled(mock_post, _sleep):
    """SSL UNEXPECTED_EOF 第一次失败、第二次成功:即便没开 retry_enabled 也应自动重试。"""
    mock_post.side_effect = [
        requests.exceptions.SSLError(
            "HTTPSConnectionPool(host='api.deepseek.com', port=443): Max retries exceeded "
            "(Caused by SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF "
            "occurred in violation of protocol (_ssl.c:1032)')))"
        ),
        _success_response("好的,给出分析。"),
    ]

    ok, text = _provider().call_api("分析一下这只票", _model_cfg())

    assert ok is True
    assert "分析" in text
    assert mock_post.call_count == 2  # 重试了 1 次


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_persistent_ssl_error_exhausts_retries_with_clear_message(mock_post, _sleep):
    """持续 SSL EOF:重试若干次后失败,错误信息要可读(指明连接异常),且不再是裸 urllib3 噪声。"""
    mock_post.side_effect = requests.exceptions.SSLError(
        "EOF occurred in violation of protocol (_ssl.c:1032)"
    )

    ok, text = _provider().call_api("分析一下", _model_cfg())

    assert ok is False
    assert mock_post.call_count >= 3  # 至少重试到 3 次
    assert "API调用失败" in text


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_connection_reset_is_retried(mock_post, _sleep):
    """连接被重置(ConnectionError)同样属于瞬时错误,应重试。"""
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("Connection reset by peer"),
        _success_response(),
    ]

    ok, text = _provider().call_api("p", _model_cfg())

    assert ok is True
    assert mock_post.call_count == 2


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_timeout_is_retried(mock_post, _sleep):
    """读超时是瞬时错误,应重试。"""
    mock_post.side_effect = [
        requests.exceptions.Timeout("Read timed out"),
        _success_response(),
    ]

    ok, _text = _provider().call_api("p", _model_cfg())

    assert ok is True
    assert mock_post.call_count == 2


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_http_400_is_not_retried(mock_post, _sleep):
    """HTTP 400 是确定性错误,立即返回、绝不重试。"""
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "invalid request"
    mock_post.return_value = resp

    ok, text = _provider().call_api("p", _model_cfg())

    assert ok is False
    assert mock_post.call_count == 1
    assert "API请求错误" in text


@patch("analysis.llm_service.time.sleep", return_value=None)
@patch("analysis.llm_service.requests.post")
def test_success_first_try_does_not_retry(mock_post, _sleep):
    """首次即成功不应触发任何重试或 sleep。"""
    mock_post.return_value = _success_response()

    ok, _text = _provider().call_api("p", _model_cfg())

    assert ok is True
    assert mock_post.call_count == 1
    _sleep.assert_not_called()
