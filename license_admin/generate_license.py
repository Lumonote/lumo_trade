#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kronos 授权码生成工具
管理员使用此工具为用户生成授权码
"""

import hashlib
import sys


def generate_license_code(device_id, license_type="PERMANENT"):
    """根据设备ID生成授权码（设备绑定）

    Args:
        device_id: 16位设备ID
        license_type: 授权类型 (PERMANENT, TRIAL, etc.)

    Returns:
        格式: LUMO-XXXXD-XXXXX-XXXXX-XXXXX (D表示设备绑定)
    """
    # 使用与验证器相同的盐值和算法
    salt = "KRONOS_DEVICE_SALT_2024"
    combined_data = f"{device_id}{salt}{license_type}"

    # 生成SHA256哈希
    device_hash = hashlib.sha256(combined_data.encode()).hexdigest()

    # 从哈希中提取段落
    segment1 = device_hash[:4].upper() + "D"  # D表示设备绑定 (Device-bound)
    segment2 = device_hash[4:9].upper()
    segment3 = device_hash[9:14].upper()

    # 计算校验码（MD5哈希的前5位）
    raw_data = f"{segment1}{segment2}{segment3}"
    checksum = hashlib.md5(raw_data.encode()).hexdigest()[:5].upper()

    # 格式化为 LUMO-XXXXD-XXXXX-XXXXX-XXXXX (校验码只覆盖中间三段, 前缀纯展示)
    return f"LUMO-{segment1}-{segment2}-{segment3}-{checksum}"


def main():
    """主函数"""
    print("=" * 60)
    print("Kronos 授权码生成工具")
    print("=" * 60)
    print()

    if len(sys.argv) > 1:
        # 命令行参数模式
        device_id = sys.argv[1].strip().upper()
    else:
        # 交互模式
        print("请输入用户的设备ID (16位十六进制):")
        device_id = input("> ").strip().upper()

    # 验证设备ID格式
    if len(device_id) != 16:
        print(f"❌ 错误: 设备ID必须是16位十六进制字符，当前长度: {len(device_id)}")
        sys.exit(1)

    try:
        int(device_id, 16)  # 验证是否为有效的十六进制
    except ValueError:
        print("❌ 错误: 设备ID必须是有效的十六进制字符")
        sys.exit(1)

    # 生成授权码
    license_code = generate_license_code(device_id)

    print()
    print("-" * 60)
    print("✅ 授权码生成成功!")
    print("-" * 60)
    print(f"设备ID:   {device_id}")
    print(f"授权码:   {license_code}")
    print(f"授权类型: PERMANENT (永久授权)")
    print(f"绑定模式: DEVICE_BOUND (设备绑定)")
    print("-" * 60)
    print()
    print("提示:")
    print("1. 请将授权码发送给用户")
    print("2. 用户在应用中输入此授权码即可激活")
    print("3. 此授权码仅对该设备ID有效，不可转移到其他设备")
    print("4. 授权码以 'D' 结尾表示设备绑定模式")
    print()


if __name__ == "__main__":
    main()
