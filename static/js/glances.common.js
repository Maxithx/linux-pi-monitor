(function () {
  function $(id) { return document.getElementById(id); }

  const els = {
    statusText: $("glances-status-text"),
    installBtn: $("install-glances-btn"),
    startBtn: $("start-glances-service-btn"),
    viewLogBtn: $("view-glances-log-btn"),
    uninstallBtn: $("uninstall-glances"),
    clearLogBtn: $("clear-log-btn") || $("clear-glances-log-btn"),
    installingText: $("installing-text"),
    uninstallingText: $("uninstalling-text"),
    outBox: $("glances-output"),
    logBox: $("glances-log-output"),
    iframe: document.getElementById("glances-frame")
  };

  async function getActiveProfile() {
    try {
      return await fetch("/profiles/list", { cache: "no-store" }).then(r => r.json());
    } catch {
      return { profiles: [] };
    }
  }

  function setButtons(disabled) {
    [els.installBtn, els.startBtn, els.viewLogBtn, els.uninstallBtn]
      .forEach(b => { if (b) b.disabled = !!disabled; });
  }

  async function updateStatus(profileId) {
    if (!els.statusText) return;
    els.statusText.style.color = "yellow";
    els.statusText.textContent = "Henter status...";

    try {
      const data = await getActiveProfile();
      const pid = profileId || data.active_profile_id || data.default_profile_id || null;
      if (!pid) throw new Error("no profile id");

      const st = await fetch(`/glances/status?profile_id=${encodeURIComponent(pid)}`, { cache: "no-store" })
        .then(r => r.json());

      if (st.installed && st.running) {
        els.statusText.style.color = "lightgreen";
        els.statusText.textContent = "✅ Glances er installeret og tjenesten kører.";
      } else if (st.installed) {
        els.statusText.style.color = "orange";
        els.statusText.textContent = "⚠️ Glances er installeret, men tjenesten kører ikke.";
      } else {
        els.statusText.style.color = "red";
        els.statusText.textContent = "❌ Glances er ikke installeret.";
      }
    } catch {
      els.statusText.style.color = "red";
      els.statusText.textContent = "❌ Kunne ikke hente Glances-status.";
    }
  }

  async function reloadIframe(profileId) {
    if (!els.iframe) return;
    const data = await getActiveProfile();
    const pid = profileId || data.active_profile_id || data.default_profile_id || null;
    const prof = (data.profiles || []).find(p => p.id === pid);
    const host = prof && (prof.pi_host || "").trim();
    if (!host) return;  // glances_url blev også tom i templaten

    const url = `http://${host}:61208/?t=${Date.now()}`; // cache-bust
    els.iframe.src = url;
  }

  document.addEventListener("DOMContentLoaded", async () => {
    if (els.clearLogBtn) {
      els.clearLogBtn.addEventListener("click", () => {
        if (els.outBox) els.outBox.textContent = "";
        if (els.logBox) els.logBox.textContent = "";
      });
    }
    await updateStatus();
    await reloadIframe();
  });

  window.GlancesUI = { setButtons, updateStatus, reloadIframe };
})();
