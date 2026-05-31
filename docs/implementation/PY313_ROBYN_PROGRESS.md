# Python 3.13 与 Robyn 迁移实施进度

更新时间：2026-05-23

## 已完成

- Python 3.13 依赖预备：根依赖与 WebUI 依赖已升级到支持 Python 3.13 的版本区间。
- 新增 `scripts/check_runtime_upgrade.py`，用于检查 Python 版本和核心运行时包。
- Python 检测链路已优先识别 3.13/3.12/3.11，并修复 `.venv` 下 `scripts/check_environment.py` 误选系统 Python 的问题。
- WebUI 路由瘦身：
  - `JobStore`：SQLite 持久化后台任务状态。
  - `BackgroundJobService`：封装后台 job 创建、日志和线程启动。
  - `http_client`：集中同步 HTTP 请求边界。
  - `TradingClientService`：交易客户端发现和跳转。
  - `PatternSearchService`：形态搜索状态、匹配、股票查询、刷新参数。
  - `MarketIntelligenceService`：首页宏观/东方财富情报聚合。
  - `StockKlineService`：本地/Sina K 线数据获取。
  - `AnalysisJobRequestParser`：后台分析任务请求参数解析。
- WebUI 启动副作用收口：导入 `webui.app` 不再自动启动行情监控线程，改为 `start_market_monitor()`。
- WebUI 可写目录收口：数据、结果、报告、模型、job SQLite 默认写入 `KRONOS_USER_DIR`，打包资源目录只读。
- 情绪缓存等运行期缓存已优先写入 `KRONOS_USER_DIR/cache`，避免发布包写入只读资源目录。
- Robyn 迁移入口：
  - 新增 `webui/robyn_app.py`，由 Robyn 接管 HTTP runtime。
  - WebUI 现有 30 条 HTTP 路由已全部注册为原生 Robyn handler；Flask 自动映射兼容层保留在代码中作为迁移兜底，但当前 manifest 中已无 Flask fallback 路由。（已于 2026-05-23 完整移除，见下方"Flask 完整移除"条目）
  - 模板渲染、静态资源、报告文件、桌面页、K 线、任务、交易客户端、形态搜索、模型状态、模型加载和预测接口已走原生 Robyn handler。
  - 新增 `webui/run_robyn.py`，`KRONOS_WEB_SERVER=robyn python webui/run.py` 可走 Robyn 启动。
  - `webui.services.http_client` 已切到 `httpx`，并提供同步与 async 两套请求 helper。
- 模型加载/预测业务逻辑已抽到 `webui.services.model_runtime`，Flask 与 Robyn 路由共用同一份实现，避免双框架逻辑分叉。（已于 2026-05-23 完整移除，见下方"Flask 完整移除"条目）
- `KRONOS_DISABLE_TORCH=1` 已下沉到 WebUI 导入层，lite 桌面包会直接禁用 Kronos 模型库导入，避免触发 torch/modelscope 依赖和模型下载。
- 桌面端自包含后端：
  - 新增 `packaging/scripts/kronos_webui_backend.py`。
  - 新增 `packaging/scripts/kronos_webui_backend.spec`。
  - 新增 `packaging/scripts/build_backend.py`。
  - Tauri 发布模式优先启动内置 `kronos_webui_backend`，找不到时回退系统 Python。
  - `build_universal.sh` 已在 Tauri build 前构建内置 backend。
  - 默认构建 `lite` backend：包含 Python、Flask/WebUI、numpy/pandas/plotly、爬虫/分析所需基础依赖；不依赖用户机器 Python 环境。（已于 2026-05-23 完整移除，见下方"Flask 完整移除"条目）
  - 默认桌面 backend 入口切到 `KRONOS_WEB_SERVER=robyn`，仍可通过环境变量回退 Flask。（已于 2026-05-23 完整移除，见下方"Flask 完整移除"条目）
  - `full` backend 模式保留 torch/modelscope/Kronos 模型推理依赖入口，并加入 macOS torch rpath 后处理；2026-05-20 已复测构建可完成，但运行 `--import-check` 时在 native 层异常终止，仍不可作为默认发布链路。
- 桌面端 Tauri 打包链路：
  - 已安装并验证 Rust/Cargo：`cargo 1.93.1` / `rustc 1.93.1`。
  - `src-tauri/Cargo.lock` 已生成，用于固定 Tauri/Rust 依赖解析结果。
  - `cargo check` 与 `cargo build --release` 已通过。
  - `packaging/scripts/build_universal.sh` 已优先使用项目 `.venv` Python，避免 Homebrew/System Python 的 PEP 668 限制导致 PyInstaller 安装失败。
  - macOS `lite + robyn` 完整打包已生成 `.app` 与 `.dmg`。
- **2026-05-23 — Flask 完整移除**：
  - `webui/app.py` 已删除；所有 helper / service singleton 落地 `webui/core.py`
  - `webui/robyn_app.py` 不再 import Flask；5 个兼容函数（`_dispatch_to_flask`、`_register_flask_routes`、`_flask_rule_to_robyn`、`_to_robyn_response`、`flask_webui` 引用）已清除
  - `requirements.txt` / `webui/requirements.txt` 不再声明 flask / flask-cors
  - `webui/run.py` 移除 `KRONOS_WEB_SERVER` 分支，固定走 Robyn
  - 测试 `tests/test_robyn_app.py` 与依赖检查脚本同步更新
  - 桌面 backend 下次 build 自动使用新源码

## 当前验证

在 `.venv` / Python 3.13.12 下：

```bash
.venv/bin/python -m pytest tests
.venv/bin/python scripts/check_runtime_upgrade.py
.venv/bin/python scripts/check_environment.py
.venv/bin/python packaging/scripts/build_backend.py --clean --mode lite
KRONOS_USER_DIR=/private/tmp/kronos_packaged_lite_user packaging/backend/kronos_webui_backend/kronos_webui_backend --import-check
```

已通过。

当前测试结果：

- `pytest tests`：58 passed
- `scripts/check_runtime_upgrade.py`：通过
- `scripts/check_environment.py`：通过；仅保留 CUDA 不可用、LLM 未配置、用户配置 JSON 解析这类非阻塞提示
- `bash -n packaging/scripts/build_universal.sh quick_start.sh webui/start.sh`：通过
- `python -m json.tool src-tauri/tauri.conf.json`：通过
- `cargo check`：通过
- `cargo build --release`：通过
- `KRONOS_SKIP_BACKEND_BUNDLE=1 KRONOS_BACKEND_BUNDLE_MODE=lite KRONOS_WEB_SERVER=robyn packaging/scripts/build_universal.sh macos`：通过，生成：
  - `src-tauri/target/release/bundle/macos/Kronos Ultra.app`
  - `src-tauri/target/release/bundle/dmg/Kronos Ultra_1.1.6_aarch64.dmg`

注意：在默认文件沙箱内执行完整 `build_universal.sh macos` 时，Tauri release 二进制和 `.app` 能生成，但 DMG 阶段的 `hdiutil` 挂载/创建镜像会失败；在沙箱外执行同一 Tauri 打包流程已通过。这是构建环境权限问题，不是 Tauri 配置或代码编译问题。

打包后端烟测：

```bash
KRONOS_PORT=7071 KRONOS_USER_DIR=/private/tmp/kronos_backend_lite_user packaging/backend/kronos_webui_backend/kronos_webui_backend
curl http://127.0.0.1:7071/
curl http://127.0.0.1:7071/api/jobs
curl http://127.0.0.1:7071/api/model-status
```

已验证 Robyn lite backend 首页和 `/desktop` 返回 `200`，`/api/jobs` 返回空任务列表，`lite` 模式下 `/api/model-status` 正确返回模型库不可用。

`full` backend 复测结果：

```bash
KRONOS_BACKEND_BUNDLE_MODE=full KRONOS_WEB_SERVER=robyn .venv/bin/python packaging/scripts/build_backend.py --clean --mode full
PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1 KRONOS_BACKEND_BUNDLE_MODE=full KRONOS_DISABLE_TORCH=0 KRONOS_USER_DIR=/private/tmp/kronos_packaged_full_user packaging/backend/kronos_webui_backend/kronos_webui_backend --import-check
```

构建成功，产物约 647M；运行导入自检时进程在 native 层异常退出，没有 Python traceback。当前仍保持 `lite` 为默认桌面发布包。

## 仍未完成

- 后台任务执行器仍使用线程，状态已通过 SQLite `JobStore` 持久化，后续可替换为 Robyn startup handler + async task。
- `full` PyInstaller backend 尚未作为默认发布链路启用。原因是 macOS + PyInstaller + PyTorch 2.12 仍会在打包后导入阶段 native 崩溃；当前 rpath 后处理已确保 torch dylib 只保留在 `_internal/torch/lib`，但仍需继续定位 PyTorch/PyInstaller 兼容问题。
- macOS bundle identifier 当前为 `com.kronos.app`，Tauri 会提示以 `.app` 结尾不推荐；该提示不阻断构建，后续发布前建议改成不以 `.app` 结尾的唯一标识。

## 桌面打包策略

发布版不再要求用户机器安装 Python 或 pip 依赖：

1. 使用当前平台的 `.venv` 安装依赖。
2. `packaging/scripts/build_backend.py --mode lite` 构建自包含 WebUI backend。
3. Tauri 将 `packaging/backend/kronos_webui_backend` 作为 resource 打进桌面包。
4. Tauri 启动时优先执行内置 backend，并设置：
   - `KRONOS_USER_DIR`
   - `KRONOS_HOST`
   - `KRONOS_PORT`
   - `KRONOS_DESKTOP=tauri`
   - `KRONOS_WEB_SERVER=robyn`
   - `KRONOS_BACKEND_BUNDLE_MODE=lite`
   - `KRONOS_DISABLE_TORCH=1`（lite 包禁用模型推理依赖，避免用户端依赖检测和模型下载）

开发版仍可使用系统 Python 直接运行源码，便于调试。

如需在桌面包内启用 Kronos 模型推理，需要构建：

```bash
KRONOS_BACKEND_BUNDLE_MODE=full .venv/bin/python packaging/scripts/build_backend.py --clean --mode full
```

该模式会显著增大体积，并需要重点验证 PyTorch/macOS 动态库加载。
