#!/usr/bin/env python3
"""
Kronos Docker 构建功能测试脚本
用于验证Docker Windows打包功能是否正常工作
"""

import os
import sys
import subprocess
import time
from pathlib import Path


class DockerBuildTester:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.project_root = self.script_dir.parent.parent
        self.test_results = []

    def log_test(self, name, success, message=""):
        """记录测试结果"""
        status = "✅ PASS" if success else "❌ FAIL"
        self.test_results.append({
            'name': name,
            'success': success,
            'message': message
        })
        print(f"{status} {name}")
        if message:
            print(f"    {message}")

    def test_docker_availability(self):
        """测试Docker是否可用"""
        try:
            result = subprocess.run(['docker', '--version'],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = result.stdout.strip()
                self.log_test("Docker安装检查", True, f"版本: {version}")
                return True
            else:
                self.log_test("Docker安装检查", False, "Docker命令执行失败")
                return False
        except FileNotFoundError:
            self.log_test("Docker安装检查", False, "Docker未安装")
            return False
        except Exception as e:
            self.log_test("Docker安装检查", False, f"检查失败: {e}")
            return False

    def test_docker_daemon(self):
        """测试Docker daemon是否运行"""
        try:
            result = subprocess.run(['docker', 'info'],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                self.log_test("Docker daemon检查", True, "Docker daemon正在运行")
                return True
            else:
                self.log_test("Docker daemon检查", False, "Docker daemon未运行")
                return False
        except Exception as e:
            self.log_test("Docker daemon检查", False, f"检查失败: {e}")
            return False

    def test_docker_files_exist(self):
        """测试Docker相关文件是否存在"""
        files_to_check = [
            'packaging/docker/Dockerfile.windows',
            'packaging/docker/Dockerfile.windows-wine',
            'packaging/scripts/build_windows_docker.py',
            'packaging/scripts/build_windows_wine.py',
            'packaging/scripts/docker_build_manager.py',
            'packaging/scripts/build_windows_docker.sh',
        ]

        all_exist = True
        missing_files = []

        for file_path in files_to_check:
            full_path = self.project_root / file_path
            if not full_path.exists():
                all_exist = False
                missing_files.append(file_path)

        if all_exist:
            self.log_test("Docker文件完整性检查", True, f"所有{len(files_to_check)}个文件都存在")
        else:
            self.log_test("Docker文件完整性检查", False,
                          f"缺失文件: {', '.join(missing_files)}")

        return all_exist

    def test_build_scripts_executable(self):
        """测试构建脚本是否可执行"""
        scripts_to_check = [
            'packaging/scripts/build_universal.sh',
            'packaging/scripts/build_windows_docker.sh',
        ]

        all_executable = True
        non_executable = []

        for script_path in scripts_to_check:
            full_path = self.project_root / script_path
            if full_path.exists():
                if not os.access(full_path, os.X_OK):
                    all_executable = False
                    non_executable.append(script_path)
            else:
                all_executable = False
                non_executable.append(f"{script_path} (不存在)")

        if all_executable:
            self.log_test("构建脚本可执行性检查", True, "所有脚本都可执行")
        else:
            self.log_test("构建脚本可执行性检查", False,
                          f"不可执行: {', '.join(non_executable)}")

        return all_executable

    def test_python_dependencies(self):
        """测试Python依赖是否满足"""
        try:
            # 检查必要的Python模块
            import json
            import subprocess
            import pathlib
            import argparse

            self.log_test("Python依赖检查", True, "所有必要模块可用")
            return True
        except ImportError as e:
            self.log_test("Python依赖检查", False, f"缺失模块: {e}")
            return False

    def test_docker_build_manager_syntax(self):
        """测试Docker构建管理器语法"""
        try:
            script_path = self.project_root / 'packaging/scripts/docker_build_manager.py'
            result = subprocess.run([sys.executable, '-m', 'py_compile', str(script_path)],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                self.log_test("Docker构建管理器语法检查", True, "语法正确")
                return True
            else:
                self.log_test("Docker构建管理器语法检查", False, f"语法错误: {result.stderr}")
                return False
        except Exception as e:
            self.log_test("Docker构建管理器语法检查", False, f"检查失败: {e}")
            return False

    def test_dockerfile_syntax(self):
        """测试Dockerfile语法"""
        dockerfiles = [
            'packaging/docker/Dockerfile.windows',
            'packaging/docker/Dockerfile.windows-wine'
        ]

        all_valid = True
        for dockerfile in dockerfiles:
            dockerfile_path = self.project_root / dockerfile
            if dockerfile_path.exists():
                try:
                    # 基本语法检查 - 确保文件可读且包含必要指令
                    with open(dockerfile_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    if 'FROM ' in content and 'CMD ' in content:
                        self.log_test(f"{dockerfile} 语法检查", True, "包含必要指令")
                    else:
                        self.log_test(f"{dockerfile} 语法检查", False, "缺少必要指令")
                        all_valid = False
                except Exception as e:
                    self.log_test(f"{dockerfile} 语法检查", False, f"读取失败: {e}")
                    all_valid = False
            else:
                self.log_test(f"{dockerfile} 语法检查", False, "文件不存在")
                all_valid = False

        return all_valid

    def test_build_universal_integration(self):
        """测试通用构建脚本集成"""
        try:
            script_path = self.project_root / 'packaging/scripts/build_universal.sh'

            if not script_path.exists():
                self.log_test("通用构建脚本集成检查", False, "build_universal.sh不存在")
                return False

            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查是否包含Docker相关功能
            docker_features = [
                'windows-docker',
                'windows-wine',
                'build_windows_docker',
                'build_windows_wine',
                'check_docker'
            ]

            missing_features = []
            for feature in docker_features:
                if feature not in content:
                    missing_features.append(feature)

            if not missing_features:
                self.log_test("通用构建脚本集成检查", True, "所有Docker功能已集成")
                return True
            else:
                self.log_test("通用构建脚本集成检查", False,
                              f"缺失功能: {', '.join(missing_features)}")
                return False

        except Exception as e:
            self.log_test("通用构建脚本集成检查", False, f"检查失败: {e}")
            return False

    def run_all_tests(self):
        """运行所有测试"""
        print("🧪 Kronos Docker 构建功能测试")
        print("=" * 50)

        # 运行测试
        tests = [
            self.test_docker_availability,
            self.test_docker_daemon,
            self.test_docker_files_exist,
            self.test_build_scripts_executable,
            self.test_python_dependencies,
            self.test_docker_build_manager_syntax,
            self.test_dockerfile_syntax,
            self.test_build_universal_integration,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                self.log_test(test.__name__, False, f"测试异常: {e}")

        # 输出测试总结
        print("\n📊 测试总结")
        print("=" * 30)

        passed = sum(1 for result in self.test_results if result['success'])
        total = len(self.test_results)

        print(f"✅ 通过: {passed}/{total}")
        print(f"❌ 失败: {total - passed}/{total}")

        if passed == total:
            print("\n🎉 所有测试通过！Docker Windows打包功能可以使用。")
            return True
        else:
            print("\n⚠️  部分测试失败，请检查上述问题。")
            print("\n💡 建议:")

            failed_tests = [r for r in self.test_results if not r['success']]
            for test in failed_tests:
                print(f"   • {test['name']}: {test['message']}")

            return False


def main():
    tester = DockerBuildTester()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
