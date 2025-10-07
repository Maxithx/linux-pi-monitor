(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const installNeofetchBtn = document.getElementById("install-neofetch-btn");
        const uninstallNeofetchBtn = document.getElementById("uninstall-neofetch-btn");
        const installCmatrixBtn = document.getElementById("install-cmatrix-btn");
        const uninstallCmatrixBtn = document.getElementById("uninstall-cmatrix-btn");
        const terminalOutput = document.getElementById("terminal-software-output");
        const installingSpinner = document.getElementById("terminal-software-spinner");

        function handle(button, url, text) {
            if (!button) return;
            button.addEventListener("click", () => {
                if (!confirm(text)) return;
                if (terminalOutput) { terminalOutput.style.display = "block"; terminalOutput.textContent = ""; }
                if (installingSpinner) installingSpinner.style.display = "inline-block";
                fetch(url, { method: "POST" })
                    .then(r => r.json())
                    .then(data => { if (terminalOutput) terminalOutput.textContent = data.output || "✅ Done."; })
                    .then(updateStatus)
                    .catch(() => { if (terminalOutput) terminalOutput.textContent = "❌ Error during installation."; })
                    .finally(() => { if (installingSpinner) installingSpinner.style.display = "none"; });
            });
        }

        function updateStatus() {
            fetch("/check-install-status")
                .then(r => r.json())
                .then(data => {
                    const nStat = document.getElementById("status-neofetch");
                    const cStat = document.getElementById("status-cmatrix");
                    const nInst = document.getElementById("install-neofetch-btn");
                    const nUn = document.getElementById("uninstall-neofetch-btn");
                    const cInst = document.getElementById("install-cmatrix-btn");
                    const cUn = document.getElementById("uninstall-cmatrix-btn");

                    if (nStat) {
                        if (data.neofetch) {
                            nStat.textContent = "Installed ✔"; nStat.style.color = "lightgreen";
                            if (nInst) nInst.style.display = "none"; if (nUn) nUn.style.display = "inline-block";
                        } else {
                            nStat.textContent = "Not Installed"; nStat.style.color = "red";
                            if (nInst) nInst.style.display = "inline-block"; if (nUn) nUn.style.display = "none";
                        }
                    }
                    if (cStat) {
                        if (data.cmatrix) {
                            cStat.textContent = "Installed ✔"; cStat.style.color = "lightgreen";
                            if (cInst) cInst.style.display = "none"; if (cUn) cUn.style.display = "inline-block";
                        } else {
                            cStat.textContent = "Not Installed"; cStat.style.color = "red";
                            if (cInst) cInst.style.display = "inline-block"; if (cUn) cUn.style.display = "none";
                        }
                    }
                })
                .catch(() => {
                    const nStat = document.getElementById("status-neofetch");
                    const cStat = document.getElementById("status-cmatrix");
                    if (nStat) nStat.textContent = "⚠️ Error";
                    if (cStat) cStat.textContent = "⚠️ Error";
                });
        }

        handle(installNeofetchBtn, "/install-neofetch", "Install Neofetch?");
        handle(uninstallNeofetchBtn, "/uninstall-neofetch", "Uninstall Neofetch?");
        handle(installCmatrixBtn, "/install-cmatrix", "Install CMatrix?");
        handle(uninstallCmatrixBtn, "/uninstall-cmatrix", "Uninstall CMatrix?");
        updateStatus();
    });
})();
