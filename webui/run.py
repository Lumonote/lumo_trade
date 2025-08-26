#!/usr/bin/env python3
"""
Kronos Web UI 启动脚本
"""

import os
import sys
import subprocess
import webbrowser
import time

def check_dependencies():
    """检查依赖是否安装"""
    try:
        import flask
        import flask_cors
        import pandas
        import numpy
        import plotly
        print("✅ 所有依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        return False

def install_dependencies():
    """安装依赖"""
    print("正在安装依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ 依赖安装完成")
        return True
    except subprocess.CalledProcessError:
        print("❌ 依赖安装失败")
        return False

def main():
    """主函数"""
    print("🚀 启动 Kronos Web UI...")
    print("=" * 50)
    
    # 检查依赖
    if not check_dependencies():
        print("\n是否自动安装依赖? (y/n): ", end="")
        if input().lower() == 'y':
            if not install_dependencies():
                return
        else:
            print("请手动安装依赖后重试")
            return
    
    # 检查模型可用性
    try:
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from model import Kronos, KronosTokenizer, KronosPredictor
        print("✅ Kronos模型库可用")
        model_available = True
    except ImportError:
        print("⚠️  Kronos模型库不可用，将使用模拟预测")
        model_available = False
    
    # 启动Flask应用
    print("\n🌐 启动Web服务器...")
    
    # 设置环境变量
    os.environ['FLASK_APP'] = 'app.py'
    os.environ['FLASK_ENV'] = 'development'
    
    # 启动服务器
    try:
        from app import app
        print("✅ Web服务器启动成功!")
        print(f"🌐 访问地址: http://localhost:7070")
        print("💡 提示: 按 Ctrl+C 停止服务器")
        
        # 自动打开浏览器
        time.sleep(2)
        webbrowser.open('http://localhost:7070')
        
        # 启动Flask应用
        app.run(debug=True, host='0.0.0.0', port=7070)
        
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        print("请检查端口7070是否被占用")

if __name__ == "__main__":
    main()
