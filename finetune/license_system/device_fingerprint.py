#!/usr/bin/env python3
import platform
import hashlib
import subprocess
import uuid
import json
import re
import os

try:
    import psutil  # type: ignore
except ImportError:
    psutil = None


class DeviceFingerprint:
    def __init__(self):
        self.system = platform.system()

    def get_device_fingerprint(self):
        """获取设备唯一指纹

        v2: device_id 只由「终身不变」的硬件锚点派生(平台UUID/整机序列号/CPU/架构),
        不再混入 MAC(可插拔网卡与网络态会变)、psutil 读数(dev 与打包产物有无不同)、
        system_profiler 超时降级值(曾引入 uuid.getnode() 每进程随机)——这些曾导致
        打包 App 每次完整重启后授权码与新指纹失配,表现为「重装后授权丢失」。
        hardware_info 仍保留全量字段用于展示/一致性参考,但不参与哈希。
        """
        hardware_info = self._collect_hardware_info()
        stable_identity = self._stable_identity(hardware_info)

        combined_info = json.dumps(stable_identity, sort_keys=True)
        device_id = hashlib.sha256(combined_info.encode()).hexdigest()[:16].upper()

        return {
            "device_id": device_id,
            "stable_identity": stable_identity,
            "hardware_info": hardware_info,
            "system_info": self._get_system_info()
        }

    def _stable_identity(self, hardware_info):
        """device_id 的唯一哈希输入:全部成分终身不变,取不到用固定哨兵,绝不随机。"""
        uuid_value, serial_value = self._get_platform_identifiers()
        return {
            "v": 2,
            "platform_uuid": uuid_value or "UNKNOWN_PLATFORM_UUID",
            "platform_serial": serial_value or "UNKNOWN_PLATFORM_SERIAL",
            "cpu_id": hardware_info.get('cpu_id') or "UNKNOWN_CPU",
            "machine": platform.machine(),
        }

    def _get_platform_identifiers(self):
        """(平台UUID, 整机序列号)。用毫秒级且开机即得的稳定来源,避免 system_profiler 超时。"""
        try:
            if self.system == "Darwin":
                result = subprocess.run(
                    ['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'],
                    capture_output=True, text=True, timeout=10
                )
                uuid_value = serial_value = None
                for line in result.stdout.split('\n'):
                    if 'IOPlatformUUID' in line and '=' in line:
                        uuid_value = line.split('=')[1].strip().strip('"')
                    elif 'IOPlatformSerialNumber' in line and '=' in line:
                        serial_value = line.split('=')[1].strip().strip('"')
                return uuid_value, serial_value
            if self.system == "Linux":
                uuid_value = serial_value = None
                for source, target in (
                    ('/sys/class/dmi/id/product_uuid', 'uuid'),
                    ('/etc/machine-id', 'uuid'),
                    ('/sys/class/dmi/id/board_serial', 'serial'),
                ):
                    try:
                        with open(source, 'r') as f:
                            value = f.read().strip()
                        if value and "O.E.M." not in value:
                            if target == 'uuid' and not uuid_value:
                                uuid_value = value
                            elif target == 'serial' and not serial_value:
                                serial_value = value
                    except (FileNotFoundError, PermissionError, OSError):
                        continue
                return uuid_value, serial_value
            if self.system == "Windows":
                uuid_value = None
                serial_value = None
                try:
                    result = subprocess.run(
                        ['wmic', 'csproduct', 'get', 'UUID', '/value'],
                        capture_output=True, text=True, timeout=10
                    )
                    result2 = subprocess.run(
                        ['wmic', 'baseboard', 'get', 'SerialNumber', '/value'],
                        capture_output=True, text=True, timeout=10
                    )
                    output = f"{result.stdout}\n{result2.stdout}"
                except (FileNotFoundError, OSError, subprocess.SubprocessError):
                    output = ""

                if not output.strip():
                    powershell = (
                        "$cs=Get-CimInstance Win32_ComputerSystemProduct;"
                        "$bb=Get-CimInstance Win32_BaseBoard;"
                        "Write-Output ('UUID=' + $cs.UUID);"
                        "Write-Output ('SerialNumber=' + $bb.SerialNumber)"
                    )
                    result = subprocess.run(
                        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', powershell],
                        capture_output=True, text=True, timeout=10
                    )
                    output = result.stdout

                for line in output.splitlines():
                    key, separator, raw_value = line.partition('=')
                    if not separator:
                        continue
                    value = raw_value.strip()
                    if key.strip() == 'UUID' and value and value.upper() != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                        uuid_value = value.upper()
                    elif key.strip() == 'SerialNumber' and value and value.lower() != "to be filled by o.e.m.":
                        serial_value = value
                return uuid_value, serial_value
        except Exception as e:
            print(f"获取平台标识失败: {e}")
        return None, None

    def _collect_hardware_info(self):
        """收集关键硬件信息"""
        info = {}

        # CPU信息
        info['cpu_id'] = self._get_cpu_id()
        try:
            if psutil is not None:
                info['cpu_count'] = psutil.cpu_count(logical=False)
            else:
                info['cpu_count'] = os.cpu_count() or 0
        except Exception:
            info['cpu_count'] = os.cpu_count() or 0

        # 主板信息
        info['motherboard'] = self._get_motherboard_info()

        # 硬盘信息
        info['disk_serial'] = self._get_primary_disk_serial()

        # 内存信息
        try:
            if psutil is not None:
                info['memory_total'] = psutil.virtual_memory().total
            else:
                info['memory_total'] = 0
        except Exception:
            info['memory_total'] = 0

        # 网卡MAC地址
        info['mac_address'] = self._get_primary_mac()

        # 系统UUID
        info['system_uuid'] = self._get_system_uuid()

        return info

    def _get_cpu_id(self):
        """获取CPU ID"""
        try:
            if self.system == "Windows":
                try:
                    result = subprocess.run(
                        ['wmic', 'cpu', 'get', 'ProcessorId', '/value'],
                        capture_output=True, text=True, timeout=10
                    )
                    output = result.stdout
                except (FileNotFoundError, OSError, subprocess.SubprocessError):
                    output = ""
                if not output.strip():
                    powershell = (
                        "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
                        "Write-Output ('ProcessorId=' + $cpu.ProcessorId)"
                    )
                    result = subprocess.run(
                        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', powershell],
                        capture_output=True, text=True, timeout=10
                    )
                    output = result.stdout
                for line in output.splitlines():
                    if 'ProcessorId=' in line:
                        value = line.split('=', 1)[1].strip()
                        if value:
                            return value.upper()

            elif self.system == "Linux":
                with open('/proc/cpuinfo', 'r') as f:
                    for line in f:
                        if 'processor' in line or 'serial' in line:
                            return line.split(':')[1].strip()

                # 备选方案：使用CPU特征
                result = subprocess.run(['lscpu'], capture_output=True, text=True, timeout=10)
                return hashlib.md5(result.stdout.encode()).hexdigest()[:16]

            elif self.system == "Darwin":  # macOS
                result = subprocess.run(
                    ['/usr/sbin/sysctl', '-n', 'machdep.cpu.brand_string'],
                    capture_output=True, text=True, timeout=10
                )
                cpu_brand = result.stdout.strip()
                result2 = subprocess.run(
                    ['/usr/sbin/sysctl', '-n', 'hw.ncpu'],
                    capture_output=True, text=True, timeout=10
                )
                cpu_count = result2.stdout.strip()
                return hashlib.md5(f"{cpu_brand}_{cpu_count}".encode()).hexdigest()[:16]

        except Exception as e:
            print(f"获取CPU ID失败: {e}")

        return "UNKNOWN_CPU"

    def _get_motherboard_info(self):
        """获取主板信息"""
        try:
            if self.system == "Windows":
                result = subprocess.run(
                    ['wmic', 'baseboard', 'get', 'SerialNumber', '/value'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'SerialNumber=' in line:
                        serial = line.split('=')[1].strip()
                        if serial and serial != "To be filled by O.E.M.":
                            return serial

            elif self.system == "Linux":
                try:
                    result = subprocess.run(
                        ['sudo', 'dmidecode', '-s', 'baseboard-serial-number'],
                        capture_output=True, text=True, timeout=10
                    )
                    serial = result.stdout.strip()
                    if serial and "Not Specified" not in serial:
                        return serial
                except:
                    # 无sudo权限时的备选方案
                    try:
                        with open('/sys/class/dmi/id/board_serial', 'r') as f:
                            return f.read().strip()
                    except:
                        pass

            elif self.system == "Darwin":
                result = subprocess.run(
                    ['system_profiler', 'SPHardwareDataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'Serial Number' in line:
                        return line.split(':')[1].strip()

        except Exception as e:
            print(f"获取主板信息失败: {e}")

        # 固定哨兵(不用 uuid.getnode(): 取不到 MAC 时它每进程随机,曾污染设备指纹)
        return "UNKNOWN_MOTHERBOARD"

    def _get_primary_disk_serial(self):
        """获取主硬盘序列号"""
        try:
            if self.system == "Windows":
                result = subprocess.run(
                    ['wmic', 'diskdrive', 'get', 'SerialNumber', '/value'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'SerialNumber=' in line:
                        serial = line.split('=')[1].strip()
                        if serial:
                            return serial

            elif self.system == "Linux":
                # 尝试获取第一个非循环设备的序列号
                result = subprocess.run(['lsblk', '-o', 'NAME,SERIAL', '-n'],
                                        capture_output=True, text=True, timeout=10)
                for line in result.stdout.split('\n'):
                    if line and not line.startswith('loop'):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1]:
                            return parts[1]

            elif self.system == "Darwin":
                result_nvme = subprocess.run(
                    ['system_profiler', 'SPNVMeDataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result_nvme.stdout.split('\n'):
                    if 'Serial Number' in line:
                        return line.split(':')[1].strip()
                result_sata = subprocess.run(
                    ['system_profiler', 'SPSerialATADataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result_sata.stdout.split('\n'):
                    if 'Serial Number' in line:
                        return line.split(':')[1].strip()
                result_storage = subprocess.run(
                    ['system_profiler', 'SPStorageDataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result_storage.stdout.split('\n'):
                    if 'Serial Number' in line:
                        return line.split(':')[1].strip()

        except Exception as e:
            print(f"获取硬盘序列号失败: {e}")

        return "UNKNOWN_DISK"

    def _get_primary_mac(self):
        """获取主网卡MAC地址"""
        try:
            if self.system == "Darwin":
                result = subprocess.run(
                    ['networksetup', '-listallhardwareports'],
                    capture_output=True, text=True, timeout=10
                )
                device = None
                for line in result.stdout.split('\n'):
                    if line.strip().startswith('Device:') and ('en0' in line or 'en1' in line):
                        device = line.split(':')[1].strip()
                        break
                if device:
                    ifconfig = subprocess.run(
                        ['ifconfig', device],
                        capture_output=True, text=True, timeout=10
                    )
                    for l in ifconfig.stdout.split('\n'):
                        if 'ether ' in l:
                            mac = l.split('ether')[1].strip()
                            return mac.replace(':', '').upper()
            if psutil is not None:
                interfaces = psutil.net_if_addrs()
                for interface_name, addresses in interfaces.items():
                    if 'lo' not in interface_name.lower() and 'loopback' not in interface_name.lower():
                        for addr in addresses:
                            if getattr(addr, "family", None) == getattr(psutil, "AF_LINK", None):
                                mac = getattr(addr, "address", "")
                                if mac and mac != '00:00:00:00:00:00':
                                    return mac.replace(':', '').upper()

        except Exception as e:
            print(f"获取MAC地址失败: {e}")

        # 固定哨兵(同上, uuid.getnode() 随机风险; MAC 本就不参与 device_id 哈希)
        return "UNKNOWN_MAC"

    def _get_system_uuid(self):
        """获取系统UUID - 使用稳定的硬件UUID，不使用随机生成"""
        try:
            if self.system == "Windows":
                result = subprocess.run(
                    ['wmic', 'csproduct', 'get', 'UUID', '/value'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'UUID=' in line:
                        uuid_value = line.split('=')[1].strip()
                        if uuid_value and uuid_value != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                            return uuid_value

            elif self.system == "Linux":
                # 尝试多个稳定的硬件UUID来源
                uuid_sources = [
                    '/sys/class/dmi/id/product_uuid',
                    '/sys/class/dmi/id/board_asset_tag',
                    '/etc/machine-id',
                    '/var/lib/dbus/machine-id'
                ]

                for source in uuid_sources:
                    try:
                        with open(source, 'r') as f:
                            uuid_value = f.read().strip()
                            if uuid_value and uuid_value != "To Be Filled By O.E.M.":
                                return uuid_value
                    except (FileNotFoundError, PermissionError):
                        continue

            elif self.system == "Darwin":
                result = subprocess.run(
                    ['system_profiler', 'SPHardwareDataType'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'Hardware UUID' in line:
                        return line.split(':')[1].strip()

        except Exception as e:
            print(f"获取系统UUID失败: {e}")

        # 备选方案：使用其他稳定硬件特征的组合哈希，而不是随机UUID
        # 这样即使UUID获取失败，设备ID仍然稳定
        fallback_info = f"{self._get_cpu_id()}_{self._get_primary_mac()}_{platform.machine()}"
        return hashlib.md5(fallback_info.encode()).hexdigest()

    def _get_system_info(self):
        """获取系统信息"""
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node()
        }

    def verify_device_consistency(self, stored_fingerprint):
        """验证设备一致性"""
        current_fingerprint = self.get_device_fingerprint()

        # 比较关键硬件信息
        critical_fields = ['cpu_id', 'motherboard', 'disk_serial', 'mac_address']

        matches = 0
        for field in critical_fields:
            stored_value = stored_fingerprint['hardware_info'].get(field)
            current_value = current_fingerprint['hardware_info'].get(field)

            if stored_value and current_value and stored_value == current_value:
                matches += 1

        # 至少3个关键字段匹配才认为是同一设备
        consistency_ratio = matches / len(critical_fields)
        return consistency_ratio >= 0.75, consistency_ratio


# 测试工具
if __name__ == "__main__":
    fp = DeviceFingerprint()
    fingerprint = fp.get_device_fingerprint()

    print("=" * 50)
    print("         设备指纹信息")
    print("=" * 50)
    print(f"设备ID: {fingerprint['device_id']}")
    print(f"系统: {fingerprint['system_info']['system']} {fingerprint['system_info']['release']}")
    print(f"CPU: {fingerprint['hardware_info']['cpu_id']}")
    print(f"主板: {fingerprint['hardware_info']['motherboard']}")
    print(f"硬盘: {fingerprint['hardware_info']['disk_serial']}")
    print(f"MAC: {fingerprint['hardware_info']['mac_address']}")
    print(f"内存: {fingerprint['hardware_info']['memory_total'] // (1024 ** 3)} GB")
