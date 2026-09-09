#!/usr/bin/env python3
"""
Lumo 跨平台 Docker 构建管理器
支持 Windows 和 Linux 容器构建
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
import platform
import json
import time


class DockerBuildManager:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.project_root = self.script_dir.parent.parent
        self.docker_dir = self.project_root / 'packaging' / 'docker'
        self.builds_dir = self.project_root / 'packaging' / 'builds'
        self.version_config = self.project_root / 'packaging' / 'version.json'
        self.version = '1.0.0'
        self.artifact_template = 'Kronos_v{version}_{platform}_{timestamp}'

    def load_version_info(self):
        """读取版本配置和artifact模板"""
        try:
            if self.version_config.exists():
                data = json.loads(self.version_config.read_text(encoding='utf-8'))
                self.version = data.get('version', self.version)
                self.artifact_template = data.get('artifact_template', self.artifact_template)
        except Exception:
            pass

    def check_docker(self):
        """检查Docker环境"""
        print("🔍 检查Docker环境...")

        # 检查Docker是否安装
        try:
            result = subprocess.run(['docker', '--version'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Docker未正确安装")
            print(f"✅ Docker版本: {result.stdout.strip()}")
        except FileNotFoundError:
            print("❌ Docker未安装")
            print("💡 请安装Docker Desktop: https://www.docker.com/products/docker-desktop")
            return False
        except Exception as e:
            print(f"❌ Docker检查失败: {e}")
            return False

        # 检查Docker是否运行
        try:
            result = subprocess.run(['docker', 'info'], capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception("Docker daemon未运行")
            print("✅ Docker daemon正在运行")
        except Exception as e:
            print(f"❌ Docker daemon检查失败: {e}")
            print("💡 请启动Docker Desktop")
            return False

        return True

    def check_windows_containers(self):
        """检查Windows容器支持"""
        if platform.system() != "Windows":
            print("ℹ️  非Windows系统，无法使用Windows容器")
            print("💡 建议使用 windows-wine 选项进行构建")
            return False

        try:
            # 检查是否支持Windows容器
            result = subprocess.run(['docker', 'version', '--format', '{{.Server.Os}}'],
                                    capture_output=True, text=True)
            if 'windows' in result.stdout.lower():
                print("✅ Windows容器支持已启用")
                return True
            else:
                print("⚠️  当前使用Linux容器，无法构建Windows镜像")
                print("💡 建议:")
                print("   1. 如果在Windows上：切换到Windows容器模式")
                print("   2. 使用 windows-wine 选项进行Wine构建")
                return False
        except Exception as e:
            print(f"❌ Windows容器检查失败: {e}")
            print("💡 建议使用 windows-wine 选项")
            return False

    def switch_to_windows_containers(self):
        """切换到Windows容器模式"""
        print("🔄 尝试切换到Windows容器模式...")

        try:
            # 尝试通过Docker Desktop CLI切换
            docker_cli_path = r"C:\Program Files\Docker\Docker\DockerCli.exe"
            if os.path.exists(docker_cli_path):
                result = subprocess.run([docker_cli_path, '-SwitchWindowsEngine'],
                                        capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    print("✅ 已切换到Windows容器模式")
                    return True

        except Exception as e:
            print(f"⚠️  自动切换失败: {e}")

        print("💡 请手动切换到Windows容器:")
        print("   1. 右键点击系统托盘中的Docker图标")
        print("   2. 选择 'Switch to Windows containers'")
        print("   3. 等待切换完成后重新运行构建")
        return False

    def build_windows_image(self):
        """构建Windows Docker镜像"""
        print("🔨 构建Windows Docker镜像...")

        image_name = "lumo-windows-builder"
        dockerfile_path = self.docker_dir / "Dockerfile.windows"

        if not dockerfile_path.exists():
            print(f"❌ Dockerfile不存在: {dockerfile_path}")
            return False

        cmd = [
            'docker', 'build',
            '-f', str(dockerfile_path),
            '-t', image_name,
            str(self.project_root)
        ]

        print(f"执行命令: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, cwd=self.project_root, timeout=3600)  # 1小时超时
            if result.returncode == 0:
                print("✅ Windows Docker镜像构建成功")
                return True
            else:
                print("❌ Windows Docker镜像构建失败")
                return False
        except subprocess.TimeoutExpired:
            print("❌ 镜像构建超时（1小时）")
            return False
        except Exception as e:
            print(f"❌ 镜像构建失败: {e}")
            return False

    def run_windows_build(self):
        """运行Windows构建容器"""
        print("🚀 运行Windows构建...")

        container_name = "lumo-windows-build"
        image_name = "lumo-windows-builder"
        output_dir = self.builds_dir / "windows"

        # 创建输出目录
        output_dir.mkdir(parents=True, exist_ok=True)

        # 清理之前的容器
        try:
            subprocess.run(['docker', 'rm', '-f', container_name],
                           capture_output=True)
        except:
            pass

        # 运行构建容器
        cmd = [
            'docker', 'run',
            '--name', container_name,
            '--rm',
            image_name
        ]

        try:
            result = subprocess.run(cmd, timeout=3600)  # 1小时超时
            if result.returncode == 0:
                print("✅ Windows构建完成")
                return self.extract_build_results(container_name, output_dir)
            else:
                print("❌ Windows构建失败")
                return False
        except subprocess.TimeoutExpired:
            print("❌ 构建超时（1小时）")
            return False
        except Exception as e:
            print(f"❌ 构建失败: {e}")
            return False

    def extract_build_results(self, container_name, output_dir):
        """从容器中提取构建结果"""
        print("📦 提取构建结果...")

        try:
            # 尝试从运行中的容器复制
            cmd = ['docker', 'cp', f'{container_name}:/lumo/dist/.', str(output_dir)]
            result = subprocess.run(cmd, capture_output=True)

            if result.returncode == 0:
                print(f"✅ 构建结果已保存到: {output_dir}")
                self.show_build_results(output_dir)
                # 生成标准化ZIP产物
                self.create_standard_zip(output_dir)
                return True
            else:
                print("⚠️  从运行容器复制失败，尝试从已停止的容器复制...")

                # 查找已停止的容器
                result = subprocess.run(['docker', 'ps', '-a', '-q', '-f', f'name={container_name}'],
                                        capture_output=True, text=True)

                if result.stdout.strip():
                    stopped_container = result.stdout.strip()
                    cmd = ['docker', 'cp', f'{stopped_container}:/lumo/dist/.', str(output_dir)]
                    result = subprocess.run(cmd)

                    # 清理容器
                    subprocess.run(['docker', 'rm', '-f', stopped_container], capture_output=True)

                    if result.returncode == 0:
                        print(f"✅ 构建结果已保存到: {output_dir}")
                        self.show_build_results(output_dir)
                        # 生成标准化ZIP产物
                        self.create_standard_zip(output_dir)
                        return True

                print("❌ 无法提取构建结果")
                return False

        except Exception as e:
            print(f"❌ 提取构建结果失败: {e}")
            return False

    def create_standard_zip(self, output_dir: Path):
        """将Windows构建结果压缩为统一命名的ZIP"""
        try:
            self.load_version_info()
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            platform_name = 'Windows'
            name = self.artifact_template
            name = name.replace('{version}', self.version)
            name = name.replace('{platform}', platform_name)
            name = name.replace('{timestamp}', timestamp)
            zip_path = output_dir / f'{name}.zip'

            # 优先打包便携版目录
            portable_dir = output_dir / 'Kronos_Ultra_Windows_Portable'
            dist_dir = output_dir / 'dist'
            target_dir = None
            if portable_dir.exists():
                target_dir = portable_dir
            elif dist_dir.exists():
                target_dir = dist_dir

            if target_dir:
                print(f"🗜️  正在创建ZIP产物: {zip_path.name}")
                # 使用系统zip命令
                subprocess.run(['zip', '-r', str(zip_path.name), target_dir.name], cwd=output_dir)
                if zip_path.exists():
                    print(f"🎉 标准化ZIP产物已生成: {zip_path}")
            else:
                print("⚠️  未找到可打包的目录 (Kronos_Windows_Portable 或 dist)")
        except Exception as e:
            print(f"⚠️  创建ZIP产物失败: {e}")

    def show_build_results(self, output_dir):
        """显示构建结果"""
        print("\n📦 构建产物:")

        if not output_dir.exists():
            print("❌ 输出目录不存在")
            return

        total_size = 0
        for item in output_dir.rglob('*'):
            if item.is_file():
                size = item.stat().st_size
                total_size += size
                size_mb = size / (1024 * 1024)
                relative_path = item.relative_to(output_dir)
                print(f"  📄 {relative_path} ({size_mb:.1f} MB)")
            elif item.is_dir() and item != output_dir:
                relative_path = item.relative_to(output_dir)
                print(f"  📁 {relative_path}/")

        total_mb = total_size / (1024 * 1024)
        print(f"\n💾 总大小: {total_mb:.1f} MB")

    def build_windows(self):
        """完整的Windows构建流程"""
        print("🚀 Lumo Windows Docker 构建器")
        print("=" * 50)

        # 1. 检查Docker环境
        if not self.check_docker():
            return False

        # 2. 检查Windows容器支持
        if not self.check_windows_containers():
            return False

        # 3. 构建Docker镜像
        if not self.build_windows_image():
            return False

        # 4. 运行构建
        if not self.run_windows_build():
            return False

        print("\n🎉 Windows构建全部完成!")
        print(f"📁 构建结果: {self.builds_dir / 'windows'}")

        return True

    def clean_docker_resources(self):
        """清理Docker资源"""
        print("🧹 清理Docker资源...")

        # 清理构建缓存
        try:
            subprocess.run(['docker', 'builder', 'prune', '-f'], capture_output=True)
            print("✅ 构建缓存已清理")
        except:
            pass

        # 清理未使用的镜像
        try:
            subprocess.run(['docker', 'image', 'prune', '-f'], capture_output=True)
            print("✅ 未使用的镜像已清理")
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description='Lumo Docker 构建管理器')
    parser.add_argument('action', choices=['build', 'clean'],
                        help='执行的操作 (build: 构建Windows版本, clean: 清理Docker资源)')
    parser.add_argument('--platform', choices=['windows'], default='windows',
                        help='目标平台 (默认: windows)')

    args = parser.parse_args()

    manager = DockerBuildManager()

    if args.action == 'build':
        if args.platform == 'windows':
            success = manager.build_windows()
            sys.exit(0 if success else 1)
    elif args.action == 'clean':
        manager.clean_docker_resources()
        sys.exit(0)


if __name__ == '__main__':
    main()
