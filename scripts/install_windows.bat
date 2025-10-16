@echo off
chcp 65001 >nul
echo ========================================
echo     Kronos 金融预测模型一键安装脚本
echo ========================================
echo.

:: 检查 Python 是否安装
echo [1/6] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 Python，请先安装 Python 3.11 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python 环境检查通过

:: 检查 pip
echo [2/6] 检查 pip 包管理器...
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 错误: 未找到 pip
    pause
    exit /b 1
)
echo ✅ pip 检查通过

:: 升级 pip
echo [3/6] 升级 pip...
python -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo ⚠️  警告: pip 升级失败，继续安装...
)

:: 创建必要目录
echo [4/6] 创建项目目录...
if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "config" mkdir config
if not exist "scripts" mkdir scripts
if not exist "results" mkdir results
echo ✅ 目录创建完成

:: 安装依赖
echo [5/6] 安装 Python 依赖包...
echo 正在安装基础依赖...
pip install numpy pandas torch matplotlib tqdm safetensors einops huggingface_hub
if %errorlevel% neq 0 (
    echo ❌ 基础依赖安装失败，尝试使用国内镜像...
    pip install numpy pandas torch matplotlib tqdm safetensors einops huggingface_hub -i https://pypi.tuna.tsinghua.edu.cn/simple/
    if %errorlevel% neq 0 (
        echo ❌ 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)

echo 正在安装 Tushare...
pip install tushare
if %errorlevel% neq 0 (
    echo ⚠️  Tushare 安装失败，可以稍后手动安装
)

echo 正在安装可视化依赖...
pip install seaborn plotly
if %errorlevel% neq 0 (
    echo ⚠️  可视化依赖安装失败，基本功能不受影响
)

echo ✅ 依赖安装完成

:: 下载模型
echo [6/6] 准备下载预训练模型...
echo 注意: 模型文件较大，首次运行时会自动下载
echo 如果下载失败，请检查网络连接或稍后重试

:: 创建配置文件
echo 创建默认配置文件...
(
echo {
echo   "tushare": {
echo     "token": "请在此处填入您的Tushare Token",
echo     "timeout": 30,
echo     "retry_count": 3
echo   },
echo   "data_settings": {
echo     "output_dir": "./data/",
echo     "file_format": "csv",
echo     "date_format": "%%Y-%%m-%%d %%H:%%M:%%S"
echo   },
echo   "default_params": {
echo     "freq": "5min",
echo     "adj": "qfq",
echo     "start_date": "",
echo     "end_date": "20241231"
echo   }
echo }
) > config\tushare_config.json

echo.
echo ========================================
echo          🎉 安装完成！
echo ========================================
echo.
echo 下一步操作:
echo 1. 编辑 config\tushare_config.json 文件，填入您的 Tushare Token
echo 2. 运行 python scripts\fetch_data.py 获取数据
echo 3. 运行 python examples\prediction_example.py 开始预测
echo.
echo 获取 Tushare Token: https://tushare.pro/register
echo 完整文档: https://github.com/your-repo/kronos
echo.
pause
