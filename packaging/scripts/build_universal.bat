@echo off
chcp 65001 >nul

REM Kronos Windows打包工具 - 增强版
REM 支持本地构建和Docker构建

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\.."

echo [*] Kronos Windows打包工具
echo ========================
echo [DIR] 项目根目录: %PROJECT_ROOT%
echo.

REM 显示使用帮助
if "%1"=="" goto show_help
if "%1"=="--help" goto show_help
if "%1"=="-h" goto show_help
if "%1"=="/?" goto show_help
goto parse_args

:show_help
echo 使用方法: %0 [平台] [选项]
echo.
echo 支持的平台:
echo   windows        - 构建Windows版本 (本地构建)
echo   windows-docker - 使用Docker构建Windows版本
echo   windows-wine   - 使用Wine构建Windows版本
echo   macos-docker   - 使用Docker构建macOS版本
echo   linux-docker   - 使用Docker构建Linux版本
echo   all            - 构建所有平台版本
echo.
echo 选项:
echo   --docker       - 强制使用Docker构建
echo   --clean        - 构建前清理
echo   --help, -h, /? - 显示此帮助
echo.
echo 示例:
echo   %0 windows                  # 构建Windows版本
echo   %0 windows-docker           # 使用Docker构建Windows版本
echo   %0 all --clean              # 清理后构建所有版本
echo.
goto end

:parse_args
set "PLATFORM=%1"
set "USE_DOCKER=false"
set "CLEAN_BUILD=false"

:parse_loop
shift
if "%1"=="" goto main_logic
if "%1"=="--docker" (
    set "USE_DOCKER=true"
    goto parse_loop
)
if "%1"=="--clean" (
    set "CLEAN_BUILD=true"
    goto parse_loop
)
echo [X] 未知选项: %1
goto show_help

:main_logic
echo [PC]  当前操作系统: windows
echo.

REM 清理函数
:clean_build
if "%CLEAN_BUILD%"=="false" goto check_python
echo [CLEAN] 清理构建目录...

REM 清理Python缓存
for /d /r "%PROJECT_ROOT%" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)
for /r "%PROJECT_ROOT%" %%f in (*.pyc) do (
    if exist "%%f" del /q "%%f" 2>nul
)

REM 清理构建目录
if exist "%PROJECT_ROOT%\build" rmdir /s /q "%PROJECT_ROOT%\build" 2>nul
if exist "%PROJECT_ROOT%\dist" rmdir /s /q "%PROJECT_ROOT%\dist" 2>nul
del /q "%PROJECT_ROOT%\*.spec" 2>nul

echo [OK] 清理完成
goto check_python

:check_python
echo [CHECK] 检查Python环境...

set "PYTHON_CMD="
for %%p in (python3.11 python3 python) do (
    where %%p >nul 2>&1
    if !errorlevel! == 0 (
        for /f "tokens=*" %%v in ('%%p --version 2^>^&1') do (
            echo %%v | findstr "3.11" >nul
            if !errorlevel! == 0 (
                set "PYTHON_CMD=%%p"
                goto python_found
            )
            if "!PYTHON_CMD!"=="" (
                echo %%v | findstr "3\." >nul
                if !errorlevel! == 0 (
                    set "PYTHON_CMD=%%p"
                )
            )
        )
    )
)

:python_found
if "%PYTHON_CMD%"=="" (
    echo [X] 未找到Python 3.x
    echo [TIP] 请安装Python 3.11或更高版本
    exit /b 1
)

for /f "tokens=*" %%v in ('%PYTHON_CMD% --version 2^>^&1') do echo [Python] 使用Python版本: %%v
echo [OK] Python环境检查完成

:check_docker
if "%USE_DOCKER%"=="false" if not "%PLATFORM%"=="windows-docker" if not "%PLATFORM%"=="macos-docker" if not "%PLATFORM%"=="linux-docker" if not "%PLATFORM%"=="windows-wine" goto prepare_resources
echo [Docker] 检查Docker环境...

where docker >nul 2>&1
if errorlevel 1 (
    echo [X] Docker未安装
    echo [TIP] 请安装Docker Desktop: https://www.docker.com/products/docker-desktop
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [X] Docker daemon未运行
    echo [TIP] 请启动Docker Desktop
    exit /b 1
)

echo [OK] Docker环境检查完成
goto prepare_resources

:prepare_resources
echo [DIR] 准备资源文件 (modern版本)...
echo [GUI] 使用现代化GUI版本
echo [OK] 资源文件准备完成

REM 根据平台选择构建方法
if "%PLATFORM%"=="windows" goto build_windows
if "%PLATFORM%"=="windows-docker" goto build_windows_docker
if "%PLATFORM%"=="windows-wine" goto build_windows_wine
if "%PLATFORM%"=="macos-docker" goto build_macos_docker
if "%PLATFORM%"=="linux-docker" goto build_linux_docker
if "%PLATFORM%"=="all" goto build_all

echo [X] 不支持的平台: %PLATFORM%
goto show_help

:build_windows
echo [WIN][COMP] 开始打包Windows版本...
echo ==========================================

cd /d "%PROJECT_ROOT%"

REM 检查并导入Python检测器
echo [FIND] 检查Python环境...
%PYTHON_CMD% -c "import sys; sys.path.append('tools'); from python_detector import get_python_detector, verify_python_environment; detector = get_python_detector(); print(f'检测到Python命令: {detector.get_command()}'); verify_python_environment()"
if errorlevel 1 (
    echo [X] Python环境检查失败
    exit /b 1
)

REM 检查PyInstaller
%PYTHON_CMD% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [PKG] 安装PyInstaller...
    %PYTHON_CMD% -m pip install PyInstaller
    if errorlevel 1 (
        echo [X] PyInstaller安装失败
        exit /b 1
    )
)

REM 运行PyInstaller
echo [BUILD] 执行PyInstaller构建...
%PYTHON_CMD% -m PyInstaller --clean --noconfirm packaging\scripts\kronos_windows.spec
if errorlevel 1 (
    echo [X] Windows构建失败
    exit /b 1
)

echo [OK] Windows版本构建完成
echo [DIR] 输出位置: %PROJECT_ROOT%\dist\
goto end

:build_windows_docker
echo [WIN][Docker] 开始Windows Docker构建...
echo ==========================================
echo [MAKE] 构建Windows Docker镜像...

cd /d "%PROJECT_ROOT%"
docker build -f packaging\docker\Dockerfile.windows -t kronos-windows .
if errorlevel 1 (
    echo [X] Windows Docker构建失败
    exit /b 1
)

echo [*] 运行Windows Docker容器...
docker run --rm -v "%PROJECT_ROOT%\dist":/output kronos-windows
if errorlevel 1 (
    echo [X] Windows Docker运行失败
    exit /b 1
)

echo [OK] Windows Docker构建完成
echo [DIR] 输出位置: %PROJECT_ROOT%\dist\
goto end

:build_windows_wine
echo [Wine][WIN] 开始Windows Wine构建...
echo ==========================================
echo [MAKE] 构建Wine Docker镜像...

cd /d "%PROJECT_ROOT%"
docker build -f packaging\docker\Dockerfile.windows-wine -t kronos-wine .
if errorlevel 1 (
    echo [X] Wine Docker构建失败
    exit /b 1
)

echo [*] 运行Wine Docker容器...
docker run --rm -v "%PROJECT_ROOT%\dist":/output kronos-wine
if errorlevel 1 (
    echo [X] Wine Docker运行失败
    exit /b 1
)

echo [OK] Wine构建完成
echo [DIR] 输出位置: %PROJECT_ROOT%\dist\
goto end

:build_macos_docker
echo [MAC][Docker] 开始macOS Docker构建...
echo ==========================================
echo [WARN]  注意: macOS Docker构建需要特殊许可
echo [TIP] 建议在macOS系统上使用本地构建
goto end

:build_linux_docker
echo [Linux][Docker] 开始Linux Docker构建...
echo ==========================================
echo [MAKE] 构建Linux Docker镜像...

cd /d "%PROJECT_ROOT%"
docker build -f packaging\docker\Dockerfile.linux -t kronos-linux .
if errorlevel 1 (
    echo [X] Linux Docker构建失败
    exit /b 1
)

echo [*] 运行Linux Docker容器...
docker run --rm -v "%PROJECT_ROOT%\dist":/output kronos-linux
if errorlevel 1 (
    echo [X] Linux Docker运行失败
    exit /b 1
)

echo [OK] Linux Docker构建完成
echo [DIR] 输出位置: %PROJECT_ROOT%\dist\
goto end

:build_all
echo [ALL] 开始构建所有平台版本...
echo ==========================================

call :build_windows
if errorlevel 1 goto end

call :build_windows_docker  
if errorlevel 1 goto end

call :build_linux_docker
if errorlevel 1 goto end

echo [OK] 所有平台构建完成
echo [DIR] 输出位置: %PROJECT_ROOT%\dist\
goto end

:end
pause