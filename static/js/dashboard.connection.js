// static/js/dashboard.connection.js
// Shows active profile + SSH status on the Dashboard (+ OS name below)

(() => {
    // ---- DOM refs (safe even if elements are missing) ----
    const sel = {
        dot: document.getElementById('dash-conn-dot'),
        text: document.getElementById('dash-conn-text'),
        hint: document.getElementById('dash-conn-hint'),
        // If you add this element in your HTML, OS will be written here on its own line.
        // Example in HTML near your connection row:
        //   <div id="dash-conn-hint"></div>
        //   <div id="dash-conn-os" class="muted"></div>
        os: document.getElementById('dash-conn-os'),
    };

    // ---- API endpoints ----
    const API = {
        listProfiles: '/profiles/list',
        checkStatus: (id) => `/check-ssh-status?profile_id=${encodeURIComponent(id)}`,
        osInfo: '/system/os'
    };

    // ---- UI state helper ----
    function setState({ color = 'red', text = 'No connection', hint = '' }) {
        if (sel.dot) {
            sel.dot.classList.remove('green', 'red', 'yellow');
            sel.dot.classList.add(color);
            sel.dot.setAttribute('aria-label', text);
            sel.dot.setAttribute('title', hint || text);
        }
        if (sel.text) sel.text.textContent = text;
        if (sel.hint) sel.hint.textContent = hint;
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
            setState({
                color: offline ? 'red' : 'yellow',
                text: offline ? 'Offline' : `Checking ${p.name}`,
                hint: offline ? 'Browser is offline' : subtitle
            });
            if (sel.os) sel.os.textContent = '';

            if (offline) return;

            const j = await fetchJSON(API.checkStatus(p.id)).catch(err => {
                setState({ color: 'red', text: 'No connection', hint: `${subtitle} (${err.message})` });
                return null;
            });
            if (!j) return;

            const connected = Boolean(j.connected) || Boolean(j.ok);
            if (connected) {
                setState({ color: 'green', text: 'Connected', hint: subtitle });

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
                setState({ color: 'red', text: 'No connection', hint: subtitle });
                if (sel.os) sel.os.textContent = '';
            }
        } catch {
            if (sel.text && sel.text.textContent === '') {
                setState({ color: 'red', text: 'No connection', hint: '(unexpected error)' });
            }
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
    window.addEventListener('profile:saved', checkOnce);

    // ---- Pause/resume polling when tab visibility changes ----
    document.addEventListener('visibilitychange', handleVisibility);

    // ---- Optional: refresh when coming back online ----
    window.addEventListener('online', checkOnce);
})();
