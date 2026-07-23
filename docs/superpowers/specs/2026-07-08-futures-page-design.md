# 股指期货桌面页（futures）设计

日期：2026-07-08 · 分支：V2.1.2 · 状态：已实现

## 目标

桌面端新增「股指期货」菜单页，展示中金所四大股指期货（IF 沪深300 / IH 上证50 / IC 中证500 / IM 中证1000）的：

1. **实时行情**：各挂牌合约价格、涨跌、成交量、持仓量，叠加现货指数与**基差/贴水率**；
2. **多空持仓榜**（参考龙虎榜/资金榜的席位表交互）：中金所每日「成交持仓排名」前 20 会员的
   持买单量（多单）榜、持卖单量（空单）榜、成交量榜、**会员净持仓榜**（多空合并轧差）；
3. **多空力量分析**：前 20 合计多单/空单/净持仓/多空比/增减仓摘要卡 + 信号标签（多增空减→偏多 等）；
4. **持仓趋势**：近 N 个交易日前 20 席位多单/空单/净持仓走势（Plotly 折线，无 Plotly 时表格兜底）。

## 数据源（本机已实测可达）

| 数据 | 接口 | 说明 |
|---|---|---|
| 期货实时行情 | `ak.futures_zh_realtime(symbol=品种名)` | 新浪；4 品种名：沪深300指数期货 / 上证50指数期货 / 中证500指数期货 / **中证1000股指期货**（注意 IM 是"股指"不是"指数"，此 akshare 版本注册表如此） |
| 多空持仓排名 | `ak.get_cffex_rank_table(date, vars_list=[variety])` | 中金所官方 CSV；返回 `{合约: DataFrame}`，列含 rank(1-20, **999=合计行**)、long/short/vol 三组 `*_open_interest, *_chg, *_party_name`；数据盘后发布 |
| 现货指数 | `hq.sinajs.cn/list=sh000300,sh000016,sh000905,sh000852` | 直连 httpx（需 Referer），`trust_env False→True` 交替（与 star_orbit_service 同套路） |

## 架构（完全对齐 star_orbit / capital_rankings 既有模式）

- **服务** `webui/services/futures_service.py`：模块级函数 + 模块内 TTL 缓存；
  - `overview(force)` → 4 品种并行(ThreadPool)拉行情 + 指数现货 + 基差；内存 TTL 30s；
  - `position_rank(variety, date)` → 排名表；**kv_repo 持久缓存**（namespace `futures_rank`，键 `IF:20260707`，
    历史日期不可变=永久缓存；当日盘中未发布→自动回退最近有数据的交易日并在 payload 标注 `fallback_from`）；
    输出：分合约表 + 全合约聚合表 + 会员净持仓榜 + 摘要(多/空合计、净持仓、多空比、增减、信号)；
  - `position_trend(variety, days)` → 逐日读缓存/补拉，输出 `[{date, long, short, net, ls_ratio, vol}]`；
  - 交易日序列：`tushare_client.recent_trade_dates` 优先，失败回退「近 N 个工作日」（抓空自然跳过）。
- **路由** `webui/robyn_app.py`：`GET /api/futures/overview`、`GET /api/futures/positions?variety=&date=&refresh=`、
  `GET /api/futures/position-trend?variety=&days=`；服务直接 import（同 star_orbit_service，不进 core 单例）。
- **页面注册** `webui/core.py` `DESKTOP_PAGES` 加 `futures` 条目（排在 capital_rankings 之后）→ 侧栏+路由自动生效。
- **模板** `webui/templates/desktop.html` 加 `{% if active_page == 'futures' %}` 区块；about 页数据来源列表补「中国金融期货交易所」。
- **前端** `webui/static/kronos_desktop_app.js`（压缩单行是仓库现状）：
  - boot() 分发链插入 `"futures"===page&&(...,setupFutures())`（精准字符串编辑）；
  - `refreshCurrentView()` 插入 futures 分支；
  - 文件尾**以可读格式追加** `setupFutures()` 及渲染函数（打包时 CI 的 minify_static.sh 会统一再压缩）；
  - 表格复用 `.capital-data-table` / `.capital-table-wrap` 样式；涨红跌绿沿用 `changeClass`。
- **CSS** `kronos_desktop.css`（未压缩）尾部追加少量 `.futures-*` 布局样式。

## 权衡与取舍

- **不建新 schema 表**：排名数据按 (品种,日期) 整包 JSON 存 kv_cache 即可，避免 schema v17 迁移；
  趋势查询逐日命中缓存，首次拉取 N 日稍慢（每日一次 CFFEX CSV 下载，串行且逐日落缓存，超时也保留进度）。
- **合约维度**：positions 一次返回该品种当日全部合约 + 聚合，前端本地切换不重复请求。
- **信号规则透明**：仅基于当日多/空增减方向组合（多增空减=偏多、空增多减=偏空、双增=分歧放大、双减=离场观望），
  不做黑盒评分，与项目「透明规则」风格一致。
- **合规**：页面固定展示既有全局免责页脚；数据仅供研究参考。

## 验证口径

- 离线单测：纯函数（聚合/净持仓/信号/合计行解析）用构造数据测试，不联网；
- 既有测试回归：test_webui_core_surface、test_robyn_app（注意仓库既存失败清单，不引入新失败）;
- 端到端：本机起 Robyn，curl 三个 API 返回真数据；浏览器打开 /desktop/futures 目检渲染。

## 明确不做（YAGNI）

- 不做期货交易/模拟盘对接；不做分钟级 K 线图（后续可复用 futures_zh_minute_sina 增量加）；
- 不做国债期货（TS/TF/T/TL）——菜单聚焦"股指"期货，代码结构上品种表可扩展；
- 不改打包脚本（新增文件均在既有打包白名单目录 webui/ 内）。
