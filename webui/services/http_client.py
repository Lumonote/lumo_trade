"""HTTP helpers for WebUI data fetches.

The synchronous helpers keep the current Flask routes unchanged, while the
async variants are used by the Robyn migration path and future async services.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
}


def _request_headers(headers: dict[str, str] | None) -> dict[str, str]:
    return dict(headers or DEFAULT_HEADERS)


def request_text(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int | float = 5,
    encoding: str = "utf-8",
    errors: str = "strict",
    retries: int = 1,
    trust_env: bool = True,
) -> str:
    """Fetch text over HTTP with small retry support.

    ``trust_env=False`` ignores system proxy env (HTTP(S)_PROXY). Domestic
    endpoints (eastmoney/tencent quotes) get killed when a proxy like Clash
    forwards them, so those callers pass ``trust_env=False`` to go direct.
    """
    last_exc: Exception | None = None
    request_headers = _request_headers(headers)

    for attempt in range(max(1, retries)):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=trust_env) as client:
                response = client.get(url, headers=request_headers)
                response.raise_for_status()
                return response.content.decode(encoding, errors=errors)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))

    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed without an exception")


def request_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int | float = 5,
    encoding: str = "utf-8",
    retries: int = 3,
    trust_env: bool = True,
) -> Any:
    """Fetch and parse a JSON HTTP response."""
    return json.loads(
        request_text(
            url,
            headers=headers,
            timeout=timeout,
            encoding=encoding,
            retries=retries,
            trust_env=trust_env,
        )
    )


def request_json_post(
    url: str,
    json_body: Any,
    headers: dict[str, str] | None = None,
    timeout: int | float = 5,
    retries: int = 2,
) -> Any:
    """POST a JSON body and parse the JSON response (small retry support)."""
    last_exc: Exception | None = None
    request_headers = _request_headers(headers)

    for attempt in range(max(1, retries)):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                response = client.post(url, headers=request_headers, json=json_body)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))

    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed without an exception")


async def async_request_text(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int | float = 5,
    encoding: str = "utf-8",
    errors: str = "strict",
    retries: int = 1,
) -> str:
    """Fetch text over HTTP with httpx.AsyncClient and retry support."""
    last_exc: Exception | None = None
    request_headers = _request_headers(headers)

    for attempt in range(max(1, retries)):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=request_headers)
                response.raise_for_status()
                return response.content.decode(encoding, errors=errors)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                await asyncio.sleep(0.2 * (attempt + 1))

    if last_exc:
        raise last_exc
    raise RuntimeError("HTTP request failed without an exception")


async def async_request_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int | float = 5,
    encoding: str = "utf-8",
    retries: int = 3,
) -> Any:
    """Fetch and parse a JSON HTTP response asynchronously."""
    return json.loads(
        await async_request_text(
            url,
            headers=headers,
            timeout=timeout,
            encoding=encoding,
            retries=retries,
        )
    )
