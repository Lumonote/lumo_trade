#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kronos 授权码生成工具
管理员使用此工具为用户生成授权码
"""

import hashlib
import sys


def generate_license_code(device_id):
    """根据设备ID生成授权码"""
    # 使用设备ID和盐值生成授权码
    combined = f"{device_id}:KRONOS:2025"
    code_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()

    # 格式化为 KRONOS-XXXXX-XXXXX-XXXXX-XXXXX
    parts = [code_hash[i:i + 5] for i in range(0, 20, 5)]
    return f"KRONOS-{'-'.join(parts)}"


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
    print("-" * 60)
    print()
    print("提示:")
    print("1. 请将授权码发送给用户")
    print("2. 用户在应用中输入此授权码即可激活")
    print("3. 此授权码仅对该设备ID有效")
    print()


if __name__ == "__main__":
    main()
