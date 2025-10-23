// static/js/network_firewall.js
(() => {
  "use strict";

  // ---------- Utilities ----------
  const $ = (sel, root = document) => root.querySelector(sel);

  function escapeHtml(s) {
    if (!s && s !== 0) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function pill(text, tone = "neutral") {
    const colors = {
      neutral: "#334155",
      good: "#16a34a",
      bad: "#b91c1c",
      warn: "#ca8a04",
      info: "#0284c7",
    };
    const bg = colors[tone] || colors.neutral;
    return `<span style="display:inline-block;padding:2px 8px;border-radius:9999px;background:${bg};color:#fff;font-size:12px;line-height:18px;margin-right:6px">${escapeHtml(text)}</span>`;
  }

  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    const txt = await r.text();
    try { return JSON.parse(txt); } catch { return { ok: false, error: txt || "Bad response" }; }
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    const txt = await r.text();
    try { return JSON.parse(txt); } catch { return { ok: false, error: txt || "Bad response" }; }
  }

  function setHeader(framework, stateText, tone = "neutral") {
    const fwLbl = $("#fw-framework");
    const fwPill = $("#fw-pill");
    if (fwLbl) fwLbl.textContent = framework ? String(framework) : "";
    if (fwPill) fwPill.innerHTML = pill(stateText || "-", tone);
  }

  function setLog(text) {
    const el = $("#fw-log");
    if (!el) return;
    el.textContent = text || "";
    el.style.display = text ? "block" : "none";
  }

  function setAlert(text) {
    const el = $("#fw-alert");
    if (!el) return;
    el.textContent = text || "";
    el.style.display = text ? "block" : "none";
  }

  // ---------- Renderers ----------
  function renderNone(root, payload) {
    const cont = $("#fw-content", root);
    setHeader("none", "Unavailable", "warn");
    const msg = escapeHtml(
      (payload && payload.error) || "No supported firewall detected (UFW/Firewalld not present or inactive)."
    );
    cont.innerHTML = `
      <div class="card" style="padding:12px">
        <div style="color:#b91c1c">${msg}</div>
      </div>`;
  }

  function rulesListUfw(numbered) {
    if (!Array.isArray(numbered) || numbered.length === 0) {
      return `<div class="muted">No rules</div>`;
    }
    const items = numbered.map((line, idx) => {
      // Expect something like "[ 1] 22/tcp ALLOW ..."
      const m = String(line).match(/^\s*\[\s*(\d+)\s*\]/);
      const num = m ? m[1] : null;
      const safe = escapeHtml(line);
      const btn = num ? `<button class="btn btn-xs danger" data-rule-num="${num}" title="Delete rule #${num}">Delete</button>` : "";
      return `<div style="display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:1px solid rgba(148,163,184,.15);padding:6px 0">
        <code style="white-space:pre-wrap">${safe}</code>
        ${btn}
      </div>`;
    }).join("");
    return `<div>${items}</div>`;
  }

  function rulesTableUfw(rows) {
    if (!Array.isArray(rows) || rows.length === 0) return '';
    const head = `<div style="display:flex;font-weight:600;border-bottom:1px solid rgba(148,163,184,.25);padding:6px 0">
      <div style="flex:2">To</div>
      <div style="flex:1">Action</div>
      <div style="flex:2">From</div>
    </div>`;
    const body = rows.map(r => `<div style="display:flex;border-bottom:1px solid rgba(148,163,184,.15);padding:6px 0">
      <div style="flex:2">${escapeHtml(r.to)}</div>
      <div style="flex:1">${escapeHtml(r.action)}</div>
      <div style="flex:2">${escapeHtml(r.from)}</div>
    </div>`).join("");
    return `<div>${head}${body}</div>`;
  }

  function renderUfw(root, p) {
    const cont = $("#fw-content", root);
    const enabled = !!p.enabled;
    const policies = p.policies && typeof p.policies === "object"
      ? Object.entries(p.policies).map(([k, v]) => `${escapeHtml(k)}: <strong>${escapeHtml(v)}</strong>`).join(" · ")
      : "-";

    setHeader("ufw", enabled ? "Enabled" : "Disabled", enabled ? "good" : "bad");

    const tableRows = p.rules_table || [];
    const rulesHtml = tableRows.length ? rulesTableUfw(tableRows) : rulesListUfw(p.rules_numbered || p.rules);
    const needsSudoStatus = !!p.needs_sudo_for_status;
    const needsSudoRules = !!p.needs_sudo_for_rules;

    cont.innerHTML = `
      <div class="card" style="padding:12px">
        ${needsSudoStatus ? `<div class="muted" style="margin-bottom:6px;">Some details are hidden (sudo required on host).</div>` : ""}
        <div class="muted" style="margin-bottom:8px;">Policies: ${policies}</div>
        <h3 style="margin:0 0 8px;">Rules</h3>
        ${needsSudoRules && (!tableRows || tableRows.length === 0) && (!p.rules_numbered || p.rules_numbered.length === 0)
        ? `<div class=\"muted\">Rules hidden – sudo required on host</div>`
        : `<div id=\"fw-rules\">${rulesHtml}</div>`}
      </div>`;

    // Bind delete buttons for UFW rules
    $("#fw-rules", cont)?.querySelectorAll("[data-rule-num]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const num = btn.getAttribute("data-rule-num");
        const sudo_pw = $("#fw-sudo")?.value || "";
        btn.disabled = true;
        setAlert("");
        setLog("");
        const res = await postJSON("/network/firewall/delete_rule", { number: Number(num), sudo_pw });
        if (!res.ok) setAlert(res.error || "Delete failed");
        if (res.log) setLog(res.log);
        await doLoad(document);
      });
    });
  }

  function renderFirewalld(root, p) {
    const cont = $("#fw-content", root);
    setHeader("firewalld", p.service_active ? "Active" : "Inactive", p.service_active ? "good" : "bad");

    const zones = Array.isArray(p.zones) ? p.zones : [];
    const zonesHtml = zones.length
      ? zones.map(z => {
        const iface = (z.interfaces && z.interfaces.length) ? z.interfaces.join(", ") : "-";
        const services = (z.services && z.services.length) ? z.services.join(", ") : "-";
        const ports = (z.ports && z.ports.length) ? z.ports.join(", ") : "-";
        return `
            <div style="padding:10px;border:1px solid rgba(148,163,184,.2);border-radius:10px;margin-bottom:10px">
              <div style="font-weight:600;margin-bottom:6px">${escapeHtml(z.name || "zone")}</div>
              <div><strong>Interfaces:</strong> ${escapeHtml(iface)}</div>
              <div><strong>Services:</strong> ${escapeHtml(services)}</div>
              <div><strong>Ports:</strong> ${escapeHtml(ports)}</div>
            </div>`;
      }).join("")
      : `<div class="muted">No active zones</div>`;

    cont.innerHTML = `
      <div class="card" style="padding:12px">
        <h3 style="margin:0 0 8px;">Zones</h3>
        ${zonesHtml}
      </div>`;
  }

  // ---------- Controls wiring ----------
  function applyControlsState(status) {
    const isNone = (status.framework || "none") === "none";
    const isUfw = (status.framework || "").toLowerCase() === "ufw";
    const enabled = !!status.enabled;

    const btnApply = $("#fw-apply");
    const btnEnable = $("#fw-enable");
    const btnDisable = $("#fw-disable");
    const btnRefreshSudo = $("#fw-refresh-sudo");
    const sudoPw = $("#fw-sudo")?.value || "";

    // Default enable/disable visibility
    if (btnEnable) btnEnable.style.display = (isUfw && !enabled) ? "inline-block" : "none";
    if (btnDisable) btnDisable.style.display = (isUfw && enabled) ? "inline-block" : "none";

    // Apply button disabled when framework none/not installed
    if (btnApply) btnApply.disabled = isNone;

    // Show elevated refresh only when host needs sudo for rules and user provided a password
    if (btnRefreshSudo) btnRefreshSudo.style.display = (isUfw && status.needs_sudo_for_rules && sudoPw) ? "inline-block" : "none";

    // Enable guard hint: if remote and SSH not allowed, backend will block; we just keep UI simple.
  }

  async function onApplyPreset() {
    setAlert(""); setLog("");
    const port = Number($("#fw-app-port")?.value || 8080) || 8080;
    const sudo_pw = $("#fw-sudo")?.value || undefined;
    const res = await postJSON("/network/firewall/apply_preset", { app_port: port, sudo_pw });
    if (!res.ok) setAlert(res.error || "Apply preset failed");
    if (res.log) setLog(res.log);
    await doLoad(document);
  }

  async function onEnable() {
    setAlert(""); setLog("");
    const sudo_pw = $("#fw-sudo")?.value || undefined;
    const res = await postJSON("/network/firewall/enable", { sudo_pw });
    if (!res.ok) setAlert(res.error || "Enable failed");
    if (res.log) setLog(res.log);
    await doLoad(document);
  }

  async function onDisable() {
    setAlert(""); setLog("");
    const sudo_pw = $("#fw-sudo")?.value || undefined;
    const res = await postJSON("/network/firewall/disable", { sudo_pw });
    if (!res.ok) setAlert(res.error || "Disable failed");
    if (res.log) setLog(res.log);
    await doLoad(document);
  }

  function bindControls() {
    $("#fw-apply")?.addEventListener("click", onApplyPreset);
    $("#fw-enable")?.addEventListener("click", onEnable);
    $("#fw-disable")?.addEventListener("click", onDisable);
    $("#fw-refresh")?.addEventListener("click", () => doLoad(document));
    $("#fw-refresh-sudo")?.addEventListener("click", () => doLoad(document, true));
  }

  // ---------- Controller ----------
  async function doLoad(root, elevated = false) {
    const fwRoot = $("#firewall-root", root);
    if (!fwRoot) return;

    const content = $("#fw-content", fwRoot);
    if (content) {
      content.innerHTML = `
        <div class="card" style="padding:12px">
          ${pill("Loading…", "info")}
        </div>`;
    }

    let status;
    if (elevated) {
      const sudo_pw = $("#fw-sudo")?.value || undefined;
      status = await postJSON("/network/firewall/status_elevated", { sudo_pw });
    } else {
      status = await getJSON("/network/firewall/status");
    }
    applyControlsState(status);

    if (!status || status.ok === false) {
      renderNone(fwRoot, status);
      return;
    }

    const fw = (status.framework || "none").toLowerCase();
    if (fw === "ufw") {
      renderUfw(fwRoot, status);
    } else if (fw === "firewalld") {
      renderFirewalld(fwRoot, status);
    } else {
      renderNone(fwRoot, status);
    }
  }

  // ---------- Boot ----------
  window.addEventListener("DOMContentLoaded", () => {
    const fwRoot = $("#firewall-root");
    if (!fwRoot) return;
    bindControls();
    doLoad(document);
  });
})();
