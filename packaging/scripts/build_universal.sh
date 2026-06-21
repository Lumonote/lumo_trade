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
    echo "  macos-dmg      - 仅基于已构建的 .app 重新生成macOS DMG"
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
    echo "  $0 macos-dmg                # 仅重新生成DMG"
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

# 使用 hdiutil 生成 macOS DMG（不走 Tauri 自带 bundle_dmg.sh 的 Finder AppleScript，
# 规避 detach 卡死 / 自动化(TCC)权限导致的 DMG 打包失败）
detach_macos_volume() {
    local volume_name="$1"
    local mount_path="/Volumes/$volume_name"

    if [ ! -e "$mount_path" ]; then
        return 0
    fi

    echo -e "${YELLOW}⚠️  发现残留卷 $mount_path，先卸载...${NC}"
    hdiutil detach "$mount_path" -force >/dev/null 2>&1 \
        || diskutil unmount force "$mount_path" >/dev/null 2>&1 \
        || true
    sleep 2
}

# 对 .app 签名：有 Developer ID 身份则做可公证的正式签名（inside-out + hardened runtime），
# 否则回退 ad-hoc。⚠️ ad-hoc 仅能消除「已损坏」，无法通过 Gatekeeper——分发到别的 Mac
# （带 com.apple.quarantine）仍会被拦截，根因即在此。彻底免提示必须 Developer ID + 公证。
codesign_macos_app() {
    local app_path="$1"
    command -v codesign &>/dev/null || return 0

    if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
        echo -e "${BLUE}🔏 使用 Developer ID 签名（hardened runtime，可公证）: $APPLE_SIGNING_IDENTITY${NC}"
        local entitlements="$PROJECT_ROOT/packaging/macos/entitlements.plist"
        local ent_arg=()
        [ -f "$entitlements" ] && ent_arg=(--entitlements "$entitlements")
        # inside-out：先签内嵌 Mach-O（dylib/so/后端 exe），最后签外层 .app
        find "$app_path/Contents/Resources" -type f \( -name "*.dylib" -o -name "*.so" \) -print0 2>/dev/null \
            | xargs -0 -I {} codesign --force --timestamp --options runtime --sign "$APPLE_SIGNING_IDENTITY" {} >/dev/null 2>&1 || true
        local backend="$app_path/Contents/Resources/packaging/backend/kronos_webui_backend/kronos_webui_backend"
        [ -f "$backend" ] && codesign --force --timestamp --options runtime "${ent_arg[@]}" --sign "$APPLE_SIGNING_IDENTITY" "$backend" >/dev/null 2>&1 || true
        if codesign --force --timestamp --options runtime "${ent_arg[@]}" --sign "$APPLE_SIGNING_IDENTITY" "$app_path" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ Developer ID 签名完成${NC}"
        else
            echo -e "${YELLOW}⚠️  Developer ID 签名失败，回退 ad-hoc${NC}"
            codesign --force --deep --sign - --timestamp=none "$app_path" >/dev/null 2>&1 || true
        fi
    else
        echo -e "${BLUE}🔏 对 .app 进行 ad-hoc 签名（未配置 APPLE_SIGNING_IDENTITY）...${NC}"
        if codesign --force --deep --sign - --timestamp=none "$app_path" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ ad-hoc 签名完成${NC}"
            echo -e "${YELLOW}ℹ️  ad-hoc 无法通过 Gatekeeper：拷到别的 Mac 仍会被拦截（这就是「拖进去却看不到」的根因）。${NC}"
            echo -e "${YELLOW}   收件人请按 DMG 内「首次打开必读.txt」放行；彻底解决请设 APPLE_SIGNING_IDENTITY 走 Developer ID + 公证。${NC}"
        else
            echo -e "${YELLOW}⚠️  ad-hoc 签名失败（不阻塞）${NC}"
        fi
    fi
}

# 配置了公证凭证则对 DMG 公证 + 装订（staple），让收件人双击即可打开、无任何拦截。
notarize_macos_dmg() {
    local dmg="$1"
    command -v xcrun &>/dev/null || return 0
    if [ -n "${APPLE_NOTARY_PROFILE:-}" ]; then
        echo -e "${BLUE}🍎 提交公证（keychain-profile: $APPLE_NOTARY_PROFILE）...${NC}"
        if xcrun notarytool submit "$dmg" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait; then
            xcrun stapler staple "$dmg" && echo -e "${GREEN}✅ 公证并装订完成${NC}"
        else
            echo -e "${YELLOW}⚠️  公证失败，请检查凭证/日志${NC}"
        fi
    elif [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
        echo -e "${BLUE}🍎 提交公证（Apple ID: $APPLE_ID）...${NC}"
        if xcrun notarytool submit "$dmg" --apple-id "$APPLE_ID" --password "$APPLE_PASSWORD" --team-id "$APPLE_TEAM_ID" --wait; then
            xcrun stapler staple "$dmg" && echo -e "${GREEN}✅ 公证并装订完成${NC}"
        else
            echo -e "${YELLOW}⚠️  公证失败，请检查凭证/日志${NC}"
        fi
    else
        echo -e "${YELLOW}ℹ️  未配置公证凭证（APPLE_NOTARY_PROFILE 或 APPLE_ID+APPLE_PASSWORD+APPLE_TEAM_ID），跳过公证。${NC}"
    fi
}

# 把「首次打开必读」说明与「修复并打开」助手写入 DMG，帮收件人绕过 Gatekeeper 拦截。
write_dmg_install_helpers() {
    local staging="$1"
    local app_name="$2"

    cat > "$staging/首次打开必读.txt" <<EOF
【Lumo Trade · 首次打开说明（macOS）】

若在别的 Mac 上提示「已损坏 / 无法验证开发者 / 来自身份不明的开发者」，
这不是软件损坏，而是 macOS Gatekeeper 的安全拦截（本应用未做 Apple 公证）。
请任选一种方式打开：

① 最省事：把「${app_name}.app」拖到右侧「Applications（应用程序）」完成安装，然后
   · macOS 13/14：在「应用程序」里按住 Control 键点按它 → 选「打开」→ 再点「打开」。
   · macOS 15(Sequoia)+：先双击一次，再打开「系统设置 → 隐私与安全性」，
     在底部找到被拦截的提示，点「仍要打开」。

② 一劳永逸（用「终端」）：打开「终端」，粘贴并回车——
       xattr -dr com.apple.quarantine "/Applications/${app_name}.app"
   之后即可正常双击。

③ 双击本目录下的「修复并打开.command」，按提示自动安装并放行。

如仍打不开，请把系统弹窗的提示文字截图反馈。
EOF

    cat > "$staging/修复并打开.command" <<EOF
#!/bin/bash
# 自动安装到「应用程序」并去除隔离属性，绕过「已损坏 / 无法验证开发者」拦截
APP_NAME="${app_name}"
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
DST="/Applications/\${APP_NAME}.app"
if [ ! -d "\$DST" ] && [ -d "\$HERE/\${APP_NAME}.app" ]; then
  echo "正在安装到 应用程序 ..."
  cp -R "\$HERE/\${APP_NAME}.app" /Applications/ 2>/dev/null || echo "复制失败：请先手动把 App 拖进「应用程序」。"
fi
if [ -d "\$DST" ]; then
  echo "正在去除隔离属性 ..."
  xattr -dr com.apple.quarantine "\$DST" 2>/dev/null || true
  echo "完成，正在打开 ..."
  open "\$DST"
else
  echo "未找到 \${APP_NAME}.app，请先把它拖进「应用程序」。"
fi
echo
read -n1 -s -r -p "按任意键关闭本窗口..."
EOF
    chmod +x "$staging/修复并打开.command"
}

create_macos_dmg() {
    local bundle_dir="$PROJECT_ROOT/src-tauri/target/release/bundle"
    local macos_dir="$bundle_dir/macos"
    local dmg_dir="$bundle_dir/dmg"

    local conf="$PROJECT_ROOT/src-tauri/tauri.conf.json"

    # 优先按 tauri.conf.json 的 productName 定位 .app（权威来源，避免改名后残留旧 .app
    # 被「find | head -1」错选）；productName 缺失或对应 .app 不存在时再回退 find。
    local product=""
    if [ -n "$PYTHON_CMD" ] && [ -f "$conf" ]; then
        product="$("$PYTHON_CMD" -c "import json; print(json.load(open(r'$conf')).get('productName',''))" 2>/dev/null || echo '')"
    fi
    local app_path=""
    if [ -n "$product" ] && [ -d "$macos_dir/$product.app" ]; then
        app_path="$macos_dir/$product.app"
    else
        app_path="$(find "$macos_dir" -maxdepth 1 -name '*.app' 2>/dev/null | head -1)"
    fi
    if [ -z "$app_path" ]; then
        echo -e "${RED}❌ 未找到 .app，无法生成 DMG: $macos_dir${NC}"
        return 1
    fi
    local app_name
    app_name="$(basename "$app_path" .app)"

    # 签名：有 Developer ID 走可公证的正式签名，否则 ad-hoc 回退（详见 codesign_macos_app）
    codesign_macos_app "$app_path"

    # 版本号与 tauri.conf.json 保持一致
    local version="1.0.0"
    if [ -n "$PYTHON_CMD" ] && [ -f "$conf" ]; then
        version="$("$PYTHON_CMD" -c "import json; print(json.load(open(r'$conf')).get('version','1.0.0'))" 2>/dev/null || echo '1.0.0')"
    fi

    # 架构后缀，与 Tauri 命名一致（x86_64->x64, arm64->aarch64）
    local arch_suffix
    case "$(uname -m)" in
        arm64|aarch64) arch_suffix="aarch64" ;;
        *)             arch_suffix="x64" ;;
    esac

    mkdir -p "$dmg_dir"
    local dmg_out="$dmg_dir/${app_name}_${version}_${arch_suffix}.dmg"

    echo -e "${BLUE}📦 使用 hdiutil 生成 DMG（跳过 Finder AppleScript）...${NC}"

    local staging
    staging="$(mktemp -d "${TMPDIR:-/tmp}/kronos_dmg.XXXXXX")"
    if [ -z "$staging" ] || [ ! -d "$staging" ]; then
        echo -e "${RED}❌ 创建临时目录失败${NC}"
        return 1
    fi
    # 任何路径退出都清理临时目录
    trap 'rm -rf "$staging"; trap - RETURN' RETURN

    cp -R "$app_path" "$staging/"
    ln -s /Applications "$staging/Applications"   # 拖拽安装到 Applications
    write_dmg_install_helpers "$staging" "$app_name"   # 「首次打开必读.txt」+「修复并打开.command」
    # 双保险阻止 Spotlight 索引 DMG 卷，避免 detach 阶段被 mdworker 抢占。
    : > "$staging/.metadata_never_index"

    detach_macos_volume "$app_name"

    rm -f "$dmg_out"
    # "资源忙" 多为瞬时（Spotlight/索引/杀软扫描占用临时设备），重试即可恢复
    local attempt
    for attempt in 1 2 3; do
        if hdiutil create \
            -volname "$app_name" \
            -srcfolder "$staging" \
            -ov \
            -format UDZO \
            -fs HFS+ \
            -nospotlight \
            -anyowners \
            -srcowners off \
            "$dmg_out"; then
            echo -e "${GREEN}✅ DMG 生成完成: $dmg_out${NC}"
            notarize_macos_dmg "$dmg_out"   # 配置了公证凭证才执行，否则打印提示
            return 0
        fi
        echo -e "${YELLOW}⚠️  hdiutil 失败（资源忙?），第 ${attempt}/3 次，5s 后重试...${NC}"
        detach_macos_volume "$app_name"
        rm -f "$dmg_out"
        sync
        sleep 5
    done
    echo -e "${RED}❌ DMG 生成失败（已重试 3 次）${NC}"
    echo -e "${YELLOW}💡 如果在沙箱/CI中运行，请在普通 macOS 终端重试：hdiutil 需要挂载磁盘映像权限。${NC}"
    return 1
}

build_tauri_desktop() {
    local platform_name="$1"

    echo -e "${PURPLE}🖥️  开始Tauri桌面构建 ($platform_name)...${NC}"
    echo "=========================================="

    check_tauri_environment || return 1
    build_bundled_backend || return 1
    cd "$PROJECT_ROOT"

    if [ "$platform_name" = "macOS" ]; then
        # macOS: 仅用 Tauri 生成 .app；DMG 改用 hdiutil 生成，
        # 规避 Tauri 自带 bundle_dmg.sh 的 Finder AppleScript（detach 卡死 / 自动化权限问题）
        # 先清理上次构建残留的 .app/.dmg：改名(productName)后旧产物会与新产物并存，
        # 导致后续「find *.app | head -1」取到旧名、DMG 命名/拷贝拿错。
        rm -rf "$PROJECT_ROOT/src-tauri/target/release/bundle/macos/"*.app 2>/dev/null || true
        rm -f "$PROJECT_ROOT/src-tauri/target/release/bundle/dmg/"*.dmg 2>/dev/null || true
        if ! npm run desktop:build -- --bundles app; then
            echo -e "${RED}❌ Tauri .app 构建失败${NC}"
            return 1
        fi
        create_macos_dmg || return 1
    else
        if ! npm run desktop:build; then
            echo -e "${RED}❌ Tauri桌面构建失败${NC}"
            return 1
        fi
    fi

    copy_tauri_artifacts
    echo -e "${GREEN}✅ Tauri桌面构建成功！${NC}"
    return 0
}

# macOS构建
build_macos() {
    if [ "$CURRENT_OS" != "macos" ]; then
        echo -e "${RED}❌ Tauri macOS构建需要在macOS系统上运行${NC}"
        return 1
    fi

    build_tauri_desktop "macOS"
}

build_macos_dmg_only() {
    if [ "$CURRENT_OS" != "macos" ]; then
        echo -e "${RED}❌ DMG生成需要在macOS系统上运行${NC}"
        return 1
    fi

    if ! command -v hdiutil &> /dev/null; then
        echo -e "${RED}❌ 未找到 hdiutil，无法生成 DMG${NC}"
        return 1
    fi

    create_macos_dmg || return 1
    copy_tauri_artifacts
    return 0
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
    if [ "$USE_DOCKER" = "false" ] || [ "$PLATFORM" = "macos" ] || [ "$PLATFORM" = "macos-dmg" ] || ([ "$PLATFORM" = "windows" ] && [ "$CURRENT_OS" = "windows" ]); then
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
        "macos-dmg")
            build_macos_dmg_only
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
