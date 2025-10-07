// static/js/glances.install.js
// Installerer Glances på fjern Linux og streamer log til UI uden at hænge.
// Tilføjet: valgfri engangs sudo-password prompt (sendes KUN i denne POST og gemmes ikke).

(() => {
    const btnInstall = document.getElementById('install-glances-btn');
    const btnStartSvc = document.getElementById('start-glances-service-btn');
    const btnViewLog = document.getElementById('view-glances-log-btn');
    const btnClearLog = document.getElementById('clear-glances-log-btn');

    const statusText = document.getElementById('glances-status-text');
    const installingText = document.getElementById('installing-text');
    const installingTimer = document.getElementById('install-timer');

    const outInstall = document.getElementById('glances-output');         // live install shell
    const outService = document.getElementById('glances-service-output'); // service-kald
    const outLog = document.getElementById('glances-log-output');     // glances log fil

    let timerId = null;
    let pollId = null;

    function setInstalling(on) {
        if (!installingText || !installingTimer) return;
        if (on) {
            installingText.style.display = '';
            const t0 = Date.now();
            clearInterval(timerId);
            timerId = setInterval(() => {
                const s = Math.floor((Date.now() - t0) / 1000);
                const m = String(Math.floor(s / 60)).padStart(2, '0');
                const r = String(s % 60).padStart(2, '0');
                installingTimer.textContent = `${m}:${r}`;
            }, 1000);
        } else {
            installingText.style.display = 'none';
            clearInterval(timerId);
            installingTimer.textContent = '00:00';
        }
    }

    async function fetchJSON(url, opts = {}) {
        const res = await fetch(url, opts);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    }

    async function fetchText(url) {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.text();
    }

    async function refreshStatus() {
        try {
            const data = await fetchJSON('/glances/status');
            const parts = [];
            parts.push(data.installed ? 'Glances: installed' : 'Glances: not installed');
            parts.push(data.running ? 'Service: running' : 'Service: not running');
            if (statusText) {
                statusText.style.color = data.running ? 'lightgreen' : (data.installed ? 'orange' : 'salmon');
                statusText.textContent = parts.join(' — ');
            }
        } catch {
            if (statusText) {
                statusText.style.color = 'yellow';
                statusText.textContent = 'Status: unknown';
            }
        }
    }

    async function startInstall() {
        try {
            if (outInstall) { outInstall.style.display = ''; outInstall.textContent = ''; }
            if (outService) { outService.style.display = 'none'; }
            if (outLog) { outLog.style.display = 'none'; }

            setInstalling(true);
            if (btnInstall) btnInstall.disabled = true;

            // === Valgfri engangs sudo-password prompt ===
            let sudoPw = null;
            const wantSudo = confirm(
                "Vil du køre installationen med engangs sudo-password til apt/sensors-detect?\n" +
                "Det gemmes ikke og bruges kun i denne installation."
            );
            if (wantSudo) {
                const pw = prompt("Indtast sudo-password (tom/Annullér = spring over):", "");
                if (pw !== null && pw !== "") sudoPw = pw;
            }

            // Start installation (sender sudo_pw hvis udfyldt)
            await fetchJSON('/glances/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ sudo_pw: sudoPw ?? undefined })
            });

            // Poll log mens installationen kører
            clearInterval(pollId);
            pollId = setInterval(async () => {
                try {
                    const txt = await fetchText('/glances/log');
                    if (outInstall) {
                        outInstall.textContent = txt || '';
                        outInstall.scrollTop = outInstall.scrollHeight;
                    }
                } catch { /* ignore */ }
            }, 1000);

            // Stop polling ved "Done./Færdig." eller efter 8 min. + kort status-poll for at fange ny listener
            const t0 = Date.now();
            const stopCheck = setInterval(async () => {
                const txt = (outInstall && outInstall.textContent) || '';
                const finished = txt.includes("Færdig.") || txt.includes("Done.");
                const timedOut = (Date.now() - t0) > 8 * 60 * 1000;
                if (finished || timedOut) {
                    clearInterval(stopCheck);
                    clearInterval(pollId);
                    setInstalling(false);
                    if (btnInstall) btnInstall.disabled = false;

                    // Poll /status i ~10 sek så UI når at skifte til installed/running
                    const tStart = Date.now();
                    const statusTick = setInterval(async () => {
                        await refreshStatus();
                        if ((Date.now() - tStart) > 10000) clearInterval(statusTick);
                    }, 1000);
                }
            }, 1500);

        } catch (e) {
            setInstalling(false);
            if (btnInstall) btnInstall.disabled = false;
            alert('Install failed: ' + e.message);
        }
    }

    async function viewLog() {
        try {
            const txt = await fetchText('/glances/log');
            if (outLog) {
                outLog.style.display = '';
                outLog.textContent = txt || '';
                outLog.scrollTop = outLog.scrollHeight;
            }
            if (outInstall) outInstall.style.display = 'none';
            if (outService) outService.style.display = 'none';
        } catch (e) {
            alert('Could not fetch log: ' + e.message);
        }
    }

    async function clearLog() {
        try {
            await fetchJSON('/glances/clear-log', { method: 'POST' });
            if (outLog) outLog.textContent = '';
            if (outInstall) outInstall.textContent = '';
        } catch (e) {
            alert('Could not clear log: ' + e.message);
        }
    }

    // Wire knapper
    btnInstall?.addEventListener('click', startInstall);
    btnViewLog?.addEventListener('click', viewLog);
    btnClearLog?.addEventListener('click', clearLog);

    // Init-status + periodisk opdatering
    refreshStatus();
    setInterval(refreshStatus, 10000);
})();
