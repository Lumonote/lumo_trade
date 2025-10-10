#!/usr/bin/env python3
import json
import hashlib
import time
import secrets
import base64
import os
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from json_storage import JSONStorage


class LicenseGenerator:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.storage = JSONStorage(data_dir)
        self.config = self._load_config()
        self.private_key = self._load_or_create_private_key()

    def _load_config(self):
        """加载配置文件"""
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            # 创建默认配置
            default_config = {
                "product_name": "KRONOS",
                "version": "1.0",
                "license_format": "KRONOS-{segment1}-{segment2}-{segment3}-{checksum}",
                "rsa_key_size": 2048
            }
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            return default_config

    def _load_or_create_private_key(self):
        """加载或创建私钥"""
        keys_dir = os.path.join(os.path.dirname(__file__), 'keys')
        os.makedirs(keys_dir, exist_ok=True)

        private_key_path = os.path.join(keys_dir, 'private.pem')
        public_key_path = os.path.join(keys_dir, 'public.pem')

        try:
            # 尝试加载现有私钥
            with open(private_key_path, 'rb') as f:
                private_key = serialization.load_pem_private_key(f.read(), password=None)
            print("已加载现有RSA密钥对")
            return private_key
        except FileNotFoundError:
            # 生成新的RSA密钥对
            print("生成新的RSA密钥对...")
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=self.config.get('rsa_key_size', 2048)
            )

            # 保存私钥
            with open(private_key_path, 'wb') as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))

            # 保存公钥
            public_key = private_key.public_key()
            with open(public_key_path, 'wb') as f:
                f.write(public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))

            # 设置文件权限（仅所有者可读写）
            os.chmod(private_key_path, 0o600)
            os.chmod(public_key_path, 0o644)

            print("密钥对已生成并保存")
            return private_key

    def generate_license(self, license_type="PERMANENT", device_id=None):
        """生成单个授权码"""
        if device_id:
            # 基于设备ID生成绑定授权码
            return self._generate_device_bound_license(device_id, license_type)
        else:
            # 生成通用授权码（向后兼容）
            return self._generate_universal_license(license_type)

    def _generate_device_bound_license(self, device_id, license_type="PERMANENT"):
        """生成与设备ID绑定的授权码"""
        # 使用设备ID作为盐值生成确定性的授权码（移除时间依赖）
        salt = "KRONOS_DEVICE_SALT_2024"
        combined_data = f"{device_id}{salt}{license_type}"  # 只基于设备ID和许可证类型

        # 生成基于设备ID的哈希
        device_hash = hashlib.sha256(combined_data.encode()).hexdigest()

        # 从哈希中提取段落
        segment1 = device_hash[:4].upper() + "D"  # D表示设备绑定
        segment2 = device_hash[4:9].upper()
        segment3 = device_hash[9:14].upper()

        # 计算校验码（只使用前三段，与客户端验证逻辑保持一致）
        raw_data = f"{segment1}{segment2}{segment3}"
        checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

        # 生成最终授权码
        license_code = f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"

        # 创建授权记录
        license_record = {
            "license_code": license_code,
            "license_type": license_type,
            "generated_time": datetime.now().isoformat(),
            "status": "UNUSED",
            "device_fingerprint": None,
            "bound_device_id": device_id,  # 记录绑定的设备ID
            "activation_time": None,
            "signature": self._sign_license_data(license_code)
        }

        # 保存到本地JSON
        self.storage.add_license(license_record)

        return license_code

    def _generate_universal_license(self, license_type="PERMANENT"):
        """生成通用授权码（向后兼容）"""
        # 生成随机段
        segment1 = secrets.token_hex(2).upper()[:4] + "U"  # U表示通用授权码
        segment2 = secrets.token_hex(3).upper()[:5]
        segment3 = secrets.token_hex(3).upper()[:5]

        # 计算校验码
        raw_data = f"{segment1}{segment2}{segment3}"
        checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

        # 生成最终授权码
        license_code = f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"

        # 创建授权记录
        license_record = {
            "license_code": license_code,
            "license_type": license_type,
            "generated_time": datetime.now().isoformat(),
            "status": "UNUSED",
            "device_fingerprint": None,
            "bound_device_id": None,  # 通用授权码不绑定设备
            "activation_time": None,
            "signature": self._sign_license_data(license_code)
        }

        # 保存到本地JSON
        self.storage.add_license(license_record)

        return license_code

    def generate_batch_licenses(self, count, license_type="PERMANENT", device_ids=None):
        """批量生成授权码"""
        licenses = []
        print(f"开始生成 {count} 个授权码...")

        if device_ids and len(device_ids) != count:
            print(f"警告：设备ID数量({len(device_ids)})与授权码数量({count})不匹配")
            device_ids = None

        for i in range(count):
            device_id = device_ids[i] if device_ids else None
            license_code = self.generate_license(license_type, device_id)
            licenses.append(license_code)

            # 显示进度
            progress = (i + 1) / count * 100
            bind_info = f" (绑定: {device_id[:8]}...)" if device_id else " (通用)"
            print(f"进度: [{i + 1:4d}/{count}] {progress:5.1f}% - {license_code}{bind_info}")

        # 导出到文本文件
        timestamp = int(time.time())
        output_file = os.path.join(self.data_dir, f'licenses_{timestamp}.txt')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# Kronos 授权码列表\n")
            f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# 总数量: {count}\n")
            f.write(f"# 授权类型: {license_type}\n")
            f.write(f"# 绑定模式: {'设备绑定' if device_ids else '通用授权'}\n")
            f.write("#" + "=" * 50 + "\n\n")

            for i, license_code in enumerate(licenses):
                device_id = device_ids[i] if device_ids else None
                if device_id:
                    f.write(f"{license_code} # 绑定设备: {device_id}\n")
                else:
                    f.write(f"{license_code}\n")

        print(f"\n✓ 成功生成 {count} 个授权码")
        print(f"✓ 已保存到数据库")
        print(f"✓ 已导出授权码文件")

        return licenses

    def _sign_license_data(self, license_code):
        """对授权码进行数字签名"""
        signature = self.private_key.sign(
            license_code.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()

    def verify_license_signature(self, license_code, signature):
        """验证授权码签名（测试用）"""
        try:
            public_key = self.private_key.public_key()
            signature_bytes = base64.b64decode(signature)
            public_key.verify(
                signature_bytes,
                license_code.encode(),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception:
            return False

    def get_statistics(self):
        """获取统计信息"""
        return self.storage.get_license_statistics()

    def generate_device_bound_license_for_device(self, device_id, license_type="PERMANENT"):
        """为指定设备ID生成绑定授权码"""
        print(f"为设备 {device_id} 生成绑定授权码...")
        license_code = self._generate_device_bound_license(device_id, license_type)
        print(f"✓ 生成成功: {license_code}")
        return license_code

    def verify_device_bound_license(self, license_code, device_id):
        """验证设备绑定授权码"""
        # 检查授权码格式（设备绑定授权码的第一段应该以D结尾）
        parts = license_code.split('-')
        if len(parts) != 5 or not parts[1].endswith('D'):
            return False, "非设备绑定授权码格式"

        try:
            # 从数据库获取授权码记录
            license_record = self.storage.find_license(license_code)
            if not license_record:
                return False, "授权码不存在"

            bound_device_id = license_record.get('bound_device_id')
            if not bound_device_id:
                return False, "授权码未绑定设备"

            if bound_device_id != device_id:
                return False, f"授权码绑定的设备ID({bound_device_id})与当前设备({device_id})不匹配"

            # 验证授权码的有效性（重新生成验证）
            expected_license = self._generate_device_bound_license(device_id, license_record['license_type'])
            if expected_license != license_code:
                return False, "授权码验证失败，可能被篡改"

            return True, "设备绑定授权码验证通过"

        except Exception as e:
            return False, f"验证过程异常: {str(e)}"

    def export_public_key(self, output_path=None):
        """导出公钥到指定位置"""
        if not output_path:
            output_path = os.path.join(self.data_dir, 'public.pem')

        public_key = self.private_key.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        with open(output_path, 'wb') as f:
            f.write(public_key_pem)

        print(f"公钥已导出到: {output_path}")
        return output_path


def main():
    """主程序入口"""
    print("=" * 60)
    print("           Kronos 授权码生成器")
    print("=" * 60)

    # 确保数据目录存在
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    generator = LicenseGenerator(data_dir)

    while True:
        print("\n请选择操作:")
        print("1. 生成授权码")
        print("2. 查看统计信息")
        print("3. 导出公钥")
        print("4. 退出")

        choice = input("\n请输入选项 (1-4): ").strip()

        if choice == '1':
            try:
                count = int(input("请输入要生成的授权码数量: "))
                if count <= 0:
                    print("数量必须大于0")
                    continue
                if count > 10000:
                    confirm = input(f"您要生成 {count} 个授权码，这可能需要一些时间。是否继续？(y/n): ")
                    if confirm.lower() != 'y':
                        continue

                # 选择授权码类型
                print("\n请选择授权码类型:")
                print("1. 通用授权码 (可在任意设备激活)")
                print("2. 设备绑定授权码 (绑定特定设备)")

                license_choice = input("请输入选项 (1-2): ").strip()

                device_ids = None
                if license_choice == '2':
                    # 设备绑定授权码
                    if count == 1:
                        device_id = input("请输入设备ID: ").strip()
                        if not device_id:
                            print("设备ID不能为空")
                            continue
                        device_ids = [device_id]
                    else:
                        print(f"\n需要为 {count} 个授权码输入设备ID:")
                        device_ids = []
                        for i in range(count):
                            device_id = input(f"第 {i + 1} 个授权码的设备ID: ").strip()
                            if not device_id:
                                print("设备ID不能为空，操作已取消")
                                device_ids = None
                                break
                            device_ids.append(device_id)

                        if device_ids is None:
                            continue
                elif license_choice != '1':
                    print("无效选项，默认生成通用授权码")

                licenses = generator.generate_batch_licenses(count, device_ids=device_ids)

            except ValueError:
                print("请输入有效的数字")
            except KeyboardInterrupt:
                print("\n操作已取消")

        elif choice == '2':
            stats = generator.get_statistics()
            print(f"\n📊 授权码统计信息:")
            print(f"   总授权码数: {stats['total_licenses']}")
            print(f"   未使用: {stats['unused_licenses']}")
            print(f"   已激活: {stats['activated_licenses']}")
            print(f"   使用率: {stats['license_usage_rate']}")
            print(f"   激活总数: {stats['total_activations']}")
            print(f"   当前活跃: {stats['active_activations']}")

        elif choice == '3':
            output_path = input("请输入公钥输出路径（按回车使用默认路径）: ").strip()
            if not output_path:
                output_path = None
            generator.export_public_key(output_path)

        elif choice == '4':
            print("再见!")
            break

        else:
            print("无效选项，请重新选择")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程序已退出")
    except Exception as e:
        print(f"程序异常: {e}")
        import traceback

        traceback.print_exc()
