"""桌面外链代开:/api/open-url 端点与 desktop_mode 模板标记。

桌面 App(Tauri/WKWebView)没有新窗口处理器,新闻等外链的 target=_blank
点击会被静默吞掉。后端提供 /api/open-url 用系统默认浏览器代开,
模板输出 data-desktop-mode 供前端拦截脚本判定运行环境。
"""

import importlib
import sys

import pytest


@pytest.fixture()
def robyn_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)
    module = importlib.import_module("webui.robyn_app")
    yield module
    sys.modules.pop("webui.robyn_app", None)
    sys.modules.pop("webui.core", None)


def test_open_url_opens_system_browser_in_desktop_mode(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    opened = []
    monkeypatch.setenv("KRONOS_DESKTOP", "tauri")
    monkeypatch.setattr(
        robyn_module.webui_core.webbrowser,
        "open",
        lambda url, new=0, autoraise=True: opened.append(url) or True,
    )

    with TestClient(robyn_module.app) as client:
        response = client.post("/api/open-url", json_data={"url": "https://finance.sina.com.cn/news/1.html"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert opened == ["https://finance.sina.com.cn/news/1.html"]


def test_open_url_rejects_non_http_schemes(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    opened = []
    monkeypatch.setenv("KRONOS_DESKTOP", "tauri")
    monkeypatch.setattr(
        robyn_module.webui_core.webbrowser,
        "open",
        lambda url, new=0, autoraise=True: opened.append(url) or True,
    )

    with TestClient(robyn_module.app) as client:
        file_response = client.post("/api/open-url", json_data={"url": "file:///etc/passwd"})
        empty_response = client.post("/api/open-url", json_data={})

    assert file_response.status_code == 400
    assert empty_response.status_code == 400
    assert opened == []


def test_open_url_forbidden_outside_desktop_mode(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    opened = []
    monkeypatch.delenv("KRONOS_DESKTOP", raising=False)
    monkeypatch.setattr(
        robyn_module.webui_core.webbrowser,
        "open",
        lambda url, new=0, autoraise=True: opened.append(url) or True,
    )

    with TestClient(robyn_module.app) as client:
        response = client.post("/api/open-url", json_data={"url": "https://example.com/a"})

    assert response.status_code == 403
    assert opened == []


def test_desktop_template_marks_desktop_mode_and_loads_interceptor(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    monkeypatch.setenv("KRONOS_DESKTOP", "tauri")
    with TestClient(robyn_module.app) as client:
        desktop_html = client.get("/desktop").text
        home_html = client.get("/").text

    assert 'data-desktop-mode="1"' in desktop_html
    assert "kronos_open_external.js" in desktop_html
    assert 'data-desktop-mode="1"' in home_html
    assert "kronos_open_external.js" in home_html


def test_desktop_template_unmarked_in_browser_mode(robyn_module, monkeypatch):
    from robyn.testing import TestClient

    monkeypatch.delenv("KRONOS_DESKTOP", raising=False)
    with TestClient(robyn_module.app) as client:
        desktop_html = client.get("/desktop").text

    assert 'data-desktop-mode="0"' in desktop_html
    # 拦截脚本始终加载,由 data-desktop-mode 决定是否生效
    assert "kronos_open_external.js" in desktop_html


def test_open_url_route_registered_in_manifest(robyn_module):
    native_manifest = {
        (route["method"], route["route"])
        for route in robyn_module.get_native_route_manifest()
    }
    assert ("POST", "/api/open-url") in native_manifest
