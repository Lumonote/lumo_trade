from pathlib import Path

from webui.services.trading_client_service import TradingClientService


def test_macos_keyboard_permission_error_is_actionable():
    svc = TradingClientService(Path("missing.json"))
    message = (
        '93:125: execution error: "System Events"遇到一个错误:'
        '"osascript"不允许发送按键。 (1002)'
    )
    out = svc._friendly_keyboard_error(message, {"display_name": "同花顺"})
    assert "同花顺 已打开" in out
    assert "辅助功能" in out
    assert "Terminal" in out
    assert "osascript" not in out
