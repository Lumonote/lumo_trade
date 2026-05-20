(() => {
  const MENU_ID = "kronosTradingClientContextMenu";
  const STYLE_ID = "kronosTradingClientContextStyle";
  const TARGET_SELECTOR = [
    "[data-stock-code]",
    "[data-stock]",
    "[data-board-code]",
    "[data-board-name]",
    "[data-board]",
    "[data-sector]",
    "[data-sector-name]",
    "[data-code]",
  ].join(",");

  let clientsCache = null;
  let clientsCacheAt = 0;

  function text(value) {
    return String(value ?? "").trim();
  }

  function normalizeStockCode(value) {
    const raw = text(value).toUpperCase();
    if (!raw) return "";
    const stripped = raw.replace(/^(SH|SZ|BJ)/, "").replace(/\.(SH|SZ|BJ)$/, "");
    const match = stripped.match(/\d{6}/);
    return match ? match[0] : "";
  }

  function normalizeBoardCode(value) {
    const match = text(value).toUpperCase().match(/BK\d{4,6}/);
    return match ? match[0] : "";
  }

  function inferLabel(node, selectors) {
    for (const selector of selectors) {
      const found = node.querySelector?.(selector);
      if (found?.textContent) return text(found.textContent).replace(/\s+/g, " ");
    }
    return "";
  }

  function readTarget(node) {
    const dataset = node.dataset || {};
    const dataCode = text(dataset.code);
    const stockCode = normalizeStockCode(dataset.stockCode || dataset.stock || dataCode);
    const stockName = text(dataset.stockName || dataset.name) || inferLabel(node, [
      ".item-title",
      ".stock-title",
      ".list-title",
      ".hot-name",
      ".pattern-stock-name",
    ]);
    const boardCode = normalizeBoardCode(
      dataset.boardCode || (!stockCode ? dataCode : ""),
    );
    const boardName = text(
      dataset.boardName ||
      dataset.board ||
      dataset.sector ||
      dataset.sectorName ||
      dataset.industry,
    );

    if (stockCode) {
      return {
        type: "stock",
        stock_code: stockCode,
        stock_name: stockName,
        board_code: boardCode,
        board_name: boardName,
        title: `${stockName || "股票"} ${stockCode}`,
        subtitle: boardName ? `关联板块：${boardName}` : "",
      };
    }
    if (boardName || boardCode) {
      return {
        type: "board",
        board_code: boardCode,
        board_name: boardName,
        title: `${boardName || "板块"}${boardCode ? ` ${boardCode}` : ""}`,
        subtitle: "板块/主题跳转",
      };
    }
    return null;
  }

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .k-trading-menu {
        position: fixed;
        z-index: 100000;
        min-width: 250px;
        max-width: min(340px, calc(100vw - 16px));
        padding: 8px;
        border: 1px solid rgba(15, 23, 42, 0.12);
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.98);
        box-shadow: 0 18px 42px rgba(15, 23, 42, 0.18);
        color: #172033;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
        letter-spacing: 0;
      }
      .k-trading-menu[hidden] { display: none !important; }
      .k-trading-menu-head {
        padding: 7px 9px 8px;
        border-bottom: 1px solid #e6edf4;
      }
      .k-trading-menu-title {
        margin: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 13px;
        font-weight: 700;
      }
      .k-trading-menu-subtitle,
      .k-trading-menu-empty {
        margin: 4px 0 0;
        color: #667789;
        font-size: 12px;
      }
      .k-trading-menu-empty {
        padding: 11px 9px 7px;
        line-height: 1.6;
      }
      .k-trading-menu-group {
        margin: 8px 8px 4px;
        color: #7a8795;
        font-size: 11px;
        font-weight: 700;
      }
      .k-trading-menu button {
        width: 100%;
        min-height: 40px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        padding: 8px 9px;
        border: 0;
        border-radius: 7px;
        background: transparent;
        color: inherit;
        cursor: pointer;
        text-align: left;
      }
      .k-trading-menu button:hover,
      .k-trading-menu button:focus-visible {
        outline: 0;
        background: #eef6ff;
      }
      .k-trading-menu button[disabled] {
        cursor: wait;
        opacity: 0.65;
      }
      .k-trading-menu-label {
        font-size: 13px;
        font-weight: 650;
      }
      .k-trading-menu-meta {
        max-width: 130px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #667789;
        font-size: 12px;
      }
    `;
    document.head.appendChild(style);
  }

  function ensureMenu() {
    injectStyle();
    let menu = document.getElementById(MENU_ID);
    if (menu) return menu;
    menu = document.createElement("div");
    menu.id = MENU_ID;
    menu.className = "k-trading-menu";
    menu.hidden = true;
    menu.addEventListener("click", (event) => event.stopPropagation());
    menu.addEventListener("contextmenu", (event) => event.preventDefault());
    document.body.appendChild(menu);
    return menu;
  }

  function hideMenu() {
    const menu = document.getElementById(MENU_ID);
    if (menu) menu.hidden = true;
  }

  async function loadClients() {
    const now = Date.now();
    if (clientsCache && now - clientsCacheAt < 30000) return clientsCache;
    const response = await fetch("/api/trading-clients");
    if (!response.ok) throw new Error("交易客户端发现失败");
    const payload = await response.json();
    clientsCache = payload.clients || [];
    clientsCacheAt = now;
    return clientsCache;
  }

  function supportedClients(clients, target) {
    return clients.filter((client) => {
      const caps = client.capabilities || {};
      return target.type === "stock" ? caps.stock : caps.board;
    });
  }

  function renderHead(menu, target) {
    const head = document.createElement("div");
    head.className = "k-trading-menu-head";
    const title = document.createElement("p");
    title.className = "k-trading-menu-title";
    title.textContent = target.title;
    head.appendChild(title);
    if (target.subtitle) {
      const subtitle = document.createElement("p");
      subtitle.className = "k-trading-menu-subtitle";
      subtitle.textContent = target.subtitle;
      head.appendChild(subtitle);
    }
    menu.appendChild(head);
  }

  function renderEmpty(menu, message) {
    const empty = document.createElement("div");
    empty.className = "k-trading-menu-empty";
    empty.textContent = message;
    menu.appendChild(empty);
  }

  async function openClient(client, target, button) {
    const previous = button.querySelector(".k-trading-menu-meta")?.textContent || "";
    button.disabled = true;
    const meta = button.querySelector(".k-trading-menu-meta");
    if (meta) meta.textContent = "跳转中";
    try {
      const response = await fetch("/api/trading-clients/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: client.id, target }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.success === false) {
        throw new Error(payload.error || payload.message || "跳转失败");
      }
      hideMenu();
    } catch (error) {
      button.disabled = false;
      if (meta) meta.textContent = error.message || previous || "失败";
    }
  }

  async function renderClientActions(menu, target) {
    renderEmpty(menu, "正在查找可用交易客户端...");
    let clients = [];
    try {
      clients = supportedClients(await loadClients(), target);
    } catch (error) {
      menu.innerHTML = "";
      renderHead(menu, target);
      renderEmpty(menu, error.message);
      return;
    }

    menu.innerHTML = "";
    renderHead(menu, target);
    if (!clients.length) {
      renderEmpty(menu, "未发现支持当前标的跳转的桌面交易客户端。");
      return;
    }

    const group = document.createElement("div");
    group.className = "k-trading-menu-group";
    group.textContent = "交易客户端";
    menu.appendChild(group);

    for (const client of clients) {
      const button = document.createElement("button");
      button.type = "button";
      const label = document.createElement("span");
      label.className = "k-trading-menu-label";
      label.textContent = client.display_name || client.name || "交易客户端";
      const meta = document.createElement("span");
      meta.className = "k-trading-menu-meta";
      const directTargets = client.capabilities?.direct_targets || [];
      meta.textContent = directTargets.includes(target.type) ? "协议直连" : "客户端直达";
      button.append(label, meta);
      button.addEventListener("click", () => openClient(client, target, button));
      menu.appendChild(button);
    }
  }

  function placeMenu(menu, x, y) {
    menu.hidden = false;
    menu.style.visibility = "hidden";
    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    const rect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(x, window.innerWidth - rect.width - 8));
    const top = Math.max(8, Math.min(y, window.innerHeight - rect.height - 8));
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.style.visibility = "visible";
  }

  document.addEventListener("contextmenu", (event) => {
    const node = event.target.closest?.(TARGET_SELECTOR);
    if (!node) return;
    const target = readTarget(node);
    if (!target) return;

    event.preventDefault();
    event.stopPropagation();

    const menu = ensureMenu();
    menu.innerHTML = "";
    renderHead(menu, target);
    placeMenu(menu, event.clientX, event.clientY);
    renderClientActions(menu, target).finally(() => {
      placeMenu(menu, event.clientX, event.clientY);
    });
  });

  document.addEventListener("click", hideMenu);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideMenu();
  });
  window.addEventListener("scroll", hideMenu, true);
  window.addEventListener("resize", hideMenu);
  window.addEventListener("blur", hideMenu);
})();
