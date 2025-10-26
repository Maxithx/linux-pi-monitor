// static/js/dashboard.connection.js
// Shows active profile + SSH status on the Dashboard (+ OS name below)

(() => {
    // ---- DOM refs (safe even if elements are missing) ----
    const sel = {
        os: document.getElementById('dash-conn-os'),
    };

    // ---- API endpoints ----
    const API = {
        listProfiles: '/profiles/list',
        checkStatus: (id) => `/check-ssh-status?profile_id=${encodeURIComponent(id)}`,
        osInfo: '/system/os'
    };

    // ---- UI state helper ----
    function setState({ text = '', hint = '' }) {
        if (sel.os && text) sel.os.textContent = text;
    }

    // ---- Fetch helper with timeout + strict JSON parsing ----
    async function fetchJSON(url, { timeout = 8000, cache = 'no-store' } = {}) {
        const ctrl = new AbortController();
        const id = setTimeout(() => ctrl.abort(), timeout);
        try {
            const res = await fetch(url, { cache, signal: ctrl.signal, headers: { 'Accept': 'application/json' } });
            if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
            const text = await res.text();
            if (!text) throw new Error('Empty response');
            return JSON.parse(text);
        } finally {
            clearTimeout(id);
        }
    }

    // ---- Get active profile (id, name, host, user) ----
  async function getActiveProfile() {
    try {
      const data = await fetchJSON(API.listProfiles);
      const act = data && data.active_profile_id;
      const profiles = (data && data.profiles) || [];
      const p = profiles.find(x => x.id === act) || null;
      return p
        ? {
            id: p.id,
            name: p.name || 'Profile',
            host: p.pi_host || p.host || '',
            user: p.pi_user || p.user || ''
          }
        : null;
    } catch (e) {
      return null; // tolerate missing profiles API
    }
  }

    // ---- Fetch OS name from backend ----
    async function getOsName() {
        try {
            const j = await fetchJSON(API.osInfo);
            const os = (j && j.os_name) ? String(j.os_name).trim() : '';
            return os;
        } catch {
            return '';
        }
    }

    // ---- Single status check ----
    let inFlight = false;

    async function checkOnce() {
        if (inFlight) return;
        inFlight = true;

        try {
            const offline = typeof navigator !== 'undefined' && navigator && navigator.onLine === false;

            const p = await getActiveProfile();

            if (!p || !p.host) {
                setState({ color: 'red', text: 'No connection', hint: '(no active profile/host)' });
                if (sel.os) sel.os.textContent = '';
                return;
            }

            const subtitle = p && p.user && p.host ? `${p.user}@${p.host}` : (p && p.host ? p.host : '');
            if (offline) return;

            const j = await fetchJSON(API.checkStatus(p.id)).catch(() => null);
            if (!j) return;

            const connected = Boolean(j.connected) || Boolean(j.ok);
            if (connected) {
                // --- Now fetch and display OS name just below the connection line ---
                const osName = await getOsName();
                if (osName) {
                    if (sel.os) {
                        sel.os.textContent = osName; // ideal: dedicated line
                    } else if (sel.hint) {
                        // Fallback: append on a new line under the hint if no dedicated element exists
                        sel.hint.textContent = `${subtitle}\n${osName}`;
                    }
                }
            } else {
                if (sel.os) sel.os.textContent = '';
            }
        } catch {
            if (sel.os) sel.os.textContent = '';
        } finally {
            inFlight = false;
        }
    }

    // ---- Polling control (pause when tab is hidden) ----
    const POLL_MS = 30000;
    let pollTimer = null;

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(checkOnce, POLL_MS);
    }
    function stopPolling() {
        if (!pollTimer) return;
        clearInterval(pollTimer);
        pollTimer = null;
    }
    function handleVisibility() {
        if (document.hidden) {
            stopPolling();
        } else {
            checkOnce();
            startPolling();
        }
    }

    // ---- Boot: initial check when DOM is ready ----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            checkOnce();
            startPolling();
        }, { once: true });
    } else {
        checkOnce();
        startPolling();
    }

    // ---- Listen to your custom events to refresh immediately ----
    window.addEventListener('profile:changed', checkOnce);
})();

