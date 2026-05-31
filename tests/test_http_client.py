import asyncio
import json

import httpx

from webui.services import http_client


_ORIGINAL_CLIENT = httpx.Client
_ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


def _transport(payload: bytes, status_code: int = 200):
    def handler(_request):
        return http_client.httpx.Response(status_code, content=payload)

    return http_client.httpx.MockTransport(handler)


class _ClientFactory:
    def __init__(self, transport):
        self.transport = transport

    def __call__(self, **kwargs):
        return _ORIGINAL_CLIENT(transport=self.transport, **kwargs)


class _AsyncClientFactory:
    def __init__(self, transport):
        self.transport = transport

    def __call__(self, **kwargs):
        return _ORIGINAL_ASYNC_CLIENT(transport=self.transport, **kwargs)


def test_request_text_decodes_payload(monkeypatch):
    transport = _transport("上证".encode("gbk"))
    monkeypatch.setattr(http_client.httpx, "Client", _ClientFactory(transport))

    assert http_client.request_text("http://example.test", encoding="gbk") == "上证"


def test_request_json_parses_payload(monkeypatch):
    payload = json.dumps({"ok": True}).encode("utf-8")
    transport = _transport(payload)
    monkeypatch.setattr(http_client.httpx, "Client", _ClientFactory(transport))

    assert http_client.request_json("http://example.test") == {"ok": True}


def test_async_request_json_parses_payload(monkeypatch):
    payload = json.dumps({"ok": True}).encode("utf-8")
    transport = _transport(payload)
    monkeypatch.setattr(http_client.httpx, "AsyncClient", _AsyncClientFactory(transport))

    assert asyncio.run(http_client.async_request_json("http://example.test")) == {"ok": True}
