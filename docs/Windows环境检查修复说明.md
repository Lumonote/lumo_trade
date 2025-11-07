# Windows 打包应用环境检查修复说明

## 问题描述

在 Windows 打包应用中,虽然依赖已成功安装到用户虚拟环境 (`%LocalAppData%\Kronos\venv`),但环境检查脚本报告所有依赖"未安装"。

### 问题表现

```
依赖安装输出:
OK: 发现已存在的虚拟环境 -> C:\Users\41240\AppData\Local\Kronos\venv
Requirement already satisfied: numpy... (所有依赖已安装)
DONE: 用户虚拟环境与依赖已就绪

环境检查输出:
INFO: Python路径: C:\Users\41240\Anaconda3\python.EXE (错误路径!)
[ERROR] numpy: 未安装
[ERROR] pandas: 未安装
...
```

## 根本原因

`check_environment.py` 脚本使用 `get_actual_python_path()` 函数查找 Python 解释器,该函数通过 `shutil.which()` 在 PATH 中查找,结果找到了系统的 Anaconda Python,而不是虚拟环境的 Python。

虽然 `quick_start.ps1` 正确使用了虚拟环境的 Python 运行检查脚本,但脚本内部又重新查找了一次 Python,导致路径错误。

## 解决方案

### 1. 修改 `quick_start.ps1`

在 `Invoke-Python` 函数中添加环境变量 `KRONOS_PYTHON_PATH`,将正确的 Python 路径传递给检查脚本:

```powershell
function Invoke-Python {
    ...
    # 设置 Python 路径环境变量,让检查脚本能使用正确的 Python
    $env:KRONOS_PYTHON_PATH = $python
    ...
}
```

### 2. 修改 `check_environment.py`

在 `get_actual_python_path()` 函数中添加优先级检查逻辑:

```python
def get_actual_python_path():
    """获取实际的Python解释器路径"""
    import shutil

    # 优先检查环境变量中指定的 Python (通常由 quick_start.ps1 设置)
    venv_python = os.environ.get('KRONOS_PYTHON_PATH')
    if venv_python and os.path.exists(venv_python):
        try:
            result = subprocess.run([venv_python, "--version"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "3." in result.stdout:
                return venv_python
        except:
            pass

    # Windows: 检查用户虚拟环境
    if platform.system() == "Windows":
        venv_dir = os.path.join(os.environ.get('LocalAppData', ''), 'Kronos', 'venv')
        venv_py = os.path.join(venv_dir, 'Scripts', 'python.exe')
        if os.path.exists(venv_py):
            try:
                result = subprocess.run([venv_py, "--version"],
                                        capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and "3." in result.stdout:
                    return venv_py
            except:
                pass

    # 回退到 shutil.which() 查找系统 Python
    ...
```

## 优先级逻辑

新的查找逻辑按以下优先级进行:

1. **环境变量** `KRONOS_PYTHON_PATH` - 由启动脚本显式设置
2. **Windows 用户虚拟环境** - `%LocalAppData%\Kronos\venv\Scripts\python.exe`
3. **系统 PATH** - 通过 `shutil.which()` 查找
4. **sys.executable** - 最后备选方案

## 测试验证

修复后,环境检查应正确显示:

```
INFO: Python路径: C:\Users\41240\AppData\Local\Kronos\venv\Scripts\python.exe
[OK] numpy: 1.26.4
[OK] pandas: 2.3.3
[OK] torch: 2.9.0
...
```

## 影响范围

此修复影响所有使用以下流程的场景:
- Windows 打包应用 (PyInstaller)
- 用户虚拟环境管理
- 环境检查功能

## 相关文件

- `quick_start.ps1:92-132` - 添加环境变量传递
- `scripts/check_environment.py:88-132` - 修改查找逻辑
- `tools/python_detector.py:24-102` - 添加虚拟环境优先级检测

## 额外修复

为了确保所有组件都能正确使用虚拟环境Python,还修复了:

### 1. `tools/python_detector.py`

GUI启动器和跨平台应用使用此模块检测Python命令。添加了优先级检测:

```python
def _detect_python_command(self):
    # 1. 最高优先级: KRONOS_PYTHON_PATH 环境变量
    env_python = os.environ.get('KRONOS_PYTHON_PATH')
    if env_python and Path(env_python).exists():
        ...

    # 2. Windows: 用户虚拟环境
    if self.system == 'Windows':
        venv_python = Path(local_app_data) / 'Kronos' / 'venv' / 'Scripts' / 'python.exe'
        if venv_python.exists():
            ...

    # 3. pyenv Python
    # 4. 系统PATH中的Python
    # 5. 默认Python命令
```

### 影响的功能

此修复确保以下所有功能都使用正确的虚拟环境Python:

1. ✅ 环境检查 (`quick_start.ps1` 选项3)
2. ✅ 批量预测分析 (`quick_start.ps1` 选项6)
3. ✅ 投资机会挖掘 (`quick_start.ps1` 选项7)
4. ✅ GUI界面启动器 (`kronos_app.py`, `kronos_modern_gui.py`)
5. ✅ macOS原生界面 (`kronos_native_macos.py`)
6. ✅ Web UI (`webui/app.py`)
7. ✅ 所有其他通过启动脚本调用的Python脚本

## 测试场景

### 场景1: Windows打包应用环境
- 依赖安装到: `%LocalAppData%\Kronos\venv`
- 环境检查应显示: `C:\Users\xxx\AppData\Local\Kronos\venv\Scripts\python.exe`
- 所有依赖包应显示为已安装

### 场景2: 多Python版本共存
- 系统已安装: Anaconda Python, Python 3.9, Python 3.11等
- 应优先使用虚拟环境Python,避免版本冲突

### 场景3: GUI启动器
- GUI通过 `python_detector.py` 检测Python
- 应自动找到虚拟环境Python并使用

## 版本信息

- 修复版本: V1.0+
- 修复日期: 2025-11-06
- 修复范围: Windows打包环境 + GUI启动器 + 所有Python调用
