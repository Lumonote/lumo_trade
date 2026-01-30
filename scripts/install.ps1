# Kronos 项目 PowerShell 安装脚本
# 适用于 Windows PowerShell 5.1+ 和 PowerShell Core 6.0+

# 设置错误处理
$ErrorActionPreference = "Stop"

# 颜色输出函数
function Write-ColorOutput {
    param(
        [string]$Message,
        [string]$Color = "White"
    )
    
    $colors = @{
        "Red" = "Red"
        "Green" = "Green"
        "Yellow" = "Yellow"
        "Blue" = "Blue"
        "Cyan" = "Cyan"
        "Magenta" = "Magenta"
        "White" = "White"
    }
    
    if ($colors.ContainsKey($Color)) {
        Write-Host $Message -ForegroundColor $colors[$Color]
    } else {
        Write-Host $Message
    }
}

# 检查管理员权限
function Test-Administrator {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# 检查Python安装
function Test-PythonInstallation {
    try {
        $pythonVersion = python --version 2>$null
        if ($pythonVersion -match "Python (\d+)\.(\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            
            if ($major -eq 3 -and $minor -ge 8) {
                Write-ColorOutput "✅ Python版本检查通过: $pythonVersion" "Green"
                return $true
            } else {
                Write-ColorOutput "❌ Python版本过低: $pythonVersion (需要Python 3.11+)" "Red"
                return $false
            }
        } else {
            Write-ColorOutput "❌ 无法获取Python版本信息" "Red"
            return $false
        }
    } catch {
        Write-ColorOutput "❌ Python未安装或不在PATH中" "Red"
        Write-ColorOutput "请从 https://python.org 下载并安装Python 3.11+" "Yellow"
        return $false
    }
}

# 检查pip
function Test-PipInstallation {
    try {
        $pipVersion = pip --version 2>$null
        if ($pipVersion) {
            Write-ColorOutput "✅ pip可用: $pipVersion" "Green"
            return $true
        } else {
            Write-ColorOutput "❌ pip不可用" "Red"
            return $false
        }
    } catch {
        Write-ColorOutput "❌ pip未安装" "Red"
        return $false
    }
}

# 创建目录结构
function New-ProjectDirectories {
    $directories = @("data", "logs", "config", "scripts", "results")
    
    Write-ColorOutput "📁 创建项目目录结构..." "Blue"
    
    foreach ($dir in $directories) {
        if (!(Test-Path $dir)) {
            try {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
                Write-ColorOutput "  ✅ 创建目录: $dir" "Green"
            } catch {
                Write-ColorOutput "  ❌ 创建目录失败: $dir - $($_.Exception.Message)" "Red"
                throw
            }
        } else {
            Write-ColorOutput "  ✅ 目录已存在: $dir" "Yellow"
        }
    }
}

# 升级pip
function Update-Pip {
    Write-ColorOutput "🔄 升级pip到最新版本..." "Blue"
    
    try {
        $process = Start-Process -FilePath "python" -ArgumentList "-m", "pip", "install", "--upgrade", "pip" -Wait -PassThru -NoNewWindow
        if ($process.ExitCode -eq 0) {
            Write-ColorOutput "✅ pip升级成功" "Green"
        } else {
            Write-ColorOutput "⚠️  pip升级失败，但继续安装" "Yellow"
        }
    } catch {
        Write-ColorOutput "⚠️  pip升级异常: $($_.Exception.Message)" "Yellow"
    }
}

# 安装Python包
function Install-PythonPackages {
    param(
        [string[]]$Packages,
        [string]$Description = "依赖包",
        [switch]$UseMirror
    )
    
    Write-ColorOutput "📦 安装$Description..." "Blue"
    
    $pipArgs = @("install")
    
    if ($UseMirror) {
        $pipArgs += @("-i", "https://pypi.tuna.tsinghua.edu.cn/simple")
        Write-ColorOutput "🌏 使用清华大学镜像源" "Cyan"
    }
    
    $pipArgs += $Packages
    
    try {
        $process = Start-Process -FilePath "pip" -ArgumentList $pipArgs -Wait -PassThru -NoNewWindow
        if ($process.ExitCode -eq 0) {
            Write-ColorOutput "✅ $Description 安装成功" "Green"
            return $true
        } else {
            Write-ColorOutput "❌ $Description 安装失败" "Red"
            return $false
        }
    } catch {
        Write-ColorOutput "❌ $Description 安装异常: $($_.Exception.Message)" "Red"
        return $false
    }
}

# 创建配置文件
function New-ConfigurationFile {
    $configPath = "config\tushare_config.json"
    
    if (Test-Path $configPath) {
        Write-ColorOutput "✅ 配置文件已存在: $configPath" "Yellow"
        return
    }
    
    Write-ColorOutput "📄 创建默认配置文件..." "Blue"
    
    $config = @{
        "tushare" = @{
            "token" = "your_tushare_token_here"
            "timeout" = 30
            "retry_count" = 3
            "rate_limit" = 200
        }
        "data_settings" = @{
            "output_dir" = "./data/"
            "file_format" = "csv"
            "date_format" = "%Y-%m-%d %H:%M:%S"
            "encoding" = "utf-8"
        }
        "default_params" = @{
            "freq" = "5min"
            "adj" = "qfq"
 "start_date" = ""
            "end_date" = ""
            "max_days_per_request" = 30
        }
        "stock_lists" = @{
            "popular_stocks" = @(
                "000001.SZ", "000002.SZ", "600000.SH", "600036.SH", "600519.SH",
                "000858.SZ", "002415.SZ", "300059.SZ", "600887.SH", "002230.SZ"
            )
            "indices" = @(
                "000001.SH", "399001.SZ", "399006.SZ"
            )
        }
    }
    
    try {
        $config | ConvertTo-Json -Depth 10 | Out-File -FilePath $configPath -Encoding UTF8
        Write-ColorOutput "✅ 配置文件创建成功: $configPath" "Green"
    } catch {
        Write-ColorOutput "❌ 配置文件创建失败: $($_.Exception.Message)" "Red"
        throw
    }
}

# 创建快速启动脚本
function New-QuickStartScript {
    $scriptPath = "quick_start.bat"
    
    if (Test-Path $scriptPath) {
        Write-ColorOutput "✅ 快速启动脚本已存在" "Yellow"
        return
    }
    
    Write-ColorOutput "🚀 创建快速启动脚本..." "Blue"
    
    $scriptContent = @"
@echo off
chcp 65001 > nul
echo 🚀 Kronos 快速启动菜单
echo ========================
echo.
echo 1. 检查环境
echo 2. 配置Tushare
echo 3. 获取数据
echo 4. 运行预测
echo 5. 批量获取数据
echo 0. 退出
echo.
set /p choice=请选择操作 (0-5): 

if "%choice%"=="1" (
    python scripts/check_environment.py
) else if "%choice%"=="2" (
    python scripts/setup_tushare.py
) else if "%choice%"=="3" (
    python scripts/fetch_data.py --help
) else if "%choice%"=="4" (
    python scripts/run_prediction.py --list-data
) else if "%choice%"=="5" (
    python scripts/batch_fetch.py --help
) else if "%choice%"=="0" (
    exit
) else (
    echo 无效选择
)

pause
"@
    
    try {
        $scriptContent | Out-File -FilePath $scriptPath -Encoding ASCII
        Write-ColorOutput "✅ 快速启动脚本创建成功: $scriptPath" "Green"
    } catch {
        Write-ColorOutput "❌ 快速启动脚本创建失败: $($_.Exception.Message)" "Red"
    }
}

# 显示安装后信息
function Show-PostInstallInfo {
    Write-ColorOutput "`n🎉 Kronos项目安装完成!" "Green"
    Write-ColorOutput "=" * 50 "Green"
    
    Write-ColorOutput "`n📋 下一步操作:" "Blue"
    Write-ColorOutput "1. 配置Tushare API Token:" "White"
    Write-ColorOutput "   python scripts/setup_tushare.py" "Cyan"
    
    Write-ColorOutput "`n2. 检查环境配置:" "White"
    Write-ColorOutput "   python scripts/check_environment.py" "Cyan"
    
    Write-ColorOutput "`n3. 获取股票数据:" "White"
    Write-ColorOutput "   python scripts/fetch_data.py --symbol 600000.SH" "Cyan"
    
    Write-ColorOutput "`n4. 运行预测:" "White"
    Write-ColorOutput "   python scripts/run_prediction.py" "Cyan"
    
    Write-ColorOutput "`n5. 或使用快速启动:" "White"
    Write-ColorOutput "   .\quick_start.bat" "Cyan"
    
    Write-ColorOutput "`n📚 获取Tushare Token:" "Yellow"
    Write-ColorOutput "   https://tushare.pro/register" "Cyan"
    
    Write-ColorOutput "`n📖 项目文档:" "Yellow"
    Write-ColorOutput "   README.md" "Cyan"
    
    Write-ColorOutput "`n" "White"
}

# 主安装函数
function Install-Kronos {
    Write-ColorOutput "🚀 Kronos项目PowerShell安装程序" "Blue"
    Write-ColorOutput "=" * 50 "Blue"
    Write-ColorOutput "适用于Windows PowerShell 5.1+ 和 PowerShell Core 6.0+`n" "Cyan"
    
    # 检查PowerShell版本
    $psVersion = $PSVersionTable.PSVersion
    Write-ColorOutput "PowerShell版本: $psVersion" "Cyan"
    
    if ($psVersion.Major -lt 5) {
        Write-ColorOutput "❌ PowerShell版本过低，需要5.1+" "Red"
        exit 1
    }
    
    # 检查管理员权限（可选）
    if (Test-Administrator) {
        Write-ColorOutput "⚡ 检测到管理员权限" "Yellow"
    } else {
        Write-ColorOutput "ℹ️  以普通用户权限运行" "Cyan"
    }
    
    try {
        # 1. 检查Python环境
        Write-ColorOutput "`n🔍 步骤 1/7: 检查Python环境" "Blue"
        if (!(Test-PythonInstallation)) {
            throw "Python环境检查失败"
        }
        
        if (!(Test-PipInstallation)) {
            throw "pip检查失败"
        }
        
        # 2. 创建目录结构
        Write-ColorOutput "`n📁 步骤 2/7: 创建项目目录" "Blue"
        New-ProjectDirectories
        
        # 3. 升级pip
        Write-ColorOutput "`n🔄 步骤 3/7: 升级pip" "Blue"
        Update-Pip
        
        # 4. 安装基础依赖
        Write-ColorOutput "`n📦 步骤 4/7: 安装基础依赖" "Blue"
        $basicPackages = @("numpy", "pandas", "torch", "einops", "huggingface_hub", "safetensors")
        
        # 尝试使用镜像源
        $useMirror = $false
        $mirrorChoice = Read-Host "是否使用国内镜像源加速下载? (Y/n)"
        if ($mirrorChoice -eq "" -or $mirrorChoice -match "^[Yy]") {
            $useMirror = $true
        }
        
        if (!(Install-PythonPackages -Packages $basicPackages -Description "基础依赖" -UseMirror:$useMirror)) {
            throw "基础依赖安装失败"
        }

        # 5. 安装数据源依赖 (Tushare, Baostock)
        Write-ColorOutput "`n📈 步骤 5/7: 安装数据源依赖 (Tushare, Baostock)" "Blue"
        if (!(Install-PythonPackages -Packages @("tushare") -Description "Tushare" -UseMirror:$useMirror)) {
            Write-ColorOutput "⚠️  Tushare安装失败，但继续安装" "Yellow"
        }
        if (!(Install-PythonPackages -Packages @("baostock") -Description "Baostock" -UseMirror:$useMirror)) {
            Write-ColorOutput "⚠️  Baostock安装失败，但继续安装" "Yellow"
        }

        # 6. 安装可视化依赖
        Write-ColorOutput "`n📊 步骤 6/7: 安装可视化依赖" "Blue"
        $vizPackages = @("matplotlib", "tqdm")
        if (!(Install-PythonPackages -Packages $vizPackages -Description "可视化依赖" -UseMirror:$useMirror)) {
            Write-ColorOutput "⚠️  可视化依赖安装失败，但继续安装" "Yellow"
        }
        
        # 7. 创建配置文件和脚本
        Write-ColorOutput "`n⚙️  步骤 7/7: 创建配置文件" "Blue"
        New-ConfigurationFile
        New-QuickStartScript
        
        # 显示安装后信息
        Show-PostInstallInfo
        
        Write-ColorOutput "✅ 安装成功完成!" "Green"
        return 0
        
    } catch {
        Write-ColorOutput "`n❌ 安装失败: $($_.Exception.Message)" "Red"
        Write-ColorOutput "请检查错误信息并重试" "Yellow"
        return 1
    }
}

# 脚本入口点
if ($MyInvocation.InvocationName -ne '.') {
    # 直接运行脚本
    $exitCode = Install-Kronos
    
    if ($exitCode -eq 0) {
        Write-ColorOutput "`n按任意键退出..." "Cyan"
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    }
    
    exit $exitCode
}