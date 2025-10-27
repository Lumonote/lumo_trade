@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
REM Kronos 快速启动脚本 (Windows版本)

REM 设置颜色
color 0A

REM 支持通过命令行参数直接选择菜单项（非交互模式）
if not "%~1"=="" (
    set choice=%~1
    goto valid_input
)

:main_menu
cls
echo ================================
echo     Kronos 股票预测系统 START:
echo ================================
echo 欢迎使用 Kronos！请选择您需要的操作：
echo.
echo PACKAGE: 系统设置
echo 1. 一键安装所有依赖 (Python包 + Playwright浏览器 + 模型)
echo 2. 配置数据源 (向导)
echo 3. 检查环境状态
echo.
echo DATA: 数据获取
echo 4. 获取股票数据 (Tushare)
echo 5. 获取股票数据 (爬虫)
echo 6. 批量获取数据及预测K线
echo 7. 🔥 投资机会挖掘 (TOP100热门股票)
echo.
echo PREDICT: 预测功能
echo 8. 运行预测示例
echo.
echo CRAWLER: 爬虫设置
echo 9. 安装 Playwright 浏览器
echo 10. 测试爬虫功能
echo.
echo WEB: Web界面
echo 11. 启动Web界面
echo.
echo INFO:  帮助与信息
echo 12. 显示使用帮助
echo 13. 查看系统状态
echo.
echo 14. 退出
echo.
echo TIP: 提示: 首次使用请先选择选项1进行一键安装
echo.

REM 输入验证循环
:input_validation
set /p choice=请选择操作 (1-14):
if "%choice%"=="" goto invalid_input
echo %choice%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 goto invalid_input
if %choice% geq 1 if %choice% leq 14 goto valid_input

:invalid_input
echo ERROR: 无效输入，请输入 1-14 之间的数字
goto input_validation

:valid_input
if "%choice%"=="1" goto install_all_deps
if "%choice%"=="2" goto config_wizard
if "%choice%"=="3" goto check_env
if "%choice%"=="4" goto fetch_tushare
if "%choice%"=="5" goto fetch_crawler
if "%choice%"=="6" goto batch_fetch
if "%choice%"=="7" goto opportunity_discovery
if "%choice%"=="8" goto run_prediction
if "%choice%"=="9" goto install_playwright
if "%choice%"=="10" goto test_crawler
if "%choice%"=="11" goto start_webui
if "%choice%"=="12" goto show_help
if "%choice%"=="13" goto show_system_status
if "%choice%"=="14" goto exit_script

:install_all_deps
echo PACKAGE: 开始一键安装所有依赖和模型...
echo.
echo STEP 步骤 0/4: 配置 Python 环境和清华镜像源...
echo.

REM 检查是否已安装 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: 未找到 Python，正在尝试安装...
    echo 请手动安装 Python 3.11.13 或更高版本
    echo 下载地址: https://www.python.org/downloads/
    pause
    goto main_menu
)

REM 获取当前 Python 版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set CURRENT_VERSION=%%i
echo 当前 Python 版本: %CURRENT_VERSION%

REM 检查版本是否符合要求 (3.11+)
for /f "tokens=1,2 delims=." %%a in ("%CURRENT_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

if %MAJOR% LSS 3 (
    echo ERROR: Python 版本过低，需要 3.11+
    pause
    goto main_menu
)
if %MAJOR% EQU 3 if %MINOR% LSS 11 (
    echo ERROR: Python 版本过低，需要 3.11+
    pause
    goto main_menu
)

echo OK: Python 版本检查通过！

REM 配置 pip 清华镜像源
echo 正在配置 pip 清华大学镜像源...
if not exist "%APPDATA%\pip" mkdir "%APPDATA%\pip"

echo [global] > "%APPDATA%\pip\pip.ini"
echo index-url = https://pypi.tuna.tsinghua.edu.cn/simple/ >> "%APPDATA%\pip\pip.ini"
echo trusted-host = pypi.tuna.tsinghua.edu.cn >> "%APPDATA%\pip\pip.ini"

if exist "%APPDATA%\pip\pip.ini" (
    echo OK: pip 清华镜像源配置完成！
) else (
    echo ERROR: pip 镜像源配置失败
    pause
    goto main_menu
)

REM 升级 pip
echo 正在升级 pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo WARN:  pip 升级失败，继续使用当前版本
) else (
    echo OK: pip 升级完成！
)

echo OK: Python 环境和镜像源配置完成！
echo.
echo STEP 步骤 1/4: 验证 Python 环境...

echo STEP 步骤 2/4: 正在安装 Python 依赖包...
if exist "requirements.txt" (
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
    if errorlevel 1 (
        echo ERROR: Python 依赖包安装失败
        echo TIP: 提示: 已配置清华镜像源，如仍失败请检查网络连接
        pause
        goto main_menu
    )
    echo OK: Python 依赖处理完成（如看到 "Requirement already satisfied" 表示依赖已存在）
) else (
    echo ERROR: 未找到 requirements.txt 文件
    pause
    goto main_menu
)

echo STEP 步骤 3/4: 配置 Playwright 浏览器环境...
echo 这可能需要几分钟时间，请耐心等待...
call :get_package_version playwright PLAYWRIGHT_VERSION
if defined PLAYWRIGHT_VERSION (
    echo SKIP:  Playwright 已安装 (版本 !PLAYWRIGHT_VERSION!)，跳过包安装
) else (
    echo ACTION:  正在安装 Playwright Python 包...
    python -m pip install playwright -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
    if errorlevel 1 (
        echo WARN:  Playwright 安装失败，但继续安装其他组件
        set "PLAYWRIGHT_VERSION="
    ) else (
        call :get_package_version playwright PLAYWRIGHT_VERSION
        if defined PLAYWRIGHT_VERSION (
            echo OK: Playwright 安装完成 (版本 !PLAYWRIGHT_VERSION!)
        ) else (
            echo OK: Playwright 安装完成
        )
    )
)

if defined PLAYWRIGHT_VERSION (
    echo ACTION:  正在安装/刷新 Playwright 浏览器 (chromium)...
    python -m playwright install chromium
    if errorlevel 1 (
        echo WARN:  Chromium 浏览器资源安装失败，可稍后手动运行 "playwright install chromium"
    ) else (
        echo OK: Chromium 浏览器资源已就绪
    )
) else (
    echo WARN:  未检测到 Playwright 包，跳过浏览器资源安装
)

echo STEP 步骤 4/4: 准备 ModelScope 模型下载...
call :get_package_version modelscope MODELSCOPE_VERSION
if defined MODELSCOPE_VERSION (
    echo SKIP:  ModelScope 已安装 (版本 !MODELSCOPE_VERSION!)，跳过包安装
) else (
    echo ACTION:  正在安装 ModelScope SDK...
    python -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
    if errorlevel 1 (
        echo WARN:  ModelScope 安装失败，跳过模型下载
        set "MODELSCOPE_VERSION="
    ) else (
        call :get_package_version modelscope MODELSCOPE_VERSION
        if defined MODELSCOPE_VERSION (
            echo OK: ModelScope 安装完成 (版本 !MODELSCOPE_VERSION!)
        ) else (
            echo OK: ModelScope 安装完成
        )
    )
)

if defined MODELSCOPE_VERSION (
    echo 正在下载模型文件，这可能需要较长时间，请耐心等待...
    if not exist "models" mkdir models

    echo 请选择要下载的模型：
    echo 1. Kronos 完整模型套件 (推荐)
    echo 2. Chronos-T5-Small 轻量级模型
    echo 3. 下载所有模型
    echo 4. 跳过模型下载
    set /p model_choice=请选择 (1-4, 默认1): 
    if "%model_choice%"=="" set model_choice=1

    if "%model_choice%"=="1" (
        call :download_model_with_retry "northwind9898/Kronos-Tokenizer-base" "./models/Kronos-Tokenizer-base" "Kronos Tokenizer"
        call :download_model_with_retry "northwind9898/Kronos-small" "./models/Kronos-small" "Kronos 模型"
    ) else if "%model_choice%"=="2" (
        echo 正在下载 Chronos-T5-Small 模型...
        modelscope download --model AI-ModelScope/chronos-t5-small --local_dir ./models/chronos-t5-small
        if errorlevel 1 (
            echo WARN: Chronos-T5-Small 模型下载失败
            echo 提示: 您可以稍后手动运行以下命令下载：
            echo modelscope download --model AI-ModelScope/chronos-t5-small --local_dir ./models/chronos-t5-small
        ) else (
            echo OK: Chronos-T5-Small 模型下载完成！
        )
    ) else if "%model_choice%"=="3" (
        call :download_model_with_retry "northwind9898/Kronos-Tokenizer-base" "./models/Kronos-Tokenizer-base" "Kronos Tokenizer"
        call :download_model_with_retry "northwind9898/Kronos-small" "./models/Kronos-small" "Kronos 模型"
        echo 正在下载 Chronos-T5-Small 模型...
        modelscope download --model AI-ModelScope/chronos-t5-small --local_dir ./models/chronos-t5-small
        if errorlevel 1 (
            echo WARN: Chronos-T5-Small 模型下载失败
        ) else (
            echo OK: Chronos-T5-Small 模型下载完成！
        )
    ) else if "%model_choice%"=="4" (
        echo SKIP: 跳过模型下载
    )

    echo OK: ModelScope 模型下载流程完成！
    echo DONE: 所有依赖和模型安装完成！系统已准备就绪！
) else (
    echo WARN:  ModelScope 未安装成功，跳过模型下载
)

pause
goto main_menu

:config_wizard
echo STEP 启动配置向导...
python scripts/config_wizard.py
pause
goto main_menu

:check_env
echo CHECK: 检查环境状态...
python scripts/check_environment.py
pause
goto main_menu

:batch_fetch
echo CHART: 批量获取数据及预测K线
echo.

REM 股票代码输入
echo 请输入股票代码（多个代码用逗号分隔，例如：000001.SZ,600000.SH）：
:batch_symbols_input
set /p symbols=股票代码: 
if "%symbols%"=="" (
    echo ERROR: 股票代码不能为空
    goto batch_symbols_input
)

REM 数据源选择
echo.
echo 请选择数据源：
echo   1. 自动选择最佳数据源 (推荐)
echo   2. Tushare API
echo   3. 网络爬虫

:batch_source_input
set /p source_choice=请选择 (1-3, 默认1): 
if "%source_choice%"=="" set source_choice=1
if %source_choice% geq 1 if %source_choice% leq 3 goto valid_batch_source
echo ERROR: 请输入 1-3 之间的数字
goto batch_source_input

:valid_batch_source
if "%source_choice%"=="1" set source=auto
if "%source_choice%"=="2" set source=tushare
if "%source_choice%"=="3" set source=crawler

REM 获取天数
echo.
:batch_days_input
set /p days=请输入要获取的天数（默认365天）: 
if "%days%"=="" set days=365

echo.
echo 正在批量获取 %symbols% 的数据（使用 %source% 数据源，获取 %days% 天数据）...

REM 批量获取数据
python scripts/batch_fetch.py --symbols %symbols% --min-days %days% --config config/tushare_config.json
if errorlevel 1 (
    echo ERROR: 数据获取失败
    pause
    goto main_menu
)

echo OK: 数据获取完成！

REM 从输入的股票代码中提取第一个进行预测演示
for /f "tokens=1 delims=," %%a in ("%symbols%") do set first_symbol=%%a

REM 移除交易所后缀，只保留股票代码部分
for /f "tokens=1 delims=." %%b in ("%first_symbol%") do set clean_symbol=%%b

echo.
echo PREDICT: 开始运行预测...
echo 使用股票 %clean_symbol% 进行预测演示
echo 预测完成后将自动生成HTML综合分析报告并打开浏览器
REM 使用代码中的默认参数：T=0.8, p=0.90, n=3
python examples/prediction_batch_example.py --stock-code %clean_symbol%
if errorlevel 1 (
    echo WARN: 预测运行失败，但数据已成功获取
) else (
    echo OK: 批量预测完成！
    echo REPORT: HTML分析报告已自动生成到results目录
)

pause
goto main_menu

:opportunity_discovery
echo 🔥 投资机会挖掘 - 分析TOP100热门股票
echo.
echo 本功能将自动完成以下流程：
echo   1. 获取市场热度TOP100股票
echo   2. 多维度打分分析（量化模型、技术、情绪、板块、基本面、事件）
echo   3. 5阶段漏斗筛选
echo   4. 生成HTML投资机会挖掘报告
echo.
echo 注意：此过程可能需要15-30分钟，请耐心等待...
echo.

set /p confirm=是否开始投资机会挖掘？(Y/n):
if /i "%confirm%"=="n" goto main_menu

echo 正在启动投资机会挖掘系统...
python scripts/run_opportunity_discovery.py --limit 100 --workers 10
if errorlevel 1 (
    echo ERROR: 投资机会挖掘执行失败
) else (
    echo OK: 投资机会挖掘完成！报表已生成到results目录
)
pause
goto main_menu

:run_prediction
echo PREDICT: 运行预测示例
python examples/prediction_example.py
pause
goto main_menu

:install_playwright
echo CRAWLER: 正在安装 Playwright 浏览器...
echo 这可能需要几分钟时间，请耐心等待...
pip install playwright
if errorlevel 1 (
    echo ERROR: Playwright 安装失败
    pause
    goto main_menu
)
playwright install chromium
if errorlevel 1 (
    echo ERROR: Playwright 浏览器安装失败
    pause
    goto main_menu
)
echo OK: Playwright 浏览器安装完成！
pause
goto main_menu

:test_crawler
echo TEST: 测试爬虫功能...
python -c "import asyncio; from scripts.crawler import CrawlerManager; asyncio.run(CrawlerManager().test_connection())"
pause
goto main_menu

:exit_script
echo BYE: 感谢使用 Kronos！再见！
exit /b 0

:show_help
cls
echo ================================
echo      Kronos 使用帮助 HELP:
echo ================================
echo.
echo START: 快速开始：
echo   1. 运行 quick_start.bat
echo   2. 选择“1”进行一键安装
echo   3. 选择“2”配置数据源（需要Tushare Token）
echo   4. 选择“7”运行预测示例
echo.
echo DATA: 数据源配置：
echo   - Tushare: 需要注册账号获取Token (https://tushare.pro/)
echo   - 爬虫: 自动从金融网站获取数据，无需注册
echo.
echo CHART: 股票代码格式：
echo   - Tushare: 000001.SZ (深交所) 或 600000.SH (上交所)
echo   - 爬虫: 000001 (6位数字)
echo.
echo PREDICT: 预测功能：
echo   - 支持OHLCV数据预测
echo   - 可调节预测长度和采样参数
echo   - 支持批量预测多只股票
echo.
echo WEB: Web界面：
echo   - 运行: cd webui ^&^& python app.py
echo   - 访问: http://localhost:7070
echo.
echo DIR: 重要文件：
echo   - requirements.txt: Python依赖
echo   - config/tushare_config.json: Tushare配置
echo   - config/crawler_config.json: 爬虫配置
echo   - models/: 模型文件目录
echo   - data/: 数据文件目录
echo.
echo STEP 故障排除：
echo   - Python版本需求: 3.11+
echo   - 网络问题: 使用国内镜像源
echo   - 模型下载失败: 检查网络或手动下载
echo   - 爬虫被封: 调整延时或更换User-Agent
echo.
echo DOCS: 更多文档：
echo   - README.md: 详细使用说明
echo   - QUICK_START_GUIDE.md: 快速上手指南
echo   - TROUBLESHOOTING.md: 问题解决指南
echo.
pause
goto main_menu

:show_system_status
cls
echo ================================
echo       系统状态检查 STATUS:
echo ================================
echo.
echo PYTHON: Python 环境：
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python 未安装
) else (
    for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo   OK: %%i
)

echo PACKAGE: 包管理器：
pip --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: pip 未安装
) else (
    for /f "tokens=1,2" %%i in ('pip --version 2^>^&1') do echo   OK: %%i %%j
)

echo DOCS: 关键依赖包：
for %%p in (torch pandas numpy matplotlib tqdm) do (
    python -c "import %%p" >nul 2>&1
    if errorlevel 1 (
        echo   ERROR: %%p 未安装
    ) else (
        echo   OK: %%p 已安装
    )
)

echo CRAWLER:  Playwright：
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Playwright 未安装
) else (
    echo   OK: Playwright 已安装
    playwright --version >nul 2>&1
    if errorlevel 1 (
        echo   WARN:  Playwright CLI 不可用
    ) else (
        echo   OK: Playwright CLI 可用
    )
)

echo MODELSCOPE: ModelScope：
python -c "import modelscope" >nul 2>&1
if errorlevel 1 (
    echo   ERROR: ModelScope 未安装
) else (
    echo   OK: ModelScope 已安装
)

echo MODEL: 模型文件：
if exist "models" (
    set model_count=0
    for /r models %%f in (*.safetensors *.bin) do set /a model_count+=1
    if !model_count! gtr 0 (
        echo   OK: 发现 !model_count! 个模型文件
        for /d %%d in (models\*) do (
            for %%f in ("%%d") do echo     DIR: %%~nxf
        )
    ) else (
        echo   WARN:  未发现模型文件
    )
) else (
    echo   ERROR: models目录不存在
)

echo ACTION:  配置文件：
if exist "config\tushare_config.json" (
    echo   OK: Tushare配置文件存在
) else (
    echo   WARN:  Tushare配置文件不存在
)

if exist "config\crawler_config.json" (
    echo   OK: 爬虫配置文件存在
) else (
    echo   WARN:  爬虫配置文件不存在
)

echo DISK: 磁盘空间：
for /f "tokens=3" %%i in ('dir /-c ^| find "可用字节"') do echo   FOLDER: 可用空间: %%i 字节

echo.
pause
goto main_menu

:fetch_tushare
echo DATA: 使用 Tushare 获取股票数据

:tushare_input_loop
set /p symbol=请输入股票代码 (格式: 000001.SZ): 
if "%symbol%"=="" (
    echo ERROR: 股票代码不能为空
    goto tushare_input_loop
)

REM 验证Tushare格式 (6位数字.SZ或SH)
echo %symbol%| findstr /r "^[0-9][0-9][0-9][0-9][0-9][0-9]\.(SZ|SH)$" >nul
if errorlevel 1 (
    echo ERROR: 股票代码格式错误，请使用格式: 000001.SZ 或 600000.SH
    echo TIP: 提示: SZ=深交所, SH=上交所
    goto tushare_input_loop
)

echo 正在获取 %symbol% 的数据...
python scripts/fetch_data.py --symbol %symbol% --source tushare
pause
goto main_menu

:fetch_crawler
echo CRAWLER: 使用爬虫获取股票数据
echo 可选数据源:
echo   1. 自动选择最佳爬虫源
echo   2. 东方财富 (eastmoney)
echo   3. 同花顺 (tonghuashun)
echo   4. 雪球 (xueqiu)

:crawler_source_input
set /p source_choice=请选择数据源 (1-4, 默认1): 
if "%source_choice%"=="" set source_choice=1
if %source_choice% geq 1 if %source_choice% leq 4 goto valid_source
echo ERROR: 请输入 1-4 之间的数字
goto crawler_source_input

:valid_source
:crawler_symbol_input
set /p symbol=请输入股票代码 (格式: 000001): 
if "%symbol%"=="" (
    echo ERROR: 股票代码不能为空
    goto crawler_symbol_input
)

REM 验证6位数字格式
echo %symbol%| findstr /r "^[0-9][0-9][0-9][0-9][0-9][0-9]$" >nul
if errorlevel 1 (
    echo ERROR: 股票代码格式错误，请输入6位数字
    echo TIP: 示例: 000001, 600000, 300001
    goto crawler_symbol_input
)

if "%source_choice%"=="1" set source=auto
if "%source_choice%"=="2" set source=eastmoney
if "%source_choice%"=="3" set source=tonghuashun
if "%source_choice%"=="4" set source=xueqiu

echo 使用 %source% 数据源获取 %symbol% 的数据，请稍候...
python scripts/fetch_data.py --symbol %symbol% --source %source%
pause
goto main_menu

:start_webui
echo WEB: 启动Web界面...
echo 正在检查Web界面依赖...
python -c "import flask, flask_cors, pandas, numpy, plotly" >nul 2>&1
if errorlevel 1 (
    echo WARN:  缺少Web界面依赖，正在安装...
    if exist "webui\requirements.txt" (
        pip install -r webui\requirements.txt
        if errorlevel 1 (
            echo ERROR: Web界面依赖安装失败
            pause
            goto main_menu
        )
        echo OK: 依赖安装完成
    ) else (
        echo ERROR: 未找到 webui\requirements.txt 文件
        pause
        goto main_menu
    )
)

echo.
echo WEB: 启动Web服务器...
echo 访问地址: http://localhost:7070
echo 按 Ctrl+C 停止服务器
echo.
if exist "webui\app.py" (
    cd webui
    python app.py
    cd..
) else (
    echo ERROR: 未找到 webui\app.py 文件
)
pause
goto main_menu

:get_package_version
setlocal EnableDelayedExpansion
set "pkg=%~1"
set "version="
for /f "tokens=2 delims=: " %%v in ('python -m pip show %pkg% 2^>nul ^| findstr /r "^Version"') do set "version=%%v"
endlocal & set "%~2=%version%"
exit /b

REM 模型下载重试函数
:download_model_with_retry
set model_id=%~1
set local_dir=%~2
set model_name=%~3
set max_retries=3
set retry_count=0

echo 正在下载 %model_name%...

:retry_loop
if %retry_count% gtr 0 (
    echo WARN:  重试下载 %model_name% (%retry_count%/%max_retries%)...
    timeout /t 5 >nul
)

modelscope download --model %model_id% --local_dir %local_dir%
if errorlevel 0 (
    echo OK: %model_name% 下载完成！
    goto :eof
)

set /a retry_count+=1
if %retry_count% lss %max_retries% goto retry_loop

echo ERROR: %model_name% 下载失败（已重试 %max_retries% 次）
echo TIP: 备选方案：
echo   1. 检查网络连接后重新运行此脚本
echo   2. 手动下载命令: modelscope download --model %model_id% --local_dir %local_dir%
echo   3. 从 Hugging Face 下载相应模型

set /p continue_install=是否继续安装其他组件？(Y/n): 
if /i "%continue_install%"=="n" exit /b 1
goto :eof
