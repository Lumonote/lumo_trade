# 资金榜单「无量化」过滤 — 设计文档

日期: 2026-07-22
状态: 已确认(用户批准口径/覆盖/实现路径/整体设计)

## 目标

资金榜单页为以下 4 处列表增加「无量化」过滤勾选,勾选后从榜单中剔除被判定为
『量化资金参与』的股票,帮助用户聚焦非量化资金驱动的标的:

1. 主榜 · 主力净流入榜(`/api/capital-rankings/moneyflow`)
2. 主榜 · 龙虎榜(`/api/capital-rankings/dragon-tiger`)
3. 5日 / 30日窗口榜(同上两接口 envelope 内 `windows`)
4. 吸筹埋伏榜(`/api/quant-radar/accumulation`)

量化雷达 tab 自身的「量化活跃股 / 活跃板块 / 收割预警」不加此过滤
(它们本身就是量化榜,过滤即清空,无意义)。

实现路径: **后端各接口加 `no_quant=1` 参数,服务端过滤**(用户指定)。

## 『量化资金参与』判定口径(用户确认)

一只股票命中以下任一条件即被判定为量化参与,勾选「无量化」后被剔除:

- **量化雷达活跃度 ≥ 50**: `quant_radar_stock_daily` 最近有数据交易日该股
  `activity >= 50`(即预警等级 中/高,阈值体系 70/50/30);
- **龙虎榜量化席位**: 近 5 个自然日 `dragon_tiger_inst.is_quant=1`
  (席位名含 量化/DMA/程序化/算法,同步自 Tushare top_inst + 启发式兜底)。

两源并集。全部来自本地 SQLite,过滤路径**不发任何网络请求**。

## 组件设计

### 1. 量化代码集 resolver — `webui/services/quant_radar_service.py`

新增模块级函数:

```python
def quant_active_codes() -> dict
# 返回 {"codes": set[str6位代码], "as_of": "YYYY-MM-DD"|None, "available": bool}
```

- 活跃度源: `quant_radar_repo.list_dates(1)` 取最近有数据日 →
  复用既有 `get_day(trade_date, limit=0, min_activity=50)`(`limit<=0` 全量、
  `min_activity` 参数已内建,**无需新增 repo 函数**);
- 席位源: 复用既有 `_quant_seats_window(days=5)` 的 keys(6 位代码);
- `available`: 两源皆空(库无数据)时为 False,过滤退化为 no-op;
- 模块级 TTL 缓存 5 分钟(与文件内既有缓存同套路,threading.Lock 保护);
- 任何异常吞掉返回空集 + available=False,不阻断榜单。

### 2. repo 查询 — 无新增

复用既有 `data_store/quant_radar_repo.py::get_day`(已支持 `min_activity`
过滤与 `limit<=0` 全量),日期经既有 `_date_key` 归一(兼容
`YYYYMMDD` / ISO)。不新增任何 repo 函数。

### 3. 资金榜接口(主榜 + 窗口榜)

`webui/robyn_app.py::_capital_ranking_payload`:

- 读 `no_quant` query 参数(`"1"/"true"/"yes"` 为真,套用现有布尔解析口径),
  透传给 `moneyflow_ranking` / `dragon_tiger_ranking`。

`webui/services/capital_rankings_service.py`:

- `moneyflow_ranking` / `dragon_tiger_ranking` / `_envelope` / `_window_rankings`
  增加 `no_quant: bool = False` 形参;
- **top_n 语义**: no_quant 时取数阶段 over-fetch — repo limit 用
  `min(top_n * 3, 500)`,过滤后截回 top_n,避免榜单被剔后明显缩水;
  窗口榜同样处理;
- 过滤位置: `_normalize` 之后按行 code(6 位,`ts_code` 去后缀)对
  `quant_active_codes()["codes"]` 求差;`_attach_quotes` 在过滤+截断**之后**
  执行(少拉无用报价);
- envelope 新增字段:
  - `no_quant: bool`
  - `quant_filtered: int`(主榜被剔数量,截断前统计)
  - `windows.{5,30}.quant_filtered: int`
  - `quant_criteria_available: bool`
  - `quant_as_of: str|None`(活跃度口径数据日)
- resolver 每次请求内只调用一次(结果在 envelope 流程中复用)。

### 4. 吸筹榜接口

`webui/robyn_app.py::quant_radar_accumulation`:

- 读 `no_quant` 参数,透传 `accumulation_payload(..., no_quant=...)`。

`quant_radar_service.accumulation_payload`:

- **kv 快照存全量不变**,过滤在读取/返回前对 items 应用(实时与历史 as-of
  回看同样生效);
- payload 新增 `no_quant` / `quant_filtered` / `quant_criteria_available`;
- 吸筹榜本就全量返回、前端分页,无 over-fetch 需要。

### 5. 前端

`webui/templates/desktop.html`:

- 主榜查询控制区(`.capital-filter-grid`)加
  `<label><input type="checkbox" id="capitalNoQuant" /> 无量化</label>`
  —— 作用于主榜 + 5日 + 30日(同一次请求的 envelope);
- 吸筹埋伏榜头部加 `<input type="checkbox" id="quantAccumNoQuant" />` 同款。

`webui/static/kronos_desktop_app.js`(压缩文件,**尾部追加 IIFE** 模式):

- 勾选/取消 → 重新发起对应请求,URL 拼 `&no_quant=1`(通过重赋值/包装既有
  加载函数实现,锚点用实际字节);
- meta 行(`capitalRankingsMeta` / 吸筹榜 meta)显示
  「已过滤 N 只量化参与股」;`quant_criteria_available=false` 时显示
  「量化口径数据缺失,未过滤」;
- 默认不勾选,不持久化;
- ⚠️ 已知坑: 尾追加 IIFE 前补分号(避免与压缩尾表达式粘连 TypeError 静默);
  不用 `innerHTML +=` 追加已绑监听的容器。

## 错误处理

- 量化数据两源皆空: 过滤 no-op,`quant_criteria_available=false`,前端提示;
- resolver 异常: 吞掉返回空集,榜单照常返回;
- `no_quant` 参数缺省/非法: 视为 False,行为与现状完全一致(向后兼容)。

## 测试(TDD, 造数走 SQLite 临时库)

1. `quant_active_codes`: 两源并集、单源、两源皆空 available=False、TTL 缓存、
   源异常吞掉;
2. moneyflow/dragon_tiger envelope: `no_quant=1` 剔除命中股、`quant_filtered`
   计数、窗口榜各自过滤计数、over-fetch 后截回 top_n、默认参数行为不变;
3. accumulation: 过滤生效、kv 快照仍存全量、历史 as-of 过滤生效;
4. 路由: `no_quant` 参数解析(⚠️ robyn TestClient 查询串必须走
   `query_params`,不能拼 `?a=b`)。

## 约束

- 不执行任何 git 写操作(用户工作约定),文件写完停在文件系统层;
- 所有数据读本地 SQLite,不新增网络抓取,不新增表(仅新增一条 repo 查询);
- 打包 App 需重打包才生效(涉及 .py 与压缩 JS 双端改动)。
