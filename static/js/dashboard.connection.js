// static/js/dashboard.connection.js
// Viser aktiv profil + SSH status på Dashboard

(() => {
    const sel = {
        dot: document.getElementById('dash-conn-dot'),
        text: document.getElementById('dash-conn-text'),
        hint: document.getElementById('dash-conn-hint'),
    };

    const API = {
        listProfiles: '/profiles/list',
        checkStatus: (id) => `/check-ssh-status?profile_id=${encodeURIComponent(id)}`
    };

    function setState({ color = 'red', text = 'No connection', hint = '' }) {
        if (sel.dot) {
            sel.dot.classList.remove('green', 'red', 'yellow');
            sel.dot.classList.add(color);
        }
        if (sel.text) sel.text.textContent = text;
        if (sel.hint) sel.hint.textContent = hint;
    }

    async function getActiveProfile() {
        const r = await fetch(API.listProfiles, { cache: 'no-store' });
        const data = await r.json();
        const act = data.active_profile_id;
        const p = (data.profiles || []).find(x => x.id === act) || null;
        return p ? { id: p.id, name: p.name || 'Profile', host: p.pi_host || '', user: p.pi_user || '' } : null;
    }

    async function checkOnce() {
        try {
            const p = await getActiveProfile();
            if (!p || !p.host) {
                setState({ color: 'red', text: 'No connection', hint: '(no active profile/host)' });
                return;
            }
            // Vis loading-ish farve mens vi checker
            setState({ color: 'yellow', text: `Checking ${p.name}`, hint: `${p.user}@${p.host}` });

            const r = await fetch(API.checkStatus(p.id), { cache: 'no-store' });
            const j = await r.json(); // forventer { ok: true, connected: bool }
            if (j && (j.ok || j.connected)) {
                setState({ color: 'green', text: 'Connected', hint: `${p.user}@${p.host}` });
            } else {
                setState({ color: 'red', text: 'No connection', hint: `${p.user}@${p.host}` });
            }
        } catch (e) {
            setState({ color: 'red', text: 'No connection', hint: '(error)' });
        }
    }

    // Første check når DOM er klar
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', checkOnce, { once: true });
    } else {
        checkOnce();
    }

    // Opdater roligt hvert 30s
    setInterval(checkOnce, 30000);

    // Hvis du navigerer fra Settings -> Dashboard i samme session og udsender custom events,
    // kan vi lytte og opdatere med det samme (harmløst hvis aldrig fired):
    window.addEventListener('profile:changed', checkOnce);
    window.addEventListener('profile:saved', checkOnce);
})();
