(function hookEvalComposer() {
  function emptyComposer() {
    const area = document.querySelector("textarea");
    return !area || !String(area.value || "").trim();
  }

  function submitComposer() {
    const send =
      document.querySelector('button[type="submit"]') ||
      document.querySelector('button[aria-label*="Send" i]');
    if (send && emptyComposer()) {
      send.click();
    }
  }

  function composerBar() {
    const area = document.querySelector("textarea");
    if (!area) {
      return null;
    }
    let node = area.parentElement;
    while (node && node !== document.body) {
      const style = window.getComputedStyle(node);
      if (style.position === "sticky" || style.position === "fixed") {
        return node;
      }
      node = node.parentElement;
    }
    return area.closest("form") || area.parentElement;
  }

  function pinDock() {
    const bar = composerBar();
    const height = bar ? bar.getBoundingClientRect().height : 88;
    const offset = Math.max(72, Math.round(height + 12));
    document.documentElement.style.setProperty("--eval-dock-bottom", `${offset}px`);
  }

  function bindEvalButton() {
    const buttons = document.querySelectorAll("button");
    buttons.forEach((button) => {
      const label = String(button.textContent || button.getAttribute("aria-label") || "").trim();
      if (label !== "Eval" || button.dataset.evalHooked === "1") {
        return;
      }
      if (button.closest("[data-eval-dock]")) {
        return;
      }
      button.dataset.evalHooked = "1";
      button.addEventListener("click", () => {
        window.setTimeout(submitComposer, 30);
      });
    });
  }

  function tick() {
    pinDock();
    bindEvalButton();
  }

  tick();
  window.addEventListener("resize", pinDock);
  window.setInterval(tick, 800);
})();
