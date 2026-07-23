# 量化交易分析 Tab（Quant Radar）设计

日期：2026-07-13 ｜ 页面：资金榜单（capital_rankings）新增第三个 tab ｜ 分支：V2.1.2 工作区

## 1. 背景与目标

用户提供《量化如何收割散户：五大机制深度拆解》一文作为需求规格，要求在资金榜单页新增「量化交易分析」tab，提供：

1. **量化活跃股票 / 板块识别** —— 哪些票、哪些行业正处在量化算法高强度博弈中；
2. **量化收割预警** —— 按文章五大机制逐股给出预警等级与触发原因；
3. **量化行为预测** —— 基于当日盘口行为的规则化次日行为展望（透明规则，非黑盒）；
4. **个股量化行为分析** —— 输入任意代码，输出五机制评分明细 + 龙虎榜量化席位 + 防御建议；
5. **量化知识卡** —— 五机制说明、监管时间线（2024-10 → 2026-04 高频认定 300→15笔/秒）、散户防御指南。

定位是**散户防御型分析工具**：用公开数据的代理指标提示「疑似量化行为特征」，不是监管认定，页面需带免责说明（全局页脚已有，tab 内再加一行方法论说明）。

## 2. 五机制 → 可用数据源映射（核心设计）

本机没有 L2 逐笔/委托队列数据，全部用公开数据构造**代理指标**：

| 机制 | 代理指标 | 数据源 |
|---|---|---|
| ① 虚假申报/幌骗 | 大笔买入·有大买盘异动密集 **但** 收盘涨幅平庸/长上影（买单多价不涨=疑似托单诱多）；镜像：大笔卖出密集但跌不动=疑似压单吸筹 | 东财盘口异动 push2ex getAllStockChanges + 当日日K |
| ② 高频速度博弈 | 单股单日异动总次数、火箭发射与高台跳水同日并存（秒级拉砸）、量比异常 | 盘口异动 + 东财全市场快照 clist(f10 量比) |
| ③ 订单簿诱导 | 近10日影线率（(上影+下影)/振幅）、高振幅低净涨的「缠斗指数」、炸板（打开涨停板）次数 | 日K（Sina，STOCK_KLINE_SERVICE 注入）+ 盘口异动 |
| ④ 情绪算法狙击 | 当日急涨急跌反转对（8201+8203 / 8202+8204）、炸板、近5日大阳→大阴翻转、振幅放大趋势 | 盘口异动 + 日K |
| ⑤ 行为偏差套利 | 小单净流入>0 且主力净流出<0（散户接盘背离）、连涨≥3日+高位放量（追高盘拥挤）、龙虎榜量化席位站卖方 | moneyflow_dc bucket0 全市场快照 + dragon_tiger(top_inst is_quant) + 日K |

加分项：**龙虎榜量化席位**（`dragon_tiger` 表 `is_quant=1`，同步自 Tushare top_inst，名称含 量化/DMA/程序化/算法 时启发式兜底）出现 → 直接确认量化参与。

市场级温度计复用 `futures_service` 已入库的期指前20多空数据（kv `futures_rank`）作为「量化资金市场立场」参考。

### 盘口异动类型码

生产已验证的看涨码沿用 `market_intelligence._BULLISH_CHANGE_TYPES`：8201 火箭发射、8202 快速反弹、8193 大笔买入、8207 有大买盘、4 封涨停板。空头按东财位码规则镜像：8203 高台跳水、8204 加速下跌、8194 大笔卖出、8208 有大卖盘、8 封跌停板；情绪类：16 打开涨停板（炸板）、32 打开跌停板。

> ⚠️ 存疑项：8207/8208 在 akshare 旧版映射中是「竞价上涨/竞价下跌」。本仓库生产面板一直按「有大买盘/有大卖盘」展示未见异常，沿用仓库口径；两种含义同向（多/空），不影响方向统计。待交易日冒烟时人工比对一次。

## 3. 服务层 `webui/services/quant_radar_service.py`

对齐 `futures_service` 范式：模块级函数、不 import `webui.core`、外部抓取全包 `_with_deadline`、httpx `trust_env False→True` 交替、历史快照永久落 `kv_repo`（namespace `quant_radar`）、Tushare/本地库兜底、降级不抛异常只标 `degraded/note`。

### 数据获取

- `_fetch_stock_changes()`：push2ex getAllStockChanges，全类型码一次拉（pagesize 1000×翻页≤3），返回原始行。仅交易时段有数据。
- `_fetch_market_snapshot()`：push2 clist 全A按量比降序前 N=400，fields 含 f7振幅/f8换手/f10量比/f22涨速/f62主力净流入/f100行业。
- `_aggregate_changes(rows)`：按股聚合 → `{code: {name, counts:{类型:次数}, bull, bear, first_time, last_time}}`（纯函数）。
- 快照落库：盘中每次刷新把 `{date: {changes_agg, snapshot}}` 覆盖写 kv `quant_radar:day:{yyyymmdd}`；休市/盘后读取时回退最近 ≤7 天快照并标 `fallback_date`。

### 评分纯函数（全部可离线单测）

- `_spoof_score(agg, day_bar) -> (0-100, reasons[])`
- `_hft_score(agg, quote) -> (score, reasons)`
- `_orderbook_score(bars, agg) -> (score, reasons)`
- `_sentiment_score(agg, bars) -> (score, reasons)`
- `_bias_score(flow_row, bars, quant_seats) -> (score, reasons)`
- `_composite(five) -> {activity: 0-100, level: 高危|中度|轻度|常态}`，权重 ②30/①20/③20/④15/⑤15，龙虎榜量化席位 +10（封顶100）。等级阈值 ≥70/50/30。
- `_predict_stock(five, agg, bars) -> [预测文案]`：规则化次日行为展望（每条规则 tag+text，透明可解释）。
- `_predict_market(gauge, futures_signal) -> text`
- `knowledge_payload()`：五机制卡（手法/识别特征/防御）、监管时间线、防御五条 —— 静态结构化内容，前端渲染。

### 对外入口

- `overview(force=False, kline_fetcher=None)` → 市场温度计（异动类型统计/活跃股数/期指立场/市场预测）+ 活跃股票榜(TOP30，含五机制分与徽章) + 板块聚合榜(按 f100 行业) + 高危预警列表 + 知识卡 + `updated_at/live/fallback_date`。内存 TTL 60s。
- `stock_analysis(code, kline_fetcher=None)` → 单股五机制明细（分数+触发原因）+ 近10日异动统计 + 龙虎榜量化席位记录（近30日）+ moneyflow 资金结构 + 行为预测 + 防御建议。`kline_fetcher(code, limit) -> records` 由路由注入 `STOCK_KLINE_SERVICE`（复用其 60s TTL 与实时叠加），测试注入假数据。

### repo 增量

`data_store/dragon_tiger_repo.py` 新增 `get_quant_by_date(trade_date, days=30)`：按日期窗口查 `is_quant=1` 席位行（活跃榜/预警需要日期维度，现仅有 get_by_code）。

## 4. API（robyn_app）

- `GET /api/quant-radar/overview?force=0|1`
- `GET /api/quant-radar/stock/:stock_code`

均 `_json_response`；handler 内注入 `kline_fetcher=lambda code, limit: (webui_core.STOCK_KLINE_SERVICE.get_payload(code,'daily',limit)[0] or {}).get('records') or []`（键名以实现时核实为准）。

## 5. 前端（desktop.html + kronos_desktop_app.js + kronos_desktop.css）

- `#capitalTabs` 增加 `<button data-cap-tab="quant">量化交易分析</button>`；既有 4 个资金面板加 `capital-classic` class。
- 新增 `<div id="quantRadarSection" hidden>` 六区块：市场温度计（含市场预测语）、量化活跃股票榜（表格，行点击展开个股分析）、活跃板块榜、收割预警卡、个股分析面板（含代码搜索框）、知识卡（可折叠）。
- JS（压缩单行文件，函数声明提升，安全做法=文件尾追加 + 两处微创 Edit）：
  1. `setCapitalTab` 替换为带 quant 分支版本：切换 `capital-classic` 面板与 `#quantRadarSection` 显隐，quant 时调 `loadQuantRadar()`。
  2. `loadCapitalRankings` 头部加 `if(state.capital.tab==="quant")return loadQuantRadar()`（兼容顶部全局刷新入口）。
  3. 文件尾追加 `loadQuantRadar / renderQuantRadar / renderQuantStock / quantLevelBadge` 等函数。
- CSS 追加 `.quant-radar-*` 样式（等级徽章红/橙/黄/灰、机制条形分、卡片网格）。

## 6. 测试计划（tests/test_quant_radar_service.py，离线）

- 异动聚合：合成 allstock 行 → 计数/方向正确；
- 各机制评分：构造触发/不触发用例断言分数区间与 reasons 文案；
- composite：权重求和、量化席位加成封顶、等级单调；
- 预测：给定分数组合输出确定性文案；
- 快照回退：monkeypatch `KRONOS_SQLITE_PATH`，写 kv 快照 → 休市读取回退并标 `fallback_date`；
- knowledge_payload：五机制齐全、含监管时间线关键节点（15笔/秒）；
- `get_quant_by_date`：tmp 库插入 is_quant 行断言过滤；
- 模板渲染冒烟：desktop.html capital_rankings 页含 `data-cap-tab="quant"`。

## 7. 已知限制（in scope 注明，不阻塞）

- 无 L2 委托/撤单数据，幌骗与订单簿诱导为**代理指标**，命名统一带「疑似」；
- 8207/8208 标签存疑（见上）；
- 周末/盘后异动为空 → 回退最近快照，首次部署无快照时预警区显示「待交易时段积累数据」；
- 股吧情绪 NLP（机制④的完整体）v1 不接，留扩展点。

## 8. 实现勘误（2026-07-13 冒烟实测）

- **push2ex 多类型参数不生效**：`type=A,B,C` 只返回第一个类型（akshare 正统用法即每类型单独请求）。实现改为 12 类型码并行逐个抓取（每类型 pagesize=800，6 线程），方向统计恢复真实（实测周日重放 2844 条：多 1031/空 1432/炸板 81）。注意：`market_intelligence.fetch_eastmoney_changes`（实时异动面板/托盘）存在同一问题，5 类型逗号请求实际只拿到火箭发射——既存问题，本次未动，另行修复。
- **push2 clist 本机不可达**（直连/代理均 Server disconnected，与板块池代理问题记忆一致）→ 新增本地兜底 `_snapshot_from_flows()`：moneyflow_dc 哨兵 top_n=0 最近一日全市场快照（主力净额万元→元归一），量比/振幅/换手/行业缺失置 None 由规则自动跳过；板块聚合因无行业字段暂空并在 payload note 说明。clist 恢复可达时自动回到完整快照。
- 周末 push2ex 会返回上一交易日重放数据（live:true），快照回退主要覆盖「首个交易日前」与接口整体不可达两种情况。
- 既存失败（非本次引入）：`test_robyn_app.py` 两例——`template_static_and_path_params` 断言 `b"Kronos"` 但 HEAD 品牌已改名 Lumo Trade；`settings_routes` 依赖本机 tushare 配置。

## 9. 增量（2026-07-13 同日追加，用户新需求）

### 9.1 个股分析套件「量化行为」tab
- desktop.html 个股分析套件(stockSuiteTabs)新增 `data-suite-tab="quant_behavior"` + `#suitePaneQuantBehavior`；JS 三处分发链(pane 映射/tab 点击链/payload 到达链)接 `renderSuiteQuantBehavior`。
- 渲染器懒取既有 `/api/quant-radar/stock/:code`(按码缓存于 state.quantRadar.suiteCache,带「重新分析」按钮)；明细 HTML 抽公共 `quantStockDetailHtml(p)`,与资金榜单页深评面板共用。

### 9.2 市场环境维度（期指对冲 + 大盘量能）
- `_futures_context_from_series`(纯)：四品种前20席位净持仓序列(futures_rank kv,只读不发网) → 各品种 net/3日净变动/signal + 合计3日净变动,阈值 ±8000 张(与 v25 fut_bear 同口径)→ 空压/回补/中性,标注大盘(IF/IH)vs中小盘(IC/IM)分化。
- `_volume_energy`(纯)：沪指+深成指日K量能合计,今日 vs 前5日均 → 放量≥1.2x/缩量≤0.8x/平量 + 连降天数。**实测新浪指数日K无 amount 字段只有 volume**,故 metric 标 `volume`(成交量,股),比值口径与单位无关;前端按 metric 区分「成交量/成交额」文案。
- `_env_predictions`(纯)：环境×个股机制分的追加预测(对冲压制/对冲回暖/缩量拥挤/放量博弈,机制分≥50 才触发)。
- 注入语义：`stock_analysis(futures_ctx_fn, volume_fn)` 可注入;注入 `fetch_changes` 视为离线模式,未显式注入的量能源不发网。payload 新增 `market_context:{futures, volume}`;overview 新增 `volume_energy` + 温度计「大盘量能」chip + 市场预测语追加量能子句。
- e2e 实测：期指空压(3日净减12473张,IM 独减10707张)、两市量能 1.15x 平量、个股预测含「对冲压制」。

### 9.3 按天保存与搜索
- **schema v18** 新表 `quant_radar_stock_daily`(PK trade_date+code,badges/reasons 存 JSON,双索引 code+date / date+activity)+ `data_store/quant_radar_repo.py`(upsert_day/get_day 关键字搜索/get_stock_history/list_dates)。
- **按交易日双写**：overview live 路径把前200活跃股写按日表 + kv 完整快照;日期锚定 `_current_trade_date_key()`(本地 trade_calendar 优先,工作日近似兜底)——修复周末重放数据被存成幻影日期的问题。kv 历史快照被读取时懒回填按日表。
- **历史回看**：`overview(date=...)` 非当前交易日 → 纯本地(kv 快照 → 按日表重建 → 空态提示),不发网络。
- **收盘自动落库**：`start_autosave()` 守护线程(robyn startup 挂载),交易日 15:05 后若当日按日表为空自动补跑一次 overview;env 开关 KRONOS_DISABLE_QUANT_RADAR_AUTOSAVE / _SAVE_AFTER / _SAVE_INTERVAL。
- **API**：overview 加 `?date=`;新增 `GET /api/quant-radar/day?date=&q=&min_activity=&limit=`(q 匹配代码前缀/名称/行业)与 `GET /api/quant-radar/dates`。
- **前端**：温度计头部日期选择器(查看该日/回实时);活跃榜头部搜索框(searchDay 走按日表,meta 标注来源);个股深评(资金榜单页+套件 tab 共用)增「量化行为历史(按日)」表。
- **⚠️ 前端 JS 已被用户 esbuild 压缩**(追加块局部变量改名 t/e/a):后续 JS 补丁必须先从文件提取实际字节做锚点,不能用授权时的原文。
- e2e：收盘后当日 200 行落库;搜「医药」命中万邦医药、搜「301」前缀 27 条;历史空日期优雅提示;个股 history 返回当日行(activity 62)。

### 9.4 UI 修复与数据列补齐（用户截图反馈）
- **按钮换行**：`.actions` 基类带 `flex-wrap:wrap + margin-top:12px + align-items:flex-end`,面板头里的日期控件被挤成竖排 → `.quant-date-actions/.quant-stock-actions` 覆盖为 nowrap/margin-top:0/居中,date input 定宽样式。
- **空数据列(量比/换手/振幅/现价)**：新增 `_fetch_tencent_quotes`(qt.gtimg.cn 本机可达,字段位实测 3现价/32涨跌%/38换手/43振幅/49量比,80码/批×≤18批) + `_enrich_snapshot`(纯函数):报价**直接覆盖**快照行——顺带修复兜底路径拿 moneyflow_dc 历史日 close/pct 当现价的陈旧价 bug(万邦医药实际涨停 +20.01% 曾显示 -2.67)。个股深评同样接入(量比进 hft 评分,无日K时实时涨跌兜底)。
- **行业列/板块聚合**：双源合并——Tushare `stock_basic` 全市场行业为底(kv 按日缓存 key `industry_map`,无 token 回退旧图;新浪行业分类只覆盖 ~2400 只老股,创业板/次新缺失) + market_intelligence 新浪映射覆盖(经 `set_industry_provider` 注入,core 挂钩,服务不 import core)。实测行业覆盖 30/30、板块聚合 12 个。
- **异动 ×800 封顶**：`_one_type` 翻页(≤3页×800),真实计数恢复(快速反弹 2336/高台跳水 1947)。
- 离线测试语义不变:injected 模式不发任何网络(quotes/industry 均被门控)。

### 9.5 砸盘识别与全量覆盖（用户反馈:商业航天集体被砸未浮现）
未浮现的三根因:榜单只按综合活跃度排(纯单边砸盘各机制分不高挤不进 TOP30)、板块聚合只聚 TOP30、无「方向」维度输出。修复:
- **全量口径**:异动翻页 ≤8页/类型(当日实测 12104 条/2500 只全捕获)、腾讯报价覆盖全部异动股(max_batches 40)、`_build_stock_items` 全量评分(不再截断 200)、按日表落全部异动股+高活跃/砸盘项(当日 2501 行)。
- **`_smash_score`(疑似量化砸盘,独立于五机制)**:单边杀跌异动(bear≥3 且 ≥2×bull,+6/次封50) + 深跌(≤-5% 放量+25/缩量+15;≤-2% +10) + 主力净流出配合(+15) + 封跌停(+10) + 高台跳水≥2次(+10)。≥40 记 smash 徽章,≥60 深评预测置顶「程序化出货」。`_direction_label`:砸盘/拉抬/拉锯。
- **板块集体识别**:`_aggregate_sectors` 重写——全量项聚合,新增 avg_change_pct/smashed_count/collective(≥3只被砸且均跌≤-2%=「集体砸盘」,对称「集体拉抬」),集体砸盘板块置顶;市场预测语追加「X、Y 疑似遭程序化集中抛售」。
- **payload/存储**:overview 加 `smashed`(砸盘榜 top30)+gauge.smashed_stocks;按日表 schema **v19** 补 direction/smash 列(幂等迁移)+(date,smash) 索引;`get_day(direction=)` 过滤(砸盘按 smash 排序);/day 路由透传 direction。
- **前端**:收割预警面板下半区「疑似量化砸盘榜」(绿系卡片,点击深评);板块表加 状态/被砸/平均涨跌 列;活跃榜加「方向」列;搜索区「只看砸盘」按钮;温度计「疑似砸盘」chip;深评头部盘口方向行。
- **e2e(当日真实数据)**:605 只砸盘、元器件(78只)/半导体(54)/通信设备(38)等 8 板块集体砸盘;搜「航天」16 只中 航天发展(-10.02,smash90)/航天科技(-9.98,smash100)/航天机电/航天动力 全部标记砸盘——用户所指商业航天成分股已可见。
- 已知限制:行业口径为标准行业(Tushare/新浪),「商业航天」等**概念板块**聚合需接东财概念成分(dc_member),留扩展点。
