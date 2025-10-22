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

  function row(label, valueHtml) {
    return `<div style="display:flex;gap:12px;align-items:flex-start;padding:6px 0;border-bottom:1px solid rgba(148,163,184,.15)">
      <div style="min-width:180px;color:#64748b">${escapeHtml(label)}</div>
      <div style="flex:1">${valueHtml}</div>
    </div>`;
  }

  function kvtbl(obj) {
    if (!obj || typeof obj !== "object") return "-";
    const rows = Object.entries(obj)
      .map(([k, v]) => {
        const val = Array.isArray(v) ? v.map(escapeHtml).join(", ") : escapeHtml(v);
        return `<tr><td style="padding:4px 10px;color:#94a3b8">${escapeHtml(k)}</td><td style="padding:4px 10px">${val || "-"}</td></tr>`;
      })
      .join("");
    return `<table style="border-collapse:collapse;width:100%">${rows}</table>`;
  }

  // ---------- Data fetch ----------
  async function fetchStatus() {
    const r = await fetch("/network/firewall/status", { cache: "no-store" });
    try {
      return await r.json();
    } catch (_) {
      try {
        const txt = await r.text();
        return { ok: false, error: (txt && txt.trim()) || "No supported firewall or service inactive" };
      } catch {
        return { ok: false, error: "No supported firewall or service inactive" };
      }
    }
  }

  // ---------- Small header helpers ----------
  function setHeader(framework, stateText, tone = "neutral") {
    const fwLbl = $("#fw-framework");
    const fwPill = $("#fw-pill");
    if (fwLbl) fwLbl.textContent = framework ? String(framework) : '';
    if (fwPill) fwPill.innerHTML = pill(stateText || "-", tone);
  }

  // ---------- Renderers ----------
  function renderNone(root, payload) {
    const cont = $("#fw-content", root);
    const msg = escapeHtml(
      (payload && payload.error) || "No supported firewall detected (UFW/Firewalld not present or inactive)."
    );
    setHeader("none", "Unavailable", "warn");
    cont.innerHTML = `
      <div class="card" style="padding:12px">
        <div style="color:#b91c1c">${msg}</div>
      </div>`;
  }

  function renderUfw(root, p) {
    const cont = $("#fw-content", root);
    const enabled = !!p.enabled;
    const defaults = p.defaults && typeof p.defaults === "object" ? kvtbl(p.defaults) : "-";
    const rules =
      Array.isArray(p.rules) && p.rules.length
        ? `<ul style="margin:0;padding-left:18px">${p.rules.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
        : "-";

    setHeader("ufw", enabled ? "Enabled" : "Disabled", enabled ? "good" : "bad");
    cont.innerHTML = `
      <div class="card" style="padding:12px">
        ${row("Defaults", defaults)}
        ${row("Rules", rules)}
      </div>`;
  }

  function renderFirewalld(root, p) {
    const cont = $("#fw-content", root);
    const zones = Array.isArray(p.zones) ? p.zones : [];
    const zonesHtml =
      zones.length === 0
        ? "-"
        : zones
          .map((z) => {
            const iface = z.interfaces && z.interfaces.length ? z.interfaces.join(", ") : "-";
            const services = z.services && z.services.length ? z.services.join(", ") : "-";
            const ports = z.ports && z.ports.length ? z.ports.join(", ") : "-";
            return `
              <div style="padding:10px;border:1px solid rgba(148,163,184,.2);border-radius:10px;margin-bottom:10px">
                <div style="font-weight:600;margin-bottom:6px">${escapeHtml(z.name || "zone")}</div>
                ${row("Interfaces", escapeHtml(iface))}
                ${row("Services", escapeHtml(services))}
                ${row("Ports", escapeHtml(ports))}
              </div>`;
          })
          .join("");

    setHeader("firewalld", "Active", "good");
    cont.innerHTML = `
      <div class="card" style="padding:12px">
        ${row("Zones", zonesHtml)}
      </div>`;
  }

  // ---------- Controller ----------
  async function doLoad(root) {
    const fwRoot = $("#firewall-root", root);
    if (!fwRoot) return;

    const content = $("#fw-content", fwRoot);
    if (content) {
      content.innerHTML = `
        <div class="card" style="padding:12px">
          ${pill("Loading...", "info")}
        </div>`;
    }

    let data;
    try {
      data = await fetchStatus();
    } catch (e) {
      setHeader("unknown", "Error", "bad");
      if (content) content.innerHTML = `<div class="card" style="padding:12px;color:#b91c1c">Fetch failed</div>`;
      return;
    }

    if (!data || data.ok === false) {
      renderNone(fwRoot, data);
      return;
    }

    const fw = (data.framework || "none").toLowerCase();
    if (fw === "ufw") {
      renderUfw(fwRoot, data);
    } else if (fw === "firewalld") {
      renderFirewalld(fwRoot, data);
    } else {
      renderNone(fwRoot, data);
    }
  }

  // ---------- Boot ----------
  window.addEventListener("DOMContentLoaded", () => {
    const fwRoot = $("#firewall-root");
    if (!fwRoot) return;

    const refreshBtn = $("#fw-refresh", fwRoot);
    if (refreshBtn && !refreshBtn._bound) {
      refreshBtn._bound = true;
      refreshBtn.addEventListener("click", () => doLoad(document));
    }

    // Initial load (even if the section is hidden; content will be ready when user clicks the tab)
    doLoad(document);
  });
})();
