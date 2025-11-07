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

# 打包应用环境检测与用户数据路径
def _is_app_bundle() -> bool:
    return os.environ.get('KRONOS_IS_APP_BUNDLE', '').lower() in ('1', 'true', 'yes') or \
           ('.app/Contents' in os.getcwd())

def _get_user_root() -> Path:
    # 优先使用环境变量，其次使用用户文档目录，最后回退到当前工作目录
    env_user_dir = os.environ.get('KRONOS_USER_DIR')
    if env_user_dir:
        return Path(env_user_dir)
    home_docs = Path.home() / 'Documents' / 'Kronos'
    return home_docs if home_docs.exists() else Path.cwd()


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

    # 优先检查环境变量中指定的 Python (通常由 quick_start.ps1 设置)
    venv_python = os.environ.get('KRONOS_PYTHON_PATH')
    if venv_python and os.path.exists(venv_python):
        try:
            result = subprocess.run([venv_python, "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "3." in result.stdout:
                return venv_python
        except:
            pass

    # Windows: 检查用户虚拟环境
    if platform.system() == "Windows":
        venv_dir = os.path.join(os.environ.get('LocalAppData', ''), 'Kronos', 'venv')
        venv_py = os.path.join(venv_dir, 'Scripts', 'python.exe')
        if os.path.exists(venv_py):
            try:
                result = subprocess.run([venv_py, "--version"],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and "3." in result.stdout:
                    return venv_py
            except:
                pass

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
        'huggingface_hub': 'huggingface_hub'
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
        'jupyter': 'jupyter',
        'tushare': 'tushare'
    }

    results = {}
    for display_name, import_name in optional_packages.items():
        results[display_name] = check_package_installed(import_name)

    return results


def check_directories() -> Dict[str, Tuple[Path, bool]]:
    """检查必需的目录结构（打包环境优先使用用户目录）"""
    # 计算目标路径
    if _is_app_bundle():
        user_root = _get_user_root()
        targets = {
            'data': user_root / 'data',
            'logs': user_root / 'logs',
            'results': user_root / 'results',
            'config': Path(os.environ.get('KRONOS_CONFIG_DIR', str(user_root / 'config'))),
            # scripts 保持指向资源目录，通常为只读，仅检查存在性
            'scripts': Path('scripts')
        }
    else:
        # 开发环境：检查项目根目录下的相对路径
        root = Path.cwd()
        targets = {
            'data': root / 'data',
            'logs': root / 'logs',
            'results': root / 'results',
            'config': root / 'config',
            'scripts': root / 'scripts'
        }

    results: Dict[str, Tuple[Path, bool]] = {}
    for name, p in targets.items():
        results[name] = (p, p.exists() and p.is_dir())
    return results


def create_missing_directories(missing_dirs: List[Tuple[str, Path]]) -> List[str]:
    """尝试创建缺失的目录，返回仍未创建成功的目录名称列表"""
    still_missing: List[str] = []
    for name, dir_path in missing_dirs:
        try:
            # 避免在只读资源目录创建
            if not os.access(dir_path.parent, os.W_OK) and _is_app_bundle():
                print_warning(f"跳过在只读资源目录创建 {name}/，已使用用户目录")
                still_missing.append(name)
                continue

            dir_path.mkdir(parents=True, exist_ok=True)
            if dir_path.exists() and dir_path.is_dir():
                print_success(f"已创建目录 {name}/")
            else:
                print_error(f"目录 {name}/ 创建失败")
                still_missing.append(name)
        except Exception as e:
            print_warning(f"目录 {name}/ 创建失败: {str(e)}")
            still_missing.append(name)
    return still_missing


def check_config_files() -> Dict[str, Tuple[bool, str]]:
    """检查配置文件"""
    # 支持打包环境下从用户目录读取配置
    user_config_dir = os.environ.get('KRONOS_CONFIG_DIR')
    if user_config_dir:
        cfg_tushare = Path(user_config_dir) / 'tushare_config.json'
    else:
        cfg_tushare = Path('config/tushare_config.json')

    config_files = {
        'Tushare配置': str(cfg_tushare),
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
    user_config_dir = os.environ.get('KRONOS_CONFIG_DIR')
    config_path = Path(user_config_dir) / 'tushare_config.json' if user_config_dir else Path('config/tushare_config.json')

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
    info = {
        '操作系统': platform.system(),
        '系统版本': platform.release(),
        '架构': platform.machine(),
        'Python路径': get_actual_python_path(),
        '工作目录': os.getcwd()
    }
    if _is_app_bundle():
        info['应用包模式'] = '是'
        info['用户数据目录'] = str(_get_user_root())
    else:
        info['应用包模式'] = '否'
    return info


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
    missing_dirs: List[Tuple[str, Path]] = []

    for dir_name, (dir_path, exists) in dir_results.items():
        display_path = dir_path if dir_path.is_absolute() else Path.cwd() / dir_path
        if exists:
            print_success(f"目录 {dir_name}/")
        else:
            # 在应用包模式下，优先在用户目录创建
            if _is_app_bundle():
                missing_dirs.append((dir_name, dir_path))
            else:
                missing_dirs.append((dir_name, display_path))

    # 若存在缺失目录，尝试创建并记录仍缺失的目录名称
    still_missing_names: List[str] = []
    name_to_path: Dict[str, Path] = {}
    if missing_dirs:
        # 建立名称到路径的映射，便于后续生成 mkdir 提示
        for _name, _path in missing_dirs:
            name_to_path[_name] = _path
        still_missing_names = create_missing_directories(missing_dirs)

    # 配置文件检查
    print_header("配置文件检查")
    config_results = check_config_files()

    for name, (exists, status) in config_results.items():
        if exists:
            print_success(f"{name}: {status}")
        else:
            # Tushare 配置改为非必需：缺失仅提示，不当作错误
            if name == 'Tushare配置':
                print_warning(f"{name}: {status}")
            else:
                print_error(f"{name}: {status}")

    # Tushare配置检查
    tushare_ok, tushare_status = check_tushare_config()
    if tushare_ok:
        print_success(f"Tushare Token: {tushare_status}")
    else:
        # 非必需：仅显示提醒图标
        print_warning(f"Tushare Token: {tushare_status}")

    # 总结
    print_header("检查总结")

    issues = []
    if not python_ok:
        issues.append("Python版本过低")
    if required_missing:
        issues.append(f"缺少必需包: {', '.join(required_missing)}")
    if still_missing_names:
        issues.append(f"缺少目录: {', '.join(still_missing_names)}")
    # Tushare 为非必需，不计入问题列表

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
        if still_missing_names:
            # 将仍缺失目录的路径字符串化以便给出 mkdir 提示
            remaining_paths = [str(name_to_path[n]) for n in still_missing_names if n in name_to_path]
            if remaining_paths:
                print_info(f"  • 手动创建失败目录: mkdir -p {' '.join(remaining_paths)}")
        # Tushare 为非必需，不给出强制修复建议

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
