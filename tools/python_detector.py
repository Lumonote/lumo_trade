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


class PythonDetector:
    """Python命令检测器"""

    def __init__(self):
        self.system = platform.system()
        self.detected_command = None
        self._detect_python_command()

    def _detect_python_command(self):
        """检测最适合的Python命令"""
        print("🔍 检测Python环境...")

        # 首先尝试使用pyenv中的Python 3.11.13
        if self._try_pyenv_python():
            return

        # 动态检测系统中的Python
        python_names = self._get_python_candidates()

        best_python = None
        best_version = ""

        for py_name in python_names:
            try:
                py_path = shutil.which(py_name)
                if py_path:
                    result = subprocess.run([py_path, "--version"],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        version_match = re.search(r'3\.(\d+)\.(\d+)', result.stdout)
                        if version_match:
                            version = version_match.group(0)
                            print(f"发现Python {version} at {py_path}")

                            # 优先选择3.11.x
                            if version.startswith('3.11.'):
                                print(f"✅ 使用Python 3.11: {py_path}")
                                self.detected_command = py_name
                                return
                            elif version.startswith('3.') and (not best_python or version > best_version):
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

    def _try_pyenv_python(self):
        """尝试使用pyenv中的Python 3.11.13"""
        try:
            pyenv_path = shutil.which('pyenv')
            if pyenv_path:
                # 检查pyenv版本
                result = subprocess.run([pyenv_path, 'version'],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and '3.11.13' in result.stdout:
                    # 如果是3.11.x版本，直接使用pyenv中的python
                    print("✅ 发现pyenv Python 3.11.13")
                    # 尝试获取pyenv python路径
                    result = subprocess.run([pyenv_path, 'which', 'python'],
                                            capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        pyenv_python = result.stdout.strip()
                        print(f"✅ 使用pyenv Python: {pyenv_python}")
                        self.detected_command = 'python'
                        return True
        except Exception as e:
            print(f"pyenv检测失败: {e}")
        return False

    def _get_python_candidates(self):
        """获取Python命令候选列表"""
        if self.system == 'Windows':
            return ['python3.11.exe', 'python3.exe', 'python.exe', 'python3.11', 'python3', 'python']
        else:  # macOS/Linux
            return ['python3.11', 'python3', 'python']

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
