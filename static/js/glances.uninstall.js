(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const { els, setButtons, pollStatus } = window.GlancesUI || {};
        if (!els || !els.uninstallBtn) return;

        els.uninstallBtn.addEventListener("click", async () => {
            if (!confirm("Vil du afinstallere Glances og de tilhørende pakker?")) return;

            if (els.outBox) { els.outBox.style.display = "block"; els.outBox.textContent = ""; }
            if (els.uninstallingText) els.uninstallingText.style.display = "block";
            setButtons(true);

            try {
                const res = await fetch("/glances/uninstall-glances", { method: "POST", cache: "no-store", headers: { "Cache-Control": "no-cache" } });
                const ct = res.headers.get("content-type") || "";

                if (ct.includes("application/json")) {
                    const data = await res.json();
                    if (els.outBox) els.outBox.textContent = data.output || "Afinstallation udført.";
                } else if (res.body && res.body.getReader) {
                    const reader = res.body.getReader();
                    const decoder = new TextDecoder();
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;
                        const chunk = decoder.decode(value, { stream: true });
                        if (els.outBox) { els.outBox.textContent += chunk; els.outBox.scrollTop = els.outBox.scrollHeight; }
                    }
                } else {
                    const txt = await res.text();
                    if (els.outBox) els.outBox.textContent = txt || "Afinstallation udført.";
                }

                await pollStatus({ tries: 5, delay: 1200 });
            } catch (e) {
                if (els.outBox) els.outBox.textContent += "\nNetværksfejl under afinstallation.\n";
                console.error(e);
            } finally {
                if (els.uninstallingText) els.uninstallingText.style.display = "none";
                setButtons(false);
            }
        });
    });
})();
