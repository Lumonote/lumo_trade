"""设备指纹稳定性:授权「一重装/重启就丢」的根因回归测试。

历史缺陷:指纹哈希混入 en0/en1 MAC(可插拔 USB 网卡/网络态变化即漂移)、
psutil 有无(dev 与打包产物不同)、system_profiler 超时降级值(含
uuid.getnode() 每进程随机)。v2 指纹只哈希终身不变的硬件锚点。
"""
import subprocess

import pytest

from finetune.license_system.device_fingerprint import DeviceFingerprint


def test_device_id_deterministic_across_instances():
    a = DeviceFingerprint().get_device_fingerprint()["device_id"]
    b = DeviceFingerprint().get_device_fingerprint()["device_id"]
    assert a == b
    assert len(a) == 16 and all(c in "0123456789ABCDEF" for c in a)


def test_volatile_components_do_not_affect_device_id(monkeypatch):
    """MAC/内存/磁盘等易变成分变化,device_id 必须纹丝不动。"""
    base = DeviceFingerprint().get_device_fingerprint()["device_id"]

    monkeypatch.setattr(DeviceFingerprint, "_get_primary_mac", lambda self: "AABBCCDDEEFF")
    with_mac_changed = DeviceFingerprint().get_device_fingerprint()["device_id"]
    assert with_mac_changed == base

    monkeypatch.setattr(DeviceFingerprint, "_get_primary_disk_serial", lambda self: "OTHER_DISK")
    with_disk_changed = DeviceFingerprint().get_device_fingerprint()["device_id"]
    assert with_disk_changed == base


def test_subprocess_failures_still_deterministic(monkeypatch):
    """所有子进程失败(如打包首启超时)时:不抛异常、两次结果一致、无随机成分。"""

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0] if args else "?", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "check_output", boom, raising=False)
    a = DeviceFingerprint().get_device_fingerprint()["device_id"]
    b = DeviceFingerprint().get_device_fingerprint()["device_id"]
    assert a == b


def test_stable_identity_exposed_and_versioned():
    fp = DeviceFingerprint().get_device_fingerprint()
    ident = fp.get("stable_identity")
    assert isinstance(ident, dict) and ident.get("v") == 2
    # 哈希输入里绝不允许出现 MAC / 内存 / 磁盘 等易变键
    assert not ({"mac_address", "memory_total", "disk_serial", "cpu_count"} & set(ident))
