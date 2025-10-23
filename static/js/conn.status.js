// static/js/conn.status.js
(() => {
  "use strict";

  const box  = document.getElementById("global-conn");
  const dot  = document.getElementById("gc-dot");
  const text = document.getElementById("gc-text");
  const spin = document.getElementById("gc-spin");

  if (!box || !dot || !text) return;

  function paint(state) {
    // state: "checking" | "ok" | "down" | "not_configured"
    dot.classList.remove("gc-green", "gc-red");
    spin.style.display = "none";

    // Do not show a visible 'checking' state during background polling
    if (state === "checking") {
      return;
    }
    if (state === "ok") {
      dot.classList.add("gc-green");
      text.textContent = "Connected to Linux";
      return;
    }
    if (state === "not_configured") {
      dot.classList.add("gc-red");
      text.textContent = "Not configured";
      return;
    }
    // default: down
    dot.classList.add("gc-red");
    text.textContent = "Disconnected";
  }

  async function checkOnce() {
    try {
      // Silent background check without changing current text
      const r = await fetch("/check-ssh-status", { method: "GET", cache: "no-store" });
      const t = await r.text();
      let data;
      try { data = JSON.parse(t); } catch { data = { ok:false, reason:"parse_error" }; }

      if (data && data.ok && data.connected) {
        paint("ok");
      } else if (data && data.reason === "not_configured") {
        paint("not_configured");
      } else {
        paint("down");
      }
    } catch {
      paint("down");
    }
  }

  // initial and polling
  checkOnce();
  const POLL_MS = 10000; // 10s
  setInterval(checkOnce, POLL_MS);

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) checkOnce();
  });
  window.addEventListener("online", checkOnce);
  window.addEventListener("offline", () => paint("down"));
})();
