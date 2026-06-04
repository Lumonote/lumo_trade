      const page = document.body.dataset.page;
      const $ = (selector) => document.querySelector(selector);
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
        lastQueryParams: null,
        lastMatchSnapshot: null,
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
        }
      }

      async function refreshCurrentView() {
        const button = $("#refreshBtn");
        if (button) button.disabled = true;
        try {
          if (["overview", "workbench", "reports", "features"].includes(page)) {
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
        openStockKlineModal(code).catch((error) => alert(error.message));
      });

      document.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const target = event.target.closest?.("[data-kline-target]");
        if (!target) return;
        if (event.target.closest("a, button, input, textarea, select")) return;
        const code = normalizeStockCode(target.dataset.klineTarget);
        if (!code) return;
        event.preventDefault();
        openStockKlineModal(code).catch((error) => alert(error.message));
      });

      function klineTargetAttr(code, name = "") {
        const normalized = normalizeStockCode(code);
        if (!normalized) return "";
        const tip = name ? `${name} ${normalized} 点击查看K线大图` : `${normalized} 点击查看K线大图`;
        return `data-kline-target="${html(normalized)}" role="button" tabindex="0" title="${html(tip)}"`;
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
            openStockKlineModal(el.dataset.stockCode).catch((error) => alert(error.message));
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

      function renderOpportunities(data) {
        const opportunity = data.opportunity || {};
        $("#opportunityMeta").textContent = opportunity.latest_report?.updated_at || "--";
        const items = opportunity.items || [];
        const list = $("#opportunityList");
        list.innerHTML = items.map((item, index) => {
          const code = stockCodeFromItem(item);
          return `<button class="item" type="button" data-stock="${html(code)}" data-stock-code="${html(code)}" data-stock-name="${html(item.stock_name || item.name || "")}" data-sector="${html(item.sector || item.industry || "")}">
            <div class="item-top">
              <p class="item-title">${index + 1}. ${html(item.stock_name || item.name || code)}</p>
              <strong>${num(item.score)}</strong>
            </div>
            <p class="item-meta">${html(code)} · ${html(item.reason || item.summary || item.industry || "点击查看K线")}</p>
          </button>`;
        }).join("");
        if (!items.length) {
          empty(list, "还没有机会报告。", emptyAction("start-opportunity", "启动机会挖掘"));
        }
        list.querySelectorAll("[data-stock]").forEach((el) => {
          el.addEventListener("click", async () => {
            loadKline(el.dataset.stock);
            await openStockContext(stockTargetFromDataset(el.dataset));
          });
          el.addEventListener("dblclick", (event) => {
            event.preventDefault();
            openStockKlineModal(el.dataset.stock).catch((error) => alert(error.message));
          });
        });

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
          loadKline(firstCode);
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
        let data;
        try {
          data = await fetchKlineData(code, 500);
        } catch (_e) {
          return; // 盘中拉取失败静默跳过，下个周期再试
        }
        if (!data.records?.length) return;
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

      async function loadKline(code) {
        if (!code) return;
        const chart = $("#klineChart");
        const title = $("#klineTitle");
        const meta = $("#klineMeta");
        if (title) title.textContent = `${code} K线`;
        if (meta) meta.textContent = "读取中...";
        const openButton = $("#openKlineModalBtn");
        if (openButton) openButton.disabled = true;
        try {
          const data = await fetchKlineData(code, 500);
          const records = data.records || [];
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

      async function openStockKlineModal(code, limit = 240) {
        if (!code) return;
        const normalizedCode = String(code || "").trim().padStart(6, "0");
        const data = await fetchKlineData(normalizedCode, 500);
        if (!data.records?.length) {
          alert(data.message || "暂无K线数据");
          return;
        }
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
        return {
          margin: mode === "modal" ? { l: 62, r: 26, t: 36, b: 42 } : { l: 44, r: 12, t: 24, b: 28 },
          paper_bgcolor: "transparent",
          plot_bgcolor: "#ffffff",
          showlegend: true,
          legend: {
            orientation: "h",
            x: 0,
            y: mode === "modal" ? 1.08 : 1.12,
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
            y: mode === "modal" ? 1.05 : 1.08,
            showarrow: false,
            align: "left",
            text: `${html(data.code || "")} · ${firstDate} - ${lastDate} · 高 ${stats.high} 低 ${stats.low} · 区间 ${stats.delta}%`,
            font: { size: 11, color: "#6b778a" },
          }],
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
          button.addEventListener("click", () => {
            openKlineModal(Number(button.dataset.klineRange || 240));
          });
        });

        const opportunityButton = $("#klineOpportunityBtn");
        if (opportunityButton && !opportunityButton.dataset.bound) {
          opportunityButton.dataset.bound = "1";
          opportunityButton.addEventListener("click", () => {
            const context = state.klineModalContext;
            if (context) startStockOpportunity(context, opportunityButton).catch((error) => alert(error.message));
          });
        }

        const analysisButton = $("#klineAnalysisBtn");
        if (analysisButton && !analysisButton.dataset.bound) {
          analysisButton.dataset.bound = "1";
          analysisButton.addEventListener("click", () => {
            const context = state.klineModalContext;
            if (context) startStockAnalysis(context, analysisButton).catch((error) => alert(error.message));
          });
        }

        const tradingButton = $("#klineTradingBtn");
        if (tradingButton && !tradingButton.dataset.bound) {
          tradingButton.dataset.bound = "1";
          tradingButton.addEventListener("click", () => {
            const context = state.klineModalContext;
            const firstClient = context?.trading_clients?.clients?.[0];
            if (context && firstClient) openTradingClientFromContext(context, firstClient.id, tradingButton);
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
        $("#klineTradingBtn").disabled = !clients.length;
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
        $("#klineOpportunityBtn").disabled = true;
        $("#klineAnalysisBtn").disabled = true;
        $("#klineTradingBtn").disabled = true;
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

      function openKlineModal(limit = 240) {
        if (!state.currentKline) return;
        state.klineModalLimit = limit;
        closeOtherStockModals("#klineModal");
        const modal = $("#klineModal");
        modal.hidden = false;
        modal.setAttribute("aria-hidden", "false");
        syncModalOpenState();
        $("#klineModalTitle").textContent = `${state.currentKline.name || ""} ${state.currentKline.code || ""} 股票K线与分析`;
        $("#klineModalMeta").textContent = `${state.currentKline.source || "--"} · ${state.currentKline.records?.length || 0} 条 · ${klineAxisTitle(limit)}${klineQuoteText(state.currentKline)}`;
        $("#klineModalSource").textContent = state.currentKline.source || "--";
        const records = limit >= 500 ? (state.currentKline.records || []) : (state.currentKline.records || []).slice(-limit);
        const stats = klineStats(records);
        $("#klineModalRange").textContent = `区间 ${stats.delta}% · 高 ${stats.high} / 低 ${stats.low}`;
        $("#klineModalVolume").textContent = `均量 ${stats.volume}`;
        loadKlineModalContext();
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
        if (result.report_url) links.push(`<button class="button secondary" type="button" data-preview-url="${html(result.report_url)}" data-preview-label="报告">打开报告</button>`);
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
        if (job?.type === "opportunity_discovery" && result.report_path) return `报告已生成：${result.report_path}`;
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

      async function refreshVisibleResultsAfterJob(job) {
        if (job?.status !== "finished") return;
        if (!["opportunity_discovery", "batch_analysis"].includes(job.type)) return;
        try {
          const data = await loadDashboard();
          if ($("#opportunityList")) renderOpportunities(data);
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
          limit: 20,
          workers: 4,
          source: "multi",
          stock_codes: code,
        }, button);
        if (!job) return;
        if (panel) {
          panel.innerHTML = `<div class="item empty-state" id="stockOpportunityProgress">
            <p class="item-meta"><span class="spinner"></span> 机会挖掘进行中… (${html(job.id)})</p>
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
            if (action === "kline") openStockKlineModal(context.stock?.code).catch((error) => alert(error.message));
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
      // 渲染在「综合总览」tab 顶部。无 LLM、无后端改动——全部字段取自 payload 各维度。
      function suiteSummaryNum(v, fallback = 0) {
        const n = Number(v);
        return (v == null || isNaN(n)) ? fallback : n;
      }
      function suiteSummaryFmt(v, suffix = "") {
        if (v == null || v === "" || (typeof v === "number" && isNaN(v))) return "—";
        return `${v}${suffix}`;
      }

      function buildSummaryVerdict(ov, payload, consensus) {
        const radar = ov.radar || {};
        const prob = ov.scenario_probability || {};
        const scores = ["main_force_phase", "market_cycle", "volume_price_game", "chip_structure", "performance", "control_degree", "quant_activity"]
          .map((k) => radar[k]?.score).filter((v) => v != null && !isNaN(Number(v))).map(Number);
        const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
        const cScore = (consensus && consensus.score != null && !isNaN(Number(consensus.score))) ? Number(consensus.score) : null;
        const bull = prob.bullish, bear = prob.bearish;
        const probLean = (bull != null && bear != null) ? Number(bull) - Number(bear) : null;

        // 复合打分 → 多空倾向（A股惯例：偏多=红色）
        let pts = 0;
        if (cScore != null) { if (cScore >= 55) pts++; else if (cScore <= 45) pts--; }
        if (probLean != null) { if (probLean >= 10) pts++; else if (probLean <= -10) pts--; }
        if (avg != null) { if (avg >= 60) pts++; else if (avg < 45) pts--; }

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
          if (qact.score != null) parts.push(`量化活跃度 ${fmt(qact.score)}`);
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
        const payload = formEl ? Object.fromEntries(new FormData(formEl).entries()) : {
          limit: 80,
          workers: 8,
          source: "multi",
          stock_codes: "",
        };
        payload.limit = Number(payload.limit || 80);
        payload.workers = Number(payload.workers || 8);
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
            openStockKlineModal(item?.stock_code || el.dataset.stockCode).catch((error) => alert(error.message));
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
              openStockKlineModal(el.dataset.stockCode).catch((error) => alert(error.message));
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
        renderOpportunities(data);
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
        $("#featureConfigStatus").textContent = llmReady && tushareReady ? "已配置" : "待配置";
        $("#featureSettingsSummary").textContent = `AI ${llmReady ? "已配置" : "未配置"} · TuShare ${tushareReady ? "已配置 " + (settings.tushare?.token_masked || "") : "未配置"}`;

        loadPatternStatus().catch((error) => {
          const target = $("#featurePatternStatus");
          if (target) {
            target.className = "notice status error";
            target.textContent = error.message;
          }
        });
        const patternBtn = $("#featureRefreshPatternDbBtn");
        if (patternBtn && !patternBtn.dataset.bound) {
          patternBtn.dataset.bound = "1";
          patternBtn.addEventListener("click", () => {
            refreshPatternDatabase({ button: patternBtn, statusEl: $("#featurePatternStatus") });
          });
        }
        setupKronosModelControls();
        loadKronosStatus().catch((error) => {
          $("#kronosModelMeta").textContent = "读取失败";
          $("#kronosModelStatus").className = "notice status error";
          $("#kronosModelStatus").textContent = error.message;
        });
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

      async function loadSettings() {
        const settings = await fetchJson("/api/settings");
        $("#llmProviderList").innerHTML = providerModelRows(settings);
        $("#llmConfigMeta").textContent = settings.llm?.configured ? "已配置" : "未配置";
        $("#llmConfigPath").textContent = `保存位置：${settings.llm?.config_path || "--"}`;
        $("#tushareConfigMeta").textContent = settings.tushare?.configured ? `已配置 ${settings.tushare.token_masked}` : "未配置";
        $("#tushareConfigPath").textContent = `保存位置：${settings.tushare?.config_path || "--"}`;
        $("#tushareSettingsForm [name='timeout']").value = settings.tushare?.timeout || 30;
        $("#tushareSettingsForm [name='retry_count']").value = settings.tushare?.retry_count || 3;
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
          const form = new FormData(event.currentTarget);
          const payload = Object.fromEntries(form.entries());
          payload.timeout = Number(payload.timeout);
          payload.retry_count = Number(payload.retry_count);
          payload.clear_token = payload.clear_token === "1";
          try {
            const data = await fetchJson("/api/settings/tushare", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            $("#tushareConfigMeta").textContent = data.settings.tushare?.configured ? `已保存 ${data.settings.tushare.token_masked}` : "未配置";
            event.currentTarget.elements.token.value = "";
          } catch (error) {
            alert(error.message);
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
      const NOTIFY_CAT_LABEL = { hot: "热点", changes: "异动", watchlist: "自选", boards: "板块", flash: "快讯" };
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
          return `<div class="ndc-head">金十快讯${it.important ? " · <span class=\"ndc-warn\">重要</span>" : ""}</div>
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
        ]);
        renderNotifyBar();
      }
      async function startNotifyBar() {
        const bar = $("#notifyBar");
        if (!bar) return;
        const savedCats = (lsGet("kronos_notify_cats2") || "").split(",").map((s) => s.trim()).filter(Boolean);
        const valid = savedCats.filter((c) => NOTIFY_CAT_LABEL[c]);
        state.notifyCats = new Set(valid.length ? valid : ["hot", "changes", "watchlist"]);
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

      async function boot() {
        updateTaskHeader([]);
        bindStockContextModal();
        setupDrawers();
        $("#refreshBtn").addEventListener("click", () => {
          refreshCurrentView().catch((error) => {
            $("#refreshMeta").textContent = "刷新失败";
            alert(error.message);
          });
        });
        const dashboardPages = ["overview", "workbench", "reports", "features"];
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
        try {
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
