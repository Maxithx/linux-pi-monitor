// static/js/glances.service.js
// Adds a lightweight "Glances systemd" dropdown (Start/Stop/Status)
// and a safe View Log fallback (when GlancesUI from glances.install.js is absent).

(function () {
    function $(id) { return document.getElementById(id); }
    function show(el) { if (el) el.style.display = 'block'; }
    function hide(el) { if (el) el.style.display = 'none'; }
    function setDisabled(el, state) { if (el) el.disabled = !!state; }

    const outSvc = $("glances-service-output");
    const outLog = $("glances-output");

    // -------- Systemd dropdown controls --------
    const btnSysd = $("glances-systemd-btn");
    const menuSysd = $("glances-systemd-menu");

    function appendLine(el, line) {
        if (!el) return;
        show(el);
        el.textContent = (el.textContent ? el.textContent + "\n" : "") + line;
        el.scrollTop = el.scrollHeight;
    }

    async function callJSON(url, method = "GET", body) {
        const opts = { method, headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        const resp = await fetch(url, opts);
        const ct = (resp.headers.get("content-type") || "").toLowerCase();
        if (ct.includes("application/json")) return await resp.json();
        return await resp.text();
    }

    function toggleMenu() {
        if (!menuSysd) return;
        menuSysd.style.display = (menuSysd.style.display === "block" ? "none" : "block");
    }

    function closeOnOutsideClick(e) {
        if (!menuSysd || !btnSysd) return;
        if (!menuSysd.contains(e.target) && e.target !== btnSysd) {
            hide(menuSysd);
        }
    }

    async function doSystemdAction(action) {
        hide(menuSysd);
        if (!outSvc) return;

        // Optional sudo password prompt for start/stop (works with NOPASSWD if blank)
        let sudo_pw = null;
        if (action === "start" || action === "stop") {
            sudo_pw = window.prompt("Sudo password (leave blank if NOPASSWD configured):", "") || null;
        }

        appendLine(outSvc, `> glances ${action}…`);
        try {
            if (action === "start") {
                const res = await callJSON("/glances/service/start", "POST", sudo_pw ? { sudo_pw } : {});
                appendLine(outSvc, JSON.stringify(res, null, 2));
            } else if (action === "stop") {
                const res = await callJSON("/glances/service/stop", "POST", sudo_pw ? { sudo_pw } : {});
                appendLine(outSvc, JSON.stringify(res, null, 2));
            } else if (action === "status") {
                const st = await callJSON("/glances/status");
                appendLine(outSvc, JSON.stringify(st, null, 2));
            } else {
                appendLine(outSvc, "Unknown action.");
            }
        } catch (e) {
            appendLine(outSvc, "Error: " + (e && e.message ? e.message : e));
        }
    }

    // Bind dropdown open/close
    if (btnSysd && !btnSysd.dataset.bound) {
        btnSysd.dataset.bound = "1";
        btnSysd.addEventListener("click", toggleMenu);
        document.addEventListener("click", closeOnOutsideClick);
    }
    if (menuSysd && !menuSysd.dataset.bound) {
        menuSysd.dataset.bound = "1";
        menuSysd.addEventListener("click", (ev) => {
            const target = ev.target.closest(".menu-item");
            if (!target) return;
            const action = target.getAttribute("data-action");
            doSystemdAction(action);
        });
    }

    // -------- View Glances log (fallback only) --------
    // If glances.install.js exposes GlancesUI, that file already wires log/status.
    if (!window.GlancesUI) {
        const btnViewLog = $("view-glances-log-btn");

        async function fetchLogOnce() {
            if (!outLog) return;
            try {
                setDisabled(btnViewLog, true);
                show(outLog);
                outLog.textContent = "Fetching Glances log…";
                const resp = await fetch("/glances/log", { cache: "no-store" });
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                const text = await resp.text();
                outLog.textContent = text || "No log available.";
                outLog.scrollTop = outLog.scrollHeight;
            } catch (e) {
                outLog.textContent = "Failed to load log: " + (e && e.message ? e.message : e);
            } finally {
                setDisabled(btnViewLog, false);
            }
        }

        if (btnViewLog && btnViewLog.dataset.bound !== "1") {
            btnViewLog.dataset.bound = "1";
            btnViewLog.addEventListener("click", fetchLogOnce);
        }
    }
})();
