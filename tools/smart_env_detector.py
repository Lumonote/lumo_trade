#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能Python环境检测器
自动检测和匹配本机最合适的Python环境
"""

import os
import sys
import json
import platform
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class PythonEnv:
    """Python环境信息"""
    path: str  # Python可执行文件路径
    version: str  # Python版本
    type: str  # 环境类型: venv, conda, pyenv, system
    name: str  # 环境名称
    location: str  # 环境位置
    has_torch: bool = False  # 是否安装了PyTorch
    has_pandas: bool = False  # 是否安装了Pandas
    has_numpy: bool = False  # 是否安装了NumPy
    score: int = 0  # 环境评分(越高越合适)


class SmartEnvDetector:
    """智能环境检测器"""

    def __init__(self):
        self.system = platform.system()
        self.detected_envs: List[PythonEnv] = []
        self.cache_file = Path.home() / '.kronos' / 'env_cache.json'

    def detect_all_environments(self) -> List[PythonEnv]:
        """检测所有可用的Python环境"""
        print("🔍 开始扫描Python环境...")

        envs = []

        # 1. 检测Kronos虚拟环境(最高优先级)
        envs.extend(self._detect_kronos_venv())

        # 2. 检测当前激活的虚拟环境
        envs.extend(self._detect_active_venv())

        # 3. 检测Conda环境
        envs.extend(self._detect_conda_envs())

        # 4. 检测pyenv环境
        envs.extend(self._detect_pyenv_envs())

        # 5. 检测系统Python
        envs.extend(self._detect_system_python())

        # 6. 检测其他虚拟环境
        envs.extend(self._detect_other_venvs())

        # 去重并评分
        self.detected_envs = self._deduplicate_and_score(envs)

        print(f"✅ 发现 {len(self.detected_envs)} 个Python环境")
        return self.detected_envs

    def _detect_kronos_venv(self) -> List[PythonEnv]:
        """检测Kronos专用虚拟环境"""
        envs = []

        if self.system == 'Windows':
            # Windows: %LocalAppData%\Kronos\venv
            local_app_data = os.environ.get('LocalAppData', '')
            if local_app_data:
                venv_path = Path(local_app_data) / 'Kronos' / 'venv'
                python_exe = venv_path / 'Scripts' / 'python.exe'

                if python_exe.exists():
                    env = self._get_env_info(str(python_exe), 'venv', 'Kronos-venv', str(venv_path))
                    if env:
                        env.score = 1000  # 最高优先级
                        envs.append(env)
                        print(f"  ✓ Kronos虚拟环境: {python_exe}")
        else:
            # macOS/Linux: ~/Library/Application Support/Kronos/venv 或 ~/.kronos/venv
            for base_dir in [
                Path.home() / 'Library' / 'Application Support' / 'Kronos',
                Path.home() / '.kronos',
                Path.home() / 'Documents' / 'Kronos'
            ]:
                venv_path = base_dir / 'venv'
                python_exe = venv_path / 'bin' / 'python'

                if python_exe.exists():
                    env = self._get_env_info(str(python_exe), 'venv', 'Kronos-venv', str(venv_path))
                    if env:
                        env.score = 1000
                        envs.append(env)
                        print(f"  ✓ Kronos虚拟环境: {python_exe}")
                        break

        return envs

    def _detect_active_venv(self) -> List[PythonEnv]:
        """检测当前激活的虚拟环境"""
        envs = []

        # 检查VIRTUAL_ENV环境变量
        venv_path = os.environ.get('VIRTUAL_ENV')
        if venv_path:
            if self.system == 'Windows':
                python_exe = Path(venv_path) / 'Scripts' / 'python.exe'
            else:
                python_exe = Path(venv_path) / 'bin' / 'python'

            if python_exe.exists():
                env = self._get_env_info(str(python_exe), 'venv', 'active-venv', venv_path)
                if env:
                    env.score = 900  # 高优先级
                    envs.append(env)
                    print(f"  ✓ 激活的虚拟环境: {python_exe}")

        return envs

    def _detect_conda_envs(self) -> List[PythonEnv]:
        """检测Conda环境"""
        envs = []

        try:
            # 查找conda命令
            conda_cmd = self._find_command(['conda', 'conda.exe'])
            if not conda_cmd:
                return envs

            # 获取conda环境列表
            result = subprocess.run(
                [conda_cmd, 'env', 'list', '--json'],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                conda_info = json.loads(result.stdout)
                for env_path in conda_info.get('envs', []):
                    if self.system == 'Windows':
                        python_exe = Path(env_path) / 'python.exe'
                    else:
                        python_exe = Path(env_path) / 'bin' / 'python'

                    if python_exe.exists():
                        env_name = Path(env_path).name
                        env = self._get_env_info(str(python_exe), 'conda', env_name, env_path)
                        if env:
                            # Conda环境优先级较低(可能有依赖冲突)
                            env.score = 500
                            envs.append(env)
                            print(f"  ✓ Conda环境 '{env_name}': {python_exe}")
        except Exception as e:
            print(f"  ⚠️  Conda检测失败: {e}")

        return envs

    def _detect_pyenv_envs(self) -> List[PythonEnv]:
        """检测pyenv环境"""
        envs = []

        if self.system == 'Windows':
            return envs  # Windows通��不使用pyenv

        try:
            pyenv_cmd = self._find_command(['pyenv'])
            if not pyenv_cmd:
                return envs

            # 获取pyenv版本列表
            result = subprocess.run(
                [pyenv_cmd, 'versions', '--bare'],
                capture_output=True, text=True, timeout=10
            )

            if result.returncode == 0:
                pyenv_root = os.environ.get('PYENV_ROOT', str(Path.home() / '.pyenv'))

                for version in result.stdout.strip().split('\n'):
                    if version:
                        python_exe = Path(pyenv_root) / 'versions' / version / 'bin' / 'python'
                        if python_exe.exists():
                            env = self._get_env_info(str(python_exe), 'pyenv', version, str(python_exe.parent.parent))
                            if env:
                                env.score = 700
                                envs.append(env)
                                print(f"  ✓ pyenv环境 '{version}': {python_exe}")
        except Exception as e:
            print(f"  ⚠️  pyenv检测失败: {e}")

        return envs

    def _detect_system_python(self) -> List[PythonEnv]:
        """检测系统Python"""
        envs = []

        # Windows系统Python常见路径
        if self.system == 'Windows':
            python_names = ['python3.11', 'python3.12', 'python3.10', 'python3', 'python']

            # 检查PATH中的Python
            for py_name in python_names:
                py_path = self._find_command([py_name + '.exe', py_name])
                if py_path:
                    env = self._get_env_info(py_path, 'system', 'system-python', os.path.dirname(py_path))
                    if env:
                        env.score = 300  # 系统Python优先级较低
                        envs.append(env)
                        print(f"  ✓ 系统Python: {py_path}")
                        break
        else:
            # macOS/Linux
            python_names = ['python3.11', 'python3.12', 'python3.10', 'python3', 'python']

            for py_name in python_names:
                py_path = self._find_command([py_name])
                if py_path:
                    # 排除虚拟环境中的Python
                    if '/venv/' not in py_path and '/.venv/' not in py_path:
                        env = self._get_env_info(py_path, 'system', 'system-python', os.path.dirname(py_path))
                        if env:
                            env.score = 300
                            envs.append(env)
                            print(f"  ✓ 系统Python: {py_path}")
                            break

        return envs

    def _detect_other_venvs(self) -> List[PythonEnv]:
        """检测项目目录中的虚拟环境"""
        envs = []

        # 检查常见的虚拟环境目录名
        venv_names = ['venv', '.venv', 'env', '.env', 'virtualenv']
        project_root = Path.cwd()

        for venv_name in venv_names:
            venv_path = project_root / venv_name

            if venv_path.exists():
                if self.system == 'Windows':
                    python_exe = venv_path / 'Scripts' / 'python.exe'
                else:
                    python_exe = venv_path / 'bin' / 'python'

                if python_exe.exists():
                    env = self._get_env_info(str(python_exe), 'venv', f'project-{venv_name}', str(venv_path))
                    if env:
                        env.score = 800  # 项目虚拟环境高优先级
                        envs.append(env)
                        print(f"  ✓ 项目虚拟环境 '{venv_name}': {python_exe}")

        return envs

    def _get_env_info(self, python_path: str, env_type: str, env_name: str, location: str) -> Optional[PythonEnv]:
        """获取Python环境详细信息"""
        try:
            # 获取Python版本
            result = subprocess.run(
                [python_path, '--version'],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0:
                return None

            version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout + result.stderr)
            if not version_match:
                return None

            version = version_match.group(1)

            # 检查关键依赖
            has_torch = self._check_package(python_path, 'torch')
            has_pandas = self._check_package(python_path, 'pandas')
            has_numpy = self._check_package(python_path, 'numpy')

            return PythonEnv(
                path=python_path,
                version=version,
                type=env_type,
                name=env_name,
                location=location,
                has_torch=has_torch,
                has_pandas=has_pandas,
                has_numpy=has_numpy
            )
        except Exception:
            return None

    def _check_package(self, python_path: str, package_name: str) -> bool:
        """检查Python环境是否安装了指定包"""
        try:
            result = subprocess.run(
                [python_path, '-c', f'import {package_name}'],
                capture_output=True, timeout=3
            )
            return result.returncode == 0
        except:
            return False

    def _find_command(self, cmd_list: List[str]) -> Optional[str]:
        """查找命令的完整路径"""
        import shutil
        for cmd in cmd_list:
            path = shutil.which(cmd)
            if path:
                return path
        return None

    def _deduplicate_and_score(self, envs: List[PythonEnv]) -> List[PythonEnv]:
        """去重并根据依赖完整性调整评分"""
        # 去重(基于路径)
        unique_envs = {}
        for env in envs:
            normalized_path = os.path.normpath(env.path)
            if normalized_path not in unique_envs:
                unique_envs[normalized_path] = env

        envs = list(unique_envs.values())

        # 根据依赖完整性调整评分
        for env in envs:
            # 有PyTorch: +100分
            if env.has_torch:
                env.score += 100
            # 有Pandas: +50分
            if env.has_pandas:
                env.score += 50
            # 有NumPy: +30分
            if env.has_numpy:
                env.score += 30

            # Python 3.11优先
            if env.version.startswith('3.11'):
                env.score += 50
            elif env.version.startswith('3.12'):
                env.score += 40

        # 按评分排序
        envs.sort(key=lambda x: x.score, reverse=True)

        return envs

    def get_best_environment(self) -> Optional[PythonEnv]:
        """获取最合适的Python环境"""
        if not self.detected_envs:
            self.detect_all_environments()

        if self.detected_envs:
            best_env = self.detected_envs[0]
            print(f"\n🎯 推荐使用: {best_env.name} (评分: {best_env.score})")
            print(f"   路径: {best_env.path}")
            print(f"   版本: Python {best_env.version}")
            print(f"   依赖: torch={'✓' if best_env.has_torch else '✗'}, "
                  f"pandas={'✓' if best_env.has_pandas else '✗'}, "
                  f"numpy={'✓' if best_env.has_numpy else '✗'}")
            return best_env

        return None

    def print_all_environments(self):
        """打印所有检测到的环境"""
        if not self.detected_envs:
            print("未检测到任何Python环境")
            return

        print("\n" + "=" * 80)
        print(f"检测到 {len(self.detected_envs)} 个Python环境:")
        print("=" * 80)

        for i, env in enumerate(self.detected_envs, 1):
            print(f"\n[{i}] {env.name} (评分: {env.score})")
            print(f"    类型: {env.type}")
            print(f"    版本: Python {env.version}")
            print(f"    路径: {env.path}")
            print(f"    位置: {env.location}")
            print(f"    依赖: torch={'✓' if env.has_torch else '✗'}, "
                  f"pandas={'✓' if env.has_pandas else '✗'}, "
                  f"numpy={'✓' if env.has_numpy else '✗'}")

    def save_cache(self):
        """保存环境检测缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        cache_data = {
            'envs': [asdict(env) for env in self.detected_envs],
            'timestamp': str(Path.home())
        }

        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)

    def load_cache(self) -> bool:
        """加载环境检测缓存"""
        if not self.cache_file.exists():
            return False

        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            self.detected_envs = [
                PythonEnv(**env_data)
                for env_data in cache_data.get('envs', [])
            ]

            return len(self.detected_envs) > 0
        except:
            return False


def main():
    """主函数"""
    print("🔍 Kronos 智能Python环境检测器\n")

    detector = SmartEnvDetector()

    # 检测所有环境
    detector.detect_all_environments()

    # 打印所有环境
    detector.print_all_environments()

    # 获取最佳环境
    best_env = detector.get_best_environment()

    if best_env:
        # 保存缓存
        detector.save_cache()
        print(f"\n✓ 环境信息已缓存到: {detector.cache_file}")
        return best_env.path
    else:
        print("\n✗ 未找到合适的Python环境")
        return None


if __name__ == '__main__':
    best_python = main()
    if best_python:
        sys.exit(0)
    else:
        sys.exit(1)
