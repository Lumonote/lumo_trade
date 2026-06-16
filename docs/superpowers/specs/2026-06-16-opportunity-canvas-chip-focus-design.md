# 投资机会画布 · 关系芯片点击定位 + 自动缩放

日期: 2026-06-16
范围: 前端 (`webui/static/kronos_desktop_app.js` + `webui/static/kronos_desktop.css`)。无后端改动。

## 背景 / 问题

「投资机会挖掘」页的 **投资机会画布**(`#opportunityCanvasViewport`,2D canvas 节点图)右侧详情面板里,
「画布关系」区块会列出当前选中节点的 **上级 / 下级** 节点(例如选中根「报告」节点时,下级是 32 个板块:
矿物制品 / 铜 / 通信设备 …)。

现状两点不足:

1. 这些关系条目由 `opportunityCanvasRelationSummary()` 渲染为纯文本 `<span>`,**不可点击** —— 用户看到关系名却无法跳过去。
2. 画布只有 `fitOpportunityCanvas()`(适配**全部**节点)这一种自动取景,没有「聚焦到**某一个**节点」的能力。

手动缩放交互(滚轮缩放 / 拖拽平移 / 惯性 / `+` `-` `重置` `全屏` 按钮,见 `bindOpportunityCanvasControls()`)**已完整可用**,本次不改。

> 注:`desktop.html` 中 workbench 页与 opportunities 页各有一份画布工具栏,ID 重复,但二者在互斥的
> `{% if active_page == ... %}` 块里,运行时 DOM 只存在一份,不构成冲突。本次不处理该重复。

## 目标

点击「画布关系」里的某个芯片 → 选中该节点(高亮 + 右侧详情切到它)并把画布平滑**居中 + 自动缩放**到
该节点**连同其直接相邻节点**(上级 + 下级),让用户在看到关系名的同时一键「定位」并看清上下文。

## 非目标 (YAGNI)

- 不让自由文本「业务标签」pill(龙虎榜 / 概念 等)可点击 —— 它们不对应单个画布节点。
- 不改工具栏分类页签(层级 / 排名 / 板块 / 标签 / 热门 / 资金 / 龙虎榜)—— 已能切换维度。
- 不改后端、不改导出、不动重复 ID 工具栏。
- 不为相关热门板块 / 下钻列表加定位(本次只做「画布关系」芯片)。

## 设计

### 1. 新增 `focusOpportunityCanvasNode(id)`

居中 + 适配「节点及其直接邻居」,复用既有缓动变换。算法:

1. `stopOpportunityCanvasInertia()`;取 `layout = state.opportunityCanvas.layout`、`pos = layout.positions.get(id)`,缺失则直接 `return`(不报错)。
2. 邻居集合:复用 `opportunityCanvasConnectedIds(layout, id)`(返回 id 自身 + 所有与之相连边的另一端)。
3. 对邻居集合里有 `positions` 的节点求外接框 `{minX,minY,maxX,maxY,w,h}`(与 `opportunityCanvasBounds` 同口径,但只针对子集)。
4. 视口尺寸取 `#opportunityCanvasViewport` 的 `getBoundingClientRect()`;`pad = 80`。
   `fitScale = min((vw-2pad)/w, (vh-2pad)/h)`,再 `clamp(0.26, 1.2)` —— 下限同既有 `clampScale`,
   上限 1.2 防止「孤立/单节点」放得过大。
5. 目标偏移让外接框中心落到视口中心:
   `offsetX = vw/2 - centerX*fitScale`、`offsetY = vh/2 - centerY*fitScale`(`center = 外接框中心`)。
6. 写入 `c.scale / c.offsetX / c.offsetY` 后调用 `applyOpportunityCanvasTransform()`(已有的 rAF 缓动,自动出平滑动画)。
7. `selectOpportunityCanvasNode(id)` —— 设 `activeId`、重绘高亮、并 `renderOpportunityCanvasDetail(node)`
   把右侧面板切到目标节点(其关系芯片随之刷新,形成可连续「定位」的浏览链)。

### 2. 关系芯片改为可点击

`opportunityCanvasRelationSummary()` 内的 `itemHtml(ids)`:每个条目从
`<span>${title}</span>` 改为携带 id 的聚焦按钮:

```
<button type="button" class="canvas-relation-chip" data-canvas-focus="${id}" title="定位到画布">${title}</button>
```

(`id` 在 `ids` 里本就有,当前只用了 `title`;改为一并输出 `data-canvas-focus`。)

### 3. 绑定点击

`renderOpportunityCanvasDetail()` 设完 `innerHTML` 后,沿用现有 `data-canvas-*` 绑定风格补一段:

```
detail.querySelectorAll("[data-canvas-focus]").forEach((btn) => {
  btn.addEventListener("click", () => focusOpportunityCanvasNode(btn.dataset.canvasFocus));
});
```

### 4. 样式

`kronos_desktop.css`:`.canvas-relation-chip` 继承现有 `.canvas-detail-chip-list` 芯片观感,
但 `cursor:pointer`、去掉按钮默认外观、加 hover(描边/底色变化)以示可点。

## 数据流

```
用户点击关系芯片(button[data-canvas-focus=ID])
  → focusOpportunityCanvasNode(ID)
      → 求 ID + 邻居外接框 → 算 fitScale/offset → applyOpportunityCanvasTransform()(缓动到位)
      → selectOpportunityCanvasNode(ID) → 高亮 + renderOpportunityCanvasDetail(目标节点)
          → 详情面板刷新,关系芯片重新绑定(可继续点)
```

## 边界 / 错误处理

- `id` 不在 `positions`(被过滤掉/跨维度)→ `focusOpportunityCanvasNode` 直接 return,不抛错。
- 节点无邻居(外接框=单节点)→ 上限 1.2x 防过度放大。
- 视口尺寸为 0(面板隐藏/未布局)→ rect 宽高有保护,`applyOpportunityCanvasTransform` 已有 rAF 防抖,不崩。
- 缩放统一走既有 `clamp(0.26, 2.4)` 语义(本函数用 0.26–1.2 子区间)。

## 测试 / 验证

纯 canvas 交互,无单元测试钩子;以**实跑**验证:

1. opportunities 页打开画布,根节点详情「画布关系 · 下级 N 个」出现可点芯片(有 hover/手型)。
2. 点某个下级板块芯片 → 画布平滑居中到该板块 + 其相邻节点,且该节点高亮、右侧详情切过去。
3. 在板块详情里点「上级 报告」芯片 → 平滑回到根附近;点某个下级股票芯片 → 聚焦到该股票及邻居。
4. 孤立/少邻居节点不过度放大(≤1.2x)。
5. 手动滚轮/`+`/`-`/`重置`/`全屏` 仍正常(回归)。

## 影响面

- 改动文件:`webui/static/kronos_desktop_app.js`(新增 1 函数 + 改 `opportunityCanvasRelationSummary` 与
  `renderOpportunityCanvasDetail` 各一处)、`webui/static/kronos_desktop.css`(新增 1 个类)。
- 打包 App 需注意:JS 走 `?v=asset_v`(mtime)强缓存,改动后 mtime 变化即生效;WKWebView 偶发缓存可清。
