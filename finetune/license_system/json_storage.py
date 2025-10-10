#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime


class JSONStorage:
    def __init__(self, base_dir="data"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _safe_read_json(self, filepath):
        """安全读取JSON文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except FileNotFoundError:
            return None
        except Exception as e:
            print(f"读取文件失败 {filepath}: {e}")
            return None

    def _safe_write_json(self, filepath, data):
        """安全写入JSON文件"""
        try:
            # 先写入临时文件，再重命名，确保原子性操作
            temp_filepath = filepath + '.tmp'
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # 原子性重命名
            if os.path.exists(filepath):
                backup_filepath = filepath + '.backup'
                os.rename(filepath, backup_filepath)

            os.rename(temp_filepath, filepath)

            # 删除备份文件
            backup_filepath = filepath + '.backup'
            if os.path.exists(backup_filepath):
                os.remove(backup_filepath)

            return True
        except Exception as e:
            print(f"写入文件失败 {filepath}: {e}")
            # 清理临时文件
            temp_filepath = filepath + '.tmp'
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return False

    def load_licenses(self):
        """加载授权码数据"""
        filepath = os.path.join(self.base_dir, 'licenses.json')
        data = self._safe_read_json(filepath)

        if not data:
            # 创建初始结构
            data = {
                "metadata": {
                    "created_time": datetime.now().isoformat(),
                    "version": "1.0",
                    "total_licenses": 0
                },
                "licenses": []
            }
            self._safe_write_json(filepath, data)

        return data

    def save_licenses(self, data):
        """保存授权码数据"""
        filepath = os.path.join(self.base_dir, 'licenses.json')
        data["metadata"]["total_licenses"] = len(data["licenses"])
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        return self._safe_write_json(filepath, data)

    def find_license(self, license_code):
        """查找特定授权码"""
        data = self.load_licenses()
        for license_record in data["licenses"]:
            if license_record["license_code"] == license_code:
                return license_record
        return None

    def add_license(self, license_record):
        """添加新的授权码记录"""
        data = self.load_licenses()
        data["licenses"].append(license_record)
        return self.save_licenses(data)

    def update_license_status(self, license_code, status, device_fingerprint=None):
        """更新授权码状态"""
        data = self.load_licenses()

        for license_record in data["licenses"]:
            if license_record["license_code"] == license_code:
                license_record["status"] = status
                if device_fingerprint:
                    license_record["device_fingerprint"] = device_fingerprint
                    license_record["activation_time"] = datetime.now().isoformat()
                license_record["last_updated"] = datetime.now().isoformat()
                break

        return self.save_licenses(data)

    def load_activations(self):
        """加载激活记录"""
        filepath = os.path.join(self.base_dir, 'activations.json')
        data = self._safe_read_json(filepath)

        if not data:
            data = {
                "metadata": {
                    "created_time": datetime.now().isoformat(),
                    "version": "1.0",
                    "total_activations": 0
                },
                "activations": []
            }
            self._safe_write_json(filepath, data)

        return data

    def save_activations(self, data):
        """保存激活记录"""
        filepath = os.path.join(self.base_dir, 'activations.json')
        data["metadata"]["total_activations"] = len(data["activations"])
        data["metadata"]["last_updated"] = datetime.now().isoformat()
        return self._safe_write_json(filepath, data)

    def add_activation_record(self, license_code, device_fingerprint, device_info, activation_ip="unknown"):
        """添加激活记录"""
        data = self.load_activations()

        activation_record = {
            "license_code": license_code,
            "device_fingerprint": device_fingerprint,
            "device_info": device_info,
            "activation_time": datetime.now().isoformat(),
            "activation_ip": activation_ip,
            "status": "ACTIVE"
        }

        data["activations"].append(activation_record)
        return self.save_activations(data)

    def find_activation(self, device_fingerprint):
        """根据设备指纹查找激活记录"""
        data = self.load_activations()
        for record in data["activations"]:
            if record["device_fingerprint"] == device_fingerprint and record["status"] == "ACTIVE":
                return record
        return None

    def find_activation_by_license(self, license_code):
        """根据授权码查找激活记录"""
        data = self.load_activations()
        for record in data["activations"]:
            if record["license_code"] == license_code and record["status"] == "ACTIVE":
                return record
        return None

    def revoke_activation(self, device_fingerprint):
        """撤销激活记录"""
        data = self.load_activations()

        for record in data["activations"]:
            if record["device_fingerprint"] == device_fingerprint:
                record["status"] = "REVOKED"
                record["revoked_time"] = datetime.now().isoformat()
                break

        return self.save_activations(data)

    def get_license_statistics(self):
        """获取授权码统计信息"""
        license_data = self.load_licenses()
        activation_data = self.load_activations()

        total_licenses = len(license_data["licenses"])
        unused_count = len([l for l in license_data["licenses"] if l["status"] == "UNUSED"])
        activated_count = len([l for l in license_data["licenses"] if l["status"] == "ACTIVATED"])
        total_activations = len(activation_data["activations"])
        active_activations = len([a for a in activation_data["activations"] if a["status"] == "ACTIVE"])

        return {
            "total_licenses": total_licenses,
            "unused_licenses": unused_count,
            "activated_licenses": activated_count,
            "total_activations": total_activations,
            "active_activations": active_activations,
            "license_usage_rate": f"{(activated_count / total_licenses * 100):.1f}%" if total_licenses > 0 else "0%"
        }

    def cleanup_old_records(self, days=365):
        """清理旧记录（可选功能）"""
        from datetime import datetime, timedelta

        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_iso = cutoff_date.isoformat()

        # 清理旧的激活记录
        activation_data = self.load_activations()
        original_count = len(activation_data["activations"])

        activation_data["activations"] = [
            record for record in activation_data["activations"]
            if record.get("activation_time", cutoff_iso) > cutoff_iso or record["status"] == "ACTIVE"
        ]

        cleaned_count = original_count - len(activation_data["activations"])

        if cleaned_count > 0:
            self.save_activations(activation_data)
            print(f"清理了 {cleaned_count} 条旧激活记录")

        return cleaned_count


# 测试工具
if __name__ == "__main__":
    storage = JSONStorage()

    print("=" * 50)
    print("        JSON存储测试")
    print("=" * 50)

    # 测试加载数据
    licenses = storage.load_licenses()
    activations = storage.load_activations()

    print(f"授权码数据加载成功: {len(licenses['licenses'])} 条记录")
    print(f"激活记录加载成功: {len(activations['activations'])} 条记录")

    # 显示统计信息
    stats = storage.get_license_statistics()
    print("\n统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
