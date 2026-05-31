# Flask 完整移除（Flask Removal）设计文档

- **创建日期**：2026-05-23
- **作者**：OpenClawd
- **状态**：待用户复核
- **下一步**：通过后调用 `superpowers:writing-plans` 生成实施计划
- **关联 spec**（排队等待）：`2026-05-23-stock-analysis-suite-design.md`（Flask 移除完成后再做）

## 1. 背景

项目已完成 Python 3.13 + Robyn 迁移：30+ HTTP 路由已注册为原生 Robyn handler（`webui/robyn_app.py`）。但 Flask 仍以"兼容兜底"形式存在：
- `webui/app.py` 含 **33 条 Flask `@app.route`** + 94 个 helper 函数 + 7 个模块级 service 单例
- `webui/robyn_app.py` 含 **64 处 `flask_webui.*` 引用**，把 Flask 整个 app 对象作为依赖导入
- `KRONOS_WEB_SERVER` 默认值仍是 `"flask"`
- `requirements.txt` / `webui/requirements.txt` 仍声明 `flask>=3.0.0` 和 `flask-cors`
- 测试 `tests/test_robyn_app.py` 引用 `flask_webui`
- 文档（CLAUDE.md / PY313_ROBYN_PROGRESS / DEPENDENCIES）仍写 Flask 启动指令

本次目标：**彻底剥离 Flask 依赖**，Robyn 成为唯一 HTTP runtime。

## 2. 范围与边界

### 2.1 In Scope

- 把 `webui/app.py` 内所有非 Flask 业务逻辑（94 个 helper、7 个 service 单例、模块级常量）迁移到非 Flask 模块
- 删除 `webui/app.py` 内 Flask 特有代码：`Flask(__name__)`、`@app.route`、`CORS(app)`、`render_template` / `request` / `jsonify` / `send_from_directory` / `abort` 引用
- 删除 `webui/robyn_app.py` 内 Flask 兼容层：`_dispatch_to_flask`、`_register_flask_routes`、`_flask_rule_to_robyn`、`_to_robyn_response(FlaskResponse)`、`from flask import Response as FlaskResponse`、`from webui import app as flask_webui`
- 把 Robyn handler 内所有 `flask_webui.*` 引用切换到新模块路径
- `webui/run.py` 删除 `KRONOS_WEB_SERVER` 分支，固定走 Robyn
- `requirements.txt` / `webui/requirements.txt` 删除 `flask`、`flask-cors` 行
- `tests/test_robyn_app.py` 把 `robyn_module.flask_webui` 替换为新模块引用；其他依赖 Flask test client 的测试改写为 Robyn / httpx 调用
- `scripts/check_environment.py`、`scripts/check_runtime_upgrade.py` 删除 `flask` / `flask_cors` 检查
- 文档同步：`CLAUDE.md`、`docs/implementation/PY313_ROBYN_PROGRESS.md`、`docs/implementation/DEPENDENCIES.md`、`README` 类文档（如有）
- 桌面 backend：`packaging/scripts/build_backend.py`、`packaging/scripts/kronos_webui_backend.spec` 内任何 Flask 显式指引清理

### 2.2 Out of Scope

- 不修改任何路由的对外契约（URL、方法、请求体、响应结构、状态码完全保持一致）
- 不重新设计任何业务逻辑（包括缓存、模型加载、行情监控）
- 不变更 `analysis/*`、`scripts/run_opportunity_discovery.py`、批量分析等下游模块
- 不修改 Tauri 前端 / 桌面 shell 行为（用户感知零变化）
- `packaging/backend/kronos_webui_backend/_internal/...` 是构建产物，本次不修改，下次 `build_backend.py` 会自动重生成

## 3. 迁移策略

### 3.1 核心思路：**先抽离，再删除**

不一次性删 `webui/app.py`，而是分两阶段：

**阶段 A：抽离 helper 与 singleton 到 `webui/core.py`**
- 创建 `webui/core.py` 作为非 Flask 通用层
- 把 `webui/app.py` 内所有非 `@app.route` 的内容迁移过去：
  - 模块级常量（`PROJECT_ROOT`、`DESKTOP_PAGES`、`AVAILABLE_MODELS`、`MODEL_AVAILABLE` 等）
  - 模块级 service 单例（`PATTERN_SEARCH_SERVICE`、`JOB_SERVICE`、`CONFIGURATION_SERVICE`、`TRADING_CLIENT_SERVICE`、`ANALYSIS_JOB_PARSER`、`MARKET_INTELLIGENCE_SERVICE`、`STOCK_KLINE_SERVICE`）
  - 全部 94 个 helper 函数（`_json_safe`、`_load_*`、`_run_*_job`、`_stock_context_payload`、`_module_health`、`_get_job_snapshot`、`get_server_config`、`start_market_monitor` 等）
- `webui/app.py` 改为：`from webui.core import *` + 33 条 `@app.route` 装饰器（仍保留 Flask 路由层，但业务逻辑全部委托给 core）

**阶段 B：切换并删除 Flask**
- `webui/robyn_app.py` 把所有 `flask_webui.foo` 改为 `from webui.core import foo`（或在文件顶部统一 `from webui import core`）
- 删除 `webui/robyn_app.py` 内 Flask 兼容层（`_dispatch_to_flask`、`_register_flask_routes` 等约 5 个函数）
- 删除 `webui/app.py` 整个文件
- 清理 `webui/run.py` 中 Flask 分支
- 清理 `requirements.txt`、`webui/requirements.txt`、`scripts/check_*.py`、`tests/test_robyn_app.py`
- 更新文档

### 3.2 为什么分两阶段

- **阶段 A** 是 pure refactor，保留 Flask 与 Robyn 都能工作；可独立验证；如发现 helper 间隐式耦合（全局状态、闭包），可在不删 Flask 的前提下修复
- **阶段 B** 是删除性操作；前提是阶段 A 已通过完整回归测试

两个阶段在同一个分支但建议 **2 个独立 commit**，便于回滚。

### 3.3 helper 分布策略

抽到 `webui/core.py` 还是分散到 `webui/services/*`？

本次采用 **核心 + 现有 services 复用**：
- 与现有 services 主题强相关的 helper（如 `_run_pattern_refresh_job` → `services/pattern_search_service.py`、`_get_job_snapshot` → `services/background_jobs.py`）就近合并
- 与现有 services 都不强相关的散落 helper（`_json_safe`、`_load_report_history`、`_load_latest_opportunities`、`_stock_context_payload`、`_module_health`、`get_server_config`、`start_market_monitor` 等）放进 `webui/core.py`
- 模块级常量与单例统一放 `webui/core.py` 顶部
- 移动时 **保留函数签名和返回值结构不变**

## 4. 改动文件清单

### 4.1 新增
- `webui/core.py` — 非 Flask 通用层（helper、service 单例、常量）

### 4.2 修改
- `webui/robyn_app.py` — 改 import 路径，删除 5 个 Flask 兼容函数（`_dispatch_to_flask`、`_register_flask_routes`、`_flask_rule_to_robyn`、`_to_robyn_response`、`flask_webui` 模块引用）
- `webui/run.py` — 删除 `KRONOS_WEB_SERVER` 分支与所有 Flask 启动代码
- `requirements.txt` — 删除 `flask` 与 `flask-cors` 行
- `webui/requirements.txt` — 删除 `flask` 与 `flask-cors` 行
- `tests/test_robyn_app.py` — `flask_webui` 替换为 `core` 引用
- `scripts/check_environment.py` — 删除 `flask` / `flask_cors` 检查
- `scripts/check_runtime_upgrade.py` — 删除 PackageCheck("flask", ...) 与 PackageCheck("flask-cors", ...)
- `packaging/scripts/build_backend.py` — 若有显式 `flask` 包含，清理
- `packaging/scripts/kronos_webui_backend.spec` — 若有显式 `flask` 隐式导入声明，清理
- `CLAUDE.md` — 更新 web 启动章节（删除 `python app.py` 路径，只留 Robyn）
- `docs/implementation/PY313_ROBYN_PROGRESS.md` — 标记 Flask 已完全移除
- `docs/implementation/DEPENDENCIES.md` — 同步依赖清单

### 4.3 删除
- `webui/app.py` — 整个文件（在阶段 B 末尾）

### 4.4 不动
- `analysis/*`、`scripts/run_opportunity_discovery.py`、`scripts/opportunity_report_generator.py` 等
- 任何 `templates/*.html`、`static/*`（前端代码与 web 框架无关）
- `packaging/backend/kronos_webui_backend/_internal/*` 构建产物（下次 build 自动覆盖）

## 5. 验证与回归

### 5.1 强制通过的验证

1. **路由覆盖**：启动 Robyn 后，对照 `webui/robyn_app.py` 的 34 条路由清单逐一 `curl` 验证返回非 5xx
2. **现有测试**：`pytest tests/` 全部通过；特别 `test_robyn_app.py`、`test_analysis_jobs.py`、`test_robyn_endpoints.py`（如存在）
3. **机会挖掘流水线**：`python scripts/run_opportunity_discovery.py --limit 5` 跑通
4. **批量分析流水线**：通过 web UI 触发批量分析任务，确认完成
5. **桌面 backend**：`KRONOS_WEB_SERVER=robyn python webui/run.py` 启动成功，浏览器访问 `desktop`、`pattern_search`、`stock_analysis_home` 等核心页面
6. **依赖核验**：`pip install -r requirements.txt -r webui/requirements.txt` 不再安装 Flask；`python -c "import flask"` 失败（确认已无源码引用）

### 5.2 回滚策略

- 阶段 A、B 各一个 commit
- 如阶段 B 验证失败，`git revert <B>` 即可回到阶段 A 状态（Flask 与 Robyn 共存可用）
- 如阶段 A 验证失败，`git revert <A>` 回到迁移前

### 5.3 性能基线

- 阶段 B 完成后启动 Robyn，对比阶段 A（含 Flask 兼容层）的请求延迟。预期 P50 持平或下降（少一层 dispatch）。如 P50 上升 > 20%，回滚并排查。

## 6. 风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|------|------|------|
| helper 之间存在 Flask context 隐式依赖（如 `request` 全局对象） | 中 | 阻断阶段 A | 抽离前 grep `request\.`、`g\.`、`session\.`，标记需重构的 helper |
| 模块级单例的初始化顺序破坏（移到 `core.py` 后顺序变） | 低 | 启动错误 | 单例集中在 `core.py` 顶部，按依赖顺序排列；写一段 smoke import 测试 |
| 桌面 backend 打包产物仍含 Flask | 低 | 包体冗余 | `build_backend.py` 重新打包验证；`du -sh` 对比体积 |
| `tests/test_robyn_app.py` 重写后行为变化 | 中 | 测试通过但实际有 bug | 改写后跑 `pytest -v` 同时手动 curl 关键路由 |
| 文档与代码不同步 | 低 | 误导用户 | 阶段 B 同 commit 内一并更新所有文档 |

## 7. 验收清单

- [ ] `webui/app.py` 文件已删除
- [ ] `webui/robyn_app.py` 不再 `from flask import` 或引用 `flask_webui`
- [ ] `pip install` 不再安装 `flask` / `flask-cors`
- [ ] `python -c "import flask"` 失败 (`ModuleNotFoundError`)
- [ ] `KRONOS_WEB_SERVER` 环境变量从 `run.py` 中移除
- [ ] `pytest tests/` 全绿
- [ ] `python scripts/run_opportunity_discovery.py --limit 5` 跑通
- [ ] Web UI 桌面页可正常加载、操作（K 线、形态、机会挖掘、批量分析）
- [ ] `CLAUDE.md`、`PY313_ROBYN_PROGRESS.md`、`DEPENDENCIES.md` 已同步
- [ ] 阶段 A、阶段 B 两个独立 commit，可独立回滚

## 8. 完成后的后续工作

- 回到 `2026-05-23-stock-analysis-suite-design.md`，按 spec 实施个股深度分析弹窗
- 该 spec 第 2.3 节关于"新路由必须双框架注册"的描述应同步更新为"仅 Robyn 注册"（在 stock-analysis-suite 进入 writing-plans 前修订）
