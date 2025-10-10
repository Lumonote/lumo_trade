#!/bin/bash

# Kronos Windows Docker 构建脚本
# 用于在Docker中构建Windows版本的Kronos应用

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOCKER_DIR="$PROJECT_ROOT/packaging/docker"

echo "🚀 Kronos Windows Docker 构建器"
echo "================================"
echo "📁 项目根目录: $PROJECT_ROOT"
echo "🐳 Docker文件: $DOCKER_DIR"

# 检查Docker是否可用
if ! command -v docker &> /dev/null; then
    echo "❌ Docker未安装或不可用"
    echo "💡 请安装Docker Desktop并确保Windows容器支持已启用"
    exit 1
fi

# 检查Docker是否运行
if ! docker info &> /dev/null; then
    echo "❌ Docker daemon未运行"
    echo "💡 请启动Docker Desktop"
    exit 1
fi

# 切换到Windows容器模式（如果在Windows上运行）
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    echo "🔄 切换到Windows容器模式..."
    powershell -Command "& 'C:\Program Files\Docker\Docker\DockerCli.exe' -SwitchWindowsEngine" || true
fi

# 构建Docker镜像
IMAGE_NAME="kronos-windows-builder"
CONTAINER_NAME="kronos-windows-build"

echo "🔨 构建Docker镜像: $IMAGE_NAME"
cd "$PROJECT_ROOT"

docker build \
    -f packaging/docker/Dockerfile.windows \
    -t $IMAGE_NAME \
    . || {
    echo "❌ Docker镜像构建失败"
    exit 1
}

echo "✅ Docker镜像构建完成"

# 运行构建容器
echo "🚀 启动构建容器..."

# 清理之前的容器
docker rm -f $CONTAINER_NAME 2>/dev/null || true

# 创建输出目录
OUTPUT_DIR="$PROJECT_ROOT/packaging/builds/windows"
mkdir -p "$OUTPUT_DIR"

# 运行构建
docker run \
    --name $CONTAINER_NAME \
    --rm \
    -v "$OUTPUT_DIR:/output" \
    $IMAGE_NAME || {
    echo "❌ Windows构建失败"
    exit 1
}

# 从容器中复制构建结果
echo "📦 复制构建结果..."
docker cp $CONTAINER_NAME:/kronos/dist/. "$OUTPUT_DIR/" || {
    echo "⚠️  无法复制构建结果，检查容器状态"
    # 尝试从已停止的容器复制
    STOPPED_CONTAINER=$(docker ps -a -q -f name=$CONTAINER_NAME)
    if [ ! -z "$STOPPED_CONTAINER" ]; then
        docker cp $STOPPED_CONTAINER:/kronos/dist/. "$OUTPUT_DIR/"
        docker rm -f $STOPPED_CONTAINER
    fi
}

echo "🎉 Windows构建完成!"
echo "📁 构建结果保存在: $OUTPUT_DIR"

# 显示构建结果
if [ -d "$OUTPUT_DIR" ]; then
    echo ""
    echo "📦 构建产物:"
    ls -la "$OUTPUT_DIR"
    
    # 计算文件大小
    if [ -f "$OUTPUT_DIR/Kronos.exe" ]; then
        SIZE=$(du -sh "$OUTPUT_DIR/Kronos.exe" | cut -f1)
        echo "💾 Kronos.exe 大小: $SIZE"
    fi
fi

echo ""
echo "🎯 使用说明:"
echo "1. 将 $OUTPUT_DIR 中的文件传输到Windows机器"
echo "2. 双击 Kronos.exe 启动应用"
echo "3. 或使用 start_kronos.bat 查看控制台输出"
echo ""
echo "✅ 构建完成!"