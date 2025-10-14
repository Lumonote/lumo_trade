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
    echo "  macos          - 构建macOS版本 (本地构建)"
    echo "  windows        - 构建Windows版本 (需要Windows环境)"
    echo "  windows-docker - 使用Docker构建Windows版本"
    echo "  windows-wine   - 使用Wine构建Windows版本"
    echo "  linux          - 构建Linux版本"
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
    
    # 查找可用的Python版本
    PYTHON_CMD=""
    for py in python3.11 python3 python; do
        if command -v "$py" &> /dev/null; then
            VERSION=$($py --version 2>&1)
            if [[ $VERSION == *"3.11"* ]]; then
                PYTHON_CMD="$py"
                break
            elif [[ $VERSION == *"3."* ]] && [ -z "$PYTHON_CMD" ]; then
                PYTHON_CMD="$py"
            fi
        fi
    done
    
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${RED}❌ 未找到Python 3.x${NC}"
        echo -e "${YELLOW}💡 请安装Python 3.11或更高版本${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}🐍 使用Python版本: $($PYTHON_CMD --version)${NC}"
    echo -e "${GREEN}✅ Python环境检查完成${NC}"
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
            echo -e "${PURPLE}🎨 使用现代化GUI版本${NC}"
            ;;
        "console")
            echo -e "${PURPLE}⌨️  使用控制台版本${NC}"
            ;;
    esac
    
    echo -e "${GREEN}✅ 资源文件准备完成${NC}"
}

# macOS构建
build_macos() {
    if [ "$CURRENT_OS" != "macos" ] && [ "$USE_DOCKER" = false ]; then
        echo -e "${RED}❌ macOS构建需要在macOS系统上运行${NC}"
        echo -e "${YELLOW}💡 或者使用 --docker 选项进行交叉编译${NC}"
        return 1
    fi

    echo -e "${PURPLE}🎨🍎 开始打包现代化GUI macOS 版本...${NC}"
    echo "=========================================="

    cd "$PROJECT_ROOT"

    # 验证价格断层修复代码存在
    echo -e "${BLUE}🔍 验证价格断层修复代码...${NC}"
    if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" examples/prediction_batch_example.py; then
        echo -e "${GREEN}✅ 价格断层修复代码已包含${NC}"
    else
        echo -e "${RED}❌ 警告：未找到价格断层修复代码${NC}"
        echo -e "${YELLOW}   请确认 examples/prediction_batch_example.py 包含修复代码${NC}"
        read -p "是否继续打包？(y/n): " CONTINUE
        if [ "$CONTINUE" != "y" ]; then
            return 1
        fi
    fi

    # 检查并导入Python检测器
    echo -e "${BLUE}🔍 检查Python环境...${NC}"
    $PYTHON_CMD -c "import sys; sys.path.append('tools'); from python_detector import get_python_detector, verify_python_environment; detector = get_python_detector(); print(f'检测到Python命令: {detector.get_command()}'); verify_python_environment()"
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Python环境检查失败${NC}"
        return 1
    fi

    # 运行PyInstaller
    echo -e "${BLUE}🔧 执行PyInstaller构建...${NC}"
    $PYTHON_CMD -m PyInstaller \
        --clean \
        --noconfirm \
        packaging/scripts/kronos_macos.spec

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ 现代化GUI macOS版本创建成功！${NC}"

        # 验证打包结果
        echo -e "${BLUE}🔍 验证打包结果...${NC}"

        # 检查examples目录是否被打包
        if [ -d "dist/Kronos/examples" ]; then
            echo -e "${GREEN}✅ examples/ 目录已打包到 dist/Kronos/examples/${NC}"

            if [ -f "dist/Kronos/examples/prediction_batch_example.py" ]; then
                echo -e "${GREEN}✅ prediction_batch_example.py 已包含${NC}"

                # 验证修复代码
                if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" dist/Kronos/examples/prediction_batch_example.py; then
                    echo -e "${GREEN}✅ 修复代码已正确包含到打包文件中${NC}"
                else
                    echo -e "${YELLOW}⚠️  警告：打包的文件中不包含修复代码${NC}"
                fi
            else
                echo -e "${YELLOW}⚠️  警告：prediction_batch_example.py 未找到${NC}"
            fi
        elif [ -d "dist/Kronos.app/Contents/Resources/examples" ]; then
            echo -e "${GREEN}✅ examples/ 目录在 .app/Contents/Resources/ 中${NC}"

            if [ -f "dist/Kronos.app/Contents/Resources/examples/prediction_batch_example.py" ]; then
                echo -e "${GREEN}✅ prediction_batch_example.py 已包含到.app包${NC}"

                # 验证修复代码
                if grep -q "关键：修正后必须重新创建pred_overlap和pred_future" "dist/Kronos.app/Contents/Resources/examples/prediction_batch_example.py"; then
                    echo -e "${GREEN}✅ 修复代码已正确包含到.app包中${NC}"
                else
                    echo -e "${YELLOW}⚠️  警告：.app包中的文件不包含修复代码${NC}"
                fi
            else
                echo -e "${YELLOW}⚠️  警告：.app包中未找到 prediction_batch_example.py${NC}"
            fi
        else
            echo -e "${YELLOW}⚠️  警告：examples/ 目录未被打包${NC}"
        fi

        # 测试应用启动
        echo -e "${BLUE}🧪 测试应用启动...${NC}"
        if timeout 10s open dist/Kronos.app --args --test 2>/dev/null; then
            echo "  (应用可以启动)"
        else
            echo "  (启动测试超时，但构建成功)"
        fi
        
        # 创建应用包
        if [ -d "dist/Kronos.app" ]; then
            echo -e "${GREEN}✅ 现代化GUI macOS应用包创建成功！${NC}"
            
            # 创建DMG文件（统一版本命名）
            BUILD_DIR="$PROJECT_ROOT/packaging/builds"
            mkdir -p "$BUILD_DIR"

            # 读取版本配置并生成文件名
            load_version_config
            TIMESTAMP=$(date "+%Y%m%d_%H%M%S")
            PLATFORM_NAME="macOS"
            ARTIFACT_NAME="$ARTIFACT_TEMPLATE"
            ARTIFACT_NAME="${ARTIFACT_NAME/\{version\}/$VERSION}"
            ARTIFACT_NAME="${ARTIFACT_NAME/\{platform\}/$PLATFORM_NAME}"
            ARTIFACT_NAME="${ARTIFACT_NAME/\{timestamp\}/$TIMESTAMP}"
            DMG_FILE="$BUILD_DIR/${ARTIFACT_NAME}.dmg"
            if command -v hdiutil &> /dev/null; then
                hdiutil create -srcfolder "dist/Kronos.app" -volname "Kronos" "$DMG_FILE" 2>/dev/null || {
                    echo -e "${YELLOW}⚠️  DMG创建失败，但应用包构建成功${NC}"
                }
                if [ -f "$DMG_FILE" ]; then
                    echo "created: $DMG_FILE"
                    echo -e "${PURPLE}💿 创建了DMG安装包: $DMG_FILE${NC}"
                fi
            fi
            
            # 显示应用包大小
            APP_SIZE=$(du -sh "dist/Kronos.app" | cut -f1)
            echo -e "${CYAN}📏 应用包大小: $APP_SIZE${NC}"
        fi
        
        echo ""
        echo -e "${GREEN}🎯 使用说明:${NC}"
        echo "1. 双击 Kronos.app 启动应用"
        echo "2. 或者从命令行: open dist/Kronos.app"
        if [ -f "$DMG_FILE" ]; then
            echo "3. 分发给用户: $DMG_FILE"
        fi
        
        return 0
    else
        echo -e "${RED}❌ macOS构建失败${NC}"
        return 1
    fi
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
    OUTPUT_DIR="packaging/builds/windows-wine"
    
    # 构建Wine Docker镜像
    echo -e "${BLUE}🔨 构建Wine Docker镜像...${NC}"
    docker build -f packaging/docker/Dockerfile.windows-wine -t $IMAGE_NAME .
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Wine镜像构建失败${NC}"
        return 1
    fi
    
    # 创建输出目录
    mkdir -p "$OUTPUT_DIR"
    
    # 运行Wine构建
    echo -e "${BLUE}🚀 运行Wine构建...${NC}"
    docker run --name $CONTAINER_NAME --rm $IMAGE_NAME
    
    if [ $? -eq 0 ]; then
        # 从容器复制结果
        docker cp $CONTAINER_NAME:/kronos/dist/. "$OUTPUT_DIR/" || true
        echo -e "${GREEN}✅ Windows Wine构建成功！${NC}"
        echo -e "${CYAN}📁 构建结果: $OUTPUT_DIR${NC}"
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
        echo -e "${YELLOW}💡 请使用 windows-docker 或 windows-wine 选项${NC}"
        return 1
    fi
    
    echo -e "${PURPLE}🪟 开始Windows本地构建...${NC}"
    echo "=========================================="
    
    cd "$PROJECT_ROOT"
    
    $PYTHON_CMD -m PyInstaller \
        --clean \
        --noconfirm \
        packaging/scripts/kronos_windows.spec
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Windows本地构建成功！${NC}"
        return 0
    else
        echo -e "${RED}❌ Windows本地构建失败${NC}"
        return 1
    fi
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
    
    # TODO: 实现Linux构建逻辑
    echo -e "${YELLOW}⚠️  Linux构建功能正在开发中${NC}"
    return 1
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