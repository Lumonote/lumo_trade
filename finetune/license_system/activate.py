#!/usr/bin/env python3
import sys
import os
from license_validator import LicenseValidator


def print_header():
    """打印程序头部信息"""
    print("=" * 60)
    print("           Kronos 金融预测系统授权管理")
    print("=" * 60)
    print("版本: 1.0")
    print("功能: 授权激活、状态检查、设备管理")
    print("=" * 60)


def print_menu():
    """打印菜单"""
    print("\n📋 请选择操作:")
    print("1. 🔍 检查授权状态")
    print("2. 🔑 激活授权码")
    print("3. 📊 显示授权信息")
    print("4. 🔧 显示设备指纹")
    print("5. ❌ 撤销当前授权")
    print("6. 🚪 退出程序")


def check_license_status(validator):
    """检查授权状态"""
    print("\n🔍 正在检查授权状态...")
    print("-" * 40)

    is_valid, message = validator.validate_license()

    if is_valid:
        print(f"✅ {message}")
        return True
    else:
        print(f"❌ {message}")
        return False


def activate_license(validator):
    """激活授权码"""
    print("\n🔑 授权码激活")
    print("-" * 40)
    print("授权码格式: KRONOS-XXXXX-XXXXX-XXXXX-XXXXX")
    print("示例: KRONOS-A1B21-C3D4E-F5G6H-7I8J9")

    while True:
        license_code = input("\n请输入授权码 (输入 'q' 退出): ").strip()

        if license_code.lower() == 'q':
            return False

        if not license_code:
            print("❌ 授权码不能为空，请重新输入")
            continue

        print(f"\n🔄 正在激活授权码: {license_code}")
        print("=" * 50)

        success, message = validator.activate_license(license_code)

        print("=" * 50)
        if success:
            print(f"✅ {message}")
            print("\n🎉 恭喜！Kronos系统已成功激活，您现在可以使用所有功能。")
            return True
        else:
            print(f"❌ 激活失败: {message}")

            retry = input("\n是否重试激活？(y/n): ").strip().lower()
            if retry != 'y':
                return False


def show_license_info(validator):
    """显示授权信息"""
    print("\n📊 授权信息详情")
    print("-" * 40)

    info = validator.get_license_info()
    if info:
        print(f"📄 授权码: {info['license_code']}")
        print(f"📅 激活时间: {info['activation_time'][:19].replace('T', ' ')}")
        print(f"💻 设备ID: {info['device_id']}")
        print(f"🖥️  系统: {info['system_info']['system']} {info['system_info']['release']}")
        print(f"🏷️  授权类型: {info['license_type']}")
        print(f"🏠 主机名: {info['system_info']['hostname']}")
    else:
        print("❌ 未找到授权信息，请先激活授权码")


def show_device_fingerprint(validator):
    """显示设备指纹"""
    print("\n🔧 设备硬件指纹")
    print("-" * 40)

    fingerprint = validator.check_device_fingerprint()


def revoke_license(validator):
    """撤销授权"""
    print("\n❌ 撤销授权")
    print("-" * 40)
    print("⚠️  警告: 撤销授权后将无法使用Kronos系统，需要重新激活！")

    # 显示当前授权信息
    info = validator.get_license_info()
    if info:
        print(f"\n当前授权码: {info['license_code']}")
        print(f"激活时间: {info['activation_time'][:19].replace('T', ' ')}")
    else:
        print("❌ 当前设备没有激活的授权")
        return

    # 确认操作
    print("\n请输入 'REVOKE' 确认撤销操作:")
    confirm = input("确认输入: ").strip()

    if confirm == 'REVOKE':
        if validator.revoke_license():
            print("✅ 授权已成功撤销")
        else:
            print("❌ 撤销授权失败")
    else:
        print("❌ 操作已取消")


def main():
    """主程序"""
    try:
        # 初始化验证器
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        validator = LicenseValidator(data_dir)

        print_header()

        # 首次检查授权状态
        is_licensed = check_license_status(validator)

        # 如果未授权，建议先激活
        if not is_licensed:
            print("\n💡 建议: 请先激活授权码以使用Kronos系统")

        # 主循环
        while True:
            print_menu()

            try:
                choice = input("\n请输入选项 (1-6): ").strip()

                if choice == '1':
                    check_license_status(validator)

                elif choice == '2':
                    if activate_license(validator):
                        print("\n💡 提示: 现在可以启动Kronos系统使用预测功能了")

                elif choice == '3':
                    show_license_info(validator)

                elif choice == '4':
                    show_device_fingerprint(validator)

                elif choice == '5':
                    revoke_license(validator)

                elif choice == '6':
                    print("\n👋 感谢使用Kronos授权管理系统，再见!")
                    break

                else:
                    print("❌ 无效选项，请输入 1-6 之间的数字")

                # 等待用户按键继续
                if choice in ['1', '2', '3', '4', '5']:
                    input("\n按回车键继续...")

            except KeyboardInterrupt:
                print("\n\n👋 程序已退出")
                break

    except Exception as e:
        print(f"\n❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车键退出...")


if __name__ == "__main__":
    main()
