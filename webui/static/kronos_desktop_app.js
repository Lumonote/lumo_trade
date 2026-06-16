      const page = document.body.dataset.page;
      const $ = (selector) => document.querySelector(selector);
      const OPPORTUNITY_CLI_DEFAULTS = Object.freeze({
        limit: 100,
        workers: 10,
        source: "multi",
        stock_codes: "",
      });
      const OPPORTUNITY_CANVAS_VIEW_FALLBACK = Object.freeze([
        { id: "hierarchy", label: "层级", description: "报告 → 板块 → 股票 → 分析内容" },
        { id: "score_rank", label: "排名", description: "全部股票按综合评分降序" },
        { id: "sector", label: "板块", description: "按板块聚合股票关系" },
        { id: "business_tag", label: "标签", description: "按概念 / 板块 / 股票等业务标签组织关系" },
        { id: "hot_sector", label: "热门", description: "前十大热门板块全量关系" },
        { id: "funds", label: "资金", description: "按主力净流入维度聚合" },
        { id: "dragon_tiger", label: "龙虎榜", description: "热门板块与龙虎榜命中关系" },
      ]);
      const state = {
        dashboard: null,
        selectedCurve: null,
        selectedStock: null,
        drawPoints: [],
        jobs: [],
        activeJobId: null,
        jobPollTimer: null,
        currentKline: null,
        currentStockContext: null,
        currentSuitePayload: null,
        suiteFetching: false,
        klineModalContext: null,
        klineModalLimit: 240,
        klineLiveTimer: null,
        patternClickTimer: null,
        savedPatterns: [],
        watchlist: [],
        watchlistSet: null,
        notifyData: null,
        notifyCats: null,
        notifyTimer: null,
        _notifyItems: [],
        systemEvents: [],
        lastQueryParams: null,
        lastMatchSnapshot: null,
        opportunityCanvas: {
          scale: 0.86,
          offsetX: 12,
          offsetY: 18,
          activeId: "root",
          view: "hierarchy",
          raw: null,
          dragging: false,
          dragStart: null,
          layout: null,
          bound: false,
          snapshotId: null,
          raf: 0,
          inertiaRaf: 0,
          spacePanning: false,
          viewX: null,
          viewY: null,
          viewScale: null,
          panVelocityX: 0,
          panVelocityY: 0,
          lastPanMove: null,
          nodeDragging: null,
          fitted: false,
          fitOnNextRender: true,
          minimap: null,
          drawRaf: 0,
          hoverId: null,
          textCache: new Map(),
          resizeObserver: null,
          surfaceWidth: 0,
          surfaceHeight: 0,
          gridState: null,
          activeRunId: null,
        },
        opportunityData: {
          tab: "all",
          runs: null,
          activeRunId: null,
          itemsByRun: {},
          search: "",
          sortRuns: { key: "run_at", dir: "desc" },
          sortRunItems: { key: null, dir: null },
          sortPattern: { key: "pattern_score", dir: "desc" },
          patternResult: null,
        },
        hotSectorHistory: {
          snapshots: null,
          summaries: {},
          stocksByBoard: {},
          activeSnapshotId: null,
          activeBoardCode: null,
          sortSnapshots: { key: "created_at", dir: "desc" },
          sortBoards: { key: null, dir: null },
          sortBoardStocks: { key: null, dir: null },
        },
      };

      function html(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[char]);
      }

      function num(value, digits = 2) {
        const n = Number(value);
        return Number.isFinite(n) ? n.toFixed(digits) : "--";
      }

      function parseMaybeJson(value, fallback = {}) {
        if (value && typeof value === "object") return value;
        if (typeof value !== "string" || !value.trim()) return fallback;
        try {
          const parsed = JSON.parse(value);
          return parsed && typeof parsed === "object" ? parsed : fallback;
        } catch (_error) {
          return fallback;
        }
      }

      function formatMoneyText(value, fallback = "--") {
        const n = Number(value);
        if (!Number.isFinite(n)) return fallback || "--";
        const abs = Math.abs(n);
        if (abs >= 100000000) return `${(n / 100000000).toFixed(2)}亿`;
        if (abs >= 10000) return `${(n / 10000).toFixed(2)}万`;
        return n.toFixed(0);
      }

      function changeClass(value) {
        const n = Number(value);
        if (!Number.isFinite(n) || n === 0) return "";
        return n >= 0 ? "change-up" : "change-down";
      }

      function klineChangeClass(openPrice, closePrice) {
        const open = Number(openPrice);
        const close = Number(closePrice);
        if (!Number.isFinite(open) || !Number.isFinite(close) || open === 0) return "";
        return close >= open ? "kline-up" : "kline-down";
      }

      function movingAverage(values, windowSize) {
        const numbers = values.map((value) => Number(value)).filter((value) => Number.isFinite(value));
        return numbers.map((value, index) => {
          if (index + 1 < windowSize) return null;
          const slice = numbers.slice(index + 1 - windowSize, index + 1);
          const avg = slice.reduce((sum, current) => sum + current, 0) / slice.length;
          return Number(avg.toFixed(2));
        });
      }

      function volumeLabel(value) {
        const n = Number(value);
        if (!Number.isFinite(n)) return "--";
        if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
        if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
        return n.toFixed(0);
      }

      function normalizeStockCode(value) {
        const match = String(value || "").toUpperCase().replace(/^(SH|SZ|BJ)/, "").replace(/\.(SH|SZ|BJ)$/, "").match(/\d{6}/);
        return match ? match[0] : "";
      }

      function stockDisplayName(stock = {}) {
        const name = stock.name || stock.stock_name || stock.stockName || "";
        const code = stock.code || stock.stock_code || stock.stockCode || "";
        return name || code || "股票";
      }

      function stockTargetFromDataset(dataset = {}) {
        const code = normalizeStockCode(dataset.stockCode || dataset.stock || dataset.code);
        return {
          type: "stock",
          stock_code: code,
          stock_name: dataset.stockName || dataset.name || "",
          board_name: dataset.sector || dataset.industry || dataset.boardName || "",
        };
      }

      function klineStats(records) {
        if (!records.length) return { high: "--", low: "--", volume: "--", delta: "--" };
        const first = records[0];
        const last = records[records.length - 1];
        const highs = records.map((r) => Number(r.high)).filter((v) => Number.isFinite(v));
        const lows = records.map((r) => Number(r.low)).filter((v) => Number.isFinite(v));
        const volumes = records.map((r) => Number(r.volume)).filter((v) => Number.isFinite(v));
        const delta = first.open ? (((last.close - first.open) / first.open) * 100).toFixed(2) : "--";
        return {
          high: highs.length ? Math.max(...highs).toFixed(2) : "--",
          low: lows.length ? Math.min(...lows).toFixed(2) : "--",
          volume: volumes.length ? volumeLabel(volumes.reduce((sum, value) => sum + value, 0) / volumes.length) : "--",
          delta,
        };
      }

      function klinePivotPoints(records, type = "high", lookback = 2) {
        const key = type === "low" ? "low" : "high";
        const out = [];
        for (let i = lookback; i < records.length - lookback; i += 1) {
          const value = Number(records[i][key]);
          if (!Number.isFinite(value)) continue;
          let isPivot = true;
          for (let j = i - lookback; j <= i + lookback; j += 1) {
            if (j === i) continue;
            const other = Number(records[j][key]);
            if (!Number.isFinite(other)) continue;
            if (type === "low" ? other < value : other > value) {
              isPivot = false;
              break;
            }
          }
          if (isPivot) out.push({ index: i, date: records[i].date, price: value, type });
        }
        return out;
      }

      function klineClusterLevels(points, tolerance) {
        const sorted = [...points].sort((a, b) => a.price - b.price);
        const groups = [];
        sorted.forEach((point) => {
          let group = groups.find((g) => Math.abs(g.price - point.price) <= tolerance);
          if (!group) {
            group = { price: point.price, points: [] };
            groups.push(group);
          }
          group.points.push(point);
          group.price = group.points.reduce((sum, item) => sum + item.price, 0) / group.points.length;
        });
        return groups
          .map((group) => ({
            price: Number(group.price.toFixed(2)),
            touches: group.points.length,
            latestIndex: Math.max(...group.points.map((point) => point.index)),
            type: group.points[0]?.type || "level",
          }))
          .sort((a, b) => (b.touches - a.touches) || (b.latestIndex - a.latestIndex));
      }

      function klineTrendShape(points, records, color, label) {
        const usable = points.filter((point) => point.index >= records.length - 160).slice(-3);
        if (usable.length < 2) return null;
        const a = usable[usable.length - 2];
        const b = usable[usable.length - 1];
        if (b.index <= a.index) return null;
        const slope = (b.price - a.price) / (b.index - a.index);
        const endIndex = records.length - 1;
        const projected = b.price + slope * (endIndex - b.index);
        return {
          shape: {
            type: "line",
            xref: "x",
            yref: "y",
            x0: a.date,
            y0: a.price,
            x1: records[endIndex].date,
            y1: Number(projected.toFixed(2)),
            line: { color, width: 1.4, dash: "dot" },
            layer: "above",
          },
          annotation: {
            x: records[endIndex].date,
            y: Number(projected.toFixed(2)),
            xref: "x",
            yref: "y",
            text: label,
            showarrow: false,
            xanchor: "right",
            yanchor: label === "下降压力" ? "bottom" : "top",
            font: { size: 10, color },
            bgcolor: "rgba(255,255,255,0.78)",
            bordercolor: color,
            borderwidth: 1,
          },
        };
      }

      function buildKlineAutoDrawings(records, mode = "preview") {
        if (!records.length) return { shapes: [], annotations: [] };
        const dates = records.map((r) => r.date);
        const highs = records.map((r) => Number(r.high)).filter(Number.isFinite);
        const lows = records.map((r) => Number(r.low)).filter(Number.isFinite);
        if (!highs.length || !lows.length) return { shapes: [], annotations: [] };
        const lastClose = Number(records[records.length - 1]?.close);
        const high = Math.max(...highs);
        const low = Math.min(...lows);
        const span = Math.max(high - low, 0.01);
        const tolerance = Math.max(span * 0.018, Math.abs(lastClose || high) * 0.006);
        const highPivots = klinePivotPoints(records, "high");
        const lowPivots = klinePivotPoints(records, "low");
        const supports = klineClusterLevels(lowPivots, tolerance)
          .filter((level) => !Number.isFinite(lastClose) || level.price <= lastClose + tolerance)
          .slice(0, mode === "modal" ? 3 : 2);
        const resistances = klineClusterLevels(highPivots, tolerance)
          .filter((level) => !Number.isFinite(lastClose) || level.price >= lastClose - tolerance)
          .slice(0, mode === "modal" ? 3 : 2);
        if (!supports.length && Number.isFinite(low)) supports.push({ price: Number(low.toFixed(2)), touches: 1, latestIndex: 0, type: "low" });
        if (!resistances.length && Number.isFinite(high)) resistances.push({ price: Number(high.toFixed(2)), touches: 1, latestIndex: 0, type: "high" });

        const startDate = dates[0];
        const endDate = dates[dates.length - 1];
        const shapes = [];
        const annotations = [];
        const addLevel = (level, kind, index) => {
          const color = kind === "support" ? "rgba(20, 132, 92, 0.72)" : "rgba(196, 61, 54, 0.72)";
          shapes.push({
            type: "line",
            xref: "x",
            yref: "y",
            x0: startDate,
            y0: level.price,
            x1: endDate,
            y1: level.price,
            line: { color, width: index === 0 ? 1.65 : 1.05, dash: index === 0 ? "solid" : "dash" },
            layer: "below",
          });
          if (mode === "modal" || index === 0) {
            annotations.push({
              x: endDate,
              y: level.price,
              xref: "x",
              yref: "y",
              text: `${kind === "support" ? "支撑" : "压力"} ${level.price}`,
              showarrow: false,
              xanchor: "right",
              yanchor: kind === "support" ? "top" : "bottom",
              font: { size: 10, color },
              bgcolor: "rgba(255,255,255,0.82)",
              bordercolor: color,
              borderwidth: 1,
            });
          }
        };
        supports.forEach((level, index) => addLevel(level, "support", index));
        resistances.forEach((level, index) => addLevel(level, "resistance", index));
        [klineTrendShape(lowPivots, records, "rgba(16, 120, 83, 0.78)", "上升支撑"), klineTrendShape(highPivots, records, "rgba(179, 55, 48, 0.78)", "下降压力")]
          .filter(Boolean)
          .forEach((item) => {
            shapes.push(item.shape);
            if (mode === "modal") annotations.push(item.annotation);
          });
        return { shapes, annotations };
      }

      function klineAxisTitle(limit) {
        if (limit >= 500) return "全部数据";
        return `最近 ${limit} 条`;
      }

      // 统一请求封装：带超时（默认 90s）。本地分析服务卡死/无响应时，AbortController 兜底，
      // 避免前端无限转圈；调用方的 catch 会拿到可操作的错误文案。长耗时调用（AI 深度解读、
      // 形态回测）走原生 fetch 或后台任务轮询，不经过此封装，故不受超时影响。
      async function fetchJson(url, options = {}) {
        const { timeout = 90000, ...fetchOptions } = options || {};
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        try {
          let response;
          try {
            response = await fetch(url, { ...fetchOptions, signal: controller.signal });
          } catch (err) {
            if (err && err.name === "AbortError") {
              throw new Error(`请求超时（${Math.round(timeout / 1000)}秒未响应）：本地分析服务可能未启动或已卡死，请彻底退出（⌘Q）后重新打开 App`);
            }
            throw new Error(`无法连接本地分析服务，请彻底退出（⌘Q）后重新打开 App（${String((err && err.message) || err)}）`);
          }
          const data = await response.json();
          if (!response.ok) {
            throw new Error(data.error || data.message || `HTTP ${response.status}`);
          }
          return data;
        } finally {
          clearTimeout(timer);
        }
      }

      async function loadDashboard() {
        const data = await fetchJson("/api/stock-dashboard");
        state.dashboard = data;
        state.jobs = data.jobs || [];
        updateTaskHeader(state.jobs);
        updateFeatureJobPill(state.jobs);
        scheduleJobPolling(state.jobs);
        $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
        return data;
      }

      function renderReportsDrawer(reports) {
        const list = $("#reportDrawerList");
        if (!list) return;
        list.innerHTML = (reports || []).map((item) => `
          <div class="item item-clickable" role="button" tabindex="0" data-preview-url="${html(item.url || '')}" data-preview-label="${html(item.file || '报告')}">
            <div class="item-top">
              <p class="item-title">${html(item.file)}</p>
              <span class="pill">${html(item.type)}</span>
            </div>
            <p class="item-meta">${html(item.updated_at)} · ${item.size_kb} KB</p>
          </div>
        `).join("");
        if (!reports?.length) empty(list, "暂无报告。在工作台启动机会挖掘 / 批量分析后会生成报告。");
      }

      function renderJobsDrawer(jobs) {
        const list = $("#taskDrawerList");
        if (!list) return;
        list.innerHTML = (jobs || []).map((job) => {
          const resultLinks = jobResultLinks(job);
          return `
            <div class="item job-item" data-job-id="${html(job.id)}">
              <div class="item-top">
                <p class="item-title">${html(jobTypeLabel(job))} · ${html(job.id)}</p>
                <span class="pill ${jobPillClass(job.status)}">${html(jobStatusLabel(job.status))}</span>
              </div>
              <p class="item-meta">${html(jobCreatedAt(job) || "--")} · ${html(latestJobLog(job) || "暂无日志")}</p>
              ${resultLinks ? `<div class="job-result-row">${resultLinks}</div>` : ""}
            </div>
          `;
        }).join("");
        if (!jobs?.length) empty(list, "暂无任务。");
      }

      function opportunityDataSummary(text) {
        const target = $("#opportunityDataSummary");
        if (target) target.textContent = text || "";
      }

      function opportunityDataItemRow(item, index, options = {}) {
        const code = stockCodeFromItem(item);
        const rank = item.score_rank || item.item_rank || item.rank || index + 1;
        const score = item.score ?? item.total_score;
        const name = item.stock_name || item.name || code || "--";
        const sector = item.sector || item.industry || item.source || "--";
        const reason = item.reason || item.summary || item.hot_sector_rank_summary || "";
        return `
          <button class="item opportunity-data-row" type="button"
                  data-stock="${html(code)}"
                  data-stock-code="${html(code)}"
                  data-stock-name="${html(name)}"
                  data-sector="${html(sector)}"
                  data-search="${html(name)} ${html(code)} ${html(sector)}">
            <div class="item-top">
              <p class="item-title">#${html(rank)} ${html(name)} <span class="muted">${html(code)}</span></p>
              <strong>${score != null ? num(score) : "--"}</strong>
            </div>
            <p class="item-meta">${html(sector)}${reason ? ` · ${html(reason)}` : ""}${options.history ? ` · ${html(item.rating || "")}` : ""}</p>
          </button>
        `;
      }

      function bindOpportunityDataStockClicks(container) {
        container?.querySelectorAll("[data-stock]").forEach((el) => {
          if (el.dataset.bound) return;
          el.dataset.bound = "1";
          el.addEventListener("click", async () => {
            loadKline(el.dataset.stock, el.dataset.stockName || "");
            await openStockContext(stockTargetFromDataset(el.dataset));
          });
          el.addEventListener("dblclick", (event) => {
            event.preventDefault();
            openStockKlineModal(el.dataset.stock, 240, { stockName: el.dataset.stockName || "" }).catch((error) => alert(error.message));
          });
        });
      }

      function applyOpportunityDataSearch() {
        const body = $("#opportunityDataBody");
        if (!body) return;
        const q = (state.opportunityData.search || "").trim().toLowerCase();
        const hint = $("#opportunityDataSearchHint");
        let total = 0;
        let shown = 0;
        // 表格化后,可过滤单元是表体里的 <tr>(否则整张表会被当作一个 body 子节点整体隐藏);
        // 无表格时退回按 body 直接子节点过滤(卡片/占位等)。
        const tableRows = body.querySelectorAll("table.sortable-data-table tbody tr");
        const units = tableRows.length ? Array.from(tableRows) : Array.from(body.children);
        units.forEach((row) => {
          if (row.classList.contains("opp-no-filter")) return;
          total += 1;
          if (!q) {
            row.hidden = false;
            shown += 1;
            return;
          }
          const hay = (row.dataset.search || row.textContent || "").toLowerCase();
          const match = hay.includes(q);
          row.hidden = !match;
          if (match) shown += 1;
        });
        if (hint) hint.textContent = q ? `匹配 ${shown}/${total} 条` : "";
      }

      function renderOpportunityAllData() {
        const body = $("#opportunityDataBody");
        if (!body) return;
        const items = state.dashboard?.opportunity?.items || [];
        opportunityDataSummary(`全部数据 ${items.length} 条 · 当前总览仅显示前 10 条，画布使用全量数据。`);
        body.innerHTML = items.map((item, index) => opportunityDataItemRow(item, index)).join("");
        if (!items.length) empty(body, "暂无机会数据。");
        bindOpportunityDataStockClicks(body);
        applyOpportunityDataSearch();
      }

      async function loadOpportunityRuns() {
        if (Array.isArray(state.opportunityData.runs)) return state.opportunityData.runs;
        const payload = await fetchJson("/api/opportunity-runs?limit=80");
        state.opportunityData.runs = payload.runs || [];
        return state.opportunityData.runs;
      }

      async function loadOpportunityRunItems(runId) {
        if (!runId) return [];
        if (state.opportunityData.itemsByRun[runId]) return state.opportunityData.itemsByRun[runId];
        const payload = await fetchJson(`/api/opportunity-runs/${encodeURIComponent(runId)}/items`);
        const rows = (payload.items || []).map((row) => ({
          ...row,
          stock_code: row.code,
          stock_name: row.name,
          score: row.total_score,
          score_rank: row.item_rank,
        }));
        state.opportunityData.itemsByRun[runId] = rows;
        return rows;
      }

      // ===== 通用可排序表格(历史/板块四层共用)=====
      // 据 sortedCapitalRows 的纯算法新建;资金榜单链路完全不改(回归隔离 D1)。
      function sortRows(rows, key, dir, valueFor) {
        const factor = dir === "asc" ? 1 : -1;
        const isEmpty = (v) => v == null || v === "" || (typeof v === "number" && !Number.isFinite(v));
        const decorated = (rows || []).map((row, i) => {
          const raw = typeof valueFor === "function" ? valueFor(row, key) : row[key];
          const n = Number(raw);
          return { row, i, raw, isNum: !isEmpty(raw) && Number.isFinite(n), n, empty: isEmpty(raw) };
        });
        decorated.sort((a, b) => {
          if (a.empty && b.empty) return a.i - b.i;
          if (a.empty) return 1;     // 缺失值恒沉底,与方向无关
          if (b.empty) return -1;
          let cmp;
          if (a.isNum && b.isNum) cmp = a.n - b.n;
          else cmp = String(a.raw).localeCompare(String(b.raw), "zh-Hans-CN", { numeric: true });
          if (cmp !== 0) return cmp * factor;
          return a.i - b.i;          // 同值稳定(原序)
        });
        return decorated.map((d) => d.row);
      }

      // spec = { columns, sortState, sortAttr?, tableClass?, rowAttrs?, emptyText? }
      // columns[i] = { key, label, sortable=true, cell(row), value(row)?, className? }
      function sortableTableHtml(rows, spec) {
        const cols = spec.columns || [];
        const sortAttr = spec.sortAttr || "sort-key";
        const sort = spec.sortState || {};
        const valueFor = (row, key) => {
          const col = cols.find((c) => c.key === key);
          if (col && typeof col.value === "function") return col.value(row);
          return Object.prototype.hasOwnProperty.call(row, key) ? row[key] : undefined;
        };
        let viewRows = rows || [];
        if (sort.key && cols.some((c) => c.key === sort.key)) {
          viewRows = sortRows(viewRows, sort.key, sort.dir, valueFor);
        }
        const th = cols.map((col) => {
          const label = html(col.label != null ? col.label : col.key);
          const extra = col.className ? ` ${col.className}` : "";
          if (col.sortable === false) return `<th class="${html(col.className || "")}">${label}</th>`;
          const active = sort.key === col.key;
          const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "";
          return `<th class="sortable-col${active ? " sorted" : ""}${extra}" data-${sortAttr}="${html(col.key)}" title="点击按此列排序">${label}<span class="sort-arrow">${arrow}</span></th>`;
        }).join("");
        const tableClass = spec.tableClass || "sortable-data-table";
        if (!viewRows.length) {
          return `<div class="sortable-table-wrap"><table class="${tableClass}"><thead><tr>${th}</tr></thead><tbody><tr class="opp-no-filter"><td colspan="${cols.length}" class="sortable-empty">${html(spec.emptyText || "暂无数据")}</td></tr></tbody></table></div>`;
        }
        const tr = viewRows.map((row) => {
          const attrs = (typeof spec.rowAttrs === "function" ? spec.rowAttrs(row) : "") || "";
          const tds = cols.map((col) => {
            const cls = col.className ? ` class="${html(col.className)}"` : "";
            const content = typeof col.cell === "function" ? col.cell(row) : html(row[col.key]);
            return `<td${cls}>${content}</td>`;
          }).join("");
          return `<tr ${attrs}>${tds}</tr>`;
        }).join("");
        return `<div class="sortable-table-wrap"><table class="${tableClass}"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
      }

      // 三态表头:不同 key→降序;同 key 降→升;同 key 升→清空(恢复原序)。
      function bindSortableHeaders(container, sortState, rerender, sortAttr = "sort-key") {
        if (!container) return;
        const dataKey = sortAttr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
        container.querySelectorAll(`[data-${sortAttr}]`).forEach((thEl) => {
          thEl.addEventListener("click", () => {
            const key = thEl.dataset[dataKey];
            if (!key) return;
            if (sortState.key !== key) { sortState.key = key; sortState.dir = "desc"; }
            else if (sortState.dir === "desc") { sortState.dir = "asc"; }
            else { sortState.key = null; sortState.dir = null; }
            rerender();
          });
        });
      }

      function opportunityRunRow(run) {
        const count = run.item_count ?? run.analyzed ?? "--";
        const source = run.source || "--";
        return `
          <div class="item opportunity-run-row">
            <div class="item-top">
              <p class="item-title">${html(run.run_at || run.created_at || "--")}</p>
              <span class="pill">${html(count)}条</span>
            </div>
            <p class="item-meta">${html(run.report_file || "未记录报告")} · 来源 ${html(source)} · ${html(run.mode || "--")}</p>
            <div class="actions">
              <button class="button secondary compact" type="button" data-opportunity-run="${html(run.id || "")}">查看全部</button>
            </div>
          </div>
        `;
      }

      async function renderOpportunityHistoryData(runId = null) {
        const body = $("#opportunityDataBody");
        if (!body) return;
        opportunityDataSummary("读取历史数据...");
        body.innerHTML = "";
        try {
          const runs = await loadOpportunityRuns();
          if (!runs.length) {
            opportunityDataSummary("暂无历史 run。");
            empty(body, "暂无历史机会挖掘数据。");
            return;
          }
          const activeRunId = runId || state.opportunityData.activeRunId;
          if (!activeRunId) {
            opportunityDataSummary(`历史数据 ${runs.length} 次 run · 点击表格行打开某次全量股票。`);
            const sortState = state.opportunityData.sortRuns;
            const renderTable = () => {
              body.innerHTML = sortableTableHtml(runs, {
                sortState,
                tableClass: "sortable-data-table opportunity-run-table",
                emptyText: "暂无历史机会挖掘数据。",
                rowAttrs: (run) => `class="opp-run-row" data-opportunity-run="${html(run.id || "")}" data-search="${html(run.run_at || "")} ${html(run.source || "")} ${html(run.report_file || "")}" role="button" tabindex="0"`,
                columns: [
                  { key: "run_at", label: "时间", className: "col-left", cell: (r) => `<span class="cell-strong">${html(r.run_at || r.created_at || "--")}</span>`, value: (r) => r.run_at || r.created_at },
                  { key: "item_count", label: "条数", cell: (r) => html(r.item_count ?? r.analyzed ?? "--"), value: (r) => r.item_count ?? r.analyzed },
                  { key: "source", label: "来源", className: "col-left", cell: (r) => html(zhLabel("source", r.source) || "--"), value: (r) => r.source },
                  { key: "mode", label: "模式", className: "col-left", cell: (r) => html(zhLabel("strategy", r.mode) || "--"), value: (r) => r.mode },
                  { key: "report_file", label: "报告", className: "col-left", cell: (r) => `<span class="cell-sub">${html(r.report_file || "未记录")}</span>`, value: (r) => r.report_file },
                  { key: "_action", label: "操作", sortable: false, cell: () => `<button class="button secondary compact" type="button">查看全部</button>` },
                ],
              });
              bindSortableHeaders(body.querySelector("table"), sortState, renderTable);
              body.querySelectorAll("[data-opportunity-run]").forEach((row) => {
                row.addEventListener("click", () => {
                  const id = row.dataset.opportunityRun;
                  if (!id) return;
                  state.opportunityData.activeRunId = id;
                  renderOpportunityHistoryData(id).catch((error) => alert(error.message));
                });
              });
              applyOpportunityDataSearch();
            };
            renderTable();
            return;
          }
          const activeRun = runs.find((run) => String(run.id) === String(activeRunId));
          const items = await loadOpportunityRunItems(activeRunId);
          opportunityDataSummary(`历史 run ${activeRun?.run_at || activeRunId} · 全部数据 ${items.length} 条`);
          // 评分维度为动态列(不同 run 的 scores key 可能不同):取当前数据并集
          const scoreKeys = [];
          const seenScore = new Set();
          items.forEach((it) => {
            const sc = parseMaybeJson(it.scores_json || it.scores, {});
            Object.keys(sc || {}).forEach((k) => {
              if (!seenScore.has(k)) { seenScore.add(k); scoreKeys.push(k); }
            });
          });
          const sg = (r) => parseMaybeJson(r.signals_json || r.signals, {});
          const sigCell = (k, suf = "") => (r) => {
            const v = sg(r)[k];
            return v == null || v === "" ? "--" : num(v, k === "rsi" ? 1 : 2) + suf;
          };
          const sigVal = (k) => (r) => { const v = Number(sg(r)[k]); return Number.isFinite(v) ? v : null; };
          const sortState = state.opportunityData.sortRunItems;
          const renderTable = () => {
            const back = `<button class="button secondary compact opp-no-filter opportunity-history-back" type="button">返回历史列表</button>`;
            if (!items.length) {
              body.innerHTML = back + `<div class="item empty-state opp-no-filter"><p class="item-meta">这次 run 没有入库股票明细。</p></div>`;
            } else {
              body.innerHTML = back + sortableTableHtml(items, {
                sortState,
                tableClass: "sortable-data-table opportunity-run-items-table",
                rowAttrs: (r) => {
                  const code = r.code || r.stock_code || "";
                  const name = r.stock_name || r.name || "";
                  return `data-stock="${html(code)}" data-stock-code="${html(code)}" data-stock-name="${html(name)}" data-sector="${html(r.sector || "")}" data-search="${html(name)} ${html(code)} ${html(r.sector || "")}" role="button" tabindex="0"`;
                },
                columns: [
                  { key: "rank", label: "名次", cell: (r) => `#${html(r.score_rank || r.item_rank || r.rank || "--")}`, value: (r) => r.score_rank || r.item_rank || r.rank },
                  { key: "name", label: "名称·代码", className: "col-left", cell: (r) => `<span class="cell-strong">${html(r.stock_name || r.name || r.code || "--")}</span> <span class="cell-sub">${html(r.code || "")}</span>`, value: (r) => r.stock_name || r.name || r.code },
                  { key: "score", label: "综合分", cell: (r) => { const s = r.score ?? r.total_score; return s != null ? `<span class="cell-strong">${num(s)}</span>` : "--"; }, value: (r) => r.score ?? r.total_score },
                  { key: "rating", label: "评级", cell: (r) => html(r.rating || "--"), value: (r) => r.rating },
                  { key: "change_pct", label: "涨跌幅", cell: (r) => r.change_pct != null ? `<span class="${changeClass(r.change_pct)}">${num(r.change_pct)}%</span>` : "--", value: (r) => r.change_pct },
                  ...scoreKeys.map((k) => ({
                    key: `score_${k}`,
                    label: zhLabel("score", k),
                    cell: (r) => { const v = parseMaybeJson(r.scores_json || r.scores, {})[k]; return v == null || v === "" ? "--" : num(v, 1); },
                    value: (r) => { const v = Number(parseMaybeJson(r.scores_json || r.scores, {})[k]); return Number.isFinite(v) ? v : null; },
                  })),
                  { key: "sig_chase", label: zhLabel("signal", "chase"), cell: sigCell("chase"), value: sigVal("chase") },
                  { key: "sig_rsi", label: "RSI", cell: sigCell("rsi"), value: sigVal("rsi") },
                  { key: "sig_change_3d", label: zhLabel("signal", "change_3d"), cell: sigCell("change_3d", "%"), value: sigVal("change_3d") },
                  { key: "sig_sell", label: zhLabel("signal", "sell_signals"), cell: sigCell("sell_signals"), value: sigVal("sell_signals") },
                  { key: "degraded", label: "降级", cell: (r) => r.degraded ? `<span class="cell-sub">降级</span>` : "", value: (r) => r.degraded ? 1 : 0 },
                ],
              });
            }
            body.querySelector(".opportunity-history-back")?.addEventListener("click", () => {
              state.opportunityData.activeRunId = null;
              renderOpportunityHistoryData().catch((error) => alert(error.message));
            });
            if (items.length) bindSortableHeaders(body.querySelector("table"), sortState, renderTable);
            bindOpportunityDataStockClicks(body);
            applyOpportunityDataSearch();
          };
          renderTable();
        } catch (error) {
          opportunityDataSummary("历史数据读取失败");
          empty(body, `历史数据读取失败：${error.message}`);
        }
      }

      async function renderOpportunitySectorsData() {
        const body = $("#opportunityDataBody");
        if (!body) return;
        opportunityDataSummary("读取热门板块快照...");
        body.innerHTML = "";
        try {
          const snapshots = await loadHotSectorSnapshots();
          if (!snapshots.length) {
            opportunityDataSummary("暂无热门板块快照。");
            empty(body, "暂无热门板块快照。先运行一次机会挖掘或热门板块扫描。");
            return;
          }
          const activeSnapshotId = state.hotSectorHistory.activeSnapshotId;
          if (!activeSnapshotId) {
            opportunityDataSummary(`热门板块 ${snapshots.length} 个快照 · 点击表格行查看板块排名。`);
            const sortState = state.hotSectorHistory.sortSnapshots;
            const renderTable = () => {
              body.innerHTML = sortableTableHtml(snapshots, {
                sortState,
                tableClass: "sortable-data-table hot-sector-snapshot-table",
                emptyText: "暂无热门板块快照。",
                rowAttrs: (s) => `data-hot-sector-snapshot="${html(s.id || "")}" data-search="${html(s.created_at || "")} ${html(s.trade_date || "")} ${html(s.source || "")}" role="button" tabindex="0"`,
                columns: [
                  { key: "created_at", label: "快照时间", className: "col-left", cell: (s) => `<span class="cell-strong">${html(s.created_at || "--")}</span>`, value: (s) => s.created_at },
                  { key: "trade_date", label: "交易日", className: "col-left", cell: (s) => html(s.trade_date || "--"), value: (s) => s.trade_date },
                  { key: "board_count", label: "板块数", cell: (s) => html(s.board_count ?? 0), value: (s) => s.board_count },
                  { key: "stock_count", label: "股票数", cell: (s) => html(s.stock_count ?? 0), value: (s) => s.stock_count },
                  { key: "relation_count", label: "关联数", cell: (s) => html(s.relation_count ?? 0), value: (s) => s.relation_count },
                  { key: "source", label: "来源", className: "col-left", cell: (s) => html(zhLabel("source", s.source) || "--"), value: (s) => s.source },
                ],
              });
              bindSortableHeaders(body.querySelector("table"), sortState, renderTable);
              body.querySelectorAll("[data-hot-sector-snapshot]").forEach((row) => {
                row.addEventListener("click", () => {
                  state.hotSectorHistory.activeSnapshotId = row.dataset.hotSectorSnapshot;
                  state.hotSectorHistory.activeBoardCode = null;
                  renderOpportunitySectorsData().catch((error) => alert(error.message));
                });
              });
              applyOpportunityDataSearch();
            };
            renderTable();
            return;
          }
          const summary = await loadHotSectorSummary(activeSnapshotId);
          const boards = summary?.boards || [];
          const activeBoardCode = state.hotSectorHistory.activeBoardCode;
          if (!activeBoardCode) {
            opportunityDataSummary(`快照 ${summary?.snapshot?.created_at || activeSnapshotId} · ${boards.length} 个板块`);
            const sortState = state.hotSectorHistory.sortBoards;
            const renderTable = () => {
              const back = `<button class="button secondary compact opp-no-filter opportunity-sector-back" type="button">返回快照列表</button>`;
              if (!boards.length) {
                body.innerHTML = back + `<div class="item empty-state opp-no-filter"><p class="item-meta">该快照没有板块明细。</p></div>`;
              } else {
                body.innerHTML = back + sortableTableHtml(boards, {
                  sortState,
                  tableClass: "sortable-data-table hot-sector-board-table",
                  rowAttrs: (b) => { const code = b.board_code || b.code || ""; return `data-hot-sector-board="${html(code)}" data-search="${html(b.board_name || b.name || "")} ${html(code)} ${html(b.board_type || "")}" role="button" tabindex="0"`; },
                  columns: [
                    { key: "board_rank", label: "名次", cell: (b) => `#${html(b.board_rank ?? "--")}`, value: (b) => b.board_rank },
                    { key: "board_name", label: "板块名", className: "col-left", cell: (b) => `<span class="cell-strong">${html(b.board_name || b.name || b.board_code || "--")}</span>`, value: (b) => b.board_name || b.name },
                    { key: "change_pct", label: "涨跌幅", cell: (b) => { const p = Number(b.change_pct); return Number.isFinite(p) ? `<span class="${changeClass(p)}">${p >= 0 ? "+" : ""}${num(p)}%</span>` : "--"; }, value: (b) => b.change_pct },
                    { key: "board_type", label: "类型", className: "col-left", cell: (b) => html(b.board_type || "--"), value: (b) => b.board_type },
                    { key: "main_net_inflow", label: "主力净流入", cell: (b) => html(formatMoneyText(b.main_net_inflow, b.main_net_inflow_text)), value: (b) => b.main_net_inflow },
                    { key: "stock_count", label: "股票数", cell: (b) => html(b.stock_count ?? 0), value: (b) => b.stock_count },
                    { key: "relation_count", label: "关联数", cell: (b) => html(b.relation_count ?? 0), value: (b) => b.relation_count },
                  ],
                });
              }
              body.querySelector(".opportunity-sector-back")?.addEventListener("click", () => {
                state.hotSectorHistory.activeSnapshotId = null;
                renderOpportunitySectorsData().catch((error) => alert(error.message));
              });
              if (boards.length) bindSortableHeaders(body.querySelector("table"), sortState, renderTable);
              body.querySelectorAll("[data-hot-sector-board]").forEach((row) => {
                row.addEventListener("click", () => {
                  state.hotSectorHistory.activeBoardCode = row.dataset.hotSectorBoard;
                  renderOpportunitySectorsData().catch((error) => alert(error.message));
                });
              });
              applyOpportunityDataSearch();
            };
            renderTable();
            return;
          }
          const payload = await loadHotSectorBoardStocks(activeSnapshotId, activeBoardCode);
          const stocks = payload.stocks || [];
          const board = boards.find((b) => String(b.board_code) === String(activeBoardCode));
          opportunityDataSummary(`${board?.board_name || activeBoardCode} · ${stocks.length} 条${payload.has_more ? " · 还有更多" : ""}`);
          const sortState = state.hotSectorHistory.sortBoardStocks;
          const renderTable = () => {
            const back = `<button class="button secondary compact opp-no-filter opportunity-sector-back" type="button">返回板块排名</button>`;
            if (!stocks.length) {
              body.innerHTML = back + `<div class="item empty-state opp-no-filter"><p class="item-meta">该板块暂无成分股明细。</p></div>`;
            } else {
              body.innerHTML = back + sortableTableHtml(stocks, {
                sortState,
                tableClass: "sortable-data-table hot-sector-stock-table",
                rowAttrs: (s) => `data-stock-code="${html(s.code || "")}" data-stock-name="${html(s.name || "")}" data-search="${html(s.name || "")} ${html(s.code || "")}" role="button" tabindex="0"`,
                columns: [
                  { key: "stock_rank", label: "名次", cell: (s) => `#${html(s.stock_rank ?? "--")}`, value: (s) => s.stock_rank },
                  { key: "name", label: "名称·代码", className: "col-left", cell: (s) => `<span class="cell-strong">${html(s.name || s.code || "--")}</span> <span class="cell-sub">${html(s.code || "")}</span>`, value: (s) => s.name || s.code },
                  { key: "change_pct", label: "涨跌幅", cell: (s) => { const p = Number(s.change_pct); return Number.isFinite(p) ? `<span class="${changeClass(p)}">${p >= 0 ? "+" : ""}${num(p)}%</span>` : "--"; }, value: (s) => s.change_pct },
                  { key: "main_net_inflow", label: "主力净流入", cell: (s) => html(s.main_net_inflow_text || formatMoneyText(s.main_net_inflow, "--")), value: (s) => s.main_net_inflow },
                  { key: "candidate_rank", label: "候选排名", cell: (s) => html(s.candidate_rank ?? "--"), value: (s) => s.candidate_rank },
                  { key: "price", label: "最新价", cell: (s) => s.price != null ? html(s.price) : "--", value: (s) => s.price },
                  { key: "lhb", label: "龙虎榜命中", className: "col-left", cell: (s) => s.lhb_trade_date ? html(`${s.lhb_trade_date} 净买 ${formatMoneyText(s.lhb_net_amount, "--")}${s.lhb_reason ? " · " + s.lhb_reason : ""}`) : `<span class="cell-sub">未命中</span>`, value: (s) => s.lhb_trade_date || "" },
                ],
              });
            }
            body.querySelector(".opportunity-sector-back")?.addEventListener("click", () => {
              state.hotSectorHistory.activeBoardCode = null;
              renderOpportunitySectorsData().catch((error) => alert(error.message));
            });
            if (stocks.length) bindSortableHeaders(body.querySelector("table"), sortState, renderTable);
            bindHotStockClicks(body);
            applyOpportunityDataSearch();
          };
          renderTable();
        } catch (error) {
          opportunityDataSummary("热门板块读取失败");
          empty(body, `热门板块读取失败：${error.message}`);
        }
      }

      // 机会挖掘形态回测(item H):对当前/选定 run 的 Top-N 股票做形态自回测打分。
      async function renderOpportunityPatternBacktest() {
        const body = $("#opportunityDataBody");
        if (!body) return;
        const runId = state.opportunityCanvas.activeRunId || null;
        const cached = state.opportunityData.patternResult;

        const renderResult = (result) => {
          const rows = (result && result.rows) || [];
          const sortState = state.opportunityData.sortPattern;
          const meta = result?.run
            ? `形态回测 · ${html(result.run.date || result.run.run_at || "")} · 扫描 ${result.scanned}/${result.total} 只 · 窗口 ${result.window_days || "--"}日`
            : "形态回测";
          opportunityDataSummary(meta);
          const draw = () => {
            const head = `<button class="button compact opp-no-filter opp-pattern-run" type="button">重新回测</button>
              <p class="item-meta opp-no-filter">形态评分 = 该股最近形态在自身历史相似片段的 10 日胜率;收益为相似形态后 10 日平均收益。仅供研究参考。</p>`;
            body.innerHTML = head + sortableTableHtml(rows, {
              sortState,
              tableClass: "sortable-data-table opportunity-pattern-table",
              emptyText: "无回测结果。",
              rowAttrs: (r) => `data-stock="${html(r.code || "")}" data-stock-code="${html(r.code || "")}" data-stock-name="${html(r.name || "")}" data-search="${html(r.name || "")} ${html(r.code || "")}" role="button" tabindex="0"`,
              columns: [
                { key: "name", label: "名称·代码", className: "col-left", cell: (r) => `<span class="cell-strong">${html(r.name || r.code || "--")}</span> <span class="cell-sub">${html(r.code || "")}</span>`, value: (r) => r.name || r.code },
                { key: "total_score", label: "综合分", cell: (r) => r.total_score != null ? num(r.total_score) : "--", value: (r) => r.total_score },
                { key: "rating", label: "评级", cell: (r) => html(r.rating || "--"), value: (r) => r.rating },
                { key: "pattern_score", label: "形态评分", cell: (r) => r.pattern_score != null ? `<span class="cell-strong">${num(r.pattern_score, 1)}</span>` : `<span class="cell-sub">${html(r.note || "--")}</span>`, value: (r) => r.pattern_score },
                { key: "win_rate", label: "10日胜率", cell: (r) => r.win_rate != null ? `${num(r.win_rate * 100, 1)}%` : "--", value: (r) => r.win_rate },
                { key: "avg_return", label: "10日平均收益", cell: (r) => r.avg_return != null ? `<span class="${changeClass(r.avg_return)}">${num(r.avg_return * 100, 2)}%</span>` : "--", value: (r) => r.avg_return },
                { key: "sample_count", label: "样本数", cell: (r) => html(r.sample_count ?? 0), value: (r) => r.sample_count },
              ],
            });
            body.querySelector(".opp-pattern-run")?.addEventListener("click", () => runPatternBacktest());
            bindSortableHeaders(body.querySelector("table"), sortState, draw);
            bindOpportunityDataStockClicks(body);
            applyOpportunityDataSearch();
          };
          draw();
        };

        const runPatternBacktest = async () => {
          opportunityDataSummary("形态回测中…(联网拉取日线,约 10–40 秒)");
          body.innerHTML = `<p class="item-meta opp-no-filter"><span class="spinner"></span> 正在对 Top 股票联网回测形态,请稍候…</p>`;
          try {
            const start = await fetchJson("/api/opportunity/pattern-backtest", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ run_id: runId ? Number(runId) : undefined, top_n: 20 }),
            });
            const jobId = start.job_id || start.job?.id;
            if (!jobId) throw new Error("回测任务创建失败");
            const job = await pollJob(jobId, {
              intervalMs: 2000,
              maxAttempts: 90,
              onUpdate: (j) => { const log = latestJobLog(j); if (log) opportunityDataSummary(log); },
            });
            if (!job || job.status === "failed") {
              body.innerHTML = `<p class="notice status error opp-no-filter">形态回测失败：${html(job?.error || "超时,请重试")}</p>`;
              return;
            }
            state.opportunityData.patternResult = job.result || {};
            renderResult(state.opportunityData.patternResult);
          } catch (error) {
            body.innerHTML = `<p class="notice status error opp-no-filter">${html(error.message)}</p>`;
          }
        };

        if (cached && cached.rows) {
          renderResult(cached);
          return;
        }
        opportunityDataSummary("形态回测:基于个股形态打分并展示历史收益率");
        body.innerHTML = `
          <div class="opp-no-filter" style="padding:8px 2px;">
            <button class="button opp-pattern-run" type="button">运行形态回测</button>
            <p class="item-meta">对当前选定挖掘 run 的 Top 20 股票联网回测:用每只票最近形态在自身历史里找相似片段,统计后续 10 日胜率与平均收益作为「形态评分」。</p>
          </div>`;
        body.querySelector(".opp-pattern-run")?.addEventListener("click", () => runPatternBacktest());
      }

      function setOpportunityDataTab(tab) {
        const valid = ["all", "history", "sectors", "pattern"];
        state.opportunityData.tab = valid.includes(tab) ? tab : "all";
        document.querySelectorAll("[data-opportunity-data-tab]").forEach((btn) => {
          const active = btn.dataset.opportunityDataTab === state.opportunityData.tab;
          btn.classList.toggle("active", active);
          btn.setAttribute("aria-selected", active ? "true" : "false");
        });
        state.opportunityData.search = "";
        const searchInput = $("#opportunityDataSearch");
        if (searchInput) searchInput.value = "";
        const hint = $("#opportunityDataSearchHint");
        if (hint) hint.textContent = "";
        if (state.opportunityData.tab === "history") {
          renderOpportunityHistoryData().catch((error) => alert(error.message));
        } else if (state.opportunityData.tab === "sectors") {
          renderOpportunitySectorsData().catch((error) => alert(error.message));
        } else if (state.opportunityData.tab === "pattern") {
          renderOpportunityPatternBacktest().catch((error) => alert(error.message));
        } else {
          renderOpportunityAllData();
        }
      }

      function renderOpportunityDataDrawer() {
        setOpportunityDataTab(state.opportunityData.tab || "all");
      }

      function opportunityAnalysisCard(item, index) {
        const code = stockCodeFromItem(item);
        const rank = item.score_rank || item.item_rank || item.rank || index + 1;
        const score = item.score ?? item.total_score;
        const name = item.stock_name || item.name || code || "--";
        const source = item.sector || item.industry || item.source_detail || item.source || "--";
        const scores = parseMaybeJson(item.scores_json || item.scores, {});
        const signals = parseMaybeJson(item.signals_json || item.signals, {});
        const scoreBits = Object.entries(scores || {})
          .slice(0, 8)
          .map(([key, value]) => `<span>${html(key)} <strong>${num(value)}</strong></span>`)
          .join("");
        const signalBits = [
          ["追高风险", signals.chase],
          ["RSI", signals.rsi],
          ["1日", signals.day_change],
          ["3日", signals.change_3d],
          ["5日", signals.change_5d],
          ["卖出信号", signals.sell_signals],
        ]
          .filter(([, value]) => value != null && value !== "")
          .map(([label, value]) => `<span>${html(label)} <strong>${num(value)}</strong></span>`)
          .join("");
        const reason = item.reason || item.summary || item.hot_sector_rank_summary || "";
        return `
          <article class="item opportunity-analysis-card"
                   data-stock="${html(code)}"
                   data-stock-code="${html(code)}"
                   data-stock-name="${html(name)}"
                   data-sector="${html(source)}"
                   data-search="${html(name)} ${html(code)} ${html(source)}"
                   role="button"
                   tabindex="0">
            <div class="item-top">
              <p class="item-title">#${html(rank)} ${html(name)} <span class="muted">${html(code)}</span></p>
              <strong>${score != null ? num(score) : "--"}</strong>
            </div>
            <p class="item-meta">${html(source)} · ${html(item.rating || "--")}${item.change_pct != null ? ` · 涨跌 ${num(item.change_pct)}%` : ""}${item.degraded ? " · 数据降级" : ""}</p>
            ${reason ? `<p class="opportunity-analysis-text">${html(reason)}</p>` : ""}
            ${scoreBits ? `<div class="analysis-mini-grid">${scoreBits}</div>` : ""}
            ${signalBits ? `<div class="analysis-mini-grid muted-grid">${signalBits}</div>` : ""}
          </article>
        `;
      }

      async function loadHotSectorSnapshots() {
        if (Array.isArray(state.hotSectorHistory.snapshots)) return state.hotSectorHistory.snapshots;
        const payload = await fetchJson("/api/hot-sector-snapshots?limit=80");
        state.hotSectorHistory.snapshots = payload.snapshots || [];
        return state.hotSectorHistory.snapshots;
      }

      async function loadHotSectorSummary(snapshotId) {
        if (!snapshotId) return null;
        if (state.hotSectorHistory.summaries[snapshotId]) return state.hotSectorHistory.summaries[snapshotId];
        const payload = await fetchJson(`/api/hot-sector-snapshot?snapshot_id=${encodeURIComponent(snapshotId)}`);
        state.hotSectorHistory.summaries[snapshotId] = payload;
        return payload;
      }

      async function loadHotSectorBoardStocks(snapshotId, boardCode) {
        if (!snapshotId || !boardCode) return { stocks: [], relations: [] };
        const key = `${snapshotId}:${boardCode}`;
        if (state.hotSectorHistory.stocksByBoard[key]) return state.hotSectorHistory.stocksByBoard[key];
        const payload = await fetchJson(`/api/hot-sector-snapshot/${encodeURIComponent(snapshotId)}/stocks?board_code=${encodeURIComponent(boardCode)}&limit=1000`);
        state.hotSectorHistory.stocksByBoard[key] = payload;
        return payload;
      }

      function hotSectorSnapshotRow(snapshot, activeId) {
        const id = String(snapshot.id || "");
        const active = String(activeId || "") === id ? " active" : "";
        return `
          <button class="item hot-sector-snapshot-row${active}" type="button" data-hot-sector-snapshot="${html(id)}">
            <div class="item-top">
              <p class="item-title">${html(snapshot.created_at || "--")}</p>
              <span class="pill">${html(snapshot.board_count ?? 0)}板块</span>
            </div>
            <p class="item-meta">${html(snapshot.trade_date || "交易日未记录")} · 股票 ${html(snapshot.stock_count ?? 0)} · 关联 ${html(snapshot.relation_count ?? 0)} · ${html(snapshot.source || "--")}</p>
          </button>
        `;
      }

      function hotSectorBoardHistoryRow(board, activeCode) {
        const code = board.board_code || board.code || "";
        const active = String(activeCode || "") === String(code) ? " active" : "";
        const inflow = formatMoneyText(board.main_net_inflow, board.main_net_inflow_text);
        const pct = Number(board.change_pct || 0);
        return `
          <button class="item hot-sector-board-row${active}" type="button" data-hot-sector-board="${html(code)}">
            <div class="item-top">
              <p class="item-title">#${html(board.board_rank || "--")} ${html(board.board_name || board.name || code)}</p>
              <strong class="${changeClass(pct)}">${pct >= 0 ? "+" : ""}${num(pct)}%</strong>
            </div>
            <p class="item-meta">${html(board.board_type || "--")} · 主力净流入 ${html(inflow)} · 股票 ${html(board.stock_count ?? 0)} · 关联 ${html(board.relation_count ?? 0)}</p>
          </button>
        `;
      }

      function hotSectorStockAnalysisCard(stock, index) {
        const code = stock.code || "";
        const pct = Number(stock.change_pct || 0);
        const inflow = stock.main_net_inflow_text || formatMoneyText(stock.main_net_inflow, "");
        const lhb = stock.lhb_trade_date
          ? `龙虎榜 ${html(stock.lhb_trade_date)} · 净买 ${html(formatMoneyText(stock.lhb_net_amount, "--"))}${stock.lhb_reason ? ` · ${html(stock.lhb_reason)}` : ""}`
          : "未命中龙虎榜";
        return `
          <article class="item opportunity-analysis-card hot-sector-stock-card"
                   data-stock-code="${html(code)}"
                   data-stock-name="${html(stock.name || "")}"
                   data-search="${html(stock.name || "")} ${html(code)}"
                   role="button"
                   tabindex="0">
            <div class="item-top">
              <p class="item-title">#${html(stock.stock_rank || index + 1)} ${html(stock.name || code)} <span class="muted">${html(code)}</span></p>
              <strong class="${changeClass(pct)}">${pct >= 0 ? "+" : ""}${num(pct)}%</strong>
            </div>
            <p class="item-meta">候选排名 ${html(stock.candidate_rank || "--")} · 主力净流入 ${html(inflow || "--")} · 最新价 ${stock.price != null ? html(stock.price) : "--"}</p>
            <p class="opportunity-analysis-text">${lhb}</p>
          </article>
        `;
      }

      function renderOpportunitiesPage(data) {
        state.opportunityData.runs = null;
        state.opportunityData.activeRunId = null;
        state.hotSectorHistory.snapshots = null;
        state.hotSectorHistory.activeSnapshotId = null;
        state.hotSectorHistory.activeBoardCode = null;
        setupWorkbench(data);
        renderOpportunities(data);
      }

      function hotStockRow(s, i) {
        const pct = Number(s.change_pct || 0);
        const cls = pct >= 0 ? "hot-up" : "hot-down";
        const sub = s.main_net_inflow_text ? `主力 ${html(s.main_net_inflow_text)}` : (s.price != null ? `¥${html(s.price)}` : "");
        return `
          <div class="item hot-rank-row item-clickable" data-stock-code="${html(s.code || '')}" data-stock-name="${html(s.name || '')}" role="button" tabindex="0" title="点击查看个股">
            <span class="hot-rank-no">${i + 1}</span>
            <div style="flex:1;min-width:0;">
              <p class="item-title">${html(s.name)} <span class="muted">${html(s.code || '')}</span></p>
              <p class="item-meta">${sub}</p>
            </div>
            <strong class="${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</strong>
          </div>
        `;
      }

      function hotBoardRow(b, i) {
        const pct = Number(b.change_pct || 0);
        const cls = pct >= 0 ? "hot-up" : "hot-down";
        return `
          <div class="item hot-rank-row">
            <span class="hot-rank-no">${i + 1}</span>
            <div style="flex:1;min-width:0;">
              <p class="item-title">${html(b.name)}</p>
              <p class="item-meta">主力净流入 ${html(b.main_net_inflow_text || '--')}</p>
            </div>
            <strong class="${cls}">${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%</strong>
          </div>
        `;
      }

      function bindHotStockClicks(container) {
        if (!container) return;
        container.querySelectorAll("[data-stock-code]").forEach((el) => {
          el.addEventListener("click", () => {
            const code = el.dataset.stockCode;
            if (!code) return;
            openStockContext({
              type: "stock",
              stock_code: code,
              stock_name: el.dataset.stockName || "",
              board_name: "",
            }).catch((error) => console.warn("打开个股失败", error));
          });
          el.addEventListener("dblclick", (event) => {
            event.preventDefault();
            const code = el.dataset.stockCode;
            if (!code) return;
            openStockKlineModal(code, 240, { stockName: el.dataset.stockName || "" }).catch((error) => alert(error.message));
          });
        });
      }

      function renderHotTopics(intel) {
        const em = (intel && intel.eastmoney) || {};
        const concept = $("#hotConceptList");
        if (concept) {
          const boards = em.concept_boards || [];
          concept.innerHTML = boards.map((b, i) => hotBoardRow(b, i)).join("");
          if (!boards.length) empty(concept, "板块数据暂不可用（检查网络 / 稍后刷新）。");
        }
        const gainers = $("#hotGainersList");
        if (gainers) {
          const rows = em.top_gainers || [];
          gainers.innerHTML = rows.map((s, i) => hotStockRow(s, i)).join("");
          if (!rows.length) empty(gainers, "涨幅榜暂不可用。");
          bindHotStockClicks(gainers);
        }
        const hot = $("#hotStocksList");
        if (hot) {
          const rows = em.hot_stocks || [];
          hot.innerHTML = rows.map((s, i) => hotStockRow(s, i)).join("");
          if (!rows.length) empty(hot, "个股热度暂不可用。");
          bindHotStockClicks(hot);
        }
        const flash = $("#hotFlashList");
        if (flash) {
          const items = (intel && intel.jinshi) || [];
          flash.innerHTML = items.map((n) => `
            <div class="item">
              <div class="item-top">
                <p class="item-title">${html(n.title)}</p>
                ${n.important ? `<span class="pill warn">重要</span>` : ""}
              </div>
              <p class="item-meta">${html(n.source || "金十")} · ${html(n.time || "")}</p>
            </div>
          `).join("");
          if (!items.length) empty(flash, "快讯暂不可用。");
        }
      }

      function renderOverviewHotLists(data) {
        const intel = (data && data.market && data.market.intelligence) || {};
        const em = intel.eastmoney || {};
        const eastmoney = $("#ovHotEastmoney");
        if (eastmoney) {
          const rows = em.hot_stocks || [];
          eastmoney.innerHTML = rows.map((s, i) => hotStockRow(s, i)).join("");
          if (!rows.length) empty(eastmoney, "东方财富热榜暂不可用（检查网络 / 稍后刷新）。");
          bindHotStockClicks(eastmoney);
        }
      }

      function renderNewsPanel(el, items, fallbackSource, emptyText) {
        if (!el) return;
        const rows = items || [];
        el.innerHTML = rows.map((n) => `
          <div class="item" title="${html(n.summary || n.title || "")}">
            <div class="item-top">
              <p class="item-title">${html(n.title)}</p>
            </div>
            <p class="item-meta">${html(n.source || fallbackSource)} · ${html(n.time || "")}</p>
          </div>
        `).join("");
        if (!rows.length) empty(el, emptyText);
      }

      function renderOverviewNews(data) {
        const intel = (data && data.market && data.market.intelligence) || {};
        renderNewsPanel($("#ovEastmoneyNews"), intel.eastmoney_news, "东方财富", "东财资讯暂不可用（检查网络 / 稍后刷新）。");
        renderNewsPanel($("#ovFutuNews"), intel.ths_news, "同花顺", "同花顺电报暂不可用（检查网络 / 稍后刷新）。");
      }

      function setupOverviewSearch() {
        const input = $("#overviewStockInput");
        const btn = $("#overviewStockSearchBtn");
        const suggest = $("#overviewStockSuggest");
        if (!input || !btn || !suggest || btn.dataset.bound) return;
        btn.dataset.bound = "1";
        const run = async () => {
          const q = input.value.trim();
          if (!q) return;
          try {
            const data = await fetchJson(`/api/pattern-search/stocks?q=${encodeURIComponent(q)}&limit=8`);
            const stocks = data.stocks || [];
            suggest.innerHTML = stocks.map((item) => `
              <button class="item" type="button" data-stock-code="${html(item.stock_code)}" data-stock-name="${html(item.stock_name || "")}" data-sector="${html(item.industry || "")}" title="查看个股分析">
                <div class="item-top">
                  <p class="item-title">${html(item.stock_name || item.stock_code)}</p>
                  <span class="pill">${html(item.stock_code)}</span>
                </div>
                <p class="item-meta">${html(item.market || "--")} · ${html(item.industry || "--")}</p>
              </button>
            `).join("");
            if (!stocks.length) empty(suggest, "没有匹配股票。");
            bindHotStockClicks(suggest);
          } catch (error) {
            empty(suggest, "搜索失败：" + (error?.message || error));
          }
        };
        btn.addEventListener("click", run);
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") { event.preventDefault(); run(); }
        });
      }

      function marketCornerItemHtml(item, index) {
        const pct = Number(item.change_pct || 0);
        const pctText = Number.isFinite(pct) ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "--";
        const meta = item.meta ? `<span class="market-corner-meta">${html(item.meta)}</span>` : "";
        return `
          <span class="market-corner-item" data-market-corner-idx="${index}">
            <span class="market-corner-kind">${html(item.kind)}</span>
            <strong>${html(item.name || "--")}</strong>
            ${item.value ? `<span>${html(item.value)}</span>` : ""}
            <span class="${changeClass(pct)}">${pctText}</span>
            ${meta}
          </span>
        `;
      }

      function renderMarketCornerTicker(market = {}) {
        const box = $("#marketCornerTicker");
        const track = $("#marketCornerTrack");
        if (!box || !track) return;
        const em = market.intelligence?.eastmoney || {};
        const items = [];
        (market.indices || []).filter((item) => item.available !== false).slice(0, 5).forEach((item) => {
          items.push({
            kind: "指数",
            name: item.name,
            value: item.price != null ? num(item.price) : "",
            change_pct: item.change_pct,
            meta: item.code,
          });
        });
        [...(em.industry_boards || []), ...(em.concept_boards || [])].slice(0, 12).forEach((board) => {
          items.push({
            kind: board.type || "板块",
            name: board.name,
            value: board.main_net_inflow_text ? `主力 ${board.main_net_inflow_text}` : "",
            change_pct: board.change_pct,
            meta: board.code || board.board_code || "",
          });
        });
        if (!items.length) {
          box.hidden = true;
          return;
        }
        const single = items.map(marketCornerItemHtml).join("");
        track.innerHTML = single + single;
        track.style.setProperty("--market-corner-dur", `${Math.min(160, Math.max(34, items.length * 4)).toFixed(0)}s`);
        const time = $("#marketCornerTime");
        if (time) time.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        box.hidden = false;
      }

      function setupDrawers() {
        const openDrawer = (id) => {
          const d = $("#" + id);
          if (!d) return;
          d.hidden = false;
          void d.offsetWidth;
          d.classList.add("open");
          d.setAttribute("aria-hidden", "false");
        };
        const closeDrawer = (d) => {
          if (!d) return;
          d.classList.remove("open");
          d.setAttribute("aria-hidden", "true");
          window.setTimeout(() => { d.hidden = true; }, 220);
        };
        $("#openReportDrawerBtn")?.addEventListener("click", async () => {
          openDrawer("reportDrawer");
          try { if (!state.dashboard) await loadDashboard(); } catch (error) { console.warn(error); }
          renderReportsDrawer(state.dashboard?.reports || []);
        });
        $("#openTaskDrawerBtn")?.addEventListener("click", async () => {
          openDrawer("taskDrawer");
          renderJobsDrawer(state.jobs || []);
          try { await loadJobs(); } catch (error) { console.warn(error); }
        });
        document.querySelectorAll(".opportunity-data-menu-btn").forEach((btn) => {
          btn.addEventListener("click", async () => {
            const target = btn.dataset.opportunityDataTabTarget;
            if (target) state.opportunityData.tab = target;
            openDrawer("opportunityDataDrawer");
            try { if (!state.dashboard) await loadDashboard(); } catch (error) { console.warn(error); }
            renderOpportunityDataDrawer();
          });
        });
        document.querySelectorAll("[data-opportunity-data-tab]").forEach((btn) => {
          btn.addEventListener("click", () => setOpportunityDataTab(btn.dataset.opportunityDataTab));
        });
        $("#opportunityDataSearch")?.addEventListener("input", (event) => {
          state.opportunityData.search = event.target.value || "";
          applyOpportunityDataSearch();
        });
        document.querySelectorAll("[data-drawer-close]").forEach((btn) => {
          btn.addEventListener("click", () => closeDrawer($("#" + btn.dataset.drawerClose)));
        });
        document.querySelectorAll(".drawer-backdrop").forEach((d) => {
          d.addEventListener("click", (event) => { if (event.target === d) closeDrawer(d); });
        });
        document.addEventListener("keydown", (event) => {
          if (event.key === "Escape") {
            document.querySelectorAll(".drawer-backdrop:not([hidden])").forEach(closeDrawer);
          }
        });
      }

      function renderDashboardPage(data) {
        renderMarketCornerTicker(data.market || {});
        if (page === "overview") {
          renderOverview(data);
          return;
        }
        if (page === "workbench") {
          setupWorkbench(data);
          renderOpportunities(data);
          renderReports(data);
          renderHotTopics(data.market?.intelligence);
          bindKlineInteractions();
          return;
        }
        if (page === "reports") {
          renderReports(data);
          return;
        }
        if (page === "features") {
          renderFeatureOverview(data);
          bindKlineInteractions();
          return;
        }
        if (page === "opportunities") {
          renderOpportunitiesPage(data);
        }
      }

      async function refreshCurrentView() {
        const button = $("#refreshBtn");
        if (button) button.disabled = true;
        try {
          if (["overview", "workbench", "reports", "features", "opportunities"].includes(page)) {
            const data = await loadDashboard();
            renderDashboardPage(data);
            return;
          }
          if (page === "patterns") {
            await loadPatternStatus();
            $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
            return;
          }
          if (page === "settings") {
            await Promise.all([loadSettings(), loadKronosStatus()]);
            $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
            return;
          }
          if (page === "watchlist") {
            await Promise.all([refreshWatchlist(), refreshNotifyData()]);
            $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
            return;
          }
          if (page === "capital_rankings") {
            await loadCapitalRankings();
            $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
            return;
          }
          if (page === "paper_trading") {
            await loadPaperTrading();
            return;
          }
          if (page === "command_center") {
            await loadCommandCenter();
            return;
          }
          await loadJobs();
        } finally {
          if (button) button.disabled = false;
        }
      }

      function empty(target, text = "暂无数据", actionsHtml = "") {
        if (!target) return;
        target.innerHTML = `
          <div class="item empty-state">
            <p class="item-meta">${html(text)}</p>
            ${actionsHtml ? `<div class="actions empty-actions">${actionsHtml}</div>` : ""}
          </div>
        `;
      }

      function emptyAction(action, label, extraAttrs = "") {
        return `<button class="button secondary" type="button" data-action="${html(action)}" ${extraAttrs}>${html(label)}</button>`;
      }

      document.addEventListener("click", (event) => {
        const previewEl = event.target.closest("[data-preview-url]");
        if (!previewEl) return;
        event.preventDefault();
        event.stopPropagation();
        const url = previewEl.dataset.previewUrl;
        const label = previewEl.dataset.previewLabel || "预览";
        if (url) openFilePreview(url, label);
      });

      document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const previewEl = event.target.closest?.("[data-preview-url]");
        if (!previewEl) return;
        if (event.target.closest("input, textarea, select")) return;
        event.preventDefault();
        const url = previewEl.dataset.previewUrl;
        const label = previewEl.dataset.previewLabel || "预览";
        if (url) openFilePreview(url, label);
      });

      document.addEventListener("click", (event) => {
        const actionEl = event.target.closest("[data-action]");
        if (!actionEl) return;
        const action = actionEl.dataset.action;
        if (action === "start-opportunity") {
          startOpportunityFromContext(actionEl).catch((error) => alert(error.message));
        }
        if (action === "start-batch") {
          startBatchFromContext(actionEl).catch((error) => alert(error.message));
        }
      });

      document.addEventListener("click", (event) => {
        const target = event.target.closest("[data-kline-target]");
        if (!target) return;
        if (event.target.closest("a, button, input, textarea, select, [data-stock-action], [data-action]")) {
          return;
        }
        const code = normalizeStockCode(target.dataset.klineTarget);
        if (!code) return;
        event.preventDefault();
        event.stopPropagation();
        openStockKlineModal(code, 240, { stockName: target.dataset.stockName || "" }).catch((error) => alert(error.message));
      });

      document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const target = event.target.closest?.("[data-kline-target]");
        if (!target) return;
        if (event.target.closest("a, button, input, textarea, select")) return;
        const code = normalizeStockCode(target.dataset.klineTarget);
        if (!code) return;
        event.preventDefault();
        openStockKlineModal(code, 240, { stockName: target.dataset.stockName || "" }).catch((error) => alert(error.message));
      });

      function klineTargetAttr(code, name = "") {
        const normalized = normalizeStockCode(code);
        if (!normalized) return "";
        const tip = name ? `${name} ${normalized} 点击查看K线大图` : `${normalized} 点击查看K线大图`;
        return `data-kline-target="${html(normalized)}" data-stock-name="${html(name || "")}" role="button" tabindex="0" title="${html(tip)}"`;
      }

      function renderOverview(data) {
        const market = data.market || {};
        const opportunity = data.opportunity || {};
        const primary = market.primary_index || {};
        $("#marketIndex").textContent = primary.available ? num(primary.price) : "--";
        $("#marketIndexMeta").innerHTML = primary.available
          ? `<span class="${changeClass(primary.change_pct)}">${num(primary.change_pct)}%</span> · ${html(primary.name)}`
          : "指数接口暂不可用";
        $("#monitoredCount").textContent = market.monitored_count ?? "--";
        $("#particleCount").textContent = `市场粒子 ${market.total_particles ?? "--"}`;
        $("#opportunityCount").textContent = opportunity.stats?.total ?? 0;
        $("#opportunityStats").textContent = `强机会 ${opportunity.stats?.strong_count ?? 0} · 最高 ${num(opportunity.stats?.top_score)}`;

        const indexList = $("#indexList");
        if (indexList) {
          indexList.innerHTML = (market.indices || []).map((item) => `
            <div class="item">
              <div class="item-top">
                <p class="item-title">${html(item.name)}</p>
                <span class="pill ${item.available ? "ok" : "warn"}">${item.available ? "在线" : "不可用"}</span>
              </div>
              <p class="item-meta">${html(item.code)} · ${item.available ? num(item.price) : "--"} · <span class="${changeClass(item.change_pct)}">${item.available ? num(item.change_pct) + "%" : "--"}</span></p>
            </div>
          `).join("");
          if (!market.indices?.length) empty(indexList);
        }

        const topMovers = $("#topMovers");
        topMovers.innerHTML = (market.top_movers || []).map((item) => `
          <button class="item" type="button" data-stock-code="${html(item.code || "")}" data-stock-name="${html(item.name || "")}" data-sector="${html(item.sector || "")}">
            <div class="item-top">
              <p class="item-title">${html(item.name || item.code)}</p>
              <strong class="${changeClass(item.change)}">${num(item.change)}%</strong>
            </div>
            <p class="item-meta">${html(item.code)} · ${html(item.sector)} · ${num(item.price)}</p>
          </button>
        `).join("");
        if (!market.top_movers?.length) empty(topMovers);
        topMovers.querySelectorAll("[data-stock-code]").forEach((el) => {
          el.addEventListener("click", () => openStockContext(stockTargetFromDataset(el.dataset)));
          el.addEventListener("dblclick", (event) => {
            event.preventDefault();
            openStockKlineModal(el.dataset.stockCode, 240, { stockName: el.dataset.stockName || "" }).catch((error) => alert(error.message));
          });
        });

        const news = $("#marketNews");
        const newsItems = market.intelligence?.sina_news || market.news || [];
        news.innerHTML = newsItems.slice(0, 8).map((item) => `
          <div class="item">
            <div class="item-top">
              <p class="item-title">${html(item.title || item.tag || "市场信息")}</p>
              <span class="pill">${html(item.time || item.tag || "news")}</span>
            </div>
            ${item.url ? `<a class="item-meta" href="${html(item.url)}" target="_blank" rel="noreferrer">查看来源</a>` : ""}
          </div>
        `).join("");
        if (!newsItems.length) empty(news);

        const sectors = $("#sectorList");
        sectors.innerHTML = (market.sectors || []).map((item) => {
          const leader = item.leader || null;
          const leaderHtml = leader
            ? `<span class="sector-leader" ${klineTargetAttr(leader.code, leader.name)}>${html(leader.name || leader.code || "--")}</span> ${num(leader.change)}%`
            : "--";
          const meta = item.main_net_inflow_text
            ? `主力净流入 ${html(item.main_net_inflow_text)}`
            : `监控 ${item.monitored_count || 0} · 龙头 ${leaderHtml}`;
          return `
          <div class="item" data-sector="${html(item.name || "")}">
            <div class="item-top">
              <p class="item-title">${html(item.name)}</p>
              <strong class="${changeClass(item.avg_change)}">${num(item.avg_change)}%</strong>
            </div>
            <p class="item-meta">${meta}</p>
          </div>
        `;
        }).join("");
        if (!market.sectors?.length) empty(sectors);
      }

      function stockCodeFromItem(item) {
        return item.stock_code || item.code || item.symbol || "";
      }

      function opportunityCanvasViews(canvas) {
        const views = Array.isArray(canvas?.views) && canvas.views.length
          ? canvas.views
          : OPPORTUNITY_CANVAS_VIEW_FALLBACK;
        return views.filter((view) => view && view.id && view.label);
      }

      function opportunityCanvasViewLabel(canvas, viewId) {
        return (opportunityCanvasViews(canvas).find((view) => view.id === viewId) || {}).label || "层级";
      }

      function cloneOpportunityCanvasNode(node, overrides = {}) {
        return {
          ...(node || {}),
          tags: Array.isArray(node?.tags) ? [...node.tags] : [],
          analysis: Array.isArray(node?.analysis) ? node.analysis.map((item) => ({ ...item })) : [],
          ...overrides,
        };
      }

      function opportunityCanvasRoot(canvas, subtitle) {
        const root = (canvas?.nodes || []).find((node) => node.id === "root") || {
          id: "root",
          type: "root",
          title: "投资机会分析",
          subtitle: "",
          detail: "",
          tags: [],
        };
        return cloneOpportunityCanvasNode(root, {
          subtitle: subtitle || root.subtitle || "",
        });
      }

      function baseOpportunityCanvas(canvas) {
        return canvas || {
          title: "投资机会分析",
          subtitle: "暂无机会挖掘报告",
          nodes: [],
          edges: [],
          stats: {},
          views: OPPORTUNITY_CANVAS_VIEW_FALLBACK,
        };
      }

      function sectorOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const keepTypes = new Set(["root", "sector", "stock", "hot_sector", "hot_board"]);
        const nodes = (base.nodes || [])
          .filter((node) => keepTypes.has(node.type))
          .map((node) => node.id === "root"
            ? opportunityCanvasRoot(base, "板块维度 · 聚合股票与热门板块")
            : cloneOpportunityCanvasNode(node));
        const ids = new Set(nodes.map((node) => node.id));
        const edges = (base.edges || []).filter((edge) => ids.has(edge.from) && ids.has(edge.to));
        return {
          ...base,
          view: "sector",
          subtitle: "板块维度",
          nodes,
          edges,
        };
      }

      function scoreRankOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const root = opportunityCanvasRoot(base, "排名维度 · 全部股票按综合分排序");
        const stocks = (base.nodes || [])
          .filter((node) => node.type === "stock")
          .map((node) => cloneOpportunityCanvasNode(node))
          .sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
        const group = {
          id: "score-rank-all-stocks",
          type: "sector",
          level: 1,
          title: "全部股票排行",
          subtitle: `${stocks.length}只 · 按综合评分降序`,
          detail: "当前机会挖掘 run 的全量股票，按综合评分从高到低排列。",
          tags: ["全量", "分数排序"],
          count: stocks.length,
          top_score: stocks.length ? Number(stocks[0].score || 0) : 0,
        };
        const nodes = [root, group];
        const edges = [{ from: "root", to: group.id, relation: "score_rank_group" }];
        stocks.forEach((stock, index) => {
          const rank = stock.score_rank || stock.report_rank || index + 1;
          nodes.push(cloneOpportunityCanvasNode(stock, {
            level: 2,
            subtitle: `全量#${rank} · 板块#${stock.sector_rank || "--"} · ${stock.rating || "评分"} · ${num(stock.score)}`,
            tags: [`全量#${rank}`, stock.rating || "评分", stock.sector || "板块"].filter(Boolean).slice(0, 4),
          }));
          edges.push({ from: group.id, to: stock.id, relation: "score_rank_stock" });
        });
        return {
          ...base,
          view: "score_rank",
          subtitle: "排名维度",
          nodes,
          edges,
          stats: {
            ...(base.stats || {}),
            stocks: stocks.length,
          },
        };
      }

      function hotBoardCanvasNodes(canvas) {
        return (canvas?.nodes || []).filter((node) => node.type === "hot_board");
      }

      function businessTagOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const sectors = (base.nodes || []).filter((node) => node.type === "sector");
        const stocks = (base.nodes || []).filter((node) => node.type === "stock");
        const hotBoards = hotBoardCanvasNodes(base);
        const lhbBoards = hotBoards.filter((node) => Number(node.relation_count || 0) > 0);
        const fundBoards = hotBoards.filter((node) => Number.isFinite(Number(node.main_net_inflow)));
        const root = opportunityCanvasRoot(base, "标签维度 · 概念 / 板块 / 股票 / 资金 / 龙虎榜");
        const nodes = [root];
        const edges = [];
        const groups = [
          {
            id: "business-tag-sector",
            title: "板块",
            subtitle: `${sectors.length}个报告板块`,
            detail: "机会挖掘报告解析出的所属板块，用于查看板块到股票的关系。",
            tags: ["业务标签", "板块"],
            children: sectors,
          },
          {
            id: "business-tag-stock",
            title: "股票",
            subtitle: `${stocks.length}只候选股票`,
            detail: "机会挖掘报告中的候选股票，可继续打开个股分析、K线和完整分析内容。",
            tags: ["业务标签", "股票"],
            children: stocks,
          },
          {
            id: "business-tag-concept",
            title: "概念 / 热门板块",
            subtitle: `${hotBoards.length}个热门板块`,
            detail: "前十大热门行业 / 概念板块快照，记录板块排名、资金和成分股关系。",
            tags: ["业务标签", "概念"],
            children: hotBoards,
          },
          {
            id: "business-tag-funds",
            title: "资金",
            subtitle: `${fundBoards.length}个板块有资金字段`,
            detail: "按主力净流入字段连接热门板块，便于继续展开成分股资金排名。",
            tags: ["业务标签", "资金"],
            children: fundBoards,
          },
          {
            id: "business-tag-lhb",
            title: "龙虎榜",
            subtitle: `${lhbBoards.length}个板块命中`,
            detail: "命中龙虎榜的热门板块关系，点击板块可继续展开命中股票和买卖资金。",
            tags: ["业务标签", "龙虎榜"],
            children: lhbBoards,
          },
        ].filter((group) => group.children.length);
        groups.forEach((group, index) => {
          nodes.push({
            id: group.id,
            type: "tag",
            level: 1,
            title: group.title,
            subtitle: group.subtitle,
            detail: group.detail,
            tags: group.tags,
            entity_kind: group.title,
            analysis: group.children.slice(0, 16).map((child) => ({
              label: child.title || child.stock_name || child.board_code || "节点",
              value: child.subtitle || child.detail || "",
            })),
          });
          edges.push({ from: "root", to: group.id, relation: "business_tag" });
          group.children.slice(0, group.id === "business-tag-stock" ? 80 : 40).forEach((child) => {
            const childId = `${group.id}-${child.id}`;
            nodes.push(cloneOpportunityCanvasNode(child, {
              id: childId,
              source_node_id: child.id,
              level: 2,
              tags: [group.title, ...(child.tags || [])].slice(0, 4),
            }));
            edges.push({ from: group.id, to: childId, relation: `business_tag_${index + 1}` });
          });
        });
        return {
          ...base,
          view: "business_tag",
          subtitle: "业务标签维度",
          nodes,
          edges,
          stats: {
            ...(base.stats || {}),
            business_tags: groups.length,
            stocks: stocks.length,
          },
        };
      }

      function hotSectorOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const root = opportunityCanvasRoot(base, "热门板块维度 · 前十大板块全量快照");
        const hotRoot = (base.nodes || []).find((node) => node.id === "hot-sector-root");
        const boards = hotBoardCanvasNodes(base);
        const nodes = [root];
        const edges = [];
        if (hotRoot) {
          nodes.push(cloneOpportunityCanvasNode(hotRoot, { level: 1 }));
          edges.push({ from: "root", to: hotRoot.id, relation: "hot_sector_snapshot" });
        }
        boards.forEach((board) => {
          nodes.push(cloneOpportunityCanvasNode(board, { level: 2 }));
          edges.push({ from: hotRoot?.id || "root", to: board.id, relation: "hot_sector_board" });
        });
        return {
          ...base,
          view: "hot_sector",
          subtitle: "热门板块维度",
          nodes,
          edges,
        };
      }

      function fundsOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const root = opportunityCanvasRoot(base, "资金维度 · 按主力净流入聚合板块");
        const boards = hotBoardCanvasNodes(base)
          .map((node) => cloneOpportunityCanvasNode(node))
          .sort((a, b) => Number(b.main_net_inflow || 0) - Number(a.main_net_inflow || 0));
        const groups = [
          {
            id: "funds-inflow",
            title: "主力净流入",
            test: (node) => Number(node.main_net_inflow || 0) > 0,
            tags: ["资金维度", "净流入"],
          },
          {
            id: "funds-outflow",
            title: "主力净流出",
            test: (node) => Number(node.main_net_inflow || 0) < 0,
            tags: ["资金维度", "净流出"],
          },
          {
            id: "funds-unknown",
            title: "资金待确认",
            test: (node) => !Number.isFinite(Number(node.main_net_inflow)),
            tags: ["资金维度", "待确认"],
          },
        ];
        const nodes = [root];
        const edges = [];
        groups.forEach((group) => {
          const matched = boards.filter(group.test);
          if (!matched.length) return;
          nodes.push({
            id: group.id,
            type: "hot_sector",
            level: 1,
            title: group.title,
            subtitle: `${matched.length}个热门板块`,
            detail: `${group.title} 下包含 ${matched.length} 个热门板块。`,
            tags: group.tags,
          });
          edges.push({ from: "root", to: group.id, relation: "fund_group" });
          matched.forEach((board) => {
            const inflow = Number(board.main_net_inflow);
            nodes.push(cloneOpportunityCanvasNode(board, {
              level: 2,
              subtitle: `#${board.board_rank || "--"} · 主力 ${Number.isFinite(inflow) ? volumeLabel(inflow) : "--"} · 龙虎榜 ${board.relation_count || 0}`,
              tags: ["资金", ...(board.tags || [])].slice(0, 4),
            }));
            edges.push({ from: group.id, to: board.id, relation: "fund_to_board" });
          });
        });
        return {
          ...base,
          view: "funds",
          subtitle: "资金维度",
          nodes,
          edges,
        };
      }

      function dragonTigerOpportunityCanvasView(canvas) {
        const base = baseOpportunityCanvas(canvas);
        const root = opportunityCanvasRoot(base, "龙虎榜维度 · 热门板块命中关系");
        const boards = hotBoardCanvasNodes(base)
          .filter((node) => Number(node.relation_count || 0) > 0)
          .sort((a, b) => Number(b.relation_count || 0) - Number(a.relation_count || 0));
        const group = {
          id: "dragon-tiger-relations",
          type: "hot_sector",
          level: 1,
          title: "龙虎榜命中",
          subtitle: `${boards.length}个热门板块`,
          detail: "展示热门板块与龙虎榜命中记录的关联关系，点击板块可继续展开成分股和命中明细。",
          tags: ["龙虎榜", "关系维度"],
          drilldown: (base.nodes || []).find((node) => node.id === "hot-sector-root")?.drilldown,
        };
        const nodes = [root, group];
        const edges = [{ from: "root", to: group.id, relation: "dragon_tiger_group" }];
        boards.forEach((board) => {
          nodes.push(cloneOpportunityCanvasNode(board, {
            level: 2,
            subtitle: `#${board.board_rank || "--"} · 龙虎榜 ${board.relation_count || 0}条 · ${board.stock_count || 0}只`,
            tags: ["龙虎榜", ...(board.tags || [])].slice(0, 4),
          }));
          edges.push({ from: group.id, to: board.id, relation: "dragon_tiger_to_board" });
        });
        return {
          ...base,
          view: "dragon_tiger",
          subtitle: "龙虎榜维度",
          nodes,
          edges,
        };
      }

      function opportunityCanvasViewPayload(canvas, viewId) {
        const base = baseOpportunityCanvas(canvas);
        if (viewId === "score_rank" || viewId === "rank") return scoreRankOpportunityCanvasView(base);
        if (viewId === "sector") return sectorOpportunityCanvasView(base);
        if (viewId === "business_tag" || viewId === "tag") return businessTagOpportunityCanvasView(base);
        if (viewId === "hot_sector") return hotSectorOpportunityCanvasView(base);
        if (viewId === "funds") return fundsOpportunityCanvasView(base);
        if (viewId === "dragon_tiger") return dragonTigerOpportunityCanvasView(base);
        return {
          ...base,
          view: "hierarchy",
          nodes: (base.nodes || []).map((node) => cloneOpportunityCanvasNode(node)),
          edges: [...(base.edges || [])],
        };
      }

      function opportunityCanvasNodeSize(type) {
        if (type === "root") return { width: 230, height: 112 };
        if (type === "sector") return { width: 250, height: 104 };
        if (type === "stock") return { width: 280, height: 116 };
        if (type === "hot_sector") return { width: 270, height: 108 };
        if (type === "hot_board") return { width: 280, height: 100 };
        return { width: 270, height: 92 };
      }

      function layoutOpportunityCanvas(canvas) {
        const nodes = (canvas && canvas.nodes) || [];
        const edges = (canvas && canvas.edges) || [];
        const children = new Map();
        edges.forEach((edge) => {
          if (!children.has(edge.from)) children.set(edge.from, []);
          children.get(edge.from).push(edge.to);
        });
        const nodeMap = new Map(nodes.map((node) => [node.id, node]));
        const positions = new Map();
        let row = 0;
        const rowHeight = 82;
        const top = 74;
        const columns = { root: 70, sector: 360, stock: 700, tag: 1040 };
        const rootChildren = children.get("root") || [];
        const sectors = rootChildren.filter((id) => nodeMap.get(id)?.type === "sector");
        const extraRootChildren = rootChildren.filter((id) => nodeMap.get(id)?.type !== "sector");
        if (!rootChildren.length && nodeMap.has("root")) {
          positions.set("root", { x: columns.root, y: top + 120, ...opportunityCanvasNodeSize("root") });
        }

        sectors.forEach((sectorId) => {
          const stocks = (children.get(sectorId) || []).filter((id) => nodeMap.get(id)?.type === "stock");
          const sectorStartRow = row;
          const stockCenters = [];
          if (!stocks.length) {
            positions.set(sectorId, { x: columns.sector, y: top + row * rowHeight, ...opportunityCanvasNodeSize("sector") });
            row += 2;
            return;
          }
          stocks.forEach((stockId) => {
            const tags = (children.get(stockId) || []).filter((id) => nodeMap.get(id)?.type === "tag");
            const tagRows = Math.max(1, tags.length);
            tags.forEach((tagId, tagIndex) => {
              positions.set(tagId, { x: columns.tag, y: top + (row + tagIndex) * rowHeight, ...opportunityCanvasNodeSize("tag") });
            });
            const stockY = top + (row + (tagRows - 1) / 2) * rowHeight;
            positions.set(stockId, { x: columns.stock, y: stockY, ...opportunityCanvasNodeSize("stock") });
            stockCenters.push(stockY);
            row += tagRows + 0.55;
          });
          const sectorY = stockCenters.length
            ? stockCenters.reduce((sum, value) => sum + value, 0) / stockCenters.length
            : top + sectorStartRow * rowHeight;
          positions.set(sectorId, { x: columns.sector, y: sectorY, ...opportunityCanvasNodeSize("sector") });
          row += 0.8;
        });

        extraRootChildren.forEach((parentId) => {
          const parentNode = nodeMap.get(parentId);
          const childIds = children.get(parentId) || [];
          const startRow = row + 0.8;
          if (!childIds.length) {
            positions.set(parentId, { x: columns.sector, y: top + startRow * rowHeight, ...opportunityCanvasNodeSize(parentNode?.type) });
            row = startRow + 1.8;
            return;
          }
          const childCenters = [];
          childIds.forEach((childId, childIndex) => {
            const childNode = nodeMap.get(childId);
            const y = top + (startRow + childIndex * 1.35) * rowHeight;
            positions.set(childId, { x: columns.stock, y, ...opportunityCanvasNodeSize(childNode?.type) });
            childCenters.push(y);
          });
          const parentY = childCenters.reduce((sum, value) => sum + value, 0) / childCenters.length;
          positions.set(parentId, { x: columns.sector, y: parentY, ...opportunityCanvasNodeSize(parentNode?.type) });
          row = startRow + childIds.length * 1.35 + 0.8;
        });

        if (nodeMap.has("root")) {
          const childPositions = rootChildren.map((id) => positions.get(id)).filter(Boolean);
          const rootY = childPositions.length
            ? childPositions.reduce((sum, pos) => sum + pos.y, 0) / childPositions.length
            : top + 120;
          positions.set("root", { x: columns.root, y: rootY, ...opportunityCanvasNodeSize("root") });
        }

        const width = 1380;
        const height = Math.max(620, Math.ceil(row * rowHeight + 220));
        return { nodeMap, children, positions, width, height, edges };
      }

      function opportunityCanvasCurrentTransform() {
        const c = state.opportunityCanvas;
        return {
          x: c.viewX ?? c.offsetX ?? 0,
          y: c.viewY ?? c.offsetY ?? 0,
          scale: Math.max(0.1, c.viewScale ?? c.scale ?? 1),
        };
      }

      function setupOpportunityCanvasSurface() {
        const canvas = $("#opportunityCanvasSurface");
        const viewport = $("#opportunityCanvasViewport");
        if (!canvas || !viewport) return null;
        const rect = viewport.getBoundingClientRect();
        const width = Math.max(1, Math.floor(rect.width));
        const height = Math.max(1, Math.floor(rect.height));
        const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
        const pixelWidth = Math.round(width * dpr);
        const pixelHeight = Math.round(height * dpr);
        if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
          canvas.width = pixelWidth;
          canvas.height = pixelHeight;
          state.opportunityCanvas.surfaceWidth = width;
          state.opportunityCanvas.surfaceHeight = height;
        }
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext("2d");
        return ctx ? { canvas, viewport, ctx, width, height, dpr } : null;
      }

      function opportunityCanvasViewportPoint(clientX, clientY) {
        const viewport = $("#opportunityCanvasViewport");
        const rect = viewport?.getBoundingClientRect();
        return rect ? { x: clientX - rect.left, y: clientY - rect.top } : { x: 0, y: 0 };
      }

      function opportunityCanvasWorldPoint(clientX, clientY) {
        const point = opportunityCanvasViewportPoint(clientX, clientY);
        const transform = opportunityCanvasCurrentTransform();
        return {
          x: (point.x - transform.x) / transform.scale,
          y: (point.y - transform.y) / transform.scale,
        };
      }

      function scheduleOpportunityCanvasDraw() {
        const c = state.opportunityCanvas;
        if (c.drawRaf) return;
        const draw = () => {
          c.drawRaf = 0;
          drawOpportunityCanvasSurface();
        };
        c.drawRaf = window.requestAnimationFrame ? window.requestAnimationFrame(draw) : 0;
        if (!c.drawRaf) draw();
      }

      function opportunityCanvasPath(fromPos, toPos) {
        const x1 = fromPos.x + fromPos.width;
        const y1 = fromPos.y + fromPos.height / 2;
        const x2 = toPos.x;
        const y2 = toPos.y + toPos.height / 2;
        const dx = Math.max(70, (x2 - x1) * 0.48);
        return { x1, y1, x2, y2, c1x: x1 + dx, c1y: y1, c2x: x2 - dx, c2y: y2 };
      }

      function opportunityCanvasConnectedIds(layout, activeId) {
        const ids = new Set(activeId ? [activeId] : []);
        if (!layout || !activeId) return ids;
        (layout.edges || []).forEach((edge) => {
          if (edge.from === activeId) ids.add(edge.to);
          if (edge.to === activeId) ids.add(edge.from);
        });
        return ids;
      }

      function opportunityCanvasBounds(layout) {
        const positions = Array.from(layout?.positions?.values?.() || []);
        if (!positions.length) return { minX: 0, minY: 0, maxX: 800, maxY: 500, width: 800, height: 500 };
        const minX = Math.min(...positions.map((pos) => pos.x));
        const minY = Math.min(...positions.map((pos) => pos.y));
        const maxX = Math.max(...positions.map((pos) => pos.x + pos.width));
        const maxY = Math.max(...positions.map((pos) => pos.y + pos.height));
        return { minX, minY, maxX, maxY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) };
      }

      function opportunityCanvasViewportWorldBounds(width, height, transform) {
        const margin = 360 / transform.scale;
        return {
          minX: (-transform.x / transform.scale) - margin,
          minY: (-transform.y / transform.scale) - margin,
          maxX: ((width - transform.x) / transform.scale) + margin,
          maxY: ((height - transform.y) / transform.scale) + margin,
        };
      }

      function opportunityCanvasRectIntersects(pos, bounds) {
        return pos.x + pos.width >= bounds.minX
          && pos.x <= bounds.maxX
          && pos.y + pos.height >= bounds.minY
          && pos.y <= bounds.maxY;
      }

      function opportunityCanvasNodeMetric(node) {
        if (!node) return "";
        if (node.score != null) return `${node.score_rank ? `#${node.score_rank} · ` : ""}评分 ${num(node.score)}`;
        if (node.board_rank) return `#${node.board_rank}`;
        if (node.stock_count != null) return `${node.stock_count}只`;
        return "";
      }

      function opportunityCanvasNodePalette(node) {
        const palettes = {
          root: { fill: "#eef5ff", border: "#2f6fdd", chip: "#dbeafe", chipText: "#174a9b" },
          sector: { fill: "#eef8f6", border: "#11756f", chip: "#d7f1ee", chipText: "#0f5f59" },
          stock: { fill: "#fff9ec", border: "#a86d00", chip: "#ffedc2", chipText: "#7a4d00" },
          tag: { fill: "#fbf7fb", border: "#8d7190", chip: "#eee2ef", chipText: "#654b67" },
          hot_sector: { fill: "#f4f1ff", border: "#6f55d8", chip: "#e8e2ff", chipText: "#4932a8" },
          hot_board: { fill: "#fff3f1", border: "#c43d36", chip: "#ffe0dc", chipText: "#9f2923" },
        };
        return palettes[node?.type] || { fill: "#ffffff", border: "#8da2bd", chip: "#edf2f7", chipText: "#314158" };
      }

      function canvasRoundRect(ctx, x, y, width, height, radius) {
        const r = Math.min(radius, width / 2, height / 2);
        ctx.beginPath();
        if (ctx.roundRect) {
          ctx.roundRect(x, y, width, height, r);
          return;
        }
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + width, y, x + width, y + height, r);
        ctx.arcTo(x + width, y + height, x, y + height, r);
        ctx.arcTo(x, y + height, x, y, r);
        ctx.arcTo(x, y, x + width, y, r);
        ctx.closePath();
      }

      function opportunityCanvasWrapText(ctx, value, maxWidth, maxLines) {
        const text = String(value ?? "").replace(/\s+/g, " ").trim();
        if (!text) return [];
        const c = state.opportunityCanvas;
        const key = `${ctx.font}|${Math.round(maxWidth)}|${maxLines}|${text}`;
        if (c.textCache?.has(key)) return c.textCache.get(key);
        const lines = [];
        let line = "";
        Array.from(text).forEach((char) => {
          const test = line + char;
          if (line && ctx.measureText(test).width > maxWidth) {
            lines.push(line);
            line = char.trimStart();
          } else {
            line = test;
          }
        });
        if (line) lines.push(line);
        let out = lines;
        if (lines.length > maxLines) {
          out = lines.slice(0, maxLines);
          let last = out[out.length - 1] || "";
          while (last.length > 1 && ctx.measureText(`${last}...`).width > maxWidth) {
            last = last.slice(0, -1);
          }
          out[out.length - 1] = `${last}...`;
        }
        if (c.textCache) {
          if (c.textCache.size > 2400) c.textCache.clear();
          c.textCache.set(key, out);
        }
        return out;
      }

      function opportunityCanvasDrawPill(ctx, text, x, y, options = {}) {
        const label = String(text || "");
        if (!label) return 0;
        ctx.save();
        ctx.font = options.font || "700 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
        const width = Math.min(options.maxWidth || 140, Math.ceil(ctx.measureText(label).width + 14));
        const height = options.height || 20;
        canvasRoundRect(ctx, x, y, width, height, options.radius || 6);
        ctx.fillStyle = options.fill || "#edf2f7";
        ctx.fill();
        ctx.fillStyle = options.color || "#314158";
        ctx.textBaseline = "middle";
        const clipped = ctx.measureText(label).width + 14 > width ? label.slice(0, Math.max(1, Math.floor(width / 8))) + "..." : label;
        ctx.fillText(clipped, x + 7, y + height / 2);
        ctx.restore();
        return width;
      }

      function opportunityCanvasDrawNode(ctx, node, pos, flags, transform) {
        const palette = opportunityCanvasNodePalette(node);
        const scale = Math.max(0.1, transform.scale);
        const dimmed = flags.activeId && !flags.connected.has(node.id);
        const active = node.id === flags.activeId;
        const hover = node.id === flags.hoverId;
        const dragging = flags.draggingId === node.id;
        ctx.save();
        ctx.globalAlpha = dimmed ? 0.36 : 1;
        if (active || hover || dragging) {
          ctx.shadowColor = "rgba(47, 111, 221, 0.18)";
          ctx.shadowBlur = 18 / scale;
          ctx.shadowOffsetY = 8 / scale;
        }
        canvasRoundRect(ctx, pos.x, pos.y, pos.width, pos.height, 8);
        ctx.fillStyle = palette.fill;
        ctx.fill();
        ctx.shadowColor = "transparent";
        ctx.lineWidth = (active || hover ? 2 : 1) / scale;
        ctx.strokeStyle = active || hover ? "#2f6fdd" : palette.border;
        ctx.stroke();

        ctx.fillStyle = "#ffffff";
        ctx.strokeStyle = "#c6d0dd";
        ctx.lineWidth = 1 / scale;
        ctx.beginPath();
        ctx.arc(pos.x, pos.y + pos.height / 2, 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = palette.border;
        ctx.beginPath();
        ctx.arc(pos.x + pos.width, pos.y + pos.height / 2, 5, 0, Math.PI * 2);
        ctx.fill();

        const pad = 12;
        let y = pos.y + 10;
        const typeLabel = opportunityCanvasNodeTypeLabel(node);
        opportunityCanvasDrawPill(ctx, typeLabel, pos.x + pad, y, {
          fill: palette.chip,
          color: palette.chipText,
          maxWidth: 116,
        });
        const metric = opportunityCanvasNodeMetric(node);
        if (metric) {
          ctx.font = "700 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
          const metricWidth = Math.min(116, Math.ceil(ctx.measureText(metric).width + 14));
          opportunityCanvasDrawPill(ctx, metric, pos.x + pos.width - pad - metricWidth, y, {
            fill: "rgba(47, 111, 221, 0.1)",
            color: "#174a9b",
            maxWidth: metricWidth,
          });
        }

        y += 32;
        ctx.fillStyle = "#172033";
        ctx.font = "700 14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
        ctx.textBaseline = "top";
        const titleLines = opportunityCanvasWrapText(ctx, node.title || "--", pos.width - pad * 2, 2);
        titleLines.forEach((line) => {
          ctx.fillText(line, pos.x + pad, y);
          y += 17;
        });

        ctx.fillStyle = "#6b778a";
        ctx.font = "12px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
        const subtitleLines = opportunityCanvasWrapText(ctx, node.subtitle || "", pos.width - pad * 2, 2);
        subtitleLines.forEach((line) => {
          if (y < pos.y + pos.height - 24) ctx.fillText(line, pos.x + pad, y);
          y += 15;
        });

        const tags = (node.tags || []).filter(Boolean).slice(0, 3);
        if (tags.length && pos.height >= 92) {
          let tagX = pos.x + pad;
          const tagY = pos.y + pos.height - 24;
          tags.forEach((tag) => {
            if (tagX > pos.x + pos.width - 42) return;
            ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
            const width = Math.min(92, Math.ceil(ctx.measureText(String(tag)).width + 14));
            if (tagX + width > pos.x + pos.width - pad) return;
            canvasRoundRect(ctx, tagX, tagY, width, 18, 9);
            ctx.fillStyle = "rgba(255, 255, 255, 0.72)";
            ctx.fill();
            ctx.strokeStyle = "#dbe3ee";
            ctx.lineWidth = 1 / scale;
            ctx.stroke();
            ctx.fillStyle = "#314158";
            ctx.textBaseline = "middle";
            ctx.fillText(String(tag).slice(0, 12), tagX + 7, tagY + 9);
            tagX += width + 5;
          });
        }
        ctx.restore();
      }

      function opportunityCanvasDrawEdge(ctx, edge, layout, flags, transform, bounds) {
        const fromPos = layout.positions.get(edge.from);
        const toPos = layout.positions.get(edge.to);
        if (!fromPos || !toPos) return;
        const edgeBounds = {
          x: Math.min(fromPos.x, toPos.x) - 110,
          y: Math.min(fromPos.y, toPos.y) - 80,
          width: Math.abs((toPos.x + toPos.width) - fromPos.x) + 220,
          height: Math.abs((toPos.y + toPos.height) - fromPos.y) + 160,
        };
        if (!opportunityCanvasRectIntersects(edgeBounds, bounds)) return;
        const path = opportunityCanvasPath(fromPos, toPos);
        const active = !!flags.activeId && (edge.from === flags.activeId || edge.to === flags.activeId);
        const related = !flags.activeId || active;
        const scale = Math.max(0.1, transform.scale);
        ctx.save();
        ctx.globalAlpha = related ? (active ? 1 : 0.8) : 0.2;
        ctx.strokeStyle = active ? "#2f6fdd" : "#b8c5d6";
        ctx.lineWidth = (active ? 3 : 2) / scale;
        ctx.beginPath();
        ctx.moveTo(path.x1, path.y1);
        ctx.bezierCurveTo(path.c1x, path.c1y, path.c2x, path.c2y, path.x2, path.y2);
        ctx.stroke();

        const angle = Math.atan2(path.y2 - path.c2y, path.x2 - path.c2x);
        const size = (active ? 8 : 7) / scale;
        ctx.fillStyle = active ? "#2f6fdd" : "#b8c5d6";
        ctx.beginPath();
        ctx.moveTo(path.x2, path.y2);
        ctx.lineTo(path.x2 - Math.cos(angle - 0.42) * size, path.y2 - Math.sin(angle - 0.42) * size);
        ctx.lineTo(path.x2 - Math.cos(angle + 0.42) * size, path.y2 - Math.sin(angle + 0.42) * size);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }

      function drawOpportunityCanvasSurface() {
        const setup = setupOpportunityCanvasSurface();
        const layout = state.opportunityCanvas.layout;
        if (!setup) return;
        const { ctx, width, height, dpr } = setup;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
        if (!layout) return;
        const transform = opportunityCanvasCurrentTransform();
        const bounds = opportunityCanvasViewportWorldBounds(width, height, transform);
        const c = state.opportunityCanvas;
        const connected = opportunityCanvasConnectedIds(layout, c.activeId);
        const flags = {
          activeId: c.activeId,
          hoverId: c.hoverId,
          draggingId: c.nodeDragging?.id || null,
          connected,
        };
        ctx.save();
        ctx.translate(transform.x, transform.y);
        ctx.scale(transform.scale, transform.scale);
        (layout.edges || []).forEach((edge) => opportunityCanvasDrawEdge(ctx, edge, layout, flags, transform, bounds));
        const nodes = Array.from(layout.positions.entries())
          .map(([id, pos]) => ({ id, pos, node: layout.nodeMap.get(id) }))
          .filter((item) => item.node && opportunityCanvasRectIntersects(item.pos, bounds))
          .sort((a, b) => {
            const aTop = (a.id === flags.activeId ? 2 : 0) + (a.id === flags.hoverId ? 1 : 0) + (a.id === flags.draggingId ? 3 : 0);
            const bTop = (b.id === flags.activeId ? 2 : 0) + (b.id === flags.hoverId ? 1 : 0) + (b.id === flags.draggingId ? 3 : 0);
            return aTop - bTop;
          });
        nodes.forEach(({ node, pos }) => opportunityCanvasDrawNode(ctx, node, pos, flags, transform));
        ctx.restore();
      }

      function applyOpportunityCanvasTransform() {
        const viewport = $("#opportunityCanvasViewport");
        const c = state.opportunityCanvas;
        if (c.viewX == null) c.viewX = c.offsetX;
        if (c.viewY == null) c.viewY = c.offsetY;
        if (c.viewScale == null) c.viewScale = c.scale;
        const commit = () => {
          const factor = c.dragging || c.nodeDragging ? 0.5 : 0.24;
          c.viewX += (c.offsetX - c.viewX) * factor;
          c.viewY += (c.offsetY - c.viewY) * factor;
          c.viewScale += (c.scale - c.viewScale) * factor;
          const close = Math.abs(c.offsetX - c.viewX) < 0.12
            && Math.abs(c.offsetY - c.viewY) < 0.12
            && Math.abs(c.scale - c.viewScale) < 0.001;
          if (close) {
            c.viewX = c.offsetX;
            c.viewY = c.offsetY;
            c.viewScale = c.scale;
          }
          if (viewport) {
            const nextGrid = {
              x: Math.round(c.viewX),
              y: Math.round(c.viewY),
              size: Math.round(Math.max(10, 28 * c.viewScale) * 10) / 10,
            };
            const prevGrid = c.gridState || {};
            if (Math.abs((prevGrid.x ?? Infinity) - nextGrid.x) >= 2
              || Math.abs((prevGrid.y ?? Infinity) - nextGrid.y) >= 2
              || Math.abs((prevGrid.size ?? Infinity) - nextGrid.size) >= 0.5) {
              viewport.style.setProperty("--canvas-grid-x", `${nextGrid.x}px`);
              viewport.style.setProperty("--canvas-grid-y", `${nextGrid.y}px`);
              viewport.style.setProperty("--canvas-grid-size", `${nextGrid.size}px`);
              c.gridState = nextGrid;
            }
          }
          drawOpportunityCanvasSurface();
          updateOpportunityCanvasMinimapViewport();
          if (close) {
            c.raf = 0;
          } else {
            c.raf = window.requestAnimationFrame ? window.requestAnimationFrame(commit) : 0;
          }
        };
        if (c.raf) return;
        c.raf = window.requestAnimationFrame ? window.requestAnimationFrame(commit) : 0;
        if (!c.raf) commit();
      }

      function stopOpportunityCanvasInertia() {
        const c = state.opportunityCanvas;
        if (c.inertiaRaf) {
          cancelAnimationFrame(c.inertiaRaf);
          c.inertiaRaf = 0;
        }
        c.panVelocityX = 0;
        c.panVelocityY = 0;
      }

      function startOpportunityCanvasInertia() {
        const c = state.opportunityCanvas;
        const speed = Math.hypot(c.panVelocityX, c.panVelocityY);
        if (!window.requestAnimationFrame || speed < 0.06) return;
        if (c.inertiaRaf) cancelAnimationFrame(c.inertiaRaf);
        let last = performance.now();
        const step = (now) => {
          const dt = Math.min(34, Math.max(1, now - last));
          last = now;
          c.offsetX += c.panVelocityX * dt;
          c.offsetY += c.panVelocityY * dt;
          const decay = Math.pow(0.9, dt / 16);
          c.panVelocityX *= decay;
          c.panVelocityY *= decay;
          applyOpportunityCanvasTransform();
          if (Math.hypot(c.panVelocityX, c.panVelocityY) > 0.02) {
            c.inertiaRaf = requestAnimationFrame(step);
          } else {
            c.inertiaRaf = 0;
            c.panVelocityX = 0;
            c.panVelocityY = 0;
          }
        };
        c.inertiaRaf = requestAnimationFrame(step);
      }

      function updateOpportunityCanvasSelection(activeId) {
        if (!state.opportunityCanvas.layout) return;
        state.opportunityCanvas.activeId = activeId;
        scheduleOpportunityCanvasDraw();
      }

      function fitOpportunityCanvas() {
        const viewport = $("#opportunityCanvasViewport");
        const layout = state.opportunityCanvas.layout;
        if (!viewport || !layout) return;
        const c = state.opportunityCanvas;
        const rect = viewport.getBoundingClientRect();
        const bounds = opportunityCanvasBounds(layout);
        const pad = 64;
        const fitScale = Math.min(
          1.08,
          Math.max(0.26, Math.min((rect.width - pad * 2) / bounds.width, (rect.height - pad * 2) / bounds.height)),
        );
        c.scale = fitScale;
        c.offsetX = Math.round((rect.width - bounds.width * fitScale) / 2 - bounds.minX * fitScale);
        c.offsetY = Math.round((rect.height - bounds.height * fitScale) / 2 - bounds.minY * fitScale);
        applyOpportunityCanvasTransform();
      }

      function ensureOpportunityCanvasMinimap() {
        const viewport = $("#opportunityCanvasViewport");
        if (!viewport) return null;
        let mini = $("#opportunityCanvasMinimap");
        if (!mini) {
          mini = document.createElement("div");
          mini.id = "opportunityCanvasMinimap";
          mini.className = "opportunity-canvas-minimap";
          viewport.appendChild(mini);
        }
        return mini;
      }

      function renderOpportunityCanvasMinimap() {
        const layout = state.opportunityCanvas.layout;
        const mini = ensureOpportunityCanvasMinimap();
        if (!layout || !mini) return;
        const bounds = opportunityCanvasBounds(layout);
        const width = 176;
        const height = 110;
        const pad = 8;
        const scale = Math.min((width - pad * 2) / bounds.width, (height - pad * 2) / bounds.height);
        state.opportunityCanvas.minimap = { bounds, width, height, pad, scale };
        mini.innerHTML = `
          <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true">
            ${(Array.from(layout.positions.entries())).map(([id, pos]) => {
              const node = layout.nodeMap.get(id) || {};
              const x = pad + (pos.x - bounds.minX) * scale;
              const y = pad + (pos.y - bounds.minY) * scale;
              const w = Math.max(3, pos.width * scale);
              const h = Math.max(3, pos.height * scale);
              return `<rect class="${html(node.type || "node")}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="2"></rect>`;
            }).join("")}
          </svg>
          <div class="canvas-minimap-view"></div>
        `;
        updateOpportunityCanvasMinimapViewport();
      }

      function updateOpportunityCanvasMinimapViewport() {
        const c = state.opportunityCanvas;
        const mini = $("#opportunityCanvasMinimap");
        const view = mini?.querySelector(".canvas-minimap-view");
        const viewport = $("#opportunityCanvasViewport");
        if (!view || !viewport || !c.minimap) return;
        const { bounds, pad, scale } = c.minimap;
        const rect = viewport.getBoundingClientRect();
        const transform = opportunityCanvasCurrentTransform();
        const x = pad + (((-transform.x / transform.scale) - bounds.minX) * scale);
        const y = pad + (((-transform.y / transform.scale) - bounds.minY) * scale);
        const w = (rect.width / transform.scale) * scale;
        const h = (rect.height / transform.scale) * scale;
        view.style.left = `${x}px`;
        view.style.top = `${y}px`;
        view.style.width = `${w}px`;
        view.style.height = `${h}px`;
      }

      function selectOpportunityCanvasNode(id) {
        const layout = state.opportunityCanvas.layout;
        if (!layout) return;
        const node = layout.nodeMap.get(id);
        if (!node) return;
        state.opportunityCanvas.activeId = id;
        updateOpportunityCanvasSelection(id);
        renderOpportunityCanvasDetail(node);
      }

      function opportunityCanvasHitNode(clientX, clientY) {
        const layout = state.opportunityCanvas.layout;
        if (!layout) return null;
        const point = opportunityCanvasWorldPoint(clientX, clientY);
        const entries = Array.from(layout.positions.entries()).reverse();
        for (const [id, pos] of entries) {
          if (point.x >= pos.x && point.x <= pos.x + pos.width && point.y >= pos.y && point.y <= pos.y + pos.height) {
            return { id, pos, node: layout.nodeMap.get(id) };
          }
        }
        return null;
      }

      function bindOpportunityCanvasNodeInteractions() {
        scheduleOpportunityCanvasDraw();
      }

      function opportunityCanvasNodeTypeLabel(node) {
        if (!node) return "节点";
        if (node.entity_kind) return "业务标签";
        if (node.type === "root") return "报告";
        if (node.type === "sector") return "板块";
        if (node.type === "stock") return "股票";
        if (node.type === "hot_sector") return "热门板块";
        if (node.type === "hot_board") return "板块快照";
        if (node.type === "tag") return "分析内容";
        return "节点";
      }

      function opportunityCanvasFactRows(node) {
        const rows = [];
        const add = (label, value) => {
          if (value === null || value === undefined || value === "") return;
          rows.push({ label, value });
        };
        add("类型", opportunityCanvasNodeTypeLabel(node));
        add("股票代码", node.stock_code);
        add("股票名称", node.stock_name);
        add("所属板块", node.sector);
        add("全量排名", node.score_rank ? `#${node.score_rank}` : "");
        add("报告排名", node.report_rank ? `#${node.report_rank}` : "");
        add("板块内排名", node.sector_rank ? `#${node.sector_rank}${node.sector_peer_count ? ` / ${node.sector_peer_count}` : ""}` : "");
        add("综合评分", node.score != null ? num(node.score) : "");
        add("评级", node.rating);
        add("候选来源", node.source);
        add("相关热门板块数", node.hot_sector_count != null ? `${node.hot_sector_count}个` : "");
        add("热门板块排名", node.hot_sector_rank_summary);
        add("龙虎榜命中", node.lhb_hit ? `是${node.lhb_relation_count ? ` · ${node.lhb_relation_count}条关系` : ""}` : "");
        add("板块代码", node.board_code);
        add("板块类型", node.board_type);
        add("板块排名", node.board_rank ? `#${node.board_rank}` : "");
        add("成分股数量", node.stock_count != null ? `${node.stock_count}只` : "");
        add("龙虎榜关系", node.relation_count != null ? `${node.relation_count}条` : "");
        add("主力净流入", node.main_net_inflow != null ? volumeLabel(node.main_net_inflow) : "");
        add("涨跌幅", node.change_pct != null ? `${num(node.change_pct)}%` : "");
        add("快照ID", node.snapshot_id);
        add("快照时间", node.created_at);
        add("业务标签", node.entity_kind);
        return rows;
      }

      function opportunityCanvasHotSectorMemberships(node) {
        const rows = Array.isArray(node?.hot_sector_memberships) ? node.hot_sector_memberships : [];
        if (!rows.length) return "";
        const itemHtml = rows.slice(0, 16).map((item) => {
          const inflow = item.main_net_inflow_text || (item.main_net_inflow != null ? volumeLabel(item.main_net_inflow) : "--");
          const lhb = item.lhb_hit
            ? `龙虎榜 ${item.lhb_trade_date || ""} · 净 ${volumeLabel(item.lhb_net_amount)}`
            : "龙虎榜未命中";
          return `
            <div class="canvas-membership-row">
              <strong>${html(item.board_name || item.board_code || "热门板块")}</strong>
              <p class="item-meta">板块#${html(item.board_rank || "--")} · 成分股#${html(item.stock_rank || "--")} · 主力 ${html(inflow)} · 涨跌 ${item.change_pct != null ? `${num(item.change_pct)}%` : "--"} · ${html(lhb)}</p>
              ${item.lhb_reason ? `<p class="item-meta">${html(item.lhb_reason)}</p>` : ""}
            </div>
          `;
        }).join("");
        const more = rows.length > 16 ? `<p class="item-meta">另有 ${rows.length - 16} 个关联热门板块，可在热门/标签维度继续钻取。</p>` : "";
        return `
          <div class="canvas-detail-section">
            <strong>相关热门板块</strong>
            <div class="canvas-membership-list">${itemHtml}</div>
            ${more}
          </div>
        `;
      }

      function opportunityCanvasRelationSummary(node) {
        const layout = state.opportunityCanvas.layout;
        if (!node || !layout) return "";
        const parentIds = (layout.edges || []).filter((edge) => edge.to === node.id).map((edge) => edge.from);
        const childIds = (layout.children?.get(node.id) || []).slice();
        const itemHtml = (ids) => ids.slice(0, 18).map((id) => {
          const related = layout.nodeMap?.get(id);
          if (!related) return "";
          return `<span>${html(related.title || id)}</span>`;
        }).join("");
        const parentHtml = itemHtml(parentIds);
        const childHtml = itemHtml(childIds);
        if (!parentHtml && !childHtml) return "";
        return `
          <div class="canvas-detail-section">
            <strong>画布关系</strong>
            ${parentHtml ? `<p class="item-meta">上级 ${parentIds.length} 个</p><div class="canvas-detail-chip-list">${parentHtml}</div>` : ""}
            ${childHtml ? `<p class="item-meta">下级 ${childIds.length} 个</p><div class="canvas-detail-chip-list">${childHtml}</div>` : ""}
          </div>
        `;
      }

      // 评分分项 / 风险信号 维度的中文标签（与后端 core.py 对齐）
      // 统一术语字典(EN→CN):评分维度 / 风险信号 / 来源 / 策略 / 关系 / 量化模型。
      // 凡展示给用户的英文 key 都走 zhLabel(kind,key);未命中回退原 key(绝不空白)。
      const OPP_LABELS = {
        score: {
          sector: "板块", technical: "技术", quantitative: "量化", fundamental: "基本面",
          sentiment: "情绪", news: "消息", event: "事件", events: "事件", moneyflow: "资金",
          momentum: "动量", volume_health: "量能", liquidity: "流动性", dragon_tiger: "龙虎榜",
          position_timing: "仓位择时", capital_flow: "资金流", capital: "资金",
          valuation: "估值", risk: "风险", trend: "趋势", pattern: "形态",
        },
        signal: {
          chase: "追高风险", rsi: "RSI", day_change: "当日涨幅", change_1d: "当日涨幅",
          change_3d: "3日涨幅", change_5d: "5日涨幅", sell_signals: "卖出信号",
          buy_signals: "买入信号", quant_score: "量化总分",
        },
        source: {
          multi: "多源候选", sector_hot: "热门板块成分股", heat: "热度候选",
          moneyflow_dc: "东方财富资金", oversold: "超跌反弹", dragon: "龙虎榜机构",
          dragon_tiger: "龙虎榜", manual: "手动指定",
        },
        strategy: { balanced: "均衡", strict: "严格", loose: "宽松", market_scan: "全市场扫描" },
        relation: { dragon_tiger: "龙虎榜", sector: "板块", concept: "概念" },
        model: {
          turtle_trading_system: "海龟交易", macd_golden_cross: "MACD金叉",
          atr_momentum: "ATR动量", cta_trend: "CTA趋势", ml_random_forest: "机器学习RF",
          multi_factor_alpha: "多因子Alpha", pairs_arbitrage: "配对套利",
          hft_microstructure: "高频微观结构", ichimoku_cloud: "一目均衡云",
          bollinger_squeeze: "布林挤压", rsi_divergence: "RSI背离",
          parabolic_sar: "抛物转向", money_flow_index: "资金流量", vwap_deviation: "VWAP偏离",
        },
      };
      function zhLabel(kind, key) {
        return (OPP_LABELS[kind] || {})[key] || key;
      }
      // 旧引用名保留为统一字典的别名,避免双份字典漂移
      const CANVAS_SCORE_LABELS = OPP_LABELS.score;
      const CANVAS_SIGNAL_LABELS = OPP_LABELS.signal;
      const CANVAS_SIGNAL_ORDER = ["chase", "rsi", "day_change", "change_3d", "change_5d", "sell_signals", "quant_score"];
      const CANVAS_SIGNAL_PCT = new Set(["day_change", "change_3d", "change_5d"]);

      function opportunityCanvasScoreBreakdown(node) {
        const raw = node && typeof node.score_breakdown === "object" ? node.score_breakdown : null;
        if (!raw) return "";
        const entries = Object.entries(raw).filter(([, v]) => v !== null && v !== undefined && v !== "");
        if (!entries.length) return "";
        const cells = entries.map(([key, value]) => {
          const numeric = Number(value);
          return `
            <div class="canvas-detail-fact">
              <span>${html(zhLabel('score', key))}</span>
              <strong>${Number.isFinite(numeric) ? num(numeric, 1) : html(String(value))}</strong>
            </div>
          `;
        }).join("");
        return `
          <div class="canvas-detail-section">
            <strong>评分分项</strong>
            <div class="canvas-detail-facts">${cells}</div>
          </div>
        `;
      }

      function opportunityCanvasSignals(node) {
        const raw = node && typeof node.signals === "object" ? node.signals : null;
        if (!raw) return "";
        const cells = CANVAS_SIGNAL_ORDER
          .filter((key) => raw[key] !== null && raw[key] !== undefined && raw[key] !== "")
          .map((key) => {
            const numeric = Number(raw[key]);
            const suffix = CANVAS_SIGNAL_PCT.has(key) ? "%" : "";
            return `
              <div class="canvas-detail-fact">
                <span>${html(zhLabel('signal', key))}</span>
                <strong>${Number.isFinite(numeric) ? num(numeric, 2) + suffix : html(String(raw[key]))}</strong>
              </div>
            `;
          }).join("");
        const exclusions = Array.isArray(raw.exclusions) ? raw.exclusions.filter(Boolean) : [];
        const exclusionHtml = exclusions.length
          ? `<p class="item-meta">过滤标记：${exclusions.map((x) => html(String(x))).join("、")}</p>`
          : "";
        if (!cells && !exclusionHtml) return "";
        return `
          <div class="canvas-detail-section">
            <strong>风险信号</strong>
            ${cells ? `<div class="canvas-detail-facts">${cells}</div>` : ""}
            ${exclusionHtml}
          </div>
        `;
      }

      function opportunityCanvasQuantModels(node) {
        const models = Array.isArray(node?.quant_models) ? node.quant_models.filter(Boolean) : [];
        if (!models.length) return "";
        const chips = models.map((m) => `<span class="pill">${html(String(m))}</span>`).join("");
        return `
          <div class="canvas-detail-section">
            <strong>量化模型 <span class="muted">${models.length}</span></strong>
            <div class="canvas-detail-tags">${chips}</div>
          </div>
        `;
      }

      // 评分明细重做为「综合总览」样式:统一卡片(总评+评级)+维度进度条+信号 tone 卡片。
      function opportunityScoreRatingLean(rating, score) {
        const s = Number(score);
        if (rating === "S" || rating === "A" || (Number.isFinite(s) && s >= 78)) return "bull";
        if (rating === "C" || rating === "D" || (Number.isFinite(s) && s < 60)) return "bear";
        return "neutral";
      }
      function opportunitySignalTone(key, n) {
        if (!Number.isFinite(n)) return "neutral";
        if (key === "chase") return n >= 60 ? "danger" : (n >= 40 ? "warn" : "good");
        if (key === "rsi") return (n >= 80 || n <= 20) ? "warn" : "good";
        if (key === "day_change" || key === "change_3d" || key === "change_5d") return n >= 15 ? "warn" : (n < 0 ? "neutral" : "good");
        if (key === "sell_signals") return n >= 2 ? "warn" : "good";
        if (key === "quant_score") return n >= 90 ? "warn" : (n < 50 ? "good" : "neutral");
        return "neutral";
      }
      function opportunityCanvasScoreSummary(node) {
        const breakdown = node && typeof node.score_breakdown === "object" ? node.score_breakdown : null;
        const signals = node && typeof node.signals === "object" ? node.signals : null;
        const hasScore = node && node.score != null && node.score !== "";
        const dimEntries = breakdown
          ? Object.entries(breakdown).filter(([, v]) => v !== null && v !== undefined && v !== "")
          : [];
        const sigKeys = signals
          ? CANVAS_SIGNAL_ORDER.filter((k) => signals[k] !== null && signals[k] !== undefined && signals[k] !== "")
          : [];
        const exclusions = signals && Array.isArray(signals.exclusions) ? signals.exclusions.filter(Boolean) : [];
        if (!hasScore && !dimEntries.length && !sigKeys.length && !exclusions.length) return "";

        const scoreTxt = hasScore ? num(node.score, 1) : "--";
        const rating = node.rating || "";
        const lean = opportunityScoreRatingLean(rating, node.score);
        const dims = dimEntries.map(([key, value]) => {
          const n = Number(value);
          const pct = Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0;
          const valTxt = Number.isFinite(n) ? num(n, 1) : html(String(value));
          const tone = Number.isFinite(n) ? (n >= 70 ? "good" : (n >= 50 ? "mid" : "low")) : "mid";
          return `
            <div class="opp-score-row">
              <span class="opp-score-label">${html(zhLabel("score", key))}</span>
              <span class="opp-score-bar"><i class="tone-${tone}" style="width:${pct}%"></i></span>
              <strong class="opp-score-val">${valTxt}</strong>
            </div>`;
        }).join("");
        let sigChips = sigKeys.map((k) => {
          const n = Number(signals[k]);
          const suffix = CANVAS_SIGNAL_PCT.has(k) ? "%" : "";
          const tone = opportunitySignalTone(k, n);
          const val = Number.isFinite(n) ? num(n, 2) + suffix : html(String(signals[k]));
          return `<div class="opp-signal-chip tone-${tone}"><span>${html(zhLabel("signal", k))}</span><strong>${val}</strong></div>`;
        }).join("");
        if (exclusions.length) {
          sigChips += `<div class="opp-signal-chip tone-warn"><span>过滤标记</span><strong>${exclusions.slice(0, 4).map((x) => html(String(x))).join("、")}</strong></div>`;
        }
        return `
          <div class="opp-score-card">
            <div class="opp-score-head">
              <span class="opp-score-title">📊 评分总览</span>
              <span class="opp-score-verdict lean-${lean}">综合 ${scoreTxt}${rating ? " · " + html(rating) : ""}</span>
            </div>
            ${dims ? `<div class="opp-score-dims">${dims}</div>` : ""}
            ${sigChips ? `<div class="opp-score-signals">${sigChips}</div>` : ""}
          </div>`;
      }

      function renderOpportunityCanvasDetail(node) {        const detail = $("#opportunityCanvasDetail");
        if (!detail) return;
        if (!node) {
          detail.innerHTML = `
            <div class="canvas-detail-empty">
              <p class="item-meta">暂无可展示的层级分析。</p>
            </div>
          `;
          return;
        }
        const tags = (node.tags || []).map((tag) => `<span class="pill">${html(tag)}</span>`).join("");
        const facts = opportunityCanvasFactRows(node).map((row) => `
          <div class="canvas-detail-fact">
            <span>${html(row.label)}</span>
            <strong>${html(row.value)}</strong>
          </div>
        `).join("");
        const analysis = (node.analysis || []).map((section) => `
          <div class="canvas-detail-section">
            <strong>${html(section.label)}</strong>
            <p>${html(section.value)}</p>
          </div>
        `).join("");
        const stockActions = node.stock_code ? `
          <div class="actions canvas-detail-actions">
            <button class="button secondary compact" type="button" data-canvas-stock="${html(node.stock_code)}" data-canvas-stock-name="${html(node.stock_name || '')}">个股分析</button>
            <button class="button secondary compact" type="button" data-canvas-kline="${html(node.stock_code)}">K线</button>
          </div>
        ` : "";
        const typeLabel = opportunityCanvasNodeTypeLabel(node);
        const scoreSummaryHtml = opportunityCanvasScoreSummary(node);
        const quantModelsHtml = opportunityCanvasQuantModels(node);
        const drilldown = node.drilldown ? `
          <div class="actions canvas-detail-actions">
            <button class="button compact" type="button" data-canvas-drill-node="${html(node.id)}">展开相关信息</button>
          </div>
          <div id="canvasDrilldown" class="canvas-drilldown"></div>
        ` : "";
        detail.innerHTML = `
          <div class="canvas-detail-head">
            <span class="pill">${html(typeLabel)}</span>
            <h3>${html(node.title || "--")}</h3>
            <p class="item-meta">${html(node.subtitle || "")}</p>
            <div class="canvas-detail-tags">${tags}</div>
          </div>
          ${stockActions}
          ${drilldown}
          ${facts ? `<div class="canvas-detail-facts">${facts}</div>` : ""}
          ${scoreSummaryHtml}
          ${quantModelsHtml}
          ${opportunityCanvasHotSectorMemberships(node)}
          ${opportunityCanvasRelationSummary(node)}
          ${node.detail ? `<div class="canvas-detail-section"><strong>分析摘要</strong><p>${html(node.detail)}</p></div>` : ""}
          ${analysis ? `<div class="canvas-detail-section canvas-detail-section-title"><strong>内容明细</strong><p>按当前节点列出完整分析字段和关系内容。</p></div>` : ""}
          ${analysis}
        `;
        detail.querySelector("[data-canvas-stock]")?.addEventListener("click", (event) => {
          const btn = event.currentTarget;
          openStockContext({
            type: "stock",
            stock_code: btn.dataset.canvasStock,
            stock_name: btn.dataset.canvasStockName || "",
            board_name: node.sector || "",
          }).catch((error) => alert(error.message));
        });
        detail.querySelector("[data-canvas-kline]")?.addEventListener("click", (event) => {
          openStockKlineModal(event.currentTarget.dataset.canvasKline, 240, { stockName: node.stock_name || "" }).catch((error) => alert(error.message));
        });
        detail.querySelector("[data-canvas-drill-node]")?.addEventListener("click", (event) => {
          const id = event.currentTarget.dataset.canvasDrillNode;
          const targetNode = state.opportunityCanvas.layout?.nodeMap?.get(id);
          loadCanvasDrilldown(targetNode, event.currentTarget).catch((error) => alert(error.message));
        });
      }

      function hotSectorStockRow(row) {
        const lhb = row.lhb_trade_date
          ? `龙虎榜 ${html(row.lhb_trade_date)} · 买入 ${volumeLabel(row.lhb_buy_amount)} · 净 ${volumeLabel(row.lhb_net_amount)}`
          : "龙虎榜未命中";
        const inflow = row.main_net_inflow_text || volumeLabel(row.main_net_inflow);
        return `
          <div class="canvas-drill-row">
            <div>
              <strong>${html(row.stock_rank || row.candidate_rank || "--")}. ${html(row.name || row.code)} <span class="muted">${html(row.code || "")}</span></strong>
              <p class="item-meta">主力净流入 ${html(inflow)} · 涨跌 ${num(row.change_pct)}% · ${lhb}</p>
              ${row.lhb_reason ? `<p class="item-meta">${html(row.lhb_reason)}</p>` : ""}
            </div>
            <div class="actions">
              <button class="button secondary compact" type="button" data-drill-stock="${html(row.code || "")}" data-drill-stock-name="${html(row.name || "")}">分析</button>
              <button class="button secondary compact" type="button" data-drill-kline="${html(row.code || "")}" data-drill-stock-name="${html(row.name || "")}">K线</button>
            </div>
          </div>
        `;
      }

      async function loadCanvasDrilldown(node, button, offset = 0) {
        if (!node?.drilldown) return;
        const target = $("#canvasDrilldown");
        if (!target) return;
        const originalText = button?.textContent || "";
        if (button) {
          button.disabled = true;
          button.textContent = "读取中...";
        }
        try {
          const drill = node.drilldown;
          if (drill.type === "hot_sector_snapshot") {
            const payload = await fetchJson(`/api/hot-sector-snapshot?snapshot_id=${encodeURIComponent(drill.snapshot_id)}`);
            const boards = payload.boards || [];
            target.innerHTML = `
              <div class="canvas-drill-block">
                ${boards.map((board) => `
                  <button class="canvas-drill-row canvas-drill-board" type="button"
                          data-hot-board="${html(board.board_code || '')}"
                          data-hot-snapshot="${html(payload.snapshot?.id || drill.snapshot_id || '')}">
                    <div>
                      <strong>${html(board.board_rank || "--")}. ${html(board.board_name || board.board_code)}</strong>
                      <p class="item-meta">成分股 ${html(board.stock_count || 0)} · 龙虎榜关系 ${html(board.relation_count || 0)} · 涨跌 ${num(board.change_pct)}%</p>
                    </div>
                  </button>
                `).join("")}
              </div>
            `;
            target.querySelectorAll("[data-hot-board]").forEach((el) => {
              el.addEventListener("click", () => {
                loadCanvasDrilldown({
                  title: el.textContent,
                  drilldown: {
                    type: "hot_sector_stocks",
                    snapshot_id: el.dataset.hotSnapshot,
                    board_code: el.dataset.hotBoard,
                  },
                }, button).catch((error) => alert(error.message));
              });
            });
            return;
          }
          if (drill.type === "hot_sector_stocks") {
            const limit = 120;
            const url = `/api/hot-sector-snapshot/${encodeURIComponent(drill.snapshot_id)}/stocks?board_code=${encodeURIComponent(drill.board_code || "")}&limit=${limit}&offset=${offset}`;
            const payload = await fetchJson(url);
            const rows = payload.stocks || [];
            const rowsHtml = rows.map(hotSectorStockRow).join("");
            const moreHtml = payload.has_more
              ? `<button class="button secondary compact canvas-more-btn" type="button" data-next-offset="${html(payload.next_offset || 0)}">继续展开</button>`
              : "";
            if (offset > 0) {
              const existing = target.querySelector(".canvas-drill-list");
              if (existing) existing.insertAdjacentHTML("beforeend", rowsHtml);
              target.querySelector(".canvas-more-btn")?.remove();
              target.insertAdjacentHTML("beforeend", moreHtml);
            } else {
              target.innerHTML = `
                <div class="canvas-drill-block">
                  <div class="canvas-drill-list">${rowsHtml || `<p class="item-meta">暂无成分股明细。</p>`}</div>
                  ${moreHtml}
                </div>
              `;
            }
            target.querySelectorAll("[data-drill-stock]").forEach((el) => {
              if (el.dataset.bound) return;
              el.dataset.bound = "1";
              el.addEventListener("click", () => {
                openStockContext({
                  type: "stock",
                  stock_code: el.dataset.drillStock,
                  stock_name: el.dataset.drillStockName || "",
                  board_name: node.title || "",
                }).catch((error) => alert(error.message));
              });
            });
            target.querySelectorAll("[data-drill-kline]").forEach((el) => {
              if (el.dataset.bound) return;
              el.dataset.bound = "1";
              el.addEventListener("click", () => openStockKlineModal(el.dataset.drillKline, 240, { stockName: el.dataset.drillStockName || "" }).catch((error) => alert(error.message)));
            });
            target.querySelector(".canvas-more-btn")?.addEventListener("click", (event) => {
              loadCanvasDrilldown(node, event.currentTarget, Number(event.currentTarget.dataset.nextOffset || 0)).catch((error) => alert(error.message));
            });
          }
        } finally {
          if (button) {
            button.disabled = false;
            button.textContent = originalText || "展开相关信息";
          }
        }
      }

      function opportunityCanvasPanel() {
        return $("#opportunityCanvasViewport")?.closest(".opportunity-canvas-panel") || null;
      }

      function syncOpportunityCanvasFullscreenState() {
        const panel = opportunityCanvasPanel();
        const btn = $("#opportunityCanvasFullscreen");
        const active = !!panel && (document.fullscreenElement === panel || panel.dataset.canvasFallbackFullscreen === "1");
        if (panel) panel.classList.toggle("is-canvas-fullscreen", active);
        document.body.classList.toggle("canvas-fullscreen-open", active);
        if (btn) {
          btn.textContent = active ? "退出全屏" : "全屏";
          btn.title = active ? "退出全屏画布" : "全屏查看画布";
        }
      }

      function refreshOpportunityCanvasViewport(fit = false) {
        window.requestAnimationFrame(() => {
          if (fit) fitOpportunityCanvas();
          else applyOpportunityCanvasTransform();
        });
      }

      function bindOpportunityCanvasControls() {
        const viewport = $("#opportunityCanvasViewport");
        if (!viewport || state.opportunityCanvas.bound) return;
        state.opportunityCanvas.bound = true;
        const c = state.opportunityCanvas;
        const clampScale = (nextScale) => Math.max(0.26, Math.min(2.4, nextScale));
        const viewportPoint = (clientX, clientY) => {
          const rect = viewport.getBoundingClientRect();
          return { x: clientX - rect.left, y: clientY - rect.top };
        };
        const viewportCenter = () => {
          const rect = viewport.getBoundingClientRect();
          return { x: rect.width / 2, y: rect.height / 2 };
        };
        const setScale = (nextScale, anchor = viewportCenter()) => {
          const current = c.scale || 1;
          const next = clampScale(nextScale);
          if (Math.abs(next - current) < 0.001) return;
          const ratio = next / current;
          c.offsetX = anchor.x - (anchor.x - c.offsetX) * ratio;
          c.offsetY = anchor.y - (anchor.y - c.offsetY) * ratio;
          c.scale = next;
          applyOpportunityCanvasTransform();
        };
        $("#opportunityCanvasZoomOut")?.addEventListener("click", () => setScale(c.scale / 1.18));
        $("#opportunityCanvasZoomIn")?.addEventListener("click", () => setScale(c.scale * 1.18));
        $("#opportunityCanvasReset")?.addEventListener("click", () => {
          stopOpportunityCanvasInertia();
          fitOpportunityCanvas();
        });
        $("#opportunityCanvasFullscreen")?.addEventListener("click", async () => {
          const panel = opportunityCanvasPanel();
          if (!panel) return;
          const wasActive = document.fullscreenElement === panel || panel.dataset.canvasFallbackFullscreen === "1";
          try {
            if (document.fullscreenElement === panel) {
              await document.exitFullscreen?.();
            } else if (panel.dataset.canvasFallbackFullscreen === "1") {
              panel.dataset.canvasFallbackFullscreen = "0";
            } else if (panel.requestFullscreen) {
              try {
                await panel.requestFullscreen();
              } catch (_) {
                panel.dataset.canvasFallbackFullscreen = "1";
              }
            } else {
              panel.dataset.canvasFallbackFullscreen = "1";
            }
          } finally {
            syncOpportunityCanvasFullscreenState();
            refreshOpportunityCanvasViewport(!wasActive);
          }
        });
        document.addEventListener("fullscreenchange", () => {
          syncOpportunityCanvasFullscreenState();
          refreshOpportunityCanvasViewport();
        });
        $("#opportunityCanvasExport")?.addEventListener("click", async (event) => {
          const btn = event.currentTarget;
          const snapshotId = c.snapshotId;
          const old = btn.textContent;
          btn.disabled = true;
          btn.textContent = "导出中...";
          try {
            const url = snapshotId
              ? `/api/hot-sector-snapshot/${encodeURIComponent(snapshotId)}/export`
              : "/api/opportunity-canvas/export";
            const payload = await fetchJson(url, { method: "POST", timeout: 180000 });
            if (!payload.url) throw new Error("导出完成但未返回下载地址");
            downloadUrl(payload.url, payload.file || "opportunity_canvas.xlsx");
          } catch (error) {
            alert(`导出失败：${error.message}`);
          } finally {
            btn.disabled = false;
            btn.textContent = old;
          }
        });
        if (window.ResizeObserver && !c.resizeObserver) {
          c.resizeObserver = new ResizeObserver(() => refreshOpportunityCanvasViewport());
          c.resizeObserver.observe(viewport);
        } else if (!window.ResizeObserver && !c.resizeBound) {
          c.resizeBound = true;
          window.addEventListener("resize", () => refreshOpportunityCanvasViewport());
        }
        const finishNodeDrag = (event) => {
          const drag = c.nodeDragging;
          if (!drag) return false;
          c.nodeDragging = null;
          viewport.releasePointerCapture?.(drag.pointerId);
          selectOpportunityCanvasNode(drag.id);
          renderOpportunityCanvasMinimap();
          scheduleOpportunityCanvasDraw();
          if (event) {
            event.preventDefault();
            event.stopPropagation();
          }
          return true;
        };
        viewport.addEventListener("wheel", (event) => {
          event.preventDefault();
          stopOpportunityCanvasInertia();
          const horizontalPan = event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY) * 1.2;
          if (horizontalPan) {
            c.offsetX -= event.deltaX || event.deltaY;
            c.offsetY -= event.deltaX ? event.deltaY : 0;
            applyOpportunityCanvasTransform();
            return;
          }
          const zoomFactor = Math.exp(-event.deltaY * 0.0014);
          setScale(c.scale * zoomFactor, viewportPoint(event.clientX, event.clientY));
        }, { passive: false });
        viewport.addEventListener("pointerdown", (event) => {
          if (event.button !== 0 && event.button !== 1) return;
          const hit = event.button === 0 ? opportunityCanvasHitNode(event.clientX, event.clientY) : null;
          event.preventDefault();
          stopOpportunityCanvasInertia();
          viewport.focus?.({ preventScroll: true });
          if (hit && !c.spacePanning) {
            c.nodeDragging = {
              id: hit.id,
              pointerId: event.pointerId,
              startX: event.clientX,
              startY: event.clientY,
              posX: hit.pos.x,
              posY: hit.pos.y,
              moved: false,
            };
            c.hoverId = hit.id;
            viewport.setPointerCapture?.(event.pointerId);
            scheduleOpportunityCanvasDraw();
            return;
          }
          c.dragging = true;
          c.dragStart = { x: event.clientX, y: event.clientY, offsetX: c.offsetX, offsetY: c.offsetY };
          c.lastPanMove = { x: event.clientX, y: event.clientY, t: performance.now() };
          viewport.classList.add("is-panning");
          viewport.setPointerCapture?.(event.pointerId);
        });
        viewport.addEventListener("pointermove", (event) => {
          if (c.nodeDragging) {
            const drag = c.nodeDragging;
            const pos = c.layout?.positions?.get(drag.id);
            if (!pos) return;
            event.preventDefault();
            const dx = (event.clientX - drag.startX) / Math.max(0.1, c.scale || 1);
            const dy = (event.clientY - drag.startY) / Math.max(0.1, c.scale || 1);
            if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
            pos.x = Math.round(drag.posX + dx);
            pos.y = Math.round(drag.posY + dy);
            scheduleOpportunityCanvasDraw();
            return;
          }
          if (!c.dragging || !c.dragStart) {
            const hit = opportunityCanvasHitNode(event.clientX, event.clientY);
            const hoverId = hit?.id || null;
            if (hoverId !== c.hoverId) {
              c.hoverId = hoverId;
              viewport.style.cursor = hoverId && !c.spacePanning ? "pointer" : "";
              scheduleOpportunityCanvasDraw();
            }
            return;
          }
          c.offsetX = c.dragStart.offsetX + event.clientX - c.dragStart.x;
          c.offsetY = c.dragStart.offsetY + event.clientY - c.dragStart.y;
          const now = performance.now();
          if (c.lastPanMove) {
            const dt = Math.max(1, now - c.lastPanMove.t);
            c.panVelocityX = (event.clientX - c.lastPanMove.x) / dt;
            c.panVelocityY = (event.clientY - c.lastPanMove.y) / dt;
          }
          c.lastPanMove = { x: event.clientX, y: event.clientY, t: now };
          applyOpportunityCanvasTransform();
        });
        viewport.addEventListener("pointerup", (event) => {
          if (finishNodeDrag(event)) return;
          c.dragging = false;
          c.dragStart = null;
          c.lastPanMove = null;
          viewport.classList.remove("is-panning");
          viewport.releasePointerCapture?.(event.pointerId);
          startOpportunityCanvasInertia();
        });
        viewport.addEventListener("pointercancel", (event) => {
          if (finishNodeDrag(event)) return;
          c.dragging = false;
          c.dragStart = null;
          c.lastPanMove = null;
          viewport.classList.remove("is-panning");
        });
        viewport.addEventListener("pointerleave", () => {
          if (c.dragging || c.nodeDragging || !c.hoverId) return;
          c.hoverId = null;
          viewport.style.cursor = "";
          scheduleOpportunityCanvasDraw();
        });
        viewport.addEventListener("dblclick", (event) => {
          if (opportunityCanvasHitNode(event.clientX, event.clientY)) return;
          setScale(c.scale * 1.25, viewportPoint(event.clientX, event.clientY));
        });
        document.addEventListener("keydown", (event) => {
          const active = document.activeElement;
          const typing = active && ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName);
          if (event.code !== "Space" || typing || (!viewport.matches(":hover") && active !== viewport)) return;
          event.preventDefault();
          c.spacePanning = true;
          viewport.classList.add("space-pan");
        });
        document.addEventListener("keyup", (event) => {
          if (event.code !== "Space") return;
          c.spacePanning = false;
          viewport.classList.remove("space-pan");
        });
        document.addEventListener("keydown", (event) => {
          if (event.key !== "Escape") return;
          const panel = opportunityCanvasPanel();
          if (!panel || panel.dataset.canvasFallbackFullscreen !== "1") return;
          panel.dataset.canvasFallbackFullscreen = "0";
          syncOpportunityCanvasFullscreenState();
          refreshOpportunityCanvasViewport();
        });
      }

      function renderOpportunityCanvasViewSwitch(canvas) {
        const target = $("#opportunityCanvasViewSwitch");
        if (!target) return;
        const views = opportunityCanvasViews(canvas);
        const activeView = state.opportunityCanvas.view;
        target.innerHTML = views.map((view) => `
          <button class="canvas-view-tab${view.id === activeView ? " active" : ""}" type="button"
                  role="tab"
                  aria-selected="${view.id === activeView ? "true" : "false"}"
                  data-canvas-view="${html(view.id)}"
                  title="${html(view.description || view.label)}">${html(view.label)}</button>
        `).join("");
        target.querySelectorAll("[data-canvas-view]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const view = btn.dataset.canvasView || "hierarchy";
            if (view === state.opportunityCanvas.view) return;
            stopOpportunityCanvasInertia();
            state.opportunityCanvas.view = view;
            state.opportunityCanvas.activeId = "root";
            state.opportunityCanvas.fitOnNextRender = true;
            renderOpportunityCanvas(state.opportunityCanvas.raw);
          });
        });
      }

      // 画布按日切换:头部选择器(默认=最新);切到历史 run → /api/opportunity-canvas
      async function setupOpportunityCanvasDatePicker() {
        const selects = document.querySelectorAll("#opportunityCanvasDateSelect");
        if (!selects.length) return;
        let runs = [];
        try { runs = await loadOpportunityRuns(); } catch (_e) { runs = []; }
        const opts = [`<option value="">最新(默认)</option>`].concat(
          runs.map((r) => `<option value="${html(r.id)}">${html(r.run_at || r.created_at || "--")} · ${html(zhLabel("source", r.source) || "")}</option>`)
        ).join("");
        selects.forEach((sel) => {
          sel.innerHTML = opts;
          sel.value = state.opportunityCanvas.activeRunId || "";
          if (sel.dataset.bound) return;
          sel.dataset.bound = "1";
          sel.addEventListener("change", () => onOpportunityCanvasDateChange(sel.value));
        });
      }

      async function onOpportunityCanvasDateChange(runId) {
        state.opportunityCanvas.activeRunId = runId || null;
        document.querySelectorAll("#opportunityCanvasDateSelect").forEach((s) => { s.value = runId || ""; });
        state.opportunityCanvas.activeId = "root";
        state.opportunityCanvas.fitOnNextRender = true;
        if (!runId) {
          const canvas = state.dashboard?.opportunity?.canvas;
          if (canvas) { renderOpportunityCanvas(canvas); return; }
          try { const p = await fetchJson("/api/opportunity-canvas"); renderOpportunityCanvas(p.canvas); }
          catch (e) { alert(`回到最新失败：${e.message}`); }
          return;
        }
        try {
          const payload = await fetchJson(`/api/opportunity-canvas?run_id=${encodeURIComponent(runId)}`);
          renderOpportunityCanvas(payload.canvas);
          const meta = $("#opportunityCanvasMeta");
          if (meta && payload.date) meta.textContent = `${payload.date} 快照 · ${meta.textContent}`;
        } catch (e) {
          alert(`切换失败：${e.message}`);
        }
      }

      function renderOpportunityCanvas(canvas) {
        const viewport = $("#opportunityCanvasViewport");
        const surface = $("#opportunityCanvasSurface");
        const meta = $("#opportunityCanvasMeta");
        if (!viewport || !surface) return;
        const rawPayload = canvas || { nodes: [], edges: [], stats: {}, views: OPPORTUNITY_CANVAS_VIEW_FALLBACK };
        state.opportunityCanvas.raw = rawPayload;
        const views = opportunityCanvasViews(rawPayload);
        if (!views.some((view) => view.id === state.opportunityCanvas.view)) {
          state.opportunityCanvas.view = views[0]?.id || "hierarchy";
        }
        const payload = opportunityCanvasViewPayload(rawPayload, state.opportunityCanvas.view);
        renderOpportunityCanvasViewSwitch(rawPayload);
        const layout = layoutOpportunityCanvas(payload);
        state.opportunityCanvas.layout = layout;
        const hotRoot = layout.nodeMap.get("hot-sector-root");
        const rawHotRoot = (rawPayload.nodes || []).find((node) => node.id === "hot-sector-root");
        state.opportunityCanvas.snapshotId = (hotRoot || rawHotRoot)?.drilldown?.snapshot_id || null;
        state.opportunityCanvas.hoverId = null;
        state.opportunityCanvas.nodeDragging = null;
        state.opportunityCanvas.textCache?.clear?.();
        viewport.style.cursor = "";
        if (meta) {
          const stats = payload.stats || {};
          const analysisCount = stats.analysis ?? stats.tags ?? 0;
          meta.textContent = `${opportunityCanvasViewLabel(rawPayload, state.opportunityCanvas.view)} · 板块 ${stats.sectors || 0} · 股票 ${stats.stocks || 0} · 分析 ${analysisCount}`;
        }
        bindOpportunityCanvasNodeInteractions();
        const activeNode = layout.nodeMap.get(state.opportunityCanvas.activeId) || layout.nodeMap.get("root") || (payload.nodes || [])[0];
        state.opportunityCanvas.activeId = activeNode?.id || "root";
        renderOpportunityCanvasDetail(activeNode);
        updateOpportunityCanvasSelection(state.opportunityCanvas.activeId);
        renderOpportunityCanvasMinimap();
        bindOpportunityCanvasControls();
        if (state.opportunityCanvas.fitOnNextRender || !state.opportunityCanvas.fitted) {
          state.opportunityCanvas.fitOnNextRender = false;
          state.opportunityCanvas.fitted = true;
          fitOpportunityCanvas();
        } else {
          applyOpportunityCanvasTransform();
        }
      }

      function renderOpportunities(data) {
        const opportunity = data.opportunity || {};
        const report = opportunity.latest_report || {};
        const meta = report.run_meta || {};
        // 时间 + 报告文件 + 评分版本 + 候选来源:区分「展示的是哪次 run/哪版规则」
        const metaBits = [report.updated_at || "--"];
        if (report.file) metaBits.push(report.file);
        if (meta.ruleset_version) metaBits.push(`规则 ${meta.ruleset_version}`);
        if (meta.source) metaBits.push(`来源 ${meta.source}`);
        if (meta.config_hash) metaBits.push(`配置 ${meta.config_hash}`);
        if (report.all_degraded) metaBits.push("数据降级");
        const items = opportunity.items || [];
        const overviewItems = items.slice(0, 10);
        const metaText = [...metaBits, `总览Top10`, `画布全量${items.length}条`].join(" · ");
        document.querySelectorAll("#opportunityMeta").forEach((el) => {
          el.textContent = metaText;
        });
        renderOpportunityCanvas(opportunity.canvas);
        setupOpportunityCanvasDatePicker().catch(() => {});
        document.querySelectorAll("#opportunityList").forEach((list) => {
          list.innerHTML = overviewItems.map((item, index) => {
            const code = stockCodeFromItem(item);
            const rank = item.score_rank || item.rank || index + 1;
            return `<button class="item" type="button" data-stock="${html(code)}" data-stock-code="${html(code)}" data-stock-name="${html(item.stock_name || item.name || "")}" data-sector="${html(item.sector || item.industry || "")}">
              <div class="item-top">
                <p class="item-title">${html(rank)}. ${html(item.stock_name || item.name || code)}</p>
                <strong>${num(item.score)}</strong>
              </div>
              <p class="item-meta">${html(code)} · ${html(item.reason || item.summary || item.industry || "点击查看K线")}</p>
            </button>`;
          }).join("");
          if (!items.length) {
            empty(list, opportunity.empty_reason || "还没有机会报告。", emptyAction("start-opportunity", "启动机会挖掘"));
          } else if (items.length > overviewItems.length) {
            list.insertAdjacentHTML("beforeend", `
              <button class="item opportunity-more-row opportunity-data-menu-btn-inline" type="button">
                <div class="item-top">
                  <p class="item-title">查看全部 ${html(items.length)} 条</p>
                  <span class="pill">全部数据</span>
                </div>
                <p class="item-meta">总览仅显示前 10 条，画布和数据菜单保留全量。</p>
              </button>
            `);
          }
          list.querySelectorAll("[data-stock]").forEach((el) => {
            el.addEventListener("click", async () => {
              loadKline(el.dataset.stock, el.dataset.stockName || "");
              await openStockContext(stockTargetFromDataset(el.dataset));
            });
            el.addEventListener("dblclick", (event) => {
              event.preventDefault();
              openStockKlineModal(el.dataset.stock, 240, { stockName: el.dataset.stockName || "" }).catch((error) => alert(error.message));
            });
          });
          list.querySelector(".opportunity-data-menu-btn-inline")?.addEventListener("click", () => {
            document.querySelector(".opportunity-data-menu-btn")?.click();
          });
        });
        if ($("#opportunityDataDrawer") && !$("#opportunityDataDrawer").hidden && state.opportunityData.tab === "all") {
          renderOpportunityAllData();
        }

        const quant = $("#quantModels");
        const models = opportunity.quant_models || {};
        const quantNote = opportunity.quant_models_note || "";
        const entries = Array.isArray(models)
          ? models.map((value) => [value.name || value.model || "量化模型", value])
          : Object.entries(models);
        const quantNoteHtml = quantNote
          ? `<p class="item-meta" style="margin:0 0 8px;color:#b26a00;">⚠️ ${html(quantNote)}</p>`
          : "";
        quant.innerHTML = quantNoteHtml + entries.map(([name, value]) => `
          <div class="item">
            <div class="item-top">
              <p class="item-title">${html(name)}</p>
              <span class="pill">${typeof value === "object" ? html(value.count ?? value.total ?? "--") : html(value)}</span>
            </div>
            <p class="item-meta">${typeof value === "object" ? html(value.description || value.summary || JSON.stringify(value)) : "模型触发摘要"}</p>
          </div>
        `).join("");
        if (!entries.length) {
          empty(quant, "暂无量化模型摘要。", emptyAction("start-opportunity", "生成摘要"));
        }

        const requested = new URLSearchParams(location.search).get("stock");
        const firstCode = requested || stockCodeFromItem(items[0] || {});
        if (firstCode) {
          const firstItem = items.find((item) => stockCodeFromItem(item) === firstCode) || items[0] || {};
          loadKline(firstCode, firstItem.stock_name || firstItem.name || "");
          if (requested) {
            openStockContext({
              type: "stock",
              stock_code: firstCode,
              stock_name: "",
              board_name: "",
            }).catch((error) => console.warn("打开股票工作台失败", error));
          }
        }
      }

      function klineQuoteText(data) {
        const q = data?.quote;
        if (!q || !(Number(q.price) > 0)) return "";
        const pct = Number(q.change_pct || 0);
        const sign = pct > 0 ? "+" : "";
        return ` · 实时 ¥${num(q.price)} (${sign}${num(pct)}%)`;
      }

      function klineMetaText(data) {
        const records = data?.records || [];
        return `${data?.source || "--"} · ${records.length} 条 · MA/成交量${klineQuoteText(data)}`;
      }

      // A股交易时段（粗判，含集合竞价缓冲；忽略法定节假日）：用于盘中自动刷新K线。
      function isAStockTradingHours() {
        const now = new Date();
        const day = now.getDay();
        if (day === 0 || day === 6) return false;
        const mins = now.getHours() * 60 + now.getMinutes();
        return (mins >= 565 && mins <= 690) || (mins >= 775 && mins <= 905); // 09:25–11:30 / 12:55–15:05
      }

      // 盘中每隔 KLINE_LIVE_REFRESH_MS 重拉当前股票K线（叠加后端实时价），让当日bar跟随最新成交。
      async function refreshKlineLive() {
        const code = state.currentKline?.code;
        if (!code || !isAStockTradingHours()) return;
        const previousName = state.currentKline?.name || "";
        let data;
        try {
          data = await fetchKlineData(code, 500);
        } catch (_e) {
          return; // 盘中拉取失败静默跳过，下个周期再试
        }
        if (!data.records?.length) return;
        data.name = data.name || previousName;
        state.currentKline = data;
        const meta = $("#klineMeta");
        if (meta) meta.textContent = klineMetaText(data);
        renderKlineChart("klineChart", data, { mode: "preview", limit: 160 });
        const modal = $("#klineModal");
        if (modal && !modal.hidden) {
          const limit = state.klineModalLimit || 240;
          renderKlineChart("klineModalChart", data, { mode: "modal", limit });
          const mMeta = $("#klineModalMeta");
          if (mMeta) mMeta.textContent = `${data.source || "--"} · ${data.records.length} 条 · ${klineAxisTitle(limit)}${klineQuoteText(data)}`;
        }
      }

      async function fetchKlineData(code, limit = 500) {
        const payload = await fetchJson(`/api/stock-kline/${encodeURIComponent(code)}?limit=${limit}`);
        return payload.data || {};
      }

      async function loadKline(code, stockName = "") {
        if (!code) return;
        const chart = $("#klineChart");
        const title = $("#klineTitle");
        const meta = $("#klineMeta");
        const titleText = stockName && stockName !== code ? `${stockName} ${code}` : code;
        if (title) title.textContent = `${titleText} K线`;
        if (meta) meta.textContent = "读取中...";
        const openButton = $("#openKlineModalBtn");
        if (openButton) openButton.disabled = true;
        try {
          const data = await fetchKlineData(code, 500);
          data.name = data.name || stockName || "";
          const records = data.records || [];
          const readyTitle = data.name && data.name !== code ? `${data.name} ${code}` : code;
          if (title) title.textContent = `${readyTitle} K线`;
          if (meta) meta.textContent = klineMetaText(data);
          state.currentKline = data;
          if (!records.length || !window.Plotly || !chart) {
            if (chart) {
              chart.innerHTML = `<p class="muted">${html(data.message || "暂无K线数据")}</p>`;
            }
            if (openButton) openButton.disabled = true;
            return;
          }
          renderKlineChart("klineChart", data, { mode: "preview", limit: 160 });
          if (openButton) openButton.disabled = false;
        } catch (error) {
          if (meta) meta.textContent = "读取失败";
          if (chart) chart.innerHTML = `<p class="muted">${html(error.message)}</p>`;
        }
      }

      async function openStockKlineModal(code, limit = 240, options = {}) {
        if (limit && typeof limit === "object") {
          options = limit;
          limit = Number(options.limit || 240);
        }
        if (!code) return;
        const normalizedCode = String(code || "").trim().padStart(6, "0");
        const stockName = options.stockName || options.name || "";
        // 先把弹窗打开给出「读取中」反馈，数据到了再渲染——行情接口慢时按钮不再"点了没反应"。
        const modal = $("#klineModal");
        if (modal) {
          closeOtherStockModals("#klineModal");
          modal.hidden = false;
          modal.setAttribute("aria-hidden", "false");
          syncModalOpenState();
          $("#klineModalTitle").textContent = `${stockName ? `${stockName} ` : ""}${normalizedCode} 股票K线与分析`;
          $("#klineModalMeta").textContent = "K线读取中...";
          const chart = $("#klineModalChart");
          if (chart) chart.innerHTML = `<div class="stock-context-loading">K线读取中…</div>`;
        }
        let data;
        try {
          data = await fetchKlineData(normalizedCode, 500);
        } catch (error) {
          if (modal) closeKlineModal();
          throw error;
        }
        if (!data.records?.length) {
          if (modal) closeKlineModal();
          alert(data.message || "暂无K线数据");
          return;
        }
        data.name = data.name || stockName || "";
        state.currentKline = data;
        openKlineModal(limit);
      }

      function klineStockNameFromContext(context) {
        return context?.stock?.name || state.currentKline?.name || "";
      }

      function klineStockTarget() {
        const code = normalizeStockCode(
          state.currentKline?.code ||
          state.klineModalContext?.stock?.code ||
          state.currentStockContext?.stock?.code,
        );
        return {
          type: "stock",
          stock_code: code,
          stock_name: klineStockNameFromContext(state.klineModalContext),
          board_name: state.klineModalContext?.stock?.sector || "",
        };
      }

      function minimalKlineContext() {
        const target = klineStockTarget();
        const stock = {
          code: target.stock_code,
          name: target.stock_name || state.currentKline?.name || target.stock_code,
          sector: target.board_name || "",
        };
        return {
          stock,
          quote: state.currentKline?.quote || {},
          opportunity: null,
          opportunity_report: null,
          reports: [],
          analysis_results: [],
          news: [],
          social: [],
          trading_clients: { clients: [] },
        };
      }

      function klineActionContext() {
        const contextCode = normalizeStockCode(state.klineModalContext?.stock?.code);
        const currentCode = normalizeStockCode(state.currentKline?.code);
        if (state.klineModalContext && (!currentCode || contextCode === currentCode)) {
          return state.klineModalContext;
        }
        return minimalKlineContext();
      }

      function buildKlineTraces(records, mode) {
        const dates = records.map((r) => r.date);
        const closes = records.map((r) => Number(r.close));
        const volumes = records.map((r) => Number(r.volume || 0));
        const volumeColors = records.map((r) => Number(r.close) >= Number(r.open) ? "rgba(196, 61, 54, 0.42)" : "rgba(25, 135, 84, 0.42)");
        const hoverText = records.map((r) => {
          const cls = klineChangeClass(r.open, r.close);
          const direction = cls === "kline-up" ? "上涨" : cls === "kline-down" ? "下跌" : "平盘";
          return [
            `${r.date}`,
            `开 ${num(r.open)} 高 ${num(r.high)}`,
            `低 ${num(r.low)} 收 ${num(r.close)}`,
            `成交量 ${volumeLabel(r.volume)}`,
            `涨跌 ${num(r.pct_chg)}% · ${direction}`,
          ].join("<br>");
        });
        const traces = [{
          x: dates,
          open: records.map((r) => r.open),
          high: records.map((r) => r.high),
          low: records.map((r) => r.low),
          close: records.map((r) => r.close),
          text: hoverText,
          hoverinfo: "text",
          type: "candlestick",
          name: "K线",
          xaxis: "x",
          yaxis: "y",
          increasing: {
            line: { color: "#c43d36", width: mode === "modal" ? 1.35 : 1.1 },
            fillcolor: "rgba(196, 61, 54, 0.84)",
          },
          decreasing: {
            line: { color: "#198754", width: mode === "modal" ? 1.35 : 1.1 },
            fillcolor: "rgba(25, 135, 84, 0.84)",
          },
        }];
        [
          [5, "#d98c21"],
          [10, "#2f6fdd"],
          [20, "#6f55d8"],
          [60, "#11756f"],
        ].forEach(([windowSize, color]) => {
          if (records.length >= windowSize) {
            traces.push({
              x: dates,
              y: movingAverage(closes, windowSize),
              type: "scatter",
              mode: "lines",
              name: `MA${windowSize}`,
              line: { color, width: mode === "modal" ? 1.8 : 1.25 },
              hoverinfo: "skip",
              xaxis: "x",
              yaxis: "y",
            });
          }
        });
        traces.push({
          x: dates,
          y: volumes,
          type: "bar",
          name: "成交量",
          marker: { color: volumeColors },
          hovertemplate: "%{x}<br>成交量 %{y:,.0f}<extra></extra>",
          xaxis: "x",
          yaxis: "y2",
        });
        return traces;
      }

      function buildKlineLayout(data, records, options = {}) {
        const mode = options.mode || "preview";
        const stats = klineStats(records);
        const firstDate = records[0]?.date || "--";
        const lastDate = records[records.length - 1]?.date || "--";
        const autoDrawings = buildKlineAutoDrawings(records, mode);
        return {
          margin: mode === "modal" ? { l: 62, r: 58, t: 62, b: 42 } : { l: 44, r: 48, t: 44, b: 28 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#fbfdff",
          showlegend: true,
          legend: {
            orientation: "h",
            x: 0,
            y: mode === "modal" ? 1.14 : 1.18,
            font: { size: 11, color: "#344256" },
          },
          hovermode: "x unified",
          dragmode: "pan",
          barmode: "overlay",
          xaxis: {
            rangeslider: { visible: mode === "modal", thickness: 0.08 },
            showspikes: true,
            spikemode: "across",
            spikesnap: "cursor",
            spikecolor: "#96a3b4",
            spikethickness: 1,
            showgrid: true,
            gridcolor: "#eef2f6",
            linecolor: "#c6d0dd",
            tickfont: { size: 11, color: "#6b778a" },
            rangebreaks: [{ bounds: ["sat", "mon"] }],
            rangeselector: mode === "modal" ? {
              x: 0,
              y: 1.16,
            buttons: [
                { count: 1, label: "1月", step: "month", stepmode: "backward" },
                { count: 3, label: "3月", step: "month", stepmode: "backward" },
                { count: 6, label: "6月", step: "month", stepmode: "backward" },
                { step: "all", label: "全部" },
              ],
              bgcolor: "#ffffff",
              activecolor: "#dbeafe",
              bordercolor: "#dbe3ee",
              borderwidth: 1,
              font: { size: 11, color: "#344256" },
            } : undefined,
          },
          shapes: autoDrawings.shapes,
          yaxis: {
            domain: mode === "modal" ? [0.28, 1] : [0.31, 1],
            side: "right",
            fixedrange: false,
            showgrid: true,
            gridcolor: "#eef2f6",
            zeroline: false,
            linecolor: "#c6d0dd",
            tickfont: { size: 11, color: "#6b778a" },
          },
          yaxis2: {
            domain: [0, mode === "modal" ? 0.2 : 0.22],
            side: "right",
            fixedrange: false,
            showgrid: true,
            gridcolor: "#f5f7fa",
            zeroline: false,
            tickfont: { size: 10, color: "#96a3b4" },
          },
          annotations: [{
            xref: "paper",
            yref: "paper",
            x: 0,
            y: mode === "modal" ? 1.08 : 1.1,
            showarrow: false,
            align: "left",
            text: `${html((data.name ? `${data.name} ` : "") + (data.code || ""))} · ${firstDate} - ${lastDate} · 高 ${stats.high} 低 ${stats.low} · 区间 ${stats.delta}%`,
            font: { size: 11, color: "#6b778a" },
          }, ...autoDrawings.annotations],
        };
      }

      function renderKlineChart(targetId, data, options = {}) {
        const target = document.getElementById(targetId);
        if (!target || !window.Plotly) return;
        const limit = Number(options.limit || 160);
        const mode = options.mode || "preview";
        const sourceRecords = data.records || [];
        const records = limit >= 500 ? sourceRecords : sourceRecords.slice(-limit);
        if (!records.length) {
          target.innerHTML = `<p class="muted">${html(data.message || "暂无K线数据")}</p>`;
          return;
        }
        Plotly.react(
          target,
          buildKlineTraces(records, mode),
          buildKlineLayout(data, records, { mode }),
          {
            displayModeBar: mode === "modal",
            displaylogo: false,
            responsive: true,
            scrollZoom: true,
            modeBarButtonsToAdd: mode === "modal" ? ["drawline", "drawopenpath", "drawrect", "eraseshape"] : [],
            modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
          },
        );
      }

      function bindKlineInteractions() {
        const chart = $("#klineChart");
        const openButton = $("#openKlineModalBtn");
        const modal = $("#klineModal");
        const closeButton = $("#closeKlineModalBtn");

        const open = () => {
          if (!state.currentKline) return;
          openKlineModal(240);
        };

        if (chart && !chart.dataset.bound) {
          chart.dataset.bound = "1";
          chart.addEventListener("click", open);
          chart.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              open();
            }
          });
        }

        if (openButton && !openButton.dataset.bound) {
          openButton.dataset.bound = "1";
          openButton.addEventListener("click", open);
        }

        if (closeButton && !closeButton.dataset.bound) {
          closeButton.dataset.bound = "1";
          closeButton.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            closeKlineModal();
          });
        }

        if (modal && !modal.dataset.bound) {
          modal.dataset.bound = "1";
          modal.addEventListener("click", (event) => {
            if (event.target === modal) closeKlineModal();
          });
        }

        document.querySelectorAll("[data-kline-range]").forEach((button) => {
          if (button.dataset.bound) return;
          button.dataset.bound = "1";
          button.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            openKlineModal(Number(button.dataset.klineRange || 240), { reloadContext: false });
          });
        });

        const opportunityButton = $("#klineOpportunityBtn");
        if (opportunityButton && !opportunityButton.dataset.bound) {
          opportunityButton.dataset.bound = "1";
          opportunityButton.addEventListener("click", () => {
            const context = klineActionContext();
            if (context?.stock?.code) startStockOpportunity(context, opportunityButton).catch((error) => alert(error.message));
          });
        }

        const analysisButton = $("#klineAnalysisBtn");
        if (analysisButton && !analysisButton.dataset.bound) {
          analysisButton.dataset.bound = "1";
          analysisButton.addEventListener("click", () => {
            const context = klineActionContext();
            if (context?.stock?.code) startStockAnalysis(context, analysisButton).catch((error) => alert(error.message));
          });
        }

        const tradingButton = $("#klineTradingBtn");
        if (tradingButton && !tradingButton.dataset.bound) {
          tradingButton.dataset.bound = "1";
          tradingButton.addEventListener("click", () => {
            const context = klineActionContext();
            const firstClient = context?.trading_clients?.clients?.[0];
            if (context && firstClient) {
              openTradingClientFromContext(context, firstClient.id, tradingButton);
            } else {
              prependStockContextNotice("未发现可跳转的本地交易软件，请先在个股分析里刷新交易软件。", "info", tradingButton);
            }
          });
        }
      }

      function syncModalOpenState() {
        const anyOpen = ["#klineModal", "#stockContextModal"].some((selector) => {
          const modal = $(selector);
          return modal && !modal.hidden;
        });
        document.body.classList.toggle("modal-open", anyOpen);
      }

      function closeOtherStockModals(activeSelector) {
        if (activeSelector !== "#stockContextModal") {
          const stockModal = $("#stockContextModal");
          if (stockModal && !stockModal.hidden) {
            stockModal.hidden = true;
            stockModal.setAttribute("aria-hidden", "true");
          }
        }
      }

      function renderKlineInsight(context) {
        const target = $("#klineStockInsight");
        if (!target || !context) return;
        const reports = context.reports || [];
        const analysisRows = context.analysis_results || [];
        const newsRows = context.news || [];
        const clients = context.trading_clients?.clients || [];
        target.innerHTML = `
          <div class="kline-insight-section">
            ${stockContextSummary(context)}
          </div>
          <div class="kline-insight-section">
            <div class="panel-header compact-panel-header">
              <h3 class="panel-title">投资机会挖掘</h3>
              <span class="panel-meta">${html(context.opportunity_report?.updated_at || "--")}</span>
            </div>
            <div class="list">${opportunityDetailHtml(context.opportunity)}</div>
          </div>
          <div class="kline-insight-section">
            <div class="panel-header compact-panel-header">
              <h3 class="panel-title">个股分析</h3>
              <span class="panel-meta">${analysisRows.length} 条</span>
            </div>
            <div class="list">${analysisRowsHtml(analysisRows)}</div>
          </div>
          <div class="kline-insight-section">
            <div class="panel-header compact-panel-header">
              <h3 class="panel-title">相关新闻 / 研报</h3>
              <span class="panel-meta">${newsRows.length + reports.length} 条</span>
            </div>
            <div class="list">${newsRowsHtml(newsRows, reports)}</div>
          </div>
          <div class="kline-insight-section">
            <div class="panel-header compact-panel-header">
              <h3 class="panel-title">雪球 / 韭研公社</h3>
              <span class="panel-meta">外部信息</span>
            </div>
            <div class="list">${socialRowsHtml(context.social || [])}</div>
          </div>
        `;
        const status = $("#klineInsightStatus");
        if (status) {
          status.textContent = `已读取 ${analysisRows.length + reports.length + newsRows.length} 条信息`;
          status.className = "pill ok";
        }
        $("#klineOpportunityBtn").disabled = false;
        $("#klineAnalysisBtn").disabled = false;
        $("#klineTradingBtn").disabled = false;
      }

      async function loadKlineModalContext() {
        const target = $("#klineStockInsight");
        const code = normalizeStockCode(state.currentKline?.code);
        if (!target || !code) return;
        target.innerHTML = `
          <div class="kline-insight-title">
            <h3>${html(state.currentKline?.name || "股票分析工作台")} ${html(code)}</h3>
            <span>机会 · 分析 · 资讯</span>
          </div>
          <div class="stock-context-loading">正在读取股票分析...</div>
        `;
        const status = $("#klineInsightStatus");
        if (status) {
          status.textContent = "股票分析读取中";
          status.className = "pill warn";
        }
        $("#klineOpportunityBtn").disabled = false;
        $("#klineAnalysisBtn").disabled = false;
        $("#klineTradingBtn").disabled = false;
        try {
          const name = state.currentKline?.name || "";
          const context = await fetchJson(`/api/stock-context/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}`);
          state.klineModalContext = context;
          state.currentStockContext = context;
          renderKlineInsight(context);
        } catch (error) {
          target.innerHTML = `<div class="notice status error">${html(error.message)}</div>`;
          if (status) {
            status.textContent = "股票分析失败";
            status.className = "pill bad";
          }
        }
      }

      function updateKlineRangeButtons(limit) {
        document.querySelectorAll("[data-kline-range]").forEach((button) => {
          const active = Number(button.dataset.klineRange || 0) === Number(limit);
          button.classList.toggle("active", active);
          button.setAttribute("aria-pressed", active ? "true" : "false");
        });
      }

      function openKlineModal(limit = 240, options = {}) {
        if (!state.currentKline) return;
        state.klineModalLimit = limit;
        closeOtherStockModals("#klineModal");
        const modal = $("#klineModal");
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        syncModalOpenState();
        const modalTitle = state.currentKline.name && state.currentKline.name !== state.currentKline.code
          ? `${state.currentKline.name} ${state.currentKline.code}`
          : (state.currentKline.code || "");
        $("#klineModalTitle").textContent = `${modalTitle} 股票K线与分析`;
        $("#klineModalMeta").textContent = `${state.currentKline.source || "--"} · ${state.currentKline.records?.length || 0} 条 · ${klineAxisTitle(limit)}${klineQuoteText(state.currentKline)}`;
        $("#klineModalSource").textContent = state.currentKline.source || "--";
        const records = limit >= 500 ? (state.currentKline.records || []) : (state.currentKline.records || []).slice(-limit);
        const stats = klineStats(records);
        $("#klineModalRange").textContent = `区间 ${stats.delta}% · 高 ${stats.high} / 低 ${stats.low}`;
        $("#klineModalVolume").textContent = `均量 ${stats.volume}`;
        updateKlineRangeButtons(limit);
        const currentCode = normalizeStockCode(state.currentKline?.code);
        const contextCode = normalizeStockCode(state.klineModalContext?.stock?.code);
        const shouldReloadContext = options.reloadContext ?? (currentCode && currentCode !== contextCode);
        if (shouldReloadContext) {
          state.klineModalContext = null;
          loadKlineModalContext();
        }
        window.setTimeout(() => {
          renderKlineChart("klineModalChart", state.currentKline, { mode: "modal", limit });
        }, 30);
      }

      function closeKlineModal() {
        const modal = $("#klineModal");
        if (!modal) return;
        if (window.Plotly && $("#klineModalChart")) {
          Plotly.purge("klineModalChart");
        }
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        state.klineModalContext = null;
        syncModalOpenState();
      }

      document.addEventListener("keydown", (event) => {
        const modal = $("#klineModal");
        if (event.key === "Escape" && modal && !modal.hidden) {
          closeKlineModal();
          return;
        }
        const stockModal = $("#stockContextModal");
        if (event.key === "Escape" && stockModal && !stockModal.hidden) {
          closeStockContext();
        }
      });

      const JOB_TYPE_LABELS = {
        opportunity_discovery: "机会挖掘",
        batch_analysis: "批量分析",
        pattern_refresh: "指纹库刷新",
      };
      const JOB_STATUS_LABELS = {
        queued: "排队中",
        running: "运行中",
        finished: "已完成",
        failed: "失败",
      };

      function isActiveJob(job) {
        return ["queued", "running"].includes(job?.status);
      }

      function jobTypeLabel(job) {
        return JOB_TYPE_LABELS[job?.type] || job?.type || "后台任务";
      }

      function jobStatusLabel(status) {
        return JOB_STATUS_LABELS[status] || status || "--";
      }

      function jobPillClass(status) {
        if (status === "finished") return "ok";
        if (status === "failed") return "bad";
        if (status === "running" || status === "queued") return "warn";
        return "";
      }

      function jobStatusClass(status) {
        if (status === "finished") return "success";
        if (status === "failed") return "error";
        if (status === "running" || status === "queued") return "warning";
        return "info";
      }

      function latestJobLog(job) {
        return (job?.logs || []).slice(-1)[0] || "";
      }

      function jobCreatedAt(job) {
        return String(job?.created_at || job?.started_at || "").replace("T", " ").slice(0, 19);
      }

      function jobResultLinks(job) {
        const result = job?.result || {};
        const links = [];
        if (result.top_report_url) links.push(`<button class="button secondary" type="button" data-preview-url="${html(result.top_report_url)}" data-preview-label="Top榜">打开Top榜</button>`);
        if (result.report_url && result.report_url !== result.top_report_url) links.push(`<button class="button secondary" type="button" data-preview-url="${html(result.report_url)}" data-preview-label="报告">打开报告</button>`);
        if (result.csv_url)    links.push(`<button class="button secondary" type="button" data-preview-url="${html(result.csv_url)}" data-preview-label="CSV">打开CSV</button>`);
        if (result.json_url)   links.push(`<button class="button secondary" type="button" data-preview-url="${html(result.json_url)}" data-preview-label="明细">打开明细</button>`);
        return links.join("");
      }

      function jobStockLinks(job) {
        const result = job?.result || {};
        const stocks = Array.isArray(result.stocks) ? result.stocks : [];
        if (job?.type !== "batch_analysis" || !stocks.length) return "";
        const total = result.passed_count != null ? result.passed_count : stocks.length;
        const hint = `通过 ${total} 只${result.stocks_truncated ? `（显示前 ${stocks.length} 只）` : ""} · 点击查看个股分析`;
        const btns = stocks.map((s) => {
          const meta = [s.score != null ? num(s.score) : "", s.rating || ""].filter(Boolean).join(" · ");
          return `<button class="button secondary job-stock-btn" type="button" data-stock-code="${html(s.code || "")}" data-stock-name="${html(s.name || "")}" title="查看个股分析">${html(s.code || "")}${meta ? ` · ${meta}` : ""}</button>`;
        }).join("");
        return `<p class="item-meta" style="margin-top:10px">${hint}</p><div class="job-result-row">${btns}</div>`;
      }

      function jobResultText(job) {
        const result = job?.result || {};
        if (job?.status === "failed") return job.error || "任务失败，请查看日志。";
        if (job?.type === "opportunity_discovery" && result.report_path) {
          const scope = result.mode_label || (result.mode === "specified_pool" ? "指定股票池" : "全市场扫描");
          const source = result.source_label ? ` · ${result.source_label}` : "";
          return `${scope}${source} · 报告已生成：${result.report_path}`;
        }
        if (job?.type === "batch_analysis" && result.rows != null) return `批量分析完成，通过股票 ${result.rows} 只`;
        if (job?.status === "finished") return "任务已完成。";
        return latestJobLog(job) || "任务正在执行。";
      }

      function updateTaskHeader(jobs) {
        const target = $("#activeTaskMeta");
        if (!target) return;
        const active = (jobs || []).find(isActiveJob);
        const latest = active || (jobs || [])[0];
        if (!latest) {
          target.className = "task-meta";
          target.textContent = "暂无任务";
          return;
        }
        target.className = `task-meta ${jobPillClass(latest.status)}`;
        const prefix = isActiveJob(latest) ? "进行中" : "最近结果";
        const log = latestJobLog(latest).replace(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*/, "");
        target.textContent = `${prefix}: ${jobTypeLabel(latest)} · ${jobStatusLabel(latest.status)}${log ? " · " + log.slice(0, 42) : ""}`;
      }

      function updateFeatureJobPill(jobs) {
        const target = $("#featureJobStatus");
        if (!target) return;
        const active = (jobs || []).find(isActiveJob);
        const latest = active || (jobs || [])[0];
        if (!latest) {
          target.textContent = "暂无任务";
          target.className = "pill";
          return;
        }
        target.textContent = `${jobTypeLabel(latest)} ${jobStatusLabel(latest.status)}`;
        target.className = `pill ${jobPillClass(latest.status)}`;
      }

      // 是否有后台任务进行中（排队/运行）。用于在任务期间锁定所有"会启动任务"的按钮，避免重复提交导致任务叠加。
      function jobLocked() {
        return (state.jobs || []).some(isActiveJob);
      }

      // 单一真相源：每次任务状态变化都经 renderJobs 调用本函数重算所有启动按钮的禁用态。
      // 公式统一为 disabled = 有任务进行中(locked) || 按钮自身前置条件未满足(own)，按钮各自的交互处理器也用同一公式，二者天然一致，无需保存/还原历史态。
      function applyJobLockUI(jobs) {
        const locked = (jobs || []).some(isActiveJob);
        // 纯启动按钮：唯一禁用理由就是"有任务在跑"。锁定时置灰并改文案，解锁还原原文案。
        document
          .querySelectorAll('#opportunityForm button[type="submit"], #batchForm button[type="submit"], #refreshPatternDbBtn, #featureRefreshPatternDbBtn')
          .forEach((btn) => {
            btn.disabled = locked;
            btn.classList.toggle("job-locked", locked);
            if (locked) {
              if (!("jobLockLabel" in btn.dataset)) {
                btn.dataset.jobLockLabel = btn.textContent;
                btn.textContent = "任务进行中…";
              }
            } else if ("jobLockLabel" in btn.dataset) {
              btn.textContent = btn.dataset.jobLockLabel;
              delete btn.dataset.jobLockLabel;
            }
          });
        // 自带前置条件的按钮：禁用 = 有任务 || 自身条件未满足（文案不动，避免与"无曲线/未出匹配"等本身的禁用语义冲突）。
        const matchDraw = $("#matchDrawBtn");
        if (matchDraw) matchDraw.disabled = locked || (state.drawPoints?.length || 0) < 5;
        const matchStock = $("#matchStockBtn");
        if (matchStock) matchStock.disabled = locked || !state.selectedCurve;
        const patternBacktest = $("#patternBacktestBtn");
        if (patternBacktest) patternBacktest.disabled = locked || !(state.lastBacktest?.codes?.length);
      }

      function renderJobDetail(job) {
        const summary = $("#jobDetailSummary");
        const logs = $("#jobLogStream");
        if (!summary || !logs) return;
        if (!job) {
          $("#jobDetailTitle").textContent = "任务日志";
          $("#jobDetailMeta").textContent = "选择或启动任务";
          summary.className = "notice status info";
          summary.textContent = "启动任务后这里会实时展示进度、日志和结果。";
          $("#jobDetailActions").innerHTML = "";
          logs.innerHTML = `<div class="job-log-empty">暂无日志</div>`;
          return;
        }

        $("#jobDetailTitle").textContent = `${jobTypeLabel(job)} · ${job.id}`;
        $("#jobDetailMeta").textContent = `${jobStatusLabel(job.status)} · ${jobCreatedAt(job) || "--"}`;
        summary.className = `notice status ${jobStatusClass(job.status)}`;
        summary.textContent = jobResultText(job);
        $("#jobDetailActions").innerHTML = jobResultLinks(job) + jobStockLinks(job);
        bindHotStockClicks($("#jobDetailActions"));

        const rows = (job.logs || []).map((line) => `<div class="job-log-line">${html(line)}</div>`).join("");
        logs.innerHTML = rows || `<div class="job-log-empty">暂无日志</div>`;
        logs.scrollTop = logs.scrollHeight;
      }

      function renderJobs(jobs) {
        renderJobsDrawer(jobs);
        applyJobLockUI(jobs);
        const target = $("#jobList");
        if (!target) return;
        target.innerHTML = (jobs || []).map((job) => {
          const active = state.activeJobId === job.id ? " active" : "";
          const resultLinks = jobResultLinks(job);
          return `
            <div class="item job-item${active}" data-job-id="${html(job.id)}" role="button" tabindex="0">
              <div class="item-top">
                <p class="item-title">${html(jobTypeLabel(job))} · ${html(job.id)}</p>
                <span class="pill ${jobPillClass(job.status)}">${html(jobStatusLabel(job.status))}</span>
              </div>
              <p class="item-meta">${html(jobCreatedAt(job) || "--")} · ${html(latestJobLog(job) || "暂无日志")}</p>
              ${resultLinks ? `<div class="job-result-row">${resultLinks}</div>` : ""}
            </div>
          `;
        }).join("");
        if (!jobs?.length) {
          empty(target, "暂无任务。");
          renderJobDetail(null);
          return;
        }
        target.querySelectorAll("[data-job-id]").forEach((el) => {
          const select = () => {
            state.activeJobId = el.dataset.jobId;
            renderJobs(state.jobs);
            renderJobDetail(state.jobs.find((job) => job.id === state.activeJobId));
          };
          el.addEventListener("click", (event) => {
            if (event.target.closest("a")) return;
            select();
          });
          el.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              select();
            }
          });
        });
      }

      function mergeJobSnapshot(job) {
        if (!job?.id) return;
        state.jobs = [job, ...(state.jobs || []).filter((item) => item.id !== job.id)];
        if (!state.activeJobId || state.activeJobId === job.id || isActiveJob(job)) {
          state.activeJobId = job.id;
        }
        renderJobs(state.jobs);
        updateTaskHeader(state.jobs);
        updateFeatureJobPill(state.jobs);
        renderJobDetail(state.jobs.find((item) => item.id === state.activeJobId) || job);
      }

      function scheduleJobPolling(jobs) {
        if (!(jobs || []).some(isActiveJob) || state.jobPollTimer) return;
        state.jobPollTimer = window.setTimeout(async () => {
          state.jobPollTimer = null;
          try {
            await loadJobs();
          } catch (error) {
            const target = $("#activeTaskMeta");
            if (target) target.textContent = `任务刷新失败: ${error.message}`;
          }
        }, 1500);
      }

      async function loadJobs(options = {}) {
        const data = await fetchJson("/api/jobs");
        state.jobs = data.jobs || [];
        if (options.selectJobId) state.activeJobId = options.selectJobId;
        if (!state.activeJobId && state.jobs.length) {
          state.activeJobId = (state.jobs.find(isActiveJob) || state.jobs[0]).id;
        }
        renderJobs(state.jobs);
        updateTaskHeader(state.jobs);
        updateFeatureJobPill(state.jobs);
        renderJobDetail(state.jobs.find((job) => job.id === state.activeJobId) || state.jobs[0] || null);
        scheduleJobPolling(state.jobs);
        return state.jobs;
      }

      function opportunityReportFileFromJob(job) {
        const result = job?.result || {};
        if (result.top_report_file) return result.top_report_file;
        if (result.report_file) return result.report_file;
        const raw = String(result.top_report_url || result.top_report_path || result.report_url || result.report_path || "");
        const match = raw.match(/opportunity_top10_\d{8}_\d{6}\.md/);
        return match ? match[0] : "";
      }

      async function renderOpportunityReportFromJob(job) {
        if (job?.type !== "opportunity_discovery" || !$("#opportunityList")) return false;
        const file = opportunityReportFileFromJob(job);
        if (!file) return false;
        const payload = await fetchJson(`/api/opportunity-report?file=${encodeURIComponent(file)}`);
        renderOpportunities({
          opportunity: {
            latest_report: payload.latest_report || {
              file: payload.file || file,
              url: payload.url || job.result?.top_report_url || job.result?.report_url || "",
              updated_at: payload.updated_at || "--",
            },
            market_env: payload.market_env || "",
            empty_reason: payload.all_degraded
              ? "本次机会报告全部候选缺少有效历史行情数据，已隐藏诊断性 Top 榜，避免误当正常推荐。"
              : "",
            items: payload.all_degraded ? [] : (payload.items || payload.cards || []),
            canvas: payload.canvas,
            quant_models: payload.quant_models || {},
            quant_models_note: payload.quant_models_note || "",
          },
        });
        return true;
      }

      async function refreshVisibleResultsAfterJob(job) {
        if (job?.status !== "finished") return;
        if (!["opportunity_discovery", "batch_analysis"].includes(job.type)) return;
        let renderedCurrentOpportunity = false;
        if (job.type === "opportunity_discovery") {
          try {
            renderedCurrentOpportunity = await renderOpportunityReportFromJob(job);
          } catch (error) {
            console.warn("刷新本次机会报告失败", error);
          }
        }
        try {
          const data = await loadDashboard();
          if ($("#opportunityList") && !renderedCurrentOpportunity) renderOpportunities(data);
          if ($("#reportList")) renderReports(data);
        } catch (error) {
          console.warn("刷新任务结果失败", error);
        }
      }

      async function pollJob(jobId, options = {}) {
        const {
          statusEl = null,
          onDone = null,
          onUpdate = null,
          intervalMs = 1500,
          maxAttempts = 120,
        } = options;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
          const data = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
          const job = data.job || {};
          mergeJobSnapshot(job);
          if (statusEl) {
            const latestLog = latestJobLog(job);
            statusEl.className = `notice status ${jobStatusClass(job.status)}`;
            statusEl.textContent = `${jobStatusLabel(job.status)} · ${latestLog || jobId}`;
          }
          if (onUpdate) await onUpdate(job);
          if (["finished", "failed"].includes(job.status)) {
            if (onDone) await onDone(job);
            await loadJobs({ selectJobId: job.id });
            return job;
          }
          await new Promise((resolve) => setTimeout(resolve, intervalMs));
        }
        return null;
      }

      async function startTrackedJob(endpoint, payload, submitButton = null) {
        if (submitButton) submitButton.disabled = true;
        try {
          const data = await fetchJson(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const job = data.job;
          if (job) {
            mergeJobSnapshot(job);
            await loadJobs({ selectJobId: job.id });
            pollJob(job.id, {
              onDone: refreshVisibleResultsAfterJob,
            }).catch((error) => {
              const summary = $("#jobDetailSummary");
              if (summary) {
                summary.className = "notice status error";
                summary.textContent = error.message;
              }
            });
            return job;
          }
          return data;
        } catch (error) {
          alert(error.message);
          return null;
        } finally {
          // 先清掉对“触发按钮”的即时禁用：覆盖动态渲染的按钮（如个股操作区“机会挖掘”），它们不在统一锁定清单里，
          // 否则会永久卡在禁用态。随后 applyJobLockUI 按真实任务状态对标准启动按钮做权威锁定：
          // 任务在跑→重新禁用并显示“任务进行中…”，直到轮询结束(loadJobs→renderJobs)才解锁。
          // 两步同步相邻执行、中间无渲染，不存在可点窗口。修复原 bug：pollJob 未 await，
          // finally 在任务刚创建时即触发，导致任务进行中的标准启动按钮被错误恢复为可点。
          if (submitButton) submitButton.disabled = false;
          applyJobLockUI(state.jobs);
        }
      }

      function stockContextSummary(context) {
        const stock = context.stock || {};
        const quote = context.quote || {};
        const kline = context.kline_summary || {};
        const opportunity = context.opportunity || {};
        const quoteText = quote ? `${num(quote.price)} · ${num(quote.change_pct)}%` : "--";
        const klineText = kline.available
          ? `${kline.records || 0} 条 · 收 ${num(kline.latest_close)} · 区间 ${num(kline.range_change_pct)}%`
          : (kline.message || "暂无K线数据");
        return `
          <div class="stock-context-summary">
            <div class="metric compact-metric">
              <span>行情</span>
              <strong class="${changeClass(quote.change_pct)}">${html(quoteText)}</strong>
              <small class="muted">${html(quote.updated_at || quote.source || "--")}</small>
            </div>
            <div class="metric compact-metric">
              <span>机会评分</span>
              <strong>${opportunity.score != null ? num(opportunity.score) : "--"}</strong>
              <small class="muted">${html(opportunity.rating || opportunity.recommendation || "未入选最新机会榜")}</small>
            </div>
            <div class="metric compact-metric">
              <span>K线</span>
              <strong>${html(kline.available ? num(kline.latest_close) : "--")}</strong>
              <small class="muted">${html(klineText)}</small>
            </div>
          </div>
        `;
      }

      function opportunityDetailHtml(opportunity) {
        if (!opportunity) {
          return `<div class="item empty-state"><p class="item-meta">最新机会榜暂无该股票，启动机会挖掘后会在任务日志和报告里更新。</p></div>`;
        }
        const fields = [
          ["入选原因", opportunity.reason || opportunity.summary],
          ["板块", opportunity.sector || opportunity.industry],
          ["技术", opportunity.technical],
          ["量化", opportunity.quant],
          ["情绪资金", opportunity.sentiment],
          ["风险/加减分", opportunity.risk],
        ].filter(([, value]) => value);
        const title = opportunity.stock_name || opportunity.name || opportunity.stock_code;
        const targetAttr = klineTargetAttr(opportunity.stock_code, opportunity.stock_name || opportunity.name);
        return `
          <div class="item">
            <div class="item-top">
              <p class="item-title" ${targetAttr}>${html(title)}</p>
              <span class="pill ${Number(opportunity.score || 0) >= 80 ? "ok" : "warn"}">${html(opportunity.rating || "评分")} ${num(opportunity.score)}</span>
            </div>
            <p class="item-meta">${html(opportunity.recommendation || "")}</p>
            <div class="stock-context-fields">
              ${fields.map(([label, value]) => `<div><b>${html(label)}</b><span>${html(value)}</span></div>`).join("")}
            </div>
          </div>
        `;
      }

      function reportRowsHtml(reports = []) {
        if (!reports.length) {
          return `<div class="item empty-state"><p class="item-meta">暂无该股票本地报告。</p></div>`;
        }
        return reports.map((item) => `
          <div class="item item-clickable" role="button" tabindex="0" data-preview-url="${html(item.url||'')}" data-preview-label="${html(item.file||'报告')}">
            <div class="item-top">
              <p class="item-title">${html(item.file)}</p>
              <span class="pill">${html(item.type || "报告")}</span>
            </div>
            <p class="item-meta">${html(item.updated_at || "--")} · ${html(item.size_kb || "--")} KB</p>
          </div>
        `).join("");
      }

      function analysisRowsHtml(rows = []) {
        if (!rows.length) {
          return `
            <div class="item empty-state">
              <p class="item-meta">暂无该股票本地批量分析结果，可查看综合研判总结。</p>
              <div class="actions">
                <button class="button secondary compact" type="button" data-stock-action="analysis">查看综合研判</button>
              </div>
            </div>
          `;
        }
        return rows.map((item) => `
          <div class="item item-clickable" role="button" tabindex="0" data-preview-url="${html(item.url||'')}" data-preview-label="${html(item.file||'批量分析结果')}">
            <div class="item-top">
              <p class="item-title">${html(item.file || "批量分析结果")}</p>
              <span class="pill">${html(item.updated_at || "--")}</span>
            </div>
            <div class="stock-context-fields">
              ${(item.fields || []).slice(0, 8).map((field) => `<div><b>${html(field.label)}</b><span>${html(field.value)}</span></div>`).join("")}
            </div>
          </div>
        `).join("");
      }

      function socialRowsHtml(social = []) {
        if (!social.length) {
          return `<div class="item empty-state"><p class="item-meta">暂无社区入口。</p></div>`;
        }
        return social.map((item) => `
          <a class="item" href="${html(item.url || "#")}" target="_blank" rel="noreferrer">
            <div class="item-top">
              <p class="item-title">${html(item.platform)} · ${html(item.title)}</p>
              <span class="pill">${html(item.status === "external_link" ? "直达" : "缓存")}</span>
            </div>
            <p class="item-meta">${html(item.summary || "")}</p>
          </a>
        `).join("");
      }

      function newsRowsHtml(news = [], reports = []) {
        const newsRows = (news || []).map((item) => `
          <a class="item" href="${html(item.url || "#")}" target="_blank" rel="noreferrer">
            <div class="item-top">
              <p class="item-title">${html(item.platform || "资讯")} · ${html(item.title || "")}</p>
              <span class="pill">${html(item.status === "external_link" ? "检索" : "本地")}</span>
            </div>
            <p class="item-meta">${html(item.summary || "")}</p>
          </a>
        `);
        const reportRows = (reports || []).slice(0, 4).map((item) => `
          <a class="item" href="${html(item.url || "#")}" target="_blank" rel="noreferrer">
            <div class="item-top">
              <p class="item-title">本地报告 · ${html(item.file)}</p>
              <span class="pill">${html(item.type || "报告")}</span>
            </div>
            <p class="item-meta">${html(item.updated_at || "--")} · ${html(item.size_kb || "--")} KB</p>
          </a>
        `);
        const rows = [...newsRows, ...reportRows];
        return rows.length ? rows.join("") : `<div class="item empty-state"><p class="item-meta">暂无相关新闻或研报入口。</p></div>`;
      }

      function tradingClientRowsHtml(context) {
        const clients = context.trading_clients?.clients || [];
        if (!clients.length) {
          return `
            <div class="item empty-state">
              <p class="item-meta">未发现可跳转的本地交易软件。</p>
              <div class="actions">
                <button class="button secondary compact" type="button" data-stock-action="refresh-trading-clients">重新检测</button>
              </div>
            </div>
          `;
        }
        const stock = context.stock || {};
        return clients.map((client) => `
          <button class="item stock-trading-client" type="button" data-client-id="${html(client.id)}">
            <div class="item-top">
              <p class="item-title">${html(client.display_name || client.name || "交易软件")}</p>
              <span class="pill">${html((client.capabilities?.direct_targets || []).includes("stock") ? "协议直连" : "快捷输入")}</span>
            </div>
            <p class="item-meta">${html(stock.code || "--")} · ${html(client.path || client.bundle_id || client.platform || "")}</p>
          </button>
        `).join("");
      }

      function renderStockContext(context) {
        const stock = context.stock || {};
        const body = $("#stockContextBody");
        const reports = context.reports || [];
        const analysisRows = context.analysis_results || [];
        $("#stockContextTitle").textContent = stockDisplayName(stock);
        const boards = Array.isArray(stock.boards) ? stock.boards.filter(Boolean) : [];
        const boardText = boards.length ? boards.join(" / ") : (stock.sector && stock.sector !== "—" ? stock.sector : "--");
        $("#stockContextMeta").textContent = `${stock.code || "--"} · ${boardText}`;
        body.innerHTML = `
          <div class="stock-context-grid">
            <section class="stock-context-main">
              ${stockContextSummary(context)}
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">个股机会</h3>
                  <span class="panel-meta">${html(context.opportunity_report?.updated_at || "--")}</span>
                </div>
                <div class="panel-body list" id="stockOpportunityPanel">${opportunityDetailHtml(context.opportunity)}</div>
              </div>
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">个股分析结果</h3>
                  <span class="panel-meta" id="stockAnalysisPanelMeta">${analysisRows.length} 条</span>
                </div>
                <div class="panel-body list" id="stockAnalysisPanel">${analysisRowsHtml(analysisRows)}</div>
              </div>
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">本地报告</h3>
                  <span class="panel-meta">${reports.length} 条</span>
                </div>
                <div class="panel-body list">${reportRowsHtml(reports)}</div>
              </div>
            </section>
            <aside class="stock-context-side">
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">操作</h3>
                  <span class="panel-meta">股票级</span>
                </div>
                <div class="panel-body">
                  <div class="stock-context-actions">
                    <button class="button" type="button" data-stock-action="trading-primary" ${context.trading_clients?.clients?.length ? "" : "disabled"}>打开交易软件</button>
                    <button class="button" type="button" data-stock-action="opportunity">机会挖掘</button>
                    <button class="button secondary" type="button" data-stock-action="analysis">个股分析</button>
                    <button class="button secondary" type="button" data-stock-action="kline">K线大图</button>
                  </div>
                </div>
              </div>
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">交易软件</h3>
                  <div class="panel-header-actions">
                    <span class="panel-meta">${context.trading_clients?.platform || "--"}</span>
                    <button class="button secondary compact" type="button" data-stock-action="refresh-trading-clients">刷新</button>
                  </div>
                </div>
                <div class="panel-body list">${tradingClientRowsHtml(context)}</div>
              </div>
              <div class="panel">
                <div class="panel-header">
                  <h3 class="panel-title">雪球 / 韭研公社</h3>
                  <span class="panel-meta">外部信息</span>
                </div>
                <div class="panel-body list">${socialRowsHtml(context.social || [])}</div>
              </div>
            </aside>
          </div>
        `;
        bindStockContextActions(context);
      }

      async function startStockOpportunity(context, button = null) {
        const code = context.stock?.code;
        if (!code) return;
        const panel = $("#stockOpportunityPanel");
        const job = await startTrackedJob("/api/opportunity-discovery/start", {
          limit: OPPORTUNITY_CLI_DEFAULTS.limit,
          workers: OPPORTUNITY_CLI_DEFAULTS.workers,
          source: OPPORTUNITY_CLI_DEFAULTS.source,
          stock_codes: code,
        }, button);
        if (!job) return;
        if (panel) {
          panel.innerHTML = `<div class="item empty-state" id="stockOpportunityProgress">
            <p class="item-meta"><span class="spinner"></span> 指定股票池机会挖掘进行中… (${html(job.id)})</p>
          </div>`;
        }
        await pollJob(job.id, {
          onUpdate: (j) => {
            const note = document.getElementById("stockOpportunityProgress");
            if (note) {
              const log = latestJobLog(j) || jobStatusLabel(j.status);
              note.querySelector("p").innerHTML = `<span class="spinner"></span> ${html(log)}`;
            }
          },
          onDone: async (j) => {
            await refreshStockContextInPlace(code, context.stock?.name || "");
            if (j.status === "failed") {
              prependStockContextNotice(`机会挖掘失败: ${latestJobLog(j) || j.id}`, "error", button);
            }
          },
        });
      }

      // 「个股分析」改为只展示综合研判总结（综合总览 tab 顶部），不再触发批量分析 CSV 任务。
      async function startStockAnalysis(context, button = null) {
        const code = context.stock?.code;
        if (!code) return;
        // 个股弹窗未打开（如从 K线弹窗触发）则先打开它——会加载 suite 并渲染，避免渲染进隐藏弹窗。
        const modal = document.getElementById("stockContextModal");
        const alreadyOpen = modal && !modal.hidden && state.currentStockCode === code;
        if (!alreadyOpen) {
          await openStockContext({ stock_code: code, stock_name: context.stock?.name || "" });
        }
        const navBtn = document.querySelector('#stockSuiteTabs button.suite-tab[data-suite-tab="overview"]');
        if (navBtn) navBtn.click();  // 复用 tab 切换逻辑：激活态 / 面板可见性 / 加载态 / 渲染
        // 已加载则立即（重）渲染；仍在加载时切换逻辑会显示「数据加载中…」，
        // 加载完成后 openStockContext 的 renderActiveSuiteTab 会补渲染。
        if (!state.suiteFetching && state.currentSuitePayload) {
          renderSuiteOverview(state.currentSuitePayload);
        }
        requestAnimationFrame(() => {
          const card = document.querySelector("#suitePaneOverview .suite-summary-card");
          if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }

      async function refreshStockContextInPlace(code, name = "") {
        try {
          const fresh = await fetchJson(`/api/stock-context/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}`);
          state.currentStockContext = fresh;
          renderStockContext(fresh);
        } catch (error) {
          console.warn("refresh stock context failed", error);
        }
      }

      async function refreshStockSuiteInPlace(code, name = "") {
        state.suiteFetching = true;
        try {
          const fresh = await fetchJson(`/api/stock-analysis-suite/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}&refresh=1`);
          state.currentSuitePayload = fresh;
        } catch (error) {
          console.warn("refresh stock suite failed", error);
        } finally {
          state.suiteFetching = false;
          renderActiveSuiteTab();
        }
      }

      function stockNoticeTarget(button = null) {
        if (button?.closest?.("#klineModal")) return $("#klineStockInsight");
        return $("#stockContextBody") || $("#klineStockInsight");
      }

      function prependStockContextNotice(message, type = "info", button = null) {
        const body = stockNoticeTarget(button);
        if (!body) return;
        const notice = document.createElement("div");
        notice.className = `notice status ${type}`;
        notice.textContent = message;
        body.prepend(notice);
      }

      async function openTradingClientFromContext(context, clientId, button = null) {
        const stock = context.stock || {};
        if (!clientId || !stock.code) return;
        if (button) button.disabled = true;
        try {
          const payload = await fetchJson("/api/trading-clients/open", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              client_id: clientId,
              target: {
                type: "stock",
                stock_code: stock.code,
                stock_name: stock.name || "",
                board_name: stock.sector || "",
              },
            }),
          });
          const meta = button?.querySelector(".item-meta");
          const message = payload.message || `${payload.client || "交易软件"} 已打开 ${stock.code}`;
          if (meta) meta.textContent = message;
          else prependStockContextNotice(message, "success", button);
        } catch (error) {
          const meta = button?.querySelector(".item-meta");
          if (meta) meta.textContent = error.message;
          else prependStockContextNotice(error.message, "error", button);
        } finally {
          if (button) button.disabled = false;
        }
      }

      async function refreshTradingClientsForContext(context, button = null) {
        if (button) button.disabled = true;
        try {
          const payload = await fetchJson("/api/trading-clients?refresh=true");
          const clients = (payload.clients || []).filter((client) => client.capabilities?.stock);
          const nextContext = {
            ...context,
            trading_clients: {
              platform: payload.platform,
              generated_at: payload.generated_at,
              clients,
            },
          };
          state.currentStockContext = nextContext;
          renderStockContext(nextContext);
        } catch (error) {
          const body = $("#stockContextBody");
          const notice = document.createElement("div");
          notice.className = "notice status error";
          notice.textContent = error.message;
          body.prepend(notice);
        } finally {
          if (button) button.disabled = false;
        }
      }

      function bindStockContextActions(context) {
        const body = $("#stockContextBody");
        body.querySelectorAll("[data-stock-action]").forEach((button) => {
          button.addEventListener("click", () => {
            const action = button.dataset.stockAction;
            if (action === "trading-primary") {
              const firstClient = context.trading_clients?.clients?.[0];
              if (firstClient) openTradingClientFromContext(context, firstClient.id, button);
            }
            if (action === "refresh-trading-clients") refreshTradingClientsForContext(context, button);
            if (action === "opportunity") startStockOpportunity(context, button).catch((error) => alert(error.message));
            if (action === "analysis") startStockAnalysis(context, button).catch((error) => alert(error.message));
            if (action === "kline") openStockKlineModal(context.stock?.code, 240, { stockName: context.stock?.name || "" }).catch((error) => alert(error.message));
          });
        });
        body.querySelectorAll(".stock-trading-client").forEach((button) => {
          button.addEventListener("click", () => {
            openTradingClientFromContext(context, button.dataset.clientId, button);
          });
        });
      }

      async function openStockContext(target) {
        const code = normalizeStockCode(target?.stock_code || target?.stockCode || target?.code || target?.stock);
        if (!code) return;
        state.currentStockCode = code;
        closeOtherStockModals("#stockContextModal");
        const modal = $("#stockContextModal");
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        syncModalOpenState();
        $("#stockContextTitle").textContent = stockDisplayName({ code, name: target.stock_name || target.stockName || "" });
        ensureStockContextStar();
        syncStockContextStar();
        $("#stockContextMeta").textContent = "读取中...";
        $("#stockContextBody").innerHTML = `<div class="stock-context-loading">正在读取股票上下文...</div>`;
        resetStockSuiteTabs();
        initStockSuiteTabs();
        const name = target.stock_name || target.stockName || "";
        try {
          const context = await fetchJson(`/api/stock-context/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}`);
          state.currentStockContext = context;
          renderStockContext(context);
        } catch (error) {
          $("#stockContextMeta").textContent = "读取失败";
          $("#stockContextBody").innerHTML = `<div class="notice status error">${html(error.message)}</div>`;
        }
        state.suiteFetching = true;
        try {
          const suite = await fetchJson(`/api/stock-analysis-suite/${encodeURIComponent(code)}?name=${encodeURIComponent(name)}`);
          state.currentSuitePayload = suite;
        } catch (error) {
          state.currentSuitePayload = { success: false, error: String(error?.message || error) };
        } finally {
          state.suiteFetching = false;
          renderActiveSuiteTab();
        }
      }

      function renderActiveSuiteTab() {
        const activeBtn = document.querySelector("#stockSuiteTabs button.suite-tab.active");
        if (!activeBtn) return;
        const tab = activeBtn.dataset.suiteTab;
        const payload = state.currentSuitePayload;
        if (tab === "overview") renderSuiteOverview(payload);
        else if (tab === "market_cycle") renderSuiteDimensionPane(payload, "market_cycle");
        else if (tab === "main_force_phase") renderSuiteDimensionPane(payload, "main_force_phase");
        else if (tab === "volume_price_game") renderSuiteDimensionPane(payload, "volume_price_game");
        else if (tab === "chip_structure") renderSuiteDimensionPane(payload, "chip_structure");
        else if (tab === "performance") renderSuiteDimensionPane(payload, "performance");
        else if (tab === "probability") renderSuiteProbabilityPane(payload);
        else if (tab === "risk_control") renderSuiteRiskControl(payload);
        else if (tab === "limit_up_screening") renderSuiteLimitUpPane(payload);
        else if (tab === "main_force_deep") renderSuiteMainForceDeep(payload);
        else if (tab === "quant_matrix") renderSuiteQuantMatrix(payload);
        else if (tab === "chip_radar") renderSuiteChipRadar(payload);
        else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
        else if (tab === "panel") renderSuitePanel(payload);
        else if (tab === "ai_interpretation") renderSuiteAi(payload);
        else if (tab === "pattern_backtest") renderSuitePatternBacktest(payload);
        else if (tab === "financials") renderSuiteFinancials();
      }

      function renderSuiteLoading(paneId, label) {
        const pane = document.getElementById(paneId);
        if (!pane) return;
        pane.innerHTML = `<div class="suite-ai-empty"><p class="suite-empty-note"><span class="spinner"></span> ${html(label)}</p></div>`;
      }

      function closeStockContext() {
        const modal = $("#stockContextModal");
        if (!modal) return;
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        syncModalOpenState();
      }

      function bindStockContextModal() {
        const modal = $("#stockContextModal");
        const closeButton = $("#closeStockContextBtn");
        if (closeButton && !closeButton.dataset.bound) {
          closeButton.dataset.bound = "1";
          closeButton.addEventListener("click", closeStockContext);
        }
        if (modal && !modal.dataset.bound) {
          modal.dataset.bound = "1";
          modal.addEventListener("click", (event) => {
            if (event.target === modal) closeStockContext();
          });
        }
      }

      function resetStockSuiteTabs() {
        state.currentSuitePayload = null;
        const nav = $("#stockSuiteTabs");
        if (nav) {
          nav.querySelectorAll("button.suite-tab").forEach((b) => {
            b.classList.toggle("active", b.dataset.suiteTab === "quick");
          });
        }
        const panels = $("#stockSuitePanels");
        if (panels) {
          panels.querySelectorAll(".suite-pane").forEach((p) => {
            p.classList.toggle("hidden", p.dataset.suitePane !== "quick");
            if (p.dataset.suitePane !== "quick") {
              p.innerHTML = "";
              delete p.dataset.rendered;
            }
          });
        }
      }

      function initStockSuiteTabs() {
        const nav = $("#stockSuiteTabs");
        if (!nav || nav.dataset.bound === "1") return;
        nav.dataset.bound = "1";
        nav.addEventListener("click", (event) => {
          const btn = event.target.closest("button.suite-tab");
          if (!btn) return;
          if (btn.disabled) {
            showToast(btn.title || "该面板即将上线");
            return;
          }
          const tab = btn.dataset.suiteTab;
          nav.querySelectorAll("button.suite-tab").forEach((b) => b.classList.toggle("active", b === btn));
          document.querySelectorAll("#stockSuitePanels .suite-pane").forEach((p) => {
            p.classList.toggle("hidden", p.dataset.suitePane !== tab);
          });
          if (tab === "quick") return;
          if (tab === "financials") { renderSuiteFinancials(); return; }
          if (state.suiteFetching && !state.currentSuitePayload) {
            const paneIdMap = {
              overview: "suitePaneOverview",
              market_cycle: "suitePaneMarketCycle",
              main_force_phase: "suitePaneMainForce",
              volume_price_game: "suitePaneVolumePrice",
              chip_structure: "suitePaneChip",
              performance: "suitePanePerformance",
              probability: "suitePaneProbability",
              risk_control: "suitePaneRiskControl",
              limit_up_screening: "suitePaneLimitUp",
              main_force_deep: "suitePaneMainForceDeep",
              quant_matrix: "suitePaneQuantMatrix",
              chip_radar: "suitePaneChipRadar",
              institutional_holdings: "suitePaneHoldings",
              panel: "suitePanePanel",
              ai_interpretation: "suitePaneAi",
              pattern_backtest: "suitePanePatternBacktest",
            };
            renderSuiteLoading(paneIdMap[tab] || "suitePaneOverview", "数据加载中…");
            return;
          }
          const payload = state.currentSuitePayload;
          if (tab === "overview") renderSuiteOverview(payload);
          else if (tab === "market_cycle") renderSuiteDimensionPane(payload, "market_cycle");
          else if (tab === "main_force_phase") renderSuiteDimensionPane(payload, "main_force_phase");
          else if (tab === "volume_price_game") renderSuiteDimensionPane(payload, "volume_price_game");
          else if (tab === "chip_structure") renderSuiteDimensionPane(payload, "chip_structure");
          else if (tab === "performance") renderSuiteDimensionPane(payload, "performance");
          else if (tab === "probability") renderSuiteProbabilityPane(payload);
          else if (tab === "risk_control") renderSuiteRiskControl(payload);
          else if (tab === "limit_up_screening") renderSuiteLimitUpPane(payload);
          else if (tab === "main_force_deep") renderSuiteMainForceDeep(payload);
          else if (tab === "quant_matrix") renderSuiteQuantMatrix(payload);
          else if (tab === "chip_radar") renderSuiteChipRadar(payload);
          else if (tab === "institutional_holdings") renderSuiteHoldings(payload);
          else if (tab === "panel") renderSuitePanel(payload);
          else if (tab === "ai_interpretation") renderSuiteAi(payload);
        else if (tab === "pattern_backtest") renderSuitePatternBacktest(payload);
        });
      }

      function showToast(msg) {
        let toast = document.getElementById("kronosToast");
        if (!toast) {
          toast = document.createElement("div");
          toast.id = "kronosToast";
          document.body.appendChild(toast);
        }
        toast.textContent = String(msg || "");
        toast.style.opacity = "1";
        clearTimeout(showToast._timer);
        showToast._timer = setTimeout(() => {
          toast.style.opacity = "0";
        }, 2200);
      }

      // 综合研判总结：从已加载的 suite payload 确定性地汇总成一段「非常完整的总结说明」，
      // 渲染在「综合总览」tab 顶部。无 LLM——全部字段取自 payload 各维度。
      function suiteSummaryNum(v, fallback = 0) {
        const n = Number(v);
        return (v == null || isNaN(n)) ? fallback : n;
      }
      function suiteSummaryFmt(v, suffix = "") {
        if (v == null || v === "" || (typeof v === "number" && isNaN(v))) return "—";
        return `${v}${suffix}`;
      }
      function suiteSummaryTechnicalTrend(ov, payload) {
        const keyHit = (ov?.key_signals || []).find((s) => s?.label === "技术趋势" && s?.value);
        if (keyHit) return String(keyHit.value);
        const maHit = (payload?.panel?.indicators || []).find((i) => i?.key === "ma_align" && i?.data_status !== "unavailable" && i?.value_text);
        return maHit ? String(maHit.value_text) : "";
      }

      function buildSummaryVerdict(ov, payload, consensus) {
        const radar = ov.radar || {};
        const prob = ov.scenario_probability || {};
        const scores = ["main_force_phase", "market_cycle", "volume_price_game", "chip_structure", "performance", "control_degree", "quant_activity"]
          .map((k) => radar[k])
          .filter((r) => r?.score != null && !isNaN(Number(r.score)) && !(Number(r.score) === 0 && r.label === "未知"))
          .map((r) => Number(r.score));
        const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
        const cScore = (consensus && consensus.score != null && !isNaN(Number(consensus.score))) ? Number(consensus.score) : null;
        const bull = prob.bullish, bear = prob.bearish;
        const probLean = (bull != null && bear != null) ? Number(bull) - Number(bear) : null;
        const technicalTrend = suiteSummaryTechnicalTrend(ov, payload);

        // 复合打分 → 多空倾向（A股惯例：偏多=红色）
        let pts = 0;
        if (cScore != null) { if (cScore >= 55) pts++; else if (cScore <= 45) pts--; }
        if (probLean != null) { if (probLean >= 10) pts++; else if (probLean <= -10) pts--; }
        if (avg != null) { if (avg >= 60) pts++; else if (avg < 45) pts--; }
        if (technicalTrend.includes("多头")) pts++;
        else if (technicalTrend.includes("空头")) pts--;

        let tag, lean, advice;
        if (pts >= 2) { tag = "偏多 · 积极关注"; lean = "bull"; advice = "多维信号一致偏多，可逢低分批介入，并以量能持续放大作为加仓确认"; }
        else if (pts === 1) { tag = "谨慎偏多"; lean = "bull"; advice = "信号偏正面但仍存分歧，建议轻仓试探、严格执行止损"; }
        else if (pts <= -2) { tag = "偏空 · 规避"; lean = "bear"; advice = "多维信号偏空，建议规避或仅观望，不宜追高介入"; }
        else if (pts === -1) { tag = "谨慎偏空"; lean = "bear"; advice = "信号整体偏弱，建议以观望为主，等待企稳放量信号"; }
        else { tag = "多空分歧 · 观望"; lean = "neutral"; advice = "多空力量大体均衡、方向尚不明朗，观望为宜"; }

        const rc = payload.risk_control || {};
        const tail = [];
        if (rc.available !== false) {
          const ep = rc.execution_plan || {};
          const rr = ep.risk_reward || {}, sl = ep.stop_loss || {};
          if (rr.ratio != null) tail.push(`盈亏比 ${rr.ratio}`);
          if (sl.price != null) tail.push(`止损 ${sl.price}`);
          const firstLeg = (rc.scaled_entry || [])[0];
          if (firstLeg && firstLeg.position_pct != null) tail.push(`首仓 ${firstLeg.position_pct}%`);
        }
        const text = advice + (tail.length ? `（${tail.join(" · ")}）` : "") + "。本结论由本页各量化维度自动汇总，仅供研究参考，不构成投资建议。";
        return { tag, lean, text };
      }

      function buildComprehensiveSummary(payload) {
        if (!payload || payload.success === false || !payload.overview) return "";
        const ov = payload.overview;
        const radar = ov.radar || {};
        const rad = (k) => radar[k] || {};
        const fmt = suiteSummaryFmt, numOr = suiteSummaryNum;
        const sections = [];

        // 1. 趋势周期
        {
          const mc = rad("market_cycle"), mf = rad("main_force_phase"), vp = rad("volume_price_game");
          const parts = [];
          if (mc.label || mc.score != null) parts.push(`市场周期处于「${mc.label || "—"}」(${fmt(mc.score)}分)`);
          const technicalTrend = suiteSummaryTechnicalTrend(ov, payload);
          if (technicalTrend) parts.push(`技术趋势「${technicalTrend}」`);
          if (mf.label || mf.score != null) parts.push(`主力运作处于「${mf.label || "—"}」阶段(${fmt(mf.score)}分)`);
          if (vp.label || vp.score != null) parts.push(`量价关系呈「${vp.label || "—"}」(${fmt(vp.score)}分)`);
          if (mc.reason) parts.push(mc.reason);
          if (parts.length) sections.push({ key: "趋势周期", text: parts.join("；") + "。" });
        }

        // 2. 资金筹码
        {
          const chip = rad("chip_structure"), ctrl = rad("control_degree");
          const cc = payload.chip_control || {};
          const mfd = payload.main_force_deep || {};
          const parts = [];
          if (chip.label || chip.score != null) parts.push(`筹码结构「${chip.label || "—"}」(${fmt(chip.score)}分)`);
          if (ctrl.score != null) parts.push(`主力控盘度 ${fmt(ctrl.score)}`);
          if (cc.control_label && cc.data_status !== "unavailable") parts.push(`控盘评级「${cc.control_label}」`);
          if (cc.concentration_90 != null) parts.push(`90%筹码集中度 ${fmt(cc.concentration_90)}`);
          const hr = mfd.hsgt?.latest?.hold_ratio;
          if (hr != null && !isNaN(Number(hr))) parts.push(`北向持股占流通 ${Number(hr).toFixed(2)}%`);
          const qa = mfd.dragon_tiger?.quant_seat_appearances;
          if (qa != null) parts.push(`近90日量化席位现身 ${qa} 次`);
          if (parts.length) sections.push({ key: "资金筹码", text: parts.join("；") + "。" });
        }

        // 3. 量化共振
        {
          const qm = payload.quant_matrix || {};
          const reso = qm.multi_period_resonance || {};
          const prob = ov.scenario_probability || {};
          const qact = rad("quant_activity");
          const parts = [];
          if (qm.current_posture && qm.data_status !== "unavailable") parts.push(`30 模型当前态势「${qm.current_posture}」`);
          if (reso.bull != null || reso.bear != null) parts.push(`看多 ${numOr(reso.bull)} / 看空 ${numOr(reso.bear)} / 观望 ${numOr(reso.neutral)} 个模型`);
          if (prob.bullish != null || prob.bearish != null) parts.push(`概率推演 看涨 ${fmt(prob.bullish, "%")} · 看跌 ${fmt(prob.bearish, "%")} · 震荡 ${fmt(prob.sideways, "%")}`);
          if (qact.score != null && !(Number(qact.score) === 0 && qact.label === "未知")) parts.push(`量化活跃度 ${fmt(qact.score)}`);
          if (parts.length) sections.push({ key: "量化共振", text: parts.join("；") + "。" });
        }

        // 4. 业绩价值
        {
          const perf = rad("performance");
          if (perf.label || perf.score != null || perf.reason) {
            const parts = [`业绩预期「${perf.label || "—"}」(${fmt(perf.score)}分)`];
            if (perf.reason) parts.push(perf.reason);
            sections.push({ key: "业绩价值", text: parts.join("；") + "。" });
          }
        }

        // 5. 风险提示
        {
          const rc = payload.risk_control || {};
          const parts = [];
          if (rc.available !== false) {
            const ep = rc.execution_plan || {};
            const sl = ep.stop_loss || {}, rr = ep.risk_reward || {};
            if (sl.price != null) parts.push(`建议止损 ${sl.price}(-${fmt(sl.drop_pct)}%)`);
            if (rr.ratio != null) parts.push(`盈亏比 ${rr.ratio}`);
          }
          const hidden = (rc.hidden_risks || [])
            .map((h) => (h && h.text) ? h.text : (typeof h === "string" ? h : ""))
            .filter(Boolean);
          if (hidden.length) parts.push(`隐性风险：${hidden.slice(0, 3).join("、")}`);
          const warnSignals = (ov.key_signals || [])
            .filter((s) => s.tone === "warn" || s.tone === "danger")
            .map((s) => `${s.label}${s.value ? "(" + s.value + ")" : ""}`);
          if (warnSignals.length) parts.push(`需警惕：${warnSignals.slice(0, 3).join("、")}`);
          if (parts.length) sections.push({ key: "风险提示", text: parts.join("；") + "。" });
        }

        // 6. 多空评审团
        let consensus = null;
        {
          const p = payload.panel || {};
          const c = p.consensus;
          if (c && p.data_status !== "unavailable") {
            consensus = c;
            const gd = p.great_divide || {};
            const total = numOr(c.bull) + numOr(c.neutral) + numOr(c.bear);
            const parts = [`${total ? total + " 位" : ""}评审团多空温度 ${fmt(c.score)}(${c.label || "—"})，多 ${numOr(c.bull)} / 观望 ${numOr(c.neutral)} / 空 ${numOr(c.bear)}`];
            if (gd.bull?.name || gd.bear?.name) parts.push(`最强多头 ${gd.bull?.name || "—"} vs 最强空头 ${gd.bear?.name || "—"}`);
            if (gd.punchline) parts.push(gd.punchline);
            sections.push({ key: "多空评审团", text: parts.join("；") + "。" });
          }
        }

        // 7. 操作建议（结论）
        const concl = buildSummaryVerdict(ov, payload, consensus);
        sections.push({ key: "操作建议", text: concl.text, concl: true });

        if (sections.length <= 1) return "";  // 仅结论无依据时不展示空壳

        const stockName = stockDisplayName(payload.stock || {});
        const code = payload.stock?.code || "";
        const rows = sections.map((s) => `
          <div class="suite-summary-row${s.concl ? " concl" : ""}">
            <span class="suite-summary-key">【${html(s.key)}】</span>${html(s.text)}
          </div>`).join("");
        return `
          <div class="suite-summary-card">
            <div class="suite-summary-head">
              <span class="suite-summary-title">📋 综合研判总结 · ${html(stockName)}${code && code !== stockName ? " " + html(code) : ""}</span>
              <span class="suite-summary-verdict lean-${concl.lean}">${html(concl.tag)}</span>
            </div>
            <div class="suite-summary-body">${rows}</div>
          </div>`;
      }

      function renderSuiteOverview(payload) {
        const pane = document.getElementById("suitePaneOverview");
        if (!pane) return;
        pane.dataset.rendered = "1";
        if (!payload || payload.success === false || !payload.overview) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(payload?.error || "综合总览数据加载失败")}</p></div>`;
          return;
        }
        const ov = payload.overview;
        const keySignalsHtml = (ov.key_signals || []).map((s) => `
          <div class="suite-key-card tone-${s.tone || "neutral"}">
            <div class="suite-key-label">${html(s.label)}</div>
            <div class="suite-key-value">${html(s.value)}</div>
          </div>`).join("");
        const deepSignalsHtml = (ov.deep_signals || []).map((s) => `
          <div class="suite-deep-signal">
            <span class="suite-deep-tag">${html(s.tag || "—")}</span>
            <span>${html(s.text)}</span>
          </div>`).join("") || `<div class="suite-deep-signal suite-empty-note">暂无深度信号</div>`;
        pane.innerHTML = `
          ${buildComprehensiveSummary(payload)}
          <div class="suite-radar-section">
            <div id="suiteRadarChart" class="suite-radar-chart"></div>
            <div class="suite-key-signals">
              ${keySignalsHtml}
              <div id="suiteProbabilityDonut" class="suite-probability-donut"></div>
            </div>
          </div>
          <div class="suite-deep-signals">${deepSignalsHtml}</div>
        `;
        drawRadarChart(ov.radar);
        drawProbabilityDonut(ov.scenario_probability);
      }

      function drawRadarChart(radar) {
        const el = document.getElementById("suiteRadarChart");
        if (!el) return;
        const labels = ["主力阶段", "市场周期", "量价博弈", "筹码结构", "业绩预期", "控盘度", "量化活跃度"];
        const keys = ["main_force_phase", "market_cycle", "volume_price_game", "chip_structure", "performance", "control_degree", "quant_activity"];
        const values = keys.map((k) => (radar?.[k]?.score ?? 0));
        if (typeof Plotly === "undefined") {
          el.innerHTML = renderRadarSvgFallback(labels, values);
          return;
        }
        Plotly.newPlot(el, [{
          type: "scatterpolar",
          r: [...values, values[0]],
          theta: [...labels, labels[0]],
          fill: "toself",
          line: { color: "#2f6fdd" },
          fillcolor: "rgba(47,111,221,0.18)",
        }], {
          polar: {
            radialaxis: { range: [0, 100], visible: true, color: "#6b778a", gridcolor: "rgba(0,0,0,0.08)" },
            angularaxis: { color: "#344256", gridcolor: "rgba(0,0,0,0.08)" },
            bgcolor: "rgba(0,0,0,0)",
          },
          paper_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#172033", size: 11 },
          showlegend: false,
          margin: { t: 30, l: 40, r: 40, b: 30 },
        }, { displayModeBar: false, responsive: true });
      }

      function renderRadarSvgFallback(labels, values) {
        const cx = 160, cy = 160, r = 120;
        const n = labels.length || 1;
        const norm = values.map((v) => Math.max(0, Math.min(1, (v || 0) / 100)));
        const pts = norm.map((v, i) => {
          const a = -Math.PI / 2 + i * 2 * Math.PI / n;
          return [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
        });
        const polyPoints = pts.map((p) => p.map((x) => x.toFixed(1)).join(",")).join(" ");
        const labelTags = labels.map((l, i) => {
          const a = -Math.PI / 2 + i * 2 * Math.PI / n;
          return `<text x="${(cx + Math.cos(a) * (r + 18)).toFixed(1)}" y="${(cy + Math.sin(a) * (r + 18)).toFixed(1)}" text-anchor="middle" fill="#344256" font-size="12">${html(l)}</text>`;
        }).join("");
        return `<svg viewBox="0 0 320 320" width="100%" height="320" preserveAspectRatio="xMidYMid meet">
          <polygon points="${polyPoints}" fill="rgba(47,111,221,0.18)" stroke="#2f6fdd" stroke-width="2"/>
          ${labelTags}
        </svg>`;
      }

      function drawProbabilityDonut(prob) {
        const el = document.getElementById("suiteProbabilityDonut");
        if (!el || typeof Plotly === "undefined") return;
        Plotly.newPlot(el, [{
          type: "pie",
          hole: 0.5,
          labels: ["看涨", "看跌", "震荡"],
          values: [prob?.bullish ?? 33, prob?.bearish ?? 33, prob?.sideways ?? 34],
          marker: { colors: ["#198754", "#c43d36", "#6b778a"] },
          textinfo: "label+percent",
          textfont: { color: "#ffffff", size: 11 },
        }], {
          paper_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#172033" },
          showlegend: false,
          margin: { t: 10, l: 10, r: 10, b: 10 },
          height: 200,
        }, { displayModeBar: false, responsive: true });
      }

      const SUITE_DIMENSION_META = {
        market_cycle: {
          title: "市场周期",
          desc: "大盘风格 + 资金流入比衡量当前 A 股市场处于牛/震荡/熊周期",
          tagFilter: ["大盘周期", "仓位上限"],
          deepTags: [],
          scoreLabel: "周期得分",
        },
        main_force_phase: {
          title: "主力阶段",
          desc: "主力控盘度 + 近 5 日主力净流入推测主力建仓/拉升/撤离阶段",
          tagFilter: ["主力阶段"],
          deepTags: ["资金"],
          scoreLabel: "主力阶段得分",
        },
        volume_price_game: {
          title: "量价博弈",
          desc: "30 个量化模型买卖票数归一化反映多空博弈强度",
          tagFilter: ["量能质量"],
          deepTags: [],
          scoreLabel: "博弈得分",
        },
        chip_structure: {
          title: "筹码结构",
          desc: "90% 成本集中度 + 获利盘比率衡量筹码健康度",
          tagFilter: ["筹码集中度"],
          deepTags: ["筹码"],
          scoreLabel: "筹码得分",
        },
        performance: {
          title: "业绩预期",
          desc: "PE 行业排位 + ROE + 净利润同比增速综合打分",
          tagFilter: [],
          deepTags: [],
          scoreLabel: "业绩得分",
        },
      };

      function scoreTone(score) {
        if (score == null) return "neutral";
        if (score >= 70) return "info";
        if (score >= 40) return "warn";
        return "warn";
      }

      function renderSuiteDimensionPane(payload, key) {
        const meta = SUITE_DIMENSION_META[key] || {};
        const paneIdMap = {
          market_cycle: "suitePaneMarketCycle",
          main_force_phase: "suitePaneMainForce",
          volume_price_game: "suitePaneVolumePrice",
          chip_structure: "suitePaneChip",
          performance: "suitePanePerformance",
        };
        const pane = document.getElementById(paneIdMap[key]);
        if (!pane) return;
        pane.dataset.rendered = "1";
        if (!payload || payload.success === false || !payload.overview) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(payload?.error || meta.title + "数据加载失败")}</p></div>`;
          return;
        }
        const radar = payload.overview.radar || {};
        const entry = radar[key] || {};
        const score = entry.score;
        const label = entry.label || "—";
        const reason = entry.reason || "—";
        const tone = scoreTone(score);
        const keySignals = (payload.overview.key_signals || []).filter((s) => (meta.tagFilter || []).includes(s.label));
        const deepSignals = (payload.overview.deep_signals || []).filter((s) => (meta.deepTags || []).includes(s.tag));
        const keyHtml = keySignals.map((s) => `
          <div class="suite-key-card tone-${html(s.tone || "neutral")}">
            <div class="suite-key-label">${html(s.label)}</div>
            <div class="suite-key-value">${html(s.value)}</div>
          </div>`).join("");
        const deepHtml = deepSignals.length
          ? deepSignals.map((s) => `<div class="suite-deep-signal"><span class="suite-deep-tag">${html(s.tag)}</span><span>${html(s.text)}</span></div>`).join("")
          : `<p class="suite-empty-note">暂无关联深度信号</p>`;
        const gaugeId = `suiteGauge_${key}`;
        pane.innerHTML = `
          <div class="suite-radar-section">
            <div class="suite-dimension-summary">
              <h3 style="margin:0 0 8px;font-size:16px;color:var(--ink);">${html(meta.title || key)}</h3>
              <p class="suite-empty-note" style="margin:0 0 16px;">${html(meta.desc || "")}</p>
              <div class="suite-key-card tone-${tone}" style="margin-bottom:12px;">
                <div class="suite-key-label">${html(meta.scoreLabel || "得分")}</div>
                <div class="suite-key-value" style="font-size:28px;">${score == null ? "—" : score}</div>
              </div>
              <div class="suite-key-card tone-info" style="margin-bottom:12px;">
                <div class="suite-key-label">当前定性</div>
                <div class="suite-key-value">${html(label)}</div>
              </div>
              <div class="suite-key-card tone-neutral">
                <div class="suite-key-label">分析依据</div>
                <div class="suite-key-value" style="font-size:13px;">${html(reason)}</div>
              </div>
            </div>
            <div class="suite-key-signals">
              <div id="${gaugeId}" class="suite-radar-chart" style="height:240px;"></div>
              ${keyHtml || `<div class="suite-key-card tone-neutral"><div class="suite-key-label">关联信号</div><div class="suite-key-value" style="font-size:13px;">暂无</div></div>`}
            </div>
          </div>
          <div class="suite-deep-signals">${deepHtml}</div>
        `;
        drawScoreGauge(gaugeId, score, meta.title || key);
      }

      function drawScoreGauge(elementId, score, title) {
        const el = document.getElementById(elementId);
        if (!el) return;
        const value = Math.max(0, Math.min(100, Number(score) || 0));
        if (typeof Plotly === "undefined") {
          el.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:48px;color:var(--ink);font-weight:600;">${score == null ? "—" : score}</div>`;
          return;
        }
        Plotly.newPlot(el, [{
          type: "indicator",
          mode: "gauge+number",
          value,
          gauge: {
            axis: { range: [0, 100], tickcolor: "#6b778a" },
            bar: { color: "#2f6fdd" },
            steps: [
              { range: [0, 40], color: "rgba(196,61,54,0.18)" },
              { range: [40, 70], color: "rgba(247,193,82,0.22)" },
              { range: [70, 100], color: "rgba(25,135,84,0.22)" },
            ],
          },
          number: { font: { color: "#172033", size: 32 } },
        }], {
          paper_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#172033" },
          margin: { t: 20, l: 20, r: 20, b: 20 },
        }, { displayModeBar: false, responsive: true });
      }

      function renderSuiteProbabilityPane(payload) {
        const pane = document.getElementById("suitePaneProbability");
        if (!pane) return;
        pane.dataset.rendered = "1";
        if (!payload || payload.success === false || !payload.overview) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(payload?.error || "概率推演数据加载失败")}</p></div>`;
          return;
        }
        const prob = payload.overview.scenario_probability || {};
        const bullish = prob.bullish, bearish = prob.bearish, sideways = prob.sideways;
        if (bullish == null && bearish == null && sideways == null) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(prob.source || "30 量化模型未产出可推演的多空信号")}</p></div>`;
          return;
        }
        pane.innerHTML = `
          <div class="suite-radar-section">
            <div id="suiteProbBigDonut" class="suite-radar-chart" style="height:280px;"></div>
            <div class="suite-key-signals">
              <div class="suite-key-card tone-info">
                <div class="suite-key-label">看涨概率</div>
                <div class="suite-key-value" style="font-size:24px;">${bullish ?? "—"}%</div>
              </div>
              <div class="suite-key-card tone-warn">
                <div class="suite-key-label">看跌概率</div>
                <div class="suite-key-value" style="font-size:24px;">${bearish ?? "—"}%</div>
              </div>
              <div class="suite-key-card tone-neutral">
                <div class="suite-key-label">震荡概率</div>
                <div class="suite-key-value" style="font-size:24px;">${sideways ?? "—"}%</div>
              </div>
              <div class="suite-key-card tone-neutral">
                <div class="suite-key-label">数据来源</div>
                <div class="suite-key-value" style="font-size:12px;">${html(prob.source || "30 量化模型")}</div>
              </div>
            </div>
          </div>
        `;
        const el = document.getElementById("suiteProbBigDonut");
        if (el && typeof Plotly !== "undefined") {
          Plotly.newPlot(el, [{
            type: "pie",
            hole: 0.55,
            labels: ["看涨", "看跌", "震荡"],
            values: [bullish ?? 0, bearish ?? 0, sideways ?? 0],
            marker: { colors: ["#198754", "#c43d36", "#6b778a"] },
            textinfo: "label+percent",
            textfont: { color: "#ffffff", size: 13 },
          }], {
            paper_bgcolor: "rgba(0,0,0,0)",
            font: { color: "#172033" },
            showlegend: false,
            margin: { t: 20, l: 20, r: 20, b: 20 },
          }, { displayModeBar: false, responsive: true });
        }
      }

      function renderSuiteLimitUpPane(payload) {
        const pane = document.getElementById("suitePaneLimitUp");
        if (!pane) return;
        pane.dataset.rendered = "1";
        if (!payload || payload.success === false || !payload.overview) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(payload?.error || "涨停筛选数据加载失败")}</p></div>`;
          return;
        }
        const radar = payload.overview.radar || {};
        const vp = radar.volume_price_game || {};
        const mf = radar.main_force_phase || {};
        const chip = radar.chip_structure || {};
        const cycle = radar.market_cycle || {};
        const factors = [
          { label: "量价共振", score: vp.score, hint: "量价博弈得分≥60，量能放大配合", pass: (vp.score ?? 0) >= 60 },
          { label: "主力承接", score: mf.score, hint: "主力阶段得分≥60，控盘+净流入", pass: (mf.score ?? 0) >= 60 },
          { label: "筹码集中", score: chip.score, hint: "筹码结构得分≥60，主力锁仓充分", pass: (chip.score ?? 0) >= 60 },
          { label: "顺势环境", score: cycle.score, hint: "市场周期得分≥60，处于牛/拉升环境", pass: (cycle.score ?? 0) >= 60 },
        ];
        const passCount = factors.filter((f) => f.pass).length;
        const verdict = passCount >= 3 ? { tag: "高潜涨停", tone: "info" }
                      : passCount === 2 ? { tag: "条件性候选", tone: "warn" }
                      : { tag: "不建议追涨", tone: "warn" };
        const factorHtml = factors.map((f) => `
          <div class="suite-key-card tone-${f.pass ? "info" : "neutral"}">
            <div class="suite-key-label">${html(f.label)} · ${f.pass ? "通过" : "未达标"}</div>
            <div class="suite-key-value">${f.score == null ? "—" : f.score}</div>
            <div class="suite-empty-note" style="margin-top:4px;font-size:12px;">${html(f.hint)}</div>
          </div>`).join("");
        pane.innerHTML = `
          <div class="suite-radar-section">
            <div class="suite-dimension-summary">
              <h3 style="margin:0 0 8px;font-size:16px;color:var(--ink);">涨停筛选 · 多因子打分</h3>
              <p class="suite-empty-note" style="margin:0 0 16px;">基于量价、主力、筹码、周期 4 因子综合评估涨停潜力，每项 ≥60 视为通过</p>
              <div class="suite-key-card tone-${verdict.tone}" style="margin-bottom:12px;">
                <div class="suite-key-label">综合判定</div>
                <div class="suite-key-value" style="font-size:22px;">${html(verdict.tag)} · ${passCount}/4 通过</div>
              </div>
              <p class="suite-empty-note" style="font-size:12px;">注：本面板基于工作台已加载的量化打分快速判定。若需完整涨停黑马追踪，请到「机会挖掘」运行 limit_up 任务。</p>
            </div>
            <div class="suite-key-signals">
              ${factorHtml}
            </div>
          </div>
        `;
      }

      function renderSuiteRiskControl(payload) {
        const pane = document.getElementById("suitePaneRiskControl");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const rc = payload?.risk_control;
        if (!rc) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>操盘风控数据加载失败</p></div>`;
          return;
        }
        if (rc.available === false) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>${html(rc.reason || "数据不足")}</p></div>`;
          return;
        }
        const ep = rc.execution_plan || {};
        const sl = ep.stop_loss || {};
        const rr = ep.risk_reward || {};
        const scaledHtml = (rc.scaled_entry || []).map((e) => `
          <div class="suite-price-row"><span>${html(e.label)}</span>
            <span class="price">${html(e.price)} <span class="meta">${html(e.position_pct)}%</span></span>
          </div>`).join("");
        const takeProfitHtml = (rc.tiered_take_profit || []).map((t) => `
          <div class="suite-price-row"><span>${html(t.label)}</span>
            <span class="price">${html(t.price)} <span class="meta">${html(t.sell_pct)}%</span></span>
          </div>`).join("");
        const deepHtml = (rc.deep_signals || []).map((s) => `
          <div class="suite-deep-signal"><span>${html(s.text)}</span></div>`).join("")
          || `<p class="suite-empty-note">暂无深度信号</p>`;
        const hiddenHtml = (rc.hidden_risks || []).map((h) => `
          <div class="suite-deep-signal"><span>${html(h.text || h)}</span></div>`).join("")
          || `<p class="suite-empty-note">暂无隐性风险</p>`;
        pane.innerHTML = `
          <div class="suite-risk-grid">
            <div class="suite-risk-col">
              <h4>操盘执行方案</h4>
              <div class="suite-price-row"><span>止损价</span><span class="price">${html(sl.price ?? "—")} <span class="meta">(${html(sl.drop_pct ?? "—")}%)</span></span></div>
              <div class="suite-price-row"><span>盈亏比</span><span class="price">${html(rr.ratio ?? "—")} <span class="meta">${html(rr.expected_return_pct ?? "—")}%</span></span></div>
              <h4 style="margin-top:16px">分批建仓</h4>
              ${scaledHtml}
              <h4 style="margin-top:16px">分层止盈</h4>
              ${takeProfitHtml}
            </div>
            <div class="suite-risk-col">
              <h4>深度信号</h4>
              ${deepHtml}
            </div>
            <div class="suite-risk-col">
              <h4>隐性风险预警</h4>
              ${hiddenHtml}
            </div>
          </div>
        `;
      }

      // === 个股深度挖掘 M1 helpers ===
      function suiteFormatAmount(v) {
        if (v == null || isNaN(v)) return "—";
        const abs = Math.abs(v);
        if (abs >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
        if (abs >= 1e4) return (v / 1e4).toFixed(2) + " 万";
        return Number(v).toFixed(0);
      }

      function suiteUnavailableBanner(reason, withDiag) {
        const diag = withDiag
          ? ` <a href="/api/diagnostics/data-sources" target="_blank" rel="noopener">查看诊断</a>`
          : "";
        return `<div class="suite-unavailable-banner">数据源暂不可用：${html(reason || "未知原因")}${diag}</div>`;
      }

      function suiteStaleBanner(lastUpdated) {
        return `<div class="suite-stale-banner">最近一次入库：${html(lastUpdated || "未知")}（本期 M1 仅展示历史快照）</div>`;
      }

      function renderSuiteMainForceDeep(payload) {
        const pane = document.getElementById("suitePaneMainForceDeep");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const section = (payload && payload.main_force_deep) || {};
        if (!payload || payload.success === false || section.data_status === "unavailable") {
          pane.innerHTML = suiteUnavailableBanner(section.reason || payload?.error, true);
          return;
        }
        const isStale = section.data_status === "stale";
        const banner = isStale ? suiteStaleBanner(section.last_updated) : "";
        const dt = section.dragon_tiger || {};
        const hsgt = section.hsgt || {};
        const stageTl = section.stage_timeline;
        const qs = section.quant_signature;
        const ctrl = payload.overview?.radar?.control_degree?.score;
        const seatRows = (dt.highlight_seats || []).map((s) => `
          <tr>
            <td>${html(s.trade_date)}</td>
            <td>${html(s.inst_name)}${s.is_quant ? `<span class="quant-seat-pill" data-confidence="${html(s.quant_confidence || "")}">量化</span>` : ""}</td>
            <td>${html(s.side)}</td>
            <td>${suiteFormatAmount(s.net_amount)}</td>
            <td>${s.is_quant ? html(s.quant_confidence || "") : ""}</td>
          </tr>`).join("") || `<tr><td colspan="5" class="suite-empty-note">暂无龙虎榜数据</td></tr>`;
        pane.innerHTML = `
          ${banner}
          <div class="suite-kpi-bar">
            <div class="suite-kpi-card"><div class="suite-kpi-label">阶段</div><div class="suite-kpi-value">${html(stageTl?.current_label || "—")}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">控盘度</div><div class="suite-kpi-value">${ctrl ?? "—"}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">量化席位 90 日</div><div class="suite-kpi-value">${dt.quant_seat_appearances ?? "—"}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">北向占流通股 (%)</div><div class="suite-kpi-value">${hsgt.latest?.hold_ratio != null ? Number(hsgt.latest.hold_ratio).toFixed(2) : "—"}</div></div>
          </div>
          <h4>主力四阶段时间轴（近 60 交易日）</h4>
          <div class="suite-stage-axis">${(stageTl?.rows || []).slice(-60).map((r) => `<div class="suite-stage-cell" data-stage="${html(r.label)}" title="${html(r.date)}: ${html(r.label)}"></div>`).join("") || `<div class="suite-empty-note">阶段判定将于 M3 上线后可用</div>`}</div>
          <h4>龙虎榜机构席位（近 90 日）</h4>
          <table class="suite-table"><thead><tr><th>日期</th><th>席位</th><th>方向</th><th>净额</th><th>标记</th></tr></thead><tbody>${seatRows}</tbody></table>
          <h4>北向资金 30 日趋势</h4>
          <div id="suiteHsgtTrendChart" style="height:180px"></div>
          <h4>量化行为签名</h4>
          <div class="suite-empty-note">${qs ? `活跃度 ${html(String(qs.score))}，事件 ${(qs.events || []).length} 个` : "将于 M3 上线后可用"}</div>
        `;
        if (hsgt.trend_30d && hsgt.trend_30d.length && typeof Plotly !== "undefined") {
          Plotly.newPlot("suiteHsgtTrendChart", [{
            type: "scatter", mode: "lines", line: { color: "#2f6fdd", shape: "spline" },
            x: hsgt.trend_30d.map((r) => r.trade_date),
            y: hsgt.trend_30d.map((r) => r.hold_ratio),
          }], {
            margin: { t: 10, l: 44, r: 16, b: 28 }, paper_bgcolor: "rgba(0,0,0,0)",
            plot_bgcolor: "rgba(0,0,0,0)", font: { color: "#172033", size: 11 },
            yaxis: { title: "持股比 (%)" },
          }, { displayModeBar: false, responsive: true });
        }
      }

      function renderSuiteQuantMatrix(payload) {
        const pane = document.getElementById("suitePaneQuantMatrix");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const s = (payload && payload.quant_matrix) || {};
        if (!payload || payload.success === false || s.data_status === "unavailable") {
          pane.innerHTML = `
            ${suiteUnavailableBanner(s.reason || payload?.error, false)}
            <div class="suite-preview-block">
              <h4>预览结构（多周期热力 / 历史命中率 M4 接入）</h4>
              <ul>
                <li>30 模型信号矩阵（多周期列：日内 / 3 日 / 10 日 / 30 日 — M4）</li>
                <li>当前态势卡片（强势多头 / 震荡偏多 / 震荡 / 震荡偏空 / 强势空头）</li>
                <li>多周期共振环形图</li>
                <li>30 日历史命中率柱状图（M4）</li>
              </ul>
            </div>
          `;
          return;
        }
        const reso = s.multi_period_resonance || { bull: 0, bear: 0, neutral: 0 };
        const sigText = (v) => v === 1 ? "买入" : (v === -1 ? "卖出" : "观望");
        const sigColor = (v) => v === 1 ? "#d23f3f" : (v === -1 ? "#2f9e5a" : "#6b778a");
        const rows = (s.signals_matrix || []).map((m) => `
          <tr><td>${html(m.model)}</td><td>${html(m.period)}</td>
          <td style="color:${sigColor(m.signal)}">${sigText(m.signal)}</td></tr>`).join("");
        pane.innerHTML = `
          <div class="suite-kpi-bar">
            <div class="suite-kpi-card"><div class="suite-kpi-label">当前态势</div><div class="suite-kpi-value">${html(s.current_posture ?? "—")}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">看多模型</div><div class="suite-kpi-value" style="color:#d23f3f">${reso.bull}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">看空模型</div><div class="suite-kpi-value" style="color:#2f9e5a">${reso.bear}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">观望模型</div><div class="suite-kpi-value">${reso.neutral}</div></div>
          </div>
          <div id="suiteQuantResonanceChart" style="height:240px"></div>
          <h4 style="margin:14px 0 6px">30 模型信号（日线）</h4>
          <table class="suite-table"><thead><tr><th>模型</th><th>周期</th><th>信号</th></tr></thead><tbody>${rows || '<tr><td colspan="3">无信号</td></tr>'}</tbody></table>
        `;
        if (typeof Plotly !== "undefined") {
          Plotly.newPlot("suiteQuantResonanceChart", [{
            type: "pie", hole: 0.55,
            labels: ["看多", "看空", "观望"],
            values: [reso.bull, reso.bear, reso.neutral],
            marker: { colors: ["#d23f3f", "#2f9e5a", "#9aa6b8"] },
            textinfo: "label+value",
          }], {
            margin: { t: 20, l: 20, r: 20, b: 20 }, paper_bgcolor: "rgba(0,0,0,0)",
            font: { color: "#172033", size: 11 }, showlegend: false,
          }, { displayModeBar: false, responsive: true });
        }
      }


      function renderSuiteChipRadar(payload) {
        const pane = document.getElementById("suitePaneChipRadar");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const s = (payload && payload.chip_control) || {};
        if (!payload || payload.success === false || s.data_status === "unavailable") {
          pane.innerHTML = `
            ${suiteUnavailableBanner(s.reason || payload?.error, false)}
            <div class="suite-preview-block">
              <h4>预览结构（M2/M3 接入后可用）</h4>
              <ul>
                <li>控盘度仪表盘（0–100）</li>
                <li>筹码集中度雷达（90 / 70 / 50 / Top10）</li>
                <li>官方筹码分布直方图（stock_cyq_em）</li>
              </ul>
            </div>
          `;
          return;
        }
        pane.innerHTML = `
          <div class="suite-kpi-bar">
            <div class="suite-kpi-card"><div class="suite-kpi-label">控盘度</div><div class="suite-kpi-value">${s.control_degree ?? "—"}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">控盘标签</div><div class="suite-kpi-value">${html(s.control_label ?? "—")}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">筹码集中度 90%</div><div class="suite-kpi-value">${s.concentration_90 ?? "—"}</div></div>
            <div class="suite-kpi-card"><div class="suite-kpi-label">Top10 持股集中度</div><div class="suite-kpi-value">${s.top10_concentration ?? "—"}</div></div>
          </div>
          <div id="suiteChipRadarChart" style="height:260px"></div>
          <div id="suiteCyqHistogram" style="height:240px"></div>
        `;
        if (typeof Plotly !== "undefined") {
          Plotly.newPlot("suiteChipRadarChart", [{
            type: "scatterpolar", fill: "toself", line: { color: "#2f6fdd" },
            r: [s.concentration_90 ?? 0, s.concentration_70 ?? 0, s.concentration_50 ?? 0, s.top10_concentration ?? 0,
                s.concentration_90 ?? 0],
            theta: ["90% 集中", "70% 集中", "50% 集中", "Top10 持股", "90% 集中"],
          }], {
            polar: { radialaxis: { range: [0, 100], visible: true } },
            margin: { t: 30, l: 40, r: 40, b: 30 }, paper_bgcolor: "rgba(0,0,0,0)",
            font: { color: "#172033", size: 11 }, showlegend: false,
          }, { displayModeBar: false, responsive: true });
          const cyq = s.cyq_distribution;
          if (cyq && cyq.prices && cyq.prices.length) {
            Plotly.newPlot("suiteCyqHistogram", [{
              type: "bar", x: cyq.prices, y: cyq.ratios, marker: { color: "#2f6fdd" },
            }], {
              margin: { t: 16, l: 44, r: 16, b: 32 }, paper_bgcolor: "rgba(0,0,0,0)",
              plot_bgcolor: "rgba(0,0,0,0)", font: { color: "#172033", size: 11 },
              xaxis: { title: "价位" }, yaxis: { title: "持仓比 (%)" },
            }, { displayModeBar: false, responsive: true });
          }
        }
      }

      function renderSuiteHoldings(payload) {
        const pane = document.getElementById("suitePaneHoldings");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const s = (payload && payload.institutional_holdings) || {};
        if (!payload || payload.success === false || s.data_status === "unavailable") {
          pane.innerHTML = suiteUnavailableBanner(s.reason || payload?.error, true);
          return;
        }
        const isStale = s.data_status === "stale";
        const banner = isStale ? suiteStaleBanner(s.last_updated) : "";
        const t10 = s.top10_floatholders || {};
        const hn = s.holder_number || {};
        const surveys = (s.surveys && s.surveys.recent_90d) || [];
        const funds = (s.fund_holds && s.fund_holds.rows) || [];
        const t10Rows = (t10.rows || []).map((r) => `
          <tr>
            <td>${r.holder_rank}</td>
            <td>${html(r.holder_name)}</td>
            <td>${r.hold_amount != null ? (r.hold_amount / 1e4).toFixed(2) : "—"}</td>
            <td>${r.hold_ratio != null ? Number(r.hold_ratio).toFixed(2) : "—"}</td>
            <td>${suiteHoldingChangeBadge(r.change_type, r.change_amount)}</td>
          </tr>`).join("") || `<tr><td colspan="5" class="suite-empty-note">无数据</td></tr>`;
        const surveyItems = surveys.slice(0, 10).map((r) => `<li>${html(r.survey_date)} — ${html(r.inst_name)}：${html(r.topic || "")}</li>`).join("") || `<li class="suite-empty-note">无调研记录</li>`;
        pane.innerHTML = `
          ${banner}
          <h4>Top10 流通股东（${html(t10.period || "—")}）</h4>
          <table class="suite-table"><thead><tr><th>#</th><th>股东</th><th>持仓 (万股)</th><th>占流通比 (%)</th><th>变动</th></tr></thead><tbody>${t10Rows}</tbody></table>
          <h4>股东户数变化</h4>
          <div>最新户数：<b>${hn.latest_num ?? "—"}</b>　环比：<b>${hn.pct_change_qoq != null ? Number(hn.pct_change_qoq).toFixed(2) + "%" : "—"}</b></div>
          <div id="suiteHolderNumSpark" style="height:120px"></div>
          <h4>机构调研（近 90 日）</h4>
          <ul>${surveyItems}</ul>
          <h4>重仓基金（${html((s.fund_holds && s.fund_holds.period) || "—")}）</h4>
          <div id="suiteFundHoldBar" style="height:240px"></div>
        `;
        if (typeof Plotly !== "undefined") {
          if (hn.history && hn.history.length) {
            Plotly.newPlot("suiteHolderNumSpark", [{
              type: "scatter", mode: "lines", line: { color: "#2f6fdd", shape: "spline" },
              x: hn.history.map((r) => r.end_date), y: hn.history.map((r) => r.holder_num),
            }], {
              margin: { t: 8, l: 8, r: 8, b: 8 }, paper_bgcolor: "rgba(0,0,0,0)",
              plot_bgcolor: "rgba(0,0,0,0)", xaxis: { visible: false }, yaxis: { visible: false },
            }, { displayModeBar: false, responsive: true });
          }
          if (funds.length) {
            Plotly.newPlot("suiteFundHoldBar", [{
              type: "bar", orientation: "h", marker: { color: "#2f6fdd" },
              y: funds.map((f) => f.fund_name), x: funds.map((f) => f.nv_ratio),
            }], {
              margin: { t: 16, l: 120, r: 16, b: 32 }, paper_bgcolor: "rgba(0,0,0,0)",
              plot_bgcolor: "rgba(0,0,0,0)", font: { color: "#172033", size: 11 },
              xaxis: { title: "占基金净值 (%)" },
            }, { displayModeBar: false, responsive: true });
          }
        }
      }

      function suiteHoldingChangeBadge(type, amount) {
        if (!type || type === "unchanged") return "—";
        const colorMap = { new: "#198754", add: "#198754", cut: "#c43d36", exit: "#6b778a" };
        const labelMap = { new: "新进", add: "增持", cut: "减持", exit: "退出" };
        const amt = amount ? ` ${(amount / 1e4).toFixed(0)} 万` : "";
        return `<span style="color:${colorMap[type] || "#6b778a"}">${html(labelMap[type] || type)}${amt}</span>`;
      }

      // 多空评审团：终端风格。红=多 #d23f3f，绿=空 #2f9e5a，黄=中性 #c9a227。
      const BBP_SCHOOL_ORDER = ["A", "B", "C", "D", "E", "F", "G"];
      function bbpSignalColor(sig) {
        return sig === "bull" || sig === "up" ? "#d23f3f"
             : sig === "bear" || sig === "down" ? "#2f9e5a" : "#c9a227";
      }
      function bbpSignalText(sig) {
        return sig === "bull" ? "多" : sig === "bear" ? "空"
             : sig === "up" ? "↑" : sig === "down" ? "↓" : "—";
      }
      function bbpSignalLabel(sig) {
        return sig === "bull" ? "看多" : sig === "bear" ? "看空"
             : sig === "up" ? "偏多" : sig === "down" ? "偏空" : "观望";
      }

      // 悬停投资风格卡片：7 流派各自的详细理念 + 选股逻辑（真实可考的投资方法论），
      // 叠加该分析师的个人风格标签、关注指标与本股裁决，构成"非常详细的投资风格总结"。
      const BBP_SCHOOL_STYLE = {
        A: { tag: "长期主义 · 安全边际",
             philosophy: "把股票视为企业所有权的一部分，坚信价格长期围绕内在价值波动。要求以显著低于内在价值的价格买入，用足够的安全边际抵御误判与坏运气，赚企业长期复利与估值回归的钱，而非市场情绪的钱。",
             focus: "看重盈利质量(ROE)、护城河深度、行业估值分位与现金流稳定性；偏好低估值、高壁垒、能长期持有的好生意，回避高负债与概念炒作。" },
        B: { tag: "高成长 · 合理价格(GARP)",
             philosophy: "相信优秀公司的盈利成长会持续驱动股价，愿意为高确定性的成长支付合理溢价。核心是以合理价格买入高成长，赚业绩兑现与渗透率提升的钱，而不是单纯的估值博弈。",
             focus: "看重营收与净利同比增速、行业空间与渗透率、研发投入与新品周期；偏好高速扩张、赛道景气、管理层进取的公司，容忍较高估值但要求成长可被验证。" },
        C: { tag: "自上而下 · 周期择时",
             philosophy: "自上而下，从经济周期、货币与流动性、政策与地缘出发判断大类资产与板块轮动。信奉反身性——价格与基本面相互强化，趋势一旦形成可自我加速；重在押注大级别拐点，判断错了就快速止损。",
             focus: "看重趋势方向、动量、利率与流动性环境、板块轮动位置；以择时与仓位管理为核心，顺大势而为，在拐点与极端情绪处逆向布局。" },
        D: { tag: "趋势顺势 · 量价纪律",
             philosophy: "信奉价格反映一切，只看图表与量价、不问基本面。顺势交易、强者恒强：突破确认时进场、趋势走坏时离场，用严格止损把单笔亏损控制在小额，让利润奔跑。",
             focus: "看重趋势结构、动量强度、量价配合(放量突破/缩量回踩)、关键支撑阻力与所处阶段(底部/拉升/顶部/下跌)；偏好强势突破形态，回避下降趋势与无量品种。" },
        E: { tag: "本分 · 时间的玫瑰",
             philosophy: "价值投资的中国本土实践，强调本分与商业模式，长期持有少数能看懂的优质龙头，赚企业成长与时间复利的钱、淡化择时；逆向流派则以低位、预期差与弱者体系取胜。",
             focus: "看重ROE与盈利持续性、行业估值分位、品牌与定价权、消费垄断属性；偏好确定性高、可长期复利、管理层靠谱的公司，回避看不懂与商业模式差的生意。" },
        F: { tag: "情绪短线 · 龙虎榜打板",
             philosophy: "短线情绪交易，赚市场情绪与资金合力的钱。核心是龙虎榜与打板接力，捕捉板块龙头与情绪周期的高潮，讲求快准狠：亏损立即止损，盈利集中在主升浪的几天。",
             focus: "看重龙虎榜席位与资金动向、控盘度、放量与连板高度、板块效应与情绪周期位置；偏好题材龙头与首板强势股，回避退潮期与跟风弱势股。" },
        G: { tag: "数据驱动 · 多因子套利",
             philosophy: "用统计与数学模型系统化决策、剥离主观情绪。通过多因子、统计套利与算法交易，在大量标的上捕捉可重复的微小优势，靠分散、纪律与高换手把概率优势转化为稳定收益。",
             focus: "看重多因子信号、模型共振比例、波动率与相关性、量价微观结构；以信号强度与概率优势决定买卖，不依赖单一标的的基本面故事。" },
      };
      const BBP_METRIC_LABEL = {
        roe: "ROE 净资产收益率", pe_industry_rank: "PE 行业分位",
        net_profit_yoy: "净利润同比", revenue_yoy: "营收同比", pb: "市净率 PB",
        momentum: "动量强度", trend: "趋势方向", volatility: "波动率", volume: "成交量能",
      };
      function bbpStyleDetail(a, schoolName) {
        return {
          name: a.name, schoolKey: a.school, schoolName,
          signal: a.signal, score: a.score, voice: a.voice || "",
          metrics: a.key_metrics || [],
          insight: a.insight || a.headline || "",
          reasons: (a.reasons || []).slice(0, 4),
          source: a.source,
          insufficient: !!a.data_insufficient,
        };
      }
      function bbpStyleCardHtml(d) {
        const s = BBP_SCHOOL_STYLE[d.schoolKey] || {};
        const col = d.insufficient ? "#9aa3b2" : bbpSignalColor(d.signal);
        const metrics = (d.metrics || [])
          .map((m) => `<span class="bsc-metric">${html(BBP_METRIC_LABEL[m] || m)}</span>`).join("");
        const reasons = (d.reasons || []).filter((r) => r && r !== d.insight)
          .map((r) => `<li>${html(r)}</li>`).join("");
        const scoreHtml = d.insufficient
          ? `<span class="bsc-score insuf">数据不足</span>`
          : `<span class="bsc-score" style="color:${col}">${bbpSignalLabel(d.signal)} ${html(String(d.score))}</span>`;
        return `
          <div class="bsc-head">
            <span class="bsc-dot" style="background:${col}"></span>
            <span class="bsc-name">${html(d.name)}</span>
            <span class="bsc-school">${html(d.schoolName)}${s.tag ? " · " + html(s.tag) : ""}</span>
            ${scoreHtml}
          </div>
          ${d.voice ? `<div class="bsc-voice">个人风格：${html(d.voice)}${d.source === "rule" ? '<em class="bsc-rule">规则推断</em>' : ""}</div>` : ""}
          ${s.philosophy ? `<h6>流派理念</h6><p>${html(s.philosophy)}</p>` : ""}
          ${s.focus ? `<h6>选股逻辑</h6><p>${html(s.focus)}</p>` : ""}
          ${metrics ? `<h6>关注指标</h6><div class="bsc-metrics">${metrics}</div>` : ""}
          <div class="bsc-verdict">
            <h6>本股裁决</h6>
            ${d.insight ? `<div class="bsc-insight">${html(d.insight)}</div>` : ""}
            ${reasons ? `<ul class="bsc-reasons">${reasons}</ul>` : ""}
          </div>`;
      }
      function bbpEnsureStyleCard() {
        let card = document.getElementById("bbpStyleCard");
        if (!card) {
          card = document.createElement("div");
          card.id = "bbpStyleCard";
          card.className = "bbp-style-card";
          document.body.appendChild(card);
        }
        return card;
      }
      function bbpPositionStyleCard(card, rect) {
        const margin = 10;
        const cardW = card.offsetWidth, cardH = card.offsetHeight;
        const vw = window.innerWidth, vh = window.innerHeight;
        let left = rect.right + margin;
        if (left + cardW > vw - margin) left = rect.left - cardW - margin;  // 右侧放不下→翻到左侧
        if (left < margin) left = Math.max(margin, vw - cardW - margin);
        let top = rect.top;
        if (top + cardH > vh - margin) top = Math.max(margin, vh - cardH - margin);
        card.style.left = left + "px";
        card.style.top = top + "px";
      }
      function bbpShowStyleCard(memberEl) {
        const raw = memberEl.getAttribute("data-style-detail");
        if (!raw) return;
        let d;
        try { d = JSON.parse(raw); } catch (e) { return; }
        const card = bbpEnsureStyleCard();
        if (card.__forEl === memberEl && card.style.display === "block") return;
        card.__forEl = memberEl;
        card.innerHTML = bbpStyleCardHtml(d);
        card.style.display = "block";
        bbpPositionStyleCard(card, memberEl.getBoundingClientRect());
        requestAnimationFrame(() => card.classList.add("show"));
      }
      function bbpHideStyleCard() {
        const card = document.getElementById("bbpStyleCard");
        if (!card) return;
        card.classList.remove("show");
        card.style.display = "none";
        card.__forEl = null;
      }
      function bbpInstallStyleHover() {
        if (window.__bbpStyleHoverInstalled) return;
        window.__bbpStyleHoverInstalled = true;
        const pick = (e) => (e.target.closest ? e.target.closest(".bbp-member[data-style-detail]") : null);
        document.addEventListener("mouseover", (e) => { const m = pick(e); if (m) bbpShowStyleCard(m); });
        document.addEventListener("mouseout", (e) => {
          const m = pick(e);
          if (!m) return;
          const to = e.relatedTarget;
          if (to && to.closest && to.closest(".bbp-member[data-style-detail]")) return;  // 成员间移动→交给 mouseover 切换内容，避免闪烁
          if (!m.contains(to)) bbpHideStyleCard();
        });
        document.addEventListener("focusin", (e) => { const m = pick(e); if (m) bbpShowStyleCard(m); });
        document.addEventListener("focusout", (e) => { const m = pick(e); if (m) bbpHideStyleCard(); });
        window.addEventListener("scroll", bbpHideStyleCard, true);
        window.addEventListener("resize", bbpHideStyleCard);
      }

      function renderSuitePanel(payload) {
        const pane = document.getElementById("suitePanePanel");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const p = (payload && payload.panel) || {};
        if (!payload || payload.success === false || p.data_status === "unavailable") {
          pane.innerHTML = suiteUnavailableBanner(p.reason || payload?.error, false);
          return;
        }
        const c = p.consensus || { score: 50, label: "—", bull: 0, neutral: 0, bear: 0 };
        const gd = p.great_divide || {};
        const banner = p.data_status === "stale" ? suiteStaleBanner(p.last_updated) : "";
        const sliderPct = Math.max(0, Math.min(100, c.score));

        // 顶部：温度计 + 计数 + 大分歧（常动区）
        const head = `
          <div class="bbp-head">
            <div class="bbp-thermo">
              <div class="bbp-thermo-label"><span>极空</span><span>多空温度计</span><span>极多</span></div>
              <div class="bbp-thermo-track">
                <div class="bbp-thermo-slider" style="left:${sliderPct}%"></div>
              </div>
              <div class="bbp-thermo-score" style="color:${bbpSignalColor(c.score >= 55 ? "bull" : c.score <= 45 ? "bear" : "neutral")}">
                ${html(String(c.score))} · ${html(c.label)}
              </div>
            </div>
            <div class="bbp-counts">
              <span class="bbp-count bull">多 ${c.bull}</span>
              <span class="bbp-count neutral">观望 ${c.neutral}</span>
              <span class="bbp-count bear">空 ${c.bear}</span>
            </div>
          </div>
          <div class="bbp-divide">
            <div class="bbp-divide-side bull">
              <div class="bbp-divide-tag">最强多头</div>
              <div class="bbp-divide-name">${html(gd.bull?.name || "—")} <small>${html(gd.bull?.score != null ? String(gd.bull.score) : "")}</small></div>
            </div>
            <div class="bbp-divide-vs">VS</div>
            <div class="bbp-divide-side bear">
              <div class="bbp-divide-tag">最强空头</div>
              <div class="bbp-divide-name">${html(gd.bear?.name || "—")} <small>${html(gd.bear?.score != null ? String(gd.bear.score) : "")}</small></div>
            </div>
          </div>
          <div class="bbp-punchline">${html(gd.punchline || "")}</div>`;

        // 16 指标栏（4 组）
        const groupTitles = { capital: "资金面", technical: "技术面", chip: "筹码·机构", model: "模型·预测" };
        const inds = p.indicators || [];
        const groupHtml = Object.keys(groupTitles).map((g) => {
          const cells = inds.filter((it) => it.group === g).map((it) => {
            const off = it.data_status === "unavailable";
            const col = off ? "#6b778a" : bbpSignalColor(it.signal);
            const w = Math.round((it.strength || 0) * 100);
            return `<div class="bbp-ind ${off ? "off" : ""}">
              <div class="bbp-ind-top"><span class="bbp-ind-label">${html(it.label)}</span>
                <span class="bbp-ind-sig" style="color:${col}">${bbpSignalText(it.signal)}</span></div>
              <div class="bbp-ind-val">${html(it.value_text)}</div>
              <div class="bbp-ind-bar"><i style="width:${w}%;background:${col}"></i></div>
            </div>`;
          }).join("");
          return `<div class="bbp-ind-group"><h5>${groupTitles[g]}</h5><div class="bbp-ind-grid">${cells}</div></div>`;
        }).join("");

        // 7 流派 · 全部展开；悬停成员弹出详细投资风格卡片（流派理念 + 个人风格 + 关注指标 + 本股裁决）
        const analysts = p.analysts || [];
        const schools = (p.schools || []).slice().sort(
          (a, b) => BBP_SCHOOL_ORDER.indexOf(a.key) - BBP_SCHOOL_ORDER.indexOf(b.key));
        const memberRow = (a, i, schoolName) => {
          const detail = bbpStyleDetail(a, schoolName);
          const insuf = !!a.data_insufficient;
          // 数据不足时盖过“规则推断”标签：分数置灰为“—”，不伪装成自信中性
          const tag = insuf ? '<em class="bbp-insuf-tag">数据不足</em>'
            : (a.source === "rule" ? '<em class="bbp-rule-tag">规则推断</em>' : "");
          return `<div class="bbp-member${insuf ? " bbp-insuf" : ""}" style="animation-delay:${i * 30}ms"
            tabindex="0" data-style-detail="${html(JSON.stringify(detail))}">
            <span class="bbp-dot" style="background:${insuf ? "#c2c8d2" : bbpSignalColor(a.signal)}"></span>
            <span class="bbp-member-name">${html(a.name)}${tag}</span>
            <span class="bbp-member-head">${html(a.insight || a.headline)}</span>
            <span class="bbp-member-score"${insuf ? "" : ` style="color:${bbpSignalColor(a.signal)}"`}>${insuf ? "—" : a.score}</span>
          </div>`;
        };
        const schoolHtml = schools.map((s) => {
          const lean = s.lean_score >= 55 ? "bull" : s.lean_score <= 45 ? "bear" : "neutral";
          const members = analysts.filter((a) => a.school === s.key)
            .sort((a, b) => b.score - a.score);
          const allInsuf = members.length > 0 && members.every((a) => a.data_insufficient);
          const membersHtml = members.map((a, i) => memberRow(a, i, s.name)).join("");
          const leanHtml = allInsuf
            ? `<span class="bbp-school-lean insuf">数据不足</span>`
            : `<span class="bbp-school-lean" style="color:${bbpSignalColor(lean)}">${html(s.lean)} ${s.lean_score}</span>`;
          return `<details class="bbp-school${allInsuf ? " bbp-insuf" : ""}" data-school="${html(s.key)}" open>
            <summary>
              <span class="bbp-school-caret">▶</span>
              <span class="bbp-school-name">${html(s.name)}</span>
              <span class="bbp-school-meta">${s.count} 人</span>
              <span class="bbp-minibar"><i style="width:${allInsuf ? 0 : Math.max(0, Math.min(100, s.lean_score))}%;background:${allInsuf ? "#c2c8d2" : bbpSignalColor(lean)}"></i></span>
              ${leanHtml}
            </summary>
            <div class="bbp-members">${membersHtml}</div>
          </details>`;
        }).join("");

        pane.innerHTML = `${banner}
          <div class="bbp-root">
            ${head}
            <div class="bbp-overlay" id="bbpOverlay">
              ${renderPanelOverlay(payload)}
            </div>
            <div class="bbp-section-title">量化指标（16）</div>
            ${groupHtml}
            <div class="bbp-section-title">投资人评审团（${analysts.length} 位 · 悬停查看投资风格）</div>
            <div class="bbp-schools">${schoolHtml}</div>
          </div>`;
        bbpInstallStyleHover();
      }

      // P0-A/P0-B：reviewed=true 显 AI 点评(+黄旗警告)；质量拦截显红条+回退规则文案；未生成显升档按钮
      function renderPanelOverlay(payload) {
        const ov = (payload && payload.analysis_overlay) || {};
        const stock = (payload && payload.stock) || {};
        const q = ov.quality || {};
        const criticals = q.criticals || [];
        if (!ov.reviewed) {
          if (criticals.length) {
            // P0-B：AI 已生成但被机械质量门拦截 —— 红条 + 重新生成；下方仍渲染规则版 panel
            return `
              <div class="bbp-overlay-redbar">
                <span class="bbp-overlay-redbar-title">⚠ AI 点评未通过质量门</span>
                <span class="bbp-overlay-redbar-reason">${html(criticals.join("；"))}</span>
                <button class="bbp-overlay-btn" type="button"
                  onclick="triggerPanelOverlay('${html(stock.code || "")}')">重新生成</button>
              </div>`;
          }
          const reason = ov.reason ? `<span class="bbp-overlay-reason">${html(ov.reason)}</span>` : "";
          return `
            <div class="bbp-overlay-empty">
              <button class="bbp-overlay-btn" type="button"
                onclick="triggerPanelOverlay('${html(stock.code || "")}')">AI 深度点评</button>
              ${reason}
            </div>`;
        }
        const risks = (ov.risks || []).map((r) => `<li>${html(r)}</li>`).join("");
        const zones = ov.buy_zones || {};
        const zoneRow = (k, label) => {
          const items = (zones[k] || []).map((z) => `<span class="bbp-zone-pill">${html(z)}</span>`).join("");
          return items ? `<div class="bbp-zone"><span class="bbp-zone-label">${label}</span>${items}</div>` : "";
        };
        const nar = (() => {
          if (ov.narrative_override) return `<div class="bbp-overlay-nar">${html(ov.narrative_override)}</div>`;
          // 兜底：narrative 省略时（旧缓存/模型偷懒）用前几条逐人点评充当正文，避免「AI 点评」只剩标签像没显示完
          const ins = ov.panel_insights || {};
          const picks = Object.values(ins).filter((t) => typeof t === "string" && t.trim()).slice(0, 3);
          return picks.length
            ? `<div class="bbp-overlay-nar">${picks.map((t) => "· " + html(t)).join("<br>")}</div>`
            : "";
        })();
        const warnings = (q.warnings || []).map((w) => `<div class="bbp-overlay-flag">⚠ ${html(w)}</div>`).join("");
        const flags = warnings ? `<div class="bbp-overlay-flags">${warnings}</div>` : "";
        return `
          <div class="bbp-overlay-card" data-status="${html(ov.data_status || "")}">
            <div class="bbp-overlay-tag">AI 点评 · ${html(ov.tier || "")}${ov.data_status === "stale" ? " · 历史" : ""}</div>
            ${nar}
            ${risks ? `<div class="bbp-overlay-risks"><b>风险</b><ul>${risks}</ul></div>` : ""}
            <div class="bbp-overlay-zones">
              ${zoneRow("value", "价值")}${zoneRow("growth", "成长")}
              ${zoneRow("technical", "技术")}${zoneRow("youzi", "游资")}
            </div>
            ${flags}
          </div>`;
      }

      async function triggerPanelOverlay(code) {
        if (!code) { showToast("缺少股票代码"); return; }
        const box = document.getElementById("bbpOverlay");
        if (box) box.innerHTML = `<div class="bbp-overlay-empty">⏳ 正在调用 DeepSeek 生成深度点评…</div>`;
        try {
          const resp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}/panel-overlay`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tier: "deep" }),
          });
          const data = await resp.json();
          const blocked = data.overlay && (data.overlay.quality || {}).criticals
            && data.overlay.quality.criticals.length;
          if (data.success && state.currentSuitePayload) {
            state.currentSuitePayload.analysis_overlay = data.overlay;
            if (data.merged_panel) state.currentSuitePayload.panel = data.merged_panel;
            renderSuitePanel(state.currentSuitePayload);   // 整面重渲（含覆盖后的金句/逐人 insight）
          } else if (blocked && state.currentSuitePayload) {
            // P0-B：被质量门拦截 —— 落 state 整面重渲（红条 + 规则版 panel），与重载表现一致
            state.currentSuitePayload.analysis_overlay = data.overlay;
            if (data.merged_panel) state.currentSuitePayload.panel = data.merged_panel;
            renderSuitePanel(state.currentSuitePayload);
          } else if (box) {
            box.innerHTML = `<div class="bbp-overlay-empty">
              <span class="bbp-overlay-reason">生成失败：${html((data.overlay && data.overlay.reason) || data.error || "未知错误")}</span>
              <button class="bbp-overlay-btn" type="button" onclick="triggerPanelOverlay('${html(code)}')">重试</button>
            </div>`;
          }
        } catch (err) {
          if (box) box.innerHTML = `<div class="bbp-overlay-empty">
            <span class="bbp-overlay-reason">网络错误：${html(String(err && err.message || err))}</span>
            <button class="bbp-overlay-btn" type="button" onclick="triggerPanelOverlay('${html(code)}')">重试</button>
          </div>`;
        }
      }

      function renderSuiteAi(payload) {
        const pane = document.getElementById("suitePaneAi");
        if (!pane) return;
        pane.dataset.rendered = "1";
        const ai = payload?.ai_interpretation;
        if (ai && ai.status === "ready" && ai.report) {
          renderAiReady(pane, ai);
          return;
        }
        pane.innerHTML = `
          <div class="suite-ai-empty">
            <h3>AI 操盘手深度解读</h3>
            <p>基于多因子模型 + DeepSeek 推理引擎<br>约 3-5k tokens / 单次 5-30 秒</p>
            <button id="suiteAiGenBtn" class="suite-ai-button" type="button">生成深度解读</button>
          </div>
        `;
        const btn = document.getElementById("suiteAiGenBtn");
        if (btn) {
          btn.addEventListener("click", () => {
            const stock = payload?.stock || {};
            triggerSuiteAi(stock.code, stock.name || "");
          });
        }
      }

      function renderAiReady(pane, ai) {
        pane.innerHTML = `
          <div class="suite-ai-report">${renderSuiteMarkdown(ai.report)}</div>
          <div class="suite-ai-footer">Token 使用：${html(ai.token_usage ?? "—")} · 生成时间：${html(ai.generated_at || "—")}</div>
        `;
      }

      async function triggerSuiteAi(code, name) {
        if (!code) {
          showToast("缺少股票代码");
          return;
        }
        const pane = document.getElementById("suitePaneAi");
        const btn = document.getElementById("suiteAiGenBtn");
        if (btn) {
          btn.disabled = true;
          btn.textContent = "正在调用 DeepSeek…";
        }
        // 推理模型单次耗时可达 100s+，远超 WKWebView 对单个 fetch 的 ~60s 强制超时。
        // 因此：POST 仅启动后台任务（秒回），再以 3s 间隔轮询 GET 取结果——每个请求都极短，不会被掐断。
        pane.innerHTML = `
          <div class="suite-ai-empty">
            <h3>AI 操盘手深度解读</h3>
            <p class="suite-ai-progress" id="suiteAiProgress">⏳ 正在调用 DeepSeek 推理引擎…</p>
          </div>
        `;
        const progressEl = document.getElementById("suiteAiProgress");
        const startedAt = Date.now();
        const tick = setInterval(() => {
          if (!progressEl) return;
          const secs = Math.round((Date.now() - startedAt) / 1000);
          progressEl.textContent = `⏳ 正在调用 DeepSeek 推理引擎…已用 ${secs}s（推理模型通常需 60-120s，请稍候）`;
        }, 1000);

        const showError = (msg) => {
          clearInterval(tick);
          pane.innerHTML = `
            <div class="suite-ai-empty">
              <p>LLM 调用失败：${html(msg)}</p>
              <button class="suite-ai-button" type="button" id="suiteAiRetryBtn">重试</button>
            </div>
          `;
          const retry = document.getElementById("suiteAiRetryBtn");
          if (retry) retry.addEventListener("click", () => triggerSuiteAi(code, name));
        };
        const showReady = (ai) => {
          clearInterval(tick);
          if (state.currentSuitePayload) {
            state.currentSuitePayload.ai_interpretation = {
              status: "ready",
              report: ai.report,
              token_usage: ai.token_usage,
              generated_at: ai.generated_at,
            };
          }
          renderAiReady(pane, ai);
        };

        try {
          // 1) 启动后台任务（立即返回 status:running）
          const startResp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}/ai`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name || "", force_refresh: false }),
          });
          const startData = await startResp.json();
          if (startData && startData.success === false) {
            showError(startData.error || "启动失败");
            return;
          }
          if (startData && startData.status === "ready" && startData.report) {
            showReady(startData);
            return;
          }
          // 2) 轮询结果（90 × 3s ≈ 270s，覆盖后端 240s 超时）
          const maxAttempts = 90;
          for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            await new Promise((r) => setTimeout(r, 3000));
            let data = null;
            try {
              const resp = await fetch(`/api/stock-analysis-suite/${encodeURIComponent(code)}/ai`);
              data = await resp.json();
            } catch (pollErr) {
              continue; // 单次轮询抖动，忽略后继续
            }
            if (!data) continue;
            if (data.status === "ready" && data.report) { showReady(data); return; }
            if (data.status === "failed") { showError(data.error || "未知错误"); return; }
            // running / idle → 继续轮询
          }
          showError("生成超时，请重试");
        } catch (error) {
          showError(String(error?.message || error));
        }
      }

      function renderSuiteMarkdown(md) {
        const escaped = String(md || "")
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
        const lines = escaped.split(/\r?\n/);
        const out = [];
        let inParagraph = false;
        const closePara = () => {
          if (inParagraph) {
            out.push("</p>");
            inParagraph = false;
          }
        };
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            closePara();
            continue;
          }
          const h3 = trimmed.match(/^###\s+(.+)$/);
          const h2 = trimmed.match(/^##\s+(.+)$/);
          const h1 = trimmed.match(/^#\s+(.+)$/);
          if (h3) { closePara(); out.push(`<h3>${h3[1]}</h3>`); continue; }
          if (h2) { closePara(); out.push(`<h2>${h2[1]}</h2>`); continue; }
          if (h1) { closePara(); out.push(`<h2>${h1[1]}</h2>`); continue; }
          if (!inParagraph) {
            out.push("<p>");
            inParagraph = true;
          } else {
            out.push("<br>");
          }
          out.push(trimmed);
        }
        closePara();
        return out.join("");
      }

      function opportunityPayloadFromForm() {
        const formEl = $("#opportunityForm");
        const payload = formEl
          ? { ...OPPORTUNITY_CLI_DEFAULTS, ...Object.fromEntries(new FormData(formEl).entries()) }
          : { ...OPPORTUNITY_CLI_DEFAULTS };
        payload.limit = Number(payload.limit || OPPORTUNITY_CLI_DEFAULTS.limit);
        payload.workers = Number(payload.workers || OPPORTUNITY_CLI_DEFAULTS.workers);
        payload.source = payload.source || OPPORTUNITY_CLI_DEFAULTS.source;
        return payload;
      }

      function batchPayloadFromForm() {
        const formEl = $("#batchForm");
        const payload = formEl ? Object.fromEntries(new FormData(formEl).entries()) : {
          stock_codes: "600519, 300750, 000001, 002230, 601138",
          filter_strategy: "balanced",
          max_concurrent: 5,
        };
        payload.max_concurrent = Number(payload.max_concurrent || 5);
        payload.data_types = ["comprehensive"];
        return payload;
      }

      async function startOpportunityFromContext(button = null) {
        await startTrackedJob("/api/opportunity-discovery/start", opportunityPayloadFromForm(), button);
      }

      async function startBatchFromContext(button = null) {
        await startTrackedJob("/api/batch-analysis/start", batchPayloadFromForm(), button);
      }

      function setupWorkbench(data) {
        state.jobs = data.jobs || [];
        updateTaskHeader(state.jobs);
        updateFeatureJobPill(state.jobs);
        renderJobs(state.jobs);
        if (!state.activeJobId && state.jobs.length) {
          state.activeJobId = (state.jobs.find(isActiveJob) || state.jobs[0]).id;
        }
        renderJobDetail(state.jobs.find((job) => job.id === state.activeJobId) || state.jobs[0] || null);
        scheduleJobPolling(state.jobs);

        const opportunityForm = $("#opportunityForm");
        if (opportunityForm && !opportunityForm.dataset.bound) {
          opportunityForm.dataset.bound = "1";
          opportunityForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await startOpportunityFromContext(event.submitter);
          });
        }

        const batchForm = $("#batchForm");
        if (batchForm && !batchForm.dataset.bound) {
          batchForm.dataset.bound = "1";
          batchForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            await startBatchFromContext(event.submitter);
          });
        }
      }

      function renderReports(data) {
        renderReportsDrawer(data.reports);
        if ($("#scoringHealthBody")) {
          loadScoringHealth().catch((error) => {
            const body = $("#scoringHealthBody");
            if (body) body.innerHTML = `<div class="notice status error">健康度读取失败：${html(error.message)}</div>`;
          });
        }
        const reports = $("#reportList");
        if (reports) {
          reports.innerHTML = (data.reports || []).map((item) => `
            <div class="item item-clickable" role="button" tabindex="0" data-preview-url="${html(item.url||'')}" data-preview-label="${html(item.file||'报告')}">
              <div class="item-top">
                <p class="item-title">${html(item.file)}</p>
                <span class="pill">${html(item.type)}</span>
              </div>
              <p class="item-meta">${html(item.updated_at)} · ${item.size_kb} KB</p>
            </div>
          `).join("");
          if (!data.reports?.length) {
            empty(reports, "暂无报告。", emptyAction("start-opportunity", "生成机会报告"));
          }
        }

        const modules = $("#moduleList");
        if (modules) {
          modules.innerHTML = (data.modules || []).map((item) => `
            <div class="item">
              <div class="item-top">
                <p class="item-title">${html(item.name)}</p>
                <span class="pill ${item.status === "ready" ? "ok" : "warn"}">${html(item.status)}</span>
              </div>
              <p class="item-meta">${html(item.scope)} · ${html(item.module)}</p>
            </div>
          `).join("");
        }

        const batch = data.batch || {};
        if ($("#batchMeta")) {
          $("#batchMeta").textContent = `分析 ${batch.analysis_count || 0} · 预测 ${batch.prediction_count || 0}`;
        }
        const runs = [...(batch.analysis_runs || []), ...(batch.prediction_runs || [])];
        const batchRuns = $("#batchRuns");
        if (batchRuns) {
          batchRuns.innerHTML = runs.map((item) => `
            <div class="item item-clickable" role="button" tabindex="0" data-preview-url="${html(item.url||'')}" data-preview-label="${html(item.file||'批量结果')}">
              <div class="item-top">
                <p class="item-title">${html(item.file)}</p>
                <span class="pill">${item.rows || 0} 行</span>
              </div>
              <p class="item-meta">${html(item.updated_at)} · 最高评分 ${num(item.top_score)}</p>
            </div>
          `).join("");
          if (!runs.length) {
            empty(batchRuns, "暂无批量结果。", emptyAction("start-batch", "启动批量分析"));
          }
        }
      }

      // ── 评分健康度卡片（reports 页顶部；数据源 /api/scoring-health）──────────
      async function loadScoringHealth() {
        const data = await fetchJson("/api/scoring-health");
        renderScoringHealth(data);
        return data;
      }
      function renderScoringHealth(data) {
        const body = $("#scoringHealthBody");
        const meta = $("#scoringHealthMeta");
        if (!body) return;
        if (!data || !data.available) {
          if (meta) meta.textContent = "暂无回测数据";
          body.innerHTML = `<div class="item empty-state"><p class="item-meta">${html((data && data.message) || "暂无回测数据")}</p></div>`;
          return;
        }
        const range = data.date_range || {};
        if (meta) meta.textContent = `${html(data.file || "")} · ${range.start || "--"} ~ ${range.end || "--"} · ${range.days || 0} 个交易日`;
        const pct = (v) => (v == null ? "--" : `${(v * 100).toFixed(1)}%`);
        const ret = (v) => (v == null ? "--" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
        const wrCls = (v) => (v == null ? "" : v >= 0.5 ? "change-up" : v < 0.45 ? "change-down" : "");
        const rows = (data.tiers || []).map((t) => {
          const f = t.full || {}, r = t.recent || {};
          const warn = t.tier === "B" && data.warnings?.b_tier_recent_degraded
            ? ` <span class="pill warn" title="B级近20日胜率低于45%">⚠ 退化</span>` : "";
          return `<tr>
            <td><strong>${html(t.tier)}</strong>${warn}</td>
            <td>${f.evaluable ?? 0}/${f.n ?? 0}</td>
            <td class="${wrCls(f.win_rate)}">${pct(f.win_rate)}</td>
            <td>${ret(f.avg_return)}</td>
            <td>${r.evaluable ?? 0}/${r.n ?? 0}</td>
            <td class="${wrCls(r.win_rate)}">${pct(r.win_rate)}</td>
            <td>${ret(r.avg_return)}</td>
          </tr>`;
        }).join("");
        const base = data.baseline || {};
        const degraded = data.degraded || {};
        const degradedCls = (degraded.ratio || 0) > 0.15 ? "change-down" : "";
        body.innerHTML = `
          <div class="actions" style="flex-wrap:wrap;gap:14px;margin-bottom:10px;font-size:0.86rem;">
            <span>基线胜率(全量) <strong class="${wrCls(base.full?.win_rate)}">${pct(base.full?.win_rate)}</strong></span>
            <span>基线胜率(近${data.recent_window_days || 20}日) <strong class="${wrCls(base.recent?.win_rate)}">${pct(base.recent?.win_rate)}</strong></span>
            <span>降级run占比 <strong class="${degradedCls}">${pct(degraded.ratio)}</strong>（近${data.recent_window_days || 20}日 ${pct(degraded.recent_ratio)}）</span>
            ${data.warnings?.b_tier_recent_degraded ? `<span class="pill warn">⚠ B级近${data.recent_window_days || 20}日胜率退化(&lt;45%)</span>` : ""}
          </div>
          <div style="overflow:auto;">
            <table class="csv-preview-table" style="width:100%;font-size:0.84rem;">
              <thead><tr>
                <th>分档</th><th>全量样本(可评估/总)</th><th>全量5日胜率</th><th>全量平均收益</th>
                <th>近${data.recent_window_days || 20}日样本</th><th>近${data.recent_window_days || 20}日胜率</th><th>近${data.recent_window_days || 20}日平均</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
          <p class="item-meta" style="margin-top:8px;">降级run = quant_score=0 或评分&lt;50（取数失败导致评分封顶，污染样本）；胜率按 5 日收益&gt;0 统计。</p>`;
      }

      function normalizeCurve(values) {
        if (!values.length) return [];
        const min = Math.min(...values);
        const max = Math.max(...values);
        if (max === min) return values.map(() => 0.5);
        return values.map((value) => (value - min) / (max - min));
      }

      function resample(points, length = 30) {
        if (points.length < 2) return [];
        const sorted = [...points].sort((a, b) => a.x - b.x);
        const minX = sorted[0].x;
        const maxX = sorted[sorted.length - 1].x;
        const values = [];
        for (let i = 0; i < length; i += 1) {
          const x = minX + ((maxX - minX) * i) / (length - 1);
          let right = sorted.findIndex((point) => point.x >= x);
          if (right <= 0) {
            values.push(1 - sorted[0].y);
            continue;
          }
          const left = sorted[right - 1];
          const next = sorted[right];
          const ratio = (x - left.x) / Math.max(next.x - left.x, 1);
          values.push(1 - (left.y + (next.y - left.y) * ratio));
        }
        return normalizeCurve(values);
      }

      function resampleSeries(values, length = 60) {
        const source = (values || []).map(Number).filter((value) => Number.isFinite(value));
        if (!source.length) return [];
        if (source.length === 1) return Array.from({ length }, () => source[0]);
        const output = [];
        const span = source.length - 1;
        for (let i = 0; i < length; i += 1) {
          const position = (span * i) / Math.max(length - 1, 1);
          const leftIndex = Math.floor(position);
          const rightIndex = Math.min(source.length - 1, leftIndex + 1);
          const ratio = position - leftIndex;
          output.push(source[leftIndex] + (source[rightIndex] - source[leftIndex]) * ratio);
        }
        return output;
      }

      function patternCompareMetrics(queryCurve, stockCurve) {
        const length = Math.max(60, queryCurve.length, stockCurve.length, 2);
        const query = normalizeCurve(resampleSeries(queryCurve, length));
        const stock = normalizeCurve(resampleSeries(stockCurve, length));
        const diff = query.map((value, index) => Number((stock[index] - value).toFixed(4)));
        const absDiff = diff.map((value) => Math.abs(value));
        const mae = absDiff.reduce((sum, value) => sum + value, 0) / Math.max(absDiff.length, 1);
        const rmse = Math.sqrt(diff.reduce((sum, value) => sum + (value * value), 0) / Math.max(diff.length, 1));
        const maxDiff = Math.max(...absDiff, 0);
        let sameDirection = 0;
        let directionTotal = 0;
        for (let index = 1; index < length; index += 1) {
          const queryStep = query[index] - query[index - 1];
          const stockStep = stock[index] - stock[index - 1];
          if (Math.abs(queryStep) < 0.001 && Math.abs(stockStep) < 0.001) continue;
          directionTotal += 1;
          if ((queryStep >= 0 && stockStep >= 0) || (queryStep < 0 && stockStep < 0)) {
            sameDirection += 1;
          }
        }
        const directionRate = directionTotal ? sameDirection / directionTotal : 0;
        const similarity = Math.max(0, 1 - mae);
        return { query, stock, diff, mae, rmse, maxDiff, directionRate, similarity };
      }

      function localCurveExtrema(values, limit = 8) {
        const peaks = [];
        const troughs = [];
        for (let index = 1; index < values.length - 1; index += 1) {
          const prev = values[index - 1];
          const current = values[index];
          const next = values[index + 1];
          const contrast = Math.abs(current - ((prev + next) / 2));
          if (contrast < 0.015) continue;
          if (current >= prev && current >= next && (current > prev || current > next)) {
            peaks.push({ index, value: current, contrast });
          }
          if (current <= prev && current <= next && (current < prev || current < next)) {
            troughs.push({ index, value: current, contrast });
          }
        }
        const pick = (points) => points.sort((a, b) => b.contrast - a.contrast).slice(0, limit).sort((a, b) => a.index - b.index);
        return { peaks: pick(peaks), troughs: pick(troughs) };
      }

      function extremaTrace(points, x, name, color, symbol) {
        if (!points.length) return null;
        return {
          x: points.map((point) => x[point.index]),
          y: points.map((point) => point.value),
          type: "scatter",
          mode: "markers",
          name,
          marker: { color, size: 8, symbol, line: { color: "#ffffff", width: 1 } },
          hovertemplate: "%{x}<br>%{y:.3f}<extra></extra>",
          xaxis: "x",
          yaxis: "y",
        };
      }

      function setupPatternCanvas() {
        const canvas = $("#patternCanvas");
        const ctx = canvas.getContext("2d");
        let drawing = false;

        function draw() {
          const width = canvas.width;
          const height = canvas.height;
          ctx.clearRect(0, 0, width, height);
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, width, height);
          for (let i = 1; i < 24; i += 1) {
            const major = i % 4 === 0;
            ctx.strokeStyle = major ? "#d9e1ec" : "#edf2f7";
            ctx.lineWidth = major ? 1 : 0.6;
            ctx.beginPath();
            ctx.moveTo((width * i) / 24, 0);
            ctx.lineTo((width * i) / 24, height);
            ctx.stroke();
          }
          for (let i = 1; i < 12; i += 1) {
            const major = i % 3 === 0;
            ctx.strokeStyle = major ? "#d9e1ec" : "#edf2f7";
            ctx.lineWidth = major ? 1 : 0.6;
            ctx.beginPath();
            ctx.moveTo(0, (height * i) / 12);
            ctx.lineTo(width, (height * i) / 12);
            ctx.stroke();
          }
          if (state.drawPoints.length > 1) {
            ctx.strokeStyle = "#2f6fdd";
            ctx.lineWidth = 3.2;
            ctx.lineJoin = "round";
            ctx.lineCap = "round";
            ctx.beginPath();
            state.drawPoints.forEach((point, index) => {
              const x = point.x * width;
              const y = point.y * height;
              if (index === 0) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            });
            ctx.stroke();
          }
          $("#matchDrawBtn").disabled = jobLocked() || state.drawPoints.length < 5;
          $("#savePatternBtn").disabled = state.drawPoints.length < 2;
          const exportBtn = $("#exportPatternBtn");
          if (exportBtn) exportBtn.disabled = state.drawPoints.length < 2;
        }

        function point(event) {
          const rect = canvas.getBoundingClientRect();
          return {
            x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
            y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
          };
        }

        canvas.addEventListener("pointerdown", (event) => {
          drawing = true;
          state.drawPoints = [point(event)];
          draw();
        });
        canvas.addEventListener("pointermove", (event) => {
          if (!drawing) return;
          state.drawPoints.push(point(event));
          draw();
        });
        window.addEventListener("pointerup", () => {
          if (!drawing) return;
          drawing = false;
          state.selectedCurve = resample(state.drawPoints);
          draw();
        });
        $("#clearPatternBtn").addEventListener("click", () => {
          state.drawPoints = [];
          state.selectedCurve = null;
          draw();
        });
        $("#savePatternBtn").addEventListener("click", () => {
          saveDrawnPattern(canvas);
        });
        $("#exportPatternBtn").addEventListener("click", () => exportPatternFiles(canvas));
        draw();
      }

      async function saveDrawnPattern(canvas) {
        if (!canvas || state.drawPoints.length < 2) return;
        const curve = state.selectedCurve || resample(state.drawPoints);
        const status = $("#patternStatus");
        const nameInput = $("#patternSaveName");
        const tagsInput = $("#patternSaveTags");
        const name = (nameInput?.value || "").trim() || `手绘 ${new Date().toLocaleString("zh-CN", { hour12: false })}`;
        const tags = (tagsInput?.value || "").trim();
        const body = {
          name,
          normalized_curve: curve,
          points: state.drawPoints,
          source: "draw",
        };
        const wd = Number($("#patternWindowDays")?.value);
        if (Number.isFinite(wd) && wd > 0) body.window_days = wd;
        if (tags) body.tags = tags;
        // 检索过则一并存下查询条件与命中快照，供「历史图形」一键重跑/查看
        if (state.lastQueryParams) body.query_params = state.lastQueryParams;
        if (state.lastMatchSnapshot && state.lastMatchSnapshot.length) body.result_snapshot = state.lastMatchSnapshot;
        try {
          await fetchJson("/api/pattern-search/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (status) {
            status.className = "notice status success";
            const extra = body.result_snapshot ? `（含 ${body.result_snapshot.length} 条匹配快照，可一键重跑）` : "";
            status.textContent = `「${name}」已存入「历史图形」${extra}，可在下方直接复用选股。`;
          }
          if (nameInput) nameInput.value = "";
          if (tagsInput) tagsInput.value = "";
          await loadSavedPatterns();
        } catch (error) {
          if (status) {
            status.className = "notice status warning";
            status.textContent = `保存到历史库失败：${error.message}`;
          }
        }
      }

      // 按需导出 PNG / JSON（不再每次保存都强制下载，避免污染下载目录）
      function exportPatternFiles(canvas) {
        if (!canvas || state.drawPoints.length < 2) return;
        const curve = state.selectedCurve || resample(state.drawPoints);
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        const payload = {
          type: "kronos-pattern-drawing",
          version: 1,
          saved_at: new Date().toISOString(),
          points: state.drawPoints,
          normalized_curve: curve,
        };
        const jsonBlob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        downloadBlob(jsonBlob, `kronos_pattern_${stamp}.json`);
        canvas.toBlob((blob) => {
          if (blob) downloadBlob(blob, `kronos_pattern_${stamp}.png`);
        });
      }

      async function loadSavedPatterns() {
        const list = $("#savedPatternList");
        if (!list) return;
        try {
          const data = await fetchJson("/api/pattern-search/saved?limit=50");
          state.savedPatterns = data.patterns || [];
          renderSavedPatterns(state.savedPatterns);
        } catch (error) {
          empty(list, `历史图形读取失败：${error.message}`);
        }
      }

      function renderSavedPatterns(patterns) {
        const list = $("#savedPatternList");
        const meta = $("#savedPatternMeta");
        if (!list) return;
        if (meta) meta.textContent = `${patterns.length} 条`;
        if (!patterns.length) {
          empty(list, "暂无历史图形。在左侧手绘后点「保存图形」即可入库复用。");
          return;
        }
        list.innerHTML = patterns
          .map((p) => {
            const tags = (p.tags || []).map((t) => `<span class="tag-chip">${html(t)}</span>`).join("");
            const rerun = p.query_params
              ? `<button class="button secondary compact" type="button" data-saved-rerun="${p.id}" title="按保存时的窗口/回推/数量条件重新检索">重跑检索</button>`
              : "";
            const snap = p.result_count > 0
              ? `<button class="button secondary compact" type="button" data-saved-snap="${p.id}">查看快照(${p.result_count})</button>`
              : "";
            const metaBits = [
              html(p.created_at || ""),
              `${p.normalized_curve?.length || 0} 点`,
              p.window_days ? `窗口${p.window_days}日` : "",
              p.result_count ? `命中${p.result_count}` : "",
            ].filter(Boolean).join(" · ");
            return `
            <div class="item" data-saved-id="${p.id}">
              <div class="item-top">
                <p class="item-title">${html(p.name || "未命名形态")}</p>
                <span class="pill">${String(p.source || "draw").startsWith("stock") ? "个股" : "手绘"}</span>
              </div>
              <p class="item-meta">${metaBits}</p>
              ${tags ? `<div class="tag-row">${tags}</div>` : ""}
              <div class="actions" style="margin-top: 8px;">
                <button class="button compact" type="button" data-saved-use="${p.id}">用此形态选股</button>
                ${rerun}
                ${snap}
                <button class="button secondary compact" type="button" data-saved-preview="${p.id}">预览</button>
                <button class="button secondary compact" type="button" data-saved-del="${p.id}">删除</button>
              </div>
            </div>
          `;
          })
          .join("");
        const find = (id) => patterns.find((x) => String(x.id) === id);
        list.querySelectorAll("[data-saved-use]").forEach((el) => {
          el.addEventListener("click", () => { const p = find(el.dataset.savedUse); if (p) useSavedPattern(p, { run: true }); });
        });
        list.querySelectorAll("[data-saved-rerun]").forEach((el) => {
          el.addEventListener("click", () => { const p = find(el.dataset.savedRerun); if (p) rerunSavedPattern(p); });
        });
        list.querySelectorAll("[data-saved-snap]").forEach((el) => {
          el.addEventListener("click", () => { const p = find(el.dataset.savedSnap); if (p) showSavedSnapshot(p); });
        });
        list.querySelectorAll("[data-saved-preview]").forEach((el) => {
          el.addEventListener("click", () => { const p = find(el.dataset.savedPreview); if (p) useSavedPattern(p, { run: false }); });
        });
        list.querySelectorAll("[data-saved-del]").forEach((el) => {
          el.addEventListener("click", () => deleteSavedPattern(el.dataset.savedDel));
        });
      }

      // 按保存时的查询条件回填筛选器并重新检索
      function rerunSavedPattern(p) {
        const qp = p.query_params || {};
        if (qp.window_days && $("#patternWindowDays")) $("#patternWindowDays").value = String(qp.window_days);
        if (qp.query_offset_days != null && $("#patternOffsetDays")) $("#patternOffsetDays").value = String(qp.query_offset_days);
        if (qp.top_n && $("#patternTopN")) $("#patternTopN").value = String(qp.top_n);
        useSavedPattern(p, { run: true });
      }

      // 查看保存时落库的命中快照（不重新检索，直接展示历史结果）
      function showSavedSnapshot(p) {
        const snap = p.result_snapshot || [];
        if (!snap.length) { showToast("该形态未保存匹配快照"); return; }
        const meta = $("#patternResultMeta");
        if (meta) meta.textContent = `历史快照 ${snap.length} 条 · 保存于 ${p.created_at || "--"}`;
        state.selectedCurve = p.normalized_curve;
        renderPatternResults(snap, p.normalized_curve);
      }

      function useSavedPattern(pattern, { run = false } = {}) {
        if (!pattern?.normalized_curve?.length) return;
        state.selectedCurve = pattern.normalized_curve;
        const matchDraw = $("#matchDrawBtn");
        const matchStock = $("#matchStockBtn");
        if (matchDraw) matchDraw.disabled = false;
        if (matchStock) matchStock.disabled = false;
        const title = $("#patternCompareTitle");
        const cmeta = $("#patternCompareMeta");
        if (title) title.textContent = `${pattern.name || "历史形态"} 预览`;
        if (cmeta) cmeta.textContent = pattern.created_at || "--";
        plotPatternCompare(pattern.normalized_curve, {
          stock_code: pattern.name || "saved",
          stock_name: pattern.name || "历史形态",
          normalized_curve: pattern.normalized_curve,
          score: 1,
        });
        if (run) {
          runPatternMatch(pattern.normalized_curve).catch((error) => alert(error.message));
        }
      }

      async function deleteSavedPattern(id) {
        try {
          await fetchJson(`/api/pattern-search/saved/${encodeURIComponent(id)}/delete`, { method: "POST" });
          await loadSavedPatterns();
        } catch (error) {
          alert(`删除失败：${error.message}`);
        }
      }

      function downloadBlob(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }

      function downloadUrl(url, filename = "") {
        const link = document.createElement("a");
        link.href = url;
        if (filename) link.download = filename;
        link.rel = "noopener";
        document.body.appendChild(link);
        link.click();
        link.remove();
      }

      function patternStatusText(status) {
        if (status.available) {
          const stale = status.staleness_days != null ? ` · ${status.staleness_days} 天前` : "";
          const warning = status.warning ? ` · ${status.warning}` : "";
          return `指纹库 ${status.total_stocks} 只股票 · 快照 ${status.snapshot_date || "--"}${stale}${warning}`;
        }
        return status.warning || "指纹库尚未生成，请先点击刷新";
      }

      function renderPatternStatus(status, statusEl = null, metaEl = null) {
        const available = Boolean(status.available);
        const statusClass = available && !status.warning ? "success" : "warning";
        if (statusEl) {
          statusEl.className = `notice status ${statusClass}`;
          statusEl.textContent = patternStatusText(status);
        }
        if (metaEl) {
          metaEl.textContent = available ? `${status.total_stocks || 0} 只` : "未生成";
        }
      }

      async function loadPatternStatus() {
        const status = await fetchJson("/api/pattern-search/status");
        renderPatternStatus(status, $("#patternStatus"));
        renderPatternStatus(status, $("#featurePatternStatus"), $("#featurePatternMeta"));
        return status;
      }

      async function refreshPatternDatabase({ button = null, statusEl = null, workers = 16 } = {}) {
        if (button) button.disabled = true;
        const target = statusEl || $("#patternStatus") || $("#featurePatternStatus");
        try {
          const data = await fetchJson("/api/pattern-search/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ workers }),
          });
          if (target) target.textContent = `刷新任务已创建：${data.job_id}`;
          await pollJob(data.job_id, {
            statusEl: target,
            onDone: async (job) => {
              if (job.status === "finished") {
                await loadPatternStatus();
              } else if (target) {
                target.className = "notice status error";
                target.textContent = `刷新失败：${job.error || "请查看任务日志"}`;
              }
            },
          });
        } catch (error) {
          if (target) {
            target.className = "notice status error";
            target.textContent = error.message;
          }
          alert(error.message);
        } finally {
          if (button) button.disabled = false;
        }
      }

      async function runPatternMatch(curve) {
        if (!curve?.length) return;
        $("#patternResults").innerHTML = `<div class="item"><p class="item-meta">正在检索...</p></div>`;
        const payload = {
          curve,
          top_n: Number($("#patternTopN")?.value || 30),
          window_days: Number($("#patternWindowDays").value),
          query_offset_days: Number($("#patternOffsetDays").value),
        };
        const data = await fetchJson("/api/pattern-search/match", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const rtNote = data.quoted ? ` · 实时报价 ${(data.quote_updated_at || "").slice(11, 19)}` : "";
        $("#patternResultMeta").textContent = `${data.count || 0} 条 · ${data.compute_ms || 0} ms${rtNote}`;
        renderPatternResults(data.matches || [], data.query_curve || curve);
        // 记下本次查询条件与命中快照，保存形态时可一并落库（一键重跑 / 查看历史快照）
        state.lastQueryParams = {
          top_n: payload.top_n,
          window_days: payload.window_days,
          query_offset_days: payload.query_offset_days,
        };
        state.lastMatchSnapshot = (data.matches || []).slice(0, 60).map((m) => ({
          stock_code: m.stock_code,
          stock_name: m.stock_name,
          score: m.score,
          market: m.market,
          industry: m.industry,
          latest_close: m.latest_close,
          latest_change_pct: m.latest_change_pct,
          realtime_price: m.realtime_price,
          realtime_change_pct: m.realtime_change_pct,
          snapshot_date: m.snapshot_date,
        }));
        state.lastBacktest = {
          curve,
          window_days: payload.window_days,
          query_offset_days: payload.query_offset_days,
          codes: (data.matches || []).map((m) => m.stock_code).filter(Boolean),
        };
        const backtestBtn = $("#patternBacktestBtn");
        if (backtestBtn) backtestBtn.disabled = jobLocked() || state.lastBacktest.codes.length === 0;
      }

      async function runPatternBacktest() {
        const ctx = state.lastBacktest;
        if (!ctx || !ctx.codes?.length) { alert("请先检索出相似股票，再回测形态。"); return; }
        if (jobLocked()) { alert("已有任务进行中，请等待当前任务完成后再回测。"); return; }
        const btn = $("#patternBacktestBtn");
        const meta = $("#patternBacktestMeta");
        const body = $("#patternBacktestBody");
        if (btn) btn.disabled = true;
        if (meta) meta.textContent = "回测中…";
        if (body) body.innerHTML = `<p class="muted"><span class="spinner"></span> 正在联网拉取同类股票近一年日线并回测，请稍候（约 10–40 秒）…</p>`;
        try {
          const start = await fetchJson("/api/pattern-search/backtest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              curve: ctx.curve,
              stock_codes: ctx.codes.slice(0, 20),
              window_days: ctx.window_days,
              query_offset_days: ctx.query_offset_days,
              top_n: 20,
            }),
          });
          const jobId = start.job_id || start.job?.id;
          if (!jobId) throw new Error("回测任务创建失败");
          const job = await pollJob(jobId, {
            intervalMs: 2000,
            maxAttempts: 90,
            onUpdate: (j) => {
              const log = latestJobLog(j);
              if (meta && log) meta.textContent = log;
            },
          });
          if (!job) {
            if (body) body.innerHTML = `<p class="notice status error">回测超时，请稍后重试。</p>`;
            if (meta) meta.textContent = "超时";
            return;
          }
          if (job.status === "failed") {
            if (body) body.innerHTML = `<p class="notice status error">回测失败：${html(job.error || "请查看任务日志")}</p>`;
            if (meta) meta.textContent = "失败";
            return;
          }
          renderPatternBacktest(job.result || {});
        } catch (error) {
          if (body) body.innerHTML = `<p class="notice status error">${html(error.message)}</p>`;
          if (meta) meta.textContent = "失败";
        } finally {
          if (btn) btn.disabled = false;
        }
      }

      function backtestResultHtml(result) {
        if (!result || !result.ok) {
          return `<p class="notice status error">${html(result?.error || "回测无结果")}</p>`;
        }
        const pct = (v) => `${(Number(v) * 100).toFixed(1)}%`;
        const signed = (v) => `${Number(v) >= 0 ? "+" : ""}${(Number(v) * 100).toFixed(1)}%`;
        const rows = (result.horizons || []).map((h) => `
          <tr>
            <td>后${h.horizon}日</td>
            <td>${h.count}</td>
            <td class="${changeClass(h.win_rate - 0.5)}">${pct(h.win_rate)}</td>
            <td class="${changeClass(h.avg_return)}">${signed(h.avg_return)}</td>
            <td class="${changeClass(h.median_return)}">${signed(h.median_return)}</td>
            <td class="muted"><span class="${changeClass(h.best)}">${signed(h.best)}</span> / <span class="${changeClass(h.worst)}">${signed(h.worst)}</span></td>
          </tr>`).join("");
        const tops = (result.top_stocks || []).slice(0, 6)
          .map((s) => `${html(s.stock_name || s.stock_code)}(${s.count}次)`).join(" · ") || "--";
        const errNote = result.errors?.length
          ? `<p class="muted backtest-note">注：${result.errors.length} 只股票数据拉取失败，已跳过。</p>`
          : "";
        return `
          <p class="backtest-summary">命中相似形态样本 <strong>${result.sample_count}</strong> 次 · 成功扫描 ${result.candidates_scanned}/${result.candidates_total} 只 · 相似度≥${pct(result.similarity_threshold)} · 窗口${result.window_days}日</p>
          <table class="backtest-table">
            <thead><tr><th>周期</th><th>样本</th><th>胜率</th><th>平均涨幅</th><th>中位数</th><th>最佳/最差</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
          <p class="backtest-tops">样本最多：${tops}</p>
          ${errNote}
          <p class="muted backtest-disclaimer">历史回测基于公开日线数据与形态相似度统计，不构成投资建议，过往表现不代表未来收益。</p>`;
      }

      function renderPatternBacktest(result) {
        const meta = $("#patternBacktestMeta");
        const body = $("#patternBacktestBody");
        if (!body) return;
        body.innerHTML = backtestResultHtml(result);
        if (meta) meta.textContent = (result && result.ok) ? `${result.sample_count} 样本` : "--";
      }

      // 财务三大表(item G):懒加载 /api/stock/financial-statements,默认读缓存,可联网刷新。
      function financialTableHtml(title, periods) {
        if (!periods || !periods.length) {
          return `<div class="fin-block"><h4>${html(title)}</h4><p class="suite-empty-note">暂无${html(title)}数据</p></div>`;
        }
        const labelOrder = [];
        const seen = new Set();
        periods.forEach((p) => Object.keys(p.items || {}).forEach((k) => {
          if (!seen.has(k)) { seen.add(k); labelOrder.push(k); }
        }));
        const thead = `<tr><th class="fin-item-col">项目</th>${periods.map((p) => `<th>${html(p.period || p.report_date || "--")}</th>`).join("")}</tr>`;
        const body = labelOrder.map((label) => {
          const tds = periods.map((p) => {
            const v = (p.items || {})[label];
            return `<td>${v == null || v === "" ? "--" : html(formatMoneyText(v, "--"))}</td>`;
          }).join("");
          return `<tr><td class="fin-item-col">${html(label)}</td>${tds}</tr>`;
        }).join("");
        return `<div class="fin-block"><h4>${html(title)}</h4><div class="fin-table-wrap"><table class="fin-table"><thead>${thead}</thead><tbody>${body}</tbody></table></div></div>`;
      }

      async function renderSuiteFinancials(forceRefresh = false) {
        const pane = document.getElementById("suitePaneFinancials");
        if (!pane) return;
        const code = state.currentStockCode || state.currentSuitePayload?.stock?.code || "";
        if (!code) { pane.innerHTML = `<div class="suite-ai-empty"><p>请先打开一只股票。</p></div>`; return; }
        if (!forceRefresh && pane.dataset.rendered === "1" && pane.dataset.code === code) return;
        pane.dataset.rendered = "1";
        pane.dataset.code = code;
        pane.innerHTML = `<div class="suite-ai-empty"><p class="suite-empty-note"><span class="spinner"></span> 读取财务三大表…</p></div>`;
        let data;
        try {
          data = await fetchJson(`/api/stock/financial-statements?code=${encodeURIComponent(code)}${forceRefresh ? "&force=1" : ""}`);
        } catch (e) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>财务数据加载失败：${html(e.message)}</p></div>`;
          return;
        }
        const st = data.statements || {};
        const defs = [["balance", "资产负债表"], ["income", "利润表"], ["cashflow", "现金流量表"]];
        if (defs.every(([k]) => !(st[k] && st[k].length))) {
          pane.innerHTML = `<div class="suite-ai-empty"><p>暂无财务数据 · <button class="button secondary compact" type="button" data-fin-refresh>联网获取</button></p></div>`;
          pane.querySelector("[data-fin-refresh]")?.addEventListener("click", () => renderSuiteFinancials(true));
          return;
        }
        const srcLabel = data.source === "tushare" ? "Tushare(付费)" : (data.source === "akshare" ? "东方财富(免费)" : "—");
        const head = `
          <div class="fin-head">
            <span class="fin-src">来源 ${html(srcLabel)}${data.cached ? " · 缓存" : " · 实时取数"}${data.as_of ? " · " + html(String(data.as_of).slice(0, 10)) : ""} · 单位 元(亿/万)</span>
            <button class="button secondary compact" type="button" data-fin-refresh>刷新(联网)</button>
          </div>`;
        pane.innerHTML = head + defs.map(([key, label]) => financialTableHtml(label, st[key] || [])).join("");
        pane.querySelector("[data-fin-refresh]")?.addEventListener("click", () => renderSuiteFinancials(true));
      }

      function renderSuitePatternBacktest() {
        const pane = document.getElementById("suitePanePatternBacktest");
        if (!pane) return;
        if (pane.dataset.rendered === "1") return;  // 已渲染（含结果），切回来不覆盖
        pane.dataset.rendered = "1";
        const code = state.currentStockCode || "";
        pane.innerHTML = `
          <p class="suite-empty-note">基于该股<strong>当前形态</strong>，联网检索同类 Top20 股票并回测：统计历史上出现相似形态后 5/10/20 日的胜率与平均涨幅。约需 10–40 秒。</p>
          <div class="actions" style="margin-top:12px;">
            <button id="suiteBacktestRunBtn" class="button" type="button">开始形态回测</button>
          </div>
          <div id="suiteBacktestResult" style="margin-top:14px;"></div>`;
        const runBtn = pane.querySelector("#suiteBacktestRunBtn");
        if (runBtn) runBtn.addEventListener("click", () => runSuitePatternBacktest(code).catch((e) => alert(e.message)));
      }

      async function runSuitePatternBacktest(code) {
        const resultEl = document.getElementById("suiteBacktestResult");
        const runBtn = document.getElementById("suiteBacktestRunBtn");
        if (!resultEl) return;
        if (!code) { resultEl.innerHTML = `<p class="notice status error">缺少股票代码。</p>`; return; }
        if (jobLocked()) { resultEl.innerHTML = `<p class="notice status warn">已有任务进行中，请等待完成后再回测。</p>`; return; }
        if (runBtn) runBtn.disabled = true;
        resultEl.innerHTML = `<p class="muted"><span class="spinner"></span> 正在读取该股形态并联网回测同类股票，请稍候…</p>`;
        try {
          const curveResp = await fetchJson(`/api/pattern-search/stock-curve/${encodeURIComponent(code)}`);
          const curve = curveResp?.normalized_curve;
          if (!curve || curve.length < 5) {
            resultEl.innerHTML = `<p class="notice status warn">该股暂不在形态指纹库中。请先到「形态搜股」页点击「刷新指纹库」，再回到此处回测。</p>`;
            return;
          }
          const start = await fetchJson("/api/pattern-search/backtest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ curve, top_n: 20, window_days: 30 }),
          });
          const jobId = start.job_id || start.job?.id;
          if (!jobId) throw new Error("回测任务创建失败");
          const job = await pollJob(jobId, { intervalMs: 2000, maxAttempts: 90 });
          if (!job) { resultEl.innerHTML = `<p class="notice status error">回测超时，请稍后重试。</p>`; return; }
          if (job.status === "failed") {
            resultEl.innerHTML = `<p class="notice status error">回测失败：${html(job.error || "请查看任务日志")}</p>`;
            return;
          }
          resultEl.innerHTML = backtestResultHtml(job.result || {});
        } catch (error) {
          resultEl.innerHTML = `<p class="notice status error">${html(error.message)}</p>`;
        } finally {
          if (runBtn) runBtn.disabled = false;
        }
      }

      function renderPatternResults(matches, queryCurve) {
        const target = $("#patternResults");
        target.innerHTML = matches.map((item, index) => {
          const hasRt = item.realtime && Number.isFinite(Number(item.realtime_price));
          const rtPct = Number(item.realtime_change_pct);
          const rtLine = hasRt
            ? `<p class="item-meta pattern-rt"><span class="pattern-rt-badge">实时</span>${num(item.realtime_price)} <span class="${changeClass(rtPct)}">${Number.isFinite(rtPct) ? (rtPct >= 0 ? "+" : "") + num(rtPct) + "%" : "--"}</span></p>`
            : "";
          return `
          <button class="item pattern-result-item" type="button" data-pattern-index="${index}" data-stock-code="${html(item.stock_code || "")}" data-stock-name="${html(item.stock_name || "")}" data-sector="${html(item.industry || "")}" title="双击打开K线大图">
            <div class="item-top">
              <p class="item-title">${index + 1}. ${html(item.stock_name || item.stock_code)}</p>
              <strong>${num(Number(item.score || 0) * 100, 1)}%</strong>
            </div>
            ${rtLine}
            <p class="item-meta">${html(item.stock_code)} · ${html(item.market || "--")} · ${html(item.industry || "--")} · 快照 ${html(item.snapshot_date || "")}</p>
          </button>`;
        }).join("");
        if (!matches.length) empty(target, "暂无匹配结果。");
        target.querySelectorAll("[data-pattern-index]").forEach((el) => {
          el.addEventListener("click", () => {
            window.clearTimeout(state.patternClickTimer);
            state.patternClickTimer = window.setTimeout(() => {
              const item = matches[Number(el.dataset.patternIndex)];
              plotPatternCompare(queryCurve, item);
              openStockContext({
                type: "stock",
                stock_code: item?.stock_code || el.dataset.stockCode,
                stock_name: item?.stock_name || el.dataset.stockName || "",
                board_name: item?.industry || el.dataset.sector || "",
              }).catch((error) => console.warn("打开股票上下文失败", error));
            }, 180);
          });
          el.addEventListener("dblclick", (event) => {
            event.preventDefault();
            window.clearTimeout(state.patternClickTimer);
            const item = matches[Number(el.dataset.patternIndex)];
            openStockKlineModal(item?.stock_code || el.dataset.stockCode, 240, { stockName: item?.stock_name || el.dataset.stockName || "" }).catch((error) => alert(error.message));
          });
        });
        if (matches[0]) plotPatternCompare(queryCurve, matches[0]);
      }

      function plotPatternCompare(queryCurve, item) {
        $("#patternCompareTitle").textContent = `${item.stock_name || item.stock_code} 形态对比`;
        const stockCurve = item.matched_curve || item.normalized_curve || item.curve || item.close_curve || [];
        if (!window.Plotly || !queryCurve?.length || !stockCurve.length) {
          $("#patternCompareChart").innerHTML = `<p class="muted">暂无可绘制曲线。</p>`;
          $("#patternCompareMeta").textContent = `${num(Number(item.score || 0) * 100, 1)}%`;
          return;
        }

        const metrics = patternCompareMetrics(queryCurve, stockCurve);
        const x = metrics.query.map((_, index) => index + 1);
        const lower = metrics.query.map((value, index) => Math.min(value, metrics.stock[index]));
        const upper = metrics.query.map((value, index) => Math.max(value, metrics.stock[index]));
        const extrema = localCurveExtrema(metrics.stock, 6);
        const maxDiffRange = Math.max(metrics.maxDiff * 1.25, 0.08);
        const traces = [
          {
            x,
            y: lower,
            type: "scatter",
            mode: "lines",
            line: { color: "rgba(0,0,0,0)", width: 0 },
            hoverinfo: "skip",
            showlegend: false,
            xaxis: "x",
            yaxis: "y",
          },
          {
            x,
            y: upper,
            type: "scatter",
            mode: "lines",
            fill: "tonexty",
            fillcolor: "rgba(217, 45, 32, 0.12)",
            line: { color: "rgba(0,0,0,0)", width: 0 },
            name: "偏差带",
            hoverinfo: "skip",
            xaxis: "x",
            yaxis: "y",
          },
          {
            x,
            y: metrics.query,
            type: "scatter",
            mode: "lines",
            name: "查询形态",
            line: { color: "#2f6fdd", width: 3 },
            hovertemplate: "位置 %{x}<br>查询 %{y:.3f}<extra></extra>",
            xaxis: "x",
            yaxis: "y",
          },
          {
            x,
            y: metrics.stock,
            type: "scatter",
            mode: "lines",
            name: item.stock_name || item.stock_code,
            line: { color: "#c43d36", width: 3 },
            hovertemplate: "位置 %{x}<br>匹配 %{y:.3f}<extra></extra>",
            xaxis: "x",
            yaxis: "y",
          },
          {
            x,
            y: metrics.diff,
            type: "scatter",
            mode: "lines",
            name: "差值",
            fill: "tozeroy",
            fillcolor: "rgba(111, 85, 216, 0.10)",
            line: { color: "#6f55d8", width: 2 },
            hovertemplate: "位置 %{x}<br>差值 %{y:.4f}<extra></extra>",
            xaxis: "x2",
            yaxis: "y2",
          },
        ];
        [extremaTrace(extrema.peaks, x, "局部高点", "#a86d00", "triangle-up"), extremaTrace(extrema.troughs, x, "局部低点", "#11756f", "triangle-down")]
          .filter(Boolean)
          .forEach((trace) => traces.push(trace));

        $("#patternCompareMeta").textContent = [
          `相似 ${num(metrics.similarity * 100, 1)}%`,
          `MAE ${num(metrics.mae, 3)}`,
          `RMSE ${num(metrics.rmse, 3)}`,
          `最大偏差 ${num(metrics.maxDiff, 3)}`,
          `方向一致 ${num(metrics.directionRate * 100, 1)}%`,
        ].join(" · ");

        Plotly.react("patternCompareChart", traces, {
          margin: { l: 42, r: 16, t: 12, b: 34 },
          hovermode: "x unified",
          legend: {
            orientation: "h",
            x: 0,
            y: 1.08,
            font: { size: 11, color: "#344256" },
          },
          xaxis: {
            domain: [0, 1],
            anchor: "y",
            showgrid: false,
            zeroline: false,
          },
          yaxis: {
            domain: [0.34, 1],
            range: [-0.05, 1.05],
            title: "标准化走势",
            gridcolor: "#edf2f7",
            zeroline: false,
          },
          xaxis2: {
            domain: [0, 1],
            anchor: "y2",
            matches: "x",
            title: "形态位置",
            gridcolor: "#edf2f7",
          },
          yaxis2: {
            domain: [0, 0.22],
            range: [-maxDiffRange, maxDiffRange],
            title: "差值",
            gridcolor: "#edf2f7",
            zeroline: true,
            zerolinecolor: "#c6d0dd",
          },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#ffffff",
        }, { displayModeBar: false, responsive: true });
      }

      function setupPatterns() {
        setupPatternCanvas();
        loadPatternStatus().catch((error) => {
          $("#patternStatus").textContent = error.message;
        });
        loadSavedPatterns().catch((error) => console.warn("历史图形读取失败", error));
        document.querySelectorAll("[data-pattern-tab]").forEach((button) => {
          button.addEventListener("click", () => {
            document.querySelectorAll("[data-pattern-tab]").forEach((el) => el.classList.remove("active"));
            button.classList.add("active");
            const mode = button.dataset.patternTab;
            $("#drawPane").classList.toggle("hidden", mode !== "draw");
            $("#stockPane").classList.toggle("hidden", mode !== "stock");
          });
        });
        $("#matchDrawBtn").addEventListener("click", () => runPatternMatch(state.selectedCurve).catch((error) => alert(error.message)));
        $("#stockSearchBtn").addEventListener("click", async () => {
          const q = $("#patternStockInput").value.trim();
          if (!q) return;
          const data = await fetchJson(`/api/pattern-search/stocks?q=${encodeURIComponent(q)}&limit=8`);
          const target = $("#stockSuggestions");
          target.innerHTML = (data.stocks || []).map((item) => `
            <button class="item" type="button" data-stock-code="${html(item.stock_code)}" data-stock-name="${html(item.stock_name || "")}" data-sector="${html(item.industry || "")}" title="双击打开K线大图">
              <div class="item-top">
                <p class="item-title">${html(item.stock_name || item.stock_code)}</p>
                <span class="pill">${html(item.stock_code)}</span>
              </div>
              <p class="item-meta">${html(item.market || "--")} · ${html(item.industry || "--")}</p>
            </button>
          `).join("");
          if (!data.stocks?.length) empty(target, "没有匹配股票。");
          target.querySelectorAll("[data-stock-code]").forEach((el) => {
            el.addEventListener("click", async () => {
              window.clearTimeout(state.patternClickTimer);
              state.patternClickTimer = window.setTimeout(async () => {
              const payload = await fetchJson(`/api/pattern-search/stock-curve/${encodeURIComponent(el.dataset.stockCode)}`);
              state.selectedStock = payload;
              state.selectedCurve = payload.normalized_curve;
              $("#matchStockBtn").disabled = jobLocked();
              $("#patternCompareTitle").textContent = `${payload.stock_name} 形态预览`;
              $("#patternCompareMeta").textContent = payload.snapshot_date || "--";
              plotPatternCompare(payload.normalized_curve, {
                stock_code: payload.stock_code,
                stock_name: payload.stock_name,
                normalized_curve: payload.normalized_curve,
                score: 1,
              });
              openStockContext({
                type: "stock",
                stock_code: payload.stock_code,
                stock_name: payload.stock_name || "",
                board_name: payload.industry || "",
              }).catch((error) => console.warn("打开股票上下文失败", error));
              }, 180);
            });
            el.addEventListener("dblclick", (event) => {
              event.preventDefault();
              window.clearTimeout(state.patternClickTimer);
              openStockKlineModal(el.dataset.stockCode, 240, { stockName: el.dataset.stockName || "" }).catch((error) => alert(error.message));
            });
          });
        });
        $("#matchStockBtn").addEventListener("click", () => runPatternMatch(state.selectedCurve).catch((error) => alert(error.message)));
        const patternBacktestBtn = $("#patternBacktestBtn");
        if (patternBacktestBtn) {
          patternBacktestBtn.addEventListener("click", () => runPatternBacktest().catch((error) => alert(error.message)));
        }
        $("#refreshPatternDbBtn").addEventListener("click", () => {
          refreshPatternDatabase({ button: $("#refreshPatternDbBtn"), statusEl: $("#patternStatus") });
        });
      }

      function renderFeatureOverview(data) {
        renderOverview(data);
        renderReports(data);
        setupWorkbench(data);
        renderOverviewHotLists(data);
        renderOverviewNews(data);
        setupOverviewSearch();

        const settings = data.settings || {};
        const jobs = data.jobs || [];
        const market = data.market || {};
        const llmReady = Boolean(settings.llm?.configured);
        const tushareReady = Boolean(settings.tushare?.configured);
        $("#featureOverviewStatus").textContent = `市场粒子 ${market.total_particles ?? "--"}`;
        $("#featureOverviewStatus").className = "pill ok";
        updateFeatureJobPill(jobs);
        $("#featureConfigPill").textContent = `AI ${llmReady ? "已配置" : "未配置"} · TuShare ${tushareReady ? "已配置" : "未配置"}`;
        $("#featureConfigPill").className = `pill ${llmReady && tushareReady ? "ok" : "warn"}`;
      }

      function providerModelRows(settings) {
        const providers = settings.llm?.providers || [];
        if (!providers.length) {
          return `<div class="item"><p class="item-meta">未找到模型 Provider 配置。</p></div>`;
        }
        return providers.map((provider) => `
          <div class="item" data-provider="${html(provider.name)}">
            <div class="item-top">
              <p class="item-title">${html(provider.name)}</p>
              <span class="pill ${provider.has_api_key ? "ok" : "warn"}">${provider.has_api_key ? "Key " + html(provider.api_key_masked) : "未配置 Key"}</span>
            </div>
            <div class="form-grid">
              <label>API Key
                <input type="password" data-provider-key="${html(provider.name)}" placeholder="留空不覆盖现有 Key" autocomplete="off" />
              </label>
              <label>Provider 状态
                <input value="${provider.enabled ? "启用" : "配置保留"} · ${html(provider.api_style)}" disabled />
              </label>
            </div>
            <div class="check-row" style="margin-top: 10px;">
              ${(provider.models || []).map((model) => `
                <label title="${html(model.description || model.model_id || "")}">
                  <input type="checkbox" data-llm-model="${html(model.full_key)}" ${model.selected ? "checked" : ""} />
                  ${html(model.key)}
                </label>
              `).join("")}
            </div>
          </div>
        `).join("");
      }

      function autoFollowMetaText(af) {
        return af && af.enabled
          ? `已开启 · ≥${num(af.min_score, 0)}分 · 单票${num(af.per_stock_amount, 0)}元 · 持有${af.hold_days}日`
          : "已关闭";
      }
      function fillAutoFollowForm(af) {
        const form = $("#autoFollowForm");
        if (!form || !af) return;
        form.elements.enabled.value = af.enabled ? "1" : "0";
        form.elements.min_score.value = af.min_score ?? 78;
        form.elements.per_stock_amount.value = af.per_stock_amount ?? 20000;
        form.elements.hold_days.value = af.hold_days ?? 5;
        const meta = $("#autoFollowMeta");
        if (meta) meta.textContent = autoFollowMetaText(af);
      }

      async function loadSettings() {
        const settings = await fetchJson("/api/settings");
        $("#llmProviderList").innerHTML = providerModelRows(settings);
        $("#llmConfigMeta").textContent = settings.llm?.configured ? "已配置" : "未配置";
        $("#llmConfigPath").textContent = `保存位置：${settings.llm?.config_path || "--"}`;
        $("#tushareConfigMeta").textContent = settings.tushare?.configured ? `已配置 ${settings.tushare.token_masked}` : "未配置";
        $("#tushareConfigPath").textContent = `保存位置：${settings.tushare?.config_path || "--"}`;
        $("#tushareSettingsForm [name='timeout']").value = settings.tushare?.timeout || 30;
        $("#tushareSettingsForm [name='retry_count']").value = settings.tushare?.retry_count || 3;
        fillAutoFollowForm(settings.auto_follow);
        return settings;
      }

      async function loadKronosStatus() {
        const [status, models] = await Promise.all([
          fetchJson("/api/model-status"),
          fetchJson("/api/available-models"),
        ]);
        const select = $("#kronosModelSelect");
        const previous = select?.value;
        select.innerHTML = Object.entries(models.models || {}).map(([key, meta]) => `
          <option value="${html(key)}">${html(meta.name || key)} · ${html(meta.params || "")}</option>
        `).join("");
        if (previous && [...select.options].some((option) => option.value === previous)) {
          select.value = previous;
        }
        $("#kronosModelMeta").textContent = status.loaded ? "已载入" : status.available ? "可载入" : "不可用";
        $("#kronosModelStatus").className = `notice status ${status.loaded ? "success" : status.available ? "info" : "warning"}`;
        $("#kronosModelStatus").textContent = status.message || "--";
        $("#loadKronosModelBtn").disabled = !status.available;
        return status;
      }

      function setupKronosModelControls() {
        const button = $("#loadKronosModelBtn");
        if (!button || button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
          button.disabled = true;
          $("#kronosModelStatus").className = "notice status info";
          $("#kronosModelStatus").textContent = "正在载入模型...";
          let loadError = null;
          try {
            const data = await fetchJson("/api/load-model", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                model_key: $("#kronosModelSelect").value,
                device: $("#kronosDeviceSelect").value,
              }),
            });
            $("#kronosModelStatus").className = "notice status success";
            $("#kronosModelStatus").textContent = data.message || "模型已载入";
          } catch (error) {
            loadError = error;
            $("#kronosModelStatus").className = "notice status error";
            $("#kronosModelStatus").textContent = error.message;
          } finally {
            try {
              const status = await loadKronosStatus();
              if (loadError) {
                $("#kronosModelStatus").className = "notice status error";
                $("#kronosModelStatus").textContent = loadError.message;
                button.disabled = !status.available;
              }
            } catch (error) {
              button.disabled = false;
            }
          }
        });
      }

      function setupSettings() {
        loadSettings().catch((error) => {
          $("#llmConfigMeta").textContent = "读取失败";
          $("#llmProviderList").innerHTML = `<div class="item"><p class="item-meta">${html(error.message)}</p></div>`;
        });
        loadKronosStatus().catch((error) => {
          $("#kronosModelMeta").textContent = "读取失败";
          $("#kronosModelStatus").textContent = error.message;
        });
        setupKronosModelControls();

        $("#llmSettingsForm").addEventListener("submit", async (event) => {
          event.preventDefault();
          const enabledModels = [...document.querySelectorAll("[data-llm-model]:checked")].map((input) => input.dataset.llmModel);
          const apiKeys = {};
          document.querySelectorAll("[data-provider-key]").forEach((input) => {
            if (input.value.trim()) apiKeys[input.dataset.providerKey] = input.value.trim();
          });
          try {
            const data = await fetchJson("/api/settings/llm", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ enabled_models: enabledModels, api_keys: apiKeys }),
            });
            $("#llmConfigMeta").textContent = "已保存";
            $("#llmProviderList").innerHTML = providerModelRows(data.settings);
          } catch (error) {
            alert(error.message);
          }
        });

        $("#tushareSettingsForm").addEventListener("submit", async (event) => {
          event.preventDefault();
          const formEl = event.currentTarget;
          const form = new FormData(formEl);
          const payload = Object.fromEntries(form.entries());
          payload.timeout = Number(payload.timeout);
          payload.retry_count = Number(payload.retry_count);
          payload.clear_token = payload.clear_token === "1";
          const hasToken = Boolean((payload.token || "").trim());
          payload.verify = hasToken;  // 填了新 Token 就联网校验,即时反馈有效性
          const check = $("#tushareTokenCheck");
          if (check && hasToken) { check.style.display = ""; check.textContent = "正在校验 Token…"; check.style.color = ""; }
          try {
            const data = await fetchJson("/api/settings/tushare", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            $("#tushareConfigMeta").textContent = data.settings.tushare?.configured ? `已保存 ${data.settings.tushare.token_masked}` : "未配置";
            const tokenInput = formEl?.elements?.token;
            if (tokenInput) tokenInput.value = "";
            if (check) {
              const tc = data.token_check;
              if (tc && tc.ok) {
                check.style.display = ""; check.style.color = "var(--ok, #2e7d32)";
                check.textContent = "✓ Token 有效,已生效。现在可到「资金榜单」点「刷新 / 补偿数据」。";
              } else if (tc) {
                check.style.display = ""; check.style.color = "var(--danger, #c62828)";
                check.textContent = `✗ Token 无效:${tc.error || "校验失败"}。资金榜单 / 龙虎榜回填会因此拿不到数据。`;
              } else {
                check.style.display = "none";
              }
            }
          } catch (error) {
            if (check) { check.style.display = ""; check.style.color = "var(--danger, #c62828)"; check.textContent = `保存失败:${error.message}`; }
            alert(error.message);
          }
        });

        const autoFollowForm = $("#autoFollowForm");
        if (autoFollowForm) autoFollowForm.addEventListener("submit", async (event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const payload = {
            enabled: form.get("enabled") === "1",
            min_score: Number(form.get("min_score")),
            per_stock_amount: Number(form.get("per_stock_amount")),
            hold_days: Number(form.get("hold_days")),
          };
          const statusEl = $("#autoFollowStatus");
          try {
            const data = await fetchJson("/api/settings/auto-follow", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            fillAutoFollowForm(data.auto_follow);
            if (statusEl) statusEl.textContent = `已保存：${data.path || ""}`;
            showToast("自动跟单配置已保存");
          } catch (error) {
            if (statusEl) statusEl.textContent = `保存失败：${error.message}`;
            alert(error.message);
          }
        });

        setupDataBackup();
      }

      function setupDataBackup() {
        const exportBtn = $("#dataExportBtn");
        const fileInput = $("#dataImportFile");
        const importBtn = $("#dataImportBtn");
        const fileLabel = $("#dataBackupFile");
        const result = $("#dataBackupResult");
        if (!exportBtn) return;

        exportBtn.addEventListener("click", () => {
          showToast("正在生成整库快照…");
          window.location.href = "/api/data/export";  // 带 Content-Disposition,浏览器直接下载
        });

        fileInput?.addEventListener("change", () => {
          const f = fileInput.files && fileInput.files[0];
          if (fileLabel) fileLabel.textContent = f ? `已选择:${f.name}(${(f.size / 1048576).toFixed(2)} MB)` : "未选择文件";
          if (importBtn) importBtn.disabled = !f;
        });

        importBtn?.addEventListener("click", async () => {
          const f = fileInput?.files && fileInput.files[0];
          if (!f) return;
          if (!confirm(`确认用「${f.name}」整库替换当前数据?\n导入前会自动备份当前库,但替换后当前数据将被覆盖。`)) return;
          importBtn.disabled = true; exportBtn.disabled = true;
          if (result) { result.hidden = false; result.className = "notice status"; result.textContent = "⏳ 正在导入(校验 → 自动备份 → 灌库 → 升级)…"; }
          try {
            const fd = new FormData();
            fd.append("file", f, f.name);
            const res = await fetch("/api/data/import", { method: "POST", body: fd });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || !data.ok) throw new Error(data.error || `HTTP ${res.status}`);
            const tables = data.tables || {};
            const topTables = Object.entries(tables).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).slice(0, 6)
              .map(([k, v]) => `${k}:${v}`).join(" · ");
            if (result) {
              result.className = "notice status success";
              result.innerHTML = `✅ 导入成功(版本 v${data.imported_version} → v${data.final_version})。`
                + `<br>已自动备份当前库:<code>${html(data.pre_import_backup || "")}</code>`
                + (topTables ? `<br>主要表行数:${html(topTables)}` : "");
            }
            showToast("整库导入成功,建议刷新页面");
          } catch (e) {
            if (result) { result.className = "notice status error"; result.textContent = "❌ 导入失败:" + e.message; }
          } finally {
            importBtn.disabled = false; exportBtn.disabled = false;
          }
        });
      }

      // ─────────────────────────────────────────────────────────────
      //  自选 + 实时热点条（底部常驻滚动条，所有交互在条上完成）
      // ─────────────────────────────────────────────────────────────
      function lsGet(key, fallback = null) {
        try { const v = localStorage.getItem(key); return v == null ? fallback : v; } catch (e) { return fallback; }
      }
      function lsSet(key, value) {
        try { localStorage.setItem(key, value); } catch (e) {}
      }

      function moneyText(value) {
        const v = Number(value);
        if (!Number.isFinite(v) || v === 0) return "";
        const sign = v > 0 ? "+" : "-";
        const abs = Math.abs(v);
        if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`;
        if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(0)}万`;
        return `${sign}${abs.toFixed(0)}`;
      }

      // ── 数据层（热点 + 自选，供热点条与自选页共用）─────────────────
      async function loadHotspots() {
        const data = await fetchJson("/api/market/hotspots");
        state.notifyData = data;
        return data;
      }
      // ── 系统事件（EOD 复盘 / 机会挖掘 / 自动跟单完成；通知条「系统」分类 + OS 级通知）──
      async function loadSystemEvents() {
        const data = await fetchJson("/api/notifications/events?limit=50");
        state.systemEvents = data.events || [];
        maybeOsNotify(data);
        return data;
      }
      function maybeOsNotify(data) {
        const lastId = Number(data.last_id || 0);
        const seenRaw = lsGet("kronos_sys_notify_last_id");
        if (seenRaw == null || seenRaw === "") {
          lsSet("kronos_sys_notify_last_id", String(lastId)); // 首次启动不回放历史事件
          return;
        }
        const seen = Number(seenRaw) || 0;
        const fresh = (data.events || []).filter((e) => Number(e.id) > seen);
        if (lastId > seen) lsSet("kronos_sys_notify_last_id", String(lastId));
        if (!fresh.length) return;
        // 仅 Tauri 环境发 OS 级通知（tauri-plugin-notification，withGlobalTauri 注入）；浏览器环境静默跳过。
        const tauriNotify = window.__TAURI__ && window.__TAURI__.notification;
        if (!tauriNotify || typeof tauriNotify.sendNotification !== "function") return;
        (async () => {
          try {
            let granted = await tauriNotify.isPermissionGranted();
            if (!granted) granted = (await tauriNotify.requestPermission()) === "granted";
            if (!granted) return;
            fresh.slice(-3).forEach((e) => {
              try { tauriNotify.sendNotification({ title: e.title || "Kronos", body: e.message || "" }); } catch (err) {}
            });
          } catch (err) { console.warn("OS 通知失败", err); }
        })();
      }
      async function loadWatchlist() {
        const data = await fetchJson("/api/watchlist");
        state.watchlist = data.items || [];
        state.watchlistSet = new Set(state.watchlist.map((w) => normalizeStockCode(w.code)));
        return data;
      }
      function applyWatchlistItems(items) {
        if (Array.isArray(items)) {
          state.watchlistSet = new Set(items.map((w) => normalizeStockCode(w.code)));
        }
        syncWatchlistStars();
        syncStockContextStar();
        if (page === "watchlist") refreshWatchlist().catch(() => {});
      }
      async function addToWatchlist(code, name = "") {
        const c = normalizeStockCode(code);
        if (!c) { showToast("无效股票代码"); return; }
        const data = await fetchJson("/api/watchlist/add", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: c, name }),
        });
        applyWatchlistItems(data.items);
        showToast(data.added === false ? "已在自选中" : `已加入自选 ${c}`);
        return data;
      }
      async function removeFromWatchlist(code) {
        const c = normalizeStockCode(code);
        const data = await fetchJson("/api/watchlist/remove", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code: c }),
        });
        applyWatchlistItems(data.items);
        showToast(`已移除自选 ${c}`);
        return data;
      }
      function syncWatchlistStars() {
        document.querySelectorAll(".notify-star[data-notify-add]").forEach((btn) => {
          const on = !!(state.watchlistSet && state.watchlistSet.has(btn.dataset.notifyAdd));
          btn.classList.toggle("on", on);
          btn.textContent = on ? "★" : "＋";
          btn.title = on ? "已在自选（点击移除）" : "加入自选";
        });
      }

      // ── 热点条渲染 ────────────────────────────────────────────────
      const NOTIFY_CAT_LABEL = { hot: "热点", changes: "异动", watchlist: "自选", boards: "板块", flash: "快讯", system: "系统" };
      function notifyItems() {
        const cats = state.notifyCats || new Set();
        const intel = state.notifyData || {};
        const em = intel.eastmoney || {};
        const out = [];
        if (cats.has("hot")) {
          (em.hot_stocks || []).slice(0, 12).forEach((s) => out.push({
            kind: "stock", cat: "hot", code: s.code, name: s.name,
            pct: s.change_pct, price: s.price, inflowText: s.main_net_inflow_text,
          }));
        }
        if (cats.has("changes")) {
          (em.changes || []).slice(0, 15).forEach((s) => out.push({
            kind: "stock", cat: "changes", code: s.code, name: s.name,
            pct: s.change_pct, price: s.price, changeType: s.type, time: s.time,
          }));
        }
        if (cats.has("watchlist")) {
          (state.watchlist || []).slice(0, 30).forEach((w) => out.push({
            kind: "stock", cat: "watchlist", code: w.code, name: w.name,
            pct: w.change_pct, price: w.price, inflow: w.main_net_inflow,
          }));
        }
        if (cats.has("boards")) {
          [...(em.concept_boards || []), ...(em.industry_boards || [])].slice(0, 12).forEach((b) => out.push({
            kind: "board", cat: "boards", name: b.name, pct: b.change_pct, inflowText: b.main_net_inflow_text,
          }));
        }
        if (cats.has("flash")) {
          (intel.jinshi || []).slice(0, 10).forEach((n) => out.push({
            kind: "flash", cat: "flash", title: n.title, important: n.important, source: n.source, time: n.time,
          }));
        }
        if (cats.has("system")) {
          (state.systemEvents || []).slice(-10).reverse().forEach((e) => out.push({
            kind: "flash", cat: "system",
            title: `${e.title || ""}${e.message ? "：" + e.message : ""}`,
            important: e.level === "warn", source: "系统", time: e.created_at,
          }));
        }
        return out;
      }
      function notifyItemHtml(it, idx) {
        const chip = `<span class="notify-cat-chip cat-${it.cat}">${NOTIFY_CAT_LABEL[it.cat] || ""}</span>`;
        if (it.kind === "flash") {
          return `<div class="notify-item notify-flash${it.important ? " is-important" : ""}" data-notify-idx="${idx}" tabindex="0">
            ${chip}<span class="notify-flash-title">${html((it.title || "").slice(0, 46))}</span>
          </div>`;
        }
        const pct = Number(it.pct || 0);
        const cls = changeClass(pct);
        const pctText = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
        if (it.kind === "board") {
          return `<div class="notify-item notify-board" data-notify-idx="${idx}" tabindex="0">
            ${chip}<span class="notify-name">${html(it.name)}</span><span class="notify-pct ${cls}">${pctText}</span>
          </div>`;
        }
        const code = normalizeStockCode(it.code);
        const on = !!(state.watchlistSet && state.watchlistSet.has(code));
        const tag = it.changeType ? `<span class="notify-change-tag">${html(it.changeType)}${it.time ? " " + html(it.time) : ""}</span>` : "";
        return `<div class="notify-item notify-stock item-clickable" data-notify-idx="${idx}" data-stock-code="${html(it.code || "")}" data-stock-name="${html(it.name || "")}" role="button" tabindex="0" title="点击查看个股分析">
          ${chip}<span class="notify-name">${html(it.name || it.code)}</span>${tag}<span class="notify-pct ${cls}">${pctText}</span>
          <button class="notify-star ${on ? "on" : ""}" type="button" data-notify-add="${html(code)}" data-notify-name="${html(it.name || "")}" title="${on ? "已在自选（点击移除）" : "加入自选"}" tabindex="-1">${on ? "★" : "＋"}</button>
        </div>`;
      }
      function renderNotifyBar() {
        const bar = $("#notifyBar");
        const track = $("#notifyTrack");
        if (!bar || !track) return;
        updateNotifyCatChips();
        const updated = $("#notifyUpdated");
        if (updated) updated.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        const items = notifyItems();
        state._notifyItems = items;
        if (!items.length) {
          track.style.animationName = "none";
          track.innerHTML = `<div class="notify-item notify-empty">实时热点加载中…（无数据时请检查网络或稍后刷新）</div>`;
          return;
        }
        const single = items.map((it, i) => notifyItemHtml(it, i)).join("");
        track.innerHTML = single + single; // 复制一份实现无缝循环
        const dur = Math.min(240, Math.max(30, items.length * 3.5));
        track.style.setProperty("--notify-dur", `${dur.toFixed(0)}s`);
        // 重启动画（避免内容变化后位置错位）：先关掉再回退到样式表里的 .notify-track 动画
        track.style.animationName = "none";
        void track.offsetWidth;
        track.style.animationName = "";
        bindNotifyItems(track);
      }
      function bindNotifyItems(track) {
        track.querySelectorAll(".notify-item[data-stock-code]").forEach((el) => {
          el.addEventListener("click", (e) => {
            if (e.target.closest(".notify-star")) return;
            const code = el.dataset.stockCode;
            if (!code) return;
            openStockContext({ type: "stock", stock_code: code, stock_name: el.dataset.stockName || "", board_name: "" })
              .catch((err) => console.warn("打开个股失败", err));
          });
        });
        track.querySelectorAll(".notify-star").forEach((btn) => {
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const code = btn.dataset.notifyAdd;
            const name = btn.dataset.notifyName || "";
            const fn = (state.watchlistSet && state.watchlistSet.has(code)) ? removeFromWatchlist(code) : addToWatchlist(code, name);
            Promise.resolve(fn).catch((err) => showToast(err.message));
          });
        });
        track.querySelectorAll(".notify-item").forEach((el) => {
          el.addEventListener("mouseenter", () => notifyShowDetail(el));
          el.addEventListener("mouseleave", notifyHideDetail);
          el.addEventListener("focus", () => notifyShowDetail(el));
          el.addEventListener("blur", notifyHideDetail);
        });
      }
      function notifyEnsureCard() {
        let card = $("#notifyDetailCard");
        if (!card) {
          card = document.createElement("div");
          card.id = "notifyDetailCard";
          card.className = "notify-detail-card";
          card.hidden = true;
          document.body.appendChild(card);
        }
        return card;
      }
      function notifyDetailHtml(it) {
        if (it.kind === "flash") {
          const head = it.cat === "system" ? "系统通知" : "金十快讯";
          return `<div class="ndc-head">${head}${it.important ? " · <span class=\"ndc-warn\">重要</span>" : ""}</div>
            <div class="ndc-title">${html(it.title || "")}</div>
            <div class="ndc-meta">${html(it.source || "金十")} · ${html(it.time || "")}</div>`;
        }
        const pct = Number(it.pct || 0);
        const cls = changeClass(pct);
        const pctText = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
        const inflow = it.inflowText || moneyText(it.inflow);
        if (it.kind === "board") {
          return `<div class="ndc-head">热门板块</div>
            <div class="ndc-title">${html(it.name)} <span class="${cls}">${pctText}</span></div>
            ${inflow ? `<div class="ndc-meta">主力净流入 ${html(inflow)}</div>` : ""}`;
        }
        const code = normalizeStockCode(it.code);
        const member = !!(state.watchlistSet && state.watchlistSet.has(code));
        let head = "个股";
        if (it.cat === "watchlist") head = "自选股";
        else if (it.cat === "hot") head = "实时热点";
        else if (it.cat === "changes") head = "实时异动" + (it.changeType ? " · " + it.changeType : "");
        return `<div class="ndc-head">${html(head)}</div>
          <div class="ndc-title">${html(it.name || it.code)} <span class="muted">${html(it.code || "")}</span></div>
          <div class="ndc-row"><span class="${cls}">${pctText}</span>${it.price != null ? ` · 现价 ¥${num(it.price)}` : ""}${it.cat === "changes" && it.time ? ` · ${html(it.time)}` : ""}</div>
          ${inflow ? `<div class="ndc-meta">主力净流入 ${html(inflow)}</div>` : ""}
          <div class="ndc-foot">点击查看完整分析 · ${member ? "★ 已自选" : "＋ 可加自选"}</div>`;
      }
      function notifyShowDetail(el) {
        const it = (state._notifyItems || [])[Number(el.dataset.notifyIdx)];
        if (!it) return;
        const card = notifyEnsureCard();
        card.innerHTML = notifyDetailHtml(it);
        card.hidden = false;
        const r = el.getBoundingClientRect();
        const left = Math.max(8, Math.min(window.innerWidth - card.offsetWidth - 8, r.left));
        card.style.left = `${left}px`;
        card.style.top = `${Math.max(8, r.top - card.offsetHeight - 10)}px`;
      }
      function notifyHideDetail() {
        const card = $("#notifyDetailCard");
        if (card) card.hidden = true;
      }
      function updateNotifyCatChips() {
        document.querySelectorAll(".notify-cat[data-notify-cat]").forEach((btn) => {
          btn.classList.toggle("active", !!(state.notifyCats && state.notifyCats.has(btn.dataset.notifyCat)));
        });
      }
      function setNotifyHidden(hidden) {
        const bar = $("#notifyBar");
        const reopen = $("#notifyReopenBtn");
        if (bar) bar.hidden = hidden;
        if (reopen) reopen.hidden = !hidden;
        document.body.classList.toggle("notify-hidden", hidden);
        lsSet("kronos_notify_hidden", hidden ? "1" : "0");
      }
      function bindNotifyControls() {
        document.querySelectorAll(".notify-cat[data-notify-cat]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const cat = btn.dataset.notifyCat;
            if (!state.notifyCats) return;
            if (state.notifyCats.has(cat)) {
              if (state.notifyCats.size > 1) state.notifyCats.delete(cat); // 至少保留一个分类
            } else {
              state.notifyCats.add(cat);
            }
            lsSet("kronos_notify_cats2", [...state.notifyCats].join(","));
            renderNotifyBar();
          });
        });
        const pauseBtn = $("#notifyPauseBtn");
        if (pauseBtn) pauseBtn.addEventListener("click", () => {
          const bar = $("#notifyBar");
          const paused = bar.classList.toggle("paused");
          pauseBtn.textContent = paused ? "▶" : "⏸";
          pauseBtn.title = paused ? "继续滚动" : "暂停滚动";
        });
        const hideBtn = $("#notifyHideBtn");
        if (hideBtn) hideBtn.addEventListener("click", () => setNotifyHidden(true));
        const reopen = $("#notifyReopenBtn");
        if (reopen) reopen.addEventListener("click", () => setNotifyHidden(false));
      }
      async function refreshNotifyData() {
        await Promise.all([
          loadHotspots().catch((e) => console.warn("热点读取失败", e)),
          loadWatchlist().catch((e) => console.warn("自选读取失败", e)),
          loadSystemEvents().catch((e) => console.warn("系统事件读取失败", e)),
        ]);
        renderNotifyBar();
      }
      async function startNotifyBar() {
        const bar = $("#notifyBar");
        if (!bar) return;
        const savedCats = (lsGet("kronos_notify_cats2") || "").split(",").map((s) => s.trim()).filter(Boolean);
        const valid = savedCats.filter((c) => NOTIFY_CAT_LABEL[c]);
        state.notifyCats = new Set(valid.length ? valid : ["hot", "changes", "watchlist", "system"]);
        bindNotifyControls();
        if (lsGet("kronos_notify_hidden") === "1") setNotifyHidden(true);
        await refreshNotifyData();
        if (state.notifyTimer) clearInterval(state.notifyTimer);
        state.notifyTimer = setInterval(() => { refreshNotifyData().catch(() => {}); }, 60000);
      }

      // ── 自选页 ────────────────────────────────────────────────────
      function watchlistRowHtml(w) {
        const pct = Number(w.change_pct);
        const hasPct = Number.isFinite(pct);
        const cls = hasPct ? changeClass(pct) : "";
        const inflow = moneyText(w.main_net_inflow);
        return `<div class="item watchlist-row" data-wl-code="${html(w.code)}">
          <div class="watchlist-row-main">
            <p class="item-title">${html(w.name || w.code)} <span class="muted">${html(w.code)}</span></p>
            <p class="item-meta">${w.price != null ? `现价 ¥${num(w.price)}` : "行情暂不可用"}${inflow ? ` · 主力 ${html(inflow)}` : ""}</p>
          </div>
          <strong class="watchlist-pct ${cls}">${hasPct ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%` : "--"}</strong>
          <div class="watchlist-row-actions">
            <button class="button compact" type="button" data-wl-open="${html(w.code)}" data-wl-name="${html(w.name || "")}">分析</button>
            <button class="button secondary compact" type="button" data-wl-del="${html(w.code)}">移除</button>
          </div>
        </div>`;
      }
      function renderWatchlistPage() {
        const list = $("#watchlistTable");
        if (!list) return;
        const items = state.watchlist || [];
        const meta = $("#watchlistMeta");
        if (meta) meta.textContent = `${items.length} 只 · 更新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
        if (!items.length) {
          empty(list, "暂无自选股。在上方输入代码/名称添加，或在底部热点条、个股分析弹窗中点 ★ 加入。");
          return;
        }
        list.innerHTML = items.map(watchlistRowHtml).join("");
        list.querySelectorAll("[data-wl-open]").forEach((el) => el.addEventListener("click", () =>
          openStockContext({ type: "stock", stock_code: el.dataset.wlOpen, stock_name: el.dataset.wlName || "", board_name: "" }).catch(() => {})));
        list.querySelectorAll("[data-wl-del]").forEach((el) => el.addEventListener("click", () =>
          removeFromWatchlist(el.dataset.wlDel).catch((err) => alert(err.message))));
      }
      async function refreshWatchlist() {
        await loadWatchlist();
        renderWatchlistPage();
      }
      function setupWatchlistPage() {
        const input = $("#watchlistAddInput");
        const addBtn = $("#watchlistAddBtn");
        const refreshBtn = $("#watchlistRefreshBtn");
        const suggest = $("#watchlistAddSuggest");
        if (refreshBtn) refreshBtn.addEventListener("click", () => refreshWatchlist().catch((e) => alert(e.message)));
        const doSearch = async () => {
          const q = (input?.value || "").trim();
          if (!q) { if (suggest) suggest.innerHTML = ""; return; }
          try {
            const data = await fetchJson(`/api/pattern-search/stocks?q=${encodeURIComponent(q)}&limit=8`);
            const stocks = data.stocks || [];
            if (!suggest) return;
            suggest.innerHTML = stocks.map((it) => `
              <button class="item" type="button" data-add-code="${html(it.stock_code)}" data-add-name="${html(it.stock_name || "")}">
                <div class="item-top"><p class="item-title">${html(it.stock_name || it.stock_code)}</p><span class="pill">${html(it.stock_code)}</span></div>
                <p class="item-meta">${html(it.market || "--")} · ${html(it.industry || "--")}</p>
              </button>`).join("");
            if (!stocks.length) empty(suggest, "没有匹配股票，可直接输入 6 位代码添加。");
            suggest.querySelectorAll("[data-add-code]").forEach((el) => el.addEventListener("click", async () => {
              try { await addToWatchlist(el.dataset.addCode, el.dataset.addName); input.value = ""; suggest.innerHTML = ""; }
              catch (err) { alert(err.message); }
            }));
          } catch (e) { if (suggest) empty(suggest, e.message); }
        };
        if (addBtn) addBtn.addEventListener("click", async () => {
          const q = (input?.value || "").trim();
          const code = normalizeStockCode(q);
          if (code) {
            try { await addToWatchlist(code, ""); input.value = ""; if (suggest) suggest.innerHTML = ""; }
            catch (err) { alert(err.message); }
          } else { doSearch(); }
        });
        if (input) input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addBtn?.click(); } });
        refreshWatchlist().catch(() => {});
      }

      // ── 个股弹窗内的 ★ 自选开关 ──────────────────────────────────
      function ensureStockContextStar() {
        let btn = $("#stockContextStar");
        if (btn) return btn;
        const titleEl = $("#stockContextTitle");
        if (!titleEl) return null;
        btn = document.createElement("button");
        btn.id = "stockContextStar";
        btn.type = "button";
        btn.className = "stock-context-star";
        // 标题与星标同处一行（flex row），避免星标掉到标题下方单独占一行。
        const row = titleEl.closest(".stock-context-title-row") || titleEl.parentElement;
        row.appendChild(btn);
        btn.addEventListener("click", () => {
          const code = state.currentStockCode;
          if (!code) return;
          const name = ($("#stockContextTitle")?.textContent || "").trim();
          const fn = (state.watchlistSet && state.watchlistSet.has(normalizeStockCode(code)))
            ? removeFromWatchlist(code) : addToWatchlist(code, name);
          Promise.resolve(fn).catch((e) => showToast(e.message));
        });
        if (!state.watchlistSet) loadWatchlist().then(syncStockContextStar).catch(() => {});
        return btn;
      }
      function syncStockContextStar() {
        const btn = $("#stockContextStar");
        if (!btn) return;
        const code = normalizeStockCode(state.currentStockCode || "");
        const on = !!(code && state.watchlistSet && state.watchlistSet.has(code));
        btn.classList.toggle("on", on);
        btn.textContent = on ? "★ 已自选" : "☆ 加自选";
      }

      // ── 资金榜单（主力买入榜 / 龙虎榜）────────────────────────────
      function capitalParams() {
        const cap = state.capital;
        const selectedMode = $("#capitalMode")?.value || "single";
        const date = ($("#capitalDate")?.value || "").trim();
        const startDate = ($("#capitalStartDate")?.value || "").trim();
        const endDate = ($("#capitalEndDate")?.value || "").trim();
        const days = $("#capitalDays")?.value || 5;
        const top = $("#capitalTopN")?.value || 50;
        const hasRange = Boolean(startDate || endDate);
        if (hasRange && !(startDate && endDate)) {
          throw new Error("区间搜索需要同时填写开始日期和结束日期");
        }
        if (startDate && endDate && startDate > endDate) {
          throw new Error("区间开始日期不能晚于结束日期");
        }
        const mode = startDate && endDate ? "aggregate" : selectedMode;
        const qs = new URLSearchParams({ mode, top: String(top) });
        if (mode === "aggregate") qs.set("days", String(days));
        if (startDate && endDate) {
          qs.set("start_date", startDate);
          qs.set("end_date", endDate);
        }
        if (date) qs.set("date", date);
        cap.mode = mode;
        cap.range = startDate && endDate ? { start: startDate, end: endDate } : null;
        return qs.toString();
      }

      async function loadCapitalRankings() {
        const cap = state.capital;
        const table = $("#capitalTable");
        if (table) empty(table, "加载中…");
        const ep = cap.tab === "moneyflow" ? "moneyflow" : "dragon-tiger";
        try {
          const data = await fetchJson(`/api/capital-rankings/${ep}?${capitalParams()}`);
          cap.data = data;
          cap.rows = data.rows || [];
          cap.selected.clear();
          cap.expandedKey = null;
          renderCapitalRankings();
        } catch (e) {
          cap.data = null;
          cap.rows = [];
          cap.selected.clear();
          cap.expandedKey = null;
          if (table) empty(table, `加载失败: ${e.message}`);
          renderCapitalWindow(5);
          renderCapitalWindow(30);
          updateCapitalAnalyzeBtn();
        }
      }

      const CAPITAL_COLUMN_LABELS = {
        select: "",
        rank: "#",
        stock: "股票",
        trade_date: "日期",
        ts_code: "代码",
        name: "名称",
        last_price: "最新价",
        change_pct: "涨跌幅",
        close: "收盘价",
        pct_change: "当日涨跌幅",
        net_amount: "净买入额",
        net_amount_rate: "净占比",
        main_buy_amount: "主力买入额",
        retail_buy_amount: "散户侧买入额",
        buy_elg_amount: "超大单",
        buy_elg_amount_rate: "超大单占比",
        buy_lg_amount: "大单",
        buy_lg_amount_rate: "大单占比",
        buy_md_amount: "中单",
        buy_md_amount_rate: "中单占比",
        buy_sm_amount: "小单",
        buy_sm_amount_rate: "小单占比",
        amount_unit: "金额单位",
        l_buy: "龙虎榜买入",
        l_sell: "龙虎榜卖出",
        l_amount: "龙虎榜成交",
        amount: "成交额",
        turnover_rate: "换手率",
        net_rate: "净买占比",
        amount_rate: "成交占比",
        institution_buy_amount: "机构日买入量",
        institution_sell_amount: "机构卖出量",
        institution_net_amount: "机构净买入额",
        institution_amount: "机构总量",
        institution_count: "机构数",
        inst_name: "主力机构名称",
        side: "方向",
        buy_amount: "机构日买入量",
        sell_amount: "机构卖出量",
        is_quant: "量化标记",
        quant_confidence: "量化置信度",
        buy_institution_count: "买入机构数",
        reason_count: "原因数",
        reason: "上榜原因",
        list_count: "上榜天数",
        first_date: "起始日",
        last_date: "结束日",
        float_values: "流通市值",
        actions: "操作",
      };
      const CAPITAL_MONEY_KEYS = new Set([
        "net_amount", "main_buy_amount", "retail_buy_amount",
        "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
        "l_buy", "l_sell", "l_amount", "amount",
        "institution_buy_amount", "institution_sell_amount", "institution_net_amount", "institution_amount",
        "buy_amount", "sell_amount", "float_values",
      ]);
      const CAPITAL_MONEYFLOW_AMOUNT_KEYS = new Set([
        "net_amount", "main_buy_amount", "retail_buy_amount",
        "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount",
      ]);
      const CAPITAL_RATE_KEYS = new Set([
        "net_amount_rate", "buy_elg_amount_rate", "buy_lg_amount_rate",
        "buy_md_amount_rate", "buy_sm_amount_rate", "pct_change", "change_pct",
        "turnover_rate", "net_rate", "amount_rate",
      ]);
      const CAPITAL_INTERNAL_KEYS = new Set(["raw", "raw_json", "code", "quoted", "live_main_net_inflow", "detail_rows", "institution_rows", "institution_daily_rows"]);

      function capitalMoney(value) {
        const v = Number(value);
        if (!Number.isFinite(v)) return "--";
        if (v === 0) return "0";
        return moneyText(v) || "0";
      }

      function capitalAmountFactor(unit) {
        const text = String(unit || "").trim().toLowerCase();
        if (!text) return 1;
        if (text.includes("万元") || text === "万" || text.includes("10k")) return 10000;
        if (text.includes("亿元") || text === "亿") return 100000000;
        return 1;
      }

      function capitalAmountUnit(row, record) {
        return (record && (record.amount_unit || record._amount_unit)) || row.amount_unit || row.raw?.amount_unit || "";
      }

      function capitalDisplayAmount(row, key, value, record) {
        const isMoneyflowAmount = state.capital.tab === "moneyflow" && CAPITAL_MONEYFLOW_AMOUNT_KEYS.has(key);
        const factor = isMoneyflowAmount ? capitalAmountFactor(capitalAmountUnit(row, record) || "万元") : 1;
        return capitalMoney(Number(value) * factor);
      }

      function capitalColumns(rows, compact = false) {
        const cap = state.capital;
        const isMf = cap.tab === "moneyflow";
        const base = compact
          ? (isMf
              ? ["rank", "stock", "main_buy_amount", "institution_buy_amount", "institution_amount", "net_amount", "retail_buy_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount", "list_count", "first_date", "last_date"]
              : ["rank", "stock", "l_buy", "institution_buy_amount", "institution_amount", "l_sell", "net_amount", "l_amount", "amount", "reason_count", "list_count", "first_date", "last_date"])
          : (isMf
              ? ["select", "rank", "stock", "trade_date", "last_price", "change_pct", "main_buy_amount", "institution_buy_amount", "institution_amount", "net_amount", "retail_buy_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount", "net_amount_rate", "buy_elg_amount_rate", "buy_lg_amount_rate", "buy_md_amount_rate", "buy_sm_amount_rate", "amount_unit", "list_count", "first_date", "last_date", "actions"]
              : ["select", "rank", "stock", "trade_date", "last_price", "change_pct", "l_buy", "institution_buy_amount", "institution_amount", "l_sell", "net_amount", "l_amount", "amount", "turnover_rate", "net_rate", "amount_rate", "reason_count", "reason", "list_count", "first_date", "last_date", "actions"]);
        const seen = new Set(base);
        const extras = [];
        (rows || []).forEach((row) => {
          Object.keys(row.raw || {}).forEach((key) => {
            if (seen.has(key) || CAPITAL_INTERNAL_KEYS.has(key)) return;
            const value = row.raw[key];
            if (value == null || value === "") return;
            seen.add(key);
            extras.push(key);
          });
        });
        if (!extras.length) return base;
        const actionIndex = base.indexOf("actions");
        if (actionIndex < 0) return base.concat(extras);
        return base.slice(0, actionIndex).concat(extras, base.slice(actionIndex));
      }

      function capitalCellHtml(row, key) {
        if (key === "select") {
          return `<input type="checkbox" data-cap-pick="${html(row.code)}" ${state.capital.selected.has(row.code) ? "checked" : ""} />`;
        }
        if (key === "rank") return html(row.rank);
        if (key === "stock") {
          return `<div class="capital-stock-cell" ${klineTargetAttr(row.code, row.name)}>
            <strong>${html(row.name || row.code || "--")}</strong>
            <span>${html(row.ts_code || row.code || "")}</span>
          </div>`;
        }
        if (key === "last_price") {
          const live = row.quoted && row.last_price != null;
          if (live) return `¥${num(row.last_price)} <span class="muted">实时</span>`;
          return row.close != null ? `¥${num(row.close)}` : "--";
        }
        if (key === "change_pct") {
          const pct = row.quoted && row.change_pct != null ? row.change_pct : row.pct_change;
          const n = Number(pct);
          if (!Number.isFinite(n)) return "--";
          return `<strong class="${changeClass(n)}">${n >= 0 ? "+" : ""}${n.toFixed(2)}%</strong>`;
        }
        if (key === "actions") {
          return `<div class="capital-cell-actions">
            <button class="button secondary compact" type="button" data-cap-detail="${html(capitalRowKey(row))}">明细</button>
            <button class="button compact" type="button" data-cap-analyze="${html(row.code)}">分析</button>
            <button class="button secondary compact" type="button" data-cap-watch="${html(row.code)}" data-cap-name="${html(row.name || "")}">加自选</button>
          </div>`;
        }
        const value = Object.prototype.hasOwnProperty.call(row, key) ? row[key] : (row.raw || {})[key];
        if (value == null || value === "") return "--";
        if (CAPITAL_MONEY_KEYS.has(key)) return html(capitalDisplayAmount(row, key, value));
        if (CAPITAL_RATE_KEYS.has(key)) {
          const n = Number(value);
          return Number.isFinite(n) ? `${n.toFixed(2)}%` : html(value);
        }
        if (typeof value === "number") return html(Number.isInteger(value) ? value : Number(value).toFixed(2));
        return html(value);
      }

      const CAPITAL_NO_SORT_KEYS = new Set(["select", "actions"]);

      // 取出某列用于排序的原始值,与 capitalCellHtml 的取值口径保持一致(否则排序结果和看到的对不上)
      function capitalSortValue(row, key) {
        if (key === "rank") return row.rank;
        if (key === "stock") return row.name || row.code || "";
        if (key === "last_price") return (row.quoted && row.last_price != null) ? row.last_price : row.close;
        if (key === "change_pct") return (row.quoted && row.change_pct != null) ? row.change_pct : row.pct_change;
        const value = Object.prototype.hasOwnProperty.call(row, key) ? row[key] : (row.raw || {})[key];
        if (CAPITAL_MONEY_KEYS.has(key)) {
          const factor = state.capital.tab === "moneyflow" && CAPITAL_MONEYFLOW_AMOUNT_KEYS.has(key)
            ? capitalAmountFactor(capitalAmountUnit(row) || "万元")
            : 1;
          return Number(value) * factor;
        }
        return value;
      }

      function capitalCellEmpty(v) {
        return v == null || v === "" || (typeof v === "number" && !Number.isFinite(v));
      }

      function sortedCapitalRows(rows, key, dir) {
        const factor = dir === "asc" ? 1 : -1;
        const decorated = rows.map((row, i) => {
          const raw = capitalSortValue(row, key);
          const n = Number(raw);
          return { row, i, raw, isNum: !capitalCellEmpty(raw) && Number.isFinite(n), n, empty: capitalCellEmpty(raw) };
        });
        decorated.sort((a, b) => {
          if (a.empty && b.empty) return a.i - b.i;
          if (a.empty) return 1;   // 缺失值永远沉底,与排序方向无关
          if (b.empty) return -1;
          let cmp;
          if (a.isNum && b.isNum) cmp = a.n - b.n;
          else cmp = String(a.raw).localeCompare(String(b.raw), "zh-Hans-CN", { numeric: true });
          if (cmp !== 0) return cmp * factor;
          return a.i - b.i;        // 同值保持稳定(原榜单顺序)
        });
        return decorated.map((d) => d.row);
      }

      function capitalRowKey(row) {
        const cap = state.capital || {};
        return [
          cap.tab || "",
          row.ts_code || row.code || "",
          row.trade_date || "",
          row.first_date || "",
          row.last_date || "",
          row.reason || "",
        ].join("|");
      }

      function capitalDisplayValue(row, key, value, record) {
        if (value == null || value === "") return "--";
        if (CAPITAL_MONEY_KEYS.has(key)) return capitalDisplayAmount(row, key, value, record);
        if (CAPITAL_RATE_KEYS.has(key)) {
          const n = Number(value);
          return Number.isFinite(n) ? `${n.toFixed(2)}%` : String(value);
        }
        if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
        return String(value);
      }

      function capitalDetailPairs(row) {
        const isMf = state.capital.tab === "moneyflow";
        const keys = isMf
          ? ["trade_date", "first_date", "last_date", "list_count", "last_price", "change_pct", "close", "pct_change", "main_buy_amount", "institution_buy_amount", "institution_amount", "institution_net_amount", "institution_count", "net_amount", "retail_buy_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount", "net_amount_rate", "amount_unit"]
          : ["trade_date", "first_date", "last_date", "list_count", "reason_count", "last_price", "change_pct", "close", "pct_change", "l_buy", "institution_buy_amount", "institution_sell_amount", "institution_net_amount", "institution_amount", "institution_count", "l_sell", "net_amount", "l_amount", "amount", "turnover_rate", "net_rate", "amount_rate"];
        return keys
          .map((key) => ({ key, label: CAPITAL_COLUMN_LABELS[key] || key, value: Object.prototype.hasOwnProperty.call(row, key) ? row[key] : (row.raw || {})[key] }))
          .filter((item) => item.value != null && item.value !== "");
      }

      function capitalDetailColumns(detailRows) {
        const isMf = state.capital.tab === "moneyflow";
        const preferred = isMf
          ? ["trade_date", "ts_code", "name", "close", "pct_change", "net_amount", "buy_elg_amount", "buy_lg_amount", "buy_md_amount", "buy_sm_amount", "net_amount_rate", "amount_unit", "_amount_unit", "top_n"]
          : ["trade_date", "ts_code", "name", "close", "pct_change", "l_buy", "l_sell", "l_amount", "net_amount", "turnover_rate", "net_rate", "amount_rate", "reason"];
        const seen = new Set();
        const cols = [];
        const hasAnyValue = (key) => detailRows.some((r) => {
          const value = r ? r[key] : null;
          return value != null && value !== "";
        });
        const add = (key) => {
          if (!key || seen.has(key) || CAPITAL_INTERNAL_KEYS.has(key) || key === "raw_json") return;
          seen.add(key);
          cols.push(key);
        };
        preferred.forEach((key) => { if (hasAnyValue(key)) add(key); });
        detailRows.forEach((record) => Object.keys(record || {}).forEach((key) => {
          if (hasAnyValue(key)) add(key);
        }));
        return cols;
      }

      function capitalInstitutionDisplayValue(key, value) {
        if (value == null || value === "") return "--";
        if (key === "side") {
          const text = String(value);
          if (text === "buy") return "买入";
          if (text === "sell") return "卖出";
          return text || "--";
        }
        if (key === "is_quant") return Number(value) === 1 ? "量化" : "--";
        if (key === "quant_confidence") {
          const n = Number(value);
          if (!Number.isFinite(n)) return String(value);
          return n <= 1 ? `${(n * 100).toFixed(0)}%` : `${n.toFixed(0)}%`;
        }
        if (["buy_amount", "sell_amount", "net_amount", "institution_buy_amount", "institution_sell_amount", "institution_net_amount", "institution_amount"].includes(key)) return capitalMoney(value);
        if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
        return String(value);
      }

      function capitalInstitutionDailyTable(row) {
        const dailyRows = Array.isArray(row.institution_daily_rows) ? row.institution_daily_rows : [];
        const cols = ["trade_date", "buy_institution_count", "institution_count", "institution_buy_amount", "institution_sell_amount", "institution_net_amount", "institution_amount"];
        if (!dailyRows.length) return "";
        return `<div class="capital-detail-section">
          <div class="capital-detail-section-title">机构按日汇总</div>
          <div class="capital-detail-raw-wrap">
            <table class="capital-detail-table capital-institution-summary-table">
              <thead><tr>${cols.map((key) => `<th>${html(CAPITAL_COLUMN_LABELS[key] || key)}</th>`).join("")}</tr></thead>
              <tbody>${dailyRows.map((record) => `<tr>${cols.map((key) => `<td>${html(capitalInstitutionDisplayValue(key, record ? record[key] : null))}</td>`).join("")}</tr>`).join("")}</tbody>
              <tfoot><tr>
                <td colspan="3">区间合计</td>
                <td>${html(capitalMoney(row.institution_buy_amount))}</td>
                <td>${html(capitalMoney(row.institution_sell_amount))}</td>
                <td>${html(capitalMoney(row.institution_net_amount))}</td>
                <td>${html(capitalMoney(row.institution_amount))}</td>
              </tr></tfoot>
            </table>
          </div>
        </div>`;
      }

      function capitalInstitutionTable(row) {
        const institutionRows = Array.isArray(row.institution_rows) ? row.institution_rows : [];
        const cols = ["trade_date", "inst_name", "side", "buy_amount", "sell_amount", "net_amount", "reason", "is_quant", "quant_confidence"];
        if (!institutionRows.length) {
          return `<div class="capital-detail-section">
            <div class="capital-detail-section-title">机构买入明细</div>
            <p class="capital-detail-empty">暂无机构席位明细</p>
          </div>`;
        }
        return `<div class="capital-detail-section">
          <div class="capital-detail-section-title">机构买入明细（逐日逐机构，${html(institutionRows.length)} 条）</div>
          <div class="capital-detail-raw-wrap">
            <table class="capital-detail-table capital-institution-table">
              <thead><tr>${cols.map((key) => `<th>${html(CAPITAL_COLUMN_LABELS[key] || key)}</th>`).join("")}</tr></thead>
              <tbody>${institutionRows.map((record) => `<tr>${cols.map((key) => `<td>${html(capitalInstitutionDisplayValue(key, record ? record[key] : null))}</td>`).join("")}</tr>`).join("")}</tbody>
              <tfoot><tr>
                <td colspan="3">区间合计</td>
                <td>${html(capitalMoney(row.institution_buy_amount))}</td>
                <td>${html(capitalMoney(row.institution_sell_amount))}</td>
                <td>${html(capitalMoney(row.institution_net_amount))}</td>
                <td></td>
                <td></td>
                <td></td>
              </tr></tfoot>
            </table>
          </div>
        </div>`;
      }

      function capitalDetailHtml(row, colspan) {
        const pairs = capitalDetailPairs(row);
        const detailRows = Array.isArray(row.detail_rows) ? row.detail_rows : [];
        const detailCols = capitalDetailColumns(detailRows);
        const institutionRows = Array.isArray(row.institution_rows) ? row.institution_rows : [];
        const title = `${row.name || row.code || "--"} ${row.ts_code || row.code || ""}`;
        const reason = row.reason
          ? `<div class="capital-detail-reason"><span>${html(CAPITAL_COLUMN_LABELS.reason)}</span><strong>${html(row.reason)}</strong></div>`
          : "";
        const metrics = pairs.map((item) => `
          <div class="capital-detail-metric">
            <span>${html(item.label)}</span>
            <strong>${html(capitalDisplayValue(row, item.key, item.value))}</strong>
          </div>`).join("");
        const rawTable = detailRows.length && detailCols.length
          ? `<div class="capital-detail-raw-wrap">
              <table class="capital-detail-table">
                <thead><tr>${detailCols.map((key) => `<th>${html(CAPITAL_COLUMN_LABELS[key] || key)}</th>`).join("")}</tr></thead>
                <tbody>${detailRows.map((record) => `<tr>${detailCols.map((key) => `<td>${html(capitalDisplayValue(row, key, record ? record[key] : null, record))}</td>`).join("")}</tr>`).join("")}</tbody>
              </table>
            </div>`
          : `<p class="capital-detail-empty">暂无原始记录</p>`;
        const originalSection = `<div class="capital-detail-section">
          <div class="capital-detail-section-title">榜单原始记录</div>
          ${rawTable}
        </div>`;
        return `<tr class="capital-detail-row">
          <td colspan="${html(colspan)}">
            <div class="capital-detail-panel">
              <div class="capital-detail-head">
                <strong>${html(title)}</strong>
                <span>${html(`${institutionRows.length} 条机构明细 · ${detailRows.length} 条原始记录`)}</span>
              </div>
              ${metrics ? `<div class="capital-detail-metrics">${metrics}</div>` : ""}
              ${reason}
              ${capitalInstitutionDailyTable(row)}
              ${capitalInstitutionTable(row)}
              ${originalSection}
            </div>
          </td>
        </tr>`;
      }

      function capitalTableHtml(rows, compact = false) {
        const cols = capitalColumns(rows, compact);
        const sortable = !compact;                       // 仅主榜单可排序,聚合小窗保持服务端顺序
        const sort = (sortable && state.capital.sort) || {};
        let viewRows = rows;
        if (sort.key && cols.includes(sort.key)) {
          viewRows = sortedCapitalRows(rows, sort.key, sort.dir);
        }
        const th = cols.map((key) => {
          const label = html(CAPITAL_COLUMN_LABELS[key] != null ? CAPITAL_COLUMN_LABELS[key] : key);
          if (!sortable || CAPITAL_NO_SORT_KEYS.has(key)) {
            return `<th class="cap-col-${html(key)}">${label}</th>`;
          }
          const active = sort.key === key;
          const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "";
          return `<th class="cap-col-${html(key)} cap-sortable${active ? " sorted" : ""}" data-cap-sort="${html(key)}" title="点击按此列排序">${label}<span class="cap-sort-arrow">${arrow}</span></th>`;
        }).join("");
        const tr = viewRows.map((row) => {
          const rowKey = capitalRowKey(row);
          const expanded = sortable && state.capital.expandedKey === rowKey;
          const mainRow = `<tr class="capital-record-row${expanded ? " expanded" : ""}" data-cap-row-key="${html(rowKey)}" aria-expanded="${expanded ? "true" : "false"}" tabindex="0">${cols.map((key) => {
            const cls = key === "stock" ? "capital-stock-col" : (key === "actions" ? "capital-actions-col" : "");
            return `<td class="${cls}">${capitalCellHtml(row, key)}</td>`;
          }).join("")}</tr>`;
          return mainRow + (expanded ? capitalDetailHtml(row, cols.length) : "");
        }).join("");
        return `<table class="capital-data-table ${compact ? "compact" : ""}"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
      }

      function renderCapitalWindow(days) {
        const cap = state.capital;
        const meta = $(`#capitalWindow${days}Meta`);
        const box = $(`#capitalWindow${days}Table`);
        if (!box) return;
        const win = (cap.data && cap.data.windows && cap.data.windows[String(days)]) || {};
        const rows = win.rows || [];
        if (meta) meta.textContent = rows.length ? `${rows.length} 条 · 按${cap.tab === "moneyflow" ? "主力买入额" : "龙虎榜买入"}排序` : "--";
        if (!rows.length) {
          empty(box, `暂无${days}日聚合数据`);
          return;
        }
        box.innerHTML = capitalTableHtml(rows, true);
      }

      function updateCapitalAnalyzeBtn() {
        const cap = state.capital;
        const btn = $("#capitalAnalyzeBtn");
        if (btn) btn.textContent = `分析选中 (${cap.selected.size})`;
        const all = $("#capitalSelectAll");
        if (all) all.checked = cap.rows.length > 0 && cap.selected.size === cap.rows.length;
      }

      function renderCapitalRankings() {
        const cap = state.capital;
        const table = $("#capitalTable");
        if (!table) return;
        const d = cap.data || {};
        const meta = $("#capitalRankingsMeta");
        if (meta) {
          const tabName = cap.tab === "moneyflow" ? "主力买入榜" : "龙虎榜";
          const modeName = d.start_date && d.end_date
            ? `${d.start_date} ~ ${d.end_date} 区间`
            : (d.mode === "aggregate" ? `近${d.days}日聚合` : "单日");
          meta.textContent = `${tabName} · ${modeName} · ${d.as_of || "无数据"} · ${d.count || 0} 条`;
        }
        if (!cap.rows.length) {
          empty(table, "暂无数据。点「刷新 / 补偿数据」回填最近交易日,或调整日期 / 模式后「查询」。若回填后仍为空,多半是 Tushare Token 无效——请到「设置」检查 Token,并看「任务」里回填是否失败。");
          renderCapitalWindow(5);
          renderCapitalWindow(30);
          updateCapitalAnalyzeBtn();
          return;
        }
        table.innerHTML = capitalTableHtml(cap.rows);
        table.querySelectorAll("[data-cap-pick]").forEach((el) => el.addEventListener("change", () => {
          if (el.checked) cap.selected.add(el.dataset.capPick); else cap.selected.delete(el.dataset.capPick);
          updateCapitalAnalyzeBtn();
        }));
        table.querySelectorAll("[data-cap-watch]").forEach((el) => el.addEventListener("click", () =>
          addToWatchlist(el.dataset.capWatch, el.dataset.capName || "").catch((e) => alert(e.message))));
        table.querySelectorAll("[data-cap-analyze]").forEach((el) => el.addEventListener("click", () =>
          analyzeCapitalSelection([el.dataset.capAnalyze]).catch((e) => alert(e.message))));
        table.querySelectorAll("[data-cap-detail]").forEach((el) => el.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          toggleCapitalDetail(el.dataset.capDetail);
        }));
        table.querySelectorAll("[data-cap-row-key]").forEach((el) => {
          el.addEventListener("click", (event) => {
            if (event.target.closest("a, button, input, textarea, select, [data-kline-target]")) return;
            toggleCapitalDetail(el.dataset.capRowKey);
          });
          el.addEventListener("keydown", (event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            if (event.target.closest("a, button, input, textarea, select, [data-kline-target]")) return;
            event.preventDefault();
            toggleCapitalDetail(el.dataset.capRowKey);
          });
        });
        table.querySelectorAll("[data-cap-sort]").forEach((el) => el.addEventListener("click", () =>
          setCapitalSort(el.dataset.capSort)));
        renderCapitalWindow(5);
        renderCapitalWindow(30);
        updateCapitalAnalyzeBtn();
      }

      async function analyzeCapitalSelection(codes) {
        const cap = state.capital;
        const list = (codes && codes.length) ? codes : Array.from(cap.selected);
        if (!list.length) { showToast("请先勾选要分析的股票"); return; }
        const data = await fetchJson("/api/opportunity-discovery/start", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ stock_codes: list, source: "multi", limit: Math.max(list.length, 10), workers: 10 }),
        });
        showToast(`已提交分析任务（${list.length} 只），可在「任务」看进度,完成后见「报告库」`);
        loadJobs().catch(() => {});
        return data;
      }

      async function backfillCapital() {
        const cap = state.capital;
        const btn = $("#capitalBackfillBtn");
        const days = Number($("#capitalBackfillDays")?.value || 30);
        if (btn) { btn.disabled = true; btn.textContent = "回填中…"; }
        try {
          const resp = await fetchJson("/api/capital-rankings/backfill", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ days, kinds: [cap.tab] }),
          });
          showToast(`已提交回填任务（最近 ${days} 个交易日）…`);
          loadJobs().catch(() => {});
          const jobId = resp.job_id || resp.job?.id;
          if (jobId) {
            // 轮询任务结果:失败(多半是 Tushare Token 无效)就直接弹出原因,
            // 不再让用户对着「暂无数据」一脸懵;成功则自动刷新榜单。
            pollJob(jobId, {
              onDone: (job) => {
                if (job.status === "failed") {
                  const reason = job.error || latestJobLog(job) || "回填失败";
                  alert(`回填失败：${reason}`);
                } else {
                  loadCapitalRankings().catch(() => {});
                }
              },
            }).catch(() => {});
          }
        } catch (e) { alert(e.message); }
        finally { if (btn) { btn.disabled = false; btn.textContent = "刷新 / 补偿数据"; } }
      }

      function setCapitalSort(key) {
        const cap = state.capital;
        const cur = cap.sort || { key: null, dir: null };
        if (cur.key !== key) {
          cap.sort = { key, dir: "desc" };        // 首次点击该列:降序(榜单先看最大值)
        } else if (cur.dir === "desc") {
          cap.sort = { key, dir: "asc" };          // 再点:升序
        } else {
          cap.sort = { key: null, dir: null };     // 第三次:取消排序,回到原始榜单顺序
        }
        renderCapitalRankings();
      }

      function toggleCapitalDetail(key) {
        const cap = state.capital;
        cap.expandedKey = cap.expandedKey === key ? null : key;
        renderCapitalRankings();
      }

      function setCapitalTab(tab) {
        state.capital.tab = tab;
        state.capital.sort = { key: null, dir: null };   // 切换榜单时清空排序(两表列不同)
        state.capital.expandedKey = null;
        document.querySelectorAll("[data-cap-tab]").forEach((b) => {
          b.classList.toggle("secondary", b.dataset.capTab !== tab);
        });
        loadCapitalRankings().catch(() => {});
      }

      function setupCapitalRankings() {
        state.capital = { tab: "moneyflow", rows: [], selected: new Set(), data: null, mode: "single", sort: { key: null, dir: null }, expandedKey: null };
        document.querySelectorAll("[data-cap-tab]").forEach((b) =>
          b.addEventListener("click", () => setCapitalTab(b.dataset.capTab)));
        $("#capitalQueryBtn")?.addEventListener("click", () => loadCapitalRankings().catch((e) => alert(e.message)));
        $("#capitalBackfillBtn")?.addEventListener("click", () => backfillCapital());
        $("#capitalAnalyzeBtn")?.addEventListener("click", () => analyzeCapitalSelection().catch((e) => alert(e.message)));
        $("#capitalMode")?.addEventListener("change", () => loadCapitalRankings().catch(() => {}));
        $("#capitalSelectAll")?.addEventListener("change", (e) => {
          const cap = state.capital;
          cap.selected.clear();
          if (e.target.checked) cap.rows.forEach((r) => cap.selected.add(r.code));
          renderCapitalRankings();
        });
        setCapitalTab("moneyflow");
      }

      // ===================== 模拟盘 paper trading =====================
      function paperMoney(value) {
        const n = Number(value);
        if (!Number.isFinite(n)) return "--";
        const abs = Math.abs(n);
        const sign = n < 0 ? "-" : "";
        if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)}亿`;
        if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(2)}万`;
        return `${sign}${abs.toFixed(2)}`;
      }
      function pnlText(value) {
        const n = Number(value);
        if (!Number.isFinite(n)) return "--";
        return (n > 0 ? "+" : "") + paperMoney(n);
      }
      function paperStatTile(label, value, cls) {
        return `<div class="paper-stat"><span class="paper-stat-label">${html(label)}</span><strong class="${cls || ""}">${value}</strong></div>`;
      }

      function paperTodayText() {
        const now = new Date();
        const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
        return local.toISOString().slice(0, 10);
      }

      function paperStockRow(item) {
        const code = normalizeStockCode(item.stock_code || item.code || "");
        const name = item.stock_name || item.name || "";
        return { code, name, market: item.market || "--", industry: item.industry || "--" };
      }

      function setupPaperStockAutocomplete(codeSelector, nameSelector, suggestSelector) {
        const codeInput = $(codeSelector);
        const nameInput = $(nameSelector);
        const suggest = $(suggestSelector);
        if (!codeInput || !nameInput || !suggest || codeInput.dataset.paperStockBound) return;
        codeInput.dataset.paperStockBound = "1";
        let timer = null;
        let seq = 0;

        const hideSuggest = () => {
          suggest.hidden = true;
          suggest.innerHTML = "";
        };
        const applyStock = (stock) => {
          const row = paperStockRow(stock || {});
          if (row.code) codeInput.value = row.code;
          if (row.name) nameInput.value = row.name;
          hideSuggest();
        };
        const renderSuggest = (stocks, message = "") => {
          suggest.hidden = false;
          if (!stocks.length) {
            empty(suggest, message || "没有匹配股票。");
            return;
          }
          suggest.innerHTML = stocks.map((item, idx) => {
            const row = paperStockRow(item);
            return `<button class="item" type="button" data-paper-stock-idx="${idx}">
              <div class="item-top">
                <p class="item-title">${html(row.name || row.code)}</p>
                <span class="pill">${html(row.code)}</span>
              </div>
              <p class="item-meta">${html(row.market)} · ${html(row.industry)}</p>
            </button>`;
          }).join("");
          suggest.querySelectorAll("[data-paper-stock-idx]").forEach((btn) => {
            btn.addEventListener("click", () => applyStock(stocks[Number(btn.dataset.paperStockIdx)]));
          });
        };
        const run = async (source) => {
          const q = (source.value || "").trim();
          if (!q) { hideSuggest(); return; }
          const codeQuery = normalizeStockCode(q);
          if (!codeQuery && q.length < 2) { hideSuggest(); return; }
          const ticket = ++seq;
          try {
            const data = await fetchJson(`/api/pattern-search/stocks?q=${encodeURIComponent(q)}&limit=8`, { timeout: 12000 });
            if (ticket !== seq) return;
            const stocks = data.stocks || [];
            const exactCode = codeQuery ? stocks.find((s) => paperStockRow(s).code === codeQuery) : null;
            const exactName = stocks.find((s) => (paperStockRow(s).name || "").trim() === q);
            const singleName = source === nameInput && stocks.length === 1 && q.length >= 2 ? stocks[0] : null;
            const autoPick = exactCode || exactName || singleName;
            if (autoPick) {
              const row = paperStockRow(autoPick);
              if (row.code && (!normalizeStockCode(codeInput.value) || source === nameInput || exactCode)) {
                codeInput.value = row.code;
              }
              if (row.name && (!nameInput.value.trim() || source === codeInput || exactName || singleName)) {
                nameInput.value = row.name;
              }
              if (exactCode || exactName || singleName) {
                hideSuggest();
                return;
              }
            }
            renderSuggest(stocks, "没有匹配股票，可直接输入 6 位代码。");
          } catch (e) {
            if (ticket !== seq) return;
            renderSuggest([], "股票搜索失败:" + e.message);
          }
        };
        const schedule = (source) => {
          clearTimeout(timer);
          timer = setTimeout(() => run(source), 220);
        };
        codeInput.addEventListener("input", () => schedule(codeInput));
        nameInput.addEventListener("input", () => schedule(nameInput));
        suggest.addEventListener("mousedown", (e) => e.preventDefault());
        [codeInput, nameInput].forEach((input) => input.addEventListener("blur", () => {
          setTimeout(() => { if (!suggest.matches(":hover")) hideSuggest(); }, 180);
        }));
      }

      async function loadPaperTrading() {
        const [acc, pos, ord, trd, stats] = await Promise.all([
          fetchJson("/api/paper/account"),
          fetchJson("/api/paper/positions"),
          fetchJson("/api/paper/orders?status=pending"),
          fetchJson("/api/paper/trades?limit=200"),
          fetchJson("/api/paper/stats"),
        ]);
        renderPaperAccount(acc);
        renderPaperPositions(pos.positions || []);
        renderPaperOrders(ord.orders || []);
        renderPaperStats(stats);
        renderPaperTrades(trd.trades || []);
        loadPaperReviews().catch(() => {});
        $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
      }

      function renderPaperAccount(acc) {
        const box = $("#paperAccountStats");
        if (!box) return;
        const ret = acc.total_return || 0;
        box.innerHTML = [
          paperStatTile("起始资金", paperMoney(acc.initial_cash)),
          paperStatTile("可用资金", paperMoney(acc.cash)),
          paperStatTile("持仓市值", paperMoney(acc.position_value)),
          paperStatTile("总资产", paperMoney(acc.total_equity)),
          paperStatTile("总收益率", (ret * 100).toFixed(2) + "%", changeClass(ret)),
          paperStatTile("已实现盈亏", pnlText(acc.realized_pnl), changeClass(acc.realized_pnl)),
          paperStatTile("浮动盈亏", pnlText(acc.float_pnl), changeClass(acc.float_pnl)),
        ].join("");
      }

      function renderPaperPositions(positions) {
        const box = $("#paperPositions");
        const meta = $("#paperPositionsMeta");
        if (meta) meta.textContent = `${positions.length} 只持仓`;
        if (!box) return;
        if (!positions.length) { empty(box, "暂无持仓。买入后在此盯市。"); return; }
        box.innerHTML = positions.map((p) => {
          const rate = p.float_pnl_rate || 0;
          return `<div class="item" data-kline-target="${html(p.ts_code)}">
            <div class="item-top">
              <p class="item-title">${html(p.name || p.ts_code)} <span class="item-meta">${html(p.ts_code)}</span></p>
              <strong class="${changeClass(rate)}">${(rate * 100).toFixed(2)}%</strong>
            </div>
            <p class="item-meta">${p.qty}股 · 成本 ${num(p.avg_cost)} · 现价 ${num(p.last_price)} · 市值 ${paperMoney(p.market_value)} · 浮盈 <span class="${changeClass(p.float_pnl)}">${pnlText(p.float_pnl)}</span></p>
            <div class="actions paper-position-actions">
              <button class="button compact" type="button" data-paper-buy="${html(p.ts_code)}" data-paper-name="${html(p.name || "")}" data-paper-price-type="market" data-paper-price="${html(p.last_price)}">现价加仓</button>
              <button class="button secondary compact" type="button" data-paper-buy="${html(p.ts_code)}" data-paper-name="${html(p.name || "")}" data-paper-price-type="open" data-paper-price="${html(p.last_price)}">开盘价加仓</button>
              <button class="button secondary compact" type="button" data-paper-buy="${html(p.ts_code)}" data-paper-name="${html(p.name || "")}" data-paper-price-type="limit" data-paper-price="${html(p.last_price)}">输入价格加仓</button>
              <button class="button secondary compact" type="button" data-paper-sell="${html(p.ts_code)}" data-paper-name="${html(p.name || "")}" data-paper-qty="${p.qty}" data-paper-price="${html(p.last_price)}">卖出</button>
            </div>
          </div>`;
        }).join("");
      }

      function renderPaperOrders(orders) {
        const box = $("#paperOrders");
        if (!box) return;
        if (!orders.length) { empty(box, "暂无待撮合委托。"); return; }
        const labelOf = (o) => ({ market: "现价", open: "开盘价", close: "收盘价", limit: "输入价格" }[o.price_type] || o.price_type);
        box.innerHTML = orders.map((o) => `<div class="item">
          <div class="item-top">
            <p class="item-title">${o.side === "buy" ? "买入" : "卖出"} ${html(o.name || o.ts_code)} <span class="item-meta">${html(o.ts_code)}</span></p>
            <span class="pill">${labelOf(o)}</span>
          </div>
          <p class="item-meta">${o.qty ? o.qty + "股" : (o.amount_budget ? paperMoney(o.amount_budget) : "--")}${o.limit_price ? (" · 限价 " + num(o.limit_price)) : ""} · 下单 ${html(o.created_date || "")}</p>
          <div class="actions"><button class="button secondary compact" type="button" data-paper-cancel="${o.id}">撤单</button></div>
        </div>`).join("");
      }

      function renderPaperStats(stats) {
        const box = $("#paperStats");
        if (!box) return;
        const pf = stats.profit_factor;
        box.innerHTML = [
          paperStatTile("胜率", (stats.win_rate * 100).toFixed(1) + "%"),
          paperStatTile("卖出笔数", String(stats.sell_count)),
          paperStatTile("盈/亏笔", `${stats.win_count}/${stats.loss_count}`),
          paperStatTile("盈亏比", pf == null ? "--" : num(pf)),
          paperStatTile("平均盈利", pnlText(stats.avg_win), "change-up"),
          paperStatTile("平均亏损", pnlText(stats.avg_loss), "change-down"),
          paperStatTile("最大单笔盈", pnlText(stats.max_win), "change-up"),
          paperStatTile("最大单笔亏", pnlText(stats.max_loss), "change-down"),
          paperStatTile("最大回撤", (stats.max_drawdown * 100).toFixed(2) + "%", "change-down"),
        ].join("");
      }

      function renderPaperTrades(trades) {
        const box = $("#paperTrades");
        if (!box) return;
        if (!trades.length) { empty(box, "暂无成交记录。"); return; }
        box.innerHTML = trades.map((t) => `<div class="item">
          <div class="item-top">
            <p class="item-title">${t.side === "buy" ? "🟢 买入" : "🔴 卖出"} ${html(t.name || t.ts_code)} <span class="item-meta">${html(t.ts_code)}</span></p>
            ${t.realized_pnl != null ? `<strong class="${changeClass(t.realized_pnl)}">${pnlText(t.realized_pnl)}</strong>` : ""}
          </div>
          <p class="item-meta">${t.qty}股 @ ${num(t.price)} · 费 ${num(t.fee)} · ${html(t.traded_at || "")}</p>
        </div>`).join("");
      }

      function openPaperOrderDialog(opts = {}) {
        const dlg = $("#paperOrderDialog");
        if (!dlg) return;
        const priceType = opts.priceType || "market";
        dlg.dataset.refPrice = opts.price || "";
        $("#dlgCode").value = opts.code || "";
        $("#dlgName").value = opts.name || "";
        $("#dlgSide").value = opts.side || "buy";
        $("#dlgPriceType").value = priceType;
        $("#dlgQtyMode").value = opts.amount ? "amount" : "qty";
        $("#dlgQty").value = opts.qty || "";
        $("#dlgAmount").value = opts.amount || "";
        $("#dlgLimitPrice").value = opts.limitPrice || "";
        const res = $("#dlgResult"); res.hidden = true; res.textContent = "";
        syncPaperDialogFields();
        dlg.hidden = false; dlg.setAttribute("aria-hidden", "false");
        setTimeout(() => (priceType === "limit" ? $("#dlgLimitPrice") : $("#dlgCode"))?.focus(), 30);
      }

      function closePaperOrderDialog() {
        const dlg = $("#paperOrderDialog");
        if (!dlg) return;
        dlg.hidden = true; dlg.setAttribute("aria-hidden", "true");
      }

      function syncPaperDialogFields() {
        const pt = $("#dlgPriceType")?.value;
        const mode = $("#dlgQtyMode")?.value;
        if ($("#dlgLimitField")) $("#dlgLimitField").hidden = pt !== "limit";
        if ($("#dlgQtyField")) $("#dlgQtyField").hidden = mode !== "qty";
        if ($("#dlgAmountField")) $("#dlgAmountField").hidden = mode !== "amount";
        updatePaperOrderDialogCopy();
      }

      function updatePaperOrderDialogCopy() {
        const side = $("#dlgSide")?.value || "buy";
        const priceType = $("#dlgPriceType")?.value || "market";
        const sideText = side === "sell" ? "卖出" : "买入";
        const priceText = { market: "现价", open: "开盘价", limit: "输入价格" }[priceType] || "现价";
        const refPrice = $("#paperOrderDialog")?.dataset.refPrice;
        const ref = refPrice ? `参考现价 ${num(refPrice)}。` : "";
        if ($("#paperOrderTitle")) $("#paperOrderTitle").textContent = `${priceText}${sideText} · 模拟下单`;
        if ($("#dlgSubmitBtn")) $("#dlgSubmitBtn").textContent = `提交${sideText}`;
        if (!$("#dlgHint")) return;
        $("#dlgHint").textContent = priceType === "market"
          ? `${ref}现价单会立即按实时价成交。`
          : (priceType === "open"
            ? `${ref}开盘价单会进入委托区,结算时按日K开盘价撮合。`
            : `${ref}输入价格单会进入委托区,结算时按日K高低价区间撮合。`);
      }

      async function submitPaperOrderDialog() {
        const code = $("#dlgCode").value.trim();
        const res = $("#dlgResult");
        if (!code) { res.hidden = false; res.className = "notice status error"; res.textContent = "请填写代码"; return; }
        const mode = $("#dlgQtyMode").value;
        const payload = {
          ts_code: code, name: $("#dlgName").value.trim(),
          side: $("#dlgSide").value, price_type: $("#dlgPriceType").value,
        };
        if (mode === "qty") payload.qty = Number($("#dlgQty").value) || 0;
        else payload.amount = Number($("#dlgAmount").value) || 0;
        if (payload.price_type === "limit") payload.limit_price = Number($("#dlgLimitPrice").value) || 0;
        const btn = $("#dlgSubmitBtn"); btn.disabled = true;
        try {
          const data = await fetchJson("/api/paper/order", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
          });
          const o = data.order || {};
          res.hidden = false;
          if (o.status === "filled") {
            res.className = "notice status success";
            const pnl = o.realized_pnl != null ? ` · 已实现 ${pnlText(o.realized_pnl)}` : "";
            res.textContent = `✅ 成交:${o.filled_qty}股 @ ${num(o.filled_price)} · 费 ${num(o.fee)}${pnl}`;
            showToast("模拟成交成功");
          } else if (o.status === "pending") {
            res.className = "notice status"; res.textContent = "🕒 已进入委托区,收盘后撮合。";
            showToast("已挂委托");
          } else {
            res.className = "notice status error"; res.textContent = `❌ 未成交:${o.note || o.status || "下单失败"}`;
          }
          if (page === "paper_trading") loadPaperTrading().catch(() => {});
        } catch (e) {
          res.hidden = false; res.className = "notice status error"; res.textContent = "下单失败:" + e.message;
        } finally { btn.disabled = false; }
      }

      function openPaperHistoryDialog(opts = {}) {
        const dlg = $("#paperHistoryDialog");
        if (!dlg) return;
        $("#histCode").value = opts.code || "";
        $("#histName").value = opts.name || "";
        $("#histTradeDate").value = opts.tradeDate || paperTodayText();
        $("#histPrice").value = opts.price || "";
        $("#histQty").value = opts.qty || "";
        const res = $("#histResult"); res.hidden = true; res.textContent = "";
        dlg.hidden = false; dlg.setAttribute("aria-hidden", "false");
        setTimeout(() => $("#histCode")?.focus(), 30);
      }

      function closePaperHistoryDialog() {
        const dlg = $("#paperHistoryDialog");
        if (!dlg) return;
        dlg.hidden = true; dlg.setAttribute("aria-hidden", "true");
      }

      async function submitPaperHistoryDialog() {
        const code = $("#histCode").value.trim();
        const res = $("#histResult");
        if (!code) { res.hidden = false; res.className = "notice status error"; res.textContent = "请填写代码"; return; }
        const payload = {
          ts_code: code,
          name: $("#histName").value.trim(),
          trade_date: $("#histTradeDate").value,
          price: Number($("#histPrice").value) || 0,
          qty: Number($("#histQty").value) || 0,
        };
        const btn = $("#histSubmitBtn"); btn.disabled = true;
        try {
          const data = await fetchJson("/api/paper/history-buy", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
          });
          const o = data.order || {};
          res.hidden = false;
          if (o.status === "filled") {
            res.className = "notice status success";
            res.textContent = `已导入:${o.filled_qty}股 @ ${num(o.filled_price)} · 费 ${num(o.fee)} · 日期 ${html(o.created_date || "")}`;
            showToast("历史买入已导入");
            if (page === "paper_trading") loadPaperTrading().catch(() => {});
          } else {
            res.className = "notice status error";
            res.textContent = `导入失败:${o.note || o.status || "参数无效"}`;
          }
        } catch (e) {
          res.hidden = false; res.className = "notice status error"; res.textContent = "导入失败:" + e.message;
        } finally { btn.disabled = false; }
      }

      function setupPaperOrderDialog() {
        $("#paperOrderCloseBtn")?.addEventListener("click", closePaperOrderDialog);
        $("#paperOrderDialog")?.addEventListener("click", (e) => { if (e.target === e.currentTarget) closePaperOrderDialog(); });
        $("#dlgPriceType")?.addEventListener("change", syncPaperDialogFields);
        $("#dlgSide")?.addEventListener("change", updatePaperOrderDialogCopy);
        $("#dlgQtyMode")?.addEventListener("change", syncPaperDialogFields);
        $("#dlgSubmitBtn")?.addEventListener("click", () => submitPaperOrderDialog());
        setupPaperStockAutocomplete("#dlgCode", "#dlgName", "#dlgStockSuggest");
        $("#paperHistoryCloseBtn")?.addEventListener("click", closePaperHistoryDialog);
        $("#paperHistoryDialog")?.addEventListener("click", (e) => { if (e.target === e.currentTarget) closePaperHistoryDialog(); });
        $("#histSubmitBtn")?.addEventListener("click", () => submitPaperHistoryDialog());
        setupPaperStockAutocomplete("#histCode", "#histName", "#histStockSuggest");
        // 「加入买入池」按钮(机会结果卡片内)→ 打开下单弹窗(全局委托,卡片可在任意页的报告预览弹窗中出现)
        document.addEventListener("click", (e) => {
          const b = e.target.closest("[data-buy-pool]");
          if (!b) return;
          e.preventDefault(); e.stopPropagation();
          openPaperOrderDialog({ code: b.dataset.buyPool, name: b.dataset.buyName || "", side: "buy" });
        });
      }

      function setupPaperTrading() {
        $("#paperBuyMarketBtn")?.addEventListener("click", () => openPaperOrderDialog({ side: "buy", priceType: "market" }));
        $("#paperBuyOpenBtn")?.addEventListener("click", () => openPaperOrderDialog({ side: "buy", priceType: "open" }));
        $("#paperBuyLimitBtn")?.addEventListener("click", () => openPaperOrderDialog({ side: "buy", priceType: "limit" }));
        $("#paperHistoryBtn")?.addEventListener("click", () => openPaperHistoryDialog());
        $("#paperSettleBtn")?.addEventListener("click", () => settlePaper());
        $("#paperResetBtn")?.addEventListener("click", () => resetPaperAccount());
        $("#paperPositions")?.addEventListener("click", (e) => {
          const buy = e.target.closest("[data-paper-buy]");
          if (buy) {
            e.stopPropagation();
            openPaperOrderDialog({
              code: buy.dataset.paperBuy,
              name: buy.dataset.paperName,
              side: "buy",
              priceType: buy.dataset.paperPriceType || "market",
              price: buy.dataset.paperPrice,
            });
            return;
          }
          const sell = e.target.closest("[data-paper-sell]");
          if (!sell) return;
          e.stopPropagation();
          openPaperOrderDialog({
            code: sell.dataset.paperSell,
            name: sell.dataset.paperName,
            side: "sell",
            qty: sell.dataset.paperQty,
            price: sell.dataset.paperPrice,
          });
        });
        $("#paperOrders")?.addEventListener("click", (e) => {
          const c = e.target.closest("[data-paper-cancel]");
          if (c) cancelPaperOrder(c.dataset.paperCancel);
        });
        $("#paperReviews")?.addEventListener("click", (e) => {
          const r = e.target.closest("[data-paper-review]");
          if (r) openPaperReview(r.dataset.paperReview);
        });
        loadPaperTrading().catch((e) => showToast("模拟盘加载失败:" + e.message));
      }

      async function cancelPaperOrder(id) {
        try {
          await fetchJson(`/api/paper/order/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          showToast("已撤单");
          loadPaperTrading().catch(() => {});
        } catch (e) { alert("撤单失败:" + e.message); }
      }

      async function resetPaperAccount() {
        const cash = Number($("#paperResetCash")?.value) || 1000000;
        if (!confirm(`确认重置模拟盘?将清空所有持仓/委托/成交,起始资金设为 ${paperMoney(cash)}。`)) return;
        try {
          await fetchJson("/api/paper/reset", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ initial_cash: cash }) });
          showToast("已重置");
          loadPaperTrading().catch(() => {});
        } catch (e) { alert("重置失败:" + e.message); }
      }

      async function settlePaper() {
        const btn = $("#paperSettleBtn");
        if (btn) btn.disabled = true;
        try {
          const r = await fetchJson("/api/paper/settle", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
          const parts = [];
          if (r.settled) parts.push(`撮合成交 ${r.settled} 笔`);
          if (r.rejected) parts.push(`撮合驳回 ${r.rejected} 笔`);
          if (r.generated) parts.push("已生成当日复盘");
          else if (r.activity) parts.push("复盘已存在");
          showToast(parts.length ? parts.join(" · ") : "结算完成,当日无操作");
          await loadPaperTrading().catch(() => {});
          if (r.generated && r.date) openPaperReview(r.date);
        } catch (e) {
          alert("结算失败:" + e.message);
        } finally {
          if (btn) btn.disabled = false;
        }
      }

      async function loadPaperReviews() {
        try {
          const data = await fetchJson("/api/paper/reviews?limit=60");
          renderPaperReviews(data.reviews || []);
        } catch (e) {
          const box = $("#paperReviews");
          if (box) empty(box, "复盘列表加载失败:" + e.message);
        }
      }

      function renderPaperReviews(reviews) {
        const box = $("#paperReviews");
        if (!box) return;
        if (!reviews.length) { empty(box, "暂无复盘。收盘后自动生成,或点「立即结算/复盘」。"); return; }
        box.innerHTML = reviews.map((r) => `<div class="item" data-paper-review="${html(r.date)}" style="cursor:pointer;">
          <div class="item-top">
            <p class="item-title">📓 ${html(r.date)} 当日复盘</p>
            <span class="pill">查看</span>
          </div>
          <p class="item-meta">${html(r.file)}</p>
        </div>`).join("");
      }

      async function openPaperReview(date) {
        const modal = $("#filePreviewModal");
        const body = $("#filePreviewBody");
        const title = $("#filePreviewTitle");
        const meta = $("#filePreviewMeta");
        const openBtn = $("#filePreviewOpenBtn");
        if (!modal || !body) return;
        title.textContent = `模拟盘复盘 · ${date}`;
        meta.textContent = `paper_review_${date}.md`;
        if (openBtn) openBtn.href = `/api/paper/review/${encodeURIComponent(date)}`;
        body.innerHTML = `<div class="stock-context-loading">加载中…</div>`;
        modal.hidden = false; modal.setAttribute("aria-hidden", "false");
        try {
          const data = await fetchJson(`/api/paper/review/${encodeURIComponent(date)}`);
          body.innerHTML = `<div class="file-preview-md">${renderReviewMarkdown(data.content || "")}</div>`;
        } catch (e) {
          body.innerHTML = `<div class="notice status error">复盘加载失败:${html(e.message)}</div>`;
        }
      }

      // 复盘专用 markdown 渲染:支持 GitHub 表格(共享 renderMarkdown 不支持表格,且为别处复用,故独立实现避免回归)
      function renderReviewMarkdown(text) {
        const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
        const isRow = (l) => /^\s*\|.*\|\s*$/.test(l || "");
        const isSep = (l) => /^\s*\|?[\s:|-]+\|?\s*$/.test(l || "") && (l || "").includes("-") && (l || "").includes("|");
        const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        const lines = String(text).split("\n");
        const out = [];
        let i = 0;
        while (i < lines.length) {
          const line = lines[i];
          if (isRow(line) && isSep(lines[i + 1])) {
            const head = cells(line); i += 2;
            const rows = [];
            while (i < lines.length && isRow(lines[i])) { rows.push(cells(lines[i])); i++; }
            const th = head.map((c) => `<th style="text-align:left;padding:5px 8px;border-bottom:2px solid #cfd8dc;">${inline(c)}</th>`).join("");
            const tr = rows.map((r) => `<tr>${r.map((c) => `<td style="padding:4px 8px;border-bottom:1px solid #eceff1;">${inline(c)}</td>`).join("")}</tr>`).join("");
            out.push(`<table style="width:100%;border-collapse:collapse;margin:8px 0;font-size:0.85rem;"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`);
            continue;
          }
          let m;
          if ((m = /^#\s+(.+)$/.exec(line))) out.push(`<h2 style="margin:14px 0 8px;">${inline(m[1])}</h2>`);
          else if ((m = /^##\s+(.+)$/.exec(line))) out.push(`<h3 style="margin:12px 0 6px;">${inline(m[1])}</h3>`);
          else if ((m = /^###\s+(.+)$/.exec(line))) out.push(`<h4 style="margin:10px 0 6px;">${inline(m[1])}</h4>`);
          else if (/^\s*>\s?/.test(line)) out.push(`<blockquote style="margin:6px 0;padding:6px 10px;border-left:3px solid #cfd8dc;color:#546e7a;">${inline(line.replace(/^\s*>\s?/, ""))}</blockquote>`);
          else if (/^\s*---\s*$/.test(line)) out.push("<hr>");
          else if (line.trim() === "") out.push("");
          else out.push(`<p style="margin:4px 0;">${inline(line)}</p>`);
          i++;
        }
        return out.join("\n");
      }

      // ===================== 风险·机遇 作战大屏 command center =====================
      const CC_ACTION_COLOR = { act: "#25b88a", do: "#cfa233", care: "#cf922a", watch: "#25c2b4",
                                avoid: "#cc5878", none: "#6a93d2", unknown: "#6a93d2" };
      let ccLiveTimer = null;
      let ccKeysBound = false;
      let ccLastData = null;
      let ccActiveDate = null;   // 历史日切换:null=最近一天

      function ccRiskLabel(v) { if (v == null) return "未知"; if (v < 40) return "低"; if (v >= 60) return "高"; return "中"; }
      function ccOppLabel(v) { if (v >= 70) return "较好"; if (v >= 55) return "中性"; return "偏弱"; }
      function ccPct(v) { return (v == null ? "—" : `${Math.round(v * 100)}%`); }
      function ccYi(v) {
        if (v == null || isNaN(v)) return "—";
        const yi = Number(v) / 1e8;
        if (Math.abs(yi) >= 0.01) return `${yi >= 0 ? "+" : ""}${yi.toFixed(1)}亿`;
        const wan = Number(v) / 1e4;
        return `${wan >= 0 ? "+" : ""}${wan.toFixed(0)}万`;
      }

      function ccGauge(v, label, color, sub, detail) {
        const val = (v == null ? 0 : Math.round(v));
        return `<div class="panel gaugebox">
          <div class="ring" style="--v:${val};--c:${color}"><div class="rv"><b class="num">${val}</b><s>${html(sub || "")}</s></div></div>
          <div class="glabel"><b>${html(label)}</b><span style="color:${color}">${html(detail || "")}</span></div></div>`;
      }

      function ccPills(d) {
        const p = d.portfolio || {};
        const m = d.matrix || [];
        const act = m.filter((t) => t.code_action === "act").length;
        const avoid = m.filter((t) => t.code_action === "avoid").length;
        const held = m.filter((t) => t.held).length;
        const pill = (s, b) => `<div class="pillk"><s>${html(s)}</s><b class="num">${b}</b></div>`;
        return pill("标的数", (d.as_of && d.as_of.count != null ? d.as_of.count : m.length))
          + pill("撮合 出手 / 回避", `<span class="up">${act}</span> / <span class="down">${avoid}</span>`)
          + pill("持仓数", held)
          + pill("组合敞口", ccPct(p.exposure))
          + pill("最大集中 / 回撤", `${ccPct(p.concentration)} / ${ccPct(p.max_drawdown)}`);
      }

      function ccKpiStrip(d) {
        const i = d.indices || {};
        const mr = i.market_risk == null ? 0 : i.market_risk;
        const op = i.opportunity == null ? 0 : i.opportunity;
        const se = i.sentiment == null ? 0 : i.sentiment;
        return `<div class="kpi">
          ${ccGauge(mr, "市场风险", "#cf922a", ccRiskLabel(mr), mr >= 60 ? "系统性偏高 ⚠" : (mr < 40 ? "系统性偏低" : "中性"))}
          ${ccGauge(op, "机会指数", "#25b88a", ccOppLabel(op), `池 ${(d.as_of && d.as_of.count) || 0} 只`)}
          ${ccGauge(se, "市场情绪", "#4a82cf", se >= 60 ? "偏暖" : (se <= 40 ? "偏冷" : "中性"), "中性基准")}
          <div class="panel pills">${ccPills(d)}</div></div>`;
      }

      function ccStatusBar(d) {
        const deg = d.degraded || {};
        const reportTxt = (d.as_of && d.as_of.report) ? `报告 ${html(String(d.as_of.report))}` : "无报告";
        const sidecarTxt = (d.as_of && d.as_of.sidecar) ? "信号已加载" : "信号缺失·风险未知";
        const degHint = deg.opportunity ? ' ｜ <span style="color:#cf922a">机会源降级</span>' : "";
        const asOf = d.as_of || {};
        const dates = Array.isArray(d.available_dates) ? d.available_dates : [];
        const sel = asOf.date || ccActiveDate || (dates[0] || "");
        const dateOptions = dates.length
          ? dates.map((dt) => `<option value="${html(dt)}"${String(dt) === String(sel) ? " selected" : ""}>${html(dt)}</option>`).join("")
          : `<option value="">最近一天</option>`;
        const reportCount = asOf.report_count ? ` ｜ 当日报告 <b>${html(asOf.report_count)}</b> 份` : "";
        return `<div class="status">
          <h1>风险<span class="accent">·</span>机遇 <span style="font-size:13px;letter-spacing:2px;color:var(--muted);">统筹作战大屏</span></h1>
          <div class="meta">${reportTxt} ｜ 池 <b>${(d.as_of && d.as_of.count) || 0}</b> 只 ｜ <b>${sidecarTxt}</b>${reportCount}${degHint}</div>
          <div class="sp"></div>
          <label class="cc-date-pick" title="切换历史日期(聚合当日全部报告)">日期 <select class="cc-date-select" data-cc-date>${dateOptions}</select></label>
          <div class="btn hot" data-cc-action="recompute">↻ 重新统筹</div>
          <div class="btn" data-cc-action="fullscreen">⛶ 全屏大屏</div>
        </div>`;
      }

      function ccHeroRow(d) {
        const hasMatrix = (d.matrix || []).length > 0;
        const matrixInner = hasMatrix
          ? `<div class="plotwrap"><div id="ccMatrix" style="width:100%;height:300px;"></div></div>`
          : `<div class="cc-empty">暂无机会池数据 — 点「↻ 重新统筹」生成报告</div>`;
        return `<div class="hero">
          <div class="panel">
            <div class="ph"><span class="dotmark"></span><b>风险–机遇撮合矩阵</b>
              <span class="tag">x=机会分 · y=风险(上低下高) · 色=行动</span></div>
            ${matrixInner}
          </div>
          <div class="panel">
            <div class="ph"><span class="dotmark" style="background:#cf922a"></span><b>行业热力</b><span class="tag">块=标的数 · 色=机会强弱</span></div>
            <div class="tmwrap"><div id="ccSectorHeat" class="tm"></div></div>
          </div></div>`;
      }

      function ccRankRowCapital(row, maxAbs) {
        const nm = row.name || row.ts_code || row.code || "--";
        const val = row.main_buy_amount != null ? row.main_buy_amount : row.net_amount;
        const w = maxAbs > 0 ? Math.max(6, Math.round(Math.abs(val || 0) / maxAbs * 100)) : 6;
        const cls = (val || 0) >= 0 ? "up" : "down";
        const code = row.code || (row.ts_code || "").split(".")[0];
        return `<div class="rk-row">
          <span class="rno">${row.rank || ""}</span>
          <div><div class="rnm">${html(nm)}</div><div class="rbar" style="width:${w}%"></div></div>
          <div><div class="rval ${cls} num">${ccYi(val)}</div>
            <div class="acts" data-cc-code="${html(code)}" data-cc-name="${html(nm)}">
              <span class="mini" data-cc-act="analyze">析</span><span class="mini" data-cc-act="watch">自</span><span class="mini" data-cc-act="pool">池</span></div></div></div>`;
      }

      function ccRankRowOpp(t) {
        const badge = t.rating === "S" ? "b-s" : (t.rating === "A" ? "b-a" : "b-b");
        const riskTxt = t.risk == null ? "未知" : Math.round(t.risk);
        return `<div class="rk-row">
          <span class="badge ${badge}">${html(t.rating || "—")}</span>
          <div><div class="rnm">${html(t.name || t.code)}</div><div class="rsub">${html(t.action || "")}${t.sector ? " · " + html(t.sector) : ""}</div></div>
          <div class="dual" style="text-align:right"><b class="op num">${Math.round(t.opp || 0)}</b><span class="rsub">/ 风险 <span class="rk num">${riskTxt}</span></span></div></div>`;
      }

      function ccRankRowHold(t) {
        const flag = t.held_overlay === "减仓/止盈"
          ? '<span class="flag f-cut">⚠减仓</span>'
          : (t.held_overlay === "持有" ? '<span class="flag f-hold">持有</span>' : "");
        const riskTxt = t.risk == null ? "未知" : Math.round(t.risk);
        return `<div class="rk-row">
          <span class="rno">持</span>
          <div><div class="rnm">${html(t.name || t.code)} ${flag}</div><div class="rsub">${html(t.action || "")} · 风险 ${riskTxt} · 机会 ${Math.round(t.opp || 0)}</div></div>
          <div class="acts" data-cc-code="${html(t.code)}" data-cc-name="${html(t.name || "")}"><span class="mini" data-cc-act="analyze">析</span></div></div>`;
      }

      function ccRankings(d) {
        const cap = (d.rankings && d.rankings.capital) ? d.rankings.capital.slice(0, 6) : [];
        const maxAbs = cap.reduce((mx, r) => Math.max(mx, Math.abs((r.main_buy_amount != null ? r.main_buy_amount : r.net_amount) || 0)), 0);
        const capRows = cap.length ? cap.map((r) => ccRankRowCapital(r, maxAbs)).join("") : `<div class="cc-empty">资金榜单暂无数据</div>`;
        const oppTop = (d.matrix || []).slice().sort((a, b) => (b.opp || 0) - (a.opp || 0)).slice(0, 6);
        const oppRows = oppTop.length ? oppTop.map(ccRankRowOpp).join("") : `<div class="cc-empty">暂无机会标的</div>`;
        const held = (d.matrix || []).filter((t) => t.held);
        const p = d.portfolio || {};
        const portfolioRow = `<div class="rk-row"><span class="rno">组</span>
          <div><div class="rnm">组合风险 ${Math.round(p.risk || 0)}</div><div class="rsub">敞口 ${ccPct(p.exposure)} · 集中 ${ccPct(p.concentration)} · 回撤 ${ccPct(p.max_drawdown)}</div></div><div></div></div>`;
        const holdRows = held.length ? held.map(ccRankRowHold).join("") : `<div class="cc-empty">无模拟盘持仓</div>`;
        return `<div class="ranks">
          <div class="panel"><div class="ph"><span class="dotmark"></span><b>资金主线榜</b><span class="tag">主力买入 / 净额</span></div>${capRows}</div>
          <div class="panel"><div class="ph"><span class="dotmark" style="background:#25b88a"></span><b>机会 Top 榜</b><span class="tag">机会分 / 风险分 双标</span></div>${oppRows}</div>
          <div class="panel"><div class="ph"><span class="dotmark" style="background:#cc5878"></span><b>持仓 · 组合风险</b><span class="tag">集中度 / 回撤 / 提示</span></div>${portfolioRow}${holdRows}</div>
        </div>`;
      }

      function ccTicker(d) {
        const m = d.matrix || [];
        const acts = m.filter((t) => t.code_action === "act").slice(0, 4).map((t) => `<i class="g">🟢 出手 ${html(t.name || t.code)} 机会${Math.round(t.opp || 0)}/风险${t.risk == null ? "?" : Math.round(t.risk)}</i>`);
        const cares = m.filter((t) => t.code_action === "care" || t.code_action === "avoid").slice(0, 4).map((t) => `<i>${t.code_action === "avoid" ? "🔴 回避" : "🟠 谨慎"} ${html(t.name || t.code)} ${html(t.reason || "")}</i>`);
        const items = acts.concat(cares);
        const body = items.length ? items.join("") : '<i>暂无撮合提示 — 重新统筹后生成</i>';
        return `<div class="panel ticker"><span class="lead">⚡ 撮合 · 风险提示</span>
          <div class="tk-track"><span>${body}${body}</span></div></div>`;
      }

      function ccToggleFullscreen() {
        const el = $("#commandCenterRoot");
        if (!el) return;
        el.classList.toggle("cc-fullscreen");
        document.body.classList.toggle("cc-fs-on");
        if (typeof Plotly !== "undefined") { try { Plotly.Plots.resize("ccMatrix"); } catch (e) {} }
      }

      function ccBindGlobalKeys() {
        if (ccKeysBound) return;
        ccKeysBound = true;
        document.addEventListener("keydown", (e) => {
          if (e.key === "Escape") {
            const el = document.querySelector(".cc-screen.cc-fullscreen");
            if (el) { el.classList.remove("cc-fullscreen"); document.body.classList.remove("cc-fs-on"); }
          }
        });
      }

      // ---- 每标的动作:复用既有 深度分析 / 加自选 / 模拟盘下单 ----
      function ccTargetAction(act, code, name) {
        if (!code) return;
        if (act === "analyze") {
          openStockContext({ stock_code: code, stock_name: name || "" }).catch(() => {});
        } else if (act === "watch") {
          addToWatchlist(code, name || "").catch((e) => alert(e.message));
        } else if (act === "pool") {
          try { openPaperOrderDialog({ code: code, ts_code: code, name: name || "", side: "buy" }); }
          catch (e) { console.warn("paper order open failed", e); }
        }
      }

      function ccBindActions(host, data) {
        host.querySelectorAll("[data-cc-action]").forEach((el) => {
          el.addEventListener("click", () => {
            const a = el.dataset.ccAction;
            if (a === "fullscreen") ccToggleFullscreen();
            else if (a === "recompute") ccRecompute();
          });
        });
        const dateSel = host.querySelector("[data-cc-date]");
        if (dateSel) {
          dateSel.addEventListener("change", () => {
            ccActiveDate = dateSel.value || null;
            loadCommandCenter().catch((e) => alert("切换日期失败: " + e.message));
          });
        }
        host.querySelectorAll(".acts").forEach((box) => {
          const code = box.dataset.ccCode, name = box.dataset.ccName;
          box.querySelectorAll("[data-cc-act]").forEach((btn) => {
            btn.addEventListener("click", (e) => { e.stopPropagation(); ccTargetAction(btn.dataset.ccAct, code, name); });
          });
        });
      }

      // ---- Plotly 风险–机遇撮合散点矩阵 ----
      function ccQuadShapes() {
        const band = (x0, x1, y0, y1, color) => ({ type: "rect", xref: "x", yref: "y", x0, x1, y0, y1,
          fillcolor: color, line: { width: 0 }, layer: "below" });
        return [
          band(62, 100, 0, 50, "rgba(37,184,138,.13)"),   // 高机会·低风险 出手(右上,y反向后0-50=低风险)
          band(30, 62, 0, 50, "rgba(74,130,207,.08)"),    // 低机会·低风险 关注
          band(62, 100, 50, 100, "rgba(207,146,42,.12)"), // 高机会·高风险 谨慎
          band(30, 62, 50, 100, "rgba(204,88,120,.12)"),  // 低机会·高风险 回避
        ];
      }

      function ccDrawMatrix(d) {
        const host = document.getElementById("ccMatrix");
        if (!host) return;
        const pts = (d.matrix || []).filter((t) => t.risk != null);
        if (typeof Plotly === "undefined") {
          host.innerHTML = '<div class="cc-empty">图表加载中…</div>';
          ccDrawMatrix._retry = (ccDrawMatrix._retry || 0) + 1;
          if (ccDrawMatrix._retry <= 20) setTimeout(() => ccDrawMatrix(d), 300);
          return;
        }
        ccDrawMatrix._retry = 0;
        if (!pts.length) { host.innerHTML = '<div class="cc-empty">无可定位标的(缺结构化信号)</div>'; return; }
        const size = pts.map((t) => (t.held ? 20 : 0) + (t.rating === "S" ? 17 : t.rating === "A" ? 14 : 11));
        const trace = {
          x: pts.map((t) => t.opp), y: pts.map((t) => t.risk),
          text: pts.map((t) => t.name || t.code),
          hovertext: pts.map((t) => `${t.name || t.code}<br>${t.reason || ""}`),
          hoverinfo: "text",
          mode: "markers+text",
          textposition: "top center",
          textfont: { color: "#aebfda", size: 9 },
          customdata: pts.map((t) => t.code),
          marker: { size, color: pts.map((t) => CC_ACTION_COLOR[t.code_action] || "#6a93d2"),
                    line: { color: "rgba(255,255,255,.32)", width: 1 }, opacity: 0.92 },
          type: "scatter",
        };
        const layout = {
          paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
          font: { color: "#aebfda", size: 10 }, margin: { l: 40, r: 12, t: 8, b: 30 }, showlegend: false,
          xaxis: { title: "机会分 →", range: [30, 100], gridcolor: "rgba(95,130,173,.12)", zeroline: false },
          yaxis: { title: "风险(上低下高)", range: [100, 0], gridcolor: "rgba(95,130,173,.12)", zeroline: false },
          shapes: ccQuadShapes(),
        };
        Plotly.react("ccMatrix", [trace], layout, { displayModeBar: false, responsive: true });
        host.removeAllListeners && host.removeAllListeners("plotly_click");
        host.on && host.on("plotly_click", (ev) => {
          const code = ev.points && ev.points[0] && ev.points[0].customdata;
          const t = pts.find((x) => x.code === code);
          if (t) ccTargetAction("analyze", t.code, t.name);
        });
      }

      // ---- 行业热力:按 matrix 的 sector 聚合(块=标的数,色=平均机会强弱) ----
      function ccDrawSectorHeat(d) {
        const host = document.getElementById("ccSectorHeat");
        if (!host) return;
        const bySector = {};
        (d.matrix || []).forEach((t) => {
          const s = t.sector || "其他";
          (bySector[s] = bySector[s] || { n: 0, opp: 0, risk: 0, riskN: 0 });
          bySector[s].n += 1; bySector[s].opp += (t.opp || 0);
          if (t.risk != null) { bySector[s].risk += t.risk; bySector[s].riskN += 1; }
        });
        const rows = Object.keys(bySector).map((s) => {
          const v = bySector[s];
          return { name: s, n: v.n, avgOpp: v.opp / v.n, avgRisk: v.riskN ? v.risk / v.riskN : null };
        }).sort((a, b) => b.n - a.n).slice(0, 12);
        if (!rows.length) { host.innerHTML = '<div class="cc-empty">板块数据待接入</div>'; return; }
        const maxN = rows.reduce((mx, r) => Math.max(mx, r.n), 1);
        host.innerHTML = rows.map((r) => {
          const span = Math.max(1, Math.min(3, Math.round(r.n / maxN * 3)));
          const cls = r.avgOpp >= 70 ? "r-hot" : r.avgOpp >= 58 ? "r-up" : r.avgOpp >= 50 ? "flat" : "g-up";
          const crowd = (r.avgRisk != null && r.avgRisk >= 60) ? " crowd" : "";
          const warn = crowd ? '<span class="warn">⚠拥挤</span>' : "";
          return `<div class="blk ${cls}${crowd}" style="grid-column:span ${span}">${warn}<b>${html(r.name)}</b><s class="num">${r.n}只 · 机会${Math.round(r.avgOpp)}</s></div>`;
        }).join("");
      }

      // ---- 实时 30s 叠加(盘中,收盘停):仅刷新报价相关,不重算结构 ----
      function ccIsTradingHours() {
        const now = new Date();
        const day = now.getDay();
        if (day === 0 || day === 6) return false;
        const m = now.getHours() * 60 + now.getMinutes();
        return (m >= 9 * 60 + 30 && m <= 11 * 60 + 30) || (m >= 13 * 60 && m <= 15 * 60);
      }

      function ccStartLiveRefresh() {
        if (ccLiveTimer) clearInterval(ccLiveTimer);
        ccLiveTimer = setInterval(async () => {
          if (page !== "command_center") { clearInterval(ccLiveTimer); ccLiveTimer = null; return; }
          if (!ccIsTradingHours()) return;
          try {
            const q = await fetchJson(`/api/command-center/overview?quotes_only=1${ccActiveDate ? `&date=${encodeURIComponent(ccActiveDate)}` : ""}`);
            ccLastData = q;
            const host = $("#commandCenterRoot");
            if (host) { ccBindActions(host, q); ccDrawMatrix(q); ccDrawSectorHeat(q); }
            const kpi = host && host.querySelector(".kpi");
            if (kpi) kpi.outerHTML = ccKpiStrip(q);
          } catch (e) { /* 静默:实时叠加失败不打断 */ }
        }, 30000);
      }

      async function ccRecompute() {
        const btn = document.querySelector('#commandCenterRoot [data-cc-action="recompute"]');
        if (btn) { btn.textContent = "↻ 统筹中…"; btn.style.pointerEvents = "none"; }
        try {
          const res = await fetchJson("/api/command-center/recompute", { method: "POST" });
          const jobId = res.job_id || (res.job && res.job.id);
          if (!jobId) throw new Error("未返回 job_id");
          await pollJob(jobId, { onDone: async () => { await loadCommandCenter(); } });
        } catch (e) {
          alert("重新统筹失败: " + e.message);
        } finally {
          if (btn) { btn.textContent = "↻ 重新统筹"; btn.style.pointerEvents = ""; }
        }
      }

      function renderCommandCenter(host, data) {
        host.innerHTML = ccStatusBar(data) + ccKpiStrip(data) + ccHeroRow(data) + ccRankings(data) + ccTicker(data);
        ccBindActions(host, data);
        ccDrawMatrix(data);
        ccDrawSectorHeat(data);
      }

      async function loadCommandCenter() {
        const host = $("#commandCenterRoot");
        if (!host) return;
        host.classList.add("cc-screen");
        let data;
        try { data = await fetchJson(`/api/command-center/overview${ccActiveDate ? `?date=${encodeURIComponent(ccActiveDate)}` : ""}`); }
        catch (e) { host.innerHTML = `<div class="cc-empty">大屏数据加载失败:${html(e.message)}</div>`; return; }
        ccLastData = data;
        renderCommandCenter(host, data);
        $("#refreshMeta").textContent = `更新 ${new Date().toLocaleTimeString()}`;
      }

      function setupCommandCenter() {
        ccBindGlobalKeys();
        loadCommandCenter().then(() => ccStartLiveRefresh()).catch((e) => console.warn("command center load failed", e));
      }

      async function boot() {
        updateTaskHeader([]);
        bindStockContextModal();
        bindKlineInteractions();
        setupPaperOrderDialog();
        setupDrawers();
        $("#refreshBtn").addEventListener("click", () => {
          refreshCurrentView().catch((error) => {
            $("#refreshMeta").textContent = "刷新失败";
            alert(error.message);
          });
        });
        const dashboardPages = ["overview", "workbench", "reports", "features", "opportunities"];
        if (dashboardPages.includes(page)) {
          const data = await loadDashboard();
          renderDashboardPage(data);
        }
        if (page === "patterns") {
          $("#refreshMeta").textContent = "形态检索";
          setupPatterns();
        }
        if (page === "settings") {
          $("#refreshMeta").textContent = "后台配置";
          setupSettings();
        }
        if (page === "watchlist") {
          $("#refreshMeta").textContent = "自选股";
          setupWatchlistPage();
        }
        if (page === "capital_rankings") {
          $("#refreshMeta").textContent = "资金榜单";
          setupCapitalRankings();
        }
        if (page === "paper_trading") {
          $("#refreshMeta").textContent = "模拟盘";
          setupPaperTrading();
        }
        if (page === "command_center") {
          $("#refreshMeta").textContent = "风险·机遇";
          setupCommandCenter();
        }
        if (!dashboardPages.includes(page)) {
          loadJobs().catch((error) => {
            $("#activeTaskMeta").textContent = `任务读取失败: ${error.message}`;
          });
        }
        startNotifyBar().catch((error) => console.warn("热点条启动失败", error));
        // 盘中每 30s 自动刷新当前K线（叠加实时价）；非交易时段 refreshKlineLive 自身会跳过。
        if (state.klineLiveTimer) clearInterval(state.klineLiveTimer);
        state.klineLiveTimer = setInterval(() => { refreshKlineLive().catch(() => {}); }, 30000);
      }

      boot().catch((error) => {
        $("#refreshMeta").textContent = "加载失败";
        console.error(error);
        alert(error.message);
      });

      // ── 文件预览 modal ──────────────────────────────────────────────
      async function openFilePreview(url, label) {
        if (!url) return;
        const modal = $("#filePreviewModal");
        const body  = $("#filePreviewBody");
        const title = $("#filePreviewTitle");
        const meta  = $("#filePreviewMeta");
        const openBtn = $("#filePreviewOpenBtn");

        title.textContent = label || "预览";
        meta.textContent  = url;
        openBtn.href      = url;
        body.innerHTML    = `<div class="stock-context-loading">加载中…</div>`;
        modal.hidden      = false;
        modal.setAttribute("aria-hidden", "false");

        const ext = url.split("?")[0].split(".").pop().toLowerCase();
        const fileName = url.split("?")[0].split("/").pop() || "";
        const isOppReport = /^opportunity_top10_\d{8}_\d{6}\.md$/.test(fileName);
        try {
          if (isOppReport) {
            // 机会挖掘报告：拉取结构化卡片，渲染成与 markdown 报告同款的富卡片
            const oppRes = await fetch(`/api/opportunity-report?file=${encodeURIComponent(fileName)}`);
            if (!oppRes.ok) throw new Error(`HTTP ${oppRes.status}`);
            const payload = await oppRes.json();
            title.textContent = "机会分析结果 · 同款卡片";
            meta.textContent = `${payload.file || fileName} · 更新 ${payload.updated_at || "--"} · 共 ${(payload.cards || []).length} 只`;
            body.innerHTML = renderOpportunityReportCards(payload);
            return;
          }
          const res = await fetch(url);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);

          if (ext === "html") {
            const blob = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            body.innerHTML = `<iframe src="${blobUrl}" style="width:100%;height:70vh;border:none;border-radius:6px;"></iframe>`;
          } else if (ext === "md") {
            const text = await res.text();
            body.innerHTML = `<div class="file-preview-md">${renderMarkdown(text)}</div>`;
          } else if (ext === "csv") {
            const text = await res.text();
            body.innerHTML = renderCsvTable(text);
          } else if (ext === "json") {
            const text = await res.text();
            body.innerHTML = `<pre style="white-space:pre-wrap;word-break:break-all;font-size:0.8rem;">${html(text)}</pre>`;
          } else {
            // fallback: iframe
            body.innerHTML = `<iframe src="${html(url)}" style="width:100%;height:70vh;border:none;border-radius:6px;"></iframe>`;
          }
        } catch (err) {
          body.innerHTML = `<div class="notice status error">加载失败：${html(err.message)}</div>`;
        }
      }

      function renderOpportunityReportCards(payload) {
        const cards = (payload && payload.cards) || [];
        const env = payload && payload.market_env
          ? `<p class="notice" style="margin:0 0 12px;">${html(payload.market_env)}</p>`
          : "";
        if (!cards.length) {
          return env + `<div class="notice status">该报告未解析到个股卡片（可能是长文/降级报告）。</div>`;
        }
        const ratingColor = (r) => ({ S: "#c62828", "A+": "#e65100", A: "#ef6c00", B: "#1565c0", C: "#607d8b" }[r] || "#37474f");
        const cardsHtml = cards.map((c) => {
          const code = c.code || c.stock_code || "";
          const name = c.name || c.stock_name || code;
          const fields = (c.fields || []).map((f) =>
            `<li style="display:flex;gap:8px;padding:3px 0;border-bottom:1px dashed rgba(0,0,0,0.06);">
               <span style="flex:0 0 68px;color:#78909c;font-weight:600;">${html(f.label)}</span>
               <span style="flex:1;color:#37474f;">${html(f.value)}</span>
             </li>`
          ).join("");
          const rating = c.rating
            ? `<span class="pill" style="background:${ratingColor(c.rating)};color:#fff;">${html(c.rating)}级</span>`
            : "";
          return `<article class="oppcard" data-stock="${html(code)}" data-stock-code="${html(code)}" data-stock-name="${html(name)}" data-kline-target="${html(code)}"
              style="border:1px solid rgba(0,0,0,0.08);border-radius:10px;padding:14px 16px;margin-bottom:12px;background:#fff;cursor:pointer;">
            <header style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px;">
              <div><strong style="font-size:1.02rem;">#${c.rank} ${html(name)}</strong>
                <span class="item-meta" style="margin-left:6px;">${html(code)}</span></div>
              <div style="display:flex;align-items:center;gap:8px;white-space:nowrap;">
                <strong style="font-size:1.15rem;color:${ratingColor(c.rating)};">${num(c.score)}</strong>${rating}</div>
            </header>
            ${c.recommendation ? `<p style="margin:0 0 8px;color:#546e7a;">建议：${html(c.recommendation)}</p>` : ""}
            <ul style="list-style:none;margin:0;padding:0;font-size:0.86rem;">${fields}</ul>
            <footer style="margin-top:10px;display:flex;justify-content:flex-end;">
              <button class="button compact" type="button" data-buy-pool="${html(code)}" data-buy-name="${html(name)}">＋ 加入买入池</button>
            </footer>
          </article>`;
        }).join("");
        return env + `<div class="oppcard-list">${cardsHtml}</div>`;
      }

      function renderMarkdown(text) {
        // minimal md→html: headers, bold, code blocks, line breaks
        return text
          .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/^#{3}\s+(.+)$/gm, "<h3>$1</h3>")
          .replace(/^#{2}\s+(.+)$/gm, "<h2>$1</h2>")
          .replace(/^#{1}\s+(.+)$/gm, "<h1>$1</h1>")
          .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(/```[\s\S]*?```/g, (m) => `<pre><code>${m.slice(3, -3).replace(/^[^\n]*\n/, "")}</code></pre>`)
          .replace(/\n\n/g, "</p><p>")
          .replace(/\n/g, "<br>");
      }

      function renderCsvTable(text) {
        const lines = text.trim().split("\n").slice(0, 500);
        if (!lines.length) return "<p>空文件</p>";
        const parse = (line) => line.split(",").map((c) => c.replace(/^"|"$/g, "").trim());
        const headers = parse(lines[0]);
        const rows = lines.slice(1).map(parse);
        const th = headers.map((h) => `<th>${html(h)}</th>`).join("");
        const tr = rows.map((r) => `<tr>${r.map((c) => `<td>${html(c)}</td>`).join("")}</tr>`).join("");
        return `<div style="overflow:auto;max-height:70vh;"><table class="csv-preview-table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
      }

      (function initFilePreviewModal() {
        document.addEventListener("keydown", (e) => {
          if (e.key === "Escape" && !$("#filePreviewModal").hidden) closeFilePreview();
        });
        $("#closeFilePreviewBtn").addEventListener("click", closeFilePreview);
        $("#filePreviewModal").addEventListener("click", (e) => {
          if (e.target === e.currentTarget) closeFilePreview();
        });
      })();

      function closeFilePreview() {
        const modal = $("#filePreviewModal");
        modal.hidden = true;
        modal.setAttribute("aria-hidden", "true");
        $("#filePreviewBody").innerHTML = "";
      }

      // 合规：首次启动展示风险提示，须点「我已知晓风险」方可进入（localStorage 记住，之后不再弹）
      (function initRiskDisclaimer() {
        const KEY = "kronos_risk_ack_v1";
        const modal = $("#riskDisclaimerModal");
        if (!modal) return;
        let acked = false;
        try { acked = localStorage.getItem(KEY) === "1"; } catch (e) { acked = false; }
        if (!acked) {
          modal.hidden = false;
          modal.setAttribute("aria-hidden", "false");
        }
        const ackBtn = $("#riskDisclaimerAckBtn");
        if (ackBtn) {
          ackBtn.addEventListener("click", () => {
            try { localStorage.setItem(KEY, "1"); } catch (e) {}
            modal.hidden = true;
            modal.setAttribute("aria-hidden", "true");
          });
        }
        // 故意不支持点背景/Esc 关闭：必须显式确认
      })();
