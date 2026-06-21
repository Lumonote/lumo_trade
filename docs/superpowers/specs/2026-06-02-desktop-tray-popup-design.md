# 桌面端 系统托盘图标 + 富弹窗 设计稿（跨平台 macOS / Windows）

- **作者**: OpenClawd（Claude Code 协助）
- **日期**: 2026-06-02
- **状态**: Draft（待用户复审）
- **关联代码**: `src-tauri/Cargo.toml` / `src-tauri/tauri.conf.json` /
  `src-tauri/capabilities/default.json` / `src-tauri/src/main.rs` / `desktop/index.html` /
  `webui/services/watchlist_service.py` / `webui/services/market_intelligence.py` /
  `webui/robyn_app.py`
- **关联 spec**: [`2026-05-31-v2-ux-and-data-completion-design.md`](2026-05-31-v2-ux-and-data-completion-design.md)
  （本期复用其落地的 `/api/market/hotspots` 三热榜聚合 + `/api/watchlist` 自选行情）

---

## 0. 背景与目标

### 0.1 背景

当前 Tauri 外壳（`src-tauri/src/main.rs`，490 行）只做两件事：① 拉起/管理本地 Python 后端进程
（`127.0.0.1:7070`），② 打开一个 1440×920 的 `main` 窗口，关窗即杀后端退出整个 App。
**完全没有系统托盘（菜单栏）图标，也没有托盘弹窗**：

- `Cargo.toml`：`tauri = { version = "2", features = [] }` —— 连 `tray-icon` feature 都没开。
- `tauri.conf.json`：只声明一个 `main` 窗口，无 `trayIcon` 配置。
- 此前所谓「状态栏」是**应用内顶部工具条**（网页 UI 里的 `#refreshMeta`），与系统托盘是两回事。

用户希望对标 WPS 那类常驻 PC 软件：**菜单栏/系统托盘有图标，左键弹出一个富信息面板**
（自选行情 / 实时热点 / 快捷工具），**macOS 与 Windows 都要实现**。

数据层已就绪：弹窗三区数据可直接复用已验证可用的两个 JSON 接口，**后端零改动**：
- `GET /api/watchlist` → 自选股 + 东财/腾讯实时报价（`watchlist_service.list_with_quotes()`）
- `GET /api/market/hotspots` → 金十快讯 + 雪球热门 + 东财板块/热股/涨幅榜
  （`MarketIntelligenceService.load()`）

主窗的「静态 splash 页探测 7070 就绪后 `location.replace` 进入后端 UI」这一现成范式
（`desktop/index.html`）可被弹窗页直接沿用。

### 0.2 本期目标

1. **系统托盘图标**：mac 菜单栏 / Win 系统托盘常驻图标，跨平台一致。
2. **富弹窗面板**：左键托盘 → 无边框、置顶、不进任务栏的紧凑面板（~360×520），失焦自动收起；
   含「自选行情 / 实时热点 / 快捷工具」三区，数据取自上述两接口，面板内自动刷新。
3. **右键托盘菜单**：`打开控制台` / `刷新行情` / `退出 Kronos`。
4. **关窗→隐藏到托盘常驻**（已拍板）：关主窗不退出、后端继续跑；仅托盘菜单「退出」真正关闭并杀后端。
5. **点击联动主窗**（已拍板）：点自选某行 → 主窗显示并跳该股个股分析；点快捷工具 → 主窗跳对应页。
6. **跨平台打包验证**：macOS（arm64 + Intel x86_64 现有双产物）与 Windows 均出图标 + 弹窗可用。

### 0.3 非目标（YAGNI）

- 不改任何后端 Python 代码 / 接口（纯复用 `/api/watchlist`、`/api/market/hotspots`）。
- 不引入前端框架/打包器（弹窗页是单文件原生 HTML+JS，与 `desktop/index.html` 同级，走 frontendDist）。
- 不做弹窗内的下单 / 编辑自选 / 复杂图表（弹窗只读 + 跳转；增删自选仍在主窗完成）。
- 不做托盘图标的未读角标 / 气泡通知 / 闪烁提醒（本期纯「点开看」，通知是后续可选项）。
- 不做 Linux 托盘（仓库当前打包目标为 mac + Win；Linux 代码路径保留但不验收）。
- 不实现 macOS「隐藏 Dock 图标变纯菜单栏 accessory」（保留 Dock，行为最不意外；可作后续选项）。

---

## 1. 决策记录（已与用户确认）

| # | 决策点 | 选定 | 影响 |
|---|---|---|---|
| D1 | 关闭主窗口（×）行为 | **隐藏到托盘常驻** | 拦截 `main` 窗 `CloseRequested`→`hide()`，不停后端；后端生命周期改由「真正退出」事件兜底 |
| D2 | 弹窗点击跳转力度 | **唤起主窗并跳对应页** | 需新增 Tauri 命令 `open_main(route)`：显示+聚焦主窗 + 导航到后端路由（个股分析/机会挖掘等） |
| D3 | 交互模型 | 左键 toggle 弹窗 / 右键原生菜单 | 标准菜单栏应用范式 |
| D4 | 弹窗加载方式 | 静态页 `desktop/tray.html`（frontendDist）+ fetch 两接口 | 与主窗 `index.html` 同范式；后端零改动 |
| D5 | mac Dock 图标 | 保留（Regular 激活策略） | 关窗后仍可从 Dock 或托盘重新唤起主窗 |
| D6 | mac 托盘图标样式 | 先复用现有 `assets/kronos_ai_stock.png`；预留单色 template 图标位 | 单色 template 是 mac 菜单栏最佳实践，作为打磨项 |

---

## 2. 架构总览

```
┌──────────────────────── Tauri 外壳 (Rust, main.rs) ────────────────────────┐
│                                                                            │
│  setup():                                                                  │
│    ├─ start_backend()  ── 现状不变，拉起 127.0.0.1:7070 ──┐                 │
│    ├─ TrayIconBuilder ── 建托盘图标 + 右键菜单            │                 │
│    └─ (tray-popup 窗口由 conf 声明, 隐藏创建)            │                 │
│                                                          │                 │
│  事件:                                                   ▼                 │
│   tray 左键 Up   → positioner 锚定 + popup.show()+focus    Python 后端       │
│   tray 右键      → 原生菜单 (打开控制台/刷新/退出)         (Robyn/Flask)     │
│   menu 事件      → open_main / refresh / app.exit(0)       提供 JSON API     │
│   popup 失焦     → popup.hide()                            ┌──────────────┐ │
│   main CloseReq  → 拦截 → main.hide()  (D1 常驻)           │ /api/watchlist│ │
│   ExitRequested  → BackendProcess.stop() (杀后端)          │ /api/market/  │ │
│                                                            │   hotspots    │ │
│  #[command] open_main(route)  ← 弹窗 JS 调用 (D2)          │ /desktop/*    │ │
│  #[command] hide_popup()      ← 弹窗 JS 调用               └──────────────┘ │
└────────────────────────────────────────────────────────────────────────▲──┘
                                                                           │ fetch
┌──────────────────── tray-popup webview (desktop/tray.html) ──────────────┴──┐
│  探测 7070 就绪 → fetch /api/watchlist + /api/market/hotspots → 渲染三区     │
│  自选行 onclick → invoke open_main('/desktop/...?code=600519')              │
│  快捷工具 onclick → invoke open_main('/desktop/features#...')               │
│  每 ~20s（仅可见时）自动刷新；失焦由 Rust 侧 hide                            │
└──────────────────────────────────────────────────────────────────────────┘
```

**数据流（弹窗显示一次）**：左键托盘 → Rust `popup.show()` → webview 触发 `visibilitychange`/
`focus` → JS 拉两接口 → 渲染。**联动主窗**：JS `invoke('open_main', {route})` → Rust 显示+聚焦
`main` 窗 + `main.eval("location.assign(route)")`（或对已在 `/desktop/*` 的主窗做 hash 导航）。

---

## 3. 交互模型

| 触发 | 平台 | 行为 |
|---|---|---|
| 左键单击托盘图标 | mac & win | 若 popup 隐藏→ positioner 锚定托盘位置后 `show()+set_focus()`；若已可见→ `hide()`（toggle） |
| 右键点击托盘图标 | mac & win | 弹出原生菜单：`打开控制台` / `刷新行情` / `——` / `退出 Kronos` |
| popup 失去焦点 | mac & win | `hide()`（点面板外/切走应用即收起，菜单栏应用标准行为） |
| 菜单「打开控制台」 | — | `open_main('/desktop/features')`：显示+聚焦主窗 |
| 菜单「刷新行情」 | — | 若 popup 可见则向其 `emit('tray://refresh')`；同时主窗（若在）刷新 |
| 菜单「退出 Kronos」 | — | `app.exit(0)` → 触发 `ExitRequested` → `BackendProcess.stop()` 杀后端 |

**防抖/防闪烁**：左键 toggle 与「失焦自动 hide」可能竞争（点图标时 popup 刚因失焦 hide，又被
toggle show，或反之）。处理：仅在 `MouseButton::Left` + `MouseButtonState::Up` 上做 toggle；
失焦 hide 在 `WindowEvent::Focused(false)` 上做；用一个 `Instant` 去抖（忽略 hide 后 ~200ms 内的
show，或反向），实现细节留给计划阶段，验收以「连点不卡死、不双触」为准。

---

## 4. 弹窗页面设计（`desktop/tray.html`）

### 4.1 版式草图（自设计，尺寸约 360×520）

```
┌─────────────────────────────────────────┐
│  Kronos 行情台        ⟳刷新  ⤢控制台    │  头部:标题 / 刷新 / 打开主窗 / 更新时间
│                                  09:42:18 │
├─────────────────────────────────────────┤
│  自选行情                         共 4 只 │
│   贵州茅台  600519     1685.0   +1.23% ↑ │  红涨绿跌(A股口径)
│   宁德时代  300750      198.6   -0.85% ↓ │  点一行 → 主窗跳该股个股分析
│   比亚迪    002594      245.1   +0.42% ↑ │
│   中际旭创  300308      142.3   +3.10% ↑ │  (空时显示「+ 在主窗添加自选」)
├─────────────────────────────────────────┤
│  实时热点            [涨幅榜] [快讯]      │  小 tab 切换
│   ① 某某科技  300xxx            +20.0%   │  涨幅榜 = hotspots.eastmoney.top_gainers
│   ② 某某股份  600xxx            +12.4%   │  快讯   = hotspots.jinshi(金十)
│   ③ 某某新材  002xxx             +9.8%   │
├─────────────────────────────────────────┤
│  快捷工具                                 │
│   [ 控制台 ]  [ 机会挖掘 ]  [ 个股分析 ]  │  点击→ open_main(对应路由)
└─────────────────────────────────────────┘
```

### 4.2 三区数据与行为

**头部**：标题「Kronos 行情台」+ `⟳刷新`（手动重拉两接口）+ `⤢控制台`（`open_main('/desktop/features')`）
+ 右下角 `updated_at`（取自接口或本地刷新时刻）。

**区 1 · 自选行情**（`/api/watchlist` → `items[]`）：每行 `name｜code｜price｜change_pct`。
- 涨跌色：**红涨绿跌**（A 股口径）；`change_pct > 0` 红、`< 0` 绿、`== 0` 灰。
- 点击行 → `open_main('/desktop/...?code=<code>')` 打开该股个股分析（具体路由计划阶段对齐 DESKTOP_PAGES）。
- `items` 为空 → 占位「+ 在主窗添加自选」，点击 `open_main('/desktop/features')`。
- `quoted=false`（报价源全挂）→ 行内价格显示「—」并提示「行情源暂不可用」。

**区 2 · 实时热点**（`/api/market/hotspots`）：默认两个 tab，懒展示、可滚动：
- `涨幅榜` = `eastmoney.top_gainers`（名称 + 代码 + 涨跌幅，红涨绿跌），点行同样 `open_main` 跳个股。
- `快讯` = `jinshi`（金十快讯标题 + 时间），点击可选择外链或忽略（本期纯展示，不外跳）。
- 某子源为空/报错（`hotspots.errors[...]`）→ 该 tab 显示「该来源暂不可用」，不阻塞另一 tab。

**区 3 · 快捷工具**：按钮组，全部走 `open_main(route)`：
- `控制台`→`/desktop/features`，`机会挖掘`→ 机会挖掘页路由，`个股分析`→ 个股分析页路由。
- 具体后端路由在计划阶段对照实际 `DESKTOP_PAGES`/`webui/robyn_app.py` 路由确认。

### 4.3 加载与刷新策略

- **就绪探测**：页面加载先 `fetch('http://127.0.0.1:7070/api/watchlist', {cache:'no-store'})`
  失败则按 `desktop/index.html` 同款节奏重试（1s 间隔，最多 N 次），就绪后渲染。
- **可见才刷新**：监听 `document.visibilitychange` / 窗口 `focus`；可见时每 ~20s 轮询一次，
  隐藏时停止（省流、避免后台空转）。
- **手动刷新**：头部 `⟳` 与右键菜单「刷新行情」（Rust `emit('tray://refresh')` → JS 监听）即时重拉。
- **失败兜底**：任一接口失败显示上次成功数据 + 顶部细条「更新失败，显示缓存」；不清空已渲染内容。

---

## 5. Tauri 外壳改动（`src-tauri/`）

### 5.1 `Cargo.toml`
- `tauri = { version = "2", features = ["tray-icon"] }`（开托盘）。
- 新增 `tauri-plugin-positioner = { version = "2", features = ["tray-icon"] }`（弹窗锚定托盘位置）。
- 实现期对照 Tauri v2 文档核对 feature 名与插件版本（计划阶段验证）。

### 5.2 `tauri.conf.json`
- `app.windows` 增加第二个窗口 `tray-popup`：
  `{ label:"tray-popup", url:"tray.html", width:360, height:520, resizable:false,
     decorations:false, alwaysOnTop:true, skipTaskbar:true, visible:false, focus:false }`。
- 注册 positioner 插件（若需 conf 侧声明）。`bundle.icon` 不变（复用现有图标集）。

### 5.3 `capabilities/default.json`
- `windows` 由 `["main"]` 扩为 `["main","tray-popup"]`。
- 增加 positioner / window（show/hide/set_focus）/ event（emit/listen）等所需权限项
  （具体权限标识计划阶段按 Tauri v2 capabilities schema 填全）。

### 5.4 `src-tauri/src/main.rs`
- **build 托盘**：`setup()` 内 `TrayIconBuilder` 建图标（`app.default_window_icon()` 或
  `assets/kronos_ai_stock.png`）+ `Menu`（打开控制台/刷新/退出）。`.on_tray_icon_event` 处理左键
  toggle（配合 positioner `move_window(Position::TrayCenter)` 一类）+ `.on_menu_event` 处理菜单。
- **positioner**：`.plugin(tauri_plugin_positioner::init())` +
  `.on_tray_icon_event(tauri_plugin_positioner::on_tray_event)` 缓存托盘坐标。
- **失焦隐藏**：`on_window_event` 中对 `tray-popup` 的 `WindowEvent::Focused(false)` → `hide()`。
- **D1 关窗常驻**：对 `main` 的 `WindowEvent::CloseRequested` → `api.prevent_close()` + `hide()`，
  **不再** `stop()`。后端 `stop()` 改为仅在 `RunEvent::ExitRequested { .. } | Exit`（即菜单「退出」/
  `Cmd+Q`）触发——现有 `app.run(|_, event| ...)` 已处理该事件，保留即可。
- **命令**：新增 `#[tauri::command] open_main(app, route)`（show+focus `main` + 导航）、
  `hide_popup(app)`；`.invoke_handler(tauri::generate_handler![open_main, hide_popup])`。

> 兼容性：现有 `terminate_child` / `cleanup_backend_processes` / pid 文件逻辑全部保留；本期只改
> 「何时调用 stop()」，不改 stop() 实现。`#![windows_subsystem = "windows"]` 保留（无控制台窗）。

---

## 6. IPC / 命令契约

| 命令 | 调用方 | 参数 | 行为 |
|---|---|---|---|
| `open_main` | tray.html JS | `route: string`（如 `/desktop/features` 或带 `?code=`/`#`） | 显示+聚焦 `main`；若主窗已在 `/desktop/*` 则 hash/同源导航，否则整页 `location.assign(http://127.0.0.1:7070{route})` |
| `hide_popup` | tray.html JS | — | `tray-popup.hide()`（点击跳转后顺手收起面板） |

| 事件 | 方向 | 用途 |
|---|---|---|
| `tray://refresh` | Rust → tray-popup | 右键菜单「刷新行情」通知弹窗重拉数据 |

JS 侧用 `window.__TAURI__.core.invoke('open_main', { route })` 与
`window.__TAURI__.event.listen('tray://refresh', ...)`（Tauri v2 全局注入，无需打包器）。

---

## 7. 数据契约（复用，零改动）

**`GET /api/watchlist`**（`watchlist_service.list_with_quotes()`）
```json
{ "items": [ { "code":"600519","name":"贵州茅台","added_at":"...",
              "price":1685.0,"change_pct":1.23,"change_amount":20.5,"main_net_inflow":1.2e8 } ],
  "count": 4, "quoted": true, "updated_at": "2026-06-02T09:42:18" }
```

**`GET /api/market/hotspots`**（`MarketIntelligenceService.load()`，含 30s TTL 缓存）
```json
{ "updated_at":"...", "jinshi":[...], "xueqiu_hot":[...],
  "eastmoney": { "industry_boards":[...], "concept_boards":[...], "money_boards":[...],
                 "hot_stocks":[...], "top_gainers":[...], "updated_at":"..." },
  "errors": {} }
```
弹窗本期只消费 `items[]`、`eastmoney.top_gainers`、`jinshi`、`errors`、`updated_at`；其余字段忽略。

---

## 8. 跨平台差异

| 维度 | macOS | Windows |
|---|---|---|
| 图标位置 | 顶部菜单栏 | 右下角系统托盘 |
| 弹窗锚定 | 图标正下方（positioner `TrayCenter` 系） | 托盘上方/右下（positioner 同 API 自动换算） |
| 图标样式 | 建议单色 template（`set_icon_as_template(true)`）适配深浅色；本期先用现有彩色 png | 现有彩色 ico/png |
| Dock/任务栏 | 保留 Dock 图标（D5）；popup `skipTaskbar` 不入程序坞窗口列表 | popup `skipTaskbar` 不入任务栏 |
| 进程清理 | 现有 `lsof`/`kill -TERM/-KILL` + 进程组 | 现有 `taskkill /T /F`（不变） |
| 退出键 | `Cmd+Q` / 菜单「退出」→ ExitRequested | 菜单「退出」→ ExitRequested |

托盘图标与 popup 的 Rust 代码用 `#[cfg(...)]` 仅在差异处分叉（如 `set_icon_as_template` 仅 mac），
主流程共用。

---

## 9. 错误与边界处理

| 场景 | 处理 |
|---|---|
| 弹窗显示时后端未就绪 | 探测重试 + 面板显示「正在连接本地服务…」，就绪后自动渲染 |
| `/api/watchlist` 失败 | 保留上次数据 + 顶部「更新失败，显示缓存」细条；不清空 |
| `quoted=false`（报价源全挂） | 价格列「—」+ 提示「行情源暂不可用」 |
| `hotspots.errors` 某源报错 | 对应 tab 显示「该来源暂不可用」，另一 tab 正常 |
| 自选为空 | 占位「+ 在主窗添加自选」 |
| 左键 toggle 与失焦 hide 竞争 | `Instant` 去抖（§3） |
| 关主窗后再点托盘「打开控制台」 | `open_main` 对已隐藏的 main 执行 `show()+set_focus()`（窗口仍存活，只是 hidden） |
| 菜单「退出」 | `app.exit(0)` → `ExitRequested` → `stop()` 杀后端 + 清 pid（复用现有） |

---

## 10. 文件改动清单

| 文件 | 类型 | 改动 |
|---|---|---|
| `src-tauri/Cargo.toml` | 改 | tauri 开 `tray-icon`；加 `tauri-plugin-positioner` |
| `src-tauri/tauri.conf.json` | 改 | 新增隐藏 `tray-popup` 窗口；注册 positioner（如需） |
| `src-tauri/capabilities/default.json` | 改 | 加 `tray-popup` + 所需权限 |
| `src-tauri/src/main.rs` | 改 | 建托盘+菜单+positioner；左键 toggle / 右键菜单 / 失焦 hide；`open_main`/`hide_popup` 命令；D1 关窗→hide |
| `desktop/tray.html` | **新增** | 紧凑富面板页（探测就绪 + fetch 两接口 + 三区渲染 + 自动刷新 + invoke 联动） |
| `assets/`（可选） | 新增 | mac 单色 template 托盘图标（打磨项，非必须） |
| 后端 / Python | **不动** | — |

---

## 11. 测试与验收

**P1 托盘骨架**：`cargo build`（src-tauri）通过；运行后 mac 菜单栏 / Win 托盘出现图标；右键出菜单。
**P2 弹窗页面**：左键弹出面板，三区渲染真实数据（自选行情红涨绿跌、涨幅榜、金十快讯），失焦收起。
**P3 联动+生命周期**：点自选行/快捷工具 → 主窗显示并跳对应页；**关主窗 ×，App 不退出、托盘仍在、
后端仍监听 7070**；托盘菜单「退出」→ App 退出且 `lsof -ti tcp:7070` 为空（后端被杀）。
**P4 跨平台**：mac（arm64 现有产物）+ Windows 打包后均图标可见、弹窗可用、退出干净；
弹窗在两平台锚定位置正确。

验收以「真实运行截图 + 行为观察」为准（沿用本仓 manual + screenshot 范式，不新增 Playwright 冒烟）。
打磨完进入 `verify` 技能跑一次桌面端实跑确认。

---

## 12. 开放问题 / 风险

1. **后端常驻内存**：D1 使后台 Python 服务长驻。该桌面 lite 包默认 `KRONOS_DISABLE_TORCH=1`，
   空闲时为轻量 Robyn/Flask 服务，常驻可接受；如后续反馈占用偏高，可加「空闲 N 分钟自动停后端、
   下次唤起再拉起」策略（本期不做）。
2. **positioner 在多显示器/缩放下的锚定**：少数环境弹窗位置可能偏移；计划阶段以插件推荐用法为准，
   验收时在主屏验证，多屏异常作已知项。
3. **个股/机会挖掘页的精确路由**：§4.2 / §6 的 `open_main` 目标路由需在计划阶段对照实际
   `DESKTOP_PAGES` 与 `webui/robyn_app.py` 路由表确认，避免跳转 404。
4. **WKWebView 缓存**：改了 `desktop/tray.html` 后桌面 App 可能仍显示旧页（历史已知坑），
   验证时若不更新需清 `~/Library/Caches`+`WebKit/com.kronos.app` 后全退重开。

---

## 13. 里程碑

| 阶段 | 内容 | 体量 | 依赖 |
|---|---|---|---|
| **P1** | Cargo/conf/capabilities 开托盘 + main.rs 建图标&右键菜单 + 隐藏 popup 窗 | M | Tauri v2 tray API 核对 |
| **P2** | `desktop/tray.html` 三区页面（探测+fetch+渲染+刷新） | M | P1（popup 窗存在） |
| **P3** | 左键 toggle+positioner+失焦 hide；`open_main`/`hide_popup` 命令；D1 关窗常驻 | M | P1、P2 |
| **P4** | mac + Windows 打包验证 + `verify` 实跑 | S | P1–P3 |
