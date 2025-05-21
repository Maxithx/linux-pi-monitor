// === FORM FELTER: Vis/skjul SSH-key eller password ===
document.addEventListener("DOMContentLoaded", function () {
    const authMethod = document.getElementById("auth_method");
    const keyFields = document.getElementById("key_fields");
    const passwordField = document.getElementById("password_field");

    function toggleAuthFields() {
        if (!authMethod) return;
        const method = authMethod.value;
        keyFields.style.display = method === "key" ? "block" : "none";
        passwordField.style.display = method === "password" ? "block" : "none";
    }

    if (authMethod) {
        authMethod.addEventListener("change", toggleAuthFields);
        toggleAuthFields();
    }

    // === STATUS: Opdater forbindelse til Linux hvert 5. sekund ===
    function updateSSHStatus() {
        fetch("/check-ssh-status")
            .then(res => res.json())
            .then(data => {
                const container = document.getElementById("connection-status");
                const statusDiv = container.querySelector(".status-indicator");
                if (!statusDiv) return;

                if (data.status === "connected") {
                    statusDiv.innerHTML = '<span class="dot dot-green"></span>Forbundet til Linux';
                } else {
                    statusDiv.innerHTML = '<span class="dot dot-red"></span>Ingen forbindelse til Linux';
                }
            });
    }

    setInterval(updateSSHStatus, 5000);
    updateSSHStatus();

    // === STATUS: Opdater Glances status (installeret/kører) ===
    const glancesStatusText = document.getElementById("glances-status-text");
    const installBtn = document.getElementById("install-glances-btn");
    const startBtn = document.getElementById("start-glances-service-btn");
    const viewLogBtn = document.getElementById("view-glances-log-btn");
    const uninstallBtn = document.getElementById("uninstall-glances");
    const uninstallingText = document.getElementById("uninstalling-text");

    function setGlancesButtons(disabled) {
        [installBtn, startBtn, viewLogBtn, uninstallBtn].forEach(btn => {
            if (btn) btn.disabled = disabled;
        });
    }

    function updateGlancesStatus() {
        if (!glancesStatusText) return;
        glancesStatusText.textContent = "Henter status...";
        glancesStatusText.style.color = "yellow";

        fetch("/glances/check-glances-status")
            .then(res => res.json())
            .then(data => {
                if (data.installed && data.running) {
                    glancesStatusText.style.color = "lightgreen";
                    glancesStatusText.textContent = "✅ Glances er installeret og tjenesten kører.";
                } else if (data.installed && !data.running) {
                    glancesStatusText.style.color = "orange";
                    glancesStatusText.textContent = "⚠️ Glances er installeret, men tjenesten kører ikke.";
                } else {
                    glancesStatusText.style.color = "red";
                    glancesStatusText.textContent = "❌ Glances er ikke installeret.";
                }
            })
            .catch(() => {
                glancesStatusText.style.color = "red";
                glancesStatusText.textContent = "❌ Kunne ikke hente Glances-status.";
            });
    }

    // === HANDLING: Installer Glances med live-output ===
    if (installBtn) {
    installBtn.addEventListener("click", () => {
        const outputBox = document.getElementById("glances-output");
        const installingText = document.getElementById("installing-text");

        outputBox.style.display = "block";
        outputBox.textContent = "";
        setGlancesButtons(true);

        // Vis spinner og info-tekst
        if (installingText) installingText.style.display = "block";

        fetch("/glances/install-glances", { method: "POST" })
            .then(response => {
                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                function read() {
                    reader.read().then(({ done, value }) => {
                        if (done) {
                            if (installingText) installingText.style.display = "none"; // Skjul spinner igen
                            setTimeout(updateGlancesStatus, 3000);
                            setGlancesButtons(false);
                            return;
                        }

                        const text = decoder.decode(value);
                        outputBox.textContent += text;
                        outputBox.scrollTop = outputBox.scrollHeight;
                        read();
                    });
                }

                read();
            })
            .catch(() => {
                outputBox.textContent += "\nFejl under installation.";
                if (installingText) installingText.style.display = "none";
                setGlancesButtons(false);
            });
    });
}


    // === HANDLING: Start Glances-tjeneste ===
    if (startBtn) {
        startBtn.addEventListener("click", () => {
            const outputBox = document.getElementById("glances-output");
            outputBox.style.display = "block";
            outputBox.textContent = "Starter Glances-tjenesten...";
            setGlancesButtons(true);

            fetch("/glances/start-glances-service", { method: "POST" })
                .then(res => res.json())
                .then(data => {
                    outputBox.textContent = data.output;
                    setTimeout(updateGlancesStatus, 3000);
                })
                .catch(() => {
                    outputBox.textContent = "Fejl ved start af tjenesten.";
                })
                .finally(() => setGlancesButtons(false));
        });
    }

    // === HANDLING: Vis log for Glances ===
    if (viewLogBtn) {
        viewLogBtn.addEventListener("click", () => {
            const logBox = document.getElementById("glances-log-output");
            logBox.style.display = "block";
            logBox.textContent = "Henter log for Glances...";
            setGlancesButtons(true);

            fetch("/glances/glances-service-log")
                .then(res => res.json())
                .then(data => {
                    logBox.textContent = data.log;
                })
                .catch(() => {
                    logBox.textContent = "Fejl ved hentning af log.";
                })
                .finally(() => setGlancesButtons(false));
        });
    }

    // === HANDLING: Afinstaller Glances ===
    if (uninstallBtn) {
    uninstallBtn.addEventListener("click", () => {
        if (!confirm("Vil du afinstallere Glances og de tilhørende pakker?")) return;

        const outputBox = document.getElementById("glances-output");
        outputBox.style.display = "block";
        outputBox.textContent = "";

        // Vis status og spinner
        if (uninstallingText) uninstallingText.style.display = "block";
        setGlancesButtons(true);

        fetch("/glances/uninstall-glances", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                outputBox.textContent = data.output;
                setTimeout(updateGlancesStatus, 3000);
            })
            .catch(() => {
                outputBox.textContent = "Fejl ved afinstallation.";
            })
            .finally(() => {
                setGlancesButtons(false);
                if (uninstallingText) uninstallingText.style.display = "none";
            });
    });
}


    // === GEM KNAP: Gem Pi-indstillinger ===
    const saveForm = document.getElementById("save-form");
    const clearBtn = document.getElementById("clear-settings-btn");

    if (saveForm) {
        saveForm.addEventListener("submit", function (e) {
            e.preventDefault();
            const formData = new FormData(saveForm);
            fetch("/save-settings", {
                method: "POST",
                body: formData
            })
                .then(res => res.json())
                .then(data => {
                    const messageBox = document.getElementById("status-message");
                    if (data.success) {
                        messageBox.style.color = "lightgreen";
                        messageBox.textContent = "✔️ Indstillinger blev gemt. Forbindelse oprettet.";
                    } else {
                        messageBox.style.color = "red";
                        messageBox.textContent = "❌ " + (data.message || "Fejl: Kunne ikke oprette forbindelse.");
                    }
                })
                .catch(() => {
                    const messageBox = document.getElementById("status-message");
                    messageBox.style.color = "red";
                    messageBox.textContent = "❌ Netværksfejl: Kunne ikke kontakte serveren.";
                });
        });
    }

    // === RYD KNAP: Ryd alle indstillinger ===
    if (clearBtn) {
        clearBtn.addEventListener("click", function () {
            if (confirm("Vil du rydde alle indstillinger?")) {
                fetch("/clear-settings", { method: "POST" })
                    .then(res => res.json())
                    .then(data => {
                        const messageBox = document.getElementById("status-message");
                        if (data.success) {
                            messageBox.style.color = "lightgreen";
                            messageBox.textContent = "🔄 Indstillinger blev nulstillet.";
                            document.getElementById("pi_host").value = "";
                            document.getElementById("pi_user").value = "";
                            document.getElementById("ssh_key_path").value = "";
                            document.getElementById("password").value = "";
                        } else {
                            messageBox.style.color = "red";
                            messageBox.textContent = "❌ " + (data.message || "Fejl ved nulstilling.");
                        }
                    })
                    .catch(() => {
                        const messageBox = document.getElementById("status-message");
                        messageBox.style.color = "red";
                        messageBox.textContent = "❌ Netværksfejl ved rydning af indstillinger.";
                    });
            }
        });
    }

    // === KNAP: Genstart Linux-systemet ===
    window.rebootLinux = function () {
        const rebootStatusBox = document.getElementById("reboot-status");
        if (!confirm("Er du sikker på, at du vil genstarte Linux-systemet?")) return;

        rebootStatusBox.textContent = "🔄 Linux genstarter... forbindelsen afbrydes midlertidigt.";

        fetch("/terminal/reboot-linux", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    rebootStatusBox.textContent = "🔄 Linux genstarter nu... forbindelsen afbrydes.";
                } else {
                    rebootStatusBox.textContent = "❌ Genstart mislykkedes.";
                }
            })
            .catch(() => {
                rebootStatusBox.textContent = "❌ Netværksfejl under genstart.";
            });
    };

    updateGlancesStatus();
});
