# 资金榜单个股点击查看详情 — 设计

日期: 2026-07-16

## 需求

资金榜单（主榜 + 5日/30日窗口聚合表）中的个股支持点击查看详情：点击股票名称打开完整的「个股分析套件」弹窗（`#stockContextModal`，含快照/财务/综合总览/主力周期等 tab），与热点榜、行情台的行为一致。

## 现状

- 股票单元格 `.capital-stock-cell` 带 `klineTargetAttr()` 生成的 `data-kline-target` 属性，点击由 document 级委托处理器打开 K线大图弹窗。
- 整行点击展开/收起行内明细（`toggleCapitalDetail`），处理器已排除 `[data-kline-target]` 内的点击。

## 方案（选定：替换股票名点击为个股分析弹窗）

后端零改动。前端在 `webui/static/kronos_desktop_app.js`（esbuild 压缩产物）**末尾追加**一段代码，沿用既有的「function 重赋值挂钩」模式：

1. **tooltip 修正**：重赋值包装 `capitalTableHtml`，对返回的 HTML 做正则替换，把 `.capital-stock-cell` 开标签内的「点击查看K线大图」改为「点击查看个股详情」。
2. **点击拦截**：document **捕获阶段** 委托监听 `click` 与 `keydown`(Enter/Space)，命中 `.capital-stock-cell[data-kline-target]` 时 `preventDefault + stopPropagation`（阻断原 K线委托处理器与行展开处理器），改调 `openStockContext({stock_code, stock_name})` 打开个股分析套件弹窗。

保留 `data-kline-target` 属性不改名：行展开处理器的排除逻辑继续生效，即使拦截层失效也只回退为原 K线行为，不会误触发行展开。

## 覆盖范围

- 主榜（资金流/龙虎榜两个子 tab）与 5日/30日窗口聚合表均由 `capitalTableHtml` 渲染，一次覆盖。
- 量化雷达 / 吸筹埋伏 tab 已有各自详情入口，不改动。

## 备选方案（未采用）

- 每行加「详情」按钮：零行为变更风险，但多占一列，且与热点榜「点名字看详情」不一致。
- 行内展开明细里加详情链接：入口太深。

## 验证

- `node --check` 语法校验。
- e2e：起 dev 服务，浏览器打开资金榜单页，点击个股单元格，断言 `#stockContextModal` 可见且 K线弹窗未打开；5日/30日聚合表同验。
- 打包 App 需重打包（或清 WKWebView 缓存）后生效。
