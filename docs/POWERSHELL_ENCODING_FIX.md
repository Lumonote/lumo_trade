# Windows打包PowerShell编码问题修复方案

## 问题描述

Windows打包后出现PowerShell脚本编码问题，主要表现为：

1. 中文字符显示为乱码
2. PowerShell解析器报语法错误
3. 脚本无法正常执行

## 问题原因

1. **编码问题**：PyInstaller打包时没有正确处理UTF-8编码的PowerShell文件
2. **BOM缺失**：Windows PowerShell需要UTF-8 BOM来正确识别编码
3. **字符串拼接**：PowerShell脚本中使用了不安全的字符串拼接方式

## 修复方案

### 1. PowerShell脚本修复

#### 1.1 编码设置

```powershell
# 强制UTF-8编码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# 设置控制台代码页
chcp 65001 | Out-Null

# 设置PowerShell编码
$PSDefaultParameterValues['*:Encoding'] = 'utf8'
```

#### 1.2 字符串处理

将字符串拼接从：

```powershell
Write-Host ("STEP 步骤 " + $step + "/" + $totalSteps + ": 安装依赖...")
```

改为：

```powershell
Write-Host "STEP 步骤 $step/$totalSteps : 安装依赖..."
```

### 2. 打包配置修复

#### 2.1 PyInstaller Hook

创建 `packaging/hooks/hook-powershell.py`：

```python
def hook(hook_api):
# 确保PowerShell文件以UTF-8 BOM格式打包
# 处理编码问题
```

#### 2.2 Spec文件更新

在 `packaging/specs/kronos_windows.spec` 中：

```python
hookspath = [os.path.join(project_root, 'packaging/hooks')],
```

### 3. 执行脚本优化

#### 3.1 批处理执行脚本

创建 `run_powershell.bat`：

```batch
@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "quick_start.ps1" %*
```

#### 3.2 启动脚本修改

在 `tools/launchers/kronos_modern_gui.py` 中：

```python
if run_script.exists():
    final_command = f'"{run_script}" {script_args}'
```

## 修复文件清单

1. **quick_start.ps1** - 修复编码和字符串处理
2. **run_powershell.bat** - 新增批处理执行脚本
3. **packaging/hooks/hook-powershell.py** - 新增PyInstaller Hook
4. **packaging/specs/kronos_windows.spec** - 更新打包配置
5. **tools/launchers/kronos_modern_gui.py** - 修改启动逻辑
6. **scripts/fix_powershell_encoding.py** - 编码修复工具
7. **scripts/test_powershell_encoding.py** - 测试脚本

## 测试验证

### 1. 编码测试

```bash
python scripts/test_powershell_encoding.py
```

### 2. 打包测试

```bash
python packaging/scripts/build.py --target windows
```

### 3. 功能测试

运行打包后的应用，测试PowerShell脚本功能是否正常。

## 使用说明

### 开发环境

1. 确保PowerShell文件以UTF-8 BOM格式保存
2. 使用字符串插值而不是拼接
3. 添加适当的编码设置

### 打包环境

1. 运行打包脚本会自动应用修复
2. 检查生成的批处理文件是否正确
3. 验证PowerShell脚本编码

### 用户环境

1. 双击 `run_powershell.bat` 执行PowerShell脚本
2. 或通过主应用界面执行相关功能
3. 确保Windows系统支持UTF-8编码

## 注意事项

1. **BOM要求**：Windows PowerShell需要UTF-8 BOM
2. **执行策略**：使用 `-ExecutionPolicy Bypass` 跳过限制
3. **编码一致性**：确保所有相关文件使用相同编码
4. **错误处理**：添加适当的错误处理和回退机制

## 故障排除

### 问题1：仍然出现乱码

- 检查文件是否以UTF-8 BOM格式保存
- 确认控制台代码页设置为65001
- 验证PowerShell编码设置

### 问题2：语法错误

- 检查字符串拼接语法
- 确认引号匹配
- 验证变量引用格式

### 问题3：执行失败

- 检查执行策略设置
- 确认文件路径正确
- 验证权限设置

## 更新日志

- **v1.0** - 初始修复方案
- **v1.1** - 添加批处理执行脚本
- **v1.2** - 优化字符串处理
- **v1.3** - 完善测试和文档
