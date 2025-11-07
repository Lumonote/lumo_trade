# Windows PyTorch DLL 初始化失败修复指南

## 问题现象

```
[WARNING] GPU: 检查失败: [WinError 1114] 动态链接库(DLL)初始化例程失败。
Error loading "C:\Users\palmer\AppData\Local\Kronos\venv\Lib\site-packages\torch\lib\c10.dll"

[ERROR] torch: 检查失败: Command timed out after 10 seconds
```

## 根本原因

PyTorch的C++库(c10.dll)初始化失败,通常由以下原因引起:

1. **缺少Microsoft Visual C++ Redistributable**
2. **缺少CUDA运行时库** (如果安装的是GPU版本)
3. **DLL依赖冲突** (多个Python环境)
4. **PyTorch版本不兼容**

## 解决方案

### 方案1: 安装Microsoft Visual C++ Redistributable (推荐)

PyTorch需要Visual C++ 2019或更新版本的运行库。

**下载链接**:
- [Microsoft Visual C++ 2015-2022 Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)
- [Microsoft Visual C++ 2015-2022 Redistributable (x86)](https://aka.ms/vs/17/release/vc_redist.x86.exe)

**安装步骤**:
1. 下载对应版本(建议同时安装x64和x86)
2. 运行安装程序
3. 重启命令行/应用
4. 重新测试

### 方案2: 重新安装PyTorch (CPU版本)

如果只需要CPU运算,建议安装CPU专用版本,避免CUDA依赖。

```powershell
# 激活虚拟环境
C:\Users\palmer\AppData\Local\Kronos\venv\Scripts\activate

# 卸载现有PyTorch
pip uninstall torch torchvision torchaudio -y

# 安装CPU版本 (从清华镜像)
pip install torch torchvision torchaudio --index-url https://pypi.tuna.tsinghua.edu.cn/simple/
```

**或者从官方源安装**:
```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 方案3: 增加超时时间 (临时方案)

如果PyTorch确实能用,只是加载慢,可以增加检查超时时间。

修改 `scripts/check_environment.py` 第139行:

```python
# 原来
timeout=10

# 改为
timeout=30  # 增加到30秒
```

### 方案4: 检查DLL依赖 (高级)

使用依赖检查工具查看缺少的DLL:

1. 下载 [Dependencies](https://github.com/lucasg/Dependencies/releases) (DLL依赖分析工具)
2. 打开 `C:\Users\palmer\AppData\Local\Kronos\venv\Lib\site-packages\torch\lib\c10.dll`
3. 查看缺少的依赖项
4. 根据缺少的DLL安装相应的运行库

## 验证修复

完成任一方案后,重新运行环境检查:

```powershell
.\quick_start.ps1 3
```

**成功标志**:
```
[OK] torch: 2.x.x
[OK] GPU: CUDA不可用,将使用CPU (如果是CPU版本)
或
[OK] GPU: 1个GPU可用 (NVIDIA ...) (如果是GPU版本)
```

## 常见问题

### Q1: 我需要GPU版本吗?

**A**: 大多数用户使用CPU版本即可:
- ✅ CPU版本: 适合日常预测、小批量分析
- ⚠️ GPU版本: 仅在训练大模型或处理海量数据时需要

### Q2: 如何判断我装的是CPU还是GPU版本?

```powershell
C:\Users\palmer\AppData\Local\Kronos\venv\Scripts\python.exe -c "import torch; print(torch.__version__)"
```

输出包含 `+cpu` 表示CPU版本,如: `2.0.1+cpu`
输出包含 `+cu117` 等表示GPU版本(CUDA 11.7)

### Q3: 安装VC++ Redistributable后仍然报错?

1. 确认同时安装了x64和x86版本
2. 重启计算机(某些DLL需要重启才能生效)
3. 尝试方案2重新安装PyTorch

### Q4: 超时但最终能用?

某些系统第一次加载PyTorch确实很慢(初始化CUDA或加载大量DLL)。可以:
1. 增加超时时间(方案3)
2. 运行一次实际预测,PyTorch加载后就快了

## 推荐配置

### 标准配置 (大多数用户)

```powershell
# 安装Visual C++ 2015-2022 Redistributable (x64 + x86)
# 安装PyTorch CPU版本
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### GPU配置 (有NVIDIA显卡)

需要额外安装:
1. [NVIDIA驱动](https://www.nvidia.com/Download/index.aspx)
2. [CUDA Toolkit 11.8](https://developer.nvidia.com/cuda-11-8-0-download-archive) (根据PyTorch版本)
3. PyTorch GPU版本

```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

## 快速修复脚本

创建文件 `fix_pytorch.ps1`:

```powershell
# 激活虚拟环境
$venvPy = "C:\Users\palmer\AppData\Local\Kronos\venv\Scripts\python.exe"

Write-Host "正在卸载现有PyTorch..." -ForegroundColor Yellow
& $venvPy -m pip uninstall torch torchvision torchaudio -y

Write-Host "正在安装PyTorch CPU版本..." -ForegroundColor Cyan
& $venvPy -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

Write-Host "验证安装..." -ForegroundColor Green
& $venvPy -c "import torch; print(f'PyTorch版本: {torch.__version__}'); print(f'CUDA可用: {torch.cuda.is_available()}')"
```

运行:
```powershell
.\fix_pytorch.ps1
```

## 参考链接

- [PyTorch官网](https://pytorch.org/)
- [PyTorch安装指南](https://pytorch.org/get-started/locally/)
- [Microsoft VC++ Redistributable下载](https://docs.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
- [CUDA下载](https://developer.nvidia.com/cuda-downloads)

---

**修复状态**: ⏳ 待执行
**最后更新**: 2025-11-06
