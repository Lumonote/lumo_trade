#!/usr/bin/env python3
"""
跨平台Python命令检测器
统一处理Mac和Windows平台的Python命令差异
"""

import os
import sys
import platform
import subprocess
import shutil
import re
from pathlib import Path

MIN_SUPPORTED_VERSION = (3, 11)
PREFERRED_MINOR_ORDER = (13, 12, 11)


class PythonDetector:
    """Python命令检测器"""

    def __init__(self):
        self.system = platform.system()
        self.detected_command = None
        self._detect_python_command()

    def _detect_python_command(self):
        """检测最适合的Python命令"""
        print("🔍 检测Python环境...")

        # 最高优先级:检查环境变量 KRONOS_PYTHON_PATH
        env_python = os.environ.get('KRONOS_PYTHON_PATH')
        if env_python and Path(env_python).exists():
            try:
                result = subprocess.run([env_python, "--version"],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout + result.stderr)
                    if version_match:
                        version = version_match.group(0)
                        if self._is_supported_version(version):
                            print(f"✅ 使用环境变量指定的Python {version}: {env_python}")
                            self.detected_command = env_python
                            return
                        print(f"⚠️ 环境变量Python版本过低: {version}")
            except Exception as e:
                print(f"环境变量Python检测失败: {e}")

        # Windows: 检查用户虚拟环境
        if self.system == 'Windows':
            local_app_data = os.environ.get('LocalAppData', '')
            if local_app_data:
                venv_python = Path(local_app_data) / 'Kronos' / 'venv' / 'Scripts' / 'python.exe'
                if venv_python.exists():
                    try:
                        result = subprocess.run([str(venv_python), "--version"],
                                                capture_output=True, text=True, timeout=5)
                        if result.returncode == 0:
                            version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout + result.stderr)
                            if version_match:
                                version = version_match.group(0)
                                if self._is_supported_version(version):
                                    print(f"✅ 使用用户虚拟环境Python {version}: {venv_python}")
                                    self.detected_command = str(venv_python)
                                    return
                                print(f"⚠️ 用户虚拟环境Python版本过低: {version}")
                    except Exception as e:
                        print(f"虚拟环境Python检测失败: {e}")

        # 优先使用当前激活的虚拟环境
        if self._try_active_venv():
            return

        # 尝试使用pyenv当前版本
        if self._try_pyenv_python():
            return

        # 动态检测系统中的Python
        python_names = self._get_python_candidates()

        best_python = None
        best_version = None

        for py_name in python_names:
            try:
                py_path = shutil.which(py_name)
                if py_path:
                    result = subprocess.run([py_path, "--version"],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout + result.stderr)
                        if version_match:
                            version = version_match.group(0)
                            print(f"发现Python {version} at {py_path}")
                            if self._is_supported_version(version) and (
                                not best_python or self._version_rank(version) > self._version_rank(best_version)
                            ):
                                best_python = py_name
                                best_version = version
            except Exception as e:
                print(f"检测 {py_name} 失败: {e}")
                continue

        if best_python:
            print(f"✅ 使用最佳Python {best_version}: {best_python}")
            self.detected_command = best_python
        else:
            print("⚠️ 使用默认Python命令")
            self.detected_command = self._get_default_python()

    @staticmethod
    def _parse_version(version):
        """解析 3.x.y 版本号。"""
        if not version:
            return None
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', version)
        if not match:
            return None
        return tuple(int(part) for part in match.groups())

    @classmethod
    def _is_supported_version(cls, version):
        parsed = cls._parse_version(version)
        return bool(parsed and parsed[:2] >= MIN_SUPPORTED_VERSION)

    @classmethod
    def _version_rank(cls, version):
        """对支持版本排序：3.13 > 3.12 > 3.11，其后按实际版本号兜底。"""
        parsed = cls._parse_version(version)
        if not parsed:
            return (-1, 0, 0, 0)
        major, minor, patch = parsed
        try:
            preference = len(PREFERRED_MINOR_ORDER) - PREFERRED_MINOR_ORDER.index(minor)
        except ValueError:
            preference = 0
        return (preference, major, minor, patch)

    def _try_active_venv(self):
        """尝试使用当前激活的虚拟环境。"""
        venv_path = os.environ.get('VIRTUAL_ENV')
        if not venv_path:
            return False

        python_path = (
            Path(venv_path) / 'Scripts' / 'python.exe'
            if self.system == 'Windows'
            else Path(venv_path) / 'bin' / 'python'
        )
        if not python_path.exists():
            return False

        try:
            result = subprocess.run([str(python_path), "--version"],
                                    capture_output=True, text=True, timeout=5)
            version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout or result.stderr)
            if result.returncode == 0 and version_match:
                version = version_match.group(0)
                if self._is_supported_version(version):
                    print(f"✅ 使用当前虚拟环境Python {version}: {python_path}")
                    self.detected_command = str(python_path)
                    return True
                print(f"⚠️ 当前虚拟环境Python版本过低: {version}")
        except Exception as e:
            print(f"当前虚拟环境检测失败: {e}")
        return False

    def _try_pyenv_python(self):
        """尝试使用pyenv当前选中的Python。"""
        try:
            pyenv_path = shutil.which('pyenv')
            if pyenv_path:
                # 检查pyenv版本
                result = subprocess.run([pyenv_path, 'version'],
                                        capture_output=True, text=True, timeout=5)
                version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout or result.stderr)
                if result.returncode == 0 and version_match:
                    version = version_match.group(0)
                    if not self._is_supported_version(version):
                        print(f"⚠️ pyenv Python版本过低: {version}")
                        return False
                    # 尝试获取pyenv python路径
                    result = subprocess.run([pyenv_path, 'which', 'python'],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        pyenv_python = result.stdout.strip()
                        print(f"✅ 使用pyenv Python {version}: {pyenv_python}")
                        self.detected_command = 'python'
                        return True
        except Exception as e:
            print(f"pyenv检测失败: {e}")
        return False

    def _get_python_candidates(self):
        """获取Python命令候选列表"""
        if self.system == 'Windows':
            return [
                'python3.13.exe', 'python3.12.exe', 'python3.11.exe',
                'python3.exe', 'python.exe', 'python3.13', 'python3.12',
                'python3.11', 'python3', 'python'
            ]
        else:  # macOS/Linux
            return ['python3.13', 'python3.12', 'python3.11', 'python3', 'python']

    def _get_default_python(self):
        """获取默认Python命令"""
        if self.system == 'Windows':
            return 'python'
        else:
            return 'python3'

    def get_command(self):
        """获取检测到的Python命令"""
        return self.detected_command or self._get_default_python()

    def get_command_list(self, script_path, *args):
        """获取完整的命令列表"""
        cmd = [self.get_command(), script_path]
        cmd.extend(args)
        return cmd

    def verify_python(self):
        """验证Python环境"""
        try:
            cmd = self.get_command()
            result = subprocess.run([cmd, "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
                if version_match:
                    version = version_match.group(1)
                    print(f"✅ Python验证成功: {version}")
                    return True
            print(f"❌ Python验证失败: {result.stderr}")
            return False
        except Exception as e:
            print(f"❌ Python验证异常: {e}")
            return False


# 全局Python检测器实例
_python_detector = None


def get_python_detector():
    """获取全局Python检测器实例"""
    global _python_detector
    if _python_detector is None:
        _python_detector = PythonDetector()
    return _python_detector


def get_python_command():
    """获取Python命令"""
    return get_python_detector().get_command()


def get_python_command_list(script_path, *args):
    """获取完整的Python命令列表"""
    return get_python_detector().get_command_list(script_path, *args)


def verify_python_environment():
    """验证Python环境"""
    return get_python_detector().verify_python()


if __name__ == "__main__":
    # 测试Python检测器
    detector = PythonDetector()
    print(f"\n🐍 检测结果:")
    print(f"Python命令: {detector.get_command()}")
    print(f"验证结果: {detector.verify_python()}")

    # 测试命令生成
    test_cmd = detector.get_command_list("scripts/test.py", "--arg1", "value1")
    print(f"示例命令: {' '.join(test_cmd)}")
