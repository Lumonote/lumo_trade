#!/usr/bin/env python3
"""
验证旧算法生成的授权码是否能通过客户端验证
"""

import hashlib


def verify_old_algorithm(license_code, device_id):
    """模拟客户端的验证逻辑（旧算法）"""
    try:
        # 移除 KRONOS- 前缀和连字符
        code_parts = license_code.replace('KRONOS-', '').replace('-', '')

        # 使用设备ID作为盐值生成校验码
        combined = f"{device_id}:KRONOS:2025"
        expected_hash = hashlib.sha256(combined.encode()).hexdigest()[:20].upper()

        # 比较授权码（取前20位）与期望的哈希值
        return code_parts == expected_hash
    except Exception as e:
        print(f"验证异常: {e}")
        return False


def main():
    print("=" * 80)
    print("旧算法授权码验证测试")
    print("=" * 80)

    device_id = "764AABC95A0DFD52"
    old_license = "KRONOS-C268E-32A5E-1FE5B-6A4A9"  # 使用旧算法生成的授权码
    new_license = "KRONOS-4F49D-8F358-7B2D8-022C4"  # 使用新算法生成的授权码

    print(f"\n设备ID: {device_id}")
    print(f"\n测试1: 旧算法生成的授权码")
    print(f"  授权码: {old_license}")
    result1 = verify_old_algorithm(old_license, device_id)
    print(f"  验证结果: {'✅ 通过' if result1 else '❌ 失败'}")

    print(f"\n测试2: 新算法生成的授权码")
    print(f"  授权码: {new_license}")
    result2 = verify_old_algorithm(new_license, device_id)
    print(f"  验证结果: {'✅ 通过' if result2 else '❌ 失败'}")

    print("\n" + "=" * 80)
    print("结论:")
    print("=" * 80)
    if result1:
        print(f"✅ 正确的授权码（请使用这个）: {old_license}")
    if result2:
        print(f"⚠️  新算法授权码也通过了验证（意外）")
    elif not result2:
        print(f"❌ 新算法授权码无法通过验证: {new_license}")

    print("\n💡 使用方法:")
    print(f"   在打包后的客户端程序中输入: {old_license}")


if __name__ == "__main__":
    main()
