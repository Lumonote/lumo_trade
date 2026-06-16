# 投资机会画布 · 关系芯片点击定位 + 自动缩放 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「投资机会画布」右侧「画布关系」里的上级/下级芯片可点击,点击后画布平滑居中并自动缩放到「该节点 + 直接邻居」。

**Architecture:** 纯前端。新增 `focusOpportunityCanvasNode(id)`(求目标节点+相邻节点外接框 → 算 fit 缩放与居中偏移 → 走既有 rAF 缓动 `applyOpportunityCanvasTransform` → `selectOpportunityCanvasNode` 高亮并刷新详情);把 `opportunityCanvasRelationSummary` 的关系条目从 `<span>` 改为带 `data-canvas-focus` 的 `<button>`;在 `renderOpportunityCanvasDetail` 末尾绑定点击。CSS 加 `.canvas-relation-chip` 交互样式。

**Tech Stack:** 原生 JS(canvas 2D)、CSS。无构建步骤;静态文件经 `?v=asset_v`(mtime)缓存,改完即生效。无后端、无 JS 单测框架 —— 本特性以**实跑画布点击**验证。

参考规格:`docs/superpowers/specs/2026-06-16-opportunity-canvas-chip-focus-design.md`

---

## File Structure

- Modify `webui/static/kronos_desktop_app.js`
  - 新增函数 `focusOpportunityCanvasNode(id)`(插入到 `selectOpportunityCanvasNode` 之后,约 line 2685 后)
  - 改 `opportunityCanvasRelationSummary` 内 `itemHtml`(约 line 2779-2783):`<span>` → `<button data-canvas-focus>`
  - 改 `renderOpportunityCanvasDetail`(在已有 `data-canvas-drill-node` 绑定后,约 line 3037 后)新增 focus 绑定
- Modify `webui/static/kronos_desktop.css`
  - 在 `.canvas-detail-chip-list span`(约 line 3873)后新增 `.canvas-relation-chip` 与 `:hover`

---

## Task 1: 新增 `focusOpportunityCanvasNode(id)` 聚焦函数

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`(插入点:`selectOpportunityCanvasNode` 函数结束 `}` 之后,当前约 line 2685)

- [ ] **Step 1: 插入函数**

在 `selectOpportunityCanvasNode(id) { ... }` 之后新增:

```javascript
      // 点击「画布关系」芯片 → 居中并自动缩放到「目标节点 + 直接邻居」外接框。
      function focusOpportunityCanvasNode(id) {
        const c = state.opportunityCanvas;
        const layout = c.layout;
        const viewport = $("#opportunityCanvasViewport");
        if (!layout || !viewport || !id) return;
        const pos = layout.positions.get(id);
        if (!pos) return; // 跨维度/被过滤的节点:静默不动
        stopOpportunityCanvasInertia();
        const ids = opportunityCanvasConnectedIds(layout, id); // 自身 + 相连边的另一端
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        ids.forEach((nid) => {
          const p = layout.positions.get(nid);
          if (!p) return;
          minX = Math.min(minX, p.x);
          minY = Math.min(minY, p.y);
          maxX = Math.max(maxX, p.x + p.width);
          maxY = Math.max(maxY, p.y + p.height);
        });
        if (!Number.isFinite(minX)) { // 无邻居,退化为单节点
          minX = pos.x; minY = pos.y; maxX = pos.x + pos.width; maxY = pos.y + pos.height;
        }
        const boxW = Math.max(1, maxX - minX);
        const boxH = Math.max(1, maxY - minY);
        const rect = viewport.getBoundingClientRect();
        const vw = Math.max(1, rect.width);
        const vh = Math.max(1, rect.height);
        const pad = 80;
        const fitScale = Math.max(0.26, Math.min(1.2,
          Math.min((vw - pad * 2) / boxW, (vh - pad * 2) / boxH)));
        const centerX = minX + boxW / 2;
        const centerY = minY + boxH / 2;
        c.scale = fitScale;
        c.offsetX = Math.round(vw / 2 - centerX * fitScale);
        c.offsetY = Math.round(vh / 2 - centerY * fitScale);
        applyOpportunityCanvasTransform(); // 既有 rAF 缓动 → 平滑动画到位
        selectOpportunityCanvasNode(id);   // 高亮 + 右侧详情切到目标(并重绑芯片)
      }
```

- [ ] **Step 2: 静态自检(无语法错误 / 依赖均存在)**

Run: `node --check webui/static/kronos_desktop_app.js`
Expected: 无输出(退出码 0)。依赖 `opportunityCanvasConnectedIds`、`stopOpportunityCanvasInertia`、`selectOpportunityCanvasNode`、`applyOpportunityCanvasTransform`、`$` 均已在本文件定义。

---

## Task 2: 关系芯片改为可点击按钮 + 绑定点击

**Files:**
- Modify: `webui/static/kronos_desktop_app.js`(`opportunityCanvasRelationSummary` 的 `itemHtml`,约 line 2779;`renderOpportunityCanvasDetail` 末尾,约 line 3037)

- [ ] **Step 1: 关系条目 `<span>` → `<button data-canvas-focus>`**

把 `opportunityCanvasRelationSummary` 内的:

```javascript
        const itemHtml = (ids) => ids.slice(0, 18).map((id) => {
          const related = layout.nodeMap?.get(id);
          if (!related) return "";
          return `<span>${html(related.title || id)}</span>`;
        }).join("");
```

改为:

```javascript
        const itemHtml = (ids) => ids.slice(0, 18).map((id) => {
          const related = layout.nodeMap?.get(id);
          if (!related) return "";
          return `<button type="button" class="canvas-relation-chip" data-canvas-focus="${html(id)}" title="定位到画布">${html(related.title || id)}</button>`;
        }).join("");
```

- [ ] **Step 2: 在详情渲染末尾绑定 focus 点击**

`renderOpportunityCanvasDetail` 里,已有的 `data-canvas-drill-node` 监听块:

```javascript
        detail.querySelector("[data-canvas-drill-node]")?.addEventListener("click", (event) => {
          const id = event.currentTarget.dataset.canvasDrillNode;
          const targetNode = state.opportunityCanvas.layout?.nodeMap?.get(id);
          loadCanvasDrilldown(targetNode, event.currentTarget).catch((error) => alert(error.message));
        });
```

之后(函数闭合 `}` 之前)新增:

```javascript
        detail.querySelectorAll("[data-canvas-focus]").forEach((btn) => {
          btn.addEventListener("click", () => focusOpportunityCanvasNode(btn.dataset.canvasFocus));
        });
```

- [ ] **Step 3: 静态自检**

Run: `node --check webui/static/kronos_desktop_app.js`
Expected: 无输出(退出码 0)。

---

## Task 3: 芯片交互样式

**Files:**
- Modify: `webui/static/kronos_desktop.css`(在 `.canvas-detail-chip-list span { ... }` 块之后,约 line 3873)

- [ ] **Step 1: 新增按钮芯片样式**

在 `.canvas-detail-chip-list span { ... }` 块后插入:

```css
.canvas-detail-chip-list .canvas-relation-chip {
  max-width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 3px 7px;
  background: var(--surface-soft);
  color: var(--ink-2);
  font: inherit;
  font-size: 12px;
  line-height: 1.4;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease, color .15s ease;
}

.canvas-detail-chip-list .canvas-relation-chip:hover {
  border-color: var(--accent, #2f6fdd);
  background: rgba(47, 111, 221, 0.1);
  color: var(--accent, #2f6fdd);
}
```

- [ ] **Step 2: 自检 CSS 已落盘**

Run: `grep -n "canvas-relation-chip" webui/static/kronos_desktop.css`
Expected: 命中 2 行(基础样式 + :hover)。

---

## Task 4: 实跑验证 + 提交

**Files:** 无新增。验证后一次性提交本特性。

- [ ] **Step 1: 启动 webui**

Run(后台):`cd webui && python run.py`(或项目既有启动方式),浏览器开 `http://127.0.0.1:7070/desktop/opportunities`。

- [ ] **Step 2: 视觉/交互验证(逐条对照)**

1. 画布加载后,右侧根「报告」节点详情出现「画布关系 · 下级 N 个」,每个板块名是**可点芯片**(手型 + hover 变色)。
2. 点某个下级板块芯片 → 画布**平滑居中**到该板块及其相邻节点,该节点高亮,右侧详情切到它。
3. 在板块详情点「上级」里的「报告」芯片 → 平滑回到根附近;点某「下级」股票芯片 → 聚焦该股票及邻居。
4. 邻居很少/孤立的节点不被放得过大(≤ 1.2x)。
5. 回归:滚轮缩放、拖拽平移、`+` / `-` / `重置` / `全屏` 仍正常。
6. 控制台无报错。

- [ ] **Step 3: 提交**

```bash
git add webui/static/kronos_desktop_app.js webui/static/kronos_desktop.css
git commit -m "feat(opportunity): 画布关系芯片点击定位 + 居中适配节点及邻居自动缩放

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- 规格「设计 §1 focusOpportunityCanvasNode」→ Task 1 ✓(居中 + 适配节点及邻居 + 1.2x 上限 + 缓动 + 选中)
- 规格「§2 关系芯片可点击」→ Task 2 Step 1 ✓
- 规格「§3 绑定点击」→ Task 2 Step 2 ✓
- 规格「§4 样式」→ Task 3 ✓
- 规格「测试/验证 1–5」→ Task 4 Step 2 ✓(逐条覆盖,含手动缩放回归)
- 规格「非目标」(业务标签 pill 不点 / 不改页签 / 不动后端与重复 ID)→ 计划未触碰,符合 ✓

**2. Placeholder scan:** 无 TBD/TODO;每个改动步骤均含完整代码与确切命令。

**3. Type/名称一致性:** `focusOpportunityCanvasNode`、`data-canvas-focus`、`canvas-relation-chip` 在 Task 1/2/3 间命名一致;依赖函数名(`opportunityCanvasConnectedIds`/`stopOpportunityCanvasInertia`/`selectOpportunityCanvasNode`/`applyOpportunityCanvasTransform`)与源文件现有定义一致。
