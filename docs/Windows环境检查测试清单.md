# Windows 环境检查修复测试清单

## 前置条件

- Windows 10/11 系统
- 已安装打包版Kronos应用
- 系统存在多个Python版本(可选,用于测试优先级)

## 测试步骤

### 1. 依赖安装测试

**操作**: 运行 `quick_start.ps1 1` (安装依赖)

**预期结果**:
```
✅ 发现已存在的虚拟环境 -> C:\Users\[用户名]\AppData\Local\Kronos\venv
或
✅ 创建用户级虚拟环境 -> C:\Users\[用户名]\AppData\Local\Kronos\venv

Looking in indexes: https://pypi.tuna.tsinghua.edu.cn/simple/
Requirement already satisfied: numpy...
Requirement already satisfied: pandas...
...
✅ 用户虚拟环境与依赖已就绪
```

### 2. 环境检查测试

**操作**: 运行 `quick_start.ps1 3` (检查环境)

**预期结果**:
```
INFO: 使用 Python: C:\Users\[用户名]\AppData\Local\Kronos\venv\Scripts\python.exe

============================================================
    Kronos 环境检测工具
============================================================

系统信息
[INFO] Python路径: C:\Users\[用户名]\AppData\Local\Kronos\venv\Scripts\python.exe

必需依赖包检查
[OK] numpy: 1.26.4
[OK] pandas: 2.3.3
[OK] torch: 2.9.0
[OK] matplotlib: 3.10.7
[OK] tqdm: 4.67.1
[OK] safetensors: 0.6.2
[OK] einops: 0.8.1
[OK] huggingface_hub: 0.35.3

检查总结
[OK] 🎉 环境检查通过！所有组件都已正确安装和配置。
```

**错误情况** (修复前):
```
[INFO] Python路径: C:\Users\[用户名]\Anaconda3\python.EXE  ❌ 错误!
[ERROR] numpy: 未安装  ❌
[ERROR] pandas: 未安装  ❌
```

### 3. 批量预测测试

**操作**: 运行 `quick_start.ps1 6` (批量预测)

**预期结果**:
```
INFO: 使用 Python: C:\Users\[用户名]\AppData\Local\Kronos\venv\Scripts\python.exe
✅ 多数据源获取器初始化成功
✅ 批量预测成功生成HTML报告
```

### 4. 投资机会挖掘测试

**操作**: 运行 `quick_start.ps1 7` (投资机会挖掘)

**预期结果**:
```
INFO: 使用 Python: C:\Users\[用户名]\AppData\Local\Kronos\venv\Scripts\python.exe
正在启动投资机会挖掘系统...
✅ 成功生成HTML投资机会报告
```

### 5. 多Python版本共存测试

**前置条件**: 系统同时安装了Anaconda和系统Python

**操作**:
1. 打开PowerShell
2. 运行 `where python` 查看所有Python路径
3. 运行 `quick_start.ps1 3`

**预期结果**:
- 即使系统PATH中有多个Python,环境检查也应使用虚拟环境的Python
- 不应受系统Python版本影响

### 6. GUI启动器测试

**操作**:
1. 双击运行 `kronos_app.py` 或打包的GUI应用
2. 选择任意功能(如批量预测)

**预期结果**:
```
🔍 检测Python环境...
✅ 使用用户虚拟环境Python 3.11.9: C:\Users\[用户名]\AppData\Local\Kronos\venv\Scripts\python.exe
```

## 验证要点

### ✅ Python路径正确性
- [ ] 环境检查显示的Python路径包含 `\AppData\Local\Kronos\venv\`
- [ ] 不是Anaconda路径 (如 `Anaconda3\python.exe`)
- [ ] 不是系统Python路径 (如 `C:\Python39\python.exe`)

### ✅ 依赖包检测
- [ ] 所有必需依赖显示 `[OK]` 状态
- [ ] 显示正确的版本号
- [ ] 无 `[ERROR] xxx: 未安装` 错误

### ✅ GPU检测 (可选)
- [ ] 如果有NVIDIA GPU,应显示GPU信息
- [ ] 如果无GPU或DLL问题,应显示警告而非错误

### ✅ 功能完整性
- [ ] 批量预测功能正常运行
- [ ] 投资机会挖掘功能正常运行
- [ ] 生成的HTML报告可正常打开

## 常见问题排查

### 问题1: 仍显示Anaconda Python路径

**原因**: 环境变量未正确传递

**解决方案**:
1. 检查 `quick_start.ps1` 第110行是否有 `$env:KRONOS_PYTHON_PATH = $python`
2. 检查 `check_environment.py` 第93行是否有环境变量检查逻辑

### 问题2: 依赖仍显示未安装

**原因**: 虚拟环境创建失败或依赖安装失败

**解决方案**:
1. 检查 `%LocalAppData%\Kronos\venv` 是否存在
2. 重新运行 `quick_start.ps1 1` 安装依赖
3. 检查网络连接和镜像源

### 问题3: GUI启动器无法找到虚拟环境

**原因**: `python_detector.py` 未更新

**解决方案**:
1. 确认 `tools/python_detector.py` 第44-61行包含虚拟环境检测逻辑
2. 重新打包应用(如果是打包版本)

## 测试报告模板

**测试日期**: ________

**测试环境**:
- 操作系统: Windows _____
- Python版本(系统): _____
- 是否有多Python: 是/否

**测试结果**:

| 测试项 | 状态 | 备注 |
|--------|------|------|
| 依赖安装 | ✅/❌ | |
| 环境检查-Python路径 | ✅/❌ | |
| 环境检查-依赖检测 | ✅/❌ | |
| 批量预测 | ✅/❌ | |
| 投资机会挖掘 | ✅/❌ | |
| GUI启动器 | ✅/❌ | |

**问题记录**:
-

**修复建议**:
-
