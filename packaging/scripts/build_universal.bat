@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Lumo Trade Windows release build.
REM This intentionally mirrors the macOS path: PyInstaller WebUI backend + Tauri shell.

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "CLEAN_BUILD=false"

if /I "%~1"=="windows" shift

:parse_args
if "%~1"=="" goto configure
if /I "%~1"=="--clean" (
    set "CLEAN_BUILD=true"
    shift
    goto parse_args
)
if /I "%~1"=="--help" goto show_help
if /I "%~1"=="-h" goto show_help
if /I "%~1"=="/?" goto show_help
echo [ERROR] Unsupported option: %~1
goto show_help_error

:show_help
echo Usage: %~nx0 [windows] [--clean]
echo.
echo Builds the same Lumo Trade Tauri/WebUI desktop application as macOS.
echo Docker/Wine legacy GUI packages are not release-compatible and are disabled.
exit /b 0

:show_help_error
echo Usage: %~nx0 [windows] [--clean]
exit /b 2

:configure
cd /d "%PROJECT_ROOT%"
echo [Lumo Trade] Windows Tauri release build
echo [ROOT] %PROJECT_ROOT%

set "PYTHON_CMD="
if exist "%PROJECT_ROOT%\.venv\Scripts\python.exe" set "PYTHON_CMD=%PROJECT_ROOT%\.venv\Scripts\python.exe"
if not defined PYTHON_CMD if exist "%PROJECT_ROOT%\venv\Scripts\python.exe" set "PYTHON_CMD=%PROJECT_ROOT%\venv\Scripts\python.exe"
if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] Python 3.11+ was not found.
    exit /b 1
)

%PYTHON_CMD% -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11+ is required.
    exit /b 1
)

if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
if defined CARGO_HOME if exist "%CARGO_HOME%\bin\cargo.exe" set "PATH=%CARGO_HOME%\bin;%PATH%"
where cargo >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Rust/Cargo was not found.
    echo [TIP] Install Rustup: winget install --id Rustlang.Rustup -e
    echo [TIP] Then reopen PowerShell and run this build command again.
    exit /b 1
)
if exist "%ProgramFiles%\nodejs\npm.cmd" set "PATH=%ProgramFiles%\nodejs;%PATH%"
if exist "%LOCALAPPDATA%\Programs\nodejs\npm.cmd" set "PATH=%LOCALAPPDATA%\Programs\nodejs;%PATH%"
if exist "%USERPROFILE%\.volta\bin\npm.cmd" set "PATH=%USERPROFILE%\.volta\bin;%PATH%"
if defined NVM_SYMLINK if exist "%NVM_SYMLINK%\npm.cmd" set "PATH=%NVM_SYMLINK%;%PATH%"
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js/npm was not found.
    echo [TIP] Install Node.js LTS: winget install --id OpenJS.NodeJS.LTS -e
    echo [TIP] Then reopen PowerShell and run this build command again.
    exit /b 1
)

if defined VSCMD_VER (
    where link.exe >nul 2>&1
    if not errorlevel 1 goto msvc_ready
)

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" set "VSWHERE=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VS_INSTALL="
if exist "%VSWHERE%" for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VS_INSTALL=%%I"
if exist "%VSWHERE%" if not defined VS_INSTALL for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -property installationPath`) do set "VS_INSTALL=%%I"
if not defined VS_INSTALL if exist "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools" set "VS_INSTALL=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools"
if not defined VS_INSTALL if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Community" set "VS_INSTALL=%ProgramFiles%\Microsoft Visual Studio\2022\Community"
if not defined VS_INSTALL if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Professional" set "VS_INSTALL=%ProgramFiles%\Microsoft Visual Studio\2022\Professional"
if not defined VS_INSTALL if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise" set "VS_INSTALL=%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise"
if not defined VS_INSTALL goto msvc_not_installed

echo [MSVC] Visual Studio installation: %VS_INSTALL%
set "VS_ARCH=x64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "VS_ARCH=arm64"
set "VCVARSALL=%VS_INSTALL%\VC\Auxiliary\Build\vcvarsall.bat"
if exist "%VCVARSALL%" (
    call "%VCVARSALL%" %VS_ARCH%
) else (
    set "VSDEVCMD=%VS_INSTALL%\Common7\Tools\VsDevCmd.bat"
    if not exist "%VS_INSTALL%\Common7\Tools\VsDevCmd.bat" goto msvc_workload_missing
    call "%VS_INSTALL%\Common7\Tools\VsDevCmd.bat" -no_logo -arch=%VS_ARCH% -host_arch=%VS_ARCH%
)
if errorlevel 1 goto msvc_workload_missing
where link.exe >nul 2>&1
if errorlevel 1 goto msvc_workload_missing
for /f "delims=" %%L in ('where link.exe') do echo [MSVC] Linker: %%L
goto msvc_ready

:msvc_not_installed
echo [ERROR] Visual Studio Build Tools was not found.
echo [TIP] Install Visual Studio 2022 Build Tools with Desktop development with C++:
echo [TIP] winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --passive --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
echo [TIP] Then reopen PowerShell and run this build command again.
exit /b 1

:msvc_workload_missing
echo [ERROR] Visual Studio was found, but the MSVC linker link.exe is unavailable.
echo [TIP] Open Visual Studio Installer, select Modify, and enable Desktop development with C++.
echo [TIP] Ensure MSVC v143 and a Windows 10 or Windows 11 SDK are selected.
exit /b 1

:msvc_ready

set "TAURI_CLI=%PROJECT_ROOT%\node_modules\.bin\tauri.cmd"
if not exist "%TAURI_CLI%" goto install_tauri_dependencies
call "%TAURI_CLI%" --version >nul 2>&1
if errorlevel 1 goto install_tauri_dependencies
goto tauri_dependencies_ready

:install_tauri_dependencies
echo [DEPS] Installing Windows Tauri CLI dependencies...
call npm install --include=optional
if errorlevel 1 exit /b 1
if not exist "%TAURI_CLI%" (
    echo [ERROR] Tauri CLI command was not created: %TAURI_CLI%
    exit /b 1
)
call "%TAURI_CLI%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Windows Tauri CLI could not start after npm install.
    exit /b 1
)

:tauri_dependencies_ready

if not defined KRONOS_BACKEND_BUNDLE_MODE set "KRONOS_BACKEND_BUNDLE_MODE=lite"
if not defined KRONOS_WEB_SERVER set "KRONOS_WEB_SERVER=robyn"

if /I "%CLEAN_BUILD%"=="true" (
    echo [CLEAN] Removing previous Windows bundle output...
    if exist "%PROJECT_ROOT%\src-tauri\target\release\bundle\msi" rmdir /s /q "%PROJECT_ROOT%\src-tauri\target\release\bundle\msi"
    if exist "%PROJECT_ROOT%\src-tauri\target\release\bundle\nsis" rmdir /s /q "%PROJECT_ROOT%\src-tauri\target\release\bundle\nsis"
)

echo [BACKEND] Building bundled Robyn backend (%KRONOS_BACKEND_BUNDLE_MODE%)...
%PYTHON_CMD% "%PROJECT_ROOT%\packaging\scripts\build_backend.py" --clean --mode "%KRONOS_BACKEND_BUNDLE_MODE%"
if errorlevel 1 (
    echo [ERROR] Bundled backend build failed.
    exit /b 1
)

if not exist "%PROJECT_ROOT%\packaging\backend\lumo_webui_backend\lumo_webui_backend.exe" (
    echo [ERROR] Bundled backend executable is missing.
    exit /b 1
)

echo [BACKEND] Verifying bundled imports...
set "KRONOS_USER_DIR=%TEMP%\lumo_trade_backend_import_check"
"%PROJECT_ROOT%\packaging\backend\lumo_webui_backend\lumo_webui_backend.exe" --import-check
if errorlevel 1 (
    echo [ERROR] Bundled backend import check failed. The installer was not built.
    exit /b 1
)

echo [TAURI] Building Lumo Trade installers...
call npm run desktop:build -- --bundles nsis
if errorlevel 1 (
    echo [ERROR] Tauri desktop build failed.
    exit /b 1
)

set "BUNDLE_DIR=%PROJECT_ROOT%\src-tauri\target\release\bundle"
set "OUTPUT_DIR=%PROJECT_ROOT%\packaging\builds"
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
powershell.exe -NoProfile -NonInteractive -Command "$src='%BUNDLE_DIR%'; $dst='%OUTPUT_DIR%'; Get-ChildItem -Path $src -Recurse -File | Where-Object { $_.Extension -eq '.msi' -or $_.Name -like '*-setup.exe' } | ForEach-Object { Copy-Item $_.FullName -Destination $dst -Force; Write-Host ('[ARTIFACT] ' + $_.FullName) }"
if errorlevel 1 (
    echo [ERROR] Failed to copy Tauri artifacts.
    exit /b 1
)

echo [OK] Lumo Trade Windows build completed.
echo [OUTPUT] %OUTPUT_DIR%
exit /b 0
