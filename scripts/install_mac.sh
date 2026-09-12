#!/bin/bash

# Kronos macOS/Linux 一键安装脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_message() {
    echo -e "${2}${1}${NC}"
}

print_success() {
    print_message "✅ $1" "$GREEN"
}

print_error() {
    print_message "❌ $1" "$RED"
}

print_warning() {
    print_message "⚠️  $1" "$YELLOW"
}

print_info() {
    print_message "$1" "$CYAN"
}

# 错误处理
set -e
trap 'print_error "安装过程中出现错误，请检查上面的错误信息"' ERR

print_info "========================================"
print_info "     Kronos 金融预测模型一键安装脚本"
print_info "========================================"
echo

# 检测操作系统
OS="$(uname -s)"
case "${OS}" in
    Linux*)     MACHINE=Linux;;
    Darwin*)    MACHINE=Mac;;
    *)          MACHINE="UNKNOWN:${OS}"
esac
print_info "检测到操作系统: $MACHINE"

# 1. 检查 Python
print_info "[1/7] 检查 Python 环境..."
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        print_error "未找到 Python，请先安装 Python 3.11 或更高版本"
        if [[ "$MACHINE" == "Mac" ]]; then
            print_info "macOS 安装建议: brew install python3"
        else
            print_info "Linux 安装建议: sudo apt-get install python3 python3-pip"
        fi
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1)
print_success "Python 环境检查通过: $PYTHON_VERSION"

# 2. 检查 pip
print_info "[2/7] 检查 pip 包管理器..."
if ! command -v pip3 &> /dev/null; then
    if ! command -v pip &> /dev/null; then
        print_error "未找到 pip"
        exit 1
    else
        PIP_CMD="pip"
    fi
else
    PIP_CMD="pip3"
fi

PIP_VERSION=$($PIP_CMD --version 2>&1)
print_success "pip 检查通过: $PIP_VERSION"

# 3. 升级 pip
print_info "[3/7] 升级 pip..."
$PYTHON_CMD -m pip install --upgrade pip || print_warning "pip 升级失败，继续安装..."
print_success "pip 升级完成"

# 4. 检查并安装系统依赖
print_info "[4/7] 检查系统依赖..."
if [[ "$MACHINE" == "Mac" ]]; then
    # macOS 特定检查
    if ! command -v brew &> /dev/null; then
        print_warning "未找到 Homebrew，某些功能可能受限"
        print_info "安装 Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    fi
elif [[ "$MACHINE" == "Linux" ]]; then
    # Linux 特定检查
    if command -v apt-get &> /dev/null; then
        print_info "检测到 apt 包管理器"
        # 检查是否需要安装开发工具
        if ! dpkg -l | grep -q python3-dev; then
            print_info "安装 Python 开发包..."
            sudo apt-get update
            sudo apt-get install -y python3-dev python3-pip build-essential
        fi
    elif command -v yum &> /dev/null; then
        print_info "检测到 yum 包管理器"
        if ! rpm -qa | grep -q python3-devel; then
            print_info "安装 Python 开发包..."
            sudo yum install -y python3-devel python3-pip gcc gcc-c++
        fi
    fi
fi
print_success "系统依赖检查完成"

# 5. 创建项目目录
print_info "[5/7] 创建项目目录..."
directories=("data" "logs" "config" "scripts" "results")
for dir in "${directories[@]}"; do
    mkdir -p "$dir"
done
print_success "目录创建完成"

# 6. 安装 Python 依赖
print_info "[6/7] 安装 Python 依赖包..."

# 检查requirements.txt文件是否存在
if [ -f "requirements.txt" ]; then
    print_info "正在从requirements.txt安装依赖..."
    if ! $PIP_CMD install -r requirements.txt; then
        print_warning "使用国内镜像重试..."
        $PIP_CMD install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/
    fi
else
    # 如果requirements.txt不存在，使用原来的方式
    print_info "requirements.txt不存在，使用默认依赖列表..."
    
    # 基础依赖
    print_info "正在安装基础依赖..."
    if ! $PIP_CMD install numpy pandas torch matplotlib tqdm safetensors einops huggingface_hub; then
        print_warning "使用国内镜像重试..."
        $PIP_CMD install numpy pandas torch matplotlib tqdm safetensors einops huggingface_hub -i https://pypi.tuna.tsinghua.edu.cn/simple/
    fi

    # Tushare
    print_info "正在安装 Tushare..."
    if ! $PIP_CMD install tushare; then
        print_warning "Tushare 安装失败，可以稍后手动安装"
    fi

    # Baostock
    print_info "正在安装 Baostock..."
    if ! $PIP_CMD install baostock; then
        print_warning "Baostock 安装失败，可以稍后手动安装"
    fi
fi

# 可视化依赖（额外安装）
print_info "正在安装可视化依赖..."
if ! $PIP_CMD install seaborn plotly; then
    print_warning "可视化依赖安装失败，基本功能不受影响"
fi

print_success "依赖安装完成"

# 7. 创建配置文件
print_info "[7/7] 创建配置文件..."

cat > config/tushare_config.json << 'EOF'
{
  "tushare": {
    "token": "请在此处填入您的Tushare Token",
    "timeout": 30,
    "retry_count": 3
  },
  "data_settings": {
    "output_dir": "./data/",
    "file_format": "csv",
    "date_format": "%Y-%m-%d %H:%M:%S"
  },
  "default_params": {
    "freq": "5min",
    "adj": "qfq",
 "start_date": "",
    "end_date": "20241231"
  }
}
EOF

# 创建快速启动脚本
cat > quick_start.sh << 'EOF'
#!/bin/bash
# Kronos 快速启动脚本

echo "Kronos 快速启动菜单"
echo "=================="
echo "1. 获取股票数据"
echo "2. 运行预测示例"
echo "3. 批量获取数据"
echo "4. 检查环境"
echo "5. 退出"
echo
read -p "请选择操作 (1-5): " choice

case $choice in
    1)
        read -p "请输入股票代码 (如 000001.SZ): " symbol
        python3 scripts/fetch_data.py --symbol $symbol
        ;;
    2)
        python3 examples/prediction_example.py
        ;;
    3)
        python3 scripts/batch_fetch.py
        ;;
    4)
        python3 scripts/check_environment.py
        ;;
    5)
        echo "再见！"
        exit 0
        ;;
    *)
        echo "无效选择"
        ;;
esac
EOF

chmod +x quick_start.sh

print_success "配置文件创建完成"

echo
print_success "========================================"
print_success "          🎉 安装完成！"
print_success "========================================"
echo
print_info "下一步操作:"
echo "1. 编辑 config/tushare_config.json 文件，填入您的 Tushare Token"
echo "2. 运行 ./quick_start.sh 使用快速启动菜单"
echo "3. 或者运行 python3 scripts/fetch_data.py 获取数据"
echo "4. 运行 python3 examples/prediction_example.py 开始预测"
echo
print_info "获取 Tushare Token（邀请注册，部分接口需 5000 积分）: https://tushare.pro/weborder/#/login?reg=711997"
print_info "完整文档: https://github.com/Lumonote/lumo_trade"
echo

read -p "按回车键退出..."