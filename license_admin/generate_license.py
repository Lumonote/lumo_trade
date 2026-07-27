#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kronos 授权码生成工具
管理员使用此工具为用户生成授权码
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from finetune.license_system.license_codec import generate_device_license


def generate_license_code(device_id, license_type="PERMANENT"):
    """根据设备ID生成授权码（设备绑定）

    Args:
        device_id: 16位设备ID
        license_type: 授权类型 (PERMANENT, TRIAL, etc.)

    Returns:
        格式: LUMO-XXXXD-XXXXX-XXXXX-XXXXX (D表示设备绑定)
    """
    return generate_device_license(device_id, license_type)


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
