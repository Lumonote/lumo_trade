"""设备验证授权服务(桌面打包版功能门禁).

历史: 设备验证原先只活在老启动器 tools/launchers/kronos_modern_gui.py 里,
Tauri + PyInstaller(kronos_webui_backend) 新打包链换了入口后从未接入,
打包 App 因此完全无门禁。本模块把同一套授权算法移植进 webui 服务层,
由 robyn_app 的全局 before_request 门禁消费。

算法契约(不可改, 否则已发授权码全部失效):
- 设备ID: finetune/license_system/device_fingerprint.py 的 16 位指纹,
  与老启动器逐字节一致, license_admin 按用户上报的这个 ID 生成授权码。
- 授权码: license_admin/generate_license.py 同款 —
  sha256(device_id + KRONOS_DEVICE_SALT_2024 + PERMANENT) 取段 +
  md5 前 5 位校验码, 格式 LUMO-xxxxD-xxxxx-xxxxx-xxxxx(D=设备绑定)。
  校验码只覆盖中间三段, 前缀纯展示(2026-07-23 由 KRONOS- 改为 LUMO-,
  段值与盐不变); 只支持设备绑定码, 通用码(U)需要服务端存证, 桌面离线链路不认。

激活记录进 SQLite kv_cache(namespace=license), 不落散文件。
设备指纹要跑多个 system_profiler 子进程(秒级), 全模块只算一次并缓存;
robyn 启动时可用 warm_in_background() 预热, 请求路径上永不重复采集。
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from typing import Any, Optional

from data_store import kv_repo
from finetune.license_system.license_codec import (
    LICENSE_CODE_PATTERN,
    LICENSE_SALT,
    LICENSE_TYPE,
    generate_device_license,
    verify_device_license,
)

KV_NAMESPACE = "license"
KV_KEY = "activation"

_lock = threading.Lock()
_device_id_cache: Optional[str] = None
_activated_cache: bool = False


def license_required() -> bool:
    """门禁开关: KRONOS_LICENSE_REQUIRED 显式 1/0 优先, 未设时打包态(frozen)默认开。"""
    env = os.environ.get("KRONOS_LICENSE_REQUIRED", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off"}:
        return False
    return bool(getattr(sys, "frozen", False))


def _compute_device_id() -> str:
    from finetune.license_system.device_fingerprint import DeviceFingerprint

    return DeviceFingerprint().get_device_fingerprint()["device_id"]


def get_device_id() -> str:
    global _device_id_cache
    if _device_id_cache:
        return _device_id_cache
    with _lock:
        if not _device_id_cache:
            _device_id_cache = _compute_device_id()
    return _device_id_cache


def warm_in_background() -> None:
    """启动期预热设备指纹, 让 /activate 首屏不用等 system_profiler。"""
    threading.Thread(target=_safe_warm, name="license-warm", daemon=True).start()


def _safe_warm() -> None:
    try:
        get_device_id()
    except Exception:
        pass


def generate_license_code(device_id: str, license_type: str = LICENSE_TYPE) -> str:
    """与 license_admin/generate_license.py 完全一致的设备绑定授权码。"""
    return generate_device_license(device_id, license_type)


def verify_license_code(license_code: str, device_id: Optional[str] = None) -> tuple[bool, str]:
    code = str(license_code or "").strip().upper()
    if not LICENSE_CODE_PATTERN.match(code):
        return False, "授权码格式无效"
    if not code.split("-")[1].endswith("D"):
        return False, "仅支持设备绑定授权码(第二段以 D 结尾)"
    if device_id is None:
        device_id = get_device_id()
    if not verify_device_license(code, device_id):
        return False, "授权码与当前设备不匹配"
    return True, "授权码有效"


def activate(license_code: str) -> tuple[bool, str]:
    global _activated_cache
    device_id = get_device_id()
    ok, message = verify_license_code(license_code, device_id)
    if not ok:
        return False, message
    kv_repo.set_(
        KV_NAMESPACE,
        KV_KEY,
        {
            "license_code": str(license_code).strip().upper(),
            "device_id": device_id,
            "activated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    _activated_cache = True
    return True, "授权激活成功"


def _stored_activation() -> Optional[dict[str, Any]]:
    entry = kv_repo.get(KV_NAMESPACE, KV_KEY)
    if not entry:
        return None
    payload = entry[0]
    return payload if isinstance(payload, dict) else None


def is_activated() -> bool:
    """当前设备是否已激活: 存证存在且授权码对当前设备指纹仍然成立。

    激活成功后缓存 True(robyn 每请求都会问); 未激活不缓存负结果,
    kv 单读 <1ms, 且激活动作可能来自其它 worker 线程。
    """
    global _activated_cache
    if _activated_cache:
        return True
    record = _stored_activation()
    if not record:
        return False
    ok, _msg = verify_license_code(str(record.get("license_code", "")))
    if ok:
        _activated_cache = True
    return ok


def activation_status() -> dict[str, Any]:
    record = _stored_activation() or {}
    activated = is_activated()
    return {
        "required": license_required(),
        "activated": activated,
        "device_id": get_device_id(),
        "license_code": record.get("license_code") if activated else None,
        "activated_at": record.get("activated_at") if activated else None,
    }


def revoke() -> None:
    global _activated_cache
    kv_repo.delete(KV_NAMESPACE, KV_KEY)
    _activated_cache = False


def reset_for_testing() -> None:
    global _device_id_cache, _activated_cache
    with _lock:
        _device_id_cache = None
    _activated_cache = False
