(function () {
  const shell = document.getElementById("appShell");
  const content = document.querySelector(".content");
  const sidebarBtn = document.getElementById("sidebarToggleBtn");
  const fullscreenBtn = document.getElementById("workspaceFullscreenBtn");

  if (!shell || !content) {
    return;
  }

  const storedCollapsed = localStorage.getItem("kronos.sidebarCollapsed") === "1";
  if (storedCollapsed) {
    shell.classList.add("nav-collapsed");
    if (sidebarBtn) sidebarBtn.textContent = "展开";
  }

  if (sidebarBtn) {
    sidebarBtn.addEventListener("click", () => {
      const collapsed = shell.classList.toggle("nav-collapsed");
      localStorage.setItem("kronos.sidebarCollapsed", collapsed ? "1" : "0");
      sidebarBtn.textContent = collapsed ? "展开" : "菜单";
    });
  }

  function setWorkspaceExpanded(expanded) {
    shell.classList.toggle("workspace-expanded", expanded);
    if (fullscreenBtn) fullscreenBtn.textContent = expanded ? "退出" : "全屏";
  }

  async function enterFullscreen() {
    setWorkspaceExpanded(true);
    if (content.requestFullscreen && !document.fullscreenElement) {
      try {
        await content.requestFullscreen();
      } catch (error) {
        // Some desktop webviews disallow Fullscreen API; the layout expansion is enough.
      }
    }
  }

  async function exitFullscreen() {
    if (document.fullscreenElement && document.exitFullscreen) {
      try {
        await document.exitFullscreen();
      } catch (error) {
        // Keep the CSS fallback in sync below.
      }
    }
    setWorkspaceExpanded(false);
  }

  if (fullscreenBtn) {
    fullscreenBtn.addEventListener("click", () => {
      if (shell.classList.contains("workspace-expanded") || document.fullscreenElement) {
        exitFullscreen();
      } else {
        enterFullscreen();
      }
    });
  }

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement) {
      setWorkspaceExpanded(false);
    }
  });
})();
