# Kronos Quick Start Script (PowerShell Version)
# Purpose: Run stably with UTF-8 on Windows, avoid encoding issues
# Encoding: UTF-8 with BOM

# Force UTF-8 encoding with robust fallback to GBK to avoid mojibake
$ErrorActionPreference = 'SilentlyContinue'

# Attempt to set console code page to UTF-8 (65001) FIRST
try {
    cmd /c "chcp 65001 >nul 2>&1"
} catch {
    try { chcp 65001 | Out-Null } catch {}
}

# Primary: try enforce UTF-8 in console and PowerShell
try {
    $utf8 = [System.Text.Encoding]::UTF8
    $Host.UI.RawUI.OutputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    [Console]::InputEncoding = $utf8
    $OutputEncoding = $utf8
} catch {}

# PowerShell encoding parameters (prefer BOM for file outputs on Windows PowerShell 5)
$PSDefaultParameterValues = @{
    '*:Encoding' = 'utf8'
    'Out-File:Encoding' = 'utf8BOM'
    'Set-Content:Encoding' = 'utf8BOM'
}

# Fallback: if console still not in UTF-8, switch to GBK (cp936) to prevent garbled Chinese
try {
    $cp = ([Console]::OutputEncoding).CodePage
    if ($cp -ne 65001) {
        try { chcp 65001 | Out-Null } catch {}
        $cp = ([Console]::OutputEncoding).CodePage
    }
    if ($cp -ne 65001) {
        $gbk = [System.Text.Encoding]::GetEncoding(936)
        [Console]::OutputEncoding = $gbk
        [Console]::InputEncoding = $gbk
        $OutputEncoding = $gbk
        Write-Host "WARN: 控制台不支持 UTF-8，已回退到 GBK 编码以避免乱码。建议使用 Windows Terminal 或 PowerShell 7。" -ForegroundColor Yellow
    }
} catch {}

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# Ensure proper error handling and locale
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# Get command line argument
$Choice = $args[0]

function Get-PythonCommand {
    $python = $env:PYTHON
    if (-not $python -or -not (Get-Command $python -ErrorAction SilentlyContinue)) {
        $python = $env:PYTHON_CMD
    }
    if (-not $python -or -not (Get-Command $python -ErrorAction SilentlyContinue)) {
        $python = 'python'
    }
    return $python
}

function Invoke-Python {
    param(
        [Parameter(Mandatory=$true)][string]$Script,
        [Parameter(Mandatory=$false)][string[]]$Args
    )
    $python = Get-PythonCommand

    Write-Host "INFO: 使用 Python: $python" -ForegroundColor Cyan
    if ($Args) {
        & $python $Script @Args
    } else {
        & $python $Script
    }
}

function Get-PackageVersion {
    param(
        [Parameter(Mandatory=$true)][string]$Python,
        [Parameter(Mandatory=$true)][string]$Package
    )

    $info = & $Python -m pip show $Package 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $info) {
        return $null
    }

    foreach ($line in $info) {
        if ($line -like 'Version:*') {
            return $line.Split(':')[1].Trim()
        }
    }

    return $null
}

# Change working directory to script location (ensure relative paths work)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Detect packaged (PyInstaller) environment to avoid using system Python/pip
$IsPackaged = $false
try {
    if ($scriptDir -match '_MEI') { $IsPackaged = $true }
    if ($env:KRONOS_IS_APP_BUNDLE -eq 'true') { $IsPackaged = $true }
} catch { $IsPackaged = $false }

# Allow force-install in packaged mode via environment variable
$ForceInstallInApp = $false
try {
    $val1 = ($env:KRONOS_FORCE_INSTALL_IN_APP + '').ToLower()
    $val2 = ($env:KRONOS_FORCE_INSTALL + '').ToLower()
    if ($val1 -in @('true','1','yes') -or $val2 -in @('true','1','yes')) { $ForceInstallInApp = $true }
} catch { $ForceInstallInApp = $false }

# Ensure portable Python 3.11 on Windows when system Python is missing or too old
function Ensure-PortablePython {
    param(
        [Parameter(Mandatory=$false)][string]$TargetVersion = '3.11.9'
    )

    if (-not $IsWindows) {
        return
    }

    $portableRoot = Join-Path $scriptDir '.python'
    $portableDir = Join-Path $portableRoot "py311-$TargetVersion"
    $is64 = [Environment]::Is64BitOperatingSystem
    $arch = if ($is64) { 'amd64' } else { 'win32' }
    $zipName = "python-$TargetVersion-embed-$arch.zip"

    # 下载源列表（清华镜像优先，官方源作为备用）
    $downloadUrls = @(
        "https://mirrors.tuna.tsinghua.edu.cn/python/$TargetVersion/$zipName",
        "https://www.python.org/ftp/python/$TargetVersion/$zipName"
    )
    $zipPath = Join-Path $portableRoot $zipName

    New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $portableDir -Force | Out-Null

    if (-not (Test-Path (Join-Path $portableDir 'python.exe'))) {
        Write-Host "SETUP: Downloading portable Python $TargetVersion ($arch)" -ForegroundColor Cyan

        $downloadSuccess = $false
        foreach ($downloadUrl in $downloadUrls) {
            $sourceName = if ($downloadUrl -match 'tsinghua') { '清华镜像' } else { '官方源' }
            Write-Host "MIRROR: 尝试从 $sourceName 下载..." -ForegroundColor Cyan

            try {
                Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
                $downloadSuccess = $true
                Write-Host "OK: 从 $sourceName 下载成功" -ForegroundColor Green
                break
            } catch {
                Write-Host "WARN: $sourceName 下载失败，尝试下一个源..." -ForegroundColor Yellow
                try {
                    $wc = New-Object System.Net.WebClient
                    $wc.DownloadFile($downloadUrl, $zipPath)
                    $downloadSuccess = $true
                    Write-Host "OK: 从 $sourceName 下载成功 (WebClient方式)" -ForegroundColor Green
                    break
                } catch {
                    Write-Host "WARN: $sourceName (WebClient方式) 也失败" -ForegroundColor Yellow
                }
            }
        }

        if (-not $downloadSuccess) {
            Write-Host "ERROR: 所有下载源均失败，无法下载 Python" -ForegroundColor Red
            Write-Host "TIP: 请检查网络连接或手动下载 Python 3.11.9" -ForegroundColor Yellow
            return
        }

        try {
            Expand-Archive -Path $zipPath -DestinationPath $portableDir -Force
        } catch {
            try {
                Add-Type -AssemblyName System.IO.Compression.FileSystem
                [System.IO.Compression.ZipFile]::ExtractToDirectory($zipPath, $portableDir)
            } catch {
                Write-Host "ERROR: Failed to extract $zipPath" -ForegroundColor Red
                return
            }
        }

        # Enable site packages by ensuring 'import site' in _pth
        $pthFile = Get-ChildItem $portableDir -Filter 'python*.pth' | Select-Object -First 1
        if ($pthFile) {
            $lines = Get-Content $pthFile.FullName
            if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) {
                # Uncomment if commented, otherwise append
                $lines = $lines | ForEach-Object { $_ -replace '^#\s*import\s+site\s*$', 'import site' }
                if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) {
                    $lines += 'import site'
                }
                Set-Content -Path $pthFile.FullName -Value $lines -Encoding utf8
            }
        }

        # Bootstrap pip using get-pip.py
        $getPip = Join-Path $portableDir 'get-pip.py'
        try {
            Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
        } catch {
            try {
                $wc = New-Object System.Net.WebClient
                $wc.DownloadFile('https://bootstrap.pypa.io/get-pip.py', $getPip)
            } catch {
                Write-Host "WARN: Failed to download get-pip.py. You may need to install pip manually." -ForegroundColor Yellow
            }
        }

        if (Test-Path $getPip) {
            Write-Host "SETUP: Bootstrapping pip in portable Python" -ForegroundColor Cyan
            & (Join-Path $portableDir 'python.exe') $getPip
        }
    }

    # Point our tooling to the portable python without touching system PATH
    $env:PYTHON = (Join-Path $portableDir 'python.exe')
    $env:PYTHON_CMD = $env:PYTHON
    Write-Host "OK: Using isolated portable Python at $($env:PYTHON)" -ForegroundColor Green
}

# Detect if multiple Python versions are present to avoid pip/runtime conflicts
function Has-MultiplePythonVersions {
    try {
        $paths = @(cmd /c "where python 2>&1") | Where-Object { $_ -and (-not ($_ -match 'INFO|找不到')) }
        $unique = $paths | Select-Object -Unique
        if ($unique.Count -gt 1) { return $true }
    } catch { }

    try {
        $pyList = & py -0 2>$null
        if ($pyList) {
            $lines = $pyList | Where-Object { $_ -match ' -' }
            if ($lines.Count -gt 1) { return $true }
        }
    } catch { }

    return $false
}

# OS detection (PowerShell 5 on Windows only for portable Python logic)
$IsWindows = $PSVersionTable.OS -match 'Windows' -or $env:OS -match 'Windows_NT'

# Pre-flight: ensure a compatible Python (>=3.11.9) in source mode
if (-not $IsPackaged) {
    $minVersion = [Version]'3.11.9'
    $currentVersion = $null
    $candidate = $null
    try {
        $candidate = Get-PythonCommand
        $verOut = & $candidate --version 2>$null
        if ($verOut) {
            $verStr = ($verOut -replace '[^0-9\.]','').Trim()
            if ($verStr) { $currentVersion = [Version]$verStr }
        }
    } catch { }

    if (-not $currentVersion -or $currentVersion -lt $minVersion) {
        Write-Host "INFO: Python not found or version too low ($($currentVersion)) — preparing isolated portable Python 3.11.9" -ForegroundColor Yellow
        Write-Host "TIP: 这不会影响您系统的Python，会下载独立版本到 .python/ 目录" -ForegroundColor Cyan
        Ensure-PortablePython -TargetVersion '3.11.9'
    } else {
        Write-Host "OK: Python 版本检查通过 ($currentVersion >= $minVersion)" -ForegroundColor Green
    }
}

 

# Main logic - handle different menu choices
if ($Choice -eq "1") {
    Write-Host "START: 开始自动安装系统依赖..." -ForegroundColor Green

    if ($IsPackaged -and -not $ForceInstallInApp) {
        Write-Host "SKIP: 检测到应用包运行环境 (_MEI)，应用模式下禁用依赖安装" -ForegroundColor Yellow
        Write-Host "TIP: 请选择源码模式运行 'quick_start.ps1 1'，或使用已打包的依赖" -ForegroundColor Yellow
        Write-Host "TIP: 设置 'KRONOS_FORCE_INSTALL_IN_APP=true' 可强制使用系统 Python 安装依赖" -ForegroundColor Yellow
        exit 0
    } elseif ($IsPackaged -and $ForceInstallInApp) {
        Write-Host "APP: 检测到应用包环境，已启用系统 Python 强制安装依赖" -ForegroundColor Yellow
    }

    # Ensure we use the isolated portable Python if we created one
    if ($env:PYTHON) { Write-Host "INFO: 使用隔离的便携式 Python: $($env:PYTHON)" -ForegroundColor Cyan }

    $python = Get-PythonCommand
    $mirrorArgs = @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple/', '--trusted-host', 'pypi.tuna.tsinghua.edu.cn')
    $totalSteps = 4
    $step = 1

    if (Test-Path 'requirements.txt') {
        Write-Host ("STATUS: 步骤 {0}/{1}: 安装 requirements.txt 依赖包..." -f $step, $totalSteps) -ForegroundColor Cyan
        # Prefer portable Python when multiple versions detected
        if (Has-MultiplePythonVersions) {
            Write-Host "WARN: 检测到系统存在多个 Python 版本，使用隔离的便携式 Python 3.11.9 以避免冲突" -ForegroundColor Yellow
            Ensure-PortablePython -TargetVersion '3.11.9'
            $python = Get-PythonCommand
        }

        & $python -m pip install -r requirements.txt @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host "OK: Python 依赖处理完成（如出现 'Requirement already satisfied' 表示该依赖已存在）" -ForegroundColor Green
        } else {
            Write-Host "ERROR: requirements.txt 依赖安装失败 (退出代码 $exitCode)" -ForegroundColor Red
            Write-Host "ACTION: 切换到隔离的便携式 Python 3.11.9 并重试依赖安装" -ForegroundColor Yellow
            Ensure-PortablePython -TargetVersion '3.11.9'
            $python = Get-PythonCommand
            & $python -m pip install -r requirements.txt @mirrorArgs
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                Write-Host "OK: 重试依赖安装成功" -ForegroundColor Green
            } else {
                Write-Host "ERROR: 便携式 Python 下依赖安装仍失败 (退出代码 $exitCode)" -ForegroundColor Red
                Write-Host "TIP: 已配置清华镜像源，如仍失败请检查网络连接" -ForegroundColor Yellow
                exit $exitCode
            }
        }
    } else {
        Write-Host "ERROR: 未找到 requirements.txt 文件" -ForegroundColor Red
        exit 1
    }

    $step++
    Write-Host ("STATUS: 步骤 {0}/{1}: 检查 Playwright Python 包..." -f $step, $totalSteps) -ForegroundColor Cyan
    $playwrightVersion = Get-PackageVersion -Python $python -Package 'playwright'
    if ($playwrightVersion) {
        Write-Host "SKIP: Playwright 已安装 (版本 $playwrightVersion)，跳过包安装" -ForegroundColor Yellow
    } else {
        Write-Host "ACTION: 正在安装 Playwright Python 包..." -ForegroundColor Yellow
        & $python -m pip install 'playwright' @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            $playwrightVersion = Get-PackageVersion -Python $python -Package 'playwright'
            if ($playwrightVersion) {
                Write-Host "OK: Playwright 安装完成 (版本 $playwrightVersion)" -ForegroundColor Green
            } else {
                Write-Host "OK: Playwright 安装完成" -ForegroundColor Green
            }
        } else {
            Write-Host "ERROR: Playwright 安装失败 (退出代码 $exitCode)" -ForegroundColor Red
            exit $exitCode
        }
    }

    $step++
    Write-Host ("STATUS: 步骤 {0}/{1}: 安装/刷新 Playwright 浏览器 (chromium)..." -f $step, $totalSteps) -ForegroundColor Cyan
    & $python -m playwright install chromium
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host "OK: Chromium 浏览器资源已就绪" -ForegroundColor Green
    } else {
        Write-Host "WARN: Chromium 浏览器资源安装失败 (退出代码 $exitCode)，可稍后手动运行 'playwright install chromium'" -ForegroundColor Yellow
    }

    $step++
    Write-Host ("STATUS: 步骤 {0}/{1}: 检查 ModelScope 依赖..." -f $step, $totalSteps) -ForegroundColor Cyan
    $modelscopeVersion = Get-PackageVersion -Python $python -Package 'modelscope'
    if ($modelscopeVersion) {
        Write-Host "SKIP: ModelScope 已安装 (版本 $modelscopeVersion)" -ForegroundColor Yellow
    } else {
        Write-Host "ACTION: 正在安装 ModelScope 包..." -ForegroundColor Yellow
        & $python -m pip install 'modelscope' @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            $modelscopeVersion = Get-PackageVersion -Python $python -Package 'modelscope'
            if ($modelscopeVersion) {
                Write-Host "OK: ModelScope 安装完成 (版本 $modelscopeVersion)" -ForegroundColor Green
            } else {
                Write-Host "OK: ModelScope 安装完成" -ForegroundColor Green
            }
        } else {
            Write-Host "WARN: ModelScope 安装失败 (退出代码 $exitCode)" -ForegroundColor Yellow
        }
    }

    Write-Host "DONE: 所有依赖安装完成！系统已准备就绪" -ForegroundColor Green
}
elseif ($Choice -eq "2") {
    Write-Host "Starting configuration wizard..." -ForegroundColor Yellow
    Invoke-Python -Script 'scripts/config_wizard.py'
}
elseif ($Choice -eq "3") {
    Write-Host "Checking environment status..." -ForegroundColor Yellow
    Invoke-Python -Script 'scripts/check_environment.py'
}
elseif ($Choice -eq "6") {
    Write-Host "CHART: Batch fetch data and prediction K-line" -ForegroundColor Yellow

    # Read from environment variables for non-interactive input
    $symbolsEnv = $env:KRONOS_SYMBOLS
    $sourceEnv = $env:KRONOS_SOURCE
    $daysEnv = $env:KRONOS_DAYS

    if (-not $symbolsEnv) {
        try {
            $symbolsEnv = Read-Host "Enter stock code (comma separated, e.g.: 000001.SZ,600000.SH)"
        } catch {
            # Ignore input errors
        }
    }
    if (-not $symbolsEnv) {
        Write-Host "ERROR: Stock code cannot be empty" -ForegroundColor Red
        exit 1
    }

    if (-not $sourceEnv) { $sourceEnv = 'auto' }
    if (-not $daysEnv) { $daysEnv = '365' }

    # Normalize parameters
    $symbolsParam = $symbolsEnv -replace ',', ' '
    $validSources = @('auto','tushare','crawler')
    if (-not ($validSources -contains $sourceEnv)) { $sourceEnv = 'auto' }

    Write-Host "Batch fetching data for $symbolsEnv (source: $sourceEnv, days: $daysEnv)..." -ForegroundColor Green
    # Execute batch data fetching
    Invoke-Python -Script 'scripts/batch_fetch.py' -Args @('--symbols', $symbolsParam, '--min-days', $daysEnv, '--config', 'config/tushare_config.json')

    # Auto select first stock for prediction demo
    $firstSymbol = ($symbolsEnv -split ',')[0]
    $cleanSymbol = $firstSymbol -replace '\..*$', ''
    Write-Host "PREDICT: Starting prediction ($cleanSymbol)" -ForegroundColor Green
    Invoke-Python -Script 'examples/prediction_batch_example.py' -Args @('--stock-code', $cleanSymbol)
}
elseif ($Choice -eq "7") {
    Write-Host "Checking license status..." -ForegroundColor Yellow
    if (Test-Path 'finetune/license_system/license_validator.py') {
        Invoke-Python -Script 'finetune/license_system/license_validator.py'
    } else {
        Write-Host "License system files not found" -ForegroundColor Red
    }
}
elseif ($Choice -eq "10") {
    Write-Host "Starting Web UI..." -ForegroundColor Yellow
    if (-not $IsPackaged) {
        if (Test-Path 'webui/requirements.txt') {
            try {
                $python = Get-PythonCommand
                & $python -m pip install -r 'webui/requirements.txt'
            } catch {
                # Ignore installation failure to avoid blocking startup
            }
        }
    } else {
        Write-Host "SKIP: Packaged app detected, skipping webui dependency installation" -ForegroundColor Yellow
    }
    if (Test-Path 'webui/app.py') {
        Push-Location 'webui'
        Invoke-Python -Script 'app.py'
        Pop-Location
    } else {
        Write-Host "webui/app.py not found" -ForegroundColor Red
    }
}
elseif ($Choice -eq "11") {
    Write-Host "Showing help (check complete help in GUI)" -ForegroundColor Yellow
}
elseif ($Choice -eq "12") {
    Write-Host "System status..." -ForegroundColor Yellow
    Invoke-Python -Script 'scripts/check_environment.py'
}
else {
    Write-Host "Unsupported option. Available options: 1/2/3/6/7/10/11/12" -ForegroundColor Yellow
}