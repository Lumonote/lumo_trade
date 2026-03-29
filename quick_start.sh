#!/bin/bash

# Ensure we are in the project root
cd "$(dirname "$0")"
SCRIPT_DIR=$(pwd)

# 设置 PYTHONPATH - 添加所有必要的目录
export PYTHONPATH="${SCRIPT_DIR}:${SCRIPT_DIR}/scripts:${SCRIPT_DIR}/analysis:${SCRIPT_DIR}/model:${SCRIPT_DIR}/utils:${SCRIPT_DIR}/finetune:${PYTHONPATH:-}"

# 设置项目根目录环境变量
export KRONOS_PROJECT_ROOT="${SCRIPT_DIR}"

# 设置 pip 使用用户安装模式，解决 Python 3.12+ externally-managed-environment 限制
export PIP_USER=1

# 设置中文编码环境，解决乱码问题
export LC_ALL=zh_CN.UTF-8
export LANG=zh_CN.UTF-8
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# Function to pause
pause() {
    read -p "Press Enter to continue..."
}

run_batch_predict_and_rank_analysis() {
    local symbols_input="$1"
    local days_input="${2:-365}"
    local -a raw_symbols=()
    local -a batch_symbols=()
    local -a clean_codes=()
    local symbol=""
    local trimmed=""
    local clean_code=""
    local first_symbol=""
    local test_codes=""

    IFS=',' read -r -a raw_symbols <<< "$symbols_input"

    for symbol in "${raw_symbols[@]}"; do
        trimmed=$(echo "$symbol" | tr -d '[:space:]')
        if [[ -z "$trimmed" ]]; then
            continue
        fi
        batch_symbols+=("$trimmed")
        clean_code="${trimmed%%.*}"
        if [[ -n "$clean_code" ]]; then
            clean_codes+=("$clean_code")
        fi
    done

    if [[ ${#batch_symbols[@]} -eq 0 ]]; then
        echo "ERROR: 未解析到有效股票代码"
        return 1
    fi

    echo "正在批量获取..."
    "$PYTHON_CMD" scripts/batch_fetch.py --symbols "${batch_symbols[@]}" --min-days "$days_input" --config config/tushare_config.json
    local fetch_status=$?
    if [[ $fetch_status -ne 0 ]]; then
        return $fetch_status
    fi

    first_symbol="${clean_codes[0]}"
    if [[ -n "$first_symbol" ]]; then
        echo "PREDICT: 开始运行预测演示 ($first_symbol)..."
        "$PYTHON_CMD" examples/prediction_batch_example.py --stock-code "$first_symbol"
        local predict_status=$?
        if [[ $predict_status -ne 0 ]]; then
            echo "WARN: 首只股票预测运行失败，但将继续执行综合评分排名分析"
        fi
    fi

    if [[ ${#clean_codes[@]} -gt 0 ]]; then
        test_codes=$(IFS=,; echo "${clean_codes[*]}")
        echo "RANK: 开始运行 7 式综合评分排名详细分析 (${#clean_codes[@]}只股票)..."
        "$PYTHON_CMD" scripts/run_opportunity_discovery.py --test-codes "$test_codes" --workers 10
        local rank_status=$?
        if [[ $rank_status -ne 0 ]]; then
            echo "WARN: 综合评分排名详细分析执行失败"
        else
            echo "REPORT: 综合评分排名详细分析报告已生成到 results 目录"
        fi
    fi

    return 0
}

# Check for python command - 智能选择 Python 3.11+
find_python() {
    # 尝试找到 Python 3.11+

    # 1. 优先使用环境变量
    if [[ -n "$PYTHON_CMD" && -x "$PYTHON_CMD" ]]; then
        ver=$("$PYTHON_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        if [[ "$ver" == "3.11" || "$ver" == "3.12" || "$ver" == "3.13" ]]; then
            echo "$PYTHON_CMD"
            return 0
        fi
    fi

    if [[ -n "$PYTHON" && -x "$PYTHON" ]]; then
        ver=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        if [[ "$ver" == "3.11" || "$ver" == "3.12" || "$ver" == "3.13" ]]; then
            echo "$PYTHON"
            return 0
        fi
    fi

    # 2. 检查 python 命令
    if command -v python &>/dev/null; then
        ver=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        if [[ "$ver" == "3.11" || "$ver" == "3.12" || "$ver" == "3.13" ]]; then
            echo "python"
            return 0
        fi
    fi

    # 3. 检查 python3 命令
    if command -v python3 &>/dev/null; then
        ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
        if [[ "$ver" == "3.11" || "$ver" == "3.12" || "$ver" == "3.13" ]]; then
            echo "python3"
            return 0
        fi
    fi

    # 4. 检查完整路径
    for path in /usr/local/bin/python3.11 /opt/homebrew/bin/python3.11; do
        if [[ -x "$path" ]]; then
            echo "$path"
            return 0
        fi
    done

    # 5. 尝试通过 which 找 python3.11
    if command -v python3.11 &>/dev/null; then
        echo "python3.11"
        return 0
    fi

    return 1
}

PYTHON_CMD=$(find_python)
if [[ -z "$PYTHON_CMD" ]]; then
    echo "Error: Python 3.11+ not found. Please install Python 3.11 or later."
    exit 1
fi

echo "DEBUG: 使用Python: $PYTHON_CMD"
$PYTHON_CMD --version

# 非交互模式：支持直接传入选项编号执行并退出
# 例如: ./quick_start.sh 7 或 ./quick_start.sh --batch 7
BATCH_MODE=false
MENU_CHOICE=""

if [[ "$1" == "--batch" || "$1" == "-b" ]]; then
    BATCH_MODE=true
    MENU_CHOICE="$2"
elif [[ -n "$1" ]]; then
    # 直接传入选项编号也进入非交互模式
    BATCH_MODE=true
    MENU_CHOICE="$1"
fi

# 非交互模式：直接执行对应选项并退出
if [[ "$BATCH_MODE" == "true" && -n "$MENU_CHOICE" ]]; then
    case $MENU_CHOICE in
        1)
            echo "PACKAGE: 开始一键安装所有依赖和模型..."
            $PYTHON_CMD --version
            echo "Installing dependencies..."
            # 使用 --user flag 解决 Python 3.12+ externally-managed-environment 限制
            $PYTHON_CMD -m pip install --user -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
            echo "Installing playwright..."
            $PYTHON_CMD -m pip install --user playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
            $PYTHON_CMD -m playwright install chromium
            exit 0
            ;;
        2)
            echo "STEP 启动配置向导..."
            $PYTHON_CMD scripts/config_wizard.py
            exit 0
            ;;
        3)
            echo "CHECK: 检查环境状态..."
            $PYTHON_CMD scripts/check_environment.py
            exit 0
            ;;
        4)
            echo "DATA: 获取股票数据 (Tushare)"
            $PYTHON_CMD scripts/fetch_data.py --source tushare
            exit 0
            ;;
        5)
            echo "DATA: 获取股票数据 (爬虫)"
            $PYTHON_CMD scripts/fetch_data.py --source crawler
            exit 0
            ;;
        6)
            echo "CHART: 批量获取数据、预测K线及综合排名分析"
            # 非交互模式：从环境变量获取参数
            if [[ "$BATCH_MODE" == "true" ]]; then
                symbols="${KRONOS_SYMBOLS:-}"
                days="${KRONOS_DAYS:-365}"
                if [[ -z "$symbols" ]]; then
                    echo "ERROR: 非交互模式下需要设置 KRONOS_SYMBOLS 环境变量"
                    exit 1
                fi
                echo "AUTO: 使用环境变量参数 - 股票: $symbols, 天数: $days"
            else
                read -p "请输入股票代码（多个代码用逗号分隔）: " symbols
                read -p "请输入要获取的天数（默认365天）: " days
                days=${days:-365}
            fi
            run_batch_predict_and_rank_analysis "$symbols" "$days"
            exit 0
            ;;
        7)
            limit="${KRONOS_OPPORTUNITY_LIMIT:-100}"
            source="${KRONOS_OPPORTUNITY_SOURCE:-heat}"
            echo "🔥 投资机会挖掘 - 分析TOP${limit}候选股票 (source=${source})"
            echo "正在启动投资机会挖掘系统..."
            $PYTHON_CMD scripts/run_opportunity_discovery.py --limit "$limit" --source "$source" --workers 10
            exit 0
            ;;
        8)
            echo "PREDICT: 运行预测示例"
            $PYTHON_CMD examples/prediction_example.py
            exit 0
            ;;
        9)
            limit="${KRONOS_OPPORTUNITY_LIMIT:-100}"
            source="${KRONOS_OPPORTUNITY_SOURCE:-heat}"
            echo "🔥 投资机会挖掘 - 分析TOP${limit}候选股票 (source=${source})"
            echo "正在启动投资机会挖掘系统..."
            $PYTHON_CMD scripts/run_opportunity_discovery.py --limit "$limit" --source "$source" --workers 10
            exit 0
            ;;
        10)
            echo "🔥🔥 重大利好消息挖掘 - 从资讯流挖掘投资机会"
            $PYTHON_CMD scripts/run_major_opportunity_discovery.py --limit 50 --workers 10
            exit 0
            ;;
        11)
            echo "CRAWLER: 安装 Playwright 浏览器"
            $PYTHON_CMD -m pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
            $PYTHON_CMD -m playwright install chromium
            exit 0
            ;;
        12)
            echo "CRAWLER: 测试爬虫功能"
            $PYTHON_CMD scripts/test_crawler.py
            exit 0
            ;;
        13)
            echo "WEB: 启动Web界面"
            cd webui && $PYTHON_CMD app.py
            exit 0
            ;;
        14)
            echo "INFO: 显示使用帮助"
            cat docs/README.md 2>/dev/null || echo "帮助文档未找到"
            exit 0
            ;;
        15)
            echo "INFO: 查看系统状态..."
            $PYTHON_CMD scripts/check_environment.py
            exit 0
            ;;
        *)
            echo "未知选项: $MENU_CHOICE"
            exit 1
            ;;
    esac
fi

# 交互模式：显示菜单并等待用户选择
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
    echo "6. 批量获取数据、预测K线及综合排名分析"
    echo "7. 🔥 投资机会挖掘 (多源综合: 热度+超跌反弹+资金流向)"
    echo ""
    echo "PREDICT: 预测功能"
    echo "8. 运行预测示例"
    echo ""
    echo "DISCOVERY: 机会挖掘"
    echo "9. 🔥 投资机会挖掘 (多源综合: 热度+超跌反弹+资金流向)"
    echo "10. 🔥🔥 重大利好消息挖掘 (从资讯流挖掘)"
    echo ""
echo "CRAWLER: 爬虫设置"
echo "11. 安装 Playwright 浏览器"
echo "12. 测试爬虫功能"
echo ""
echo "WEB: Web界面"
echo "13. 启动Web界面"
echo ""
echo "INFO:  帮助与信息"
echo "14. 显示使用帮助"
echo "15. 查看系统状态"
echo ""
echo "16. 退出"
    echo ""
    echo "TIP: 提示: 首次使用请先选择选项1进行一键安装"
    echo ""
    
    read -p "请选择操作 (1-16): " choice
    
    case $choice in
        1)
            echo "PACKAGE: 开始一键安装所有依赖和模型..."
            # Check python version
            $PYTHON_CMD --version
            echo "Installing dependencies..."
            # 使用 --user flag 解决 Python 3.12+ externally-managed-environment 限制
            $PYTHON_CMD -m pip install --user -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
            echo "Installing playwright..."
            $PYTHON_CMD -m pip install --user playwright -i https://pypi.tuna.tsinghua.edu.cn/simple
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
            echo "CHART: 批量获取数据、预测K线及综合排名分析"
            read -p "请输入股票代码（多个代码用逗号分隔）: " symbols
            read -p "请输入要获取的天数（默认365天）: " days
            days=${days:-365}
            run_batch_predict_and_rank_analysis "$symbols" "$days"

            pause
            ;;
        7)
            echo "🔥 投资机会挖掘 - 自定义候选来源与条数"
            read -p "是否开始投资机会挖掘？(Y/n): " confirm
            if [[ "$confirm" != "n" && "$confirm" != "N" ]]; then
                read -p "请输入分析条数（默认100）: " limit
                limit=${limit:-100}
                echo "候选来源：1) 多源综合(默认: 热度+超跌反弹+资金流向)  2) 仅热度榜  3) 资金流向榜单"
                read -p "请选择来源 (1/2/3): " source_choice
                source="multi"
                if [[ "$source_choice" == "2" ]]; then
                    source="heat"
                elif [[ "$source_choice" == "3" ]]; then
                    source="moneyflow_dc"
                fi
                echo "正在启动投资机会挖掘系统..."
                $PYTHON_CMD scripts/run_opportunity_discovery.py --limit "$limit" --source "$source" --workers 10
            fi
            pause
            ;;
        8)
            echo "PREDICT: 运行预测示例"
            $PYTHON_CMD examples/prediction_example.py
            pause
            ;;
        9)
            echo "🔥 投资机会挖掘 - 自定义候选来源与条数"
            read -p "是否开始投资机会挖掘？(Y/n): " confirm
            if [[ "$confirm" != "n" && "$confirm" != "N" ]]; then
                read -p "请输入分析条数（默认100）: " limit
                limit=${limit:-100}
                echo "候选来源：1) 多源综合(默认: 热度+超跌反弹+资金流向)  2) 仅热度榜  3) 资金流向榜单"
                read -p "请选择来源 (1/2/3): " source_choice
                source="multi"
                if [[ "$source_choice" == "2" ]]; then
                    source="heat"
                elif [[ "$source_choice" == "3" ]]; then
                    source="moneyflow_dc"
                fi
                echo "正在启动投资机会挖掘系统..."
                $PYTHON_CMD scripts/run_opportunity_discovery.py --limit "$limit" --source "$source" --workers 10
            fi
            pause
            ;;
        10)
            echo "🔥🔥 一体化深度发现系统 - 质量优先的智能投资机会挖掘"
            echo ""
            echo "✨ 全新升级特点："
            echo "  🎯 三模式融合：关键词+论坛+新闻三重验证"
            echo "  🔬 深度钻取：多轮深度分析确保质量"
            echo "  📊 质量优先：重点关注分析质量而非速度"
            echo "  🔗 交叉验证：多源信息交叉确认"
            echo "  🏆 并购分析：专门的并购重组全方位分析"
            echo ""
            echo "分析模式："
            echo "  1. 关键词深度模式 (推荐) - 基于权重关键词体系的深度挖掘"
            echo "  2. 论坛深度模式 - 基于多平台论坛的深度舆情分析"
            echo "  3. 新闻深度模式 - 基于新闻媒体的深度事件分析"
            echo ""
            echo "钻取深度选项："
            echo "  • 表层分析 (快速, 1-2分钟)"
            echo "  • 中等深度 (平衡, 3-5分钟)"
            echo "  • 深度分析 (推荐, 5-8分钟)"
            echo "  • 全面深度 (最详细, 10-15分钟)"
            echo ""
            echo "⚠️  注意：本系统注重分析质量，分析时间较长但结果更准确可靠"
            echo ""
            
            read -p "是否开始一体化深度发现？(Y/n): " confirm
            if [[ "$confirm" != "n" && "$confirm" != "N" ]]; then
                echo "正在启动一体化深度发现系统..."
                echo "系统将引导您选择具体参数..."
                $PYTHON_CMD scripts/run_integrated_discovery.py
            fi
            pause
            ;;
        11)
            echo "CRAWLER: 正在安装 Playwright 浏览器..."
            $PYTHON_CMD -m pip install playwright
            $PYTHON_CMD -m playwright install chromium
            pause
            ;;
        12)
            echo "TEST: 测试爬虫功能..."
            $PYTHON_CMD -c "import asyncio; from scripts.crawler import CrawlerManager; asyncio.run(CrawlerManager().test_connection())"
            pause
            ;;
        13)
            echo "WEB: 启动Web界面..."
            cd webui && $PYTHON_CMD app.py
            cd ..
            pause
            ;;
        14)
            echo "================================"
            echo "      Kronos 使用帮助 HELP:"
            echo "================================"
            echo ""
            echo "START: 快速开始："
            echo "  1. 运行 quick_start.sh"
            echo "  2. 选择 1 进行一键安装"
            echo "  3. 选择 2 配置数据源（需要Tushare Token）"
            echo "  4. 选择 7 或 9 运行投资机会挖掘"
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
            echo "DISCOVERY: 机会挖掘："
            echo "  - 投资机会挖掘: 分析TOP100热门股票的多维度指标"
            echo "  - 重大利好消息挖掘: 从资讯流中挖掘潜在投资机会"
            echo ""
            echo "WEB: Web界面："
            echo "  - 运行: cd webui && python app.py"
            echo "  - 访问: http://localhost:7070"
            echo ""
            pause
            ;;
        15)
            echo "系统状态检查 STATUS:"
            $PYTHON_CMD --version
            pip --version
            echo "Checking packages..."
            for pkg in torch pandas numpy matplotlib tqdm playwright; do
                $PYTHON_CMD -c "import $pkg" 2>/dev/null && echo "OK: $pkg" || echo "ERROR: $pkg missing"
            done
            pause
            ;;
        16)
            echo "BYE: 感谢使用 Kronos！再见！"
            exit 0
            ;;
        *)
            echo "无效输入，请输入 1-16 之间的数字"
            sleep 1
            ;;
    esac
done
