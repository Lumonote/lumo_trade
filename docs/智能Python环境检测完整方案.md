# 智能Python环境检测系统 - 完整解决方案

## 🎯 核心理念

**问题**: 不同用户的机器上Python环境千差万别:
- 有的用Anaconda
- 有的用virtualenv/venv
- 有的用pyenv
- 有的有多个Python版本共存

**原有方案的局限**:
- 硬编码固定路径 → 只适用特定环境
- 简单的PATH查找 → 可能找到错误的Python
- 手动配置 → 用户体验差

**新方案**: 智能检测 + 自动匹配 + 缓存优化

## 📦 组件架构

```
tools/
├── smart_env_detector.py     # 智能环境检测器(核心)
└── python_detector.py         # Python命令检测器(集成层)

scripts/
└── check_environment.py       # 环境检查脚本(使用层)

quick_start.ps1               # PowerShell启动脚本
```

## 🔍 检测流程

### 1. 多层次环境扫描

```python
SmartEnvDetector.detect_all_environments():
    1. Kronos虚拟环境 (专用)
    2. 当前激活的虚拟环境
    3. Conda环境 (所有)
    4. pyenv环境 (macOS/Linux)
    5. 系统Python
    6. 项目虚拟环境 (venv/, .venv/等)
```

### 2. 智能评分系统

```
基础评分 (根据环境类型):
- Kronos虚拟环境: 1000分
- 激活的虚拟环境: 900分
- 项目虚拟环境: 800分
- pyenv环境: 700分
- Conda环境: 500分
- 系统Python: 300分

依赖加分:
+ PyTorch安装: +100分
+ Pandas安装: +50分
+ NumPy安装: +30分
+ Python 3.11: +50分
+ Python 3.12: +40分

最终评分 = 基础评分 + 依赖加分
```

### 3. 缓存机制

```
首次检测 → 完整扫描 (5-10秒)
     ↓
保存缓存 (~/.kronos/env_cache.json)
     ↓
后续使用 → 读取缓存 (<1秒)
```

## 💡 使用场景

### 场景1: 新用户首次安装

```bash
# 用户下载Kronos后直接运行
python tools/smart_env_detector.py

# 输出:
🔍 开始扫描Python环境...
  ✓ Conda环境 'base': /Users/xxx/anaconda3/bin/python
  ✓ 系统Python: /usr/bin/python3
✅ 发现 2 个Python环境

🎯 推荐使用: base (评分: 630)
   提示: 建议创建Kronos专用虚拟环境以获得最佳体验
```

### 场景2: 已有Kronos虚拟环境

```bash
python tools/smart_env_detector.py

# 输出:
🔍 开始扫描Python环境...
  ✓ Kronos虚拟环境: C:\Users\xxx\AppData\Local\Kronos\venv\Scripts\python.exe
  ✓ Conda环境 'base': C:\Users\xxx\anaconda3\python.exe
✅ 发现 2 个Python环境

🎯 推荐使用: Kronos-venv (评分: 1180)
   路径: C:\Users\xxx\AppData\Local\Kronos\venv\Scripts\python.exe
   版本: Python 3.11.9
   依赖: torch✓, pandas✓, numpy✓
```

### 场景3: 多环境共存 + 依赖不全

```bash
python tools/smart_env_detector.py

# 输出:
================================================================================
检测到 5 个Python环境:
================================================================================

[1] Kronos-venv (评分: 1180)
    依赖: torch✓, pandas✓, numpy✓    ← 推荐

[2] project-venv (评分: 830)
    依赖: torch✓, pandas✗, numpy✗

[3] pyenv-3.11.9 (评分: 730)
    依赖: torch✗, pandas✗, numpy✗

[4] base (评分: 580)
    依赖: torch✓, pandas✓, numpy✓

[5] system-python (评分: 300)
    依赖: torch✗, pandas✗, numpy✗

🎯 推荐使用: Kronos-venv (评分: 1180)
```

## 🔧 集成方式

### 方式1: 在Python脚本中使用

```python
# 简单使用
from tools.python_detector import get_python_command

python = get_python_command(use_smart_detection=True)
subprocess.run([python, 'script.py'])
```

```python
# 高级使用
from tools.smart_env_detector import SmartEnvDetector

detector = SmartEnvDetector()

# 加载缓存(快速)
if detector.load_cache():
    best_env = detector.get_best_environment()
else:
    # 完整检测
    detector.detect_all_environments()
    best_env = detector.get_best_environment()
    detector.save_cache()

if best_env:
    print(f"使用: {best_env.path}")
    print(f"版本: {best_env.version}")
    print(f"依赖完整性: {best_env.score}/1000+")
```

### 方式2: 在PowerShell中使用

```powershell
function Get-SmartPython {
    $detectScript = "tools\smart_env_detector.py"

    try {
        # 调用智能检测器
        $result = python $detectScript 2>&1

        if ($LASTEXITCODE -eq 0) {
            # 解析输出,提取推荐的Python路径
            # (或直接从缓存JSON读取)
            return $result
        }
    } catch {
        # 回退到传统逻辑
        return Get-PythonCommand
    }
}
```

### 方式3: 在环境检查中使用

`scripts/check_environment.py` 已集成:

```python
def get_actual_python_path():
    # 优先级1: 环境变量
    env_python = os.environ.get('KRONOS_PYTHON_PATH')
    if env_python:
        return env_python

    # 优先级2: 智能检测
    try:
        from tools.smart_env_detector import SmartEnvDetector
        detector = SmartEnvDetector()

        if detector.load_cache():
            best_env = detector.get_best_environment()
            if best_env:
                return best_env.path
    except:
        pass

    # 优先级3: 传统逻辑
    return traditional_detection()
```

## 🚀 性能优化

### 缓存策略

| 场景 | 首次检测 | 缓存加载 | 性能提升 |
|------|---------|----------|---------|
| 2个环境 | 3-5秒 | <0.1秒 | 30-50x |
| 5个环境 | 8-12秒 | <0.1秒 | 80-120x |
| 10个环境 | 15-25秒 | <0.1秒 | 150-250x |

### 缓存失效条件

- 手动删除 `~/.kronos/env_cache.json`
- 环境变化(安装/卸载Python)
- 定期刷新(建议7天)

## 🎓 最佳实践

### 1. 初次使用

```bash
# Step 1: 运行智能检测
python tools/smart_env_detector.py

# Step 2: 如果推荐创建虚拟环境
# Windows:
.\quick_start.ps1 1

# macOS/Linux:
./quick_start.sh
选择 "1) 安装依赖"

# Step 3: 验证环境
.\quick_start.ps1 3  # Windows
./quick_start.sh → 选择 "3) 检查环境"  # macOS/Linux
```

### 2. 环境迁移/更新

```bash
# 删除缓存,强制重新检测
rm ~/.kronos/env_cache.json  # macOS/Linux
del %USERPROFILE%\.kronos\env_cache.json  # Windows

# 重新检测
python tools/smart_env_detector.py
```

### 3. 多项目场景

每个项目使用独立虚拟环境:

```bash
# 项目A
cd ProjectA
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate  # Windows

# 智能检测会自动识别并优先使用项目虚拟环境(评分800+)
python tools/smart_env_detector.py
```

## 📊 优势对比

| 特性 | 传统方案 | 智能检测方案 |
|------|---------|-------------|
| 环境识别 | 单一路径 | 多种环境类型 |
| 优先级 | 固定 | 智能评分 |
| 依赖检查 | 无 | 自动检测 |
| 用户体验 | 需手动配置 | 自动推荐 |
| 性能 | 快速但不准 | 首次慢,缓存后快 |
| 兼容性 | 特定场景 | 广泛兼容 |
| 可扩展性 | 低 | 高(评分规则可调) |

## 🐛 故障排除

### 问题1: 检测不到Conda环境

**原因**: conda命令不在PATH中

**解决**:
```bash
# 临时添加到PATH
export PATH="/Users/xxx/anaconda3/bin:$PATH"  # macOS/Linux
$env:PATH = "C:\Users\xxx\anaconda3\Scripts;$env:PATH"  # Windows

# 或在conda activate后运行检测
conda activate base
python tools/smart_env_detector.py
```

### 问题2: 推荐的环境不是我想要的

**解决**: 自定义评分规则

编辑 `tools/smart_env_detector.py`:

```python
def _deduplicate_and_score(self, envs):
    for env in envs:
        # 调整评分规则
        if env.name == 'my-favorite-env':
            env.score += 500  # 提高特定环境的优先级

        # 或者调整依赖权重
        if env.has_torch:
            env.score += 200  # 原来是100
```

### 问题3: 缓存过期/不准确

```bash
# 删除缓存并重新检测
rm ~/.kronos/env_cache.json
python tools/smart_env_detector.py
```

## 📚 相关文档

- [智能环境检测使用指南.md](./智能环境检测使用指南.md) - 详细使用说明
- [Windows环境检查修复说明.md](./Windows环境检查修复说明.md) - Windows特定问题
- [Windows_PyTorch_DLL问题修复指南.md](./Windows_PyTorch_DLL问题修复指南.md) - PyTorch问题

## 🔮 未来规划

- [ ] 自动创建推荐的虚拟环境
- [ ] 环境健康度评估(依赖版本冲突检测)
- [ ] GUI环境管理器
- [ ] Docker容器检测支持
- [ ] 远程Python环境支持(SSH)

---

**版本**: V1.0
**更新日期**: 2025-11-06
**适用场景**: 所有平台,所有Python环境配置
