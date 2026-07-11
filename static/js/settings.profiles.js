// static/js/settings.profiles.js
// SSH Profiles UI (arbejder imod routes/profiles.py)

(() => {
    const API_BASE = '/profiles';
    const FETCH_TIMEOUT_MS = 15000;

    // --- smutvej til elementer (accepterer gammel/ny id-navngivning) ---
    const byId = (primary, fallback) =>
        document.getElementById(primary) || (fallback ? document.getElementById(fallback) : null);

    // UI
    const sel = byId('ssh_profile_select');
    const btnNew = byId('btn-new-profile', 'profile-new-btn');
    const btnDup = byId('btn-duplicate-profile', 'profile-dup-btn');
    const btnRen = byId('btn-rename-profile', 'profile-rename-btn');
    const btnDel = byId('btn-delete-profile', 'profile-delete-btn');
    const btnTest = byId('btn-test-profile', 'profile-test-btn');
    const btnSave = byId('btn-save-profile', 'profile-save-btn');
    const sectionToggles = [
        { root: byId('ssh-profiles-section'), body: byId('ssh-profiles-body'), btn: byId('ssh-profiles-toggle'), key: 'settings.ssh-profiles.collapsed' },
        { root: byId('glances-section'), body: byId('glances-body'), btn: byId('glances-toggle'), key: 'settings.glances.collapsed' },
        { root: byId('firewall-section'), body: byId('firewall-body'), btn: byId('firewall-toggle'), key: 'settings.firewall.collapsed' },
        { root: byId('terminal-section'), body: byId('terminal-body'), btn: byId('terminal-toggle'), key: 'settings.terminal.collapsed' },
    ];

    const host = byId('pi_host');
    const user = byId('pi_user');
    const auth = byId('auth_method');
    const keyp = byId('ssh_key_path');
    const pass = byId('password');
    const pid = byId('profile_id');

    // key helpers
    const btnGenKey = byId('btn-gen-key');
    const btnRepairKey = byId('btn-repair-key');
    const btnInstallKey = byId('btn-install-key');
    const btnDeleteKey = byId('btn-delete-key');
    const keyStatus = byId('ssh-key-status');

    const keyBox = byId('key_fields');
    const passBox = byId('password_field');

    // ---- Connection status helpers (mikro-patch) -------------------------
    const connBox = byId('connection-status');
    function renderConnStatus(isOk) {
        if (!connBox) return;
        const html = `
            <div class="status-indicator">
                <span class="dot ${isOk ? 'dot-green' : 'dot-red'}"></span>
                ${isOk ? 'Connected to Linux' : 'No connection to Linux'}
            </div>`;
        connBox.innerHTML = html;
    }
    async function refreshConnectionStatus(profileId, reason = 'manual') {
        try {
            // Hvis siden har en global checker (fra settings.ssh-status.js), så brug den også
            if (typeof window.checkSshStatus === 'function') {
                window.checkSshStatus({ profileId: profileId || (sel?.value || ''), reason });
            }
            // Fallback direkte mod dit endpoint (så status opdateres nu og her)
            const q = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
            const res = await fetch(`/check-ssh-status${q}`, { method: 'GET' });
            let ok = false;
            if (res.ok) {
                const data = await res.json().catch(() => ({}));
                // Accepter både {ok:true} og {connected:true}
                ok = !!(data && (data.ok || data.connected));
            }
            renderConnStatus(ok);
            return ok;
        } catch (_) {
            renderConnStatus(false);
            return false;
        }
    }
    // ---------------------------------------------------------------------

    // Dynamisk “Detect”-knap og kandidat-dropdown ved nøglefeltet
    let btnDetectKey = null;
    let selCandidates = null;

    function bindCollapsibleSections() {
        for (const section of sectionToggles) {
            if (!section.root || !section.body) continue;
            let stored = null;
            try { stored = localStorage.getItem(section.key); } catch { stored = null; }
            let collapsed = stored === null ? true : stored === '1';
            const apply = (isCollapsed, persist = true) => {
                collapsed = !!isCollapsed;
                section.body.style.display = collapsed ? 'none' : '';
                if (section.btn) section.btn.textContent = collapsed ? 'Expand' : 'Collapse';
                if (persist) {
                    try { localStorage.setItem(section.key, collapsed ? '1' : '0'); } catch {}
                }
            };
            apply(collapsed, stored !== null);
            if (section.btn) {
                section.btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    apply(!collapsed);
                });
            }
            section.root.querySelector('.section-toggle')?.addEventListener('click', (e) => {
                if (e.target.closest('button')) return;
                apply(!collapsed);
            });
        }
    }

    function syncCollapsibleDefaults({ hasProfiles = false, connected = false } = {}) {
        const sshSection = sectionToggles.find(s => s.key === 'settings.ssh-profiles.collapsed');
        if (!sshSection || !sshSection.body) return;
        let stored = null;
        try { stored = localStorage.getItem(sshSection.key); } catch { stored = null; }
        if (stored !== null) return;
        const shouldOpen = !hasProfiles || !connected;
        sshSection.body.style.display = shouldOpen ? '' : 'none';
        if (sshSection.btn) sshSection.btn.textContent = shouldOpen ? 'Collapse' : 'Expand';
        try { localStorage.setItem(sshSection.key, shouldOpen ? '0' : '1'); } catch {}
    }
    function ensureKeyHelpersUI() {
        if (!keyp || !keyp.parentNode) return;

        // Detect-knap
        if (!btnDetectKey) {
            btnDetectKey = document.createElement('button');
            btnDetectKey.type = 'button';
            btnDetectKey.id = 'btn-detect-key';
            btnDetectKey.textContent = 'Detect';
            btnDetectKey.className = 'btn btn-secondary';
            btnDetectKey.style.marginLeft = '8px';
            keyp.parentNode.insertBefore(btnDetectKey, keyp.nextSibling);
        }

        // Kandidat-dropdown (vises kun når der er >1 kandidater)
        if (!selCandidates) {
            selCandidates = document.createElement('select');
            selCandidates.id = 'ssh_key_candidates';
            selCandidates.className = 'form-select';
            selCandidates.style.display = 'none';
            selCandidates.style.marginTop = '6px';
            keyp.parentNode.insertBefore(selCandidates, btnDetectKey.nextSibling);
        }
    }

    // cache af det vi har hentet fra serveren
    let cache = { profiles: [], active_profile_id: null };

    // ---------- små helpers ----------
    function setBusy(el, busy, labelWhileBusy) {
        if (!el) return;
        if (busy) {
            el.dataset._origText = el.textContent;
            if (labelWhileBusy) el.textContent = labelWhileBusy;
            el.disabled = true;
            el.classList.add('is-loading');
        } else {
            if (el.dataset._origText && el.dataset.locked !== 'true') el.textContent = el.dataset._origText;
            el.disabled = el.dataset.locked === 'true';
            el.classList.remove('is-loading');
        }
    }

    async function withBusy(btn, label, fn) {
        setBusy(btn, true, label);
        try { return await fn(); }
        finally { setBusy(btn, false); }
    }

    function applyAuthVisibility() {
        if (!auth || !keyBox || !passBox) return;
        keyBox.style.display = (auth.value === 'key') ? '' : 'none';
        passBox.style.display = (auth.value === 'password') ? '' : 'none';
        if (auth.value === 'key') ensureKeyHelpersUI();
    }

    function findProfile(id) {
        return cache.profiles.find(p => p.id === id) || null;
    }

    function getSelectedProfile() {
        if (!sel) return null;
        return findProfile(sel.value);
    }

    function setFormFromProfile(p) {
        if (!p) return;
        if (host) host.value = p.pi_host || '';
        if (user) user.value = p.pi_user || '';
        if (auth) auth.value = p.auth_method || 'key';
        if (keyp) keyp.value = p.ssh_key_path || '';
        if (pass) pass.value = p.password || '';
        if (pid) pid.value = p.id;
        applyAuthVisibility();
        // Når vi viser "SSH Key", så autoudfyld hvis tomt
        if (auth && auth.value === 'key') {
            maybeSuggestKeyPath(/*onlyIfEmpty=*/true).catch(() => { });
        }
    }

    function clearSelectWithMessage(msg) {
        if (!sel) return;
        sel.innerHTML = '';
        const opt = document.createElement('option');
        opt.value = '__none__';
        opt.disabled = true;
        opt.textContent = msg || 'No profiles yet';
        sel.appendChild(opt);
        if (pid) pid.value = '';
    }

    function rebuildSelect(selectId) {
        if (!sel) return;

        sel.innerHTML = '';
        if (!cache.profiles.length) {
            clearSelectWithMessage('No profiles yet');
            return;
        }

        // opbyg optioner uden innerHTML (sikrer korrekt escaping)
        for (const p of cache.profiles) {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name || 'Unnamed';
            sel.appendChild(opt);
        }

        const wanted = selectId || cache.active_profile_id || cache.profiles[0].id;
        sel.value = wanted;
        const chosen = findProfile(wanted) || cache.profiles[0];
        setFormFromProfile(chosen);
    }

    function fetchWithTimeout(url, init = {}) {
        const controller = new AbortController();
        const t = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
        const merged = { ...init, signal: controller.signal };
        return fetch(url, merged).finally(() => clearTimeout(t));
    }

    async function api(path, method = 'GET', body = null) {
        const init = { method, headers: {} };
        if (body) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(body);
        }
        let res, data = null;
        try {
            res = await fetchWithTimeout(`${API_BASE}${path}`, init);
        } catch (err) {
            throw new Error(err?.name === 'AbortError' ? 'Request timed out' : (err?.message || 'Network error'));
        }

        try { data = await res.json(); } catch (_) { /* nogle endpoints kan være tomme */ }

        if (!res.ok) {
            const msg = (data && (data.error || data.message)) || `HTTP ${res.status}`;
            throw new Error(msg);
        }
        return data || { ok: true };
    }

    async function ensureAtLeastOneProfile() {
        if (cache.profiles.length) return;
        const { profile } = await api('/new', 'POST', { name: 'RaspberryPi' });
        cache.profiles = [profile];
        cache.active_profile_id = profile.id;
    }

    // ---------- Key-path suggestion ----------
    async function suggestKeyPathForCurrentProfile() {
        const id = pid?.value || sel?.value || '';
        const params = new URLSearchParams();
        if (id) params.set('id', id);
        const currentPath = (keyp?.value || '').trim();
        if (currentPath) params.set('path', currentPath);
        const q = params.toString() ? `?${params.toString()}` : '';
        return await api(`/suggest-key-path${q}`, 'GET');
    }

    function renderKeyStatus(status) {
        const st = status || {};
        const hasPrivate = !!st.private_exists;
        const validPrivate = !!st.private_valid;
        const hasPublicFile = !!st.public_exists;
        const validPublic = !!st.public_valid;
        if (btnGenKey) {
            btnGenKey.dataset.locked = validPrivate ? 'true' : 'false';
            btnGenKey.disabled = validPrivate;
            btnGenKey.textContent = hasPrivate && !validPrivate ? 'Replace invalid key' : (validPrivate ? 'Key already exists' : 'Generate key');
        }
        if (btnInstallKey) btnInstallKey.disabled = !(validPrivate && validPublic);
        if (btnRepairKey) btnRepairKey.style.display = (validPrivate && !validPublic) ? '' : 'none';
        if (btnDeleteKey) btnDeleteKey.style.display = (hasPrivate || hasPublicFile) ? '' : 'none';
        if (!keyStatus) return;
        if (hasPrivate && !validPrivate) {
            keyStatus.textContent = `Invalid SSH private-key file: ${st.path}. Delete it or replace it with a new key.`;
            keyStatus.style.color = '#dc3545';
        } else if (validPrivate && validPublic) {
            keyStatus.textContent = `✓ Existing SSH key found: ${st.path}`;
            keyStatus.style.color = '#35c46a';
        } else if (validPrivate && hasPublicFile) {
            keyStatus.textContent = `The public key does not match the private key: ${st.path}.pub`;
            keyStatus.style.color = '#d99b2b';
        } else if (validPrivate) {
            keyStatus.textContent = `SSH private key found, but the public key is missing: ${st.path}.pub`;
            keyStatus.style.color = '#d99b2b';
        } else {
            keyStatus.textContent = st.path ? `No SSH key exists yet at: ${st.path}` : 'No SSH key selected.';
            keyStatus.style.color = '';
        }
    }

    function populateCandidatesUI(candidates) {
        ensureKeyHelpersUI();
        if (!selCandidates) return;
        selCandidates.innerHTML = '';
        if (!candidates || candidates.length === 0) {
            selCandidates.style.display = 'none';
            return;
        }
        // Kun vis dropdown hvis der er flere valg end én
        if (candidates.length > 1) {
            const first = document.createElement('option');
            first.value = '';
            first.textContent = 'Choose an SSH key…';
            selCandidates.appendChild(first);
        }
        for (const c of candidates) {
            const opt = document.createElement('option');
            opt.value = c.path;
            const d = new Date((c.mtime || 0) * 1000);
            const when = isNaN(d.getTime()) ? '' : ` (${d.toLocaleDateString()} ${d.toLocaleTimeString()})`;
            opt.textContent = `${c.type || 'key'}: ${c.path}${when}`;
            selCandidates.appendChild(opt);
        }
        selCandidates.style.display = (candidates.length > 1) ? '' : 'none';
    }

    async function maybeSuggestKeyPath(onlyIfEmpty = true) {
        if (!keyp) return;
        try {
            let res = await suggestKeyPathForCurrentProfile();
            const configuredExists = !!res.key_status?.private_valid;
            const chosen = configuredExists ? res.key_status.path : (res.default || res.suggest_new || '');
            if (chosen && (!onlyIfEmpty || !(keyp.value || '').trim())) {
                keyp.value = chosen;
                res = await suggestKeyPathForCurrentProfile();
            }
            populateCandidatesUI(res.candidates || []);
            renderKeyStatus(res.key_status);
        } catch (e) {
            populateCandidatesUI([]);
            renderKeyStatus(null);
        }
    }

    // ---------- load ----------
    async function loadAllAndSelect(selectId = null) {
        const data = await api('/list');
        cache = {
            profiles: data.profiles || [],
            active_profile_id: data.active_profile_id || null
        };
        await ensureAtLeastOneProfile();
        rebuildSelect(selectId);
        const activeId = sel?.value || cache.active_profile_id || null;
        const connected = await refreshConnectionStatus(activeId, 'init');
        syncCollapsibleDefaults({ hasProfiles: cache.profiles.length > 0, connected });

        // Emit + tving status-check (vigtigt ved første load)
        window.dispatchEvent(new CustomEvent('profile:changed', { detail: { id: activeId } }));
    }

    // ---------- wire UI ----------
    sel?.addEventListener('change', async () => {
        const cur = getSelectedProfile();
        setFormFromProfile(cur);

        // Gør valgt profil aktiv i backenden (så andet legacy-kode kan læse den)
        let activeId = cur?.id || sel?.value || null;

        try {
            if (cur) await api('/set-active', 'POST', { id: cur.id });
        } catch (_) {
            // ikke kritisk
        } finally {
            // Sørg for at status bliver tjekket EFTER set-active
            window.dispatchEvent(new CustomEvent('profile:changed', { detail: { id: activeId } }));
            refreshConnectionStatus(activeId, 'profile-change');
        }

        // Når profil skiftes og auth=key, så foreslå nøgle hvis tomt
        if (auth && auth.value === 'key') {
            await maybeSuggestKeyPath(true);
        }
    });

    auth?.addEventListener('change', async () => {
        applyAuthVisibility();
        if (auth.value === 'key') {
            await maybeSuggestKeyPath(true);
        }
    });
    keyp?.addEventListener('change', () => maybeSuggestKeyPath(true));
    keyp?.addEventListener('blur', () => maybeSuggestKeyPath(true));
    applyAuthVisibility();
    bindCollapsibleSections();

    // ===== Key handling =====

    // Detect-knap: foreslå/scan nøgler og vis kandidater
    (function wireDetectButton() {
        ensureKeyHelpersUI();
        btnDetectKey?.addEventListener('click', async () => {
            await withBusy(btnDetectKey, 'Detecting…', async () => {
                await maybeSuggestKeyPath(false); // må gerne overskrive
            });
        });

        selCandidates?.addEventListener('change', () => {
            if (!selCandidates) return;
            const v = selCandidates.value || '';
            if (v && keyp) keyp.value = v;
        });
    })();

    // Generate an RSA keypair for this profile and store the path in the profile
    btnGenKey?.addEventListener('click', () => withBusy(btnGenKey, 'Generating…', async () => {
        const id = pid?.value || sel?.value;
        const cur = findProfile(id || '');
        if (!id || !cur) return alert('No profile selected.');
        const authBeforeGenerate = auth?.value || 'key';

        try {
            // Hvis feltet er tomt: hent forslag (så vi får pæn sti som id_<profilnavn>)
            let desiredPath = (keyp?.value || '').trim();
            if (!desiredPath) {
                try {
                    const res = await suggestKeyPathForCurrentProfile();
                    desiredPath = res.suggest_new || res.default || '';
                    if (desiredPath && keyp) keyp.value = desiredPath;
                } catch { /* no-op */ }
            }

            const body = { id };
            if (desiredPath) body.key_path = desiredPath;

            const discovery = await suggestKeyPathForCurrentProfile();
            if (discovery.key_status?.private_valid) {
                renderKeyStatus(discovery.key_status);
                alert('An SSH key already exists at this path. You can install the existing key on the host.');
                return;
            }

            if (discovery.key_status?.private_exists && !discovery.key_status?.private_valid) {
                const replace = confirm('The selected file is not a valid private SSH key. Replace this invalid file with a newly generated keypair?');
                if (!replace) return;
                body.overwrite = true;
            }

            const res = await api('/gen-key', 'POST', body);
            if (!res.ok && !res.private_key) {
                throw new Error(res.error || 'Failed to generate key');
            }

            const path = res.key_path || res.private_key;
            if (!path) throw new Error('No key path returned');

            if (keyp) keyp.value = path;

            // persist path så det hænger ved
            await api('/save', 'POST', { id, ssh_key_path: path, make_active: true });
            await loadAllAndSelect(id);
            // Behold det valgte auth-flow i UI, så brugeren kan fortsætte med SSH-key onboarding.
            if (auth) auth.value = authBeforeGenerate;
            applyAuthVisibility();
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id } }));
            refreshConnectionStatus(id, 'gen-key');
            alert('✔ Key generated and path saved.');
        } catch (e) {
            alert('Generate key failed: ' + e.message);
        }
    }));

    btnRepairKey?.addEventListener('click', () => withBusy(btnRepairKey, 'Repairing…', async () => {
        const id = pid?.value || sel?.value;
        const selectedKeyPath = (keyp?.value || '').trim();
        if (!id || !selectedKeyPath) return alert('No SSH key selected.');
        try {
            const result = await api('/repair-key', 'POST', { id, key_path: selectedKeyPath });
            await maybeSuggestKeyPath(true);
            alert(result.repaired ? '✔ Public key rebuilt from the existing private key.' : 'Repair not needed. The keypair is already valid.');
        } catch (e) {
            alert('Repair key failed: ' + e.message);
        }
    }));

    btnDeleteKey?.addEventListener('click', () => withBusy(btnDeleteKey, 'Deleting…', async () => {
        const id = pid?.value || sel?.value;
        const selectedKeyPath = (keyp?.value || '').trim();
        if (!id || !selectedKeyPath) return alert('No SSH key selected.');
        const warning = `Delete this local SSH key?\n\n${selectedKeyPath}\n\nThis cannot be undone. Hosts using this key may require password login again.`;
        if (!confirm(warning)) return;
        try {
            await api('/delete-key', 'POST', { id, key_path: selectedKeyPath });
            await loadAllAndSelect(id);
            alert('Local SSH key deleted. The profile has been switched back to Password.');
        } catch (e) {
            alert('Delete key failed: ' + e.message);
        }
    }));

    // Install the public key on the remote host – ask for password (not stored)
    btnInstallKey?.addEventListener('click', () => withBusy(btnInstallKey, 'Installing…', async () => {
        const id = pid?.value || sel?.value;
        const cur = findProfile(id || '');
        if (!id || !cur) return alert('No profile selected.');

        const h = (host?.value || cur.pi_host || '').trim();
        const u = (user?.value || cur.pi_user || '').trim();
        if (!h || !u) return alert('Fill Host and Username first, then Save profile.');

        if (auth?.value === 'key' && keyp && !(keyp.value || '').trim()) {
            await maybeSuggestKeyPath(false);
        }

        const pw = prompt(`Password for ${(u)}@${(h)}\n(only used once for installation; not stored)`, '');
        if (pw === null) return; // afbrudt

        try {
            const selectedKeyPath = (keyp?.value || '').trim();
            const res = await api('/install-key', 'POST', {
                id,
                password: pw,
                key_path: selectedKeyPath,
                pi_host: h,
                pi_user: u
            });
            if (!res.ok && !res.installed_to) throw new Error(res.error || 'Failed to install key');
            const keyTest = await api('/test', 'POST', {
                pi_host: h,
                pi_user: u,
                auth_method: 'key',
                ssh_key_path: selectedKeyPath,
                password: '',
                strict_auth: true
            });
            if (!keyTest.ok) {
                alert('The public key was copied, but key-only login could not be verified. The profile remains on Password authentication.');
                return;
            }
            await api('/save', 'POST', {
                id,
                pi_host: h,
                pi_user: u,
                auth_method: 'key',
                ssh_key_path: selectedKeyPath,
                make_active: true
            });
            await loadAllAndSelect(id);
            alert('✔ Public key installed on host.\n' + (res.installed_to || 'authorized_keys'));
            // efter nøgle-installation kan status ændre sig → trig re-check
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id } }));
            refreshConnectionStatus(id, 'install-key');
        } catch (e) {
            alert('Install key failed: ' + e.message);
        }
    }));

    // ---------- actions ----------
    btnNew?.addEventListener('click', () => withBusy(btnNew, 'Creating…', async () => {
        try {
            const name = (prompt('New profile name:', 'New profile') || '').trim();
            if (!name) return;
            const { profile } = await api('/new', 'POST', { name });
            await loadAllAndSelect(profile.id);
            window.dispatchEvent(new CustomEvent('profile:changed', { detail: { id: profile.id } }));
            refreshConnectionStatus(profile.id, 'new');
        } catch (e) {
            alert('Could not create profile: ' + e.message);
        }
    }));

    btnDup?.addEventListener('click', () => withBusy(btnDup, 'Duplicating…', async () => {
        const cur = getSelectedProfile(); if (!cur) return;
        try {
            const { profile: created } = await api('/new', 'POST', { name: `${cur.name || 'Profile'} (copy)` });
            await api('/save', 'POST', {
                id: created.id,
                name: created.name,
                pi_host: cur.pi_host || '',
                pi_user: cur.pi_user || '',
                auth_method: cur.auth_method || 'key',
                ssh_key_path: cur.ssh_key_path || '',
                password: cur.password || '',
                make_active: true
            });
            await loadAllAndSelect(created.id);
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id: created.id } }));
            refreshConnectionStatus(created.id, 'duplicate');
            alert('✔️ Profile duplicated.');
        } catch (e) {
            alert('Could not duplicate: ' + e.message);
        }
    }));

    btnRen?.addEventListener('click', () => withBusy(btnRen, 'Renaming…', async () => {
        const cur = getSelectedProfile(); if (!cur) return;
        const name = (prompt('Rename profile:', cur.name || 'Profile') || '').trim();
        if (!name) return;
        try {
            await api('/save', 'POST', {
                id: cur.id,
                name,
                pi_host: cur.pi_host || '',
                pi_user: cur.pi_user || '',
                auth_method: cur.auth_method || 'key',
                ssh_key_path: cur.ssh_key_path || '',
                password: cur.password || ''
            });
            await loadAllAndSelect(cur.id);
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id: cur.id } }));
            refreshConnectionStatus(cur.id, 'rename');
            alert('✔️ Profile renamed.');
        } catch (e) {
            alert('Could not rename: ' + e.message);
        }
    }));

    btnDel?.addEventListener('click', () => withBusy(btnDel, 'Deleting…', async () => {
        const cur = getSelectedProfile(); if (!cur) return;
        if (!confirm(`Delete profile "${cur.name || 'Profile'}"?`)) return;
        try {
            await api('/delete', 'POST', { id: cur.id });
            await loadAllAndSelect(null);
            const nowActive = sel?.value || null;
            window.dispatchEvent(new CustomEvent('profile:changed', { detail: { id: nowActive } }));
            refreshConnectionStatus(nowActive, 'delete');
            alert('✔️ Profile deleted.');
        } catch (e) {
            alert('Could not delete: ' + e.message);
        }
    }));

    btnTest?.addEventListener('click', () => withBusy(btnTest, 'Testing…', async () => {
        try {
            const body = {
                pi_host: (host?.value || '').trim(),
                pi_user: (user?.value || '').trim(),
                auth_method: auth?.value || 'key',
                ssh_key_path: (keyp?.value || '').trim(),
                password: pass?.value || '',
                quick: 1
            };
            const res = await api('/test', 'POST', body);
            alert(res.ok ? '✅ SSH connection OK!' : ('❌ ' + (res.error || 'Failed')));
            // trig re-check af UI
            const activeId = sel?.value || null;
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id: activeId } }));
            refreshConnectionStatus(activeId, 'test');
        } catch (e) {
            alert('Test failed: ' + e.message);
        }
    }));

    // Gem aktuelle felter ind i den valgte profil (og gør den aktiv)
    btnSave?.addEventListener('click', () => withBusy(btnSave, 'Saving…', async () => {
        const id = pid?.value || sel?.value;
        if (!id || id === '__none__') return alert('No profile selected.');
        const cur = findProfile(id) || {};
        try {
            if (auth?.value === 'key') {
                const discovery = await suggestKeyPathForCurrentProfile();
                const ready = discovery.key_status?.private_valid && discovery.key_status?.public_valid;
                if (!ready) {
                    renderKeyStatus(discovery.key_status);
                    alert('SSH Key cannot be saved yet. Repair or generate a complete keypair first.');
                    return;
                }
                const keyTest = await api('/test', 'POST', {
                    pi_host: (host?.value || '').trim(),
                    pi_user: (user?.value || '').trim(),
                    auth_method: 'key',
                    ssh_key_path: (keyp?.value || '').trim(),
                    password: '',
                    strict_auth: true
                });
                if (!keyTest.ok) {
                    alert('SSH Key login is not ready on the Linux host. Click "Install key on host" before saving the profile as SSH Key.');
                    return;
                }
            }
            await api('/save', 'POST', {
                id,
                name: cur.name || 'Profile',
                pi_host: (host?.value || '').trim(),
                pi_user: (user?.value || '').trim(),
                auth_method: auth?.value || 'key',
                ssh_key_path: (keyp?.value || '').trim(),
                password: pass?.value || '',
                make_active: true
            });
            await loadAllAndSelect(id);
            window.dispatchEvent(new CustomEvent('profile:saved', { detail: { id } }));
            refreshConnectionStatus(id, 'save');
            alert('✔️ Profile saved.');
        } catch (e) {
            alert('Save failed: ' + e.message);
        }
    }));

    // initial load
    loadAllAndSelect().catch(err => {
        console.error(err);
        clearSelectWithMessage('Unable to load profiles');
        // hvis noget fejler, vis som "ikke forbundet"
        renderConnStatus(false);
    });
})();
