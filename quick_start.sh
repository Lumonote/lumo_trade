#!/bin/bash
# Kronos 快速启动脚本

# 检查命令行参数 - 如果传入了选项，直接执行而不显示菜单
AUTO_CHOICE=""
if [ $# -gt 0 ]; then
    AUTO_CHOICE="$1"
fi

# 设置环境变量 - 适配打包环境
export TERM=${TERM:-xterm-256color}
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检测应用包环境并设置用户数据目录



setup_user_directories() {
    # 获取当前脚本路径
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # 检测是否在应用包内
    if [[ "$script_dir" =~ \.app/Contents/ ]]; then
        # 在应用包内，使用用户主目录
        export KRONOS_USER_DIR="$HOME/Documents/Kronos"
        export KRONOS_IS_APP_BUNDLE=true
        echo -e "${BLUE}APP: 检测到应用包环境，数据将保存到: $KRONOS_USER_DIR${NC}"
    else
        # 在开发环境，使用当前目录
        export KRONOS_USER_DIR="$script_dir"
        export KRONOS_IS_APP_BUNDLE=false
    fi
    
    # 创建用户数据目录结构
    mkdir -p "$KRONOS_USER_DIR"/{data,logs,results,models,config}
    
    # 如果在应用包内，复制配置文件到用户目录（如果不存在）
    if [ "$KRONOS_IS_APP_BUNDLE" = "true" ]; then
        local app_config_dir="$script_dir/config"
        if [ -d "$app_config_dir" ] && [ ! -f "$KRONOS_USER_DIR/config/tushare_config.json" ]; then
            cp -r "$app_config_dir"/* "$KRONOS_USER_DIR/config/" 2>/dev/null || true
        fi
    fi
    
    # 设置工作目录别名
    export KRONOS_DATA_DIR="$KRONOS_USER_DIR/data"
    export KRONOS_LOGS_DIR="$KRONOS_USER_DIR/logs"
    export KRONOS_RESULTS_DIR="$KRONOS_USER_DIR/results"
    export KRONOS_MODELS_DIR="$KRONOS_USER_DIR/models"
    export KRONOS_CONFIG_DIR="$KRONOS_USER_DIR/config"
}

# 初始化用户目录
setup_user_directories

# 智能检测Python - 动态检测而非硬编码路径
detect_python() {
    local best_python=""
    local best_version=""
    
    # 使用which/where命令动态查找所有Python安装
    local search_commands=()
    
    if command -v which >/dev/null 2>&1; then
        # Unix/Linux/macOS系统
        search_commands+=("which -a python3.11 2>/dev/null")
        search_commands+=("which -a python3 2>/dev/null") 
        search_commands+=("which -a python 2>/dev/null")
    fi
    
    if command -v where >/dev/null 2>&1; then
        # Windows系统 (cmd/powershell)
        search_commands+=("where python3.11.exe 2>/dev/null")
        search_commands+=("where python3.exe 2>/dev/null")
        search_commands+=("where python.exe 2>/dev/null")
    fi
    
    # 添加常见的命令名检测
    local python_names=("python3.11" "python3" "python")
    
    # 优先检查环境变量中的Python
    if [ -n "$PYTHON" ] && command -v "$PYTHON" >/dev/null 2>&1; then
        python_names=("$PYTHON" "${python_names[@]}")
    fi
    
    # 检测所有可能的Python安装
    for py_name in "${python_names[@]}"; do
        if command -v "$py_name" >/dev/null 2>&1; then
            local py_path=$(command -v "$py_name")
            
            # 获取版本信息
            local version_output=$($py_path --version 2>&1)
            local version=$(echo "$version_output" | grep -o "3\.[0-9]\+\.[0-9]\+" | head -1)
            
            if [ -n "$version" ]; then
                # 优先选择3.11.x版本
                if [[ "$version" =~ ^3\.11\. ]]; then
                    echo "$py_path"
                    return 0
                elif [[ "$version" =~ ^3\. ]]; then
                    # 记录其他Python 3.x版本作为备选
                    if [ -z "$best_python" ] || [[ "$version" > "$best_version" ]]; then
                        best_python="$py_path"
                        best_version="$version"
                    fi
                fi
            fi
        fi
    done
    
    # 通过系统特定命令查找更多Python安装
    for cmd in "${search_commands[@]}"; do
        if [ -n "$cmd" ]; then
            while IFS= read -r py_path; do
                if [ -n "$py_path" ] && [ -x "$py_path" ]; then
                    local version_output=$($py_path --version 2>&1)
                    local version=$(echo "$version_output" | grep -o "3\.[0-9]\+\.[0-9]\+" | head -1)
                    
                    if [[ "$version" =~ ^3\.11\. ]]; then
                        echo "$py_path"
                        return 0
                    elif [[ "$version" =~ ^3\. ]]; then
                        if [ -z "$best_python" ] || [[ "$version" > "$best_version" ]]; then
                            best_python="$py_path"
                            best_version="$version"
                        fi
                    fi
                fi
            done < <(eval "$cmd")
        fi
    done
    
    # 返回找到的最佳Python版本
    if [ -n "$best_python" ]; then
        echo "$best_python"
        return 0
    fi
    
    return 1
}

# 设置Python路径
PYTHON_CMD=$(detect_python)
if [ -z "$PYTHON_CMD" ]; then
    echo "ERROR: 未找到合适的Python环境"
    echo "建议安装Python 3.11.13"
    exit 1
fi

export PYTHON="$PYTHON_CMD"

# 设置错误处理
set -e  # 遇到错误时退出
trap cleanup_on_error ERR  # 错误时执行清理

# 清理函数
cleanup_on_error() {
    echo -e "${RED}ERROR: 脚本执行过程中发生错误${NC}"
    echo -e "${YELLOW}TIP: 建议检查：${NC}"
    echo -e "  1. 网络连接是否正常"
    echo -e "  2. Python 环境是否正确安装"
    echo -e "  3. 磁盘空间是否充足"
    echo -e "  4. 权限是否足够"
    echo
    read -p "按任意键退出..." -n1 -s
    exit 1
}

# 安全执行Python脚本的函数 - 自动处理应用包环境的工作目录问题
safe_execute_python() {
    local python_script="$1"
    local description="$2"
    shift 2  # 移除前两个参数，剩下的作为脚本参数
    local script_args="$@"
    
    echo -e "${BLUE}正在执行: $description${NC}"
    
    # 保存当前目录
    local original_dir=$(pwd)
    
    # 获取脚本实际位置，确保在正确目录下执行
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # 在应用包环境中需要切换到正确的工作目录
    if [ "$KRONOS_IS_APP_BUNDLE" = "true" ]; then
        # 在应用包内，需要找到实际的项目根目录
        if [[ "$script_dir" =~ \.app/Contents/ ]]; then
            # 从 .app/Contents/Resources 或类似路径中找到项目根目录
            local app_root=$(echo "$script_dir" | sed 's|\.app/Contents.*|.app/Contents/Resources|')
            if [ -d "$app_root" ] && [ -f "$app_root/$python_script" ]; then
                local project_root="$app_root"
            else
                # 尝试其他可能的路径
                local project_root="$script_dir"
            fi
        else
            local project_root="$script_dir"
        fi
        
        echo -e "${BLUE}DIR: 应用包环境：切换到项目根目录 $project_root${NC}"
        cd "$project_root"
    fi
    
    # 执行Python脚本
    local exit_code=0
    if [ -n "$script_args" ]; then
        # 显式传递环境变量给Python进程
        env KRONOS_DATA_DIR="$KRONOS_DATA_DIR" \
            KRONOS_USER_DIR="$KRONOS_USER_DIR" \
            KRONOS_RESULTS_DIR="$KRONOS_RESULTS_DIR" \
            KRONOS_MODELS_DIR="$KRONOS_MODELS_DIR" \
            KRONOS_CONFIG_DIR="$KRONOS_CONFIG_DIR" \
            KRONOS_IS_APP_BUNDLE="$KRONOS_IS_APP_BUNDLE" \
            PYTHON="$PYTHON_CMD" \
            "$PYTHON_CMD" "$python_script" $script_args
        exit_code=$?
    else
        # 显式传递环境变量给Python进程
        env KRONOS_DATA_DIR="$KRONOS_DATA_DIR" \
            KRONOS_USER_DIR="$KRONOS_USER_DIR" \
            KRONOS_RESULTS_DIR="$KRONOS_RESULTS_DIR" \
            KRONOS_MODELS_DIR="$KRONOS_MODELS_DIR" \
            KRONOS_CONFIG_DIR="$KRONOS_CONFIG_DIR" \
            KRONOS_IS_APP_BUNDLE="$KRONOS_IS_APP_BUNDLE" \
            PYTHON="$PYTHON_CMD" \
            "$PYTHON_CMD" "$python_script"
        exit_code=$?
    fi
    
    # 恢复原目录
    cd "$original_dir"
    
    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}OK: $description 完成${NC}"
        return 0
    else
        echo -e "${RED}ERROR: $description 失败${NC}"
        return $exit_code
    fi
}

# 安全执行命令的函数
safe_execute() {
    local command="$1"
    local description="$2"
    local allow_fail="${3:-false}"
    
    echo -e "${BLUE}正在执行: $description${NC}"
    
    if [[ "$allow_fail" == "true" ]]; then
        if ! eval "$command" 2>/dev/null; then
            echo -e "${YELLOW}WARN:  $description 失败，但继续执行${NC}"
            return 1
        fi
    else
        if ! eval "$command"; then
            echo -e "${RED}ERROR: $description 失败${NC}"
            return 1
        fi
    fi
    
    echo -e "${GREEN}OK: $description 完成${NC}"
    return 0
}

# 获取 Python 包的版本号，若未安装则返回空
get_python_package_version() {
    local package="$1"
    local version
    version=$($PYTHON_CMD - <<PY 2>/dev/null
try:
    from importlib import metadata
except ImportError:  # pragma: no cover - 仅为兼容老版本
    import importlib_metadata as metadata

package = "$package"
try:
    print(metadata.version(package))
except Exception:
    pass
PY
)
    echo "$version"
}

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 自动依赖检查和安装函数
auto_install_dependencies() {
    echo -e "${GREEN}START: 开始自动安装系统依赖...${NC}"
    
    # 暂时禁用 set -e 以便手动处理错误
    set +e
    
    local install_failed=false
    
    echo -e "${BLUE}STATUS: 步骤 1/6: 配置 Python 环境和清华镜像源...${NC}"
    
    # 检查并安装 pyenv
    if ! command -v pyenv &> /dev/null; then
        echo -e "${YELLOW}ACTION:  正在安装 pyenv...${NC}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS 使用 Homebrew 安装
            if command -v brew &> /dev/null; then
                if safe_execute "brew install pyenv" "pyenv安装" true; then
                    echo -e "${GREEN}OK: pyenv 安装完成！${NC}"
                    # 添加到 shell 配置
                    echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
                    echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
                    echo 'eval "$(pyenv init -)"' >> ~/.zshrc
                    export PYENV_ROOT="$HOME/.pyenv"
                    export PATH="$PYENV_ROOT/bin:$PATH"
                    eval "$(pyenv init -)"
                else
                    echo -e "${RED}ERROR: pyenv 安装失败${NC}"
                    install_failed=true
                fi
            else
                echo -e "${RED}ERROR: 未找到 Homebrew，请先安装 Homebrew${NC}"
                install_failed=true
            fi
        else
            # Linux 使用 curl 安装
            if safe_execute "curl https://pyenv.run | bash" "pyenv安装" true; then
                echo -e "${GREEN}OK: pyenv 安装完成！${NC}"
                # 添加到 shell 配置
                echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
                echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
                echo 'eval "$(pyenv init -)"' >> ~/.bashrc
                export PYENV_ROOT="$HOME/.pyenv"
                export PATH="$PYENV_ROOT/bin:$PATH"
                eval "$(pyenv init -)"
            else
                echo -e "${RED}ERROR: pyenv 安装失败${NC}"
                install_failed=true
            fi
        fi
    else
        echo -e "${GREEN}OK: pyenv 已安装${NC}"
    fi
    
    if [ "$install_failed" = true ]; then
        echo -e "${RED}ERROR: 依赖安装失败，请检查网络连接和系统权限${NC}"
        set -e
        return 1
    fi
    
    # 检查 Python 3.11.13 是否已安装
    echo -e "${BLUE}STATUS: 步骤 2/6: 安装 Python 3.11.13...${NC}"
    PYTHON_VERSION="3.11.13"
    if ! pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
        echo -e "${YELLOW}ACTION:  正在安装 Python ${PYTHON_VERSION}，这可能需要几分钟...${NC}"
        if safe_execute "pyenv install ${PYTHON_VERSION}" "Python ${PYTHON_VERSION} 安装" true; then
            echo -e "${GREEN}OK: Python ${PYTHON_VERSION} 安装完成！${NC}"
        else
            echo -e "${RED}ERROR: Python ${PYTHON_VERSION} 安装失败${NC}"
            install_failed=true
        fi
    else
        echo -e "${GREEN}OK: Python ${PYTHON_VERSION} 已安装${NC}"
    fi
    
    # 设置全局 Python 版本
    echo -e "${BLUE}STATUS: 步骤 3/6: 配置 Python 环境...${NC}"
    if safe_execute "pyenv global ${PYTHON_VERSION}" "设置全局Python版本" true; then
        echo -e "${GREEN}OK: Python 版本设置完成！${NC}"
    else
        echo -e "${RED}ERROR: Python 版本设置失败${NC}"
        install_failed=true
    fi
    
    # 刷新环境变量
    eval "$(pyenv init -)"
    
    # 配置 pip 清华镜像源
    echo -e "${YELLOW}ACTION:  正在配置 pip 清华大学镜像源...${NC}"
    PIP_CONFIG_DIR="$HOME/.pip"
    mkdir -p "$PIP_CONFIG_DIR"
    
    cat > "$PIP_CONFIG_DIR/pip.conf" << EOF
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple/
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
    
    if [ -f "$PIP_CONFIG_DIR/pip.conf" ]; then
        echo -e "${GREEN}OK: pip 清华镜像源配置完成！${NC}"
    else
        echo -e "${YELLOW}WARN:  pip 镜像源配置失败，使用默认源${NC}"
    fi
    
    # 升级 pip
    echo -e "${YELLOW}ACTION:  正在升级 pip...${NC}"
    if safe_execute "$PYTHON_CMD -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn" "pip升级" true; then
        echo -e "${GREEN}OK: pip 升级完成！${NC}"
    else
        echo -e "${YELLOW}WARN:  pip 升级失败，继续使用当前版本${NC}"
    fi
    
    # 验证 Python 环境
    echo -e "${BLUE}STATUS: 步骤 4/6: 验证 Python 环境...${NC}"
    if command -v $PYTHON_CMD &> /dev/null; then
        CURRENT_PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
        echo -e "${GREEN}OK: 当前 Python 版本: $CURRENT_PYTHON_VERSION${NC}"
    else
        echo -e "${RED}ERROR: Python 环境验证失败${NC}"
        install_failed=true
    fi
    
    # 安装 Python 依赖包
    echo -e "${BLUE}STATUS: 步骤 5/6: 安装 Python 依赖包...${NC}"
    if [ -f "requirements.txt" ]; then
        echo -e "${YELLOW}ACTION:  正在安装依赖包，请稍候...${NC}"
        $PYTHON_CMD -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
        local pip_exit=$?
        if [ $pip_exit -eq 0 ]; then
            echo -e "${GREEN}OK: Python 依赖处理完成（如出现 'Requirement already satisfied' 表示该依赖已存在）${NC}"
        else
            echo -e "${RED}ERROR: Python 依赖包安装失败 (退出代码 $pip_exit)${NC}"
            echo -e "${YELLOW}TIP: 提示: 已配置清华镜像源，如仍失败请检查网络连接${NC}"
            install_failed=true
        fi
    else
        echo -e "${YELLOW}WARN:  未找到 requirements.txt 文件${NC}"
    fi
    
    # 配置 Playwright 浏览器
    echo -e "${BLUE}STATUS: 步骤 6/6: 配置 Playwright 浏览器环境...${NC}"
    local playwright_version=$(get_python_package_version "playwright")
    if [ -n "$playwright_version" ]; then
        echo -e "${YELLOW}SKIP:  Playwright 已安装 (版本 $playwright_version)，跳过包安装${NC}"
    else
        echo -e "${YELLOW}ACTION:  正在安装 Playwright Python 包...${NC}"
        $PYTHON_CMD -m pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
        local pw_exit=$?
        if [ $pw_exit -eq 0 ]; then
            playwright_version=$(get_python_package_version "playwright")
            if [ -n "$playwright_version" ]; then
                echo -e "${GREEN}OK: Playwright 安装完成 (版本 $playwright_version)${NC}"
            else
                echo -e "${GREEN}OK: Playwright 安装完成${NC}"
            fi
        else
            echo -e "${RED}ERROR: Playwright 安装失败 (退出代码 $pw_exit)，爬虫功能可能受限${NC}"
        fi
    fi

    playwright_version=${playwright_version:-$(get_python_package_version "playwright")}
    if [ -n "$playwright_version" ]; then
        echo -e "${YELLOW}ACTION:  正在安装/刷新 Playwright 浏览器 (chromium)...${NC}"
        $PYTHON_CMD -m playwright install chromium
        local chromium_exit=$?
        if [ $chromium_exit -eq 0 ]; then
            echo -e "${GREEN}OK: Chromium 浏览器资源已就绪${NC}"
        else
            echo -e "${YELLOW}WARN:  Chromium 浏览器资源安装失败 (退出代码 $chromium_exit)，可稍后手动运行 'playwright install chromium'${NC}"
        fi
    else
        echo -e "${YELLOW}WARN:  未检测到 Playwright 包，跳过浏览器资源安装${NC}"
    fi
    
    # 重新启用错误处理
    set -e
    
    if [ "$install_failed" = true ]; then
        echo -e "${RED}ERROR: 部分依赖安装失败，请检查错误信息并手动处理${NC}"
        return 1
    else
        echo -e "${GREEN}DONE: 所有依赖安装完成！系统已准备就绪${NC}"
        return 0
    fi
}

# 显示欢迎信息
show_welcome() {
    clear
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}    Kronos 股票预测系统 START:${NC}"
    echo -e "${BLUE}================================${NC}"
    echo -e "${GREEN}欢迎使用 Kronos！请选择您需要的操作：${NC}"
    echo
    echo -e "${YELLOW}PACKAGE: 系统设置${NC}"
    echo "1. 一键安装所有依赖 (Python包 + Playwright浏览器 + 模型)"
    echo "2. 配置数据源 (向导)"
    echo "3. 检查环境状态"
    echo
    echo -e "${YELLOW}DATA: 数据获取${NC}"
    echo "4. 获取股票数据 (Tushare)"
    echo "5. 获取股票数据 (爬虫)"
    echo "6. 批量获取数据及预测K线"
    echo
    echo -e "${YELLOW}LICENSE: 授权管理${NC}"
    echo "7. 检查授权状态"
    echo "8. 激活授权码"
    echo
    echo -e "${YELLOW}PREDICT: 预测功能${NC}"
    echo "9. 运行预测示例"
    echo
    echo -e "${YELLOW}CRAWLER: 爬虫设置${NC}"
    echo "10. 测试爬虫功能"
    echo
    echo -e "${YELLOW}INFO:  帮助与信息${NC}"
    echo "11. 显示使用帮助"
    echo "12. 查看系统状态"
    echo
    echo "13. 退出"
    echo
    echo -e "${BLUE}TIP: 提示: 首次使用请先选择选项1进行一键安装${NC}"
    echo
}

# 显示帮助信息
show_help() {
    clear
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}      Kronos 使用帮助 DOC:${NC}"
    echo -e "${BLUE}================================${NC}"
    echo
    echo -e "${GREEN}START: 快速开始：${NC}"
    echo -e "  1. 运行 ${YELLOW}./quick_start.sh${NC} 或 ${YELLOW}quick_start.bat${NC}"
    echo -e "  2. 选择 ${YELLOW}1${NC} 进行一键安装"
    echo -e "  3. 选择 ${YELLOW}2${NC} 配置数据源（需要Tushare Token）"
    echo -e "  4. 选择 ${YELLOW}7${NC} 运行预测示例"
    echo
    echo -e "${GREEN}DATA: 数据源配置：${NC}"
    echo -e "  - ${YELLOW}Tushare${NC}: 需要注册账号获取Token (https://tushare.pro/)"
    echo -e "  - ${YELLOW}爬虫${NC}: 自动从金融网站获取数据，无需注册"
    echo
    echo -e "${GREEN}CHART: 股票代码格式：${NC}"
    echo -e "  - Tushare: ${YELLOW}000001.SZ${NC} (深交所) 或 ${YELLOW}600000.SH${NC} (上交所)"
    echo -e "  - 爬虫: ${YELLOW}000001${NC} (6位数字)"
    echo
    echo -e "${GREEN}PREDICT: 预测功能：${NC}"
    echo -e "  - 支持OHLCV数据预测"
    echo -e "  - 可调节预测长度和采样参数"
    echo -e "  - 支持批量预测多只股票"
    echo
    echo -e "${GREEN}WEB: Web界面：${NC}"
    echo -e "  - 运行: ${YELLOW}cd webui && python app.py${NC}"
    echo -e "  - 访问: ${YELLOW}http://localhost:7070${NC}"
    echo
    echo -e "${GREEN}DIR: 重要文件：${NC}"
    echo -e "  - ${YELLOW}requirements.txt${NC}: Python依赖"
    echo -e "  - ${YELLOW}config/tushare_config.json${NC}: Tushare配置"
    echo -e "  - ${YELLOW}config/crawler_config.json${NC}: 爬虫配置"
    echo -e "  - ${YELLOW}models/${NC}: 模型文件目录"
    echo -e "  - ${YELLOW}data/${NC}: 数据文件目录"
    echo
    echo -e "${GREEN}STEP 故障排除：${NC}"
    echo -e "  - Python版本需求: 3.11+"
    echo -e "  - 网络问题: 使用国内镜像源"
    echo -e "  - 模型下载失败: 检查网络或手动下载"
    echo -e "  - 爬虫被封: 调整延时或更换User-Agent"
    echo
    echo -e "${GREEN}DOCS: 更多文档：${NC}"
    echo -e "  - README.md: 详细使用说明"
    echo -e "  - QUICK_START_GUIDE.md: 快速上手指南"
    echo -e "  - TROUBLESHOOTING.md: 问题解决指南"
    echo
    read -p "按任意键返回主菜单..." -n1 -s
}

# 查看系统状态
show_system_status() {
    clear
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}       系统状态检查 STATUS:${NC}"
    echo -e "${BLUE}================================${NC}"
    echo
    
    # 检查Python环境
    echo -e "${YELLOW}PYTHON: Python 环境：${NC}"
    if command -v $PYTHON_CMD &> /dev/null; then
        python_version=$($PYTHON_CMD --version 2>&1)
        echo -e "  OK: $python_version"
    else
        echo -e "  ERROR: Python3 未安装"
    fi
    
    # 检查pip
    echo -e "${YELLOW}PACKAGE: 包管理器：${NC}"
    if command -v pip3 &> /dev/null; then
        pip_version=$(pip3 --version 2>&1 | head -1)
        echo -e "  OK: $pip_version"
    else
        echo -e "  ERROR: pip3 未安装"
    fi
    
    # 检查关键Python包
    echo -e "${YELLOW}DOCS: 关键依赖包：${NC}"
    for package in torch pandas numpy matplotlib tqdm; do
        if $PYTHON_CMD -c "import $package" 2>/dev/null; then
            version=$($PYTHON_CMD -c "import $package; print(f'$package {$package.__version__}')" 2>/dev/null)
            echo -e "  OK: $version"
        else
            echo -e "  ERROR: $package 未安装"
        fi
    done
    
    # 检查Playwright
    echo -e "${YELLOW}CRAWLER:  Playwright：${NC}"
    if $PYTHON_CMD -c "import playwright" 2>/dev/null; then
        echo -e "  OK: Playwright 已安装"
        if command -v playwright &> /dev/null; then
            echo -e "  OK: Playwright CLI 可用"
        else
            echo -e "  WARN:  Playwright CLI 不可用"
        fi
    else
        echo -e "  ERROR: Playwright 未安装"
    fi
    
    # 检查ModelScope
    echo -e "${YELLOW}MODELSCOPE: ModelScope：${NC}"
    if $PYTHON_CMD -c "import modelscope" 2>/dev/null; then
        echo -e "  OK: ModelScope 已安装"
    else
        echo -e "  ERROR: ModelScope 未安装"
    fi
    
    # 检查模型文件
    echo -e "${YELLOW}MODEL: 模型文件：${NC}"
    if [ -d "$KRONOS_MODELS_DIR" ]; then
        model_count=$(find "$KRONOS_MODELS_DIR" -name "*.safetensors" -o -name "*.bin" | wc -l)
        if [ $model_count -gt 0 ]; then
            echo -e "  OK: 发现 $model_count 个模型文件"
            for model_dir in "$KRONOS_MODELS_DIR"/*/; do
                if [ -d "$model_dir" ]; then
                    model_name=$(basename "$model_dir")
                    echo -e "    DIR: $model_name"
                fi
            done
        else
            echo -e "  WARN:  未发现模型文件"
        fi
    else
        echo -e "  ERROR: models目录不存在"
    fi
    
    # 检查配置文件
    echo -e "${YELLOW}ACTION:  配置文件：${NC}"
    if [ -f "config/tushare_config.json" ]; then
        echo -e "  OK: Tushare配置文件存在"
    else
        echo -e "  WARN:  Tushare配置文件不存在"
    fi
    
    if [ -f "config/crawler_config.json" ]; then
        echo -e "  OK: 爬虫配置文件存在"
    else
        echo -e "  WARN:  爬虫配置文件不存在"
    fi
    
    # 检查磁盘空间
    echo -e "${YELLOW}DISK: 磁盘空间：${NC}"
    disk_space=$(df -h . | awk 'NR==2 {print $4}')
    echo -e "  DATA: 可用空间: $disk_space"
    
    echo
    read -p "按任意键返回主菜单..." -n1 -s
}

show_welcome

# macOS兼容的超时函数
run_with_timeout() {
    local timeout_duration=$1
    shift
    local command="$@"
    
    # 使用perl实现超时功能（macOS兼容）
    perl -e '
        use POSIX ":sys_wait_h";
        $SIG{ALRM} = sub { kill 9, $pid; exit 124; };
        alarm '$timeout_duration';
        $pid = fork();
        if ($pid == 0) {
            exec @ARGV;
        } elsif ($pid > 0) {
            waitpid($pid, 0);
            exit $? >> 8;
        } else {
            exit 1;
        }
    ' -- $command
}

# 检查模型是否已存在
check_model_exists() {
    local local_dir=$1
    local model_name=$2
    
    if [ -d "$local_dir" ]; then
        # 检查是否有模型文件
        local model_files=$(find "$local_dir" -name "*.safetensors" -o -name "*.bin" -o -name "config.json" 2>/dev/null | wc -l)
        if [ $model_files -gt 0 ]; then
            echo -e "${GREEN}OK: ${model_name} 已存在，跳过下载${NC}"
            return 0
        fi
    fi
    return 1
}

# ModelScope 模型下载函数（带重试和备选方案）
download_model_with_fallback() {
    local model_id=$1
    local local_dir=$2
    local model_name=$3
    local max_retries=3
    local retry_count=0
    
    # 检查模型是否已存在
    if check_model_exists "$local_dir" "$model_name"; then
        return 0
    fi
    
    echo "正在下载 ${model_name}..."
    
    # 创建进度显示函数
    show_progress() {
        local pid=$1
        local message=$2
        local progress_chars="/-\\|"
        local i=0
        
        while kill -0 $pid 2>/dev/null; do
            printf "\r${YELLOW}%s %c${NC}" "$message" "${progress_chars:i++%4:1}"
            sleep 0.5
        done
        printf "\r"
    }
    
    while [ $retry_count -lt $max_retries ]; do
        if [ $retry_count -gt 0 ]; then
            echo -e "${YELLOW}重试下载 ${model_name} (${retry_count}/${max_retries})...${NC}"
            sleep 5  # 等待5秒再重试
        fi
        
        # 创建目标目录
        mkdir -p "$(dirname "$local_dir")"
        
        # 在后台运行下载命令并显示进度
        (
            run_with_timeout 300 modelscope download --model "$model_id" --local_dir "$local_dir"
        ) &
        local download_pid=$!
        
        show_progress $download_pid "下载中，请稍候..."
        
        # 等待后台进程完成并检查退出状态
        if wait $download_pid 2>/dev/null; then
            # 处理ModelScope下载后的嵌套目录结构
            # ModelScope可能会创建 models/author/model-name 的结构
            local author_dir="$(dirname "$local_dir")/$(echo "$model_id" | cut -d'/' -f1)"
            local nested_model_dir="$author_dir/$(basename "$local_dir")"
            
            # 如果存在嵌套结构，将文件移动到目标位置
            if [ -d "$nested_model_dir" ] && [ "$nested_model_dir" != "$local_dir" ]; then
                echo -e "${YELLOW}DIR: 检测到嵌套目录结构，正在整理...${NC}"
                # 确保目标目录存在
                mkdir -p "$local_dir"
                # 移动所有文件到目标目录
                if mv "$nested_model_dir"/* "$local_dir/" 2>/dev/null; then
                    # 清理空的嵌套目录
                    rmdir "$nested_model_dir" 2>/dev/null
                    rmdir "$author_dir" 2>/dev/null
                    echo -e "${GREEN}OK: 目录结构已整理完成${NC}"
                fi
            fi
            
            # 验证下载是否成功
            if check_model_exists "$local_dir" "$model_name"; then
                echo -e "${GREEN}OK: ${model_name} 下载完成！${NC}"
                return 0
            else
                echo -e "${YELLOW}WARN:  下载可能不完整，准备重试...${NC}"
            fi
        fi
        
        ((retry_count++))
    done
    
    # 所有重试失败后提供备选方案
    echo -e "${RED}ERROR: ${model_name} 下载失败（已重试 ${max_retries} 次）${NC}"
    echo -e "${YELLOW}TIP: 备选方案：${NC}"
    echo -e "  1. 检查网络连接后重新运行此脚本"
    echo -e "  2. 手动下载命令: ${BLUE}modelscope download --model $model_id --local_dir $local_dir${NC}"
    echo -e "  3. 从 Hugging Face 下载: ${BLUE}git clone https://huggingface.co/$(echo $model_id | sed 's/northwind9898/NeoQuasar/')${NC}"
    
    # 在GUI环境中自动继续，在终端环境中询问用户
    if [ "$KRONOS_IS_APP_BUNDLE" = "true" ] || [ ! -t 0 ]; then
        echo -e "${BLUE}GUI环境中自动继续安装${NC}"
        continue_install="y"
    else
        read -p "是否继续安装其他组件？(Y/n): " continue_install
    fi
    if [[ $continue_install =~ ^[Nn]$ ]]; then
        exit 1
    fi
    return 1
}

# 输入验证函数
validate_choice() {
    local input=$1
    local max_choice=$2
    
    # 检查是否为空
    if [[ -z "$input" ]]; then
        return 1
    fi
    
    # 检查是否为数字
    if ! [[ "$input" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    
    # 检查范围
    if [[ $input -lt 1 ]] || [[ $input -gt $max_choice ]]; then
        return 1
    fi
    
    return 0
}

# 在显示菜单前自动检查并安装依赖
echo -e "${BLUE}CHECK: 正在检查系统依赖...${NC}"
if ! command -v $PYTHON_CMD &> /dev/null || ! $PYTHON_CMD -c "import torch" 2>/dev/null || ! $PYTHON_CMD -c "import pandas" 2>/dev/null; then
    echo -e "${YELLOW}WARN:  检测到缺少必要依赖，正在自动安装...${NC}"
    auto_install_dependencies
    echo -e "${GREEN}OK: 依赖安装完成！${NC}"
else
    echo -e "${GREEN}OK: 系统依赖检查通过${NC}"
fi

echo

# 获取用户选择并验证
if [ -n "$AUTO_CHOICE" ]; then
    choice="$AUTO_CHOICE"
    echo -e "${BLUE}自动执行选项 $choice${NC}"
elif [ "$KRONOS_IS_APP_BUNDLE" = "true" ] || [ ! -t 0 ]; then
    # 在GUI环境中，默认执行一键安装
    choice="1"
    echo -e "${BLUE}检测到GUI环境，自动执行一键安装${NC}"
else
    # 在终端环境中，显示菜单供用户选择
    while true; do
        read -p "请选择操作 (1-13): " choice
        if validate_choice "$choice" 13; then
            break
        else
            echo -e "${RED}ERROR: 无效输入，请输入 1-13 之间的数字${NC}"
        fi
    done
fi

case $choice in
    1)
        echo -e "${GREEN}PACKAGE: 开始一键安装所有依赖...${NC}"
        
        # 检查是否需要自动安装依赖
        if ! command -v $PYTHON_CMD &> /dev/null || ! $PYTHON_CMD -c "import torch" 2>/dev/null; then
            echo -e "${BLUE}START: 检测到缺少依赖，启动自动安装...${NC}"
            auto_install_dependencies
        else
            echo -e "${GREEN}OK: 检测到依赖已安装，跳过自动安装${NC}"
            
            # 暂时禁用 set -e 以便手动处理错误
            set +e
            
            echo -e "${BLUE}STEP 步骤 0/4: 配置 Python 环境和清华镜像源...${NC}"
            
            # 检查并安装 pyenv
            if ! command -v pyenv &> /dev/null; then
                echo "正在安装 pyenv..."
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    # macOS 使用 Homebrew 安装
                    if command -v brew &> /dev/null; then
                        if safe_execute "brew install pyenv" "pyenv安装" true; then
                            echo -e "${GREEN}OK: pyenv 安装完成！${NC}"
                            # 添加到 shell 配置
                            echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
                            echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
                            echo 'eval "$(pyenv init -)"' >> ~/.zshrc
                            export PYENV_ROOT="$HOME/.pyenv"
                            export PATH="$PYENV_ROOT/bin:$PATH"
                            eval "$(pyenv init -)"
                        else
                            echo -e "${RED}ERROR: pyenv 安装失败${NC}"
                            exit 1
                        fi
                    else
                        echo -e "${RED}ERROR: 未找到 Homebrew，请先安装 Homebrew${NC}"
                        exit 1
                    fi
                else
                    # Linux 使用 curl 安装
                    if safe_execute "curl https://pyenv.run | bash" "pyenv安装" true; then
                        echo -e "${GREEN}OK: pyenv 安装完成！${NC}"
                        # 添加到 shell 配置
                        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
                        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
                        echo 'eval "$(pyenv init -)"' >> ~/.bashrc
                        export PYENV_ROOT="$HOME/.pyenv"
                        export PATH="$PYENV_ROOT/bin:$PATH"
                        eval "$(pyenv init -)"
                    else
                        echo -e "${RED}ERROR: pyenv 安装失败${NC}"
                        exit 1
                    fi
                fi
            else
                echo -e "${GREEN}OK: pyenv 已安装${NC}"
            fi
            
            # 检查 Python 3.11.13 是否已安装
            PYTHON_VERSION="3.11.13"
            if ! pyenv versions --bare | grep -q "^${PYTHON_VERSION}$"; then
                echo "正在安装 Python ${PYTHON_VERSION}..."
                echo "这可能需要几分钟时间，请耐心等待..."
                if safe_execute "pyenv install ${PYTHON_VERSION}" "Python ${PYTHON_VERSION} 安装" true; then
                    echo -e "${GREEN}OK: Python ${PYTHON_VERSION} 安装完成！${NC}"
                else
                    echo -e "${RED}ERROR: Python ${PYTHON_VERSION} 安装失败${NC}"
                    exit 1
                fi
            else
                echo -e "${GREEN}OK: Python ${PYTHON_VERSION} 已安装${NC}"
            fi
            
            # 设置全局 Python 版本
            echo "正在设置 Python ${PYTHON_VERSION} 为全局默认版本..."
            if safe_execute "pyenv global ${PYTHON_VERSION}" "设置全局Python版本" true; then
                echo -e "${GREEN}OK: Python 版本设置完成！${NC}"
            else
                echo -e "${RED}ERROR: Python 版本设置失败${NC}"
                exit 1
            fi
            
            # 刷新环境变量
            eval "$(pyenv init -)"
            
            # 配置 pip 清华镜像源
            echo "正在配置 pip 清华大学镜像源..."
            PIP_CONFIG_DIR="$HOME/.pip"
            mkdir -p "$PIP_CONFIG_DIR"
            
            cat > "$PIP_CONFIG_DIR/pip.conf" << EOF
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple/
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
            
            if [ -f "$PIP_CONFIG_DIR/pip.conf" ]; then
                echo -e "${GREEN}OK: pip 清华镜像源配置完成！${NC}"
            else
                echo -e "${RED}ERROR: pip 镜像源配置失败${NC}"
                exit 1
            fi
            
            # 升级 pip
            echo "正在升级 pip..."
            if safe_execute "$PYTHON_CMD -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn" "pip升级" true; then
                echo -e "${GREEN}OK: pip 升级完成！${NC}"
            else
                echo -e "${YELLOW}WARN:  pip 升级失败，继续使用当前版本${NC}"
            fi
            
            # 验证 Python 环境
            echo "正在验证 Python 环境..."
            CURRENT_PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
            echo "当前 Python 版本: $CURRENT_PYTHON_VERSION"
            
            if [[ "$CURRENT_PYTHON_VERSION" == "${PYTHON_VERSION}"* ]]; then
                echo -e "${GREEN}OK: Python 环境验证成功！${NC}"
            else
                echo -e "${YELLOW}WARN:  Python 版本不匹配，但继续执行${NC}"
            fi
            
            echo -e "${BLUE}STEP 步骤 1/4: 检查 Python 环境和 GUI 支持...${NC}"
            if ! command -v $PYTHON_CMD &> /dev/null; then
                echo -e "${RED}ERROR: Python 环境配置失败，请检查 pyenv 安装${NC}"
                exit 1
            fi
            
            # 检查tkinter支持
            echo "正在检查 GUI 支持 (tkinter)..."
            if ! $PYTHON_CMD -c "import tkinter; import _tkinter" 2>/dev/null; then
                echo -e "${YELLOW}WARN:  检测到 tkinter 不可用，正在尝试修复...${NC}"
                
                # 获取操作系统类型
                OS_TYPE=$(uname -s)
                case "$OS_TYPE" in
                    "Darwin")
                        echo "检测到 macOS 系统，正在安装 tkinter 支持..."
                        if command -v brew &> /dev/null; then
                            echo "正在通过 Homebrew 安装 python-tk..."
                            if safe_execute "brew install python-tk" "Homebrew python-tk 安装" true; then
                                echo -e "${GREEN}OK: tkinter 支持安装完成！${NC}"
                            else
                                echo -e "${YELLOW}WARN:  自动安装失败，将使用原生 macOS 界面${NC}"
                            fi
                        else
                            echo -e "${YELLOW}WARN:  未找到 Homebrew，建议安装：${NC}"
                            echo -e "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                            echo -e "${YELLOW}WARN:  将使用原生 macOS 界面${NC}"
                        fi
                        ;;
                    "Linux")
                        echo "检测到 Linux 系统，正在安装 tkinter 支持..."
                        if command -v apt-get &> /dev/null; then
                            echo "正在通过 apt 安装 $PYTHON_CMD-tk..."
                            if safe_execute "sudo apt-get update && sudo apt-get install -y $PYTHON_CMD-tk" "Linux tkinter 安装" true; then
                                echo -e "${GREEN}OK: tkinter 支持安装完成！${NC}"
                            else
                                echo -e "${YELLOW}WARN:  自动安装失败，请手动安装：sudo apt-get install $PYTHON_CMD-tk${NC}"
                            fi
                        elif command -v yum &> /dev/null; then
                            echo "正在通过 yum 安装 $PYTHON_CMD-tkinter..."
                            if safe_execute "sudo yum install -y $PYTHON_CMD-tkinter" "Linux tkinter 安装" true; then
                                echo -e "${GREEN}OK: tkinter 支持安装完成！${NC}"
                            else
                                echo -e "${YELLOW}WARN:  自动安装失败，请手动安装：sudo yum install $PYTHON_CMD-tkinter${NC}"
                            fi
                        else
                            echo -e "${YELLOW}WARN:  无法自动安装，请手动安装 tkinter 支持${NC}"
                        fi
                        ;;
                    *)
                        echo -e "${YELLOW}WARN:  未知操作系统，请手动安装 tkinter 支持${NC}"
                        ;;
                esac
                
                # 再次检查
                echo "重新检查 tkinter 支持..."
                if $PYTHON_CMD -c "import tkinter; import _tkinter" 2>/dev/null; then
                    echo -e "${GREEN}OK: tkinter 现在可用，将使用现代化 GUI 界面！${NC}"
                else
                    echo -e "${YELLOW}WARN:  tkinter 仍不可用，程序将自动使用原生界面${NC}"
                fi
            else
                echo -e "${GREEN}OK: tkinter 支持正常，将使用现代化 GUI 界面！${NC}"
            fi
            
            echo -e "${BLUE}STEP 步骤 2/4: 正在安装 Python 依赖包...${NC}"
            if [ -f "requirements.txt" ]; then
                $PYTHON_CMD -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
                pip_exit=$?
                if [ $pip_exit -eq 0 ]; then
                    echo -e "${GREEN}OK: Python 依赖处理完成（如出现 'Requirement already satisfied' 表示该依赖已存在）${NC}"
                else
                    echo -e "${RED}ERROR: Python 依赖包安装失败 (退出代码 $pip_exit)${NC}"
                    echo -e "${YELLOW}TIP: 提示: 已配置清华镜像源，如仍失败请检查网络连接${NC}"
                    read -p "按任意键退出..." -n1 -s
                    exit 1
                fi
            else
                echo -e "${RED}ERROR: 未找到 requirements.txt 文件${NC}"
                exit 1
            fi
            
            echo -e "${BLUE}STEP 步骤 3/4: 配置 Playwright 浏览器环境...${NC}"
            echo "这可能需要几分钟时间，请耐心等待..."

            playwright_version=$(get_python_package_version "playwright")
            if [ -n "$playwright_version" ]; then
                echo -e "${YELLOW}SKIP:  Playwright 已安装 (版本 $playwright_version)，跳过包安装${NC}"
            else
                echo -e "${YELLOW}ACTION:  正在安装 Playwright Python 包...${NC}"
                $PYTHON_CMD -m pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
                pw_exit=$?
                if [ $pw_exit -eq 0 ]; then
                    playwright_version=$(get_python_package_version "playwright")
                    if [ -n "$playwright_version" ]; then
                        echo -e "${GREEN}OK: Playwright 安装完成 (版本 $playwright_version)${NC}"
                    else
                        echo -e "${GREEN}OK: Playwright 安装完成${NC}"
                    fi
                else
                    echo -e "${YELLOW}WARN:  Playwright 安装失败 (退出代码 $pw_exit)，爬虫功能将不可用${NC}"
                fi
            fi

            playwright_version=${playwright_version:-$(get_python_package_version "playwright")}
            if [ -n "$playwright_version" ]; then
                echo -e "${YELLOW}ACTION:  正在安装/刷新 Playwright 浏览器 (chromium)...${NC}"
                $PYTHON_CMD -m playwright install chromium
                chromium_exit=$?
                if [ $chromium_exit -eq 0 ]; then
                    echo -e "${GREEN}OK: Chromium 浏览器资源已就绪${NC}"
                else
                    echo -e "${YELLOW}WARN:  Chromium 浏览器资源安装失败 (退出代码 $chromium_exit)，可稍后手动运行 'playwright install chromium'${NC}"
                fi
            else
                echo -e "${YELLOW}WARN:  未检测到 Playwright 包，跳过浏览器资源安装${NC}"
            fi
            
            echo -e "${BLUE}STEP 步骤 4/4: 准备 ModelScope 模型下载...${NC}"
            modelscope_version=$(get_python_package_version "modelscope")
            if [ -n "$modelscope_version" ]; then
                echo -e "${YELLOW}SKIP:  ModelScope 已安装 (版本 $modelscope_version)，跳过包安装${NC}"
            else
                echo "正在安装 ModelScope SDK..."
                $PYTHON_CMD -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
                ms_exit=$?
                if [ $ms_exit -eq 0 ]; then
                    modelscope_version=$(get_python_package_version "modelscope")
                    if [ -n "$modelscope_version" ]; then
                        echo -e "${GREEN}OK: ModelScope 安装完成 (版本 $modelscope_version)${NC}"
                    else
                        echo -e "${GREEN}OK: ModelScope 安装完成${NC}"
                    fi
                else
                    echo -e "${YELLOW}WARN:  ModelScope 安装失败 (退出代码 $ms_exit)，跳过模型下载${NC}"
                fi
            fi

            modelscope_version=${modelscope_version:-$(get_python_package_version "modelscope")}
            if [ -n "$modelscope_version" ]; then
                echo "正在下载模型文件，这可能需要较长时间，请耐心等待..."

                # 创建模型目录
                mkdir -p "$KRONOS_MODELS_DIR"

                # 检测是否在GUI环境中运行（无法交互）
                if [ "$KRONOS_IS_APP_BUNDLE" = "true" ] || [ ! -t 0 ]; then
                    # 在GUI环境或非交互模式下，使用默认选项
                    echo -e "${BLUE}检测到GUI环境，自动选择推荐的Kronos完整模型套件${NC}"
                    model_choice=1
                else
                    # 在终端环境中，询问用户选择下载哪些模型
                    echo -e "${YELLOW}请选择要下载的模型：${NC}"
                    echo "1. Kronos 完整模型套件 (推荐)"
                    echo "2. Chronos-T5-Small 轻量级模型"  
                    echo "3. 下载所有模型"
                    echo "4. 跳过模型下载"

                    while true; do
                        read -p "请选择 (1-4, 默认1): " model_choice
                        model_choice=${model_choice:-1}
                        if validate_choice "$model_choice" 4; then
                            break
                        else
                            echo -e "${RED}ERROR: 请输入 1-4 之间的数字${NC}"
                        fi
                    done
                fi

                case ${model_choice:-1} in
                    1|3)
                        # 使用 ModelScope 命令行下载 Kronos 模型
                        download_model_with_fallback "northwind9898/Kronos-Tokenizer-base" "$KRONOS_MODELS_DIR/Kronos-Tokenizer-base" "Kronos Tokenizer"
                        download_model_with_fallback "northwind9898/Kronos-small" "$KRONOS_MODELS_DIR/Kronos-small" "Kronos 模型"

                        # 如果选择下载所有模型，继续下载 Chronos-T5-Small
                        if [ ${model_choice:-1} -eq 3 ]; then
                            echo "正在下载 Chronos-T5-Small 模型..."
                            if modelscope download --model AI-ModelScope/chronos-t5-small --local_dir $KRONOS_MODELS_DIR/chronos-t5-small; then
                                echo -e "${GREEN}OK: Chronos-T5-Small 模型下载完成！${NC}"
                            else
                                echo -e "${YELLOW}WARN: Chronos-T5-Small 模型下载失败${NC}"
                                echo -e "${YELLOW}提示: 您可以稍后手动运行以下命令下载：${NC}"
                                echo -e "${BLUE}modelscope download --model AI-ModelScope/chronos-t5-small --local_dir $KRONOS_MODELS_DIR/chronos-t5-small${NC}"
                            fi
                        fi
                        ;;
                    2)
                        # 下载 Chronos-T5-Small 模型
                        echo "正在下载 Chronos-T5-Small 模型..."
                        if modelscope download --model AI-ModelScope/chronos-t5-small --local_dir $KRONOS_MODELS_DIR/chronos-t5-small; then
                            echo -e "${GREEN}OK: Chronos-T5-Small 模型下载完成！${NC}"
                        else
                            echo -e "${YELLOW}WARN: Chronos-T5-Small 模型下载失败${NC}"
                            echo -e "${YELLOW}提示: 您可以稍后手动运行以下命令下载：${NC}"
                            echo -e "${BLUE}modelscope download --model AI-ModelScope/chronos-t5-small --local_dir ./models/chronos-t5-small${NC}"
                        fi
                        ;;
                    4)
                        echo -e "${BLUE}SKIP: 跳过模型下载${NC}"
                        ;;
                esac

                echo -e "${GREEN}OK: ModelScope 模型下载流程完成！${NC}"
                echo -e "${GREEN}DONE: 所有依赖和模型安装完成！系统已准备就绪！${NC}"
            else
                echo -e "${YELLOW}WARN:  ModelScope 未安装成功，跳过模型下载${NC}"
            fi
        fi
        ;;
    2)
        echo -e "${BLUE}STEP 启动配置向导...${NC}"
        safe_execute_python "scripts/config_wizard.py" "配置向导"
        ;;
    3)
        echo -e "${BLUE}CHECK: 检查环境状态...${NC}"
        safe_execute_python "scripts/check_environment.py" "环境状态检查"
        ;;
    4)
        echo -e "${BLUE}DATA: 使用 Tushare 获取股票数据${NC}"
        
        # 验证股票代码函数
        validate_tushare_symbol() {
            local symbol=$1
            # Tushare 格式验证 (6位数字.交易所代码)
            if [[ $symbol =~ ^[0-9]{6}\.(SZ|SH)$ ]]; then
                return 0
            fi
            return 1
        }
        
        while true; do
            read -p "请输入股票代码 (格式: 000001.SZ): " symbol
            if [[ -z "$symbol" ]]; then
                echo -e "${RED}ERROR: 股票代码不能为空${NC}"
            elif validate_tushare_symbol "$symbol"; then
                break
            else
                echo -e "${RED}ERROR: 股票代码格式错误，请使用格式: 000001.SZ 或 600000.SH${NC}"
                echo -e "${YELLOW}TIP: 提示: SZ=深交所, SH=上交所${NC}"
            fi
        done
        
        echo -e "${GREEN}正在获取 $symbol 的数据...${NC}"
        safe_execute_python "scripts/fetch_data.py" "获取股票数据" --symbol $symbol --source tushare
        ;;
    5)
        echo -e "${BLUE}CRAWLER: 使用爬虫获取股票数据${NC}"
        echo "可选数据源:"
        echo "  1. 自动选择最佳爬虫源"
        echo "  2. 东方财富 (eastmoney)"
        echo "  3. 同花顺 (tonghuashun)"
        echo "  4. 雪球 (xueqiu)"
        
        while true; do
            read -p "请选择数据源 (1-4, 默认1): " source_choice
            source_choice=${source_choice:-1}
            if validate_choice "$source_choice" 4; then
                break
            else
                echo -e "${RED}ERROR: 请输入 1-4 之间的数字${NC}"
            fi
        done
        
        # 验证爬虫股票代码函数
        validate_crawler_symbol() {
            local symbol=$1
            # 爬虫格式验证 (6位数字)
            if [[ $symbol =~ ^[0-9]{6}$ ]]; then
                return 0
            fi
            return 1
        }
        
        while true; do
            read -p "请输入股票代码 (格式: 000001): " symbol
            if [[ -z "$symbol" ]]; then
                echo -e "${RED}ERROR: 股票代码不能为空${NC}"
            elif validate_crawler_symbol "$symbol"; then
                break
            else
                echo -e "${RED}ERROR: 股票代码格式错误，请输入6位数字${NC}"
                echo -e "${YELLOW}TIP: 示例: 000001, 600000, 300001${NC}"
            fi
        done
        
        case ${source_choice} in
            1) source="auto" ;;
            2) source="eastmoney" ;;
            3) source="tonghuashun" ;;
            4) source="xueqiu" ;;
        esac
        echo -e "${GREEN}使用 $source 数据源获取 $symbol 的数据，请稍候...${NC}"
        safe_execute_python "scripts/fetch_data.py" "获取股票数据" --symbol $symbol --source $source
        ;;
    6)
        echo -e "${BLUE}CHART: 批量获取数据及预测K线${NC}"
        
        # 股票代码输入
        echo -e "${YELLOW}请输入股票代码（多个代码用逗号分隔，例如：000001.SZ,600000.SH）：${NC}"
        read -p "股票代码: " symbols
        
        if [ -z "$symbols" ]; then
            echo -e "${RED}ERROR: 股票代码不能为空${NC}"
            read -p "按任意键继续..." -n1 -s
        else
        
        # 数据源选择
        echo -e "${YELLOW}请选择数据源：${NC}"
        echo "  1. 自动选择最佳数据源 (推荐)"
        echo "  2. Tushare API"
        echo "  3. 网络爬虫"
        
        while true; do
            read -p "请选择 (1-3, 默认1): " source_choice
            source_choice=${source_choice:-1}
            if validate_choice "$source_choice" 3; then
                break
            else
                echo -e "${RED}ERROR: 请输入 1-3 之间的数字${NC}"
            fi
        done
        
        case ${source_choice} in
            1) source="auto" ;;
            2) source="tushare" ;;
            3) source="crawler" ;;
        esac
        
        # 获取天数
        echo -e "${YELLOW}请输入要获取的天数（默认365天）：${NC}"
        read -p "天数: " days
        days=${days:-365}
        
        echo -e "${GREEN}正在批量获取 $symbols 的数据（使用 $source 数据源，获取 $days 天数据）...${NC}"
        
        # 批量获取数据
        if safe_execute_python "scripts/batch_fetch.py" "批量获取股票数据" --symbols ${symbols//,/ } --min-days "$days" --config config/tushare_config.json; then
            echo -e "${GREEN}OK: 数据获取完成！${NC}"
            
            # 从输入的股票代码中提取第一个进行预测演示
            first_symbol=$(echo $symbols | cut -d',' -f1)
            # 移除交易所后缀，只保留股票代码部分
            clean_symbol=${first_symbol%.*}
            
            # 自动运行预测
            echo -e "${GREEN}PREDICT: 开始运行预测...${NC}"
            echo -e "${BLUE}使用股票 $clean_symbol 进行预测演示${NC}"
            echo -e "${YELLOW}预测完成后将自动生成HTML综合分析报告并打开浏览器${NC}"
            
            # 执行预测脚本
            if safe_execute_python "examples/prediction_batch_example.py" "批量股票预测" --stock-code "$clean_symbol"; then
                echo -e "${GREEN}OK: 批量预测完成！${NC}"
                echo -e "${GREEN}REPORT: HTML分析报告已自动生成到$KRONOS_RESULTS_DIR目录${NC}"
            else
                echo -e "${YELLOW}WARN: 预测运行失败，但数据已成功获取${NC}"
            fi
        else
            echo -e "${RED}ERROR: 数据获取失败${NC}"
        fi
        fi
        ;;
    7)
        echo -e "${BLUE}CHECK: 检查授权状态${NC}"
        if [ ! -f "finetune/license_system/license_validator.py" ]; then
            echo -e "${RED}ERROR: 授权系统文件不存在${NC}"
            echo -e "${YELLOW}TIP: 请确保 finetune/license_system/ 目录完整${NC}"
        else
            $PYTHON_CMD -c "
import sys
sys.path.append('finetune/license_system')
from license_validator import LicenseValidator
import os

data_dir = os.path.join('$KRONOS_USER_DIR', 'finetune', 'license_system', 'data')
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)
validator = LicenseValidator(data_dir)

print('=' * 60)
print('           Kronos 授权状态检查')
print('=' * 60)

is_valid, message = validator.validate_license()

if is_valid:
    print(f'OK: {message}')
    
    info = validator.get_license_info()
    if info:
        print(f'')
        print(f'STATUS: 授权信息:')
        print(f'   授权码: {info[\"license_code\"]}')
        print(f'   激活时间: {info[\"activation_time\"][:19].replace(\"T\", \" \")}')
        print(f'   设备ID: {info[\"device_id\"]}')
        print(f'   系统: {info[\"system_info\"][\"system\"]} {info[\"system_info\"][\"release\"]}')
        print(f'   授权类型: 永久授权')
else:
    print(f'ERROR: {message}')
    print(f'')
    print(f'TIP: 请选择选项8激活授权码')
"
        fi
        ;;
    8)
        echo -e "${BLUE}KEY: 激活授权码${NC}"
        if [ ! -f "finetune/license_system/activate.py" ]; then
            echo -e "${RED}ERROR: 授权激活工具不存在${NC}"
            echo -e "${YELLOW}TIP: 请确保 finetune/license_system/activate.py 文件存在${NC}"
        else
            echo -e "${GREEN}启动授权激活工具...${NC}"
            safe_execute_python "finetune/license_system/activate.py" "授权激活工具"
        fi
        ;;
    9)
        echo -e "${BLUE}PREDICT: 运行预测示例${NC}"
        safe_execute_python "examples/prediction_example.py" "预测示例"
        ;;
    10)
        echo -e "${BLUE}TEST: 测试爬虫功能...${NC}"
        $PYTHON_CMD -c "import asyncio; from scripts.crawler import CrawlerManager; asyncio.run(CrawlerManager().test_connection())"
        ;;
    11)
        show_help
        ;;
    12)
        show_system_status
        ;;
    13)
        echo -e "${GREEN}BYE: 感谢使用 Kronos！再见！${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}ERROR: 无效选择，请输入 1-13${NC}"
        ;;
esac
