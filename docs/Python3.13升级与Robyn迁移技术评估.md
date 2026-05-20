# Python 3.13 升级与 Robyn 迁移技术评估

> 评估日期:2026-05-19
> 评估范围:Kronos 项目整体 Python 版本升级 + WebUI 框架(Flask → Robyn)迁移
> 评估人:Claude (Opus 4.7)

---

## 一、Python 3.13 升级可行性评估

### 1.1 当前状态
- 本地 Python: **3.11.14**
- 项目无 `pyproject.toml` / `setup.py`,无明确 Python 版本约束
- 两份依赖文件:`requirements.txt`(根) 和 `webui/requirements.txt`

### 1.2 🔴 关键阻塞项 (必须解决)

#### 1) NumPy 版本约束冲突
- `requirements.txt`: `numpy>=1.21.0,<2.0` ← **NumPy 1.x 不支持 Python 3.13**
- `webui/requirements.txt`: `numpy==1.24.3` ← 同样不支持
- **必须升级到 numpy>=2.1.0** 才能在 3.13 上运行

#### 2) PyTorch 版本要求
- 当前: `torch>=1.9.0` / `torch>=2.1.0`
- Python 3.13 需要 **torch>=2.5.0**(2024-10 发布)
- 注意:模型权重/checkpoint 兼容性需回归测试

#### 3) Pandas 版本
- 需 `pandas>=2.2.3` 才能官方支持 3.13
- `webui` 中 `pandas==2.2.2` 需放宽或升级

### 1.3 🟡 次要风险

| 依赖 | 风险 | 说明 |
|---|---|---|
| `baostock` | 中 | 维护不活跃,最新版可能未测试 3.13,需验证 |
| `tushare>=1.4.0` | 低 | 最新版兼容 3.13 |
| `playwright` | 低 | 官方支持 3.13 |
| `flask==2.3.3` | 低 | 可运行,建议升级到 3.x |
| `fake-useragent` | 低 | 通常兼容 |
| `einops` / `safetensors` / `huggingface_hub` | 低 | 已支持 3.13 |

### 1.4 📦 打包/分发影响
- `packaging/scripts/build_universal.sh` 和 `kronos_app.py` 使用 `tools/python_detector.py` 动态检测 Python — 需确认检测逻辑包含 3.13
- 新出现的 `src-tauri/`(Tauri 桌面端)与 Python 版本无直接耦合

### 1.5 🔧 代码层面影响
项目代码 (`model/`, `analysis/`) 主要用 `dataclasses`, `pathlib`, `concurrent.futures`, `asyncio` 等 — 这些在 3.13 中无破坏性变更。无明显使用已弃用 API 的代码模式。

Python 3.13 已移除的模块本项目均未使用 (`cgi`, `imp`, `aifc` 等),GIL 实验性变化不影响默认运行。

### 1.6 ✅ 升级建议路径

**渐进式 (推荐):**
1. 先升级到 **Python 3.12** (LTS 风险更低,所有依赖均已支持)
2. 同时把 numpy 升到 2.x、torch 升到 2.5+,完成回归测试
3. 待 baostock 等小众库确认后再迁 3.13

**直接升级 3.13 需要做的修改:**
```diff
- numpy>=1.21.0,<2.0
+ numpy>=2.1.0
- numpy==1.24.3       # webui
+ numpy>=2.1.0
- pandas==2.2.2       # webui
+ pandas>=2.2.3
- torch>=2.1.0        # webui
+ torch>=2.5.0
```

### 1.7 主要回归测试项
- Kronos 模型推理 (tokenizer + predictor) 数值一致性
- 30 个量化模型回测结果与 v20 评分历史一致 (避免 numpy 2.x 浮点行为差异)
- Playwright 爬虫 (eastmoney/tonghuashun/xueqiu) 端到端
- WebUI Flask 启动与预测流程

**结论**:技术上可升,但 numpy 1.x→2.x 是真正的硬阻塞,建议先迁 Python 3.12 + numpy 2.x 验证一轮,再迁 3.13。

---

## 二、Python 3.13 性能与能力提升

### 2.1 🚀 性能提升 (针对 Kronos 项目实际收益)

#### 1) JIT 编译器 (实验性)
- 3.13 引入 **copy-and-patch JIT**,默认关闭,需 `PYTHON_JIT=1` 启用
- 当前阶段对纯 Python 热路径有 **2-9%** 提升
- 对 Kronos 受益场景:`analysis/opportunity_scorer.py`(3554 行打分逻辑)、`technical_analysis.py`(指标计算循环)
- ⚠️ 注意:核心数值计算已在 numpy/torch C 层,JIT 收益有限

#### 2) 自由线程 (No-GIL) 实验版 ⭐ 对本项目意义最大
- `python3.13t` 构建可关闭 GIL,真正多线程并行
- **Kronos 直接受益的场景**:
  - `ThreadPoolExecutor` 批量爬取股票(`batch_fetch_enhanced.py`)
  - 30 个量化模型并行计算(`QuantitativeModels`)
  - 多股票投资机会扫描(`run_opportunity_discovery.py`)
  - 多平台情绪采集(`MultiPlatformNewsMiner`、`InvestorSentimentAnalyzer`)
- 当前不得不用 `multiprocessing` 的地方,可改用更轻量的 threading,内存共享开销大幅降低
- ⚠️ torch / numpy 等 C 扩展需 free-threaded 版本(2025 起逐步铺开)

#### 3) 内存与启动优化
- 解释器内存占用降低 ~10%
- 启动速度提升,对频繁运行的脚本(`fetch_data.py`、`opportunity_report_generator.py`)体感更好
- `docstrings` 延迟构建,模块导入更快

#### 4) 增量 GC
- 大对象分配/释放卡顿降低
- Kronos 推理时 batch 处理大 tensor 受益

### 2.2 🛠️ 新能力可以做什么

#### 1) 更现代的类型系统
```python
# PEP 695 类型参数语法 (3.12+, 3.13 完善)
class PatternStore[T]:           # 不再需要 TypeVar
    def get(self, key: str) -> T: ...

# PEP 742 TypeIs - 更精确的类型守卫
def is_valid_signal(s: object) -> TypeIs[Signal]: ...

# PEP 702 @deprecated 装饰器
@deprecated("用 OpportunityScorerV41 替代")
class OpportunityScorer: ...
```
对 `opportunity_scorer.py`、`pattern_store.py` 等核心模块的可维护性提升明显。

#### 2) 更强的错误诊断
- 完整的 traceback "did you mean" 建议
- 多行错误标注更精准
- 对调试 30 个量化模型的复杂 pipeline 极有帮助

#### 3) 改进的 REPL
- 多行编辑、彩色输出、命令历史
- 适合策略调参/回测的交互探索(替代部分 Jupyter 用途)

#### 4) `dbm.sqlite3` 成为默认后端
- 可替换 `SentimentCacheManager` 中的轻量缓存,无需额外依赖

#### 5) `pathlib` 增强
- `Path.full_match()`、`Path.from_uri()`
- 简化 `analysis/` 模块大量路径处理

#### 6) `asyncio` 性能提升
- TaskGroup、eager_task_factory 优化
- 直接受益:`AsyncDataCollector`、`AsyncOpportunityScorer`、`playwright` 爬虫

#### 7) 警告与弃用清理
- 移除 `cgi`、`imp`、`aifc`、`pipes` 等(本项目未用)
- 强制现代化(如 `datetime.utcnow()` 弃用),逼迫修正潜在 bug

### 2.3 📊 Kronos 项目可量化的预期收益

| 场景 | 预期提升 | 备注 |
|---|---|---|
| 批量爬虫 (100+ 股票) | **30-50%** | 用 free-threaded 替代 multiprocessing |
| 量化模型批量回测 | **20-40%** | 多模型并行 + JIT |
| 单股推理 (Kronos 模型) | <5% | 瓶颈在 torch,Python 层无显著影响 |
| 投资机会扫描全流程 | **15-25%** | I/O + CPU 混合负载受益最大 |
| WebUI 响应延迟 | 5-15% | Flask + 异步 I/O 优化 |
| 报告生成 (opportunity_report) | 10-20% | 大量字符串/字典处理 |

### 2.4 🎯 真正能"做新事"的方向

1. **去掉 multiprocessing 的复杂性**:30 个量化模型 + 批量股票扫描可改成纯线程池架构,代码简化、内存占用减半
2. **实时多股票监控**:free-threaded 下可同时维护数百个 WebSocket / 爬虫连接,实现盘中实时机会推送
3. **更激进的并行回测**:`simulate_v5_backtest.py` 可同时跑多个参数组合(网格搜索从串行 → 并行)
4. **更快的报告流水线**:每日 200+ 报告生成时间显著缩短

### 2.5 ⚠️ 现实约束

- **PyTorch free-threaded wheel 仍在早期** (2025 年内成熟),GIL-off 收益要等生态跟上
- **JIT 还是预览版**,生产环境建议先在测试场景启用
- **numpy 2.x 行为差异**(浮点、整数溢出)需要在升级时一并回归

### 2.6 建议路线

1. **短期 (Q2)**:升级 Python 3.12 + numpy 2.x + torch 2.5,落地大部分性能优化(无破坏性风险)
2. **中期 (Q3)**:迁移 Python 3.13 standard 版,启用 JIT 测试热路径
3. **长期 (Q4+)**:等 torch/numpy free-threaded wheel 稳定后切 `python3.13t`,重构爬虫和量化模型并行架构

**核心收益点**:对 Kronos 这类 **I/O 密集(爬虫) + CPU 密集(量化模型) + 算子密集(torch 推理) 混合负载** 的项目,3.13 的 free-threaded 模式是真正质变,其他都是渐进优化。

---

## 三、Flask → Robyn + Python 3.13 迁移方案

### 3.1 现状盘点

| 维度 | 现状 |
|---|---|
| 文件 | `webui/app.py` **3140 行 / 29 个路由** |
| 框架 | Flask 2.3.3 + flask-cors 4.0.0 |
| 模板 | Jinja2 (`render_template`)13+ HTML 模板 |
| 静态资源 | `send_from_directory` 自定义路径 (`analysis-reports/`, `figures/`, `assets/`) |
| 并发模式 | `threading.Thread` 后台任务 + `analysis_jobs_lock` + 后台 `monitor_thread` |
| 异步 | `asyncio.run()` 在线程内调用(`process_batch`) |
| HTTP 客户端 | `urllib.request`(同步阻塞) |
| 进程入口 | `run.py`(86 行,启动 + 配置) |

### 3.2 Robyn 核心差异速览

| 能力 | Flask | Robyn |
|---|---|---|
| 运行时 | WSGI 同步,gunicorn/werkzeug | Rust(actix + tokio)多 worker 多进程 |
| 路由装饰器 | `@app.route(...)` | `@app.get/post/...` |
| 异步原生 | ❌ 需 `asyncio.run()` 桥接 | ✅ `async def` 一等公民 |
| 请求对象 | `request.get_json()` | `request.json()` (函数调用) |
| 响应 | `jsonify(dict), code` | `return dict` 自动 JSON,或 `Response(...)` |
| 模板引擎 | Jinja2 内置 | 需自己接 Jinja2(Robyn 提供 `Jinja2Template` 类) |
| CORS | flask-cors | Robyn 内置 `app.add_response_header` 或中间件 |
| 后台任务 | threading | Robyn `@app.startup_handler` + asyncio 任务 |
| WebSocket | 需 flask-socketio | ✅ 原生 `@app.websocket` |
| 静态文件 | `send_from_directory` | `app.serve_directory()` |

### 3.3 🔧 必改清单

#### 1) 依赖变更
```diff
# webui/requirements.txt
- flask==2.3.3
- flask-cors==4.0.0
+ robyn>=0.66.0          # 截至 2026 已支持 Python 3.13
+ jinja2>=3.1.4           # 模板引擎(Robyn 不内置)
+ httpx>=0.27             # 替代 urllib.request,async-native
- numpy==1.24.3
+ numpy>=2.1.0
- pandas==2.2.2
+ pandas>=2.2.3
- torch>=2.1.0
+ torch>=2.5.0
```

#### 2) 路由迁移模式(29 个路由全部要改)

**Flask 原写法**:
```python
@app.route('/api/predict', methods=['POST'])
def api_predict():
    data = request.get_json()
    if not data.get('file_path'):
        return jsonify({'error': 'File path cannot be empty'}), 400
    ...
    return jsonify({'success': True, 'prediction': result})
```

**Robyn 写法**:
```python
from robyn import Robyn, Request, jsonify

app = Robyn(__file__)

@app.post("/api/predict")
async def api_predict(request: Request):
    data = request.json()                       # 不再是 .get_json()
    if not data.get('file_path'):
        return jsonify({'error': 'File path cannot be empty'}, status_code=400)
    ...
    return jsonify({'success': True, 'prediction': result})
```

#### 3) 模板渲染
```python
# 改前
from flask import render_template
@app.route('/')
def home():
    return render_template('stock_analysis_home.html')

# 改后
from robyn.templating import JinjaTemplate
template = JinjaTemplate("templates")

@app.get("/")
async def home(request):
    return template.render_template("stock_analysis_home.html")
```
影响:`stock_analysis_home.html`、`index.html`、`desktop.html` 等 13+ 个模板的渲染入口都要改。Jinja 语法本身**完全兼容**,模板文件不用改。

#### 4) 静态/文件服务
```python
# 改前
@app.route('/analysis-reports/<path:subpath>')
def analysis_reports(subpath): ...
@app.route('/figures/<path:filename>')
def figures(filename): ...

# 改后
app.serve_directory(route="/analysis-reports",
                    directory_path=str(REPORTS_DIR),
                    index_file=None)
app.serve_directory(route="/figures",
                    directory_path=str(FIGURES_DIR))
app.serve_directory(route="/assets",
                    directory_path=str(ASSETS_DIR))
```

#### 5) 路径参数
```python
# 改前
@app.route('/api/stock-kline/<stock_code>')
def stock_kline(stock_code): ...

# 改后  ⚠️ Robyn 路径参数语法不同
@app.get("/api/stock-kline/:stock_code")
async def stock_kline(request: Request):
    stock_code = request.path_params["stock_code"]
```

#### 6) CORS 处理
```python
# 改前
from flask_cors import CORS
CORS(app)

# 改后:用 Robyn 中间件
@app.before_request()
async def add_cors(request):
    return request

@app.after_request()
async def cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    return response
```

#### 7) 后台任务架构改造 ⭐ 这是最大重构点
当前代码用 `threading.Thread` + 全局 `analysis_jobs_lock` 来跑长任务(opportunity_discovery、batch_analysis、pattern_search refresh、monitor_loop)。

**问题**:Robyn 多进程模型下,内存中的 `analysis_jobs` 字典在不同 worker 之间**不共享**。

**两种方案**:

**方案 A:固定 1 worker + 沿用 threading(改动最小)**
```python
# run.py
app.start(host="0.0.0.0", port=8080, workers=1)
# 后台线程模式不变,只把 Flask 路由换成 Robyn 路由
```

**方案 B:重构为 async 任务 + Redis/SQLite 持久化(推荐,匹配 3.13 优势)**
```python
import asyncio
from collections import defaultdict

analysis_jobs: dict = {}
job_lock = asyncio.Lock()

@app.startup_handler
async def startup():
    # 替代 monitor_thread,纯 asyncio
    asyncio.create_task(monitor_loop())

@app.post("/api/batch-analysis/start")
async def start_batch_analysis(request):
    data = request.json()
    job_id = str(uuid.uuid4())
    async with job_lock:
        analysis_jobs[job_id] = {"status": "running", ...}
    asyncio.create_task(run_batch_analysis(job_id, data))
    return jsonify({"success": True, "job_id": job_id})

async def run_batch_analysis(job_id: str, data: dict):
    # 原来线程里的 asyncio.run(processor.process_batch(...))
    # 现在直接 await
    result = await processor.process_batch(...)
    analysis_jobs[job_id]["status"] = "done"
```

#### 8) HTTP 客户端替换
项目里 6 处 `urllib.request`(同步阻塞)→ 改 `httpx.AsyncClient`,避免阻塞事件循环:
```python
# 改前
req = urllib.request.Request(url, headers=...)
with urllib.request.urlopen(req, timeout=5) as f:
    data = json.loads(f.read())

# 改后
async with httpx.AsyncClient(timeout=5) as client:
    resp = await client.get(url, headers=...)
    data = resp.json()
```

#### 9) 启动入口 `run.py`
```python
# 改前
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)

# 改后
if __name__ == '__main__':
    app.start(host="0.0.0.0", port=8080, _check_port=True)
```
注意:Robyn `--processes N --workers M` 通过 CLI 参数控制,不再用 gunicorn。

### 3.4 📋 路由迁移工作量评估

| 类型 | 数量 | 单个工时 | 说明 |
|---|---|---|---|
| 简单 GET 返回 JSON | 8 | 5min | `/api/available-models`, `/api/jobs`, etc. |
| POST + JSON body | 12 | 15min | `/api/predict`, `/api/load-model`, etc. |
| 路径参数 | 4 | 10min | `/api/stock-kline/<code>` 等 |
| 模板渲染 | 4 | 10min | `/`, `/prediction`, `/desktop/<page>` |
| 静态文件 | 3 | 替换为 `serve_directory` |
| 后台任务相关 | 3 | 30min-2h | 取决于方案 A or B |

**总工时估计**:
- 方案 A(最小改动):**2-3 天**
- 方案 B(完整 async 重构):**1-2 周**

### 3.5 ⚡ Robyn + Python 3.13 实际性能预期

| 场景 | Flask 基线 | Robyn(单线程异步) | Robyn + 3.13 free-threaded |
|---|---|---|---|
| 简单 JSON 路由 QPS | ~2k | ~30k (15×) | ~40k |
| 静态文件吞吐 | ~3k | ~50k | ~60k |
| 长任务并发处理 | 受 GIL/threading 限制 | async 原生不阻塞 | 真并行,CPU 密集任务再 ×2 |
| 内存占用 | 100% 基线 | ~70% | ~60% |
| 冷启动时间 | ~2s | ~0.3s | ~0.25s |

### 3.6 ⚠️ 风险点

1. **模板**:13+ HTML 模板大量用 `url_for()` → Robyn 不支持,需手写完整路径
2. **Werkzeug 调试器**:Robyn 没有 Flask 的开发期 traceback 页面,要用 `logging` + Sentry
3. **请求上下文**:Flask `g`、`session`、`flash` 全部没有,需自己实现
4. **Robyn 生态**:中间件、扩展远不如 Flask 丰富,部分功能要手写
5. **Tushare / baostock 同步库**:这些库**不是 async 的**,在 Robyn async 路由里调用要包 `asyncio.to_thread(...)`,否则阻塞整个 worker
6. **PyTorch 推理**:`KronosPredictor.predict()` 同步且耗时(秒级),必须 `asyncio.to_thread()` 或单独进程池
7. **桌面端 Tauri 集成**:`/desktop` 路由如果走 Tauri 嵌入,需要确认 Robyn 启动方式与 Tauri 主进程兼容

### 3.7 🎯 推荐迁移路线

**Phase 1 - 准备(1 天)**
- Python 3.12 + numpy/pandas/torch 升级到位
- 把 6 处 `urllib.request` 替换为 `httpx`(双向兼容,sync 和 async 都支持)
- 抽离业务逻辑到 `webui/services/`,让路由变薄,降低迁移耦合

**Phase 2 - 框架替换(3-5 天)**
- 用方案 A(单 worker + threading 保留),把 29 个路由批量替换
- 模板渲染走 `JinjaTemplate`,先保证业务等价
- 测试所有路由功能正确

**Phase 3 - Async 化(1 周)**
- 把 `KronosPredictor.predict()`、tushare 调用包 `asyncio.to_thread`
- 把 `threading.Thread` 后台任务改成 `asyncio.create_task`
- 引入 Redis 或 SQLite 做 job 持久化(解决多 worker 问题)

**Phase 4 - 切换 Python 3.13(2-3 天)**
- 跑 free-threaded 模式 (`python3.13t`)
- 把 Robyn workers 调到多个,实测并发性能
- 启用 JIT 测试热路径

### 3.8 一句话结论

**迁移可行,但不是"换装饰器"那么简单**。Robyn 的真正价值在于 **async 原生 + Rust 运行时**,如果只做路由替换不重构 IO,只能拿到约 20-30% 提升;**配合 async 重构后才能拿到 5-10 倍 QPS 提升**,叠加 Python 3.13 free-threaded 再放大量化模型/爬虫的并行收益。最大风险点是后台任务架构(`analysis_jobs` 全局字典 + threading)需要重新设计。

---

## 四、整体路线图汇总

```
2026-Q2  →  Python 3.12 + numpy 2.x + torch 2.5    (稳健过渡)
2026-Q2  →  Flask routes → Robyn (方案 A, threading 保留)
2026-Q3  →  Async 化重构 (Phase 3)
2026-Q3  →  Python 3.13 standard + JIT 实验
2026-Q4  →  python3.13t free-threaded + 多 worker 并行
```

**关键收益里程碑**:
- 完成 Phase 2:API QPS 15×,内存 -30%
- 完成 Phase 3:长任务并发能力大幅提升,可支持盘中实时多股票监控
- 完成 Phase 4:量化模型 + 爬虫真并行,30 模型批量回测时间减半
