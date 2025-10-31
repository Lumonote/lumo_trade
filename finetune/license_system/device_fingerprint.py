#!/usr/bin/env python3
import platform
import hashlib
import subprocess
import uuid
import psutil
import json
import re
import os


class DeviceFingerprint:
    def __init__(self):
        self.system = platform.system()

    def get_device_fingerprint(self):
        """获取设备唯一指纹"""
        hardware_info = self._collect_hardware_info()

        # 生成稳定的设备ID
        combined_info = json.dumps(hardware_info, sort_keys=True)
        device_id = hashlib.sha256(combined_info.encode()).hexdigest()[:16].upper()

        return {
            "device_id": device_id,
            "hardware_info": hardware_info,
            "system_info": self._get_system_info()
        }

    def _collect_hardware_info(self):
        """收集关键硬件信息"""
        info = {}

        # CPU信息
        info['cpu_id'] = self._get_cpu_id()
        info['cpu_count'] = psutil.cpu_count(logical=False)

        # 主板信息
        info['motherboard'] = self._get_motherboard_info()

        # 硬盘信息
        info['disk_serial'] = self._get_primary_disk_serial()

        # 内存信息
        info['memory_total'] = psutil.virtual_memory().total

        # 网卡MAC地址
        info['mac_address'] = self._get_primary_mac()

        # 系统UUID
        info['system_uuid'] = self._get_system_uuid()

        return info

    def _get_cpu_id(self):
        """获取CPU ID"""
        try:
            if self.system == "Windows":
                result = subprocess.run(
                    ['wmic', 'cpu', 'get', 'ProcessorId', '/value'],
                    capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.split('\n'):
                    if 'ProcessorId=' in line:
                        return line.split('=')[1].strip()

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
                    ['sysctl', '-n', 'machdep.cpu.brand_string'],
                    capture_output=True, text=True, timeout=10
                )
                cpu_brand = result.stdout.strip()
                result2 = subprocess.run(
                    ['sysctl', '-n', 'hw.ncpu'],
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

        # 使用机器UUID作为备选
        return str(uuid.getnode())

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
                result = subprocess.run(
                    ['system_profiler', 'SPSerialATADataType'],
                    capture_output=True, text=True, timeout=10
                )
                # 解析序列号
                for line in result.stdout.split('\n'):
                    if 'Serial Number' in line:
                        return line.split(':')[1].strip()

        except Exception as e:
            print(f"获取硬盘序列号失败: {e}")

        return "UNKNOWN_DISK"

    def _get_primary_mac(self):
        """获取主网卡MAC地址"""
        try:
            # 获取默认网关接口
            interfaces = psutil.net_if_addrs()

            # 优先获取非回环接口的MAC
            for interface_name, addresses in interfaces.items():
                if 'lo' not in interface_name.lower() and 'loopback' not in interface_name.lower():
                    for addr in addresses:
                        if addr.family == psutil.AF_LINK:  # MAC地址
                            mac = addr.address
                            if mac != '00:00:00:00:00:00':
                                return mac.replace(':', '').upper()

        except Exception as e:
            print(f"获取MAC地址失败: {e}")

        # 备选方案
        return format(uuid.getnode(), '012x').upper()

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
