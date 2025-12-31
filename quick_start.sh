#!/bin/bash

# Ensure we are in the project root
cd "$(dirname "$0")"

# Set PYTHONPATH to include current directory
export PYTHONPATH=$PYTHONPATH:$(pwd)

# Function to pause
pause() {
    read -p "Press Enter to continue..."
}

# Check for python command
if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "Error: Python not found. Please install Python 3.11+"
    exit 1
fi

while true; do
    clear
    echo "================================"
    echo "    Kronos 股票预测系统 START:"
    echo "================================"
    echo "欢迎使用 Kronos！请选择您需要的操作："
    echo ""
    echo "PACKAGE: 系统设置"
    echo "1. 一键安装所有依赖 (Python包 + Playwright浏览器 + 模型)"
    echo "2. 配置数据源 (向导)"
    echo "3. 检查环境状态"
    echo ""
    echo "DATA: 数据获取"
    echo "4. 获取股票数据 (Tushare)"
    echo "5. 获取股票数据 (爬虫)"
    echo "6. 批量获取数据及预测K线"
    echo "7. 🔥 投资机会挖掘 (TOP100热门股票)"
    echo ""
    echo "PREDICT: 预测功能"
    echo "8. 运行预测示例"
    echo ""
    echo "CRAWLER: 爬虫设置"
    echo "9. 安装 Playwright 浏览器"
    echo "10. 测试爬虫功能"
    echo ""
    echo "WEB: Web界面"
    echo "11. 启动Web界面"
    echo ""
    echo "INFO:  帮助与信息"
    echo "12. 显示使用帮助"
    echo "13. 查看系统状态"
    echo ""
    echo "14. 退出"
    echo ""
    echo "TIP: 提示: 首次使用请先选择选项1进行一键安装"
    echo ""
    
    read -p "请选择操作 (1-14): " choice
    
    case $choice in
        1)
            echo "PACKAGE: 开始一键安装所有依赖和模型..."
            # Check python version
            $PYTHON_CMD --version
            echo "Installing dependencies..."
            $PYTHON_CMD -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
            echo "Installing playwright..."
            $PYTHON_CMD -m pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
            $PYTHON_CMD -m playwright install chromium
            pause
            ;;
        2)
            echo "STEP 启动配置向导..."
            $PYTHON_CMD scripts/config_wizard.py
            pause
            ;;
        3)
            echo "CHECK: 检查环境状态..."
            $PYTHON_CMD scripts/check_environment.py
            pause
            ;;
        4)
            echo "DATA: 获取股票数据 (Tushare)"
            $PYTHON_CMD scripts/fetch_data.py --source tushare
            pause
            ;;
        5)
            echo "DATA: 获取股票数据 (爬虫)"
            $PYTHON_CMD scripts/fetch_data.py --source crawler
            pause
            ;;
        6)
            echo "CHART: 批量获取数据及预测K线"
            read -p "请输入股票代码（多个代码用逗号分隔）: " symbols
            read -p "请输入要获取的天数（默认365天）: " days
            days=${days:-365}
            echo "正在批量获取..."
            $PYTHON_CMD scripts/batch_fetch.py --symbols "$symbols" --min-days "$days" --config config/tushare_config.json
            
            # Extract first symbol for prediction example
            first_symbol=$(echo $symbols | cut -d',' -f1)
            clean_symbol=$(echo $first_symbol | cut -d'.' -f1)
            
            echo "PREDICT: 开始运行预测演示 ($clean_symbol)..."
            $PYTHON_CMD examples/prediction_batch_example.py --stock-code "$clean_symbol"
            pause
            ;;
        7)
            echo "🔥 投资机会挖掘 - 分析TOP100热门股票"
            read -p "是否开始投资机会挖掘？(Y/n): " confirm
            if [[ "$confirm" != "n" && "$confirm" != "N" ]]; then
                echo "正在启动投资机会挖掘系统..."
                $PYTHON_CMD scripts/run_opportunity_discovery.py --limit 100 --workers 10
            fi
            pause
            ;;
        8)
            echo "PREDICT: 运行预测示例"
            $PYTHON_CMD examples/prediction_example.py
            pause
            ;;
        9)
            echo "CRAWLER: 正在安装 Playwright 浏览器..."
            $PYTHON_CMD -m pip install playwright
            $PYTHON_CMD -m playwright install chromium
            pause
            ;;
        10)
            echo "TEST: 测试爬虫功能..."
            $PYTHON_CMD -c "import asyncio; from scripts.crawler import CrawlerManager; asyncio.run(CrawlerManager().test_connection())"
            pause
            ;;
        11)
            echo "WEB: 启动Web界面..."
            cd webui && $PYTHON_CMD app.py
            cd ..
            pause
            ;;
        12)
            echo "================================"
            echo "      Kronos 使用帮助 HELP:"
            echo "================================"
            echo ""
            echo "START: 快速开始："
            echo "  1. 运行 quick_start.sh"
            echo "  2. 选择“1”进行一键安装"
            echo "  3. 选择“2”配置数据源（需要Tushare Token）"
            echo "  4. 选择“7”运行预测示例"
            echo ""
            echo "DATA: 数据源配置："
            echo "  - Tushare: 需要注册账号获取Token (https://tushare.pro/)"
            echo "  - 爬虫: 自动从金融网站获取数据，无需注册"
            echo ""
            echo "CHART: 股票代码格式："
            echo "  - Tushare: 000001.SZ (深交所) 或 600000.SH (上交所)"
            echo "  - 爬虫: 000001 (6位数字)"
            echo ""
            echo "PREDICT: 预测功能："
            echo "  - 支持OHLCV数据预测"
            echo "  - 可调节预测长度和采样参数"
            echo "  - 支持批量预测多只股票"
            echo ""
            echo "WEB: Web界面："
            echo "  - 运行: cd webui && python app.py"
            echo "  - 访问: http://localhost:7070"
            echo ""
            pause
            ;;
        13)
            echo "系统状态检查 STATUS:"
            $PYTHON_CMD --version
            pip --version
            echo "Checking packages..."
            for pkg in torch pandas numpy matplotlib tqdm playwright; do
                $PYTHON_CMD -c "import $pkg" 2>/dev/null && echo "OK: $pkg" || echo "ERROR: $pkg missing"
            done
            pause
            ;;
        14)
            echo "BYE: 感谢使用 Kronos！再见！"
            exit 0
            ;;
        *)
            echo "无效输入，请输入 1-14 之间的数字"
            sleep 1
            ;;
    esac
done
