# Kronos Docker 打包说明

本文档介绍如何使用Docker为Kronos项目构建Windows版本的应用程序。

## 概述

Kronos现在支持以下几种Windows构建方式：

1. **Windows本地构建** - 在Windows机器上直接构建
2. **Docker Windows容器** - 使用Windows Docker容器构建（推荐）
3. **Wine模拟器** - 使用Wine在Linux容器中构建Windows应用（备选方案）

## 前置要求

### Docker环境

- Docker Desktop 已安装并运行
- 对于Windows容器：需要Windows 10/11专业版，并启用Windows容器支持
- 对于Wine方案：支持Linux容器即可

### 系统要求

- macOS、Linux或Windows系统
- 至少8GB内存（Docker构建需要较多资源）
- 足够的磁盘空间（Docker镜像约2-4GB）

## 使用方法

### 1. 快速开始

```bash
# 使用Docker构建Windows版本（推荐）
./packaging/scripts/build_universal.sh windows-docker

# 使用Wine构建Windows版本（备选方案）
./packaging/scripts/build_universal.sh windows-wine

# 构建所有平台（包括Windows）
./packaging/scripts/build_universal.sh all
```

### 2. 详细命令

#### Windows Docker构建

```bash
cd /path/to/kronos
./packaging/scripts/build_universal.sh windows-docker
```

#### Wine构建（备选方案）

```bash
cd /path/to/kronos
./packaging/scripts/build_universal.sh windows-wine
```

#### 使用Docker构建管理器

```bash
# 构建Windows版本
python packaging/scripts/docker_build_manager.py build --platform windows

# 清理Docker资源
python packaging/scripts/docker_build_manager.py clean
```

#### 直接使用Docker脚本

```bash
# Windows Docker构建
./packaging/scripts/build_windows_docker.sh
```

### 3. 高级用法

#### 自定义Docker构建

```bash
# 手动构建Docker镜像
docker build -f packaging/docker/Dockerfile.windows -t kronos-windows-builder .

# 运行构建容器
docker run --name kronos-build --rm kronos-windows-builder

# 从容器复制结果
docker cp kronos-build:/kronos/dist/. ./packaging/builds/windows/
```

#### Wine构建方式

```bash
# 构建Wine镜像
docker build -f packaging/docker/Dockerfile.windows-wine -t kronos-wine-builder .

# 运行Wine构建
docker run --rm kronos-wine-builder
```

## 构建产物

### 输出目录结构

```
packaging/builds/
├── windows/                     # Windows Docker构建结果
│   ├── Kronos.exe              # 主程序
│   ├── Kronos_Windows_Portable/ # 便携版目录
│   └── README.txt              # 使用说明
├── windows-wine/               # Wine构建结果
│   └── Kronos_Windows_Portable/
└── Kronos_v1.0_macOS.dmg      # macOS版本（如果在macOS上构建）
```

### 文件说明

- **Kronos.exe** - Windows可执行文件（约40-60MB）
- **Kronos_Windows_Portable/** - 便携版目录，包含所有必要文件
- **README.txt** - 详细的使用说明和系统要求
- **start_kronos.bat** - 带控制台输出的启动脚本

## 构建选项对比

| 构建方式           | 优点                                 | 缺点                             | 推荐度   |
|----------------|------------------------------------|--------------------------------|-------|
| Windows Docker | ✅ 原生Windows环境<br>✅ 兼容性最好<br>✅ 性能最佳 | ❌ 需要Windows容器支持<br>❌ 镜像较大      | ⭐⭐⭐⭐⭐ |
| Wine模拟         | ✅ 跨平台支持<br>✅ Linux容器即可<br>✅ 构建速度快  | ❌ 可能有兼容性问题<br>❌ 不是真正的Windows环境 | ⭐⭐⭐   |
| 本地构建           | ✅ 性能最佳<br>✅ 调试方便                   | ❌ 需要Windows机器<br>❌ 环境配置复杂      | ⭐⭐⭐⭐  |

## 故障排除

### Docker相关问题

#### 1. Docker未运行

```
❌ Docker daemon未运行
💡 请启动Docker Desktop
```

**解决方案：** 启动Docker Desktop应用程序

#### 2. Windows容器支持

```
⚠️ 当前使用Linux容器，需要切换到Windows容器
```

**解决方案：**

1. 右键点击系统托盘中的Docker图标
2. 选择"Switch to Windows containers"
3. 等待切换完成

#### 3. 内存不足

```
❌ Docker镜像构建失败
```

**解决方案：**

1. 增加Docker Desktop的内存限制（推荐8GB+）
2. 关闭其他占用内存的应用程序
3. 清理Docker缓存：`docker system prune -a`

### 构建相关问题

#### 1. 权限错误

```
❌ Permission denied
```

**解决方案：**

- macOS/Linux: 确保脚本有执行权限 `chmod +x packaging/scripts/*.sh`
- Windows: 以管理员身份运行命令行

#### 2. 网络问题

```
❌ 无法下载依赖
```

**解决方案：**

1. 检查网络连接
2. 配置Docker代理（如果在企业网络环境中）
3. 使用国内镜像源

#### 3. 磁盘空间不足

```
❌ No space left on device
```

**解决方案：**

1. 清理Docker镜像和容器：`docker system prune -a`
2. 增加可用磁盘空间
3. 将Docker数据目录迁移到其他驱动器

### Wine相关问题

#### 1. Wine初始化失败

```
❌ Wine环境问题
```

**解决方案：**

1. 使用最新的Docker镜像
2. 增加容器的内存和时间限制
3. 切换到Windows Docker构建

#### 2. 编码问题

```
❌ 'utf-8' codec can't decode
```

**解决方案：**

1. 已在最新版本中修复
2. 更新到最新代码版本

## 性能优化

### 1. Docker优化

```bash
# 增加Docker内存限制
# Docker Desktop -> Settings -> Resources -> Memory: 8GB+

# 启用BuildKit（更快的构建）
export DOCKER_BUILDKIT=1

# 使用多阶段构建缓存
docker build --cache-from kronos-windows-builder .
```

### 2. 并行构建

```bash
# 同时构建多个平台
./packaging/scripts/build_universal.sh all
```

### 3. 缓存优化

```bash
# 保留Docker镜像以加速后续构建
docker images | grep kronos

# 清理时保留基础镜像
docker image prune -f
```

## 持续集成

### GitHub Actions示例

```yaml
name: Build Windows
on: [push, pull_request]
jobs:
  build-windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build Windows with Docker
        run: ./packaging/scripts/build_universal.sh windows-docker
```

### 本地自动化

```bash
# 创建自动构建脚本
cat > build_all.sh << 'EOF'
#!/bin/bash
./packaging/scripts/build_universal.sh all --clean
echo "所有平台构建完成！"
EOF

chmod +x build_all.sh
./build_all.sh
```

## 更多信息

- 🐳 [Docker官方文档](https://docs.docker.com/)
- 🍷 [Wine项目主页](https://www.winehq.org/)
- 📦 [PyInstaller文档](https://pyinstaller.readthedocs.io/)
- 🚀 [Kronos项目主页](https://github.com/your-org/kronos)

## 技术支持

如果遇到问题，请：

1. 查看本文档的故障排除部分
2. 检查[项目Issues](https://github.com/your-org/kronos/issues)
3. 提交新的Issue，包含完整的错误日志
4. 联系技术支持团队

---

**注意：** Docker构建功能需要足够的系统资源，建议在性能较好的机器上进行构建。首次构建会下载较大的基础镜像，请确保网络稳定。