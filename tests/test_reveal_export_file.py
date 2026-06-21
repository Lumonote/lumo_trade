"""Tests for ``webui.core.reveal_in_file_manager``.

打包 App 的 WKWebView 不触发 Content-Disposition 下载,且 :7070 远程源拿不到 Tauri
IPC —— 浏览器侧任何下载方式都静默失效("点击导出 Excel 无反应")。改由本机后端在
访达/资源管理器里直接定位刚导出的文件。这里覆盖安全护栏与各平台命令分派。
"""

import sys

import webui.core as core


def _spy_popen(monkeypatch):
    calls = []

    class _FakeProc:  # noqa: D401 - 占位返回值
        pass

    def _popen(cmd, *args, **kwargs):
        calls.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(core.subprocess, "Popen", _popen)
    return calls


def test_reveal_rejects_missing_path(monkeypatch):
    calls = _spy_popen(monkeypatch)
    assert core.reveal_in_file_manager("/no/such/file.xlsx") is False
    assert calls == []  # 不存在 → 根本不唤起文件管理器


def test_reveal_rejects_path_outside_results(tmp_path, monkeypatch):
    calls = _spy_popen(monkeypatch)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(core, "REPORT_DIRS", {"results": results})
    outside = tmp_path / "evil.xlsx"  # 在受控目录之外
    outside.write_text("x")
    assert core.reveal_in_file_manager(str(outside)) is False
    assert calls == []  # 越权路径 → 拒绝,防止变成任意文件打开器


def test_reveal_opens_file_under_results_macos(tmp_path, monkeypatch):
    calls = _spy_popen(monkeypatch)
    results = tmp_path / "results"
    results.mkdir()
    f = results / "opportunity_canvas_x.xlsx"
    f.write_text("x")
    monkeypatch.setattr(core, "REPORT_DIRS", {"results": results})
    monkeypatch.setattr(sys, "platform", "darwin")
    assert core.reveal_in_file_manager(str(f)) is True
    assert calls, "应当唤起 Finder"
    assert calls[0][0] == "/usr/bin/open" and calls[0][1] == "-R"
    assert calls[0][2].endswith("opportunity_canvas_x.xlsx")


def test_reveal_windows_uses_explorer_select(tmp_path, monkeypatch):
    calls = _spy_popen(monkeypatch)
    results = tmp_path / "results"
    results.mkdir()
    f = results / "snap.xlsx"
    f.write_text("x")
    monkeypatch.setattr(core, "REPORT_DIRS", {"results": results})
    monkeypatch.setattr(sys, "platform", "win32")
    assert core.reveal_in_file_manager(str(f)) is True
    assert calls[0][0] == "explorer" and calls[0][1].startswith("/select,")
