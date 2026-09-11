"""设备验证门禁测试:授权码算法 + kv 持久化 + robyn before_request 门禁.

[2026-09-11] 桌面端设备验证已按需求注释关闭:
license_service.license_required() 恒返回 False, robyn_app._license_gate 直接放行,
因此「门禁拦截」用例已改为断言放行。授权码算法与激活流程本身仍然有效, 用例保留。

授权码算法必须与 license_admin/generate_license.py 逐字节一致
(盐 KRONOS_DEVICE_SALT_2024, sha256 段落 + md5 校验码), 已发授权码不可失效。
设备指纹采集(system_profiler 子进程, 秒级)在测试中一律 monkeypatch 掉。
"""

import hashlib
import importlib
import sys

import pytest

DEVICE_ID = "ABCDEF0123456789"
OTHER_DEVICE_ID = "1234123412341234"

_MODULES = ("webui.robyn_app", "webui.core", "webui.services.license_service")


def _admin_expected_code(device_id: str, license_type: str = "PERMANENT") -> str:
    """license_admin/generate_license.py 的算法在测试中的独立复刻(算法锁)."""
    device_hash = hashlib.sha256(
        f"{device_id}KRONOS_DEVICE_SALT_2024{license_type}".encode()
    ).hexdigest()
    segment1 = device_hash[:4].upper() + "D"
    segment2 = device_hash[4:9].upper()
    segment3 = device_hash[9:14].upper()
    checksum = hashlib.md5(f"{segment1}{segment2}{segment3}".encode()).hexdigest()[:5].upper()
    return f"LUMO-{segment1}-{segment2}-{segment3}-{checksum}"


@pytest.fixture
def lic_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_USER_DIR", str(tmp_path))
    monkeypatch.setenv("KRONOS_SQLITE_PATH", str(tmp_path / "k.sqlite"))
    from data_store import connection as conn_mod

    conn_mod.reset_for_testing()
    for name in _MODULES:
        sys.modules.pop(name, None)
    yield
    conn_mod.reset_for_testing()
    for name in _MODULES:
        sys.modules.pop(name, None)


def _import_service(monkeypatch, required: str | None = "1", device_id: str = DEVICE_ID):
    if required is None:
        monkeypatch.delenv("KRONOS_LICENSE_REQUIRED", raising=False)
    else:
        monkeypatch.setenv("KRONOS_LICENSE_REQUIRED", required)
    lic = importlib.import_module("webui.services.license_service")
    lic.reset_for_testing()
    monkeypatch.setattr(lic, "_compute_device_id", lambda: device_id)
    return lic


# ---------------------------------------------------------------------------
# 授权码算法
# ---------------------------------------------------------------------------


def test_generate_license_code_matches_admin_algorithm(lic_env, monkeypatch):
    lic = _import_service(monkeypatch)
    assert lic.generate_license_code(DEVICE_ID) == _admin_expected_code(DEVICE_ID)


def test_verify_license_code_roundtrip_and_rejections(lic_env, monkeypatch):
    lic = _import_service(monkeypatch)
    code = lic.generate_license_code(DEVICE_ID)

    ok, _ = lic.verify_license_code(code, DEVICE_ID)
    assert ok

    # 错设备
    ok, msg = lic.verify_license_code(code, OTHER_DEVICE_ID)
    assert not ok and msg

    # 篡改校验码
    tampered = code[:-5] + ("AAAAA" if not code.endswith("AAAAA") else "BBBBB")
    ok, _ = lic.verify_license_code(tampered, DEVICE_ID)
    assert not ok

    # 格式非法(含旧 KRONOS- 前缀:2026-07-23 起前缀为 LUMO-, 旧前缀整体拒绝)
    kronos_prefixed = "KRONOS-" + code.split("-", 1)[1]
    for bad in ("", "LUMO-1234", "FOO-AAAAD-BBBBB-CCCCC-DDDDD", "lumo", kronos_prefixed):
        ok, _ = lic.verify_license_code(bad, DEVICE_ID)
        assert not ok

    # 通用码(U)不支持:门禁只认设备绑定码
    universal = code.replace("D-", "U-", 1)
    ok, _ = lic.verify_license_code(universal, DEVICE_ID)
    assert not ok


# ---------------------------------------------------------------------------
# 激活持久化 (kv/SQLite)
# ---------------------------------------------------------------------------


def test_activate_persists_and_survives_reimport(lic_env, monkeypatch):
    lic = _import_service(monkeypatch)
    code = lic.generate_license_code(DEVICE_ID)

    ok, msg = lic.activate(code)
    assert ok, msg
    assert lic.is_activated()
    status = lic.activation_status()
    assert status["activated"] is True
    assert status["device_id"] == DEVICE_ID

    # 重新导入模块(模拟重启进程):激活状态来自 SQLite kv, 仍然有效
    sys.modules.pop("webui.services.license_service", None)
    lic2 = _import_service(monkeypatch)
    assert lic2.is_activated()


def test_activate_rejects_wrong_code(lic_env, monkeypatch):
    lic = _import_service(monkeypatch)
    ok, _ = lic.activate(lic.generate_license_code(OTHER_DEVICE_ID))
    assert not ok
    assert not lic.is_activated()


def test_device_change_invalidates_activation(lic_env, monkeypatch):
    lic = _import_service(monkeypatch)
    ok, _ = lic.activate(lic.generate_license_code(DEVICE_ID))
    assert ok

    # 硬件变更 → 设备ID变化 → 授权失效
    lic.reset_for_testing()
    monkeypatch.setattr(lic, "_compute_device_id", lambda: OTHER_DEVICE_ID)
    assert not lic.is_activated()


def test_license_required_disabled_by_design(lic_env, monkeypatch):
    """设备验证已按需求注释关闭: 无论 env 取值还是打包态(frozen), 开关恒为 False。"""
    lic = _import_service(monkeypatch, required="1")
    assert lic.license_required() is False

    monkeypatch.setenv("KRONOS_LICENSE_REQUIRED", "0")
    assert lic.license_required() is False

    # 未设 env: 原本 dev 关、打包开; 现在两者都关
    monkeypatch.delenv("KRONOS_LICENSE_REQUIRED", raising=False)
    assert lic.license_required() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert lic.license_required() is False


# ---------------------------------------------------------------------------
# robyn 门禁
# ---------------------------------------------------------------------------


def _import_app(monkeypatch, required: str | None = "1", device_id: str = DEVICE_ID):
    lic = _import_service(monkeypatch, required=required, device_id=device_id)
    module = importlib.import_module("webui.robyn_app")
    return module, lic


def test_gate_disabled_pages_and_api_pass_through(lic_env, monkeypatch):
    """门禁已注释: 未激活状态下页面与 API 都不再被拦截(无 302→/activate, 无 403)。"""
    from robyn.testing import TestClient

    module, _lic = _import_app(monkeypatch)
    with TestClient(module.app) as client:
        for path in ("/", "/desktop", "/desktop/quant-radar"):
            resp = client.get(path)
            assert resp.headers.get("Location") != "/activate", path
            assert resp.status_code != 403, path

        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json().get("error") != "license_required"


def test_gate_whitelists_activation_surface(lic_env, monkeypatch):
    from robyn.testing import TestClient

    module, _lic = _import_app(monkeypatch)
    with TestClient(module.app) as client:
        page = client.get("/activate")
        assert page.status_code == 200
        assert DEVICE_ID in page.text

        status = client.get("/api/license/status")
        assert status.status_code == 200
        payload = status.json()
        # 门禁已注释: required 恒为 False; 激活面(设备ID/激活接口)仍保留可用
        assert payload["required"] is False
        assert payload["activated"] is False
        assert payload["device_id"] == DEVICE_ID

        asset = client.get("/static/lumo_desktop.css")
        assert asset.status_code == 200

        favicon = client.get("/favicon.ico")
        assert favicon.status_code == 200


def test_gate_activation_flow_unlocks(lic_env, monkeypatch):
    from robyn.testing import TestClient

    module, lic = _import_app(monkeypatch)
    good_code = lic.generate_license_code(DEVICE_ID)
    with TestClient(module.app) as client:
        bad = client.post("/api/license/activate", json_data={"license_code": "LUMO-XXXXD-XXXXX-XXXXX-XXXXX"})
        assert bad.status_code == 400
        assert bad.json()["success"] is False

        good = client.post("/api/license/activate", json_data={"license_code": good_code})
        assert good.status_code == 200
        assert good.json()["success"] is True

        assert client.get("/api/jobs").status_code == 200
        assert client.get("/desktop").status_code == 200
        status = client.get("/api/license/status").json()
        assert status["activated"] is True


def test_gate_off_in_dev_by_default(lic_env, monkeypatch):
    from robyn.testing import TestClient

    module, _lic = _import_app(monkeypatch, required=None)
    with TestClient(module.app) as client:
        assert client.get("/desktop").status_code == 200
        assert client.get("/api/jobs").status_code == 200
        status = client.get("/api/license/status").json()
        assert status["required"] is False
