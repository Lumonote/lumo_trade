# 机会挖掘评分 v25 —— 主力资金/期指多空接入 + 既有规则审计修复

日期：2026-07-09 · 分支：V2.1.2 · 状态：已实现（未 commit，git 由用户自管）

## 目标

1. 把已有数据接口中**尚未接入评分算法**的两路数据接进来并用回测验证：
   个股**主力资金**（Tushare `moneyflow_dc`，东财口径）与**期指多空**（中金所前20席位持仓，
   复用股指期货页 futures_service 的 kv 数据）；
2. 对既有 v24 规则做**全量逐条审计**，修掉失效/反向的规则。

## 数据基建（全部 SQLite，遵守「不用 CSV 落盘」约定）

- `scripts/backfill_factor_history.py`：幂等回填 2025-11-05 起 164 个交易日
  - 主力资金 → `moneyflow_dc` bucket `top_n=0`（与资金榜页共用，顺带给页面补了深历史）
  - 期指排名 → `kv_cache` namespace `futures_rank`（复用 `futures_service._load_day_rank`，
    中金所 CSV → Tushare fut_holding 兜底，deadline 防护）
  - CLI 默认写 repo `data/kronos_data.sqlite`（connection 解析顺序：`KRONOS_SQLITE_PATH` >
    `KRONOS_DATA_DIR` > repo 兜底）；已 ATTACH 同步到 App 库（163 快照日 / 652 行期指）
- `analysis/factor_history.py`：**因子取数唯一实现**，sim（`enrich_frame`）与
  live（`live_extra_factors`）共用；周末/节假日报告自动回看最近交易日（join 覆盖率 81.8%→99.1%）；
  live 侧只读本地 SQLite、带 4 天 staleness 守卫与 10 分钟 TTL，缺数据 → None → 规则不触发
- 顺手修复 `moneyflow_dc.trade_date` 双格式混存（`2026-04-22` vs `20260529`）：
  repo 写入/读取边界统一 `_date_key` 归一 + 存量 649 行迁移（无同桶冲突，已验证）

## 因子定义

- `main_net_rate`：当日主力净流入率%（净流入额/成交额）
- `fut_net_chg_3d`：IF/IH/IC/IM 前20席位净持仓 3 日滚动净变动之和（张）——市场级门控因子，
  用变动而非水平值（股指期货前20常年净空是套保结构，水平无信号）

## 既有规则审计结论（1487 行剔 degraded，双半窗方向一致性）

- **✅ 强验证保留**：v24 全部主力惩罚（chase 分段、chg3d/5d、RSI 极端、组合罚、sector、
  qs_extreme、sell3、signal_crowd…）与 sell0 奖（+14.5pp，最强正信号）
- **⚠️ 修复的 4 个问题**：
  1. `net_buy/buy_count 梯度奖`（sim + live v21 块，最高+10~16）：奖励负向群体
     （buy≥10: 37.1%wr、≥12: 29.9%、≥14: 19.4% vs 基线 40.3%，双半窗一致）→ 双侧关闭。
     **关闭后 A<B 倒挂与 [82,85) 断层同步修复**——这是 v24 遗留两大结构问题的共同根因
  2. `rsi_pullback`(RSI 50-60 罚4)：打了 25% 的行，触发组 40.9% ≈ 未触发 40.1% → 停用
  3. `sim_tech_high_pen`(tech≥80 罚3)：触发组 45.5% **高于**未触发 39.6%，方向反转 → 停用
  4. `score>=76 渐进罚`：区分度为零但**整形职能仍在**（移除会让 S 层灌水 74只/49%）→ 保留
- 观察项（未动）：`rsi_overbought`(80-85) 与 `qs_high`(90-95) 双半窗方向不一致但对分层零影响；
  live Pattern 三奖励（momentum_start 等）整体 Δ 微负，涉及 live 大块重构，留待下版

## 新规则（v25，evaluate_shared_rules 因子键缺失不触发）

| 规则 | 条件 | 分值 | 证据（前半/后半 vs 基线） |
|---|---|---|---|
| main_outflow | main_net_rate ≤ -5% | -10 | 29.4%wr；-4.3pp / -18.9pp |
| main_inflow | 2% ≤ rate < 5% | +4 | 46.7%wr；+2.1pp / +10.1pp（>5% 极端流入≈基线，不奖） |
| fut_bear | fut_net_chg_3d ≤ -8000 张 | -10 | 30.0%wr；-11.1 / -15.2；网格 6/8/10 单调改善，15 属旋钮边界且 live 25 分罚上限会截断，防过拟合取 10 |

## 终版回测（vs v24 真基线）

| | v24 | v25 |
|---|---|---|
| S | 22 / 63.6% / +7.00% | 11 / 63.6% / +7.18% |
| A | 82 / 45.1%（**A<B 倒挂**） | 27 / **63.0%** / +5.29% |
| B | 234 / 50.0% | 197 / 54.3% |
| B+ 合计 | 338 / 49.7% / +1.44% | 235 / **55.7% / +2.30%** |
| 三段走窗 B+ wr | — | 53.8 / 63.4 / 54.5（全>50%） |
| 分层单调 | ✗ | **S≥A≥B≥C 全单调，违例 0** |

新因子独立增量（关梯度奖后的对照）：B+ wr 52.2→55.7，近半窗 avg +1.47→+2.23。

## 已知不对称（记录在案，非本次引入）

- live 惩罚上限 25 分（v20），sim 无上限——市场门控与个股罚叠加时 live 会被截断；
- live Pattern 块三奖励保留（shared 池 skip），与 sim 直接消费同名规则存在口径差。

## 验证与工具

- 单测：tests/test_scoring_rules.py(33) + tests/test_factor_history.py(6) + moneyflow 系列全绿
- 审计：`scripts/audit_v25_rules.py`（逐规则触发组统计 + sim-only + 分层表）
- 网格：`scripts/grid_v25_variants.py`（RULESET 原地 patch 变体对比）
- 信号评估：`scripts/analyze_v25_factor_candidates.py`
- live 生效：下一次机会挖掘 run 自动带 v25（RULESET_VERSION 透传报告头 kronos-run-meta）；
  桌面 App 需重启后端进程（打包 App 需重打包）
