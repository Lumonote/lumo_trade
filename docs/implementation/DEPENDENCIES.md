# Kronos 项目依赖说明

本文档详细说明了 Kronos 股票预测系统中各个依赖包的用途和版本要求。

## 核心机器学习依赖

### numpy

- **用途**: 数值计算基础库，提供多维数组对象和数学函数
- **版本**: 2.1.0+
- **作用**: 支持所有数值计算操作，是 pandas 和 torch 的基础依赖

### pandas

- **用途**: 数据分析和处理库
- **版本**: 2.2.3+
- **作用**: 处理股票数据的读取、清洗、转换和分析
- **主要功能**:
    - 股票数据的 DataFrame 操作
    - 时间序列数据处理
    - 数据清洗和预处理

### torch

- **用途**: PyTorch 深度学习框架
- **版本**: 2.5.0+
- **作用**: 构建和训练神经网络模型
- **主要功能**:
    - 定义股票预测模型架构
    - 模型训练和推理
    - GPU 加速计算

## 深度学习辅助依赖

### einops (0.8.1)

- **用途**: 张量操作简化库
- **版本**: 0.8.1
- **作用**: 简化复杂的张量重塑和维度操作
- **应用场景**: 处理时间序列数据的维度变换

### huggingface_hub (0.33.1)

- **用途**: Hugging Face 模型中心客户端
- **版本**: 0.33.1
- **作用**: 下载和管理预训练模型
- **功能**: 支持从 Hugging Face 加载预训练的时间序列模型

### safetensors (0.6.2)

- **用途**: 安全的张量序列化格式
- **版本**: 0.6.2
- **作用**: 安全地保存和加载模型权重
- **优势**: 比传统 pickle 格式更安全，防止代码注入

## 数据可视化依赖

### matplotlib

- **用途**: 数据可视化库
- **版本**: 3.9.0+
- **作用**: 生成股票数据图表和预测结果可视化
- **功能**:
    - 股价走势图
    - 预测结果对比图
    - 技术指标图表

### tqdm (4.67.1)

- **用途**: 进度条显示库
- **版本**: 4.67.1
- **作用**: 在数据处理和模型训练过程中显示进度
- **应用**: 批量数据获取、模型训练进度显示

## 网络爬虫依赖

### playwright

- **用途**: 现代化网页自动化和爬虫框架
- **版本**: 1.49.0+
- **作用**: 从各大财经网站爬取股票数据
- **主要功能**:
    - 模拟浏览器行为
    - 处理 JavaScript 渲染的页面
    - 绕过基础反爬虫机制
    - 支持多种浏览器引擎

### requests (2.31.0)

- **用途**: HTTP 请求库
- **版本**: 2.31.0
- **作用**: 发送 HTTP 请求获取网页数据
- **应用场景**:
    - API 数据获取
    - 简单网页内容抓取
    - 与 Tushare 等数据源交互

### beautifulsoup4 (4.12.2)

- **用途**: HTML/XML 解析库
- **版本**: 4.12.2
- **作用**: 解析和提取网页中的股票数据
- **功能**:
    - HTML 文档解析
    - CSS 选择器支持
    - 数据提取和清洗

### fake-useragent (1.4.0)

- **用途**: 随机 User-Agent 生成器
- **版本**: 1.4.0
- **作用**: 模拟不同浏览器的请求头，避免被网站识别为爬虫
- **功能**:
    - 随机生成真实的 User-Agent
    - 提高爬虫的隐蔽性
    - 减少被反爬虫系统检测的概率

## 依赖关系图

```
核心数据处理流程:
numpy → pandas → 数据预处理
       ↓
    torch → 模型训练 → safetensors (模型保存)
       ↓
  matplotlib → 结果可视化

数据获取流程:
requests/playwright → beautifulsoup4 → 数据解析
       ↓
 fake-useragent → 反爬虫处理
       ↓
    pandas → 数据标准化
```

## 安装说明

### 基础安装

```bash
pip install -r requirements.txt
```

### Python 3.12/3.13 升级预检

```bash
python scripts/check_runtime_upgrade.py
```

该脚本用于检查解释器版本、NumPy 2.x、Pandas 2.2.3+、PyTorch 2.5+、WebUI 依赖和数据源依赖导入状态。切换 Python 3.12 或 3.13 前先运行预检，再执行业务回归脚本。

### 桌面端自包含 backend

```bash
python packaging/scripts/build_backend.py --clean --mode lite
```

`lite` 是默认桌面发布模式，会把 Python 运行时和 WebUI 基础依赖一起打进 Tauri 资源目录，用户机器不需要再安装 Python 或 pip 依赖，也不再依赖外部环境检测。该模式设置 `KRONOS_DISABLE_TORCH=1`，在 WebUI 导入层禁用 torch/modelscope/Kronos 模型推理依赖，适合保证桌面壳和 WebUI 首屏稳定启动。

桌面 backend 以 Robyn 入口启动，WebUI HTTP 路由全部为原生 Robyn handler。Flask 已于 2026-05-23 完整移除，Robyn 是唯一受支持的 HTTP runtime，不再提供 Flask 回退入口。

如需把模型推理依赖也打入 backend，可使用：

```bash
KRONOS_BACKEND_BUNDLE_MODE=full python packaging/scripts/build_backend.py --clean --mode full
```

`full` 模式体积更大，并需要单独验证 PyInstaller 与 PyTorch 在目标平台上的动态库兼容性。

当前 macOS / PyInstaller / PyTorch 2.12 组合下，`full` 模式可以完成构建，但运行 `--import-check` 会在 native 层异常终止，尚未作为默认发布包。正式桌面发布请继续使用 `lite` 模式；需要模型推理时优先走源码环境或等待 full bundle 兼容性修复。

### Playwright 浏览器安装

```bash
# 安装 Playwright 浏览器
playwright install chromium

# 或安装所有浏览器
playwright install
```

### 系统要求

- Python 3.11+，推荐 3.12；3.13 进入升级验证通道
- 至少 4GB 内存（推荐 8GB+）
- 磁盘空间：至少 2GB（包含浏览器文件）

## 版本兼容性

- **Python**: 3.11-3.13
- **NumPy**: 2.1.0+
- **Pandas**: 2.2.3+
- **PyTorch**: 2.5.0+
- **操作系统**: Windows 10+, macOS 10.14+, Ubuntu 18.04+
- **GPU 支持**: CUDA 11.0+ (可选，用于 PyTorch GPU 加速)

## 常见问题

### Q: Playwright 安装失败怎么办？

A: 确保网络连接正常，可以使用国内镜像：

```bash
playwright install chromium --with-deps
```

### Q: torch 安装很慢？

A: 可以使用清华大学镜像：

```bash
pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### Q: 某些依赖版本冲突？

A: 建议使用虚拟环境：

```bash
python -m venv kronos_env
source kronos_env/bin/activate  # Linux/Mac
# 或
kronos_env\Scripts\activate  # Windows
pip install -r requirements.txt
```

## 更新日志

- **v1.3.0**: 升级运行时依赖基线，支持 Python 3.12/3.13 验证通道
- **v1.2.0**: 新增 Playwright 爬虫支持
- **v1.1.0**: 升级 pandas 到 2.2.2，提升数据处理性能
- **v1.0.0**: 初始版本，基础机器学习功能
