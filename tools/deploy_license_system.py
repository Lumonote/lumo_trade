#!/usr/bin/env python3
"""
Lumo 授权系统部署脚本
准备客户端分发包，移除敏感信息
"""

import os
import shutil


def create_client_package():
    """创建客户端分发包"""
    print("=" * 60)
    print("        Lumo 客户端分发包创建工具")
    print("=" * 60)

    # 客户端需要的文件
    client_files = {
        'finetune/license_system/device_fingerprint.py': '设备指纹识别模块',
        'finetune/license_system/license_validator.py': '授权验证器',
        'finetune/license_system/json_storage.py': 'JSON存储工具',
        'finetune/license_system/activate.py': '激活工具',
        'finetune/license_system/config.json': '客户端配置',
        'finetune/license_system/keys/public.pem': '公钥文件',
        'quick_start.sh': '启动脚本（已包含授权检查）',
        'quick_start.bat': 'Windows启动脚本',
        'tools/launchers/lumo_with_license.py': '集成示例'
    }

    print("📋 客户端分发清单:")
    for file_path, description in client_files.items():
        if os.path.exists(file_path):
            print(f"  ✅ {file_path:<50} - {description}")
        else:
            print(f"  ❌ {file_path:<50} - {description} (缺失)")

    # 不能分发的文件（管理端专用）
    admin_only_files = {
        'license_admin/': '整个管理端目录',
        'license_admin/license_generator.py': '授权码生成器',
        'license_admin/keys/private.pem': 'RSA私钥',
        'license_admin/data/licenses.json': '完整授权码数据库',
        'test_license_system.py': '测试脚本'
    }

    print("\n🚫 禁止分发文件（必须保留在管理端）:")
    for file_path, description in admin_only_files.items():
        if os.path.exists(file_path):
            print(f"  ⚠️  {file_path:<50} - {description}")
        else:
            print(f"  ✅ {file_path:<50} - {description} (不存在)")

    print("\n" + "=" * 60)
    print("📦 部署指南:")
    print("=" * 60)
    print("1. 管理端（开发者保留）:")
    print("   - license_admin/ 整个目录")
    print("   - 包含私钥和完整授权码数据库")
    print("")
    print("2. 客户端（可以分发）:")
    print("   - finetune/license_system/ 客户端授权系统")
    print("   - quick_start.sh 已集成授权检查")
    print("   - 仅包含公钥，无私钥和授权码数据库")
    print("")
    print("3. 安全提醒:")
    print("   - 绝不分发 license_admin 目录")
    print("   - 私钥文件必须严格保密")
    print("   - 定期备份授权码数据库")


def check_security_status():
    """检查安全状态"""
    print("\n" + "=" * 60)
    print("🔒 安全状态检查:")
    print("=" * 60)

    security_checks = [
        ("私钥文件权限", lambda: oct(os.stat('license_admin/keys/private.pem').st_mode)[-3:] == '600'),
        ("公钥文件存在", lambda: os.path.exists('finetune/license_system/keys/public.pem')),
        ("客户端无私钥", lambda: not os.path.exists('finetune/license_system/keys/private.pem')),
        ("管理端目录完整",
         lambda: all(os.path.exists(f'license_admin/{f}') for f in ['license_generator.py', 'keys/', 'data/'])),
    ]

    for check_name, check_func in security_checks:
        try:
            if check_func():
                print(f"  ✅ {check_name}")
            else:
                print(f"  ❌ {check_name}")
        except Exception as e:
            print(f"  ⚠️  {check_name} - 检查失败")


def main():
    create_client_package()
    check_security_status()

    print(f"\n💡 使用建议:")
    print(f"1. 使用 python license_admin/license_generator.py 生成授权码")
    print(f"2. 将授权码提供给用户")
    print(f"3. 用户使用 ./quick_start.sh 选择授权激活")
    print(f"4. 客户端打包时删除 license_admin 目录")


if __name__ == "__main__":
    main()
