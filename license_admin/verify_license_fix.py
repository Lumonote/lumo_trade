#!/usr/bin/env python3
"""
授权码生成与验证完整测试
使用正确的设备ID生成授权码并验证
"""

import sys
import os
import hashlib

# 添加路径
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'finetune', 'license_system'))

from license_generator import LicenseGenerator


def generate_license_for_device(device_id):
    """为指定设备生成授权码"""
    print("=" * 80)
    print("生成设备绑定授权码")
    print("=" * 80)

    # 模拟生成过程（与license_generator.py一致）
    salt = "KRONOS_DEVICE_SALT_2024"
    license_type = "PERMANENT"
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
    license_code = f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"

    print(f"设备ID: {device_id}")
    print(f"授权类型: {license_type}")
    print(f"生成的授权码: {license_code}")
    print(f"\n授权码格式验证:")
    print(f"  - 第1段 (segment1): {segment1} - {'✅ 设备绑定' if segment1.endswith('D') else '❌'}")
    print(f"  - 第2段 (segment2): {segment2}")
    print(f"  - 第3段 (segment3): {segment3}")
    print(f"  - 校验码: {checksum}")

    return license_code


def verify_license_locally(license_code, device_id):
    """本地验证授权码（模拟客户端验证）"""
    print("\n" + "=" * 80)
    print("本地验证授权码（模拟客户端）")
    print("=" * 80)

    # 使用与客户端相同的验证逻辑
    salt = "KRONOS_DEVICE_SALT_2024"
    combined_data = f"{device_id}{salt}PERMANENT"

    # 生成基于设备ID的哈希
    device_hash = hashlib.sha256(combined_data.encode()).hexdigest()

    # 从哈希中提取段落
    segment1 = device_hash[:4].upper() + "D"
    segment2 = device_hash[4:9].upper()
    segment3 = device_hash[9:14].upper()

    # 计算校验码
    raw_data = f"{segment1}{segment2}{segment3}"
    checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

    # 生成期望的授权码
    expected_license_code = f"KRONOS-{segment1}-{segment2}-{segment3}-{checksum}"

    print(f"验证设备ID: {device_id}")
    print(f"输入授权码: {license_code}")
    print(f"期望授权码: {expected_license_code}")
    print(f"\n验证结果: {'✅ 通过' if license_code == expected_license_code else '❌ 失败'}")

    if license_code != expected_license_code:
        print(f"\n差异分析:")
        parts_input = license_code.split('-')
        parts_expected = expected_license_code.split('-')
        for i, (inp, exp) in enumerate(zip(parts_input, parts_expected)):
            match = '✅' if inp == exp else '❌'
            print(f"  段{i + 1}: {inp} vs {exp} {match}")

    return license_code == expected_license_code


def main():
    print("=" * 80)
    print("Kronos 授权码修复工具")
    print("=" * 80)

    # 错误的设备ID（用户之前输入的）
    wrong_device_id = "764AABC95A0DFD52"

    # 正确的设备ID（从device_fingerprint.py获取）
    correct_device_id = "C0AD81088CBB5656"

    print("\n🔍 问题诊断:")
    print(f"  错误设备ID: {wrong_device_id}")
    print(f"  正确设备ID: {correct_device_id}")
    print(f"  设备ID是否匹配: {'✅' if wrong_device_id == correct_device_id else '❌ 不匹配 - 这就是验证失败的原因！'}")

    # 使用错误的设备ID生成的授权码
    print("\n" + "=" * 80)
    print("【错误示例】使用错误设备ID生成的授权码:")
    print("=" * 80)
    wrong_license = generate_license_for_device(wrong_device_id)
    verify_license_locally(wrong_license, correct_device_id)

    # 使用正确的设备ID生成授权码
    print("\n" + "=" * 80)
    print("【正确方案】使用正确设备ID生成的授权码:")
    print("=" * 80)
    correct_license = generate_license_for_device(correct_device_id)
    verify_license_locally(correct_license, correct_device_id)

    # 总结
    print("\n" + "=" * 80)
    print("总结与建议")
    print("=" * 80)
    print(f"\n✅ 正确的授权码（请使用这个）:")
    print(f"   {correct_license}")
    print(f"\n❌ 错误的授权码（不要使用）:")
    print(f"   {wrong_license}")
    print(f"\n💡 使用方法:")
    print(f"   1. 在客户端激活程序中输入: {correct_license}")
    print(f"   2. 系统会自动获取设备ID: {correct_device_id}")
    print(f"   3. 验证将会成功通过 ✅")


if __name__ == "__main__":
    main()
