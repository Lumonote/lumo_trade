# 量化雷达「吸筹埋伏」功能设计

日期:2026-07-16
状态:设计确认,待实施
所属页面:资金榜单 → 量化交易分析(量化雷达)tab

## 1. 背景与目标

量化雷达现有五机制评分与砸盘识别偏「防收割」,缺少进攻侧能力:识别主力/量化资金
**吸筹**行为,并统计**吸筹时间跨度、吸筹量**等指标,供用户做**买入埋伏**分析。

现状:
- `_spoof_score` 已有单日盘口「压单吸筹」信号(大卖单密集但股价不跌),但无跨日跟踪;
- `moneyflow_dc`(top_n=0 全市场快照)已回填 164 个交易日,含逐日主力净额/净流入率/
  四档单量/收盘价/涨跌幅 —— 吸筹检测可完全离线完成,不需逐股拉日K;
- `quant_radar_stock_daily` 按日表积累时间短,不作为吸筹检测数据基础。

已确认的三项设计决策:
1. **呈现形式**:量化雷达 tab 新增「吸筹埋伏榜」子榜 + 个股量化行为深评新增吸筹分析区块;
2. **判定口径**:资金+量价背离为主(主力持续净流入且股价不动),不强制低位,
   盘口/席位信号只作加分;
3. **窗口**:默认 40 交易日,前端可切换 20/40/60。

## 2. 检测算法 —— 新模块 `analysis/accumulation_detector.py`(纯函数)

### 2.1 输入

单只股票升序逐日序列(来自 `moneyflow_dc` top_n=0 行),每行字段:

```
{trade_date, net_amount(主力净额), net_amount_rate(%), buy_elg_amount, buy_lg_amount,
 close, pct_change, amount_unit}
```

金额统一按 `amount_unit`(万元/元)归一到**万元**后计算,展示层转亿元。

### 2.2 覆盖门槛

窗口 W ∈ {20, 40, 60},窗口内有效数据天数 < `max(12, W // 2)` → 返回 None(跳过,
不判定)。新股/长期停牌自然被此规则排除。

### 2.3 吸筹判定(三条同时满足 → `qualified=True`)

1. **流入持续性**:窗口内 `net_amount > 0` 的天数占比 ≥ 55%;
2. **流入力度**:窗口累计 `net_amount` > 0 且窗口累计 `net_amount_rate` ≥ `0.2 × 有效天数`
   (即日均净流入率 ≥ 0.2%,按净流入率归一避免大市值票金额虚高);
3. **量价背离**:窗口区间涨跌幅(首日 close → 末日 close)在 [-15%, +15%] 内
   —— 钱持续进、价不动才算吸筹;已大幅拉升的不进榜。

### 2.4 输出统计(`qualified` 与否都输出,便于个股深评展示「未通过原因」)

| 字段 | 含义 |
|---|---|
| `qualified` | 是否判定为吸筹 |
| `window` / `coverage_days` | 窗口与有效数据天数 |
| `accum_days` / `accum_ratio` | 净流入天数 / 占比 |
| `max_streak` | 最长连续净流入天数 |
| `span_days` | 吸筹跨度:窗口内首个→最近净流入日的交易日数(吸筹时间) |
| `total_net_wan` | 累计主力净流入(万元;展示转亿元)——吸筹量 |
| `avg_rate` | 日均净流入率(%) |
| `elg_share` | 超大+大单净额占累计净流入比(区分机构型吸筹 vs 中小单堆积) |
| `window_pct_chg` | 窗口区间涨跌幅(量价背离度的价一侧) |
| `score` | 埋伏评分 0-100(见 2.5) |
| `status` | 「吸筹中」/「疑似启动」(qualified 且近 3 日累计涨幅 ≥ 5%) |
| `reasons` | 中文理由列表;未通过时给未通过原因(如「净流入天数占比不足」) |
| `daily` | 窗口逐日 `{date, net_amount, pct_change}` 序列(个股区块画条形图) |

**体积约束**:`daily` 序列只在个股深评(`stock_analysis`)返回;吸筹埋伏榜行与 kv
快照一律剔除 `daily`,控制 payload 与单条 kv 体积。

### 2.5 埋伏评分(0-100,规则透明可调)

加权合成,系数集中在模块顶部常量便于调参:

- 流入占比:`(accum_ratio - 0.55) / 0.45 → 0..30 分`
- 连续性:`min(max_streak, 10) × 2 → 0..20 分`
- 流入力度:日均净流入率 0.2%..1.0% 线性映射 `0..25 分`
- 量价背离度:`|window_pct_chg|` 越小分越高,`(15 - |chg|) / 15 → 0..15 分`
- 机构型加成:`elg_share ≥ 0.7 → +10`

### 2.6 service 层加分项(不进纯函数,叠加在榜单/个股结果上)

- 当日盘口异动含「压单吸筹/大笔买入」(`changes_agg` 的 `big_sell+sell_queue` 密集但
  当日不跌,或 `big_buy` 密集):+5,追加理由;
- 近 30 日龙虎榜量化席位现身**买方**:+5,追加理由。
- 叠加后 score 封顶 100。

## 3. 取数与服务层

### 3.1 `data_store/moneyflow_repo.py` 新增

```python
def get_market_window(end_date: str, days: int, snapshot_top_n: int = 0) -> pd.DataFrame
```

取 `trade_date <= end_date` 的最近 `days` 个 distinct 交易日(top_n=0),返回这些日期
的全市场行(约 5000 股 × 40 日 ≈ 20 万行,单查毫秒~秒级)。日期归一沿用 `_date_key`。

### 3.2 `webui/services/quant_radar_service.py` 新增

```python
def accumulation_payload(window: int = 40, date: str = "",
                         fetch_quotes=None, market_rows_fn=None,
                         changes_agg_fn=None, seats_fn=None) -> Dict
```

- 流程:`get_market_window` → 按股分组 → 逐股 `detect()` → 取 `qualified` 项按
  `score` 降序全量返回(前端分页,同现有榜单套路);
- 实时增强(仅当日、在线模式):腾讯报价覆盖现价/涨跌(复用 `_fetch_tencent_quotes`)、
  行业映射补空(复用 `_industry_map`)、盘口/席位加分(2.6);
- 缓存:进程内 TTL 10min;每交易日把榜单落 kv(`quant_radar` namespace,
  key `accum:{YYYYMMDD}:{window}`);
- 历史回看:传 `date` 且非当前交易日 → kv 快照优先,缺则纯本地 as-of 重算
  (moneyflow 数据在库,可回溯全部 164 日),不发网络;
- `fetch_*` / `*_fn` 参数供离线单测注入,套路与 `overview()` 一致。

`stock_analysis()` 增加 `accumulation` 区块:取该股近 `window`(默认 40)序列跑
`detect()`,qualified 与否都返回统计 + `daily` 序列 + 理由。

### 3.3 API(`webui/robyn_app.py`)

- `GET /api/quant-radar/accumulation?window=40&date=` → `accumulation_payload`;
  `window` 只接受 20/40/60,非法回退 40;
- 个股接口无需新路由(`stock_analysis` payload 自动携带新区块)。

## 4. 前端(`webui/static/kronos_desktop_app.js` + `kronos_desktop.css`)

⚠️ 该 JS 已被 esbuild 压缩,修改须以实际字节做锚点。

### 4.1 吸筹埋伏榜(量化雷达 tab 内新区块)

- 位置:砸盘榜之后、板块榜之前(进攻侧信息与防御侧并列);
- 控件:窗口切换 20/40/60(按钮组,切换重新请求);沿用 tab 现有日期回看控件的
  date 参数;
- 表格列:代码 | 名称 | 行业 | 现价 | 涨跌% | 埋伏评分 | 吸筹天数(占比) | 最长连续 |
  吸筹跨度 | 累计吸筹量(亿) | 日均净流率 | 窗口涨幅 | 状态徽章(吸筹中/疑似启动);
- 行为:复用现有分页组件;点击行打开个股量化行为深评;理由挂 tooltip/展开;
- 空态:非交易日或数据不足时展示 note。

### 4.2 个股深评「吸筹埋伏分析」区块

- 结论卡:qualified 结论 + 埋伏评分 + 状态;
- 统计行:吸筹天数/占比、最长连续、跨度、累计吸筹量、日均净流率、超大单占比、窗口涨幅;
- 逐日净流入条形图:`daily` 序列,纯 CSS/内联 SVG 条形(正流入/负流出双色),不引图表库;
- 未通过判定时展示统计 + 未通过原因(不显示评分为 0 的误导性大字)。

### 4.3 免责

沿用量化雷达「疑似/公开数据代理指标/不构成投资建议」口径,榜单头部带一行说明。

## 5. 测试(TDD)

- `tests/test_accumulation_detector.py`(新):
  - 典型吸筹序列(持续流入+横盘)→ qualified,统计值精确断言;
  - 派发序列(持续流出)→ 不 qualified,理由正确;
  - 已拉升序列(区间涨幅 >15%)→ 量价背离条件排除;
  - 横盘无资金 / 数据不足 → 不 qualified / None;
  - 疑似启动状态、elg_share 机构加成、amount_unit 元/万元归一。
- `tests/test_quant_radar_service.py`(扩展):
  - 注入假 market_rows_fn → 榜单排序/字段/kv 落库;
  - 盘口/席位加分叠加与封顶;
  - `stock_analysis` 带 accumulation 区块;
  - 历史 date 回看走本地重算。
- `tests/test_robyn_app`(或既有 API 测试处):accumulation 路由 smoke + window 参数校验。

## 6. 不做的事(YAGNI)

- 不新建数据库表(吸筹为派生计算;kv 快照仅为提速,删了可重算);
- 不改五机制评分、砸盘榜、`quant_radar_stock_daily` 表结构;
- 不做自动买入/跟单联动(模拟盘自动跟单是独立功能);
- 不做 L2 逐笔级吸筹识别(本机无 L2 数据,维持公开数据代理指标口径)。

## 7. 风险与已知限制

- `moneyflow_dc` 当日盘中数据可能未落库:榜单以库内最近交易日为窗口末端,
  payload 标注 `data_date`;
- 主力净流入为代理指标,无法区分「主力吸筹」与「游资短炒接力」,elg_share 与
  连续性统计部分缓解;免责口径已覆盖;
- 净流入率极端小盘票易放大:评分用日均净流入率上限截断(1.0% 封顶计分)缓解。
