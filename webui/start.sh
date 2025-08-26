#!/bin/bash

# Kronos Web UI 启动脚本

echo "🚀 启动 Kronos Web UI..."
echo "================================"

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装Python3"
    exit 1
fi

# 检查是否在正确的目录
if [ ! -f "app.py" ]; then
    echo "❌ 请在webui目录下运行此脚本"
    exit 1
fi

# 检查依赖
echo "📦 检查依赖..."
if ! python3 -c "import flask, flask_cors, pandas, numpy, plotly" &> /dev/null; then
    echo "⚠️  缺少依赖，正在安装..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ 依赖安装失败"
        exit 1
    fi
    echo "✅ 依赖安装完成"
else
    echo "✅ 所有依赖已安装"
fi

# 启动应用
echo "🌐 启动Web服务器..."
echo "访问地址: http://localhost:7070"
echo "按 Ctrl+C 停止服务器"
echo ""

python3 app.py
