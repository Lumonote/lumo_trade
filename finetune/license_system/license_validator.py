#!/usr/bin/env python3
import json
import base64
import hashlib
import os
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from device_fingerprint import DeviceFingerprint
from json_storage import JSONStorage


class LicenseValidator:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.storage = JSONStorage(data_dir)
        self.device_fp = DeviceFingerprint()
        self.public_key = self._load_public_key()
        self.cache_file = os.path.join(data_dir, '.license_cache')

    def _load_public_key(self):
        """加载公钥"""
        # 首先尝试从keys目录加载
        keys_dir = os.path.join(os.path.dirname(__file__), 'keys')
        public_key_path = os.path.join(keys_dir, 'public.pem')

        # 如果keys目录不存在，尝试从data目录加载
        if not os.path.exists(public_key_path):
            public_key_path = os.path.join(self.data_dir, 'public.pem')

        try:
            with open(public_key_path, 'rb') as f:
                public_key = serialization.load_pem_public_key(f.read())
            return public_key
        except FileNotFoundError:
            print(f"公钥文件未找到，请联系管理员")
            return None
        except Exception as e:
            print(f"加载公钥失败")
            return None

    def activate_license(self, license_code):
        """激活授权码 - 支持设备绑定和通用授权码"""
        try:
            license_code = license_code.strip().upper()
            print(f"开始激活授权码: {license_code}")

            # 1. 验证授权码格式
            if not self._validate_license_format(license_code):
                return False, "授权码格式无效"

            # 2. 检查授权码类型（设备绑定 vs 通用）
            # 授权码格式: KRONOS-XXXXD-XXXXX-XXXXX-XXXXX (设备绑定) 或 KRONOS-XXXXU-XXXXX-XXXXX-XXXXX (通用)
            parts = license_code.split('-')
            if len(parts) != 5:
                return False, "授权码格式无效"

            first_segment = parts[1]  # 第一个段落
            is_device_bound = first_segment.endswith('D')
            is_universal = first_segment.endswith('U')

            if not (is_device_bound or is_universal):
                return False, "授权码类型标识无效"

            # 3. 验证校验码
            if not self._validate_checksum(license_code):
                return False, "授权码校验失败"

            # 4. 查找授权码记录
            license_record = self.storage.find_license(license_code)
            if not license_record:
                return False, "授权码不存在"

            # 5. 检查授权码状态
            if license_record['status'] == 'REVOKED':
                return False, "授权码已被撤销"

            # 6. 验证数字签名
            signature = license_record.get('signature')
            if not signature or not self._verify_signature(license_code, signature):
                return False, "授权码签名验证失败"

            # 7. 获取当前设备指纹
            device_fingerprint = self.device_fp.get_device_fingerprint()
            current_device_id = device_fingerprint['device_id']

            print(f"当前设备ID: {current_device_id}")

            # 8. 设备绑定授权码的特殊处理
            if is_device_bound:
                bound_device_id = license_record.get('bound_device_id')
                if not bound_device_id:
                    return False, "设备绑定授权码缺少绑定设备信息"

                if bound_device_id != current_device_id:
                    return False, f"授权码绑定的设备({bound_device_id[:8]}...)与当前设备({current_device_id[:8]}...)不匹配"

                # 验证授权码是否真的是为当前设备生成的（使用设备ID盐值验证）
                if not self._validate_device_bound_license(license_code, current_device_id):
                    return False, "授权码与当前设备不匹配，可能是伪造的授权码"

                # 设备绑定授权码不允许重复激活
                if license_record['status'] == 'ACTIVATED':
                    return False, "设备绑定授权码已激活，不可重复使用"

            # 9. 通用授权码的设备检查
            elif is_universal:
                # 检查当前设备是否已有其他授权
                existing_activation = self.storage.find_activation(current_device_id)
                if existing_activation and existing_activation['license_code'] != license_code:
                    return False, f"当前设备已激活其他授权码: {existing_activation['license_code']}"

                # 检查授权码是否已在其他设备激活
                if license_record['status'] == 'ACTIVATED':
                    existing_activation = self.storage.find_activation_by_license(license_code)
                    if existing_activation and existing_activation['device_id'] != current_device_id:
                        return False, "通用授权码已在其他设备激活"

            print("正在激活授权...")

            # 10. 更新授权状态
            if not self.storage.update_license_status(license_code, 'ACTIVATED', current_device_id):
                return False, "更新授权状态失败"

            # 11. 记录激活信息
            if not self.storage.add_activation_record(
                    license_code,
                    current_device_id,
                    device_fingerprint['hardware_info']
            ):
                return False, "记录激活信息失败"

            # 12. 生成本地授权缓存
            if not self._generate_license_cache(license_code, device_fingerprint):
                return False, "生成本地授权缓存失败"

            print(f"✓ 授权码激活成功")
            print(f"  - 授权类型: {license_record.get('license_type', 'PERMANENT')}")
            print(f"  - 激活模式: {'DEVICE_BOUND' if is_device_bound else 'UNIVERSAL'}")
            print(f"  - 设备ID: {current_device_id[:8]}...")

            return True, f"授权激活成功！设备已绑定到授权码: {license_code}"

        except Exception as e:
            print(f"激活过程异常: {e}")
            return False, f"激活失败: {str(e)}"

    def validate_license(self):
        """验证当前设备的授权状态 - 优化缓存机制"""
        try:
            print("正在验证授权状态...")

            # 1. 检查本地缓存
            if not os.path.exists(self.cache_file):
                print("未找到本地授权缓存")
                return False, "设备未激活授权"

            # 2. 读取缓存
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except Exception as e:
                print(f"读取授权缓存失败: {e}")
                return False, "授权缓存文件损坏"

            # 3. 验证缓存完整性
            if not self._verify_cache_integrity(cache_data):
                print("授权缓存完整性验证失败")
                return False, "授权缓存已被篡改"

            # 4. 验证设备一致性
            stored_fingerprint = cache_data['data']['device_fingerprint']
            is_consistent, ratio = self.device_fp.verify_device_consistency(stored_fingerprint)

            if not is_consistent:
                return False, f"设备硬件发生重大变更（一致性: {ratio:.0%}），授权失效"

            # 5. 检查缓存版本和有效期
            cache_version = cache_data['data'].get('cache_version', '1.0')
            last_validation = cache_data['data'].get('last_validation')

            # 新版本缓存支持更长的有效期
            if cache_version >= '2.0':
                # 检查是否需要重新验证（7天一次）
                if last_validation:
                    last_time = datetime.fromisoformat(last_validation)
                    if (datetime.now() - last_time).days < 7:
                        print("✓ 授权验证通过（缓存有效）")
                        return True, f"授权有效（设备一致性: {ratio:.0%}）"

            # 6. 执行完整验证（旧版本缓存或缓存过期）
            license_code = cache_data['data']['license_code']
            license_record = self.storage.find_license(license_code)

            if license_record and license_record['status'] != 'ACTIVATED':
                return False, "授权已被撤销"

            # 7. 更新缓存的最后验证时间
            cache_data['data']['last_validation'] = datetime.now().isoformat()
            cache_data['data']['cache_version'] = '2.0'

            # 重新计算完整性校验
            cache_content = json.dumps(cache_data['data'], sort_keys=True)
            cache_data['integrity_hash'] = hashlib.sha256(cache_content.encode()).hexdigest()

            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            print("✓ 授权验证通过")
            return True, f"授权验证通过（设备一致性: {ratio:.0%}）"

        except Exception as e:
            print(f"验证过程异常: {e}")
            return False, f"验证过程异常: {str(e)}"

    def get_license_info(self):
        """获取当前授权信息"""
        if not os.path.exists(self.cache_file):
            return None

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            data = cache_data['data']
            return {
                "license_code": data['license_code'],
                "activation_time": data['activation_time'],
                "device_id": data['device_fingerprint']['device_id'],
                "license_type": "PERMANENT",
                "system_info": data['device_fingerprint']['system_info']
            }
        except:
            return None

    def _validate_license_format(self, license_code):
        """验证授权码格式"""
        import re
        pattern = r'^KRONOS-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$'
        return re.match(pattern, license_code) is not None

    def _validate_checksum(self, license_code):
        """验证授权码校验码"""
        parts = license_code.split('-')
        if len(parts) != 5:
            return False

        # 重新计算校验码
        raw_data = ''.join(parts[1:4])  # 取中间三段
        expected_checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

        return parts[4] == expected_checksum

    def _validate_device_bound_license(self, license_code, device_id):
        """验证设备绑定授权码是否与当前设备匹配"""
        # 使用与服务端相同的盐值和算法重新生成授权码
        salt = "KRONOS_DEVICE_SALT_2024"
        combined_data = f"{device_id}{salt}PERMANENT"  # 假设是PERMANENT类型

        # 生成基于设备ID的哈希
        device_hash = hashlib.sha256(combined_data.encode()).hexdigest()

        # 从哈希中提取段落
        segment1 = device_hash[:4].upper() + "D"  # D表示设备绑定
        segment2 = device_hash[4:9].upper()
        segment3 = device_hash[9:14].upper()

        # 计算校验码
        raw_data = f"{segment1}{segment2}{segment3}"
        checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

        # 生成期望的授权码
        expected_license_code = f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"

        return license_code == expected_license_code

    def _verify_signature(self, license_code, signature):
        """验证数字签名"""
        if not self.public_key:
            print("警告: 跳过签名验证")
            return True  # 如果没有公钥，跳过签名验证

        try:
            signature_bytes = base64.b64decode(signature)
            self.public_key.verify(
                signature_bytes,
                license_code.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception as e:
            print(f"签名验证失败")
            return False

    def _generate_license_cache(self, license_code, device_fingerprint):
        """生成本地授权缓存"""
        try:
            cache_data = {
                "license_code": license_code,
                "device_fingerprint": device_fingerprint,
                "activation_time": datetime.now().isoformat(),
                "cache_version": "1.0"
            }

            # 计算缓存完整性校验
            cache_content = json.dumps(cache_data, sort_keys=True)
            cache_hash = hashlib.sha256(cache_content.encode()).hexdigest()

            final_cache = {
                "data": cache_data,
                "integrity_hash": cache_hash
            }

            # 确保data目录存在
            os.makedirs(self.data_dir, exist_ok=True)

            # 写入缓存文件
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(final_cache, f, indent=2, ensure_ascii=False)

            # 设置文件为隐藏（Windows）
            if os.name == 'nt':
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetFileAttributesW(self.cache_file, 2)  # 隐藏属性
                except:
                    pass

            return True
        except Exception as e:
            print(f"生成授权缓存失败")
            return False

    def _generate_cache_hash(self, cache_data):
        """生成缓存数据的完整性哈希"""
        # 创建缓存数据的副本，排除integrity_hash字段
        data_copy = cache_data.copy()
        if 'integrity_hash' in data_copy:
            del data_copy['integrity_hash']

        # 生成一致的JSON字符串
        cache_content = json.dumps(data_copy, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(cache_content.encode('utf-8')).hexdigest()

    def _verify_cache_integrity(self, cache_data):
        """验证缓存完整性"""
        stored_hash = cache_data.get('integrity_hash')
        if not stored_hash:
            return False

        calculated_hash = self._generate_cache_hash(cache_data)
        return stored_hash == calculated_hash

    def revoke_license(self):
        """撤销当前设备的授权"""
        try:
            # 获取当前授权信息
            info = self.get_license_info()
            if info:
                # 更新激活记录状态
                self.storage.revoke_activation(info['device_id'])
                print("授权状态已更新")

            # 删除缓存文件
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
                print("授权已成功撤销")

            return True
        except Exception as e:
            print(f"撤销授权失败")
            return False

    def check_device_fingerprint(self):
        """检查设备指纹信息（调试用）"""
        fingerprint = self.device_fp.get_device_fingerprint()

        print("=" * 50)
        print("         当前设备指纹")
        print("=" * 50)
        print(f"设备ID: {fingerprint['device_id']}")
        print(f"系统: {fingerprint['system_info']['system']} {fingerprint['system_info']['release']}")
        print(f"CPU: {fingerprint['hardware_info']['cpu_id']}")
        print(f"主板: {fingerprint['hardware_info']['motherboard']}")
        print(f"硬盘: {fingerprint['hardware_info']['disk_serial']}")
        print(f"MAC: {fingerprint['hardware_info']['mac_address']}")
        print(f"内存: {fingerprint['hardware_info']['memory_total'] // (1024 ** 3)} GB")

        return fingerprint


# 测试程序
if __name__ == "__main__":
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    validator = LicenseValidator(data_dir)

    print("=" * 60)
    print("        Kronos 授权状态检查")
    print("=" * 60)

    # 检查当前授权状态
    is_valid, message = validator.validate_license()

    if is_valid:
        print(f"✓ {message}")

        # 显示授权信息
        info = validator.get_license_info()
        if info:
            print(f"\n📋 授权信息:")
            print(f"   授权码: {info['license_code']}")
            print(f"   激活时间: {info['activation_time'][:19].replace('T', ' ')}")
            print(f"   设备ID: {info['device_id']}")
            print(f"   系统: {info['system_info']['system']} {info['system_info']['release']}")
    else:
        print(f"✗ {message}")

        # 提供激活选项
        choice = input("\n是否要激活新的授权码？(y/n): ").strip().lower()
        if choice == 'y':
            license_code = input("请输入授权码: ").strip()
            if license_code:
                print("\n" + "=" * 50)
                success, msg = validator.activate_license(license_code)
                print("=" * 50)
                print(f"{'✓' if success else '✗'} {msg}")
            else:
                print("授权码不能为空")
