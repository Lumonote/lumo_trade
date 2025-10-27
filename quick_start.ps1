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
    # 优先使用本工具管理的用户级虚拟环境 Python（确保在打包模式/跨机器可用）
    try {
        $venvDir = Join-Path $env:LocalAppData 'Kronos\venv'
        $venvPy = Join-Path $venvDir 'Scripts\python.exe'
        if (Test-Path $venvPy) { return $venvPy }
    } catch {}

    # 然后使用 Windows 的 py 启动器定位到具体 python.exe
    try {
        $out = & py -3.11 --version 2>$null
        if ($out) {
            $exe = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($exe -and (Test-Path $exe)) { return $exe }
        }
    } catch {}
    try {
        $out = & py -3 --version 2>$null
        if ($out) {
            $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
            if ($exe -and (Test-Path $exe)) { return $exe }
        }
    } catch {}

    # 其次使用环境变量指定的 Python
    $python = $env:PYTHON
    if ($python -and (Get-Command $python -ErrorAction SilentlyContinue)) { return $python }
    $python = $env:PYTHON_CMD
    if ($python -and (Get-Command $python -ErrorAction SilentlyContinue)) { return $python }

    # 回退到 PATH 中的 python
    return 'python'
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

# If running from a packaged bundle, proactively ensure embedded Python works across machines
if ($IsPackaged) {
    try {
        $embeddedRoot = Join-Path $scriptDir '.python'
        $pyDir = $null
        if (Test-Path $embeddedRoot) {
            $cand = Get-ChildItem $embeddedRoot -Directory -Filter 'py311-*' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($cand) { $pyDir = $cand.FullName }
        }

        if ($pyDir) {
            $ok = Ensure-PackagedEmbeddedPythonReady -RootDir $pyDir
            if (-not $ok) {
                Write-Host "FATAL: 打包环境内置 Python 初始化失败，请联系发行者或检查解压权限/杀软拦截" -ForegroundColor Red
                exit 1
            } else {
                Write-Host "OK: 打包环境已就绪（嵌入式 Python encodings 自检通过）" -ForegroundColor Green
            }
        } else {
            # 没有随包提供嵌入式 Python，则退回系统 Python 的发现逻辑
            foreach ($v in 'PYTHONHOME','PYTHONPATH') { if (Test-Path Env:$v) { Remove-Item Env:$v -ErrorAction SilentlyContinue } }
        }
    } catch {
        Write-Host "WARN: 无法验证打包内嵌式 Python，将继续尝试使用系统 Python" -ForegroundColor Yellow
        foreach ($v in 'PYTHONHOME','PYTHONPATH') { if (Test-Path Env:$v) { Remove-Item Env:$v -ErrorAction SilentlyContinue } }
    }
}

# In packaged (_MEI) scenario, we must ensure embedded Python is healthy (encodings/site)
function Fix-EmbeddedPythonPth {
    param([Parameter(Mandatory=$true)][string]$BaseDir)

    try {
        $pthFile = Get-ChildItem $BaseDir -Filter 'python*._pth' -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pthFile) { return }

        $lines = Get-Content $pthFile.FullName -ErrorAction SilentlyContinue
        if (-not $lines) { return }

        $bom = [char]0xFEFF
        $lines = $lines | ForEach-Object { $_.Replace($bom, '') }

        if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) {
            $lines = $lines | ForEach-Object { $_ -replace '^#\s*import\s+site\s*$', 'import site' }
            if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) { $lines += 'import site' }
        }

        Set-Content -Path $pthFile.FullName -Value $lines -Encoding ascii
    } catch {}
}

function Ensure-PackagedEmbeddedPythonReady {
    param([Parameter(Mandatory=$true)][string]$RootDir)

    # 1) Fix _pth to enable site-packages and remove BOM side effects
    Fix-EmbeddedPythonPth -BaseDir $RootDir

    # 2) Prefer embedded python.exe if present
    $pyExe = Join-Path $RootDir 'python.exe'
    if (Test-Path $pyExe) {
        $env:PYTHON = $pyExe
        $env:PYTHON_CMD = $pyExe
    }

    # 3) Clear variables that could break stdlib discovery
    foreach ($v in 'PYTHONHOME','PYTHONPATH') {
        if (Test-Path Env:$v) { Remove-Item Env:$v -ErrorAction SilentlyContinue }
    }

    # 4) Self-check for encodings import and fs encoding
    try {
        & $pyExe -c "import sys,encodings;print(sys.getfilesystemencoding() or 'unknown')" 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: 嵌入式 Python 缺少 encodings 或初始化失败" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host "ERROR: 无法运行嵌入式 Python 进行自检" -ForegroundColor Red
        return $false
    }

    return $true
}
# Ensure a user-level managed virtual environment and install dependencies
function Ensure-ManagedVenvAndDeps {
    param(
        [Parameter(Mandatory=$false)][string]$TargetPythonVersion = '3.11.9'
    )

    # 1) Ensure a suitable system Python available to create venv
    Ensure-SystemPython -TargetVersion $TargetPythonVersion

    # 2) Create venv under %LocalAppData%\Kronos\venv (user-writable, stable across _MEI temps)
    $venvDir = Join-Path $env:LocalAppData 'Kronos\venv'
    $venvPy = Join-Path $venvDir 'Scripts\python.exe'

    if (-not (Test-Path $venvPy)) {
        try {
            $creator = Get-PythonCommand
            Write-Host "SETUP: 创建用户级虚拟环境 -> $venvDir" -ForegroundColor Cyan
            & $creator -m venv $venvDir
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Write-Host "ERROR: 虚拟环境创建失败" -ForegroundColor Red; exit 1 }
        } catch {
            Write-Host "ERROR: 无法创建虚拟环境 ($venvDir)" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "OK: 发现已存在的虚拟环境 -> $venvDir" -ForegroundColor Green
    }

    # 3) Use mirror for faster installation
    $mirrorArgs = @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple/', '--trusted-host', 'pypi.tuna.tsinghua.edu.cn')

    # 4) Upgrade pip and install requirements
    try { & $venvPy -m pip install -U pip @mirrorArgs } catch {}

    if (Test-Path 'requirements.txt') {
        Write-Host "INSTALL: 安装项目依赖 requirements.txt 到用户虚拟环境" -ForegroundColor Cyan
        & $venvPy -m pip install -r requirements.txt @mirrorArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: 依赖安装失败（虚拟环境），请检查网络或镜像源" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "ERROR: 未找到 requirements.txt 文件" -ForegroundColor Red
        exit 1
    }

    # 5) Ensure playwright and browsers (optional, best-effort)
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $env:LocalAppData 'Kronos\pw-browsers'
    if (-not (Test-Path $env:PLAYWRIGHT_BROWSERS_PATH)) { New-Item -ItemType Directory -Path $env:PLAYWRIGHT_BROWSERS_PATH -Force | Out-Null }

    $info = & $venvPy -m pip show playwright 2>$null
    if (-not $info) {
        Write-Host "INSTALL: 安装 Playwright 包" -ForegroundColor Cyan
        & $venvPy -m pip install playwright @mirrorArgs
        if ($LASTEXITCODE -ne 0) { Write-Host "WARN: Playwright 安装失败（可稍后重试）" -ForegroundColor Yellow }
    }
    try { & $venvPy -m playwright install chromium } catch { Write-Host "WARN: Chromium 资源安装失败（可稍后手动执行）" -ForegroundColor Yellow }

    Write-Host "DONE: 用户虚拟环境与依赖已就绪 -> $venvDir" -ForegroundColor Green
}


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

    # 强制启用 TLS1.2/1.3，避免旧系统默认禁用导致下载失败
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    } catch {}

    $portableRoot = Join-Path $scriptDir '.python'
    $portableDir = Join-Path $portableRoot "py311-$TargetVersion"
    $is64 = [Environment]::Is64BitOperatingSystem
    $arch = if ($is64) { 'amd64' } else { 'win32' }
    $zipName = "python-$TargetVersion-embed-$arch.zip"

    # 下载源列表（华为云优先，官方源作为备用）
    $downloadUrls = @(
        "https://mirrors.huaweicloud.com/python/$TargetVersion/$zipName",
        "https://mirrors.ustc.edu.cn/python/$TargetVersion/$zipName",
        "https://www.python.org/ftp/python/$TargetVersion/$zipName"
    )
    $zipPath = Join-Path $portableRoot $zipName

    New-Item -ItemType Directory -Path $portableRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $portableDir -Force | Out-Null

    if (-not (Test-Path (Join-Path $portableDir 'python.exe'))) {
        Write-Host "SETUP: Downloading portable Python $TargetVersion ($arch)" -ForegroundColor Cyan

        $downloadSuccess = $false
        foreach ($downloadUrl in $downloadUrls) {
            $sourceName = if ($downloadUrl -match 'tsinghua') { '清华镜像' } elseif ($downloadUrl -match 'huaweicloud') { '华为云' } elseif ($downloadUrl -match 'ustc') { '中科院' }  else { '官方源' }
            Write-Host "MIRROR: 尝试从 $sourceName 下载..." -ForegroundColor Cyan

            $maxRetries = 4
            for ($attempt = 1; $attempt -le $maxRetries -and (-not $downloadSuccess); $attempt++) {
                try {
                    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing -Headers @{ 'User-Agent' = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' }
                    $downloadSuccess = $true
                    Write-Host "OK: 从 $sourceName 下载成功 (IWR)" -ForegroundColor Green
                    break
                } catch {
                    Write-Host "WARN: IWR 失败 (尝试 $attempt/$maxRetries)，尝试 BITS 传输..." -ForegroundColor Yellow
                    try {
                        Start-BitsTransfer -Source $downloadUrl -Destination $zipPath -ErrorAction Stop
                        $downloadSuccess = $true
                        Write-Host "OK: 从 $sourceName 下载成功 (BITS)" -ForegroundColor Green
                        break
                    } catch {
                        Write-Host "WARN: BITS 失败，尝试 WebClient..." -ForegroundColor Yellow
                        try {
                            $wc = New-Object System.Net.WebClient
                            $wc.Headers.Add('user-agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
                            $wc.DownloadFile($downloadUrl, $zipPath)
                            $downloadSuccess = $true
                            Write-Host "OK: 从 $sourceName 下载成功 (WebClient)" -ForegroundColor Green
                            break
                        } catch {
                            Start-Sleep -Seconds ([Math]::Min(5 * $attempt, 15))
                        }
                    }
                }
            }

            if ($downloadSuccess) { break }
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
        # NOTE: Embedded Python uses files like 'python311._pth' (underscore),
        # so we must match '*._pth' rather than '*.pth'. Otherwise 'import site'
        # won't be enabled and 'python -m pip' will fail with "No module named pip".
        $pthFile = Get-ChildItem $portableDir -Filter 'python*._pth' | Select-Object -First 1
        if ($pthFile) {
            $lines = Get-Content $pthFile.FullName
            # Remove any BOM characters accidentally included in the first entry
            # which would turn 'python311.zip' into '\ufeffpython311.zip' and break stdlib loading
            $bom = [char]0xFEFF
            $lines = $lines | ForEach-Object { $_.Replace($bom, '') }
            if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) {
                # Uncomment if commented, otherwise append
                $lines = $lines | ForEach-Object { $_ -replace '^#\s*import\s+site\s*$', 'import site' }
                if (-not ($lines | Where-Object { $_ -match '^\s*import\s+site\s*$' })) {
                    $lines += 'import site'
                }
                # Use ASCII to avoid writing BOM and keep embedded Python path entries clean
                Set-Content -Path $pthFile.FullName -Value $lines -Encoding ascii
            }
        }

        # Bootstrap pip using get-pip.py
        $getPip = Join-Path $portableDir 'get-pip.py'
        $localGetPip = Join-Path $scriptDir 'resources\get-pip.py'

        # 优先使用本地的get-pip.py
        if (Test-Path $localGetPip) {
            Write-Host "SETUP: Using local get-pip.py from resources/" -ForegroundColor Cyan
            Copy-Item $localGetPip $getPip -Force
        } else {
            Write-Host "SETUP: Downloading get-pip.py from internet..." -ForegroundColor Cyan
            try {
                Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getPip -UseBasicParsing
            } catch {
                try {
                    $wc = New-Object System.Net.WebClient
                    $wc.DownloadFile('https://bootstrap.pypa.io/get-pip.py', $getPip)
                } catch {
                    Write-Host "ERROR: Failed to download get-pip.py. Please check network connection." -ForegroundColor Red
                    Write-Host "TIP: You can manually download https://bootstrap.pypa.io/get-pip.py to resources/ folder" -ForegroundColor Yellow
                }
            }
        }

        if (Test-Path $getPip) {
            Write-Host "SETUP: Bootstrapping pip in portable Python" -ForegroundColor Cyan
            & (Join-Path $portableDir 'python.exe') $getPip
        } else {
            Write-Host "ERROR: get-pip.py not found, cannot install pip" -ForegroundColor Red
        }
    }

    # Point our tooling to the portable python without touching system PATH
    $env:PYTHON = (Join-Path $portableDir 'python.exe')
    $env:PYTHON_CMD = $env:PYTHON
    Write-Host "OK: Using isolated portable Python at $($env:PYTHON)" -ForegroundColor Green
}

# Ensure system Python 3.11 on Windows (per-user install) when system Python is missing or too old
function Ensure-SystemPython {
    param([Parameter(Mandatory=$false)][string]$TargetVersion = '3.11.9')
    if (-not $IsWindows) { return }
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13 } catch {}
    $minVersion = [Version]$TargetVersion
    $hasOK = $false
    try {
        $verOut = & py -3.11 --version 2>$null
        if ($verOut) {
            $verStr = ($verOut -replace '[^0-9\.]','').Trim()
            if ($verStr) { $ver = [Version]$verStr; if ($ver -ge $minVersion) { $hasOK = $true } }
        }
    } catch {}
    if (-not $hasOK) {
        try {
            $verOut = & python --version 2>$null
            $verStr = ($verOut -replace '[^0-9\.]','').Trim()
            if ($verStr) { $ver = [Version]$verStr; if ($ver -ge $minVersion) { $hasOK = $true } }
        } catch {}
    }
    if ($hasOK) { return }
    Write-Host "SETUP: 正在安装系统 Python $TargetVersion（用户目录）" -ForegroundColor Cyan
    $is64 = [Environment]::Is64BitOperatingSystem
    $installerName = if ($is64) { "python-$TargetVersion-amd64.exe" } else { "python-$TargetVersion.exe" }
    $downloadUrls = @(
        "https://mirrors.huaweicloud.com/python/$TargetVersion/$installerName",
        "https://mirrors.ustc.edu.cn/python/$TargetVersion/$installerName",
        "https://www.python.org/ftp/python/$TargetVersion/$installerName"
    )
    $installerPath = Join-Path $env:TEMP $installerName
    $targetDir = Join-Path $env:LocalAppData "Programs\Python\Python311"
    New-Item -ItemType Directory -Path (Split-Path $targetDir -Parent) -Force | Out-Null
    $downloadSuccess = $false
    foreach ($url in $downloadUrls) {
        Write-Host "MIRROR: 尝试下载 $installerName ..." -ForegroundColor Cyan
        try {
            Invoke-WebRequest -Uri $url -OutFile $installerPath -UseBasicParsing -Headers @{ 'User-Agent'='Mozilla/5.0' }
            $downloadSuccess = $true
            Write-Host "OK: 下载成功" -ForegroundColor Green
            break
        } catch {
            try {
                $wc = New-Object System.Net.WebClient
                $wc.Headers.Add('user-agent','Mozilla/5.0')
                $wc.DownloadFile($url, $installerPath)
                $downloadSuccess = $true
                Write-Host "OK: 下载成功 (WebClient)" -ForegroundColor Green
                break
            } catch { Start-Sleep -Seconds 2 }
        }
    }
    if (-not $downloadSuccess) { Write-Host "ERROR: 无法下载 Python 安装包" -ForegroundColor Red; return }
    $args = "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1 TargetDir=`"$targetDir`""
    $proc = Start-Process -FilePath $installerPath -ArgumentList $args -PassThru -Wait
    if ($proc.ExitCode -ne 0) { Write-Host "ERROR: Python 安装失败 (退出代码 $($proc.ExitCode))" -ForegroundColor Red; return }
    $env:PATH = "$targetDir;$targetDir\Scripts;$env:PATH"
    $pyExe = Join-Path $targetDir 'python.exe'
    try { & $pyExe -m ensurepip 2>$null; & $pyExe -m pip install -U pip 2>$null } catch {}
    Write-Host "OK: 系统 Python 已安装到 $targetDir" -ForegroundColor Green
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
        Write-Host "INFO: 系统未检测到合适的 Python ($($currentVersion)) — 准备安装到用户目录" -ForegroundColor Yellow
        Ensure-SystemPython -TargetVersion '3.11.9'
    } else {
        Write-Host "OK: Python 版本检查通过 ($currentVersion >= $minVersion)" -ForegroundColor Green
    }
}

 

# Main logic - handle different menu choices
if ($Choice -eq "1") {
    Write-Host "START: 开始自动安装系统依赖..." -ForegroundColor Green

    if ($IsPackaged -and -not $ForceInstallInApp) {
        Write-Host "INFO: 检测到应用包运行环境，将在用户目录创建独立虚拟环境并安装依赖" -ForegroundColor Cyan
        Ensure-ManagedVenvAndDeps -TargetPythonVersion '3.11.9'
        exit 0
    } elseif ($IsPackaged -and $ForceInstallInApp) {
        Write-Host "APP: 检测到应用包环境，已启用系统 Python 强制安装依赖" -ForegroundColor Yellow
    }

    # 使用系统 Python 或用户目录安装的 Python

    $python = Get-PythonCommand
    $mirrorArgs = @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple/', '--trusted-host', 'pypi.tuna.tsinghua.edu.cn')
    $totalSteps = 4
    $step = 1

    if (Test-Path 'requirements.txt') {
        Write-Host ("STATUS: 步骤 {0}/{1}: 安装 requirements.txt 依赖包..." -f $step, $totalSteps) -ForegroundColor Cyan
        # 当检测到多个 Python 版本时，优先选择系统中满足 >=3.11.9 的版本；仅在未找到合适版本时使用便携式 Python
        if (Has-MultiplePythonVersions) {
            Write-Host "WARN: 检测到系统存在多个 Python 版本，尝试优先使用系统中满足 >=3.11.9 的版本" -ForegroundColor Yellow

            $minVersion = [Version]'3.11.9'
            $selectedPython = $null
            $selectedVersion = $null

            try {
                # 聚合候选 python.exe 路径
                $candidates = @()
                try {
                    $paths = @(cmd /c "where python 2>&1") | Where-Object { $_ -and (-not ($_ -match 'INFO|找不到')) }
                    foreach ($p in $paths) { if ($p) { $candidates += $p.Trim() } }
                } catch {}

                # 去重
                $candidates = $candidates | Select-Object -Unique

                foreach ($path in $candidates) {
                    try {
                        $verOut = & $path --version 2>$null
                        $verStr = ($verOut -replace '[^0-9\.]','').Trim()
                        if ($verStr) {
                            $ver = [Version]$verStr
                            if ($ver -ge $minVersion) {
                                $selectedPython = $path
                                $selectedVersion = $ver
                                break
                            }
                        }
                    } catch {}
                }
            } catch {}

            if ($selectedPython) {
                $env:PYTHON = $selectedPython
                $env:PYTHON_CMD = $selectedPython
                $python = $selectedPython
                Write-Host "OK: 选用系统 Python ($selectedVersion) : $selectedPython" -ForegroundColor Green
            } else {
                Write-Host "ACTION: 未找到满足条件的系统 Python，尝试安装系统 Python 3.11.9" -ForegroundColor Yellow
                Ensure-SystemPython -TargetVersion '3.11.9'
                $python = Get-PythonCommand
            }
        }

        # 源码模式也改为先确保用户级虚拟环境，避免全局污染
        Ensure-ManagedVenvAndDeps -TargetPythonVersion '3.11.9'
        # 之后的检查交给虚拟环境，不再使用系统 python 继续装
        $python = Get-PythonCommand
        $exitCode = $LASTEXITCODE
        if ($exitCode -eq 0) {
            Write-Host "OK: Python 依赖处理完成（如出现 'Requirement already satisfied' 表示该依赖已存在）" -ForegroundColor Green
        } else {
            Write-Host "ERROR: requirements.txt 依赖安装失败 (退出代码 $exitCode)" -ForegroundColor Red
            Write-Host "ACTION: 安装系统 Python 3.11.9 并重试依赖安装" -ForegroundColor Yellow
            Ensure-SystemPython -TargetVersion '3.11.9'
            $python = Get-PythonCommand
            & $python -m pip install -r requirements.txt @mirrorArgs
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                Write-Host "OK: 重试依赖安装成功" -ForegroundColor Green
            } else {
                Write-Host "ERROR: 系统 Python 下依赖安装仍失败 (退出代码 $exitCode)" -ForegroundColor Red
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
    Invoke-Python -Script 'examples/prediction_batch_example.py' -Args @('--stock-code', $cleanSymbol, '-T', '0.6', '-p', '0.90', '-n', '10')
}
elseif ($Choice -eq "8") {
    Write-Host "Checking license status..." -ForegroundColor Yellow
    if (Test-Path 'finetune/license_system/license_validator.py') {
        Invoke-Python -Script 'finetune/license_system/license_validator.py'
    } else {
        Write-Host "License system files not found" -ForegroundColor Red
    }
}
elseif ($Choice -eq "11") {
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
elseif ($Choice -eq "12") {
    Write-Host "Showing help (check complete help in GUI)" -ForegroundColor Yellow
}
elseif ($Choice -eq "13") {
    Write-Host "System status..." -ForegroundColor Yellow
    Invoke-Python -Script 'scripts/check_environment.py'
}
else {
    Write-Host "Unsupported option. Available options: 1/2/3/6/7/8/11/12/13" -ForegroundColor Yellow
}