#!/bin/bash
# Kronos macOS 终端启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$(dirname "$0")"
APP_DIR="$SCRIPT_DIR/../MacOS"

# 确保在终端中运行
if [ -z "$TERM" ]; then
    # 如果不在终端中，使用Terminal.app启动
    osascript -e "tell application \"Terminal\" to do script \"cd '$SCRIPT_DIR' && bash '$0'\""
    exit 0
fi

echo "🚀 启动 Kronos 金融预测系统..."
echo "按 Ctrl+C 退出程序"
echo ""

# 运行主程序
exec "$APP_DIR/Kronos"