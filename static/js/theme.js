/**
 * テーマ切替制御モジュール (static/js/theme.js)
 * OSシステムデフォルト (prefers-color-scheme) 追従および手動切替を管理し、localStorage へ保存する。
 */
(function (global) {
  const STORAGE_KEY = "vte_webui_theme";
  const listeners = [];

  function applyTheme(mode) {
    const valid = ["system", "light", "dark"].includes(mode) ? mode : "system";
    document.documentElement.setAttribute("data-theme", valid);
    try {
      localStorage.setItem(STORAGE_KEY, valid);
    } catch (_) {
      // ignore storage quota errors
    }

    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.themeSet === valid);
    });

    listeners.forEach((fn) => {
      try {
        fn(valid);
      } catch (_) {}
    });
  }

  function initTheme() {
    let initial = "system";
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && ["system", "light", "dark"].includes(saved)) {
        initial = saved;
      }
    } catch (_) {}

    applyTheme(initial);

    document.querySelectorAll(".theme-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        applyTheme(btn.dataset.themeSet || "system");
      });
    });

    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const handler = () => {
        if (document.documentElement.getAttribute("data-theme") === "system") {
          listeners.forEach((fn) => {
            try {
              fn("system");
            } catch (_) {}
          });
        }
      };
      if (mq.addEventListener) {
        mq.addEventListener("change", handler);
      } else if (mq.addListener) {
        mq.addListener(handler);
      }
    }
  }

  function onThemeChange(callback) {
    if (typeof callback === "function") {
      listeners.push(callback);
    }
  }

  global.AppTheme = {
    initTheme,
    applyTheme,
    onThemeChange,
  };
})(window);
