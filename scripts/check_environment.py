#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kronos 环境检测脚本
检查系统环境、Python依赖和配置文件
"""

import sys
import os
import json
import subprocess
import platform
from pathlib import Path
from typing import Dict, List, Tuple


# 颜色定义
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


# 检测是否为Windows系统
IS_WINDOWS = platform.system() == "Windows"


def print_colored(text: str, color: str = Colors.WHITE) -> None:
    """打印带颜色的文本"""
    if IS_WINDOWS:
        # Windows下不使用颜色，避免显示问题
        print(text)
    else:
        print(f"{color}{text}{Colors.END}")


def print_success(text: str) -> None:
    """打印成功信息"""
    if IS_WINDOWS:
        print_colored(f"[OK] {text}")
    else:
        print_colored(f"✅ {text}", Colors.GREEN)


def print_error(text: str) -> None:
    """打印错误信息"""
    if IS_WINDOWS:
        print_colored(f"[ERROR] {text}")
    else:
        print_colored(f"❌ {text}", Colors.RED)


def print_warning(text: str) -> None:
    """打印警告信息"""
    if IS_WINDOWS:
        print_colored(f"[WARNING] {text}")
    else:
        print_colored(f"⚠️  {text}", Colors.YELLOW)


def print_info(text: str) -> None:
    """打印信息"""
    if IS_WINDOWS:
        print_colored(f"[INFO] {text}")
    else:
        print_colored(f"ℹ️  {text}", Colors.CYAN)


def get_actual_python_path():
    """获取实际的Python解释器路径"""
    import shutil

    # 如果在应用包内，sys.executable可能指向应用本身，需要检测真实的Python
    python_names = ['python3.11', 'python3', 'python']

    for py_name in python_names:
        try:
            py_path = shutil.which(py_name)
            if py_path:
                # 验证这是一个有效的Python解释器
                result = subprocess.run([py_path, "--version"],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and "3." in result.stdout:
                    return py_path
        except:
            continue

    # 备选方案
    return sys.executable


def print_header(text: str) -> None:
    """打印标题"""
    if IS_WINDOWS:
        print(f"\n{text}\n")
    else:
        print_colored(f"\n{text}\n", Colors.BOLD + Colors.UNDERLINE + Colors.BLUE)


def check_python_version() -> Tuple[bool, str]:
    """检查Python版本"""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version.major >= 3 and version.minor >= 11:
        return True, version_str
    else:
        return False, version_str


def check_package_installed(package_name: str) -> Tuple[bool, str]:
    """检查Python包是否已安装"""
    try:
        # 使用实际的Python解释器路径
        python_path = get_actual_python_path()
        result = subprocess.run(
            [python_path, "-c", f"import {package_name}; print({package_name}.__version__)"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        else:
            return False, "未安装"
    except Exception as e:
        return False, f"检查失败: {str(e)}"


def check_required_packages() -> Dict[str, Tuple[bool, str]]:
    """检查必需的Python包"""
    required_packages = {
        'numpy': 'numpy',
        'pandas': 'pandas',
        'torch': 'torch',
        'matplotlib': 'matplotlib',
        'tqdm': 'tqdm',
        'safetensors': 'safetensors',
        'einops': 'einops',
        'huggingface_hub': 'huggingface_hub',
        'tushare': 'tushare'
    }

    results = {}
    for display_name, import_name in required_packages.items():
        results[display_name] = check_package_installed(import_name)

    return results


def check_optional_packages() -> Dict[str, Tuple[bool, str]]:
    """检查可选的Python包"""
    optional_packages = {
        'seaborn': 'seaborn',
        'plotly': 'plotly',
        'jupyter': 'jupyter'
    }

    results = {}
    for display_name, import_name in optional_packages.items():
        results[display_name] = check_package_installed(import_name)

    return results


def check_directories() -> Dict[str, bool]:
    """检查必需的目录结构"""
    required_dirs = ['data', 'logs', 'config', 'scripts', 'results']
    results = {}

    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        results[dir_name] = dir_path.exists() and dir_path.is_dir()

    return results


def create_missing_directories(missing_dirs: List[str]) -> List[str]:
    """尝试创建缺失的目录，返回仍未创建成功的目录列表"""
    still_missing = []
    for dir_name in missing_dirs:
        try:
            dir_path = Path(dir_name)
            dir_path.mkdir(parents=True, exist_ok=True)
            if dir_path.exists() and dir_path.is_dir():
                print_success(f"已创建目录 {dir_name}/")
            else:
                print_error(f"目录 {dir_name}/ 创建失败")
                still_missing.append(dir_name)
        except Exception as e:
            print_error(f"目录 {dir_name}/ 创建失败: {str(e)}")
            still_missing.append(dir_name)
    return still_missing


def check_config_files() -> Dict[str, Tuple[bool, str]]:
    """检查配置文件"""
    config_files = {
        'Tushare配置': 'config/tushare_config.json',
        '需求文件': 'requirements.txt'
    }

    results = {}
    for name, file_path in config_files.items():
        path = Path(file_path)
        if path.exists():
            try:
                if file_path.endswith('.json'):
                    with open(path, 'r', encoding='utf-8') as f:
                        json.load(f)
                    results[name] = (True, "有效")
                else:
                    results[name] = (True, "存在")
            except Exception as e:
                results[name] = (False, f"格式错误: {str(e)}")
        else:
            results[name] = (False, "不存在")

    return results


def check_tushare_config() -> Tuple[bool, str]:
    """检查Tushare配置"""
    config_path = Path('config/tushare_config.json')

    if not config_path.exists():
        return False, "配置文件不存在"

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        token = config.get('tushare', {}).get('token', '')
        if not token or token == "请在此处填入您的Tushare Token":
            return False, "Token未配置"

        if len(token) < 20:
            return False, "Token格式可能不正确"

        return True, "配置正确"

    except Exception as e:
        return False, f"配置文件错误: {str(e)}"


def check_gpu_availability() -> Tuple[bool, str]:
    """检查GPU可用性"""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            gpu_name = torch.cuda.get_device_name(0) if gpu_count > 0 else "未知"
            return True, f"{gpu_count}个GPU可用 ({gpu_name})"
        else:
            return False, "CUDA不可用，将使用CPU"
    except ImportError:
        return False, "PyTorch未安装"
    except Exception as e:
        return False, f"检查失败: {str(e)}"


def get_system_info() -> Dict[str, str]:
    """获取系统信息"""
    return {
        '操作系统': platform.system(),
        '系统版本': platform.release(),
        '架构': platform.machine(),
        'Python路径': get_actual_python_path(),
        '工作目录': os.getcwd()
    }


def main():
    """主函数"""
    print_colored("\n" + "=" * 60, Colors.BLUE)
    print_colored("    Kronos 环境检测工具", Colors.BOLD + Colors.BLUE)
    print_colored("=" * 60 + "\n", Colors.BLUE)

    # 系统信息
    print_header("系统信息")
    system_info = get_system_info()
    for key, value in system_info.items():
        print_info(f"{key}: {value}")

    # Python版本检查
    print_header("Python环境检查")
    python_ok, python_version = check_python_version()
    if python_ok:
        print_success(f"Python版本: {python_version}")
    else:
        print_error(f"Python版本过低: {python_version} (需要 >= 3.11)")

    # GPU检查
    gpu_ok, gpu_info = check_gpu_availability()
    if gpu_ok:
        print_success(f"GPU: {gpu_info}")
    else:
        print_warning(f"GPU: {gpu_info}")

    # 必需包检查
    print_header("必需依赖包检查")
    required_results = check_required_packages()
    required_missing = []

    for package, (installed, version) in required_results.items():
        if installed:
            print_success(f"{package}: {version}")
        else:
            print_error(f"{package}: {version}")
            required_missing.append(package)

    # 可选包检查
    print_header("可选依赖包检查")
    optional_results = check_optional_packages()

    for package, (installed, version) in optional_results.items():
        if installed:
            print_success(f"{package}: {version}")
        else:
            print_warning(f"{package}: {version}")

    # 目录结构检查
    print_header("目录结构检查")
    dir_results = check_directories()
    missing_dirs = []

    for dir_name, exists in dir_results.items():
        if exists:
            print_success(f"目录 {dir_name}/")
        else:
            print_error(f"目录 {dir_name}/ 不存在")
            missing_dirs.append(dir_name)

    # 自动修复：创建缺失目录
    if missing_dirs:
        print_info("\n尝试自动创建缺失目录...")
        remaining = create_missing_directories(missing_dirs)
        # 重新检查目录状态
        dir_results = check_directories()
        missing_dirs = [d for d, ok in dir_results.items() if not ok]
        if not remaining:
            print_success("所有缺失目录已成功创建")
        else:
            print_warning(f"部分目录创建失败: {', '.join(remaining)}")

    # 配置文件检查
    print_header("配置文件检查")
    config_results = check_config_files()

    for name, (exists, status) in config_results.items():
        if exists:
            print_success(f"{name}: {status}")
        else:
            print_error(f"{name}: {status}")

    # Tushare配置检查
    tushare_ok, tushare_status = check_tushare_config()
    if tushare_ok:
        print_success(f"Tushare Token: {tushare_status}")
    else:
        print_error(f"Tushare Token: {tushare_status}")

    # 总结
    print_header("检查总结")

    issues = []
    if not python_ok:
        issues.append("Python版本过低")
    if required_missing:
        issues.append(f"缺少必需包: {', '.join(required_missing)}")
    if missing_dirs:
        issues.append(f"缺少目录: {', '.join(missing_dirs)}")
    if not tushare_ok:
        issues.append("Tushare配置问题")

    if not issues:
        print_success("🎉 环境检查通过！所有组件都已正确安装和配置。")
        print_info("\n您可以开始使用Kronos进行金融预测了！")
        return True
    else:
        print_error("❌ 发现以下问题:")
        for issue in issues:
            print_error(f"  • {issue}")

        print_info("\n修复建议:")
        if not python_ok:
            print_info("  • 升级Python到3.11或更高版本")
        if required_missing:
            print_info(f"  • 安装缺少的包: pip install {' '.join(required_missing)}")
        if missing_dirs:
            print_info(f"  • 手动创建失败目录: mkdir -p {' '.join(missing_dirs)}")
        if not tushare_ok:
            print_info("  • 配置Tushare Token: 编辑 config/tushare_config.json")

        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_warning("\n检查被用户中断")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n检查过程中发生错误: {str(e)}")
        sys.exit(1)
