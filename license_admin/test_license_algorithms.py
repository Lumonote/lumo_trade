#!/usr/bin/env python3
"""
授权码算法对比测试脚本
用于诊断生成器和验证器之间的算法差异
"""

import hashlib
import sys
import os

# 添加路径以导入license_generator
sys.path.insert(0, os.path.dirname(__file__))


def old_algorithm(device_id):
    """旧版generate_license.py的算法"""
    combined = f"{device_id}:KRONOS:2025"
    code_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()
    parts = [code_hash[i:i + 5] for i in range(0, 20, 5)]
    return f"KRONOS-{'-'.join(parts)}"


def new_algorithm(device_id, license_type="PERMANENT"):
    """新版license_generator.py的算法"""
    salt = "KRONOS_DEVICE_SALT_2024"
    combined_data = f"{device_id}{salt}{license_type}"

    # 生成基于设备ID的哈希
    device_hash = hashlib.sha256(combined_data.encode()).hexdigest()

    # 从哈希中提取段落
    segment1 = device_hash[:4].upper() + "D"
    segment2 = device_hash[4:9].upper()
    segment3 = device_hash[9:14].upper()

    # 计算校验码
    raw_data = f"{segment1}{segment2}{segment3}"
    checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

    # 生成最终授权码
    return f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"


def main():
    print("=" * 80)
    print("授权码算法对比测试")
    print("=" * 80)

    # 测试设备ID
    test_device_id = "764AABC95A0DFD52"

    print(f"\n测试设备ID: {test_device_id}")
    print("-" * 80)

    # 旧算法
    old_license = old_algorithm(test_device_id)
    print(f"\n旧算法 (generate_license.py):")
    print(f"  输入: {test_device_id}:KRONOS:2025")
    print(f"  授权码: {old_license}")

    # 新算法
    new_license = new_algorithm(test_device_id)
    print(f"\n新算法 (license_generator.py):")
    print(f"  输入: {test_device_id}KRONOS_DEVICE_SALT_2024PERMANENT")
    print(f"  授权码: {new_license}")

    # 对比
    print("\n" + "=" * 80)
    print("对比结果:")
    print("=" * 80)
    print(f"算法是否一致: {'❌ 不一致' if old_license != new_license else '✅ 一致'}")

    if old_license != new_license:
        print(f"\n⚠️  问题诊断:")
        print(f"  - 旧算法生成: {old_license}")
        print(f"  - 新算法生成: {new_license}")
        print(f"  - 客户端验证器使用: 新算法")
        print(f"\n  结论: 如果使用旧算法生成授权码，客户端验证将失败！")

    # 用户实际生成的授权码
    actual_generated = "KRONOS-4F49D-8F358-7B2D8-022C4"
    print(f"\n实际生成的授权码: {actual_generated}")
    print(f"与旧算法匹配: {'✅ 是' if actual_generated == old_license else '❌ 否'}")
    print(f"与新算法匹配: {'✅ 是' if actual_generated == new_license else '❌ 否'}")

    # 详细分析实际生成的授权码
    print("\n" + "=" * 80)
    print("实际授权码分析:")
    print("=" * 80)

    parts = actual_generated.split('-')
    if len(parts) == 5:
        print(f"格式: {parts[0]}-{parts[1]}-{parts[2]}-{parts[3]}-{parts[4]}")
        print(f"第1段 (segment1): {parts[1]}")
        print(f"  - 是否以'D'结尾: {'✅ 是 (设备绑定)' if parts[1].endswith('D') else '❌ 否'}")
        print(f"  - 是否以'U'结尾: {'✅ 是 (通用授权)' if parts[1].endswith('U') else '❌ 否'}")
        print(f"第2段 (segment2): {parts[2]}")
        print(f"第3段 (segment3): {parts[3]}")
        print(f"校验码 (checksum): {parts[4]}")

        # 验证校验码
        raw_data = f"{parts[1]}{parts[2]}{parts[3]}"
        expected_checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()
        print(f"\n校验码验证:")
        print(f"  - 实际校验码: {parts[4]}")
        print(f"  - 期望校验码: {expected_checksum}")
        print(f"  - 校验结果: {'✅ 通过' if parts[4] == expected_checksum else '❌ 失败'}")

    print("\n" + "=" * 80)
    print("推荐解决方案:")
    print("=" * 80)
    print("1. 使用正确的生成工具: license_admin/license_generator.py")
    print("2. 或者更新客户端验证器以支持旧算法")
    print("3. 删除或归档旧版generate_license.py以避免混淆")
    print("=" * 80)


if __name__ == "__main__":
    main()
