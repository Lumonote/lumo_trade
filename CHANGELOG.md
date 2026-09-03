# Changelog

本项目所有值得注意的变更都会记录在此文件中。

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 文档
- 重构 README 为 Lumo Trade 主线（底层基于 Kronos 模型）
- 统一归集 Markdown 文档到 `docs/`，历史报告文件名由 Kronos 改为 Lumo 前缀
- 新增独立项目文档：`docs/Lumo_Trade_桌面端完整指南.md`
- LICENSE 版权变更为 Lumonote

## [1.1.6] - 2026-08

桌面端 Lumo Trade 正式版本。

### Added
- Lumo Trade 桌面包 v1.1.6
- 个股工作台扩展至 21 个分析页签（新增主力深度、量化矩阵、筹码·控盘雷达、机构持仓）
- 风险·机遇决策大屏（机会分 × 风险分四象限）
- 形态搜股（手绘/个股形态 + 本地指纹库 + 历史后验回测）
- 星轨图谱（产业链同心轨道）
- 系统托盘行情台与自动收盘维护
- 设备授权与数据备份迁移

### Changed
- 底部实时热点条新增六类信息流

## [v25] - 2026-07

评分体系迭代至 v25 共享评分规则。

### Added
- `analysis/scoring_rules.py`：sim / live 统一规则源（RULESET，杜绝规则漂移）
- 新增主力资金、期指门控 2 类因子
- `analysis/outcome_markers.py`：m1 标记体系（入选后表现回溯）

### Changed
- 数据驱动奖惩规则（RSI/短期涨幅/追高/量化极端等），停用无区分度旧规则

## [v5.0] - 2026-02

并发优化完整版。

### Added
- `retry_utils.py` 指数退避 + 多源回退 + 数据质量验证
- `async_data_collector.py` / `async_opportunity_scorer.py` / `batch_processor.py`
- `market_env_analyzer.py` 市场环境感知 + 6 种动态权重

### Performance
- 100 只股票处理耗时 ~450s → ~90s（5 倍提升）

## [v4.0] - 2025-12

Real-Time Intelligence Edition。

### Added
- 非官方渠道深度挖掘（社交/供应链/招聘/资金/政策）
- 信息可信度评估算法

## [v3.0] - 2025-12

Quality-First Integrated Edition。

### Added
- 一体化发现引擎（关键词/论坛/新闻三模式融合）
- 六阶段分析流程、五维度深度钻取、多轮验证

## [v2.0] - 2025-12

Ultra-Proactive Edition。

### Added
- 超前瞻性深度事件发现系统（6 维前瞻信号）
- 并购重组关联分析、关键词反向挖掘

## [v1.0] - 2025-11

基础版本。

### Added
- 批量分析 + 30 个量化模型 + 五阶段筛选
- Kronos 金融 K 线基础模型接入

---

## 发布说明

版本号采用语义化版本。`vX.Y` 里程碑版本对应历史报告（v1 → v2 → v3 → v4 → v5 → v25 评分 → m1 标记），
`X.Y.Z` 为桌面包当前版本号。详见 [docs/00_文档导航索引.md](docs/00_文档导航索引.md)。
