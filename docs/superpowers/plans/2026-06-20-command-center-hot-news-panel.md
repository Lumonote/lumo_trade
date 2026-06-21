# 实现计划 — 风险·机遇大屏「东财热点新闻」面板(落 SQLite)

日期:2026-06-20
分支:V2.1.1
Spec:`docs/superpowers/specs/2026-06-20-command-center-hot-news-panel-design.md`

## 目标摘要

撮合矩阵面板拆两栏:左栏散点图(画全部机会池标的,不变);右栏展示机会挖掘的「前十条热点新闻 + 热度」。热点新闻每天随挖掘 run 落 SQLite,大屏按所选日期读取当天热点。

数据流(自底向上):
`run_opportunity_discovery.global_hot_news` → `opportunity_repo.save_run(..., hot_news=)` 落 `opportunity_hot_news`(schema v15)→ `opportunity_repo.latest_hot_news(date)` 读 → `webui/core` 注入 → `CommandCenterService.overview()` payload `hot_news` → 前端 `ccHeroRow` / `ccHotNewsList` 渲染。

每个阶段都遵循 TDD:先写失败测试 → 实现 → 跑测试通过。除特别说明外,测试命令在仓库根、`.venv` 下运行:`.venv/bin/python -m pytest <file> -q`。

---

## 阶段 1 — Schema v15:`opportunity_hot_news` 表

**依赖**:无(最底层)。

### 1.1 写测试 `tests/test_schema_migration_v15.py`(新建)

参照 `tests/test_schema_migration_v7.py` 的临时库 + `migrate()` 模式。断言:

- 全新内存/临时库 `migrate(conn)` 返回 15;`MAX(version) FROM schema_version == 15`。
- `opportunity_hot_news` 表存在(查 `sqlite_master`)。
- `PRAGMA foreign_key_list('opportunity_hot_news')` 含一条指向 `opportunity_run` 的外键、`on_delete == 'CASCADE'`。
- `PRAGMA index_list` 含 `idx_opp_hotnews_run`。

跑:`.venv/bin/python -m pytest tests/test_schema_migration_v15.py -q` → 应失败(表/版本不存在)。

### 1.2 实现 — `data_store/schema.py`

在 `_MIGRATIONS` 列表末尾(当前最后一项 `(14, ...)`,行 ~517-537)追加 `(15, sql)` 元组,沿用现有 `(version, # 注释, """SQL""")` 风格:

```sql
CREATE TABLE IF NOT EXISTS opportunity_hot_news (
  run_id       INTEGER NOT NULL REFERENCES opportunity_run(id) ON DELETE CASCADE,
  news_rank    INTEGER NOT NULL,
  title        TEXT NOT NULL,
  url          TEXT,
  source       TEXT,
  publish_time TEXT,
  heat         REAL,
  PRIMARY KEY (run_id, news_rank)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_opp_hotnews_run ON opportunity_hot_news(run_id);
```

`migrate()` 现有循环(行 589-602)对无特殊分支的版本直接 `executescript(sql.strip())` —— v15 无需在 `if version == ...` 链里加分支。

**验证**:`.venv/bin/python -m pytest tests/test_schema_migration_v15.py -q` → 通过。同时跑 `tests/test_schema_migration_v7.py` 确认未回归既有迁移。

---

## 阶段 2 — Repo:`save_run(..., hot_news=)` 写入 + `latest_hot_news()` 读取

**依赖**:阶段 1(表已存在)。

### 2.1 写测试 `tests/test_opportunity_hot_news_repo.py`(新建)

参照 `tests/test_opportunity_repo.py` 的临时库注入模式(monkeypatch `data_store.connection` 的库路径 / 用 `get_conn` + `migrate`)。覆盖 spec「测试」节四点:

- **降序 + 限 10**:`save_run(meta, items=[], hot_news=[乱序 heat 的 12 条])` → `latest_hot_news()` 返回 10 条,`heat` 严格降序,投影字段为 `{rank, title, url, source, publish_time, heat}`,`rank` 来自 `news_rank`。
- **按日期取当日最近 run**:同日两次 run(run_at 不同)各带不同热点 + 另一日一次 run → `latest_hot_news("2026-06-19")` 只返回该日**最近一次**有热点的 run 的热点;`latest_hot_news()`(无参)返回全局最近一次有热点的 run。
- **级联删除**:写一条 run + 热点后 `DELETE FROM opportunity_run WHERE id=?` → `opportunity_hot_news` 对应行清空(验证 `PRAGMA foreign_keys=ON` 已由 `get_conn()` 设好,`connection.py:50`)。
- **空/None 安全**:`hot_news=None` 与 `hot_news=[]` 都不写表、不报错,`latest_hot_news()` 返回 `[]`。
- **title 去重保留 heat 高者**:同 title 两条不同 heat → 落库后仅留 heat 高的一条。

跑 → 应失败(`save_run` 不接受 `hot_news`、无 `latest_hot_news`)。

### 2.2 实现 — `data_store/opportunity_repo.py`

**`save_run`**(行 23)签名改为 `save_run(meta, items, hot_news=None) -> int`。在返回 `run_id` 前(行 82 `return run_id` 之上)插入热点写入:

- `hot_news` 为空 → 跳过。
- 否则:按 `title`(`.get("title")`,去首尾空白)去重,保留 `heat` 高者;按 `heat` 降序(`heat` 缺失视作 -1 排末尾);截前 `limit=10`;`enumerate(start=1)` 重排 `news_rank`。
- `executemany` 写入 `opportunity_hot_news`,字段一律 `.get(...)` 取(缺失存 NULL),`heat` 走 `_num(...)`。
- 复用同一 `conn`(行 38 已取),与 items 写入同事务语义;best-effort:外层不因热点写入失败而破坏 run/items(可 try 包裹,失败仅记日志——遵循「逐源降级」风格,但不吞掉编程错误,先按直接写入实现,测试通过即可)。

**新增 `latest_hot_news(run_date=None, limit=10) -> List[Dict]`**(放在 `runs_by_day` 附近):

- 选目标 run id:
  - `run_date` 非空:`SELECT id FROM opportunity_run r WHERE r.run_date=? AND EXISTS(SELECT 1 FROM opportunity_hot_news h WHERE h.run_id=r.id) ORDER BY r.run_at DESC, r.id DESC LIMIT 1`。
  - 为空:去掉 `run_date` 过滤,全局取最近一条有热点的 run。
- 无目标 run → 返回 `[]`。
- 取热点行:`SELECT news_rank AS rank, title, url, source, publish_time, heat FROM opportunity_hot_news WHERE run_id=? ORDER BY heat DESC, news_rank ASC LIMIT ?`,`dict(row)` 投影。

**验证**:`.venv/bin/python -m pytest tests/test_opportunity_hot_news_repo.py tests/test_opportunity_repo.py -q` → 全绿(含既有 repo 测试不回归)。

---

## 阶段 3 — 挖掘 run 落库联动

**依赖**:阶段 2(`save_run` 接受 `hot_news`)。

### 3.1 实现 — `scripts/run_opportunity_discovery.py`

行 1992 调用处:

```python
run_id = opportunity_repo.save_run(
    run_meta, opportunity_repo.build_items(filter_results),
    hot_news=self.global_hot_news)
```

`self.global_hot_news` 结构已稳定为 `{title, url, source, publish_time, heat, rank}`(行 88 初始化为 `[]`,各路径回填,见 spec 数据现状)。

### 3.2 验证

无独立单测(该脚本是编排层,联网重)。验证方式:阶段 2 的 repo 测试已覆盖 `hot_news` 入参的全部行为;此处仅传参,靠**阶段 5 集成冒烟**(跑一次挖掘 → 大屏出现热点)兜底。改动后跑 `.venv/bin/python -c "import ast; ast.parse(open('scripts/run_opportunity_discovery.py').read())"` 确认语法,或 `python -m py_compile`。

---

## 阶段 4 — 大屏读取:Service + core 注入

**依赖**:阶段 2(`latest_hot_news` 存在)。

### 4.1 写测试 — 扩展 `tests/test_command_center_service.py`

新增三个用例(参照文件内 `_svc_with_positions` 注入风格):

- **正常注入**:`CommandCenterService(..., hot_news=lambda date=None: [{"rank":1,"title":"t","heat":80,...}, ...])` → `overview()` 的 payload `out["hot_news"]` 是该列表,字段/顺序原样,`out["degraded"]["hot_news"] is False`。
- **源抛异常**:`hot_news=boom` → `out["degraded"]["hot_news"] is True`,`out["hot_news"] == []`,且 `out["matrix"]` / `out["portfolio"]` 等其余面板照常返回(逐源降级)。
- **缺省不注入**:不传 `hot_news` → `out["hot_news"] == []`、不崩。

跑 → 应失败(payload 无 `hot_news` 键)。

### 4.2 实现 — `webui/services/command_center_service.py`

- `__init__`(行 14)新增关键字参数 `hot_news=None`;`self._hot_news = hot_news or (lambda *a, **k: [])`(与 `_hot_membership` / `_news_index` 同款纯注入降级,行 22-23)。
- `overview()` 中(在 holdings_relevance 之后、`indices` 之前合适位置)插入:
  ```python
  hot_news, dhn = self._safe(lambda: self._hot_news(report.get("date")), [])
  degraded["hot_news"] = dhn
  ```
  注意:`_safe` 的 default 应为 `[]`。在返回的 payload dict(行 110)加 `"hot_news": hot_news`。

### 4.3 实现 — `webui/core.py`:`COMMAND_CENTER_SERVICE` 构造

顶部按现有风格 `import`(若未导入)`from data_store import opportunity_repo`,在 `CommandCenterService(...)` 构造处增注入:

```python
hot_news=lambda date=None: opportunity_repo.latest_hot_news(date, limit=10),
```

确认 `quotes_only` 路径也经同一 `overview()` 返回 payload(spec 已说明 DB 读取廉价,无额外联网)。

**定位**:`grep -n "CommandCenterService(" webui/core.py` 找构造点;`grep -n "COMMAND_CENTER_SERVICE" webui/core.py` 确认全局单例。若 service 在请求时按日期重建,则把 `latest_hot_news(date,...)` 的 date 由 `overview(report=...)` 内部 `report.get("date")` 驱动(已在 4.2 实现),core 注入只需传 `latest_hot_news` 本身。

### 4.4 验证

`.venv/bin/python -m pytest tests/test_command_center_service.py -q` → 全绿(含既有 6 个用例不回归)。`python -m py_compile webui/core.py`。

---

## 阶段 5 — 前端渲染:两栏 + 热点列表

**依赖**:阶段 4(payload 带 `hot_news`)。无自动化测试(纯前端),靠人工/集成冒烟。

### 5.1 实现 — `webui/static/kronos_desktop_app.js`

- `ccHeroRow(d)`(行 10759):撮合矩阵 `panel` 内 `matrixInner` 改为两栏容器:
  ```
  <div class="cc-matrix-split">
    <div class="cc-matrix-chart"><div class="plotwrap"><div id="ccMatrix" style="width:100%;height:300px;"></div></div></div>
    <div class="cc-hotnews">${ccHotNewsList(d.hot_news)}</div>
  </div>
  ```
  无机会池数据时左栏仍显示原 `cc-empty` 占位(保留 `hasMatrix` 分支,仅把它套进 `.cc-matrix-chart`)。
- 标题栏 `<span class="tag">` 文案更新为体现两栏,如 `x=机会分 · y=风险(上低下高) · 右:东财热点按热度`。
- 新增 `ccHotNewsList(list)`:`list` 空 → `<div class="cc-empty">暂无热点(重新统筹后生成)</div>`;否则逐行渲染 rank、标题(有 `url` 用 `<a href target=_blank rel=noopener>`,否则纯文本)、`source · publish_time`、热度数值 + 细热度条(宽度 = `Math.max(0,Math.min(100,heat))%`)。全部用现有 `html()`(行 108)转义。
- `ccStartLiveRefresh`(行 11161)沿用现有 `ccDrawMatrix`/`ccDrawSectorHeat`;热点列表随整页 `renderCommandCenter`(行 11192)重建即可,首版不在实时分支单独刷右栏。
- 确认 `ccDrawMatrix`(行 11078)仍按 `#ccMatrix` 取节点 —— 两栏改造后 `#ccMatrix` 仍在 DOM 内,无需改散点逻辑。`Plotly.Plots.resize("ccMatrix")`(行 10917)同理不变。

### 5.2 实现 — `webui/static/kronos_desktop.css`

- `.cc-matrix-split`:flex 两栏,左 `flex:1`(或 `1fr`),右 `width:~280px; flex:0 0 280px`;容器高沿用面板 300px。
- `.cc-matrix-chart`:`flex:1; min-width:0`(防 flex 撑破)。
- `.cc-hotnews`:`overflow:auto; height:300px`;行样式含 rank 序号、标题(`text-overflow:ellipsis` 单行或限两行)、来源小字、热度条(复用大屏既有配色变量,如机会分色)。
- 媒体查询:窄屏(`cc-fullscreen` 小窗 / `max-width`)下 `.cc-matrix-split` 改 `flex-direction:column`,右栏放开高度(best-effort)。

### 5.3 验证

资源版本号 `?v=` 走 mtime 强缓存(改 JS/CSS 自动失效);HTML no-store。dev/命令行即时生效。打包 App 需重打包(见 [Desktop Packaging] 记忆)。人工:启动 webui → 打开「风险·机遇」大屏 → 确认右栏出现热点列表(或占位文案)、左栏散点正常、切日期右栏随之变化。

---

## 阶段 6 — 集成冒烟 + 收尾

**依赖**:全部阶段。

1. 跑一次机会挖掘(命令行 `.venv/bin/python scripts/run_opportunity_discovery.py ...` 或桌面「重新统筹」),确认 `opportunity_hot_news` 有当日数据:
   `.venv/bin/python -c "from data_store.connection import get_conn; print(get_conn().execute('SELECT run_id,news_rank,title,heat FROM opportunity_hot_news ORDER BY run_id DESC,heat DESC LIMIT 10').fetchall())"`
2. 大屏选当天 → 右栏显示前十热点 + 热度条;选无热点的历史日 → 占位文案。
3. 全量回归:`.venv/bin/python -m pytest tests/test_schema_migration_v15.py tests/test_opportunity_hot_news_repo.py tests/test_opportunity_repo.py tests/test_command_center_service.py -q` 全绿。
4. 不提交(用户已声明)。改动文件清单留待用户确认后再决定提交。

---

## 影响面 / 非目标(摘自 spec)

- **非目标**:不改热点采集逻辑、不引入新外部接口、不改散点图标的范围(仍画全部)。
- **历史数据**:迁移只建表不回填;新表自下次挖掘 run 起有数据。
- **打包 App**:前后端均改动,App 需重打包;命令行/dev 即时生效。
- **外键**:CASCADE 依赖 `get_conn()` 的 `PRAGMA foreign_keys=ON`(`connection.py:50`),已默认开启。

## 未决/需留意

- core 中 `CommandCenterService` 是全局单例还是请求级重建,决定 `hot_news` 注入是否需要把 date 闭包进去——已通过 `overview()` 内部 `report.get("date")` 驱动规避,core 只注入函数本身。实现阶段 4.3 时按实际代码确认。
- `save_run` 热点写入是否 try 包裹:首版直接写入(测试覆盖空/None);若担心脏数据破坏 run 落库,可加 try 仅记日志,但不吞编程错误。
