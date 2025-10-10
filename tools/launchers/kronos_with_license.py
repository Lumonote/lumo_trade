#!/usr/local/bin/python3.11
"""
Kronos 简化GUI主程序
直接调用现有的授权系统，无需额外依赖
"""

import os
import sys
import subprocess
import platform
import json
import hashlib

# 添加项目路径到Python路径  
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


def get_device_id():
    """获取设备ID"""
    try:
        from finetune.license_system.device_fingerprint import DeviceFingerprint
        fingerprint = DeviceFingerprint()
        result = fingerprint.get_device_fingerprint()
        return result['device_id']
    except ImportError:
        # 简化版本
        info = f"{platform.system()}-{platform.node()}-{platform.processor()}"
        return hashlib.sha256(info.encode()).hexdigest()[:16].upper()
    except Exception:
        # 备用方案
        info = f"{platform.system()}-{platform.node()}-{platform.processor()}"
        return hashlib.sha256(info.encode()).hexdigest()[:16].upper()


def check_license_status():
    """检查授权状态"""
    try:
        from finetune.license_system.license_validator import LicenseValidator
        data_dir = os.path.join(project_root, 'finetune', 'license_system', 'data')
        validator = LicenseValidator(data_dir)
        return validator.validate_license()
    except ImportError:
        # 简化检查
        license_file = os.path.expanduser("~/.kronos_license")
        if os.path.exists(license_file):
            return True, "授权已激活"
        return False, "需要激活授权"
    except Exception:
        return False, "授权验证异常"


def activate_license_interactive():
    """交互式授权激活"""
    print("\n🔐 Kronos 授权激活")
    print("=" * 30)

    device_id = get_device_id()
    print(f"📱 设备ID: {device_id}")

    while True:
        license_code = input("\n请输入授权码 (或输入 'q' 退出): ").strip().upper()

        if license_code.lower() == 'q':
            return False

        if not license_code.startswith("KRONOS-"):
            print("❌ 授权码格式错误，应以 'KRONOS-' 开头")
            continue

        try:
            # 尝试使用完整的授权系统
            from finetune.license_system.license_validator import LicenseValidator
            data_dir = os.path.join(project_root, 'finetune', 'license_system', 'data')
            validator = LicenseValidator(data_dir)
            success, message = validator.activate_license(license_code)
        except ImportError:
            # 简化版本激活
            if len(license_code) >= 10:  # 基本长度检查
                license_file = os.path.expanduser("~/.kronos_license")
                with open(license_file, 'w') as f:
                    json.dump({
                        'device_id': device_id,
                        'license_code': license_code,
                        'system': platform.system()
                    }, f)
                success, message = True, "授权激活成功"
            else:
                success, message = False, "无效的授权码"
        except Exception as e:
            success, message = False, f"激活失败: {e}"

        if success:
            print(f"✅ {message}")
            return True
        else:
            print(f"❌ {message}")


def show_main_menu():
    """显示主菜单"""
    is_licensed, status_message = check_license_status()
    device_id = get_device_id()

    print("\n🚀 Kronos 金融预测系统")
    print("=" * 40)
    print(f"📱 设备ID: {device_id}")
    print(f"🖥️  系统: {platform.system()} {platform.release()}")
    print(f"🔐 授权状态: {status_message}")
    print("=" * 40)

    if is_licensed:
        print("\n✅ 系统已授权，可使用所有功能")
        print("\n📋 可用功能:")
        print("1. 股票预测分析")
        print("2. 技术指标计算")
        print("3. 数据获取和管理")
        print("4. 量化策略回测")
        print("5. 系统设置")
        print("6. 授权管理")
        print("0. 退出程序")

        choice = input("\n请选择功能 (0-6): ").strip()
        return handle_licensed_menu(choice)
    else:
        print("\n🔑 系统需要激活授权")
        print("\n📋 选项:")
        print("1. 激活授权码")
        print("2. 查看系统信息")
        print("0. 退出程序")

        choice = input("\n请选择操作 (0-2): ").strip()
        return handle_unlicensed_menu(choice)


def handle_licensed_menu(choice):
    """处理已授权用户的菜单选择"""
    if choice == '1':
        print("\n📈 启动股票预测分析...")
        try:
            subprocess.run([sys.executable, os.path.join(project_root, "examples/prediction_example.py")], check=True)
        except FileNotFoundError:
            print("⚠️  预测模块未找到，功能开发中...")
        except Exception as e:
            print(f"❌ 预测功能出错: {e}")

    elif choice == '2':
        print("\n📊 启动技术分析功能...")
        print("💡 功能包括: RSI, MACD, 布林带, KDJ等技术指标")
        print("🚧 完整功能开发中...")

    elif choice == '3':
        print("\n📋 数据管理功能...")
        try:
            subprocess.run([sys.executable, os.path.join(project_root, "scripts/fetch_data.py"), "--help"], check=True)
        except Exception:
            print(f"💡 数据获取脚本: {os.path.join(project_root, 'scripts/fetch_data.py')}")
            print(f"💡 批量获取脚本: {os.path.join(project_root, 'scripts/batch_fetch_enhanced.py')}")

    elif choice == '4':
        print("\n🔄 量化策略回测...")
        print("💡 支持多种量化模型和策略验证")
        print("🚧 完整功能开发中...")

    elif choice == '5':
        print("\n⚙️  系统设置...")
        print("💡 配置文件位置: config/")
        print("💡 模型设置和参数调整")

    elif choice == '6':
        print("\n🔐 授权管理...")
        run_license_manager()

    elif choice == '0':
        return False
    else:
        print("❌ 无效选择")

    input("\n按回车键继续...")
    return True


def handle_unlicensed_menu(choice):
    """处理未授权用户的菜单选择"""
    if choice == '1':
        if activate_license_interactive():
            print("\n🎉 授权激活成功！重新启动以使用完整功能。")

    elif choice == '2':
        print("\n📋 系统信息:")
        print(f"  设备ID: {get_device_id()}")
        print(f"  操作系统: {platform.system()} {platform.release()}")
        print(f"  Python版本: {sys.version.split()[0]}")
        print(f"  程序版本: Kronos v1.0")

    elif choice == '0':
        return False
    else:
        print("❌ 无效选择")

    input("\n按回车键继续...")
    return True


def run_license_manager():
    """运行授权管理器"""
    try:
        # 调用完整的授权激活工具
        activate_script = os.path.join(project_root, "finetune/license_system/activate.py")
        if os.path.exists(activate_script):
            subprocess.run([sys.executable, activate_script], check=True)
        else:
            print("⚠️  完整授权管理器未找到，使用简化版本")
            activate_license_interactive()
    except Exception as e:
        print(f"❌ 授权管理器启动失败: {e}")
        activate_license_interactive()


def main():
    """主程序入口"""
    print("🚀 正在启动 Kronos 金融预测系统...")

    # 检查Python版本
    if sys.version_info < (3, 6):
        print("❌ 需要Python 3.11或更高版本")
        sys.exit(1)

    try:
        while True:
            if not show_main_menu():
                break

    except KeyboardInterrupt:
        print("\n👋 程序被用户中断")
    except Exception as e:
        print(f"❌ 程序出错: {e}")
    finally:
        print("\n👋 感谢使用 Kronos 金融预测系统！")


if __name__ == "__main__":
    main()
