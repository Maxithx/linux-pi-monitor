(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const { els, setButtons, pollStatus } = window.GlancesUI || {};
        if (!els) return;

        if (els.startBtn) {
            els.startBtn.addEventListener("click", () => {
                if (els.outBox) { els.outBox.style.display = "block"; els.outBox.textContent = "Starter Glances-tjenesten..."; }
                setButtons(true);
                // ✔️ genbrug din eksisterende /install (idempotent: installerer hvis nødvendigt, starter ellers)
                fetch("/glances/install", { method: "POST" })
                    .then(r => r.json())
                    .then(data => { if (els.outBox) els.outBox.textContent = data.output || "Done."; })
                    .then(() => pollStatus({ tries: 3, delay: 1000 }))
                    .catch(() => { if (els.outBox) els.outBox.textContent = "Fejl ved start af tjenesten."; })
                    .finally(() => setButtons(false));
            });
        }

        if (els.viewLogBtn) {
            els.viewLogBtn.addEventListener("click", () => {
                if (els.logBox) { els.logBox.style.display = "block"; els.logBox.textContent = "Henter log for Glances..."; }
                setButtons(true);
                // ✔️ din eksisterende log-route returnerer text/plain
                fetch("/glances/log")
                    .then(r => r.text())
                    .then(txt => { if (els.logBox) els.logBox.textContent = (txt || "Ingen log tilgængelig."); })
                    .catch(() => { if (els.logBox) els.logBox.textContent = "Fejl ved hentning af log."; })
                    .finally(() => setButtons(false));
            });
        }
    });
})();
