// static/js/glances.uninstall.js
// Uninstall with optional one-time sudo password, supports JSON or stream replies.

(function () {
    'use strict';

    const uninstallBtn =
        document.getElementById('uninstall-glances-btn') ||
        document.getElementById('uninstall-glances');

    const outBox =
        document.getElementById('glances-output') ||
        document.getElementById('glances-log-output');

    const statusText = document.getElementById('glances-status-text');

    const hasUI = typeof window.GlancesUI === 'object' && window.GlancesUI !== null;
    const setButtons = hasUI && typeof window.GlancesUI.setButtons === 'function'
        ? window.GlancesUI.setButtons
        : (disabled) => { if (uninstallBtn) uninstallBtn.disabled = !!disabled; };

    async function refreshStatus() {
        if (hasUI && typeof window.GlancesUI.updateStatus === 'function') {
            try { await window.GlancesUI.updateStatus(); return; } catch { }
        }
        try {
            const res = await fetch('/glances/status', { cache: 'no-store' });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const st = await res.json();
            if (statusText) {
                const parts = [];
                parts.push(st.installed ? 'Glances: installed' : 'Glances: not installed');
                parts.push(st.running ? 'Service: running' : 'Service: not running');
                statusText.style.color = st.running ? 'lightgreen' : (st.installed ? 'orange' : 'salmon');
                statusText.textContent = parts.join(' — ');
            }
        } catch {
            if (statusText) {
                statusText.style.color = 'yellow';
                statusText.textContent = 'Status: unknown';
            }
        }
    }

    async function postAndRead(url, bodyObj) {
        const res = await fetch(url, {
            method: 'POST',
            cache: 'no-store',
            headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' },
            body: JSON.stringify(bodyObj || {})
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);

        const ct = (res.headers.get('content-type') || '').toLowerCase();

        // JSON response (our backend returns {"ok":..., "output": "..."} )
        if (ct.includes('application/json')) {
            const data = await res.json();
            if (outBox) {
                if (data.output) outBox.textContent += (outBox.textContent ? '\n' : '') + data.output + '\n';
                if (data.error) outBox.textContent += (outBox.textContent ? '\n' : '') + '[error] ' + data.error + '\n';
            }
            return data.ok ? 'OK' : 'ERR';
        }

        // Text/streaming fallback
        if (res.body && res.body.getReader) {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buf = '';
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                buf += chunk;
                if (outBox) {
                    outBox.textContent += chunk;
                    outBox.scrollTop = outBox.scrollHeight;
                }
            }
            return buf;
        }

        const txt = await res.text();
        if (outBox) outBox.textContent += (outBox.textContent ? '\n' : '') + (txt || '') + '\n';
        return txt;
    }

    async function doUninstall() {
        if (!uninstallBtn) return;
        if (!confirm('Uninstall Glances and related packages?')) return;

        // Ask for one-time sudo password (like install)
        let sudoPw = null;
        const wantSudo = confirm(
            'Run uninstall with a one-time sudo password (needed for systemd and apt/pipx cleanup)?\n' +
            'It will be used only for this request and not stored.'
        );
        if (wantSudo) {
            const pw = prompt('Enter sudo password (leave blank to skip):', '');
            if (pw) sudoPw = pw;
        }

        try {
            setButtons(true);
            if (outBox) {
                outBox.style.display = 'block';
                outBox.textContent = 'Starting uninstall...\n';
            }

            const endpoints = ['/glances/uninstall-glances', '/glances/uninstall'];
            let lastErr = null;

            for (const ep of endpoints) {
                try {
                    if (outBox) outBox.textContent += `→ Calling ${ep}\n`;
                    await postAndRead(ep, { sudo_pw: sudoPw ?? undefined });
                    lastErr = null;
                    break;
                } catch (e) {
                    lastErr = e;
                    if (outBox) outBox.textContent += `Endpoint failed: ${ep} (${e && e.message ? e.message : e})\n`;
                }
            }

            if (lastErr) throw lastErr;

            // Refresh status for ~8s (systemd changes)
            const start = Date.now();
            const tick = setInterval(async () => {
                await refreshStatus();
                if ((Date.now() - start) > 8000) clearInterval(tick);
            }, 1000);

        } catch (e) {
            if (outBox) outBox.textContent += '\nUninstall failed: ' + (e && e.message ? e.message : e) + '\n';
            console.error(e);
        } finally {
            setButtons(false);
        }
    }

    if (uninstallBtn && !uninstallBtn.dataset.bound) {
        uninstallBtn.dataset.bound = '1';
        uninstallBtn.addEventListener('click', doUninstall);
    }
})();
