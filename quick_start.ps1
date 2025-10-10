# Kronos Quick Start Script (PowerShell Version)
# Purpose: Run stably with UTF-8 on Windows, avoid encoding issues
# Encoding: UTF-8 with BOM

# Force UTF-8 encoding - Enhanced version with error handling
$ErrorActionPreference = 'SilentlyContinue'

# Try to set output encoding with error suppression
$Host.UI.RawUI.OutputEncoding = [System.Text.Encoding]::UTF8 2>$null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8 2>$null
[Console]::InputEncoding = [System.Text.Encoding]::UTF8 2>$null

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$OutputEncoding = [System.Text.Encoding]::UTF8

# Set console code page to UTF-8 (65001) with multiple fallbacks
try {
    cmd /c "chcp 65001 >nul 2>&1"
} catch {
    try {
        chcp 65001 | Out-Null
    } catch {
        # Ignore if both fail
    }
}

# Set PowerShell encoding parameters
$PSDefaultParameterValues = @{
    '*:Encoding' = 'utf8'
    'Out-File:Encoding' = 'utf8'
    'Set-Content:Encoding' = 'utf8'
}

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

    Write-Host "Using Python: $python" -ForegroundColor Cyan
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

    if ($IsPackaged) { return }
    if (-not $IsWindows) {
        return
    }

    $portableRoot = Join-Path $scriptDir '.python'
    $portableDir = Join-Path $portableRoot "py311-$TargetVersion"
    $is64 = [Environment]::Is64BitOperatingSystem
    $arch = if ($is64) { 'amd64' } else { 'win32' }
    $zipName = "python-$TargetVersion-embed-$arch.zip"
    $downloadUrl = "https://www.python.org/ftp/python/$TargetVersion/$zipName"
    $zipPath = Join-Path $portableRoot $zipName

    New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $portableDir -Force | Out-Null

    if (-not (Test-Path (Join-Path $portableDir 'python.exe'))) {
        Write-Host "SETUP: Downloading portable Python $TargetVersion ($arch)" -ForegroundColor Cyan
        try {
            Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
        } catch {
            try {
                $wc = New-Object System.Net.WebClient
                $wc.DownloadFile($downloadUrl, $zipPath)
            } catch {
                Write-Host "ERROR: Failed to download portable Python from $downloadUrl" -ForegroundColor Red
                return
            }
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

# OS detection (PowerShell 5 on Windows only for portable Python logic)
$IsWindows = $PSVersionTable.OS -match 'Windows' -or $env:OS -match 'Windows_NT'

# Pre-flight: ensure a compatible Python (>=3.11) in source mode
if (-not $IsPackaged) {
    $minVersion = [Version]'3.11.0'
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
        Write-Host "INFO: Python not found or version too low ($($currentVersion)) — preparing isolated portable Python." -ForegroundColor Yellow
        Ensure-PortablePython -TargetVersion '3.11.9'
    }
}

# Main logic - handle different menu choices
if ($Choice -eq "1") {
    Write-Host "PACKAGE: Starting dependency installation..." -ForegroundColor Green

    if ($IsPackaged -and -not $ForceInstallInApp) {
        Write-Host "SKIP: Detected packaged app runtime (_MEI), dependency installation disabled in app mode" -ForegroundColor Yellow
        Write-Host "TIP: Use source mode to run 'quick_start.ps1 1', or rely on bundled dependencies" -ForegroundColor Yellow
        Write-Host "TIP: Set 'KRONOS_FORCE_INSTALL_IN_APP=true' to force install with system Python" -ForegroundColor Yellow
        exit 0
    } elseif ($IsPackaged -and $ForceInstallInApp) {
        Write-Host "APP: Packaged runtime detected, proceeding with system Python dependency install (forced)" -ForegroundColor Yellow
    }

    # Ensure we use the isolated portable Python if we created one
    if ($env:PYTHON) { Write-Host "Using isolated Python at $($env:PYTHON)" -ForegroundColor Cyan }

    $python = Get-PythonCommand
    $mirrorArgs = @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple/', '--trusted-host', 'pypi.tuna.tsinghua.edu.cn')
    $totalSteps = 4
    $step = 1

    if (Test-Path 'requirements.txt') {
        Write-Host "STEP $step/$totalSteps : Installing requirements.txt dependencies..." -ForegroundColor Cyan
        & $python -m pip install -r requirements.txt @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host "OK: Base dependencies processed successfully" -ForegroundColor Green
        } else {
            Write-Host "ERROR: requirements.txt installation failed (exit code $exitCode)" -ForegroundColor Red
            exit $exitCode
        }
    } else {
        Write-Host "ERROR: requirements.txt not found" -ForegroundColor Red
        exit 1
    }

    $step++
    Write-Host "STEP $step/$totalSteps : Checking Playwright Python package..." -ForegroundColor Cyan
    $playwrightVersion = Get-PackageVersion -Python $python -Package 'playwright'
    if ($playwrightVersion) {
        Write-Host "SKIP: Playwright already installed (version $playwrightVersion)" -ForegroundColor Yellow
    } else {
        & $python -m pip install 'playwright' @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            $playwrightVersion = Get-PackageVersion -Python $python -Package 'playwright'
            if ($playwrightVersion) {
                Write-Host "OK: Playwright installed (version $playwrightVersion)" -ForegroundColor Green
            } else {
                Write-Host "OK: Playwright installed" -ForegroundColor Green
            }
        } else {
            Write-Host "ERROR: Playwright installation failed (exit code $exitCode)" -ForegroundColor Red
            exit $exitCode
        }
    }

    $step++
    Write-Host "STEP $step/$totalSteps : Installing Playwright browsers (chromium)..." -ForegroundColor Cyan
    & $python -m playwright install chromium
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        Write-Host "OK: Chromium browser resources ready" -ForegroundColor Green
    } else {
        Write-Host "WARN: Chromium browser installation failed (exit code $exitCode)" -ForegroundColor Yellow
    }

    $step++
    Write-Host "STEP $step/$totalSteps : Checking ModelScope dependency..." -ForegroundColor Cyan
    $modelscopeVersion = Get-PackageVersion -Python $python -Package 'modelscope'
    if ($modelscopeVersion) {
        Write-Host "SKIP: ModelScope already installed (version $modelscopeVersion)" -ForegroundColor Yellow
    } else {
        & $python -m pip install 'modelscope' @mirrorArgs
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            $modelscopeVersion = Get-PackageVersion -Python $python -Package 'modelscope'
            if ($modelscopeVersion) {
                Write-Host "OK: ModelScope installed (version $modelscopeVersion)" -ForegroundColor Green
            } else {
                Write-Host "OK: ModelScope installed" -ForegroundColor Green
            }
        } else {
            Write-Host "WARN: ModelScope installation failed (exit code $exitCode)" -ForegroundColor Yellow
        }
    }

    Write-Host "DONE: Installation process completed" -ForegroundColor Green
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