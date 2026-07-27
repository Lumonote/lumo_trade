# 挖掘引擎直播页(discovery_live)设计 — 2026-07-24

投资机会挖掘的动态交互进度页:多智能体并行/串行执行的 AI 特效风格,实时展示挖掘进行到哪一步。用户需求原话:「投资机会挖掘给一个动态交互的页面进行动态展示其挖掘的进度,类似多智能体并行和串行执行那种AI特效的执行过程,可以看进度到哪。」

## 自主决策记录(用户离线,以下问答由代码证据+惯例自答,均可事后推翻)

**Q1 独立页面还是嵌入工作台?** → 独立桌面页 `discovery_live`(用户原话「给一个页面」);DESKTOP_PAGES 数据驱动自动出侧栏+路由。工作台原有挖掘表单不动,新页自带精简启动控件,启动后即在本页直播。

**Q2 进度数据怎么到前端?** 三案对比:
- A. 前端解析既有 job logs 文本——零后端改动,但脆弱(文案一改就崩)、拿不到并行 worker 现场;
- B. **结构化 progress:JobStore 加 `progress` 列 + 管线埋点回调 + 前端 1.5s 轮询(选定)**——真实事件驱动、可单测、向后兼容(旧 job 无 progress 走日志回退模式);轮询与现有任务面板同构;
- C. SSE/WebSocket 推送——实时性收益对 30s~10min 级任务无意义,引入 robyn 推送复杂度,过度工程。

**Q3 特效怎么做?** 纯 CSS/SVG 动画,零新依赖,匹配现有暗色桌面主题。所有动画状态由真实 progress 驱动,不做假进度。

**Q4 CLI 兼容?** `OpportunityDiscovery(progress_hook=None)` 默认不埋点,CLI/既有调用零行为变化;hook 异常一律吞掉不影响主流程。

## 真实管线阶段(来自 scripts/run_opportunity_discovery.py run())

| key | 名称 | 形态 | 埋点位置(行号基于当前文件) |
|---|---|---|---|
| regime | 大盘环境 | 串行 | ~1367 |
| candidates | 候选获取 | 串行(multi 含 5 个子源,逐个上报 source 计数) | 1376-1554 |
| preload | 全局预载 | 串行 | 1556-1559 |
| analyze | 并发打分 | **并行 max_workers 线程**(多智能体核心段) | 1561-1644;单股埋点在 `_analyze_single_stock_with_timeout`(2268,Rich/非Rich 两分支共用的 submit 目标) |
| funnel | 漏斗筛选 | 串行 | 1648-1659 |
| llm | LLM深度分析 | 并行 2-5(仅 B 级以上;KRONOS_SKIP_LLM=1 → skipped) | 1742-1816 |
| report | 报告生成 | 串行 | 1999 |
| persist | 结果入库 | 串行 best-effort | 2044 |
| backtest | 自动回测 | 串行 best-effort | 2060-2093 |

## 架构

```
OpportunityDiscovery(progress_hook)          # 埋点:stage_start/stage_done/stage_skip/
  └─ 事件 → DiscoveryProgressTracker         #        candidates_source/analyze_total/stock_start/stock_done
              (纯聚合器,可单测)              # 聚合成 progress 快照,节流(≥0.6s 或阶段切换)写出
       └─ writer → _update_job(progress=…)   # JobStore 新增 progress 列
GET /api/jobs/:id → job.progress             # _row_to_job 自动带出
前端 IIFE(kronos_desktop_app.js 尾部追加)  # 1.5s 轮询渲染
```

### 组件

1. **JobStore**(webui/services/job_store.py):建表语句加 `progress_json TEXT`;存量库 `ALTER TABLE ADD COLUMN` 迁移(捕获 duplicate column);`update` allowed_fields 加 `progress`;`_row_to_job` 带出 `progress`。
2. **DiscoveryProgressTracker**(新文件 webui/services/discovery_progress.py):纯类,`emit(event, **data)` → 内部聚合 → 满足节流条件时调 `writer(snapshot)`。快照 schema v1:
   ```json
   {"v":1, "current_stage":"analyze", "percent":42.5, "eta_seconds":180,
    "stages":[{"key","label","status:pending|running|done|skipped|failed","detail","done","total","elapsed"}],
    "workers":[{"code","name","since_ts"}], "max_workers":10,
    "counts":{"candidates":123,"analyzed":57,"failed":3,"sources":{"heat":100,"oversold":20}},
    "updated_at":"iso"}
   ```
   percent 权重:candidates 前段合计 15%,analyze 60%(按 done/total 线性),llm 10%,report+persist+backtest 15%;ETA 由 analyze 段速率外推,其它段不给 ETA。
3. **OpportunityDiscovery**:`__init__(max_workers=10, progress_hook=None)`;新增 `_emit(event,**data)` 安全封装(try/except);阶段边界处 ~12 个调用;`_analyze_single_stock_with_timeout` 进入时 emit stock_start、finally emit stock_done(带 ok 标志)——两个执行分支(Rich/非Rich)共用此函数,单点覆盖。in-flight 集合由 Tracker 维护(线程安全锁)。
4. **runner** `_run_opportunity_job`(webui/core.py):构造 tracker(writer=lambda p: _update_job(job_id, progress=p)),传入 discovery;任务结束时补一次终态快照。
5. **模板**(webui/templates/desktop.html):新增 `{% if active_page == 'discovery_live' %}` 块:块内 `<style>`(作用域前缀 .dlv-)+ 骨架容器(阶段轨道/智能体网格/漏斗与进度环/日志流/空态启动控件)。DESKTOP_PAGES 加条目:title 「挖掘引擎」,subtitle 「投资机会挖掘实时直播:多智能体并行流水线、阶段进度、现场日志与结果直达」。
6. **JS**(webui/static/kronos_desktop_app.js,压缩文件尾部以 `;(function(){...})();` 追加,自查 `document.body.dataset.page==="discovery_live"`):
   - 轮询:GET /api/jobs 找 running/queued 或最近的 `opportunity_discovery` job → GET /api/jobs/:id;
   - 渲染:阶段轨道(节点状态色+运行中呼吸光晕+连线流光 CSS 动画)、worker 卡片网格(占位 max_workers 张,活跃卡显示 code/name/耗时+扫描线,空闲卡暗态呼吸)、进度环(SVG stroke-dasharray)+百分比+ETA、候选来源计数芯片、日志流(job.logs 尾部 10 条,自动滚动);
   - 终态:finished → 撒花脉冲一次 + 「打开 Top 报告」(result.top_report_url)/「查看机会数据」按钮;failed → 红态+error;
   - 回退:job 无 progress(历史任务)→ 仅日志流+状态条;
   - 空态:精简启动表单(source/limit/workers/可选指定代码)→ POST /api/opportunity-discovery/start → 切入直播。
   - 轮询节流:页面不可见(document.hidden)时暂停;任务终态后停表。

### 错误处理
- hook/tracker 任何异常不得影响挖掘主流程(封装层 try/except + 单测覆盖);
- progress 写库失败静默(job logs 仍在);
- 前端 fetch 失败保持上一帧画面并降频重试。

### 测试
- test_discovery_progress.py:tracker 纯逻辑(阶段流转/并行 in-flight 增减/percent 单调不回退/节流/终态快照/异常安全);
- test_job_store.py 增补:progress 列迁移(旧库升级)+ update/get 往返;
- wiring 测试:伪造 discovery 只调 hook,断言 job 行的 progress 可经 JobStore 读回(不跑真管线)。

### 验证(实证)
pytest 全绿 + dev 服起 KRONOS_PORT=7071:页面 HTML 渲染断言;`KRONOS_SKIP_LLM=1` + 指定 2 只股票池小跑真任务,轮询 /api/jobs/:id 观测 progress 从 candidates→analyze(workers 现场出现)→report→finished 的演进。

### 边界与提醒
- 打包 App 需重打包才能看到此页(模板+JS+后端均入 bundle);
- 不动 git;SQLite-only 约定满足(progress 在 webui_jobs.sqlite);
- JS 是 esbuild 压缩产物,追加 IIFE 需前置分号(既有坑);不改既有字节。
