(function () {
    document.addEventListener("DOMContentLoaded", () => {
        const authMethod = document.getElementById("auth_method");
        const keyFields = document.getElementById("key_fields");
        const passwordField = document.getElementById("password_field");
        const saveForm = document.getElementById("save-form");
        const clearBtn = document.getElementById("clear-settings-btn");

        function toggleAuthFields() {
            if (!authMethod) return;
            const method = authMethod.value;
            if (keyFields) keyFields.style.display = method === "key" ? "block" : "none";
            if (passwordField) passwordField.style.display = method === "password" ? "block" : "none";
        }
        if (authMethod) {
            authMethod.addEventListener("change", toggleAuthFields);
            toggleAuthFields();
        }

        if (saveForm) {
            saveForm.addEventListener("submit", (e) => {
                e.preventDefault();
                const formData = new FormData(saveForm);
                fetch("/save-settings", { method: "POST", body: formData })
                    .then(r => r.json())
                    .then(data => {
                        const msg = document.getElementById("status-message");
                        if (!msg) return;
                        if (data.success) {
                            msg.style.color = "lightgreen";
                            msg.textContent = "✔️ Indstillinger blev gemt. Forbindelse oprettet.";
                        } else {
                            msg.style.color = "red";
                            msg.textContent = "❌ " + (data.message || "Fejl: Kunne ikke oprette forbindelse.");
                        }
                    })
                    .catch(() => {
                        const msg = document.getElementById("status-message");
                        if (!msg) return;
                        msg.style.color = "red";
                        msg.textContent = "❌ Netværksfejl: Kunne ikke kontakte serveren.";
                    });
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener("click", () => {
                if (!confirm("Vil du rydde alle indstillinger?")) return;
                fetch("/clear-settings", { method: "POST" })
                    .then(r => r.json())
                    .then(data => {
                        const msg = document.getElementById("status-message");
                        if (!msg) return;
                        if (data.success) {
                            msg.style.color = "lightgreen";
                            msg.textContent = "🔄 Indstillinger blev nulstillet.";
                            ["pi_host", "pi_user", "ssh_key_path", "password"].forEach(id => {
                                const el = document.getElementById(id); if (el) el.value = "";
                            });
                        } else {
                            msg.style.color = "red";
                            msg.textContent = "❌ " + (data.message || "Fejl ved nulstilling.");
                        }
                    })
                    .catch(() => {
                        const msg = document.getElementById("status-message");
                        if (!msg) return;
                        msg.style.color = "red";
                        msg.textContent = "❌ Netværksfejl ved rydning af indstillinger.";
                    });
            });
        }
    });
})();
