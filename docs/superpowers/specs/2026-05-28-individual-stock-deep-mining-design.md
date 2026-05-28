# 个股深度挖掘设计稿（主力 / 量化 / 机构持仓 / 控盘度）

- **作者**: OpenClawd（Claude Code 协助）
- **日期**: 2026-05-28
- **状态**: Draft（待用户复审）
- **关联代码**: `webui/templates/desktop.html` / `webui/services/stock_suite_service.py` /
  `analysis/stock_analysis_suite.py` / `data_store/` / `analysis/advanced_analysis.py`
- **关联 spec**: [`2026-05-23-stock-analysis-suite-design.md`](2026-05-23-stock-analysis-suite-design.md)
  · [`2026-05-25-data-sqlite-migration-design.md`](2026-05-25-data-sqlite-migration-design.md)

---

## 0. 背景与目标

### 0.1 背景

`8376aad` 提交后，个股弹窗工作台已上线 11 Tab（综合总览 / 操盘风控 / AI 解读），但
后端载荷与前端渲染对「主力 / 量化机构 / 控盘度 / 机构持仓」四个方向的覆盖均停留在
单一评分 + 文本结论层面：

- 主力阶段 Tab #4 仅输出 4 级 label，缺「建仓 / 洗盘 / 拉升 / 出货」时间轴。
- 筹码结构 Tab #6 只透传单个评分，`main_force_control` 控盘度（已在
  `analysis/advanced_analysis.py:181` 计算）未对外暴露；官方筹码分布 `cyq_perf` 未接入。
- 量价博弈 Tab #5 仅聚合 30 模型多空投票数，无信号矩阵 / 历史命中率 / 多周期共振。
- 龙虎榜机构席位、北向资金、Top10 流通股东、股东户数、机构调研、重仓基金、
  融资融券、大宗交易、官方筹码 在全代码库无证据。

### 0.2 本期目标

新增 / 重构 12 Tab 工作台四个维度的能力：

1. **主力深度** — 龙虎榜机构席位（含量化席位高亮）+ 北向资金趋势 + 60 日阶段时间轴
   + 量化行为签名识别。
2. **机构持仓** — 新增 Tab：Top10 流通股东 + 股东户数曲线 + 机构调研 + 重仓基金。
3. **控盘雷达** — `main_force_control` 透传 + 官方 `cyq_perf` 成本分布
   + 90/70/50 筹码集中度 + Top10 持股集中度。
4. **量化矩阵** — 30 模型 × 多周期信号矩阵 + 历史命中率 + 多周期共振 + 当前态势板。

### 0.3 非目标

- 不引入融资融券明细 / 大宗交易（优先级最低，本期不做）。
- 不重构 `StockAnalysisSuite` 为 pipeline 架构（另起 spec）。
- 不替换图表库（继续用 ECharts）。
- 不引入实时 Tick 数据源（仍以日 + 分钟为最高频）。

---

## 1. 总体架构

### 1.1 12 Tab 信息架构（11 → 12）

| # | data-suite-tab | 标题 | 状态 | 变化 |
|---|---|---|---|---|
| 1 | quick | 快速信息 | 沿用 | — |
| 2 | overview | 综合总览 | 沿用 | radar 增 `control_degree`、`quant_activity` 两轴 |
| 3 | market_cycle | 市场周期 | 沿用 | — |
| 4 | **main_force_deep** | **主力深度**（原"主力阶段"） | **重构** | 龙虎榜机构席位（量化席位高亮）+ 北向 + 60 日阶段时间轴 + 量化签名 |
| 5 | **quant_matrix** | **量化矩阵**（原"量价博弈"） | **重构** | 30 模型 × 多周期信号矩阵 + 历史命中率 + 共振 + 态势板 |
| 6 | **chip_radar** | **筹码·控盘雷达**（原"筹码结构"） | **重构** | 控盘度 + cyq_perf + 90/70/50 集中度 + Top10 集中度 |
| 7 | performance | 业绩预期 | 沿用 | — |
| 8 | probability | 概率推演 | 沿用 | scenario_probability 融合主力 / 机构证据权重 |
| 9 | risk_control | 操盘风控 | 沿用 | `hidden_risks` 接入「量化席位异动」「股东户数骤升」等 |
| 10 | limit_up_screening | 涨停筛选 | 沿用 | 因子聚合补入主力深度评分 |
| 11 | **institutional_holdings** | **机构持仓**（新增） | **新增** | Top10 流通股东 + 股东户数曲线 + 机构调研 + 重仓基金 |
| 12 | ai_interpretation | AI 解读 | 沿用 | prompt 补 §4/§5/§6/§11 摘要 |

> Tab 顺序约定：把「机构持仓」插入 `limit_up_screening` 与 `ai_interpretation` 之间，
> 让 AI 解读始终在末位。

### 1.2 数据流总览

```
点击个股
  │
  ▼
GET /api/stock-analysis-suite/{code}
  │
  ▼
StockSuiteService（5 min LRU 不变）
  │
  ▼
StockAnalysisSuite._collect_inputs()
  │
  ├── analysis/institutional/lhb_provider         ──┐
  ├── analysis/institutional/hsgt_provider        ──┤
  ├── analysis/institutional/holders_provider     ──┤
  ├── analysis/institutional/survey_provider      ──┤    data_store/akshare_adapter
  ├── analysis/institutional/fund_holdings_provider─┤    ─ fallback chain
  ├── analysis/institutional/cyq_provider         ──┘    ─ 限流/重试/熔断
  │
  ├── analysis/institutional/stage_classifier      ─ 规则引擎（资金流+量能+价格阈值）
  └── analysis/institutional/quant_signature_detector ─ 量化行为签名
       │
       ▼
   ┌─────────────────────────────┬────────────────────────────┐
   │ SQLite (低频隔夜量入库)      │ sentiment_cache (TTL)       │
   │ dragon_tiger_inst           │ cache_type: cyq_em          │
   │ hsgt_individual             │              minute_anomaly │
   │ top10_floatholders          │              hsgt_today     │
   │ stk_holdernumber            │              quant_signature│
   │ jgdy_detail                 │                              │
   │ fund_hold_detail            │                              │
   └─────────────────────────────┴────────────────────────────┘

夜间 cron: scripts/sync_institutional_data.py → SQLite 6 张表
```

### 1.3 关键架构决策

- **provider 单一职责**：仅"取数 + 归一化为 DTO"，不写业务规则。业务规则在
  `stage_classifier` / `quant_signature_detector` / 编排器汇总函数中。
- **`AkshareAdapter` 是唯一对外取数入口**：所有 provider 通过它取数，
  失败时按 fallback 链切源；测试通过依赖注入替换 `client_factory`。
- **payload 向后兼容**：保留 `overview.radar` 5 维评分；新增
  `main_force_deep / institutional_holdings / chip_control / quant_matrix`
  4 个顶级 key，不破坏现有 7 个 Tab 渲染。
- **缓存分层**：
  - 低频（龙虎榜历史、Top10、户数、调研、基金持仓）→ SQLite 永久。
  - 高频（cyq_em、当日异常分时、北向当日变动、量化签名）→ sentiment_cache TTL 10–30 min。

---

## 2. 数据层

### 2.1 `data_store/akshare_adapter.py`

```python
class AkshareAdapter:
    """统一 akshare 取数入口，失败按 fallback 链切源。"""

    FALLBACK_CHAINS = {
        "lhb_detail": ["ak.stock_lhb_detail_em", "ak.stock_lhb_detail_daily_sina"],
        "lhb_jgmm":   ["ak.stock_lhb_jgmmtj_em"],
        "hsgt_hold":  ["ak.stock_hsgt_hold_stock_em", "ak.stock_hsgt_individual_em"],
        "top10_float":["ak.stock_circulate_stock_holder", "ak.stock_main_stock_holder"],
        "gdhs":       ["ak.stock_zh_a_gdhs_detail_em", "ak.stock_zh_a_gdhs"],
        "jgdy":       ["ak.stock_jgdy_detail_em"],
        "fund_hold":  ["ak.stock_report_fund_hold_detail"],
        "cyq":        ["ak.stock_cyq_em"],
        "minute":     ["ak.stock_zh_a_minute", "ak.stock_zh_a_hist_min_em"],
    }

    def __init__(self, client_factory=None, rate_limit_per_min: int = 30):
        self._client_factory = client_factory or _default_akshare_factory
        self._rate_limiter = TokenBucket(rate_limit_per_min, period=60)
        self._breaker_state: dict[str, BreakerState] = {}

    def fetch(self, key: str, *args, **kwargs) -> pd.DataFrame: ...
```

- **限流**：默认 30 次/分钟/源（可配置），超限自动 sleep。
- **重试**：单源 2 次（指数退避 1s / 3s），再切下一个 fallback。
- **熔断**：单 fallback 链全部失败时进入 5 分钟熔断窗口；窗口内对该 key 的请求立即
  raise `AkshareUnavailable`，provider 捕获后返回 None。
- **日志**：每次切源 / 重试 / 熔断均 `logger.warning`，并写 `data_store.sync_log` 表。

### 2.2 SQLite Migration v6

`data_store/schema.py` 新增 migration 6，建 6 张表：

```sql
-- 龙虎榜机构席位（含量化席位标记）
CREATE TABLE IF NOT EXISTS dragon_tiger_inst (
  ts_code      TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  inst_name    TEXT NOT NULL,
  side         TEXT NOT NULL,        -- 'buy' / 'sell'
  net_amount   REAL,                 -- 净额（元）
  buy_amount   REAL,
  sell_amount  REAL,
  is_quant     INTEGER DEFAULT 0,    -- 0/1
  quant_confidence TEXT,             -- 'high' / 'medium' / 'low'
  reason       TEXT,
  PRIMARY KEY (ts_code, trade_date, inst_name, side)
);
CREATE INDEX idx_lhbi_code_date ON dragon_tiger_inst(ts_code, trade_date);
CREATE INDEX idx_lhbi_quant     ON dragon_tiger_inst(is_quant, trade_date);

-- 陆股通个股持股
CREATE TABLE IF NOT EXISTS hsgt_individual (
  ts_code      TEXT NOT NULL,
  trade_date   TEXT NOT NULL,
  hold_vol     REAL,
  hold_ratio   REAL,
  market_cap   REAL,
  PRIMARY KEY (ts_code, trade_date)
);

-- Top10 流通股东（季度快照）
CREATE TABLE IF NOT EXISTS top10_floatholders (
  ts_code      TEXT NOT NULL,
  end_date     TEXT NOT NULL,        -- 报告期 YYYY-MM-DD
  holder_rank  INTEGER NOT NULL,     -- 1..10
  holder_name  TEXT NOT NULL,
  hold_amount  REAL,
  hold_ratio   REAL,
  change_type  TEXT,                 -- 'new' / 'add' / 'cut' / 'unchanged' / 'exit'
  change_amount REAL,
  PRIMARY KEY (ts_code, end_date, holder_rank)
);

-- 股东户数
CREATE TABLE IF NOT EXISTS stk_holdernumber (
  ts_code      TEXT NOT NULL,
  end_date     TEXT NOT NULL,
  holder_num   INTEGER,
  avg_hold     REAL,                 -- 户均持股
  pct_change   REAL,                 -- 环比 %
  PRIMARY KEY (ts_code, end_date)
);

-- 机构调研
CREATE TABLE IF NOT EXISTS jgdy_detail (
  ts_code      TEXT NOT NULL,
  survey_date  TEXT NOT NULL,
  inst_name    TEXT NOT NULL,
  reception    TEXT,
  topic        TEXT,
  PRIMARY KEY (ts_code, survey_date, inst_name)
);

-- 重仓基金
CREATE TABLE IF NOT EXISTS fund_hold_detail (
  ts_code      TEXT NOT NULL,
  end_date     TEXT NOT NULL,
  fund_code    TEXT NOT NULL,
  fund_name    TEXT,
  hold_shares  REAL,
  market_value REAL,
  nv_ratio     REAL,
  PRIMARY KEY (ts_code, end_date, fund_code)
);

-- 同步日志（供前端 data_status / unavailable 文案使用）
CREATE TABLE IF NOT EXISTS sync_log (
  source       TEXT NOT NULL,        -- 'lhb' / 'hsgt' / ...
  ts_code      TEXT,                 -- NULL 表示全市场任务
  ran_at       TEXT NOT NULL,        -- ISO8601
  status       TEXT NOT NULL,        -- 'ok' / 'partial' / 'failed'
  rows         INTEGER,
  error        TEXT,
  PRIMARY KEY (source, ts_code, ran_at)
);
```

每张表配 Repo：`data_store/dragon_tiger_repo.py` / `hsgt_repo.py` / `holders_repo.py`
/ `survey_repo.py` / `fund_hold_repo.py` / `sync_log_repo.py`。Repo 仅暴露：

- `upsert(rows: list[Row]) -> int`（幂等，按主键覆盖）
- `get_by_code(ts_code, since=None, limit=None) -> list[Row]`
- `latest(ts_code) -> Optional[Row]`

### 2.3 sentiment_cache TTL 扩展

沿用 `data_store/sentiment_cache_manager.py`，新增四种 cache_type（不改 schema）：

| cache_type | 内容 | TTL |
|---|---|---|
| `cyq_em` | akshare `stock_cyq_em` 成本分布 | 30 min |
| `minute_anomaly` | 当日分时异动事件表 | 10 min |
| `hsgt_today` | 当日北向变动（盘中） | 15 min |
| `quant_signature` | 当日量化行为签名识别结果 | 15 min |

### 2.4 隔夜批处理脚本

`scripts/sync_institutional_data.py`：

- **CLI**：
  ```
  python scripts/sync_institutional_data.py \
    [--codes a,b,c | --watchlist | --all] \
    [--since YYYY-MM-DD] \
    [--tables lhb,hsgt,top10,gdhs,jgdy,fund]
  ```
- **默认行为**：从 watchlist + recent_hot 取交集（上限 200 只）；逐表跑、单表失败
  写 `sync_log.status='failed'` 后继续下一表，不阻塞其他表。
- **断点续传**：通过 `sync_log` 表查最新 ran_at，跳过本次 cron 周期内已成功的源。
- **部署**：cron `30 17 * * 1-5`（A 股收盘后 30 分钟，留 buffer）。
- **运维**：脚本退出码 `0` = 全部成功；`1` = 部分失败（详情见 sync_log）；
  `2` = 全部失败（触发告警）。

### 2.5 配置文件

新增 `config/quant_seats.json`（可热加载）：

```json
{
  "high_confidence": [
    "中信证券股份有限公司上海分公司",
    "华泰证券股份有限公司总部",
    "华鑫证券有限责任公司上海宛平南路证券营业部",
    "国金证券股份有限公司上海奉贤区福海路证券营业部",
    "财通证券股份有限公司杭州金城路证券营业部"
  ],
  "medium_confidence": [
    "华泰证券股份有限公司深圳益田路荣超商务中心证券营业部",
    "招商证券股份有限公司深圳蛇口工业八路证券营业部"
  ],
  "notes": "high_confidence = 经长期统计量化交易占比 > 60% 的席位"
}
```

新增 `config/institutional_thresholds.json`（阶段判定 / 量化签名阈值，可调）：

```json
{
  "stage_classifier": {
    "T_inflow_strong_sigma": 1.5,
    "T_inflow_mild_sigma":   0.4,
    "T_low_vol_atr_pct":     0.025,
    "T_vol_z_strong":        2.0,
    "T_vol_z_mid":           1.5,
    "T_price_pos_high":      0.70,
    "T_price_pos_low":       0.40,
    "min_sign_changes_wash": 5
  },
  "quant_signature": {
    "super_order_x_avg":     8.0,
    "big_order_pct_min":     0.70,
    "flash_drop_pct":        0.02,
    "flash_recover_ratio":   0.80,
    "wash_trade_window_min": 3,
    "order_count_ratio_x":   3.0,
    "closing_window_min":    30
  }
}
```

阈值变更生效路径：编辑 JSON → 重启 Robyn（不实现热加载，避免增加复杂度）。

---

## 3. 业务层

### 3.1 `analysis/institutional/` 包结构

```
analysis/institutional/
├── __init__.py
├── base.py                       # Provider 抽象 + DTO 基类
├── lhb_provider.py               # 龙虎榜机构席位（含量化席位识别）
├── hsgt_provider.py              # 北向资金持股 + 趋势
├── holders_provider.py           # Top10 流通股东 + 股东户数
├── survey_provider.py            # 机构调研
├── fund_holdings_provider.py     # 重仓基金
├── cyq_provider.py               # 官方筹码分布
├── stage_classifier.py           # 主力四阶段规则引擎
├── quant_signature_detector.py   # 量化行为签名识别
└── quant_seat_registry.py        # 量化席位热加载注册表
```

### 3.2 Provider DTO

`analysis/institutional/base.py`：

```python
@dataclass(frozen=True)
class ProviderResult(Generic[T]):
    data: Optional[T]
    data_status: Literal["fresh", "stale", "unavailable"]
    last_updated: Optional[str]         # ISO8601
    reason: Optional[str] = None        # unavailable 时的失败原因
```

每个 provider 接口：

```python
class BaseProvider(ABC):
    @abstractmethod
    def get(self, ts_code: str, **kwargs) -> ProviderResult[T]: ...
```

### 3.3 量化席位识别

`quant_seat_registry.py`：

```python
class QuantSeatRegistry:
    def __init__(self, config_path: Path):
        self._path = config_path
        self._reload()
    def _reload(self):
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._high = set(data.get("high_confidence", []))
        self._medium = set(data.get("medium_confidence", []))
    def classify(self, inst_name: str) -> tuple[bool, str | None]:
        if inst_name in self._high:   return True, "high"
        if inst_name in self._medium: return True, "medium"
        return False, None
```

`lhb_provider.fetch_history(ts_code, days=90)` 调 `AkshareAdapter.fetch("lhb_detail")`，
对每条记录调 `registry.classify(inst_name)` 填 `is_quant / quant_confidence`，再
`upsert` 到 `dragon_tiger_inst`。

### 3.4 主力四阶段规则引擎

`stage_classifier.py`：

输入：60 交易日数据，每个交易日：
`(close, vol, main_net_inflow, retail_net_inflow, atr_pct)`。

```python
def classify_stage(daily_rows: list[DailyRow], cfg: StageCfg) -> list[Stage]:
    """对每一日返回 {label, score_0_100, evidence} 三件套。

    所有阈值键名与 config/institutional_thresholds.json#stage_classifier 一致。
    """
    # 滚动指标
    inflow_z20 = (rolling_sum(main_net_inflow, 20) - inflow_ma60) / inflow_std60  # σ 化
    vol_z      = (vol - vol_ma20) / vol_std20
    price_pos  = (close - min60) / (max60 - min60)                                 # 0..1
    atr_pct    = rolling_atr_pct(14)
    sign_chg   = rolling_sign_changes(main_net_inflow, 20)

    out = []
    for day:
        ev = []
        # 优先级：拉升 > 出货 > 建仓 > 洗盘 > 中性
        if (inflow_z20 >  cfg.T_inflow_strong_sigma
                and vol_z >  cfg.T_vol_z_strong
                and price_pos > cfg.T_price_pos_high):
            label = "拉升"
            ev = ["主力净流入连续放大", "成交量突破", "价格突破前高"]
        elif (inflow_z20 < -cfg.T_inflow_strong_sigma
                and price_pos > cfg.T_price_pos_high
                and vol_z > cfg.T_vol_z_mid):
            label = "出货"
            ev = ["主力净流出加速", "高位放量"]
        elif (abs(inflow_z20) < cfg.T_inflow_mild_sigma
                and atr_pct < cfg.T_low_vol_atr_pct
                and price_pos < cfg.T_price_pos_low):
            label = "建仓"
            ev = ["主力净流入温和", "波动率收敛", "价格低位"]
        elif (sign_chg > cfg.min_sign_changes_wash
                and cfg.T_price_pos_low <= price_pos <= cfg.T_price_pos_high):
            label = "洗盘"
            ev = ["主力净流入正负交替", "下探不破位"]
        else:
            label = "中性"
            ev = ["主力意图不明"]
        out.append(Stage(date=..., label=label,
                         score=_label_to_score(label),
                         evidence=ev))
    return out
```

阈值默认值见 §2.5。`current_label` = 最近一天的标签。

### 3.5 量化行为签名识别

`quant_signature_detector.py` —— 输入：当日分钟数据 + 历史 5 日分钟数据
+ 当日龙虎榜机构席位。

| 签名 | 判定规则 | 来源 |
|---|---|---|
| `super_order_pulse` | 单分钟成交额 > 当日均值 × `super_order_x_avg` 且大单买/卖比 > `big_order_pct_min` | 分钟数据 |
| `wash_trade` | 连续 `wash_trade_window_min` 分钟内同价位反复成交，且总成交量异常 | 分钟数据 |
| `flash_drop_recover` | 单分钟跌 > `flash_drop_pct` 后 5 分钟内拉回 > `flash_recover_ratio` | 分钟数据 |
| `order_density_anomaly` | 委托笔数/成交笔数 > 当日均值 × `order_count_ratio_x`（无 tick 时跳过） | tick |
| `quant_seat_appearance` | 当日龙虎榜 `is_quant=1` 席位 ≥ 1 | dragon_tiger_inst |
| `closing_skew` | 超大单中 ≥ 40% 集中在尾盘 `closing_window_min` 分钟 | 分钟数据 |

返回：

```python
@dataclass
class QuantSignatureReport:
    events: list[Event]          # {type, time, value, severity}
    score_0_100: int             # 综合活跃度
    severity: Literal["high", "mid", "low"]
```

写 `sentiment_cache` 类型 `quant_signature`，TTL 15 min。

### 3.6 编排器契约（`StockAnalysisSuite` 字段增量）

payload 顶层新增（与现有 `overview / risk_control / cached_reports / ai_interpretation` 平级）：

```python
{
  "overview": { ...原有..., "control_degree": int, "quant_activity": int },
  "main_force_deep": {
      "data_status": "fresh|stale|unavailable",
      "last_updated": "YYYY-MM-DDTHH:MM:SS",
      "dragon_tiger": {
          "history_90d": [...],
          "quant_seat_appearances": int,
          "net_inst_buy_30d": float,
          "highlight_seats": [...]
      },
      "hsgt": {
          "latest": {"hold_vol": ..., "hold_ratio": ..., "trade_date": "..."},
          "trend_30d": [{date, hold_ratio}, ...],
          "delta_30d_pct": float
      },
      "stage_timeline": {
          "rows": [{date, label, score, evidence}, ...],   # 60 行
          "current_label": "拉升",
          "current_evidence": [...]
      },
      "quant_signature": {
          "events": [...],
          "score": int,
          "severity": "high|mid|low"
      }
  },
  "institutional_holdings": {
      "data_status": "...",
      "last_updated": "...",
      "top10_floatholders": {"period": "2026Q1", "rows": [...], "concentration": float},
      "holder_number":     {"latest_num": int, "pct_change_qoq": float, "history": [...]},
      "surveys":           {"recent_90d": [...]},
      "fund_holds":        {"period": "2026Q1", "rows": [...], "total_nv_pct": float}
  },
  "chip_control": {
      "data_status": "...",
      "last_updated": "...",
      "control_degree": int,
      "control_label": "低控/中控/高控",
      "concentration_90": float,
      "concentration_70": float,
      "concentration_50": float,
      "top10_concentration": float,
      "cyq_distribution": {"prices": [...], "ratios": [...], "main_cost_band": [low, high]}
  },
  "quant_matrix": {
      "data_status": "...",
      "last_updated": "...",
      "signals_matrix": [{model, period, signal, confidence}, ...],
      "hit_rate_30d": float,
      "multi_period_resonance": {"bull": int, "bear": int, "neutral": int},
      "current_posture": "强势多头|震荡偏多|震荡|震荡偏空|强势空头"
  }
}
```

每个顶层 key 必须含 `data_status` 和 `last_updated`。`data_status="unavailable"`
时其他字段允许缺失。

### 3.7 风控联动

`StockAnalysisSuite._build_risk_control` 内将以下事件追加到 `hidden_risks`：

- 量化席位上榜（severity=high）：「近 5 日量化席位上榜 N 次，警惕短期博弈风险」
- 股东户数环比骤升 > 30%：「股东户数 1 季度内骤升 X%，筹码集中度下降」
- Top10 流通股东净减持 > 5%：「机构在最新季度净减持 X%」
- `quant_signature.score >= 80`：「当日量化行为签名活跃度 >= 80，注意波动放大」

### 3.8 概率推演融合

`compute_scenario_probability` 输入由"30 模型投票"扩展为"30 模型投票 +
主力深度证据 + 量化签名"加权：

```
P_bull_raw = w_model * model_vote_bull
           + w_mf    * main_force_bull_signal
           + w_qs    * (1 - quant_severity_norm)
P_bear_raw = w_model * model_vote_bear
           + w_mf    * main_force_bear_signal
           + w_qs    * quant_severity_norm
P_neut_raw = w_model * model_vote_neutral
           + w_mf    * (1 - main_force_bull_signal - main_force_bear_signal)
           + w_qs    * 0.5    # 量化签名对中性贡献固定

# 归一到和为 1
S = P_bull_raw + P_bear_raw + P_neut_raw
P_bull, P_bear, P_neutral = P_*_raw / S
```

默认权重 `w_model=0.5, w_mf=0.3, w_qs=0.2`（写在
`config/scoring_runtime_config.json` 内，可调）。`main_force_*_signal` 与
`quant_severity_norm` 均预归一化到 0..1。

---

## 4. 前端 + API + 错误处理 + 测试

### 4.1 前端改动 — `webui/templates/desktop.html` + `webui/static/kronos_desktop.css`

#### Tab nav / 容器

- `nav#stockSuiteTabs` 内：
  - Tab #4 button label：`主力阶段` → `主力深度`
  - Tab #5 label：`量价博弈` → `量化矩阵`
  - Tab #6 label：`筹码结构` → `筹码·控盘雷达`
  - 在 `涨停筛选` 与 `AI 解读` 之间插入
    `<button data-suite-tab="institutional_holdings">机构持仓</button>`
- `#stockSuitePanels` 内对应新增
  `<section data-suite-pane="institutional_holdings" hidden>...</section>`

#### 新 / 改造的渲染函数

| 函数 | Tab | UI 元素 |
|---|---|---|
| `renderSuiteMainForceDeep(payload)` | #4 | 顶部 KPI 条（阶段+控盘度+量化席位数+北向占比）· 阶段时间轴色带 60 格 · 龙虎榜机构席位表格（量化席位加 `quant-seat-pill` 标签）· 北向 30 日趋势小图 · 量化签名事件表 |
| `renderSuiteQuantMatrix(payload)` | #5 | 30 × 4 信号热力矩阵（行=模型，列=日内/3日/10日/30日）· 当前态势卡片 · 多周期共振环形图 · 30 日历史命中率柱状图 |
| `renderSuiteChipRadar(payload)` | #6 | 控盘度仪表盘（0-100）· 4 集中度雷达（90/70/50/Top10）· cyq_perf 成本分布直方图（主力成本带阴影） |
| `renderSuiteHoldings(payload)` | #11 | Top10 股东表 + 变动徽章 · 户数曲线 sparkline · 机构调研列表 · 重仓基金条形图 |
| `renderSuiteOverview(payload)` 改 | #2 | radar 增 `control_degree` / `quant_activity` 两轴 |
| `renderSuiteRiskControl(payload)` 改 | #9 | `hidden_risks` 渲染为彩色风险卡片 |

#### 图表

- 复用现有 ECharts（`desktop.html` 内已引入），不引入新图库。
- 阶段时间轴用 `heatmap` 类型；信号矩阵用 `heatmap`；cyq 直方图用 `bar`；
  北向趋势用 `line`；户数曲线用 `line`；重仓基金用横向 `bar`；雷达用 `radar`；
  控盘度仪表盘用 `gauge`。

#### 渲染分发

- `applyStockSuitePayload(payload)`（`desktop.html:2419` 附近）switch 内补 4 个分支。
- `currentStockSuitePayload` 缓存原始 payload；Tab 切换时按 `data-suite-tab` 懒渲染
  （首次显示时才画图，避免初次全画）。
- ECharts 实例存储于 `window.__suite_charts__: {tabName: echartsInstance}`，
  Tab 切换或弹窗关闭时 dispose。

### 4.2 API

- **保留** `GET /api/stock-analysis-suite/:stock_code` 与 `POST .../ai`，payload 仍走
  单一接口（不拆 4 个 endpoint，避免前端管理多 in-flight）。
- `StockSuiteService` 缓存 key 不变（`(code, date, force_refresh)`）；新增字段在
  `_assemble_payload` 内填充。
- 强制刷新 `?force_refresh=1` 绕过 LRU；**不** 绕过 sentiment_cache TTL（避免误触发
  akshare 反爬）。如需绕 TTL，使用 `?bust_ttl=cyq,minute_anomaly` 显式列出。
- 新增诊断端点 `GET /api/diagnostics/data-sources`：返回最近 24h `sync_log` 摘要，
  供前端 "数据源暂不可用" 链接跳转。

### 4.3 错误处理与降级

1. **provider 级**：每个 provider 返回 `ProviderResult[T]`；data 为 None 时
   data_status 必为 `unavailable`。
2. **编排器级**：`_collect_inputs` 把每个 provider 的 `ProviderResult` 直接写入对应
   顶层 key（不抛异常）。
3. **前端级**：4 个新 render 函数先判 `payload.X.data_status`：
   - `fresh` → 正常渲染
   - `stale` → 渲染数据 + 顶部贴黄条 `最近一次入库：{last_updated}`
   - `unavailable` → 渲染骨架 + 红条 `数据源暂不可用` + 链接 `/api/diagnostics/data-sources`
4. **AI 解读 prompt**：自动跳过 `unavailable` 字段，避免 LLM 编造。
5. **akshare 熔断中**：provider 直接返回 unavailable，不重试。

### 4.4 测试矩阵

| 层 | 测试位置 | 工具 | 关键 case |
|---|---|---|---|
| Provider 单元 | `tests/institutional/test_<x>_provider.py` | pytest + fixtures（`tests/fixtures/akshare/*.parquet`） | 正常 / 字段缺失 / akshare 返回空 / fallback 触发 |
| AkshareAdapter | `tests/data_store/test_akshare_adapter.py` | stub client_factory | 主源失败切备 / 限流触发 sleep / 熔断进入与解除 |
| `stage_classifier` | `tests/institutional/test_stage_classifier.py` | 合成数据 4 套 + 真实样本 1 套 | 4 类标签各一个正向 + 中性退化 + 边界 |
| `quant_signature_detector` | `tests/institutional/test_quant_signature.py` | 合成分钟数据 | 6 种签名各独立触发 + 多签名共存 |
| Repo | `tests/data_store/test_<x>_repo.py` | 内存 sqlite | upsert 幂等 / get_by_code 范围 / latest 边界 |
| `StockAnalysisSuite` | `tests/test_stock_analysis_suite.py` 扩展 | 全 provider stub | payload 含 4 个新顶层 key + data_status 全枚举 |
| Robyn 路由 | `tests/test_robyn_app.py` 扩展 | http client | payload schema 校验（jsonschema）+ `/api/diagnostics/data-sources` |
| 隔夜同步脚本 | `tests/scripts/test_sync_institutional_data.py` | tmp sqlite + stub adapter | 表更新计数 + 断点续传 + 退出码 |
| 前端冒烟（可选） | 手动 + screenshot | 喂 fixture payload 验 4 个 Tab 渲染 | 4 个 Tab 渲染无 console error + 关键文本可见 |

> 前端冒烟暂不上 Playwright（避免新增依赖与 CI 时间）；用 `webui/run.py` 起本地后
> 手动对照 spec 截图归档到 `docs/screenshots/2026-05-28-deep-mining/`。

### 4.5 渐进交付里程碑

| M | 内容 | 验收点 |
|---|---|---|
| **M1** | AkshareAdapter + Migration v6 + 6 provider 空实现（返回 unavailable） + payload schema 落地 + 前端用 mock fixture 渲染 4 个新 Tab | `pytest tests/data_store/test_akshare_adapter.py` 全绿；前端打开任一个股，4 个新 Tab 渲染骨架不报错 |
| **M2** | 6 provider 真实落地 + 隔夜批 `sync_institutional_data.py` + sentiment_cache TTL 接入 | `python scripts/sync_institutional_data.py --codes 000001` 入库行数 > 0；`/api/stock-analysis-suite/000001` 返回 `data_status="fresh"` |
| **M3** | `stage_classifier` + `quant_signature_detector` + AI 解读 prompt 调整 | 阶段时间轴 60 格 + 当日量化签名可见；AI 解读引用主力深度内容 |
| **M4** | 30 模型 → 信号矩阵 + 历史命中率（量化矩阵 Tab 补全） | 信号矩阵热力图渲染 + 30 日命中率柱图 |
| **M5** | 风控 `hidden_risks` 联动 + `scenario_probability` 融合 + 文档 / CHANGELOG | 操盘风控 Tab 出现新风险卡片；概率推演权重生效 |

---

## 5. 风险与回滚

### 5.1 主要风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| akshare 反爬升级 / 接口下线 | 隔夜同步与盘中拉取失败 | fallback 链 + sentiment_cache TTL + sync_log 告警 + 前端降级文案 |
| 量化席位名单滞后 / 误判 | 量化席位高亮误标 | `confidence` 三档区分；前端用 tooltip 标注信源 + 时间；JSON 可热改 |
| 阶段判定误识率 | 用户做出错决策 | UI 明确标 "规则推断 仅供参考"；tooltip 列出证据；评分 < 60 时显示"模糊阶段" |
| SQLite 表膨胀（5 年 ≈ 数百万行） | 查询变慢 | 关键索引 `(ts_code, trade_date)` 已建；2027 年起按年归档历史表 |
| 12 Tab 弹窗交互复杂 | 视觉过载 | Tab 切换懒渲染；KPI 条只展示当前 Tab 关键指标 |

### 5.2 回滚预案

- **数据层回滚**：migration v6 reverse SQL 准备好；akshare_adapter 单独失败时
  其他模块不受影响。
- **业务层回滚**：4 个新 payload 顶层 key 互相独立；可单独关闭某一个（环境变量
  `KRONOS_DISABLE_PROVIDER_LHB=1` 等）。
- **前端回滚**：Tab #11「机构持仓」可通过模板配置 `INSTITUTIONAL_TAB_ENABLED=False`
  整体隐藏；#4/#5/#6 名称改回后端不受影响，仅 desktop.html nav label 改字。

---

## 6. 待办与开放问题

- [ ] 量化席位名单初版只列示例；M2 上线前由用户确认完整名单。
- [ ] `config/institutional_thresholds.json` 默认值需要 M3 上线后跑 2 周复盘再调。
- [ ] M4 信号矩阵的"多周期"用日内 / 3 日 / 10 日 / 30 日四列是否合理？需 M3 上线
  后看 UI 密度再定。
- [ ] AI 解读 prompt 模板的详细字段顺序与权重在 M3 单独 review。
- [ ] 是否在 M5 之后追加"主力监控总览页"独立路由（spec 外，未来工作）。
