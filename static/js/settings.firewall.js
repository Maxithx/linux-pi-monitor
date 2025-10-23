// static/js/settings.firewall.js
(() => {
  "use strict";

  const btnInstall = document.getElementById("fw-helper-install");
  const btnRemove = document.getElementById("fw-helper-remove");
  const inputPw = document.getElementById("fw-helper-sudo");
  const toggleBtn = document.getElementById("fw-helper-toggle");
  const logBox = document.getElementById("fw-helper-log");
  const stateBadge = document.getElementById("fw-helper-state");

  /* ---------- small utils ---------- */
  function escapeHtml(s) {
    return (s == null ? "" : String(s))
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function setLog(txt, isError = false) {
    if (!logBox) return;
    logBox.style.color = isError ? "#ffb4b4" : "";
    logBox.textContent = txt || "";
  }

  function setBusy(isBusy) {
    [btnInstall, btnRemove, inputPw, toggleBtn].forEach(el => {
      if (!el) return;
      el.disabled = !!isBusy;
    });
    if (isBusy) setLog("Working…", false);
  }

  function inferEnabledFromExec(res) {
    const rows = Array.isArray(res?.exec) ? res.exec : [];
    const by = (name) => rows.find(r => r.step === name);
    const post1 = by("postcheck_sudo_n_status");
    const post2 = by("postcheck_sudo_n_numbered");
    if (post1 && post2) {
      return Number(post1.rc) === 0 && Number(post2.rc) === 0;
    }
    const inst = by("sudo_install");
    if (inst && Number(inst.rc) === 0) return true;
    return false;
  }

  function renderExec(res) {
    if (!logBox) { return; }
    const parts = [];
    if (res.user || res.ufw_path) {
      parts.push(`<div>user: <code>${escapeHtml(res.user || '')}</code> · ufw: <code>${escapeHtml(res.ufw_path || '')}</code></div>`);
    }
    if (res.sudoers_target) {
      parts.push(`<div>sudoers: <code>${escapeHtml(res.sudoers_target)}</code>${res.file_mode ? ` · mode: <code>${escapeHtml(res.file_mode)}</code>` : ""}</div>`);
    }
    if (res.file_content_head) {
      parts.push(`<pre style="margin:6px 0; white-space:pre-wrap;">${escapeHtml(res.file_content_head)}</pre>`);
    }
    const rows = Array.isArray(res.exec) ? res.exec : [];
    if (rows.length) {
      const head = `<div style="display:flex;font-weight:600;border-bottom:1px solid rgba(148,163,184,.25);padding:4px 0">
        <div style="flex:2">step</div><div style="width:46px">rc</div><div style="flex:3">out</div><div style="flex:3">err</div></div>`;
      const body = rows.map(r => {
        const bad = Number(r.rc) !== 0;
        return `<div style="display:flex;border-bottom:1px solid rgba(148,163,184,.15);padding:4px 0;color:${bad ? '#ffb4b4' : ''}">
          <div style="flex:2">${escapeHtml(r.step)}</div>
          <div style="width:46px">${escapeHtml(r.rc)}</div>
          <div style="flex:3;white-space:pre-wrap">${escapeHtml(r.out)}</div>
          <div style="flex:3;white-space:pre-wrap">${escapeHtml(r.err)}</div>
        </div>`;
      }).join("");
      parts.push(`<div style="margin-top:6px">${head}${body}</div>`);
    }
    const copyBtn = `<div style="margin-top:6px"><button id="fw-helper-copy" class="secondary">Copy log</button></div>`;
    logBox.style.color = "";
    logBox.innerHTML = parts.join("") + copyBtn;
    document.getElementById('fw-helper-copy')?.addEventListener('click', () => {
      try { navigator.clipboard.writeText(JSON.stringify(res, null, 2)); } catch { }
    });
  }

  async function getJSON(url) {
    const r = await fetch(url, { method: "GET" });
    const t = await r.text();
    try { return JSON.parse(t); } catch { return { ok: false, error: t || "Bad response" }; }
  }

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    const t = await r.text();
    try { return JSON.parse(t); } catch { return { ok: false, error: t || "Bad response" }; }
  }

  /* ---------- UI state ---------- */
  function paintState(enabled) {
    if (!stateBadge) return;
    if (enabled) {
      stateBadge.textContent = "Passwordless UFW status: Enabled ✓";
      stateBadge.style.color = "#8fda8f";
      btnInstall && (btnInstall.disabled = true);
      btnRemove && (btnRemove.disabled = false);
    } else {
      stateBadge.textContent = "Passwordless UFW status: Disabled";
      stateBadge.style.color = "";
      btnInstall && (btnInstall.disabled = false);
      btnRemove && (btnRemove.disabled = true);
    }
  }

  // RETURNERER nu bool (enabled)
  async function refreshState() {
    const res = await getJSON("/settings/firewall/sudoers/status");
    if (res.ok) {
      paintState(!!res.enabled);
      return !!res.enabled;
    } else {
      paintState(false);
      setLog(res.error || "Status check failed.", true);
      return false;
    }
  }

  /* ---------- actions ---------- */
  async function onInstall() {
    setBusy(true);
    try {
      const sudo_pw = inputPw?.value || "";
      const res = await postJSON("/settings/firewall/sudoers/install", { sudo_pw });

      // vis detaljer hvis vi fik dem
      if (res.exec || res.user || res.ufw_path || res.sudoers_target) {
        renderExec(res);
      }

      const enabledNow = (typeof res.enabled === "boolean")
        ? !!res.enabled
        : inferEnabledFromExec(res);
      const success = !!(res.ok || enabledNow);

      if (!success) {
        // Tjek endelig sandhed: er den faktisk enabled alligevel?
        const finalEnabled = await refreshState();
        if (finalEnabled) {
          setLog(""); // ryd “Install failed.”
          return;
        }
        setLog(res.error || "Install failed.", true);
        return;
      }

      // Succes-path
      paintState(enabledNow);
      const finalEnabled = await refreshState(); // sync med backend
      if (finalEnabled) {
        // hvis vi ikke viser en tabel/log, så ryd statuslinjen
        if (!logBox.innerHTML || logBox.textContent === "Working…") setLog("");
      }

    } catch (e) {
      setLog(String(e || "Install failed."), true);
    } finally {
      setBusy(false);
    }
  }

  async function onRemove() {
    setBusy(true);
    try {
      const sudo_pw = inputPw?.value || "";
      const res = await postJSON("/settings/firewall/sudoers/remove", { sudo_pw });
      if (res.exec || res.log) renderExec(res);

      paintState(false);
      const finalEnabled = await refreshState();
      if (!finalEnabled) setLog(""); // ryd evt. gammel fejltekst
    } catch (e) {
      setLog(String(e || "Remove failed."), true);
    } finally {
      setBusy(false);
    }
  }

  function onToggle() {
    if (!inputPw || !toggleBtn) return;
    const reveal = inputPw.type === "password";
    inputPw.type = reveal ? "text" : "password";
    toggleBtn.textContent = reveal ? "Hide" : "Show";
    toggleBtn.setAttribute("aria-pressed", String(reveal));
    inputPw.focus();
  }

  /* ---------- wire up ---------- */
  btnInstall?.addEventListener("click", onInstall);
  btnRemove?.addEventListener("click", onRemove);
  toggleBtn?.addEventListener("click", onToggle);
  inputPw?.addEventListener("keydown", (e) => { if (e.key === "Enter") onInstall(); });

  // initial paint
  refreshState();
})();
