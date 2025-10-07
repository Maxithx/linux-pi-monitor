// static/js/settings.ssh-status.js  (v10)
(() => {
    const log = (...a) => console.log('[ssh-status]', ...a);
    const $ = (sel, root = document) => root.querySelector(sel);

    // Hvor finder vi den aktuelle profil?
    function currentProfileId() {
        const root = $('#settings-root');
        const hid = $('#profile_id')?.value?.trim();
        const sel = $('#ssh_profile_select')?.value?.trim();
        const data = root?.dataset?.activeProfile?.trim();
        return (hid && hid !== '__none__') ? hid
            : (sel && sel !== '__none__') ? sel
                : (data || null);
    }

    // UI helpers
    function setDot(dotEl, colorClass) {
        dotEl.classList.remove('dot-red', 'dot-green', 'dot-yellow');
        dotEl.classList.add(colorClass);
    }

    function renderPending() {
        const box = $('#ssh-connection'); if (!box) return;
        const dot = $('#ssh-conn-dot', box);
        const text = $('#ssh-conn-text', box);
        const spin = $('#ssh-conn-spinner', box);
        const hint = $('#ssh-conn-hint', box);

        if (dot) setDot(dot, 'dot-yellow');
        if (text) text.textContent = 'Checking connection…';
        if (spin) spin.style.display = '';
        if (hint) hint.textContent = '';
        box.setAttribute('data-connected', 'checking');
    }

    function render(connected) {
        const box = $('#ssh-connection'); if (!box) return;
        const dot = $('#ssh-conn-dot', box);
        const text = $('#ssh-conn-text', box);
        const spin = $('#ssh-conn-spinner', box);
        const hint = $('#ssh-conn-hint', box);

        if (dot) setDot(dot, connected ? 'dot-green' : 'dot-red');
        if (text) text.textContent = connected ? 'Connected to Linux' : 'No connection to Linux';
        if (spin) spin.style.display = 'none';
        if (hint) hint.textContent = '';
        box.setAttribute('data-connected', connected ? '1' : '0');
    }

    async function checkOnce() {
        const id = currentProfileId();
        if (!id) { render(false); return; }
        try {
            const r = await fetch(`/check-ssh-status?profile_id=${encodeURIComponent(id)}&t=${Date.now()}`, {
                headers: { 'Accept': 'application/json' }
            });
            const data = await r.json().catch(() => ({}));
            const ok = !!(data && (data.connected || data.ok));
            log('result', { id, ok, data });
            requestAnimationFrame(() => render(ok));
        } catch (e) {
            log('error', e);
            requestAnimationFrame(() => render(false));
        }
    }

    // Reager når profiler skifter/gemmes
    window.addEventListener('profile:changed', () => { renderPending(); setTimeout(checkOnce, 50); });
    window.addEventListener('profile:saved', () => { renderPending(); setTimeout(checkOnce, 50); });

    // Første check
    const boot = () => { renderPending(); setTimeout(checkOnce, 120); };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot, { once: true });
    } else {
        // DOM er allerede klar (fx hvis scriptet indsættes sent)
        boot();
    }
})();
