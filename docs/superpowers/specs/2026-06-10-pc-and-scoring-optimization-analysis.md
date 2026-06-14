# Kronos PC端功能与机会评分算法深度优化分析

- 日期: 2026-06-10
- 分支: V2.1.1
- 状态: **分析定稿，开发启动**
- 数据依据: `results/backtest_rebuilt_20260407_204957.csv`（1489行 / 77交易日 / 2025-11-19~2026-03-09，全样本5日基线胜率 40.4%，弱市数据）

## 0. 总结

PC端功能层面已经相当完整（10页面、18服务零TODO，资金榜单+模拟盘6期与指挥中心5期均落地），缺口在**通知体系、4份未实施spec、算法健康度可视化**；算法层面最大问题不是参数而是**结构**——回测器与生产评分器已分叉到规则方向相反（chase_risk 一罚一奖），且 v17/v20 连续削弱防追高惩罚削过头：总分 IC(+0.114) 仅为最强单因子 change_3d(-0.202) 的六成。

---

## 1. PC端现状

- 10个桌面页注册于 `webui/core.py:2353`（DESKTOP_PAGES 数据驱动），路由 `robyn_app.py:312-319`，无 stub 页。
- `webui/services/` 18模块（5752行）grep TODO/FIXME 零命中，主要模块有测试（capital_rankings / paper_trading(+engine) / db_backup / command_center / pattern 系列 / watchlist）。
- "资金榜单+机会分析+模拟盘+整库备份"6期（spec `capital-rankings-and-paper-trading.md` §11）与"风险·机遇指挥中心"5期（spec `2026-06-08-risk-opportunity-command-center-design.md` §14）**代码层面均已完成**（spec状态行未更新）。
- 托盘弹窗（`src-tauri/src/main.rs:486-620` + `desktop/tray.html`）、应用内五分类通知条（`kronos_desktop_app.js:4852`）、SQLite任务系统 + 2条收盘守护线程（形态指纹重建 `core.py:2188`、模拟盘EOD `core.py:2221-2273`）均可用。

## 2. PC端缺口与开发计划（按优先级）

| 优先级 | 项目 | 说明 |
|---|---|---|
| **P0** | 通知闭环 | ① 模拟盘EOD复盘完成后接入应用内通知条分类（spec D10 半缺）；② 引入 `tauri-plugin-notification` 实现OS级通知（EOD复盘完成、机会挖掘任务完成、自选异动），目前 Cargo.toml 无该插件、App不开窗口时完全是哑的 |
| **P1** | 模拟盘↔机会挖掘自动跟单闭环 | 设置页开关（默认关）；每日机会报告生成后按档位（默认A级≥78）自动以次日开盘价建仓模拟盘、N日（默认5）后自动平仓。等于给评分算法装上持续 walk-forward live 前向验证 |
| **P1** | 算法健康度卡片 | reports/command-center 加"评分健康度"：分档滚动胜率（20d）、降级run占比（quant=0）、样本量；数据源 `results/backtest_rebuilt_*.csv` |
| **P2** | 4份未实施spec | 多空研判面板（plans已有phase1/p0a/p0b，最优先）> 个股深挖 > v2-UX > uzi-skill |
| **P2** | 数据源降级体验 | Tushare积分不足时明确提示原因 + akshare回退按钮，而非静默"数据待回填" |
| **P3** | 工程卫生 | kronos_desktop_app.js（6882行）按页面拆模块；两份已实现spec状态行更新；wip commit 拆分 |

---

## 3. 算法结构性问题（比调参优先）

1. **双轨漂移**：`simulate_v5_backtest.py`(v20) 与 live `opportunity_scorer.py`(v22/v23+) 有14+处规则分歧，**chase_risk 方向相反**（sim: ≥80 罚15；live: ≥75 奖4，`scorer:624-633`）。优化器参数全部作用在sim侧，跨轨迁移不可靠。→ **抽共享打分规则模块，两侧消费同一套规则**。
2. **v22静态权重是死配置**：`DIMENSION_WEIGHTS`(:125-136) 从不生效——`_select_dynamic_weights`(:3727-3783) 四分支全返回动态模板，实际生效 v19 base（quant 0.25/position 0.22）。
3. **白付成本采集**：events/sentiment 权重=0 但采集照跑；机构级 `analysis/institutional/dragon_tiger_list_provider.py` 未接入 scorer。
4. **回测盲区**：回测CSV仅10因子列；chase/chg3d/day_change 2026-01前全缺；live 的 headroom/牛股Pattern/单调性约束从未被回测验证。→ **报告落盘时补全因子列**。
5. **walk-forward CV 已实现但默认关闭**（`rebuild_and_optimize.py:655-743`）；optimize_v53_final 无CV。→ **默认启用**。
6. **降级run**：quant=0封顶60不区分"数据缺失 vs 真实弱信号"（:530-533 只看分数不看 quant_details error）。本次数据含101条降级行（wr 41.6%）污染样本。→ **degraded 标记 + 回测剔除**。

## 4. 参数改动（v24，5条，按证据强度排序）

新回测核心 IC：change_3d **-0.202**(p=9e-9) > chase_risk -0.193 > change_5d -0.162 > sell_signals -0.159；tech_score 唯一显著正因子 +0.081；quant_score/buy_signals 不显著；总分 +0.114。

| # | 改动 | 证据（n / 5日wr / avg） |
|---|---|---|
| 1 | 恢复 chg3d≥12 重罚（≥12 罚12-15、≥18 罚15+，部分回滚v17） | chg3d[10,18): 213/31.9%；≥18: 136/30.1%/-5.06% |
| 2 | chase惩罚分段下移：40-60罚5 / 60-80罚10-12 / ≥80罚15；**同时移除live的chase奖励**（方向冲突源头） | chase[60,80): 106/**28.3%**/-2.44%，比≥80(34.3%)还差，中段是惩罚空档 |
| 3 | **移除 zt_high_chase_bonus**（v17涨停+chase≥50加8分） | 该子群 210/35.2%/-2.86%，劣于涨停&chase<50(167/37.1%/-0.63%)，v17结论已失效 |
| 4 | quant<50奖励加 **sector<55 门控** | 无门控已跨期退化63.3%→**40.8%**；加门控 63/58.7%/+4.14% 稳定 |
| 5 | 新增 RSI≥80 × chase≥60 组合重罚（约-10） | 全场最差大子群 105/**26.7%**/**-6.99%** |

**B级提升路径**（落地为足额扣分，遵守"只打分不淘汰"偏好）：B级内剔除 `chg3d≥12 或 chase∈[40,80)` 后 n=398→263，wr 45.7%→**50.2%**（被剔除77只 wr 32.5%）。

**其它发现**：
- S档=高赔率低胜率（wr 31.1%全场最低，但按日去市场均值超额收益最高+0.63%）——不再压分，展示层标注。
- sell=0 跨期稳定（56.7%/52.4%）；tech_score 正向稳定。
- ⚠️ chase/chg3d 列仅2026-01后弱市数据（基线37.4%），防追高结论牛市未验证 → 自动跟单前向验证更根本。
- 多重检验风险：n<60子群 ±8pct 内不显著；quant<50×sector≥75 (n=9) 仅方向警示。

## 5. 执行顺序

1. **算法轨**：统一 sim/live 打分核心 → CSV补全因子列+degraded标记 → 5条参数改动 → walk-forward回测验证（合格线：B级wr≥50%、A>B单调保持、tier表完整）。
2. **PC轨**（与算法轨并行，文件不相交）：通知闭环 → 模拟盘自动跟单 → 算法健康度卡片。
3. 后续：bull-bear panel 等未实施 spec、JS拆模块。
