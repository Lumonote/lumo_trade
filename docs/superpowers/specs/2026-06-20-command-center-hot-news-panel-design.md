# 风险·机遇大屏 — 撮合矩阵旁「东财热点新闻」面板(落 SQLite)

日期:2026-06-20
分支:V2.1.1

## 背景与目标

「风险·机遇」统筹大屏(`command_center` 页)的核心组件「风险–机遇撮合矩阵」当前是一张
Plotly 散点图(x=机会分、y=风险、每点一只机会池标的),由
`webui/static/kronos_desktop_app.js` 的 `ccHeroRow` / `ccDrawMatrix` 渲染。

用户诉求:把撮合矩阵面板拆成两栏——

- **左栏**:散点图保持不变,仍画**全部**机会池标的(保留四象限全貌)。
- **右栏(原「分数低的一半」区域)**:展示「投资机会挖掘」里**前十条热点新闻**,并显示每条的
  **热度(heat)**。
- 这些热点新闻**每天落盘到 SQLite**,大屏按所选日期读取当天的热点。

## 数据现状

- 机会挖掘 `scripts/run_opportunity_discovery.py` 在 `self.global_hot_news` 上持有「前十条热点
  新闻」。其结构稳定为 `{title, url, source, publish_time, heat(0-100), rank}`(主路径
  `GlobalHotNewsCollector.get_top_news`,以及股吧话题/热榜话题/板块话题等所有回退路径都补齐 `heat`)。
- 挖掘 run 已按天落库:`opportunity_run`(主键 `id`,含 `run_date` YYYY-MM-DD)与
  `opportunity_item`(schema v9,migration 在 `data_store/schema.py`,当前最高版本 14)。
  落库入口 `opportunity_repo.save_run(meta, items)`,由
  `run_opportunity_discovery.py` 第 ~1992 行调用,桌面 job 与 CLI 共用。
- 大屏读取:`webui/core._command_center_report(date)` 聚合**当天全部 markdown 报告**;
  `CommandCenterService.overview(...)` 把各数据源(`load_report`/`hot_membership`/`news_index`
  等纯注入)组装成 payload。每个源独立降级:抛错只置 `degraded[...]` 标志,不崩。
- 大屏日期可切换:`available_dates` 来自报告日期;DB 的 `run_date` 与报告日期同为 YYYY-MM-DD,可对齐。

## 设计

### 1. SQLite 落盘

**Migration 15**(`data_store/schema.py` 的 `_MIGRATIONS` 追加 `(15, sql)`):

```sql
CREATE TABLE IF NOT EXISTS opportunity_hot_news (
  run_id       INTEGER NOT NULL REFERENCES opportunity_run(id) ON DELETE CASCADE,
  news_rank    INTEGER NOT NULL,          -- 落库时按 heat 降序的名次(1..N)
  title        TEXT NOT NULL,
  url          TEXT,
  source       TEXT,
  publish_time TEXT,
  heat         REAL,                       -- 0-100 热度
  PRIMARY KEY (run_id, news_rank)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_opp_hotnews_run ON opportunity_hot_news(run_id);
```

`migrate()` 现有循环对 `sql.strip()` 直接 `executescript` 即可,无需特殊分支。

**`data_store/opportunity_repo.py`**:

- `save_run(meta, items, hot_news=None) -> int`:新增第三个可选参数。写完 run + items 后,
  若 `hot_news` 非空:按 `title` 去重(保留 heat 高者)、按 `heat` 降序、截前 `limit`(默认 10)、
  重排 `news_rank`,`executemany` 写入 `opportunity_hot_news`。best-effort 与现有 items 写入同一
  `conn`(同一事务语义)。字段以 `.get` 取,缺失存 NULL。
- 新增 `latest_hot_news(run_date=None, limit=10) -> List[Dict]`:
  - 选定目标 run:`run_date` 非空 → 该日期 `run_at DESC` 最近一次有热点的 run;为空 → 全局
    `run_at DESC` 最近一次有热点的 run。
  - 返回该 run 的热点行,按 `heat DESC, news_rank ASC` 排序,取前 `limit`,
    投影为 `{rank, title, url, source, publish_time, heat}`(`rank` 用 `news_rank`)。
  - 无数据返回 `[]`。

**`scripts/run_opportunity_discovery.py`**:`opportunity_repo.save_run(run_meta, build_items(...))`
调用处改为 `save_run(run_meta, build_items(...), hot_news=self.global_hot_news)`。

### 2. 大屏读取

**`webui/services/command_center_service.py`**:

- `__init__` 增参数 `hot_news=None`,缺省为 `lambda *a, **k: []`(与 `hot_membership` /
  `news_index` 同样的纯注入降级风格)。
- `overview(...)` 中:`hot_news, dhn = self._safe(lambda: self._hot_news(report.get("date")), [])`,
  `degraded["hot_news"] = dhn`,payload 增 `"hot_news": hot_news`。

**`webui/core.py`**:`COMMAND_CENTER_SERVICE` 构造增注入:
`hot_news=lambda date=None: opportunity_repo.latest_hot_news(date, limit=10)`(顶部按现有风格 import
`opportunity_repo`)。`quotes_only` 路径也会带回 `hot_news`(无额外联网,DB 读取廉价)。

### 3. 前端渲染

**`webui/static/kronos_desktop_app.js`**:

- `ccHeroRow(d)`:撮合矩阵 `panel` 内部由单一 `#ccMatrix` 改为两栏容器(如
  `<div class="cc-matrix-split">`):
  - 左:`<div class="cc-matrix-chart"><div id="ccMatrix" ...></div></div>`(散点不变)。
  - 右:`<div class="cc-hotnews">` + 渲染 `ccHotNewsList(d.hot_news)`。
- 新增 `ccHotNewsList(list)`:无数据 → `<div class="cc-empty">暂无热点(重新统筹后生成)</div>`;
  否则逐行:
  - `rank`、标题(`<a href=url target="_blank" rel="noopener">`,无 url 则纯文本)、
    `source · publish_time`、**热度**(数值 + 细热度条,宽度 = `heat%`)。
  - 用现有 `html()` 转义。
- 标题栏 `<span class="tag">` 文案更新为体现两栏(如 `x=机会分 · y=风险 · 右:东财热点按热度`)。
- 实时刷新 `ccStartLiveRefresh` 走 `ccDrawMatrix`/`ccDrawSectorHeat`,热点列表随整页
  `renderCommandCenter` 重建即可;`quotes_only` 仍带回 `hot_news`,如需可在实时分支顺带刷新右栏
  (非必须,首版随整页刷新)。

**`webui/static/kronos_desktop.css`**:

- `.cc-matrix-split`:flex 两栏(左占主、右固定/弹性宽,如左 1fr、右 ~280px),沿用面板 300px 高。
- `.cc-hotnews`:`overflow:auto`,行内 rank/标题/来源/热度条样式;热度条复用大屏既有配色变量。
- 窄屏(全屏大屏 `cc-fullscreen` 或小窗)下两栏可降级为上下堆叠(媒体查询,best-effort)。

## 测试(TDD)

- **`tests/test_schema_migration_v15.py`**:全新库 `migrate()` 后 `opportunity_hot_news` 表存在、
  `schema_version` 最大值 = 15;`PRAGMA foreign_key_list` 含到 `opportunity_run` 的外键。
- **`tests/test_opportunity_hot_news_repo.py`**(或并入现有 repo 测试):
  - `save_run(meta, items, hot_news=[...乱序heat...])` 后 `latest_hot_news()` 按 heat 降序、限 10 条。
  - 多日多 run:`latest_hot_news("2026-06-19")` 只取该日最近一次 run 的热点。
  - 删除 `opportunity_run` 行后,`opportunity_hot_news` 级联清空(`ON DELETE CASCADE` 生效;
    `data_store/connection.py` 的 `get_conn()` 已设 `PRAGMA foreign_keys=ON`)。
  - `hot_news=None`/`[]` 时不写表、不报错。
- **`tests/test_command_center_service.py`**(扩展):
  - 注入 `hot_news` 源 → `overview()` 返回的 payload 含 `hot_news` 列表,顺序/字段正确。
  - `hot_news` 源抛异常 → `degraded["hot_news"] is True`,其余面板(matrix 等)照常返回。
  - 缺省(不注入)→ `hot_news == []`、不崩。

## 影响面与非目标

- **非目标**:不改机会挖掘的热点采集逻辑(沿用 `self.global_hot_news`);不引入新的外部接口;
  不改散点图本身的标的范围(仍画全部)。
- **打包 App**:前端改 `kronos_desktop_app.js` / CSS(`?v=` mtime 强缓存,HTML no-store);后端改
  Python。桌面 App 需重打包方能生效(参见 [Desktop Packaging] 记忆)。命令行/dev 即时生效。
- **历史数据**:迁移只建表,不回填历史 run 的热点(历史 run 当时未采集结构化热点入库);
  新表自下次挖掘 run 起有数据。大屏选到无热点的历史日 → 右栏显示占位文案。
- **外键开关**:CASCADE 依赖连接 `PRAGMA foreign_keys=ON`,`data_store/connection.py` 的
  `get_conn()` 已默认开启,无需额外改动;测试可显式验证级联删除。
