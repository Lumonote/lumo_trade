# 总览页「指数风向 + 板块机会与拐点」设计

日期: 2026-08-21
状态: 设计已确认, 待实施

## 1. 目标

在桌面「总览」页新增两个分区:

1. **指数风向** — 四大指数走势状态分析(上证 000001.SH / 深证成指 399001.SZ / 创业板指 399006.SZ / 科创50 000688.SH), 内部另加沪深300 000300.SH、中证1000 000852.SH 作风格轴。
2. **板块机会与拐点** — 板块级机会拐点双轨输出: 已触发(确认型) + 临界观察(预警型)。

不新建独立页面(YAGNI): 总览页当前是纯编排层, 加面板成本近零; 若后续信息密度不足再拆页。

## 2. 关键决策与约束

| 决策 | 内容 | 理由 |
|---|---|---|
| D1 | 展示四大指数, 内部用六条(加沪深300/中证1000) | 板块机会判断强依赖大小盘风格轴; 中证1000 已有 218 日现成数据 |
| D2 | **指数层只报状态分级, 不报拐点断言** | 218 个交易日里真实指数趋势拐点仅 3-5 次, 统计上无法证伪 |
| D3 | 拐点断言只限板块层 | 6000 只 × 194 日, 样本量足够做胜率校验 |
| D4 | 板块口径 = `moneyflow_dc` 自下而上聚合(时间序列) + 东财/star_orbit 板块名与成分(展示与下钻) | 只有 `moneyflow_dc` 有连续历史; 只有东财口径有用户认得的板块名 |
| D5 | **判据须过历史校验门槛才准上线** | 避免重蹈「行业/主题共性未校验即发布, 后被分半检验否决」的坑 |
| D6 | 盘中 provisional 信号**不享有历史胜率背书**, UI 分开标注 | 盘中资金流是未完成数据, 判据可能日内跳变 |
| D7 | `command_center_service.py` 只加注入槽, 不改业务逻辑 | 保持纯编排 + 独立降级架构 |
| D8 | 板块序列**落库**而非每次请求现场聚合 | `moneyflow_dc` 已 115 万行, 现场聚合不可接受 |
| D9 | 回测口径强制复用 `analysis/backtest_metrics.py` | 避免 Jensen 不等式下的年化高估老坑 |

## 3. 数据资源盘点(实测, App 库 com.kronos.app)

| 表 | 行数 | 覆盖 | 用途 |
|---|---|---|---|
| `market_daily` | 265,584 | 000001.SH / 000852.SH 各 218 日(20250924~20260820) | 指数日K |
| `moneyflow_dc` | 1,148,457 | 194 交易日 × ~6000 只/日(2025-11-05~2026-08-20) | 板块资金流序列(核心) |
| `ohlcv` | 183,382 | — | 板块涨跌幅/广度聚合 |
| `hot_sector_stock` | 17,158 | 快照式 | 个股→板块映射(主) |
| `hot_sector_board` | 560 | 快照式 | 板块命名 |
| `quant_radar_stock_daily` | 61,779 | 按日 | T5 席位共振 |
| `dragon_tiger_list` | 7,276 | — | T5 席位共振 |
| `opportunity_item` | 18,633 / 76 次挖掘 | — | 判据交叉验证参考 |
| `backtest_recommendation` | 876 | 带真实前瞻收益 | 判据校验参考 |

## 4. 架构

### 4.1 模块

| 模块 | 职责 | I/O |
|---|---|---|
| `analysis/index_pulse.py` | 指数日K序列 → 指标 + 状态分级 | 纯函数 |
| `data_store/sector_map_repo.py` | 个股→板块映射 | SQLite |
| `analysis/sector_series.py` | `moneyflow_dc` + `ohlcv` → 板块×日序列, 增量写表 | SQLite |
| `analysis/sector_turning.py` | 板块序列 → 已触发 / 临界观察 | 纯函数 |
| `webui/services/market_pulse_service.py` | 编排, 产出总览页 payload | 全注入 |
| `scripts/validate_turning_rules.py` | 判据历史校验(离线卡点) | SQLite |

复用: `analysis/market_regime.py`(`fetch_index_daily` / `persist_index_bars` / `get_index_bars` / `classify_index_level` / `merge_regime_levels` / `classify_style_regime` / `position_advice` / `trailing_changes`)、`analysis/backtest_metrics.py`(收益口径)。

### 4.2 接入

`CommandCenterService.__init__` 新增 `market_pulse=None` 注入参数, 缺省为空源 lambda。`overview()` 中:

```
pulse, d = self._safe(lambda: self._market_pulse(), {"indices": [], "sectors": {}})
degraded["market_pulse"] = d
```

payload 新增顶层键 `market_pulse`。其余面板不受影响。

### 4.3 新表(schema v21)

```sql
CREATE TABLE IF NOT EXISTS sector_daily_metrics (
  trade_date        TEXT NOT NULL,
  sector            TEXT NOT NULL,
  member_count      INTEGER,
  net_amount        REAL,     -- 主力净流入合计
  net_rate_median   REAL,     -- 净流入率中位数
  pct_chg_mean      REAL,     -- 等权涨跌幅
  breadth           REAL,     -- 上涨家数占比 0~1
  turnover_median   REAL,
  excess_vs_market  REAL,     -- 相对全市场超额
  provisional       INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (trade_date, sector)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sector_turning_signal (
  trade_date    TEXT NOT NULL,
  sector        TEXT NOT NULL,
  rule          TEXT NOT NULL,   -- T1..T5
  state         TEXT NOT NULL,   -- fired | watch
  score         REAL,
  evidence_json TEXT,
  provisional   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (trade_date, sector, rule)
) WITHOUT ROWID;
```

### 4.4 个股→板块映射与缺口

`sector_map_repo` 以 `hot_sector_stock` 为主表, Tushare `dc_member` 兜底(注意已知坑: `dc_member` 批量 8000 截断需按板块单查、`.DC` 后缀、地域板块需剔除)。

**降级行为(显式, 不静默)**: 映射不到板块的个股归入 `未分类`, 并在 payload 的 `coverage` 字段返回 `{mapped, unmapped, ratio}`。若 `ratio < 0.7`, 前端显示覆盖度警告。绝不静默丢弃个股。

## 5. 实时策略(三层新鲜度)

| 层 | 刷新 | 机制 |
|---|---|---|
| 指数 | TTL 30s, 盘中前端 30s 轮询 | 历史 bar 读 `market_daily`; 当日用实时批量报价叠加。**当日 bar 未生成时只挂「实时」徽章, 不伪造 OHLC**(复用 kline-realtime 的 `set_quote_provider` 模式) |
| 板块 | TTL 120s | 盘中抓当日全市场 `moneyflow_dc`(~6000 行), 按 `(trade_date, ts_code)` upsert; 板块聚合**只重算当日一片**, 不动历史 194 日 |
| 拐点信号 | 跟随板块层 | 当日 `provisional=1`; 收盘后(≥17:30)守护线程定稿重算并改写 `provisional=0` |

抓取链路走已验证的东财兜底(`clist` 被掐 → `moneyflow_dc`)。

每层在 payload 中各自带 `as_of`, 前端分别显示徽章。

## 6. 指数状态分级

每条指数计算:

- 趋势: 价格相对 MA20 / MA60 位置, MA20 斜率
- 动量: 5 日 / 20 日涨跌幅(`trailing_changes`)
- 量能: 成交额 5 日均 / 20 日均
- 波动: 20 日收益标准差
- 位置: 60 日收盘分位

→ 分级(复用并扩展 `classify_index_level`): `强势 / 温和上行 / 震荡 / 回调 / 风险`。

风格轴: 沪深300 与 中证1000 的 20 日相对强弱 → `大盘占优 / 小盘占优 / 均衡`(复用 `classify_style_regime`)。

仓位建议直接调用现成 `position_advice(level)`。

## 7. 拐点判据

| 编号 | 判据 | 直觉 |
|---|---|---|
| T1 资金反转 | 20 日累计主力净流入由负转正, 且近 3 日连续净流入 | 主力回补 |
| T2 背离修复 | 前期价跌但资金净流入(吸筹), 出现放量上涨日 | 吸筹兑现 |
| T3 广度突破 | breadth 由 <40% 升至 >60% 并维持 2 日 | 普涨确认 |
| T4 相对强度转正 | 20 日相对全市场超额由负转正 | 风格切入 |
| T5 席位共振 | `quant_radar` 板块异动席位数 + 龙虎榜上榜数骤增 | 资金关注度 |

**临界观察(watch)** = 判据差 1 个条件或差 1 日成立, 附「还差什么」的具体文案(例:「主力资金需再净流入 2 日, 当前 1 日」)。

**拐点分** = 通过校验的判据按各自历史超额加权, 归一到 0~100。

## 8. 校验门槛(实施第 3 步, 硬卡点)

`scripts/validate_turning_rules.py`:

1. 对 194 个交易日全板块逐日回放每条判据(**仅用收盘定稿数据**)
2. 取未来 5 / 10 日板块等权收益, 与全市场基准比超额
3. 收益口径强制走 `analysis/backtest_metrics.py`: 当日等权组合算术均值 → 跨日几何链乘

**上线门槛**: 样本 `n ≥ 30` 且 5 日超额 `> 0` 且 胜率 `> 52%`。

不达标的判据**不上线**, 在本文档「已否决判据」章节追加记录(判据定义 + 实测数据), 防止后人重做。

**预期**: 参考本项目历史经验(总分对尾部零区分度、行业共性被分半检验否决), 5 条判据中很可能仅 2-3 条过关。若全部不过关, 如实上报, 选择放宽判据或承认板块拐点不可预测 —— 不硬凑。

## 9. 前端

总览页新增两分区:

- **指数风向**: 4 张指数卡(状态分级 + 5/20 日涨跌 + 量能比 + 60 日位置)+ 风格轴结论 + 仓位建议
- **板块机会与拐点**: 双列表 —— 已触发(证据链 + 历史胜率标注)/ 临界观察(还差什么)
- provisional 信号带明显标记, 且**不显示历史胜率**

⚠️ 硬约束(既往教训):
- `webui/static/kronos_desktop_app.js` 已被 esbuild 压缩 → **按实际字节做锚点**追加
- 尾部追加的 IIFE **必须以分号结尾**(缺分号会 TypeError 静默不跑)
- 改完必须跑 `node --check`
- 避免 `innerHTML +=`(会灭掉已绑监听)

## 10. 错误处理

- 服务层每源独立 `_safe()` 降级, 单源失败只置对应 `degraded` 标志, 面板留空不崩
- 映射覆盖度不足 → 显式 `coverage` 警告, 不静默丢股票
- 指数实时报价失败 → 回退纯历史 bar, 去掉「实时」徽章
- 板块当日抓取失败 → 回退最近定稿日, 明示 as_of 日期

## 11. 测试

- `index_pulse` / `sector_turning`: TDD 纯函数, 构造序列覆盖边界(空序列、全平、单日、缺失值)
- `sector_map_repo` / `sector_series`: 真库小样本 + 缺口场景
- `market_pulse_service`: 注入假数据测各源独立降级
- e2e: 真库实证, dev 用 `KRONOS_PORT=7071`(7070 被打包 App 占)

## 12. 实施顺序

1. `sector_map_repo` + schema v21 建表, 回填映射, 报缺口数
2. `sector_series` 回填 194 日板块序列
3. **`validate_turning_rules.py` 跑校验 → 决定上线哪几条判据(硬卡点)**
4. `index_pulse` + 实时叠加
5. `sector_turning` + `market_pulse_service` + API
6. 前端两分区 + e2e
7. 收盘定稿守护线程

## 13. 已否决判据

2026-08-21 实测(样本:157 条板块线 × 194 交易日,2025-11-05~2026-08-20,仅定稿数据;前瞻 5 日,超额 = 板块等权累计收益 - 全市场等权累计收益;门槛:n≥30 且 5日超额均值>0 且 胜率>52%):

| 判据 | 样本 | 超额均值 | 胜率 | 年化 | 结论 |
|---|---|---|---|---|---|
| T1 资金反转 | 65 | +0.37% | 47.7% | +14.8% | ✗ 否决(超额正但胜率不足) |
| T2 背离修复 | 35 | -0.48% | 40.0% | -24.4% | ✗ 否决 |
| T3 广度突破 | 2218 | -0.01% | 45.9% | -4.2% | ✗ 否决 |
| T4 相对强度转正 | 855 | +0.03% | 49.2% | -1.5% | ✗ 否决 |
| T5 席位共振 | 568 | +0.66% | 50.2% | +30.9% | ✗ 否决(最接近,超额明显但胜率差 1.8pt) |

判据定义见 spec §7。

**2026-08-21 用户决策:胜率门槛从 52% 放宽到 50% 重跑,只放行 T5 席位共振**(实测胜率 50.2%、5日超额 +0.66%、年化 +30.9%、样本 568)。重跑结果:
- T5 席位共振 ✓ 上线(权重 1.0)
- T1/T2/T3/T4 保持否决(T1 胜率 47.7% 仍不足)

`kv_repo market_pulse/rule_stats` 现值:`enabled=["T5"]`、`weights={"T5": 1.0}`、门槛 `min_win_rate=50`。

⚠️ 上线门槛已从 52% 下调为 50%(盈亏平衡线),T5 的超额为正但胜率仅刚过 50%——展示时必须标注「判据经历史校验、胜率刚过半」,不能暗示高胜率。

## 14. 备注

- 打包 App 需重打包才能生效
- 本文档由用户自行决定是否 commit(项目约定: 不代为执行 git 写操作)
