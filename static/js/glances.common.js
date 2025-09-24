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
    iframe: document.querySelector('iframe[src^="/glances"]')
  };

  function setButtons(disabled) {
    [els.installBtn, els.startBtn, els.viewLogBtn, els.uninstallBtn].forEach(b => { if (b) b && (b.disabled = disabled); });
  }

  async function getActiveProfileId() {
    try {
      const data = await fetch("/profiles/list").then(r => r.json());
      return data.active_profile_id || data.default_profile_id || null;
    } catch {
      return null;
    }
  }

  async function updateStatus(profileId) {
    if (!els.statusText) return;
    els.statusText.style.color = "yellow";
    els.statusText.textContent = "Henter status...";

    try {
      const pid = profileId || await getActiveProfileId();
      if (!pid) throw new Error("no profile id");

      const data = await fetch(`/glances/status?profile_id=${encodeURIComponent(pid)}`).then(r => r.json());
      if (data.installed && data.running) {
        els.statusText.style.color = "lightgreen";
        els.statusText.textContent = "✅ Glances er installeret og tjenesten kører.";
      } else if (data.installed) {
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

  async function pollStatus({ tries = 5, delay = 1500, profileId = null } = {}) {
    for (let i = 0; i < tries; i++) {
      await updateStatus(profileId);
      await new Promise(r => setTimeout(r, delay));
      try {
        const pid = profileId || await getActiveProfileId();
        const data = await fetch(`/glances/status?profile_id=${encodeURIComponent(pid)}`).then(r => r.json());
        if (data.running) break;
      } catch { }
    }
  }

  async function reloadIframe(profileId) {
    if (!els.iframe) return;
    const pid = profileId || await getActiveProfileId();
    if (!pid) return;
    const base = "/glances/";
    els.iframe.src = `${base}?profile_id=${encodeURIComponent(pid)}&t=${Date.now()}`;
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

  // Eksporter små helpers til Settings-siden (kan kaldes efter profilswitch)
  window.GlancesUI = { els, setButtons, updateStatus, pollStatus, reloadIframe, getActiveProfileId };
})();
