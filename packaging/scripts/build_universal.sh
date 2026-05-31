#!/bin/bash

# Kronos 通用打包工具 - 增强版
# 支持本地构建和Docker构建

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION_CONFIG="$PROJECT_ROOT/packaging/version.json"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}🚀 Kronos 通用打包工具${NC}"
echo "========================"
echo -e "${BLUE}📁 项目根目录: $PROJECT_ROOT${NC}"
echo ""

# 显示使用帮助
show_help() {
    echo "使用方法: $0 [平台] [选项]"
    echo ""
    echo "支持的平台:"
    echo "  macos          - 使用Tauri构建macOS版本 (本地构建)"
    echo "  windows        - 使用Tauri构建Windows版本 (需要Windows环境)"
    echo "  windows-docker - 旧PyInstaller Docker构建Windows版本"
    echo "  windows-wine   - 旧PyInstaller Wine构建Windows版本"
    echo "  linux          - 使用Tauri构建Linux版本 (本地构建)"
    echo "  all            - 构建所有平台版本"
    echo ""
    echo "选项:"
    echo "  --docker       - 强制使用Docker构建"
    echo "  --clean        - 构建前清理"
    echo "  --help, -h     - 显示此帮助"
    echo ""
    echo "示例:"
    echo "  $0 macos                    # 构建macOS版本"
    echo "  $0 windows-docker           # 使用Docker构建Windows版本"
    echo "  $0 all --clean              # 清理后构建所有版本"
    echo ""
}

# 检查参数
if [ $# -eq 0 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    show_help
    exit 0
fi

PLATFORM="$1"
USE_DOCKER=false
CLEAN_BUILD=false

# 解析选项
shift
while [[ $# -gt 0 ]]; do
    case $1 in
        --docker)
            USE_DOCKER=true
            shift
            ;;
        --clean)
            CLEAN_BUILD=true
            shift
            ;;
        *)
            echo -e "${RED}❌ 未知选项: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

# 检测当前操作系统
detect_os() {
    case "$(uname -s)" in
        Darwin)
            echo "macos"
            ;;
        Linux)
            echo "linux"
            ;;
        CYGWIN*|MINGW32*|MSYS*|MINGW*)
            echo "windows"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

CURRENT_OS=$(detect_os)
echo -e "${BLUE}🖥️  当前操作系统: $CURRENT_OS${NC}"
echo ""

# 读取版本配置
load_version_config() {
    # 默认值
    VERSION="1.0.0"
    SHORT_VERSION="$VERSION"
    CHANNEL="stable"
    ARTIFACT_TEMPLATE="Kronos_v{version}_{platform}_{timestamp}"

    # 使用Python解析版本配置（优先）
    if [ -f "$VERSION_CONFIG" ] && [ -n "$PYTHON_CMD" ]; then
        local info
        info=$($PYTHON_CMD -c "import json,sys; p=json.load(open(r'$VERSION_CONFIG')); print(f\"{p.get('version','1.0.0')}|{p.get('short_version',p.get('version','1.0.0'))}|{p.get('channel','stable')}|{p.get('artifact_template','Kronos_v{version}_{platform}_{timestamp}')}\")" 2>/dev/null || true)
        if [ -n "$info" ]; then
            IFS='|' read -r VERSION SHORT_VERSION CHANNEL ARTIFACT_TEMPLATE <<< "$info"
        fi
    fi
}

# 清理函数
clean_build() {
    echo -e "${YELLOW}🧹 清理构建目录...${NC}"
    
    # 清理Python缓存
    find "$PROJECT_ROOT" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$PROJECT_ROOT" -type f -name "*.pyc" -delete 2>/dev/null || true
    
    # 清理构建目录
    rm -rf "$PROJECT_ROOT/build" 2>/dev/null || true
    rm -rf "$PROJECT_ROOT/dist" 2>/dev/null || true
    rm -rf "$PROJECT_ROOT"/*.spec 2>/dev/null || true
    
    echo -e "${GREEN}✅ 清理完成${NC}"
}

# 检查Python环境
check_python() {
    echo -e "${BLUE}📋 检查Python环境...${NC}"

    # 查找可用的Python版本，优先使用项目虚拟环境，避免 Homebrew/System Python 的 PEP 668 限制
    local candidates=()
    if [ -n "${PYTHON_CMD:-}" ]; then
        candidates+=("$PYTHON_CMD")
    fi
    if [ "$CURRENT_OS" = "windows" ]; then
        candidates+=(
            "$PROJECT_ROOT/.venv/Scripts/python.exe"
            "$PROJECT_ROOT/venv/Scripts/python.exe"
        )
    else
        candidates+=(
            "$PROJECT_ROOT/.venv/bin/python"
            "$PROJECT_ROOT/venv/bin/python"
        )
    fi
    candidates+=(python3.13 python3.12 python3.11 python3 python)

    PYTHON_CMD=""
    for py in "${candidates[@]}"; do
        if [ -x "$py" ] || command -v "$py" &> /dev/null; then
            if "$py" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null; then
                PYTHON_CMD="$py"
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${RED}❌ 未找到Python 3.11+${NC}"
        echo -e "${YELLOW}💡 请安装Python 3.11或更高版本${NC}"
        exit 1
    fi

    echo -e "${GREEN}🐍 使用Python版本: $($PYTHON_CMD --version)${NC}"
    echo -e "${GREEN}✅ Python环境检查完成${NC}"
}

ensure_pyinstaller() {
    if ! "$PYTHON_CMD" -c "import PyInstaller" >/dev/null 2>&1; then
        echo -e "${YELLOW}📦 未检测到 PyInstaller，正在安装...${NC}"
        "$PYTHON_CMD" -m pip install pyinstaller
    fi
}

build_bundled_backend() {
    if [ "${KRONOS_SKIP_BACKEND_BUNDLE:-0}" = "1" ]; then
        echo -e "${YELLOW}⚠️  已跳过内置 WebUI backend 构建${NC}"
        return 0
    fi

    echo -e "${BLUE}📦 构建内置 WebUI backend (PyInstaller)...${NC}"
    check_python

    cd "$PROJECT_ROOT"
    export KRONOS_BACKEND_BUNDLE_MODE="${KRONOS_BACKEND_BUNDLE_MODE:-lite}"
    export KRONOS_WEB_SERVER="${KRONOS_WEB_SERVER:-robyn}"
    "$PYTHON_CMD" "$PROJECT_ROOT/packaging/scripts/build_backend.py" --clean --mode "${KRONOS_BACKEND_BUNDLE_MODE:-lite}"

    local backend_exe="$PROJECT_ROOT/packaging/backend/kronos_webui_backend/kronos_webui_backend"
    if [ "$CURRENT_OS" = "windows" ]; then
        backend_exe="${backend_exe}.exe"
    fi
    if [ ! -f "$backend_exe" ]; then
        echo -e "${RED}❌ 内置 backend 构建失败: $backend_exe 不存在${NC}"
        return 1
    fi
    echo -e "${GREEN}✅ 内置 backend 构建完成: $backend_exe${NC}"
}

# 检查Docker环境
check_docker() {
    echo -e "${BLUE}🐳 检查Docker环境...${NC}"
    
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker未安装${NC}"
        echo -e "${YELLOW}💡 请安装Docker Desktop: https://www.docker.com/products/docker-desktop${NC}"
        return 1
    fi
    
    if ! docker info &> /dev/null; then
        echo -e "${RED}❌ Docker daemon未运行${NC}"
        echo -e "${YELLOW}💡 请启动Docker Desktop${NC}"
        return 1
    fi
    
    echo -e "${GREEN}✅ Docker环境检查完成${NC}"
    return 0
}

# 准备资源文件
prepare_resources() {
    local version=${1:-"modern"}
    echo -e "${BLUE}📂 准备资源文件 ($version版本)...${NC}"
    
    case $version in
        "modern")
            echo -e "${PURPLE}🎨 使用 Tauri + Web UI 桌面版本${NC}"
            ;;
        "console")
            echo -e "${PURPLE}⌨️  使用控制台版本${NC}"
            ;;
    esac
    
    echo -e "${GREEN}✅ 资源文件准备完成${NC}"
}

check_tauri_environment() {
    echo -e "${BLUE}📋 检查Tauri环境...${NC}"

    if ! command -v cargo &> /dev/null; then
        echo -e "${RED}❌ 未找到Rust/Cargo${NC}"
        echo -e "${YELLOW}💡 请先安装Rust工具链: https://www.rust-lang.org/tools/install${NC}"
        return 1
    fi

    if ! command -v npm &> /dev/null; then
        echo -e "${RED}❌ 未找到npm${NC}"
        echo -e "${YELLOW}💡 请先安装Node.js/npm${NC}"
        return 1
    fi

    cd "$PROJECT_ROOT"
    if [ ! -d "node_modules/@tauri-apps/cli" ]; then
        echo -e "${YELLOW}📦 未检测到Tauri CLI依赖，执行 npm install...${NC}"
        npm install
    fi

    echo -e "${GREEN}✅ Tauri环境检查完成${NC}"
}

copy_tauri_artifacts() {
    local bundle_dir="$PROJECT_ROOT/src-tauri/target/release/bundle"
    local output_dir="$PROJECT_ROOT/packaging/builds"

    if [ ! -d "$bundle_dir" ]; then
        echo -e "${YELLOW}⚠️  未找到Tauri bundle目录: $bundle_dir${NC}"
        return 0
    fi

    mkdir -p "$output_dir"
    find "$bundle_dir" -maxdepth 3 \( -name "*.dmg" -o -name "*.app" -o -name "*.msi" -o -name "*.exe" -o -name "*.deb" -o -name "*.rpm" -o -name "*.AppImage" \) ! -name "rw.*" -print | while read -r artifact; do
        local target="$output_dir/$(basename "$artifact")"
        rm -rf "$target" 2>/dev/null || true
        cp -R "$artifact" "$output_dir/" 2>/dev/null || true
        echo -e "${PURPLE}📦 Tauri产物: $artifact${NC}"
    done
    echo -e "${CYAN}📁 统一产物目录: $output_dir${NC}"
}

build_tauri_desktop() {
    local platform_name="$1"

    echo -e "${PURPLE}🖥️  开始Tauri桌面构建 ($platform_name)...${NC}"
    echo "=========================================="

    check_tauri_environment || return 1
    build_bundled_backend || return 1
    cd "$PROJECT_ROOT"

    npm run desktop:build

    if [ $? -eq 0 ]; then
        copy_tauri_artifacts
        echo -e "${GREEN}✅ Tauri桌面构建成功！${NC}"
        return 0
    else
        echo -e "${RED}❌ Tauri桌面构建失败${NC}"
        return 1
    fi
}

# macOS构建
build_macos() {
    if [ "$CURRENT_OS" != "macos" ]; then
        echo -e "${RED}❌ Tauri macOS构建需要在macOS系统上运行${NC}"
        return 1
    fi

    build_tauri_desktop "macOS"
}

# Windows Docker构建
build_windows_docker() {
    echo -e "${PURPLE}🐳🪟 开始Windows Docker构建...${NC}"
    echo "=========================================="
    
    if ! check_docker; then
        return 1
    fi
    
    # 检查是否为非Windows系统
    if [ "$CURRENT_OS" != "windows" ]; then
        echo -e "${YELLOW}⚠️  非Windows系统无法使用Windows容器${NC}"
        echo -e "${BLUE}💡 自动切换到Wine构建方案...${NC}"
        build_windows_wine
        return $?
    fi
    
    cd "$PROJECT_ROOT"
    
    # 使用Docker构建管理器
    $PYTHON_CMD packaging/scripts/docker_build_manager.py build --platform windows
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Windows Docker构建成功！${NC}"
        return 0
    else
        echo -e "${YELLOW}❌ Windows Docker构建失败，尝试Wine构建...${NC}"
        build_windows_wine
        return $?
    fi
}

# Windows Wine构建
build_windows_wine() {
    echo -e "${PURPLE}🍷🪟 开始Windows Wine构建...${NC}"
    echo "=========================================="
    
    if ! check_docker; then
        return 1
    fi
    
    cd "$PROJECT_ROOT"
    
    IMAGE_NAME="kronos-windows-wine-builder"
    CONTAINER_NAME="kronos-wine-build"
    OUTPUT_DIR="packaging/builds"
    
    # 构建Wine Docker镜像
    echo -e "${BLUE}🔨 构建Wine Docker镜像...${NC}"
    docker build -f packaging/docker/Dockerfile.windows-wine -t $IMAGE_NAME .
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Wine镜像构建失败${NC}"
        return 1
    fi
    
    # 创建输出目录（统一到 packaging/builds）
    mkdir -p "$OUTPUT_DIR"
    
    # 运行Wine构建
    echo -e "${BLUE}🚀 运行Wine构建...${NC}"
    # 运行容器（不加 --rm，便于复制产物），复制后再清理
    docker run --name $CONTAINER_NAME $IMAGE_NAME
    
    if [ $? -eq 0 ]; then
        # 从容器复制结果到统一目录
        docker cp $CONTAINER_NAME:/kronos/dist/. "$OUTPUT_DIR/" || true

        # 清理容器
        docker rm -f $CONTAINER_NAME >/dev/null 2>&1 || true

        # 读取版本配置并生成标准化ZIP名称
        load_version_config
        TIMESTAMP=$(date "+%Y%m%d_%H%M%S")
        PLATFORM_NAME="Windows"
        ARTIFACT_NAME="$ARTIFACT_TEMPLATE"
        ARTIFACT_NAME="${ARTIFACT_NAME/\{version\}/$VERSION}"
        ARTIFACT_NAME="${ARTIFACT_NAME/\{platform\}/$PLATFORM_NAME}"
        ARTIFACT_NAME="${ARTIFACT_NAME/\{timestamp\}/$TIMESTAMP}"

        # 将便携版目录压缩为标准命名的ZIP
        PORTABLE_DIR="$OUTPUT_DIR/Kronos_Ultra_Windows_Portable"
        if [ -d "$OUTPUT_DIR/Kronos_Ultra_Windows_Portable" ]; then
            (cd "$OUTPUT_DIR" && zip -r "${ARTIFACT_NAME}.zip" "Kronos_Ultra_Windows_Portable" >/dev/null 2>&1 || true)
            if [ -f "$OUTPUT_DIR/${ARTIFACT_NAME}.zip" ]; then
                echo -e "${PURPLE}📦 创建了ZIP产物: $OUTPUT_DIR/${ARTIFACT_NAME}.zip${NC}"
            fi
        else
            # 如果容器中的便携包不在顶层，尝试从 dist 目录中处理
            if [ -d "$OUTPUT_DIR/dist/Kronos_Ultra_Windows_Portable" ]; then
                mv "$OUTPUT_DIR/dist/Kronos_Ultra_Windows_Portable" "$OUTPUT_DIR/" 2>/dev/null || true
                (cd "$OUTPUT_DIR" && zip -r "${ARTIFACT_NAME}.zip" "Kronos_Ultra_Windows_Portable" >/dev/null 2>&1 || true)
                if [ -f "$OUTPUT_DIR/${ARTIFACT_NAME}.zip" ]; then
                    echo -e "${PURPLE}📦 创建了ZIP产物: $OUTPUT_DIR/${ARTIFACT_NAME}.zip${NC}"
                fi
            fi
        fi

        echo -e "${GREEN}✅ Windows Wine构建成功！${NC}"
        echo -e "${CYAN}📁 构建结果目录: $OUTPUT_DIR${NC}"
        return 0
    else
        echo -e "${RED}❌ Windows Wine构建失败${NC}"
        return 1
    fi
}

# Windows本地构建
build_windows_local() {
    if [ "$CURRENT_OS" != "windows" ]; then
        echo -e "${RED}❌ Windows本地构建需要在Windows系统上运行${NC}"
        echo -e "${YELLOW}💡 Tauri官方推荐在目标系统本地构建对应桌面包${NC}"
        return 1
    fi

    build_tauri_desktop "Windows"
}

# Linux构建
build_linux() {
    if [ "$CURRENT_OS" != "linux" ] && [ "$USE_DOCKER" = false ]; then
        echo -e "${RED}❌ Linux构建需要在Linux系统上运行${NC}"
        echo -e "${YELLOW}💡 或者使用 --docker 选项${NC}"
        return 1
    fi
    
    echo -e "${PURPLE}🐧 开始Linux构建...${NC}"
    echo "=========================================="
    
    build_tauri_desktop "Linux"
}

# 构建所有平台
build_all() {
    echo -e "${PURPLE}🌍 开始构建所有平台版本...${NC}"
    echo "=========================================="
    
    local success_count=0
    local total_count=0
    
    # macOS构建
    if [ "$CURRENT_OS" = "macos" ]; then
        ((total_count++))
        echo -e "\n${CYAN}📱 构建macOS版本...${NC}"
        if build_macos; then
            ((success_count++))
        fi
    fi
    
    # Windows构建
    ((total_count++))
    echo -e "\n${CYAN}🪟 构建Windows版本...${NC}"
    if [ "$CURRENT_OS" = "windows" ] && [ "$USE_DOCKER" = "false" ]; then
        # 在Windows系统上优先使用本地构建
        if build_windows_local; then
            ((success_count++))
        else
            # 如果本地构建失败，尝试Docker构建
            echo -e "${YELLOW}💡 本地构建失败，尝试Docker构建...${NC}"
            if build_windows_docker; then
                ((success_count++))
            fi
        fi
    else
        # 非Windows系统或强制使用Docker时使用Docker构建
        if build_windows_docker; then
            ((success_count++))
        else
            # 如果Docker构建失败，尝试Wine构建
            echo -e "${YELLOW}💡 Docker构建失败，尝试Wine构建...${NC}"
            if build_windows_wine; then
                ((success_count++))
            fi
        fi
    fi
    
    echo -e "\n${PURPLE}📊 构建总结${NC}"
    echo "========================"
    echo -e "${GREEN}✅ 成功: $success_count/$total_count${NC}"
    
    if [ $success_count -eq $total_count ]; then
        echo -e "${GREEN}🎉 所有平台构建完成！${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  部分平台构建失败${NC}"
        return 1
    fi
}

# 主构建逻辑
main() {
    # 清理构建（如果需要）
    if [ "$CLEAN_BUILD" = true ]; then
        clean_build
        echo ""
    fi
    
    # 检查Python环境（除非纯Docker构建）
    if [ "$USE_DOCKER" = "false" ] || [ "$PLATFORM" = "macos" ] || ([ "$PLATFORM" = "windows" ] && [ "$CURRENT_OS" = "windows" ]); then
        check_python
        echo ""
    fi
    
    # 准备资源文件
    prepare_resources "modern"
    echo ""
    
    # 根据平台执行构建
    case $PLATFORM in
        "macos")
            build_macos
            ;;
        "windows")
            if [ "$USE_DOCKER" = true ]; then
                build_windows_docker
            elif [ "$CURRENT_OS" = "windows" ]; then
                build_windows_local
            else
                build_windows_docker
            fi
            ;;
        "windows-docker")
            build_windows_docker
            ;;
        "windows-wine")
            build_windows_wine
            ;;
        "linux")
            build_linux
            ;;
        "all")
            build_all
            ;;
        *)
            echo -e "${RED}❌ 不支持的平台: $PLATFORM${NC}"
            echo ""
            show_help
            exit 1
            ;;
    esac
    
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        echo ""
        echo -e "${GREEN}🎉 构建流程完成！${NC}"
    else
        echo ""
        echo -e "${RED}❌ 构建失败${NC}"
    fi
    
    return $exit_code
}

# 执行主函数
main
exit $?
