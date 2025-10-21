// static/js/updates.js
// Incremental "Software Updates" rendering using SSE + per-package enrichment
// Buttons remain disabled until ALL items are found AND enriched.

// ---- DOM refs ----
const out = document.getElementById('out');
const badgeReboot = document.getElementById('badge-reboot');
const btnReboot = document.getElementById('btn-reboot');

const bodyEl = document.getElementById('updates-body');
const emptyEl = document.getElementById('updates-empty');

const btnInstallAll = document.getElementById('btn-install-all');
const btnInstallSec = document.getElementById('btn-install-security');
const btnFull = document.getElementById('btn-full') || document.querySelector('[data-action="full_noob_update"]');
const btnToggleAdvanced = document.getElementById('btn-toggle-advanced');
const advancedBox = document.getElementById('advanced-actions');
// Logs panel
const logsPanel = document.getElementById('logs-panel');
const logsToggle = document.getElementById('logs-toggle');
const logsList = document.getElementById('logs-list');
const logsCount = document.getElementById('logs-count');
// Output collapse
const btnToggleOutput = document.getElementById('btn-toggle-output');

const searchBox = document.getElementById('search-indicator');
const searchText = document.getElementById('search-text');
const searchTimer = document.getElementById('search-timer');

// NEW: count badge + connection/OS line
const updatesCount = document.getElementById('updates-count');
const connUserHost = document.getElementById('conn-userhost');
const connOS = document.getElementById('conn-os');

// Hvilke UI-handlinger kræver sudo (på Mint m.fl.)
// Hvilke UI-handlinger kræver sudo (på Mint m.fl.)
const ACTIONS_REQUIRE_SUDO = new Set([
    'apt_update',
    'apt_upgrade',
    'apt_full_upgrade',
    'full_noob_update',
    'snap_refresh'
]);

// Session sudo cache (memory only; cleared on reload)
let SUDO_PW_CACHE = null;
// Remember packages installed this session (to grey out buttons after rescan)
let INSTALLED_SET = new Set();
// Ensure a progress bar exists inside indicator
let prog = searchBox.querySelector('.progress');
if (!prog) {
    prog = document.createElement('div');
    prog.className = 'progress';
    searchBox.appendChild(prog);
}

const APT_WARNING = 'apt does not have a stable CLI interface';
const PHASING_MARKER = 'deferred due to phasing';

let tickTimer = null;
let tickProgress = null;
let pollProgressTimer = null;
let pollLogTimer = null;
let currentRunId = null;
let lastLogTextLen = 0;

// Track counts so we only enable actions when enrichment is 100% done
let totalExpected = 0;
let enrichedCount = 0;
let discoveredCount = 0;

// Busy toggle for primary action buttons (full/security/all)
const actionable = [btnFull, btnInstallSec, btnInstallAll].filter(Boolean);
function setBusy(busy) {
    actionable.forEach(b => {
        if (!b) return;
        b.disabled = !!busy;
        b.classList.toggle('is-disabled', !!busy);
        if (busy) b.setAttribute('aria-busy', 'true'); else b.removeAttribute('aria-busy');
    });
}

function ts() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function append(text) {
    if (!out) return;
    out.textContent = text;
    out.scrollTop = out.scrollHeight;
    const low = (text || '').toLowerCase();
    const warn = document.getElementById('apt-warning-note');
    const phase = document.getElementById('phasing-note');
    if (warn) warn.style.display = (text || '').includes(APT_WARNING) ? 'block' : 'none';
    if (phase) phase.style.display = low.includes(PHASING_MARKER) ? 'block' : 'none';
}

async function run(action) {
    append('Running: ' + action + ' ...');
    setBusy(true);

    // Evt. sudo password prompt (kun for bestemte handlinger)
    let sudo_password = '';
    if (ACTIONS_REQUIRE_SUDO.has(action)) {
        if (SUDO_PW_CACHE == null) {
            const typed = window.prompt('Enter sudo password (will not be stored):', '');
            if (typed === null) { append('Cancelled.'); setBusy(false); return; }
            SUDO_PW_CACHE = typed;
        }
        sudo_password = SUDO_PW_CACHE;
    }
    try {
        const r = await fetch('/updates/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, sudo_password })
        });
        const j = await r.json();
        if (!j.ok) {
            append('Error: ' + (j.error || 'unknown'));
            return;
        }
        if (j.run_id) {
            currentRunId = j.run_id;
            window.localStorage.setItem('upd.run_id', currentRunId);
            lastLogTextLen = 0;
            startProgressPolling(currentRunId);
            startLogPolling(currentRunId);
        } else {
            const text = `${(j.stdout || '').trim()}\n${(j.stderr ? '\n[stderr]\n' + j.stderr : '')}\n\n[exit ${j.rc}]`;
            append(text);
        }
    } catch (e) {
        append('Network error: ' + e);
    } finally {
        // slet password reference i JS (ikke strengt nødvendigt, men pænt)
        sudo_password = '';
        setBusy(false);
    }
}

async function rebootNow() {
    if (!confirm('Reboot the remote machine now?')) return;
    await run('reboot_now');
}

async function checkReboot() {
    try {
        const r = await fetch('/updates/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'reboot_required' })
        });
        const j = await r.json();
        const need = (j.ok && (j.stdout || '').includes('REBOOT_REQUIRED'));
        if (badgeReboot) badgeReboot.style.display = need ? 'inline-block' : 'none';
        if (btnReboot) btnReboot.disabled = !need;
    } catch (e) { /* noop */ }
}

function sevPill(security, urgency) {
    if (security) return '<span class="pill sec">Security</span>';
    if (urgency) return '<span class="pill">' + String(urgency).charAt(0).toUpperCase() + String(urgency).slice(1) + '</span>';
    return '<span class="pill">Normal</span>';
}

// Robust HTML/attr escaping
function escapeHTML(s) {
    s = (s == null ? '' : String(s));
    return s
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
function escapeAttr(s) {
    s = (s == null ? '' : String(s));
    return s.replace(/"/g, '&quot;');
}
function stripAnsi(s) {
    s = (s == null ? '' : String(s));
    return s.replace(/\x1B\[[0-9;]*[A-Za-z]/g, '');
}

// Detail row template
function rowDetail(pkg) {
    const cves = (pkg.cves || []).map(c =>
        `<a href="https://ubuntu.com/security/${c}" target="_blank" rel="noopener">${c}</a>`
    ).join(', ');
    const cl = (pkg.links && pkg.links.changelog)
        ? `<a href="${pkg.links.changelog}" target="_blank" rel="noopener">Changelog</a>` : '';
    const repo = pkg.repo || pkg.suite || '-';
    const verLine = (pkg.current || '-') + ' → ' + (pkg.candidate || '-');

    return `
  <tr class="detail">
    <td colspan="6" style="background:#0f111b; border-top:1px solid #22263a; padding:12px;">
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px;">
        <div><strong>Installed → Candidate:</strong> ${escapeHTML(verLine)}</div>
        <div><strong>Repo/Suite:</strong> ${escapeHTML(repo)}</div>
        <div><strong>Architecture:</strong> ${escapeHTML(pkg.arch || '-')}</div>
        <div><strong>CVEs:</strong> ${cves || '-'}</div>
        <div><strong>Links:</strong> ${cl || '-'}</div>
      </div>
      ${pkg.summary ? `<div style="margin-top:8px; opacity:.9;">${escapeHTML(pkg.summary)}</div>` : ''}
    </td>
  </tr>`;
}

// Skeleton row
function pkgRowSkeleton(name, candidate, arch, i) {
    const clean = stripAnsi(name);
    const version = candidate || "-";
    const sum = "Loading details…";
    return `
  <tr class="pkg" data-idx="${i}" data-name="${escapeAttr(clean)}" style="cursor:pointer;">
    <td>${escapeHTML(clean)}</td>
    <td>${escapeHTML(version)}</td>
    <td><span class="pill muted">…</span></td>
    <td title="${escapeAttr(sum)}">${escapeHTML(sum)}</td>
    <td><button class="btn small" data-install data-name="${escapeAttr(clean)}" disabled>Install</button></td>
  </tr>`;
}

// Enrich skeleton row
function enrichRow(tr, pkg) {
    const td = tr.querySelectorAll('td');
    td[1].textContent = pkg.candidate || '-';
    td[2].innerHTML = sevPill(!!pkg.security, pkg.urgency);
    const sum = pkg.summary || '';
    td[3].setAttribute('title', sum ? escapeAttr(sum) : '');
    td[3].textContent = sum ? (sum.length > 140 ? sum.slice(0, 140) + '…' : sum) : '';

    // Detail row
    let d = tr.nextElementSibling;
    if (!d || !d.classList.contains('detail')) {
        tr.insertAdjacentHTML('afterend', rowDetail(pkg));
        d = tr.nextElementSibling;
        d.style.display = 'none';
    } else {
        d.outerHTML = rowDetail(pkg);
        d = tr.nextElementSibling;
        d.style.display = 'none';
    }
}

function wireToggle(tr) {
    tr.addEventListener('click', () => {
        const n = tr.nextElementSibling;
        if (n && n.classList.contains('detail')) {
            n.style.display = (n.style.display === 'none' ? '' : 'none');
        }
    });
}

// ---- Indicator control ----
function startIndicator() {
    bodyEl.innerHTML = `<tr><td colspan="4" class="muted" style="padding:14px;">Searching for updates…</td></tr>`;
    emptyEl.style.display = 'none';
    disableInstallButtons(true);

    // reset count badge
    if (updatesCount) { updatesCount.style.display = 'none'; updatesCount.textContent = ''; }

    searchBox.style.display = 'inline-flex';
    searchText.textContent = 'Searching for updates…';
    clearInterval(tickTimer); clearInterval(tickProgress);

    let sec = 0; searchTimer.textContent = '(0s)';
    tickTimer = setInterval(() => { sec += 1; searchTimer.textContent = `(${sec}s)`; }, 1000);

    setProgress(10);
    const stages = [30, 55, 78];
    let i = 0;
    tickProgress = setInterval(() => { if (i < stages.length) { setProgress(stages[i]); i++; } }, 3500);
}

function setProgress(p) { prog.style.setProperty('--w', Math.max(0, Math.min(100, p)) + '%'); }

function stopIndicator(summary) {
    clearInterval(tickTimer); clearInterval(tickProgress);
    setProgress(100);
    const spin = searchBox.querySelector('.spinner');
    if (spin) spin.style.display = 'none';
    searchText.textContent = summary || 'Updated';
    searchTimer.textContent = '';
    setTimeout(() => {
        searchBox.style.display = 'none';
        if (spin) spin.style.display = '';
        setProgress(0);
    }, 1000);
}

function showEnriching() {
    // Switch indicator to enrichment phase (keeps spinner up)
    searchBox.style.display = 'inline-flex';
    searchText.textContent = `Enriching details… (${enrichedCount}/${totalExpected})`;
    setProgress(Math.min(95, 40 + Math.floor((enrichedCount / Math.max(1, totalExpected)) * 55)));
}

// ---- SSE scan ----
let currentSource = null;
let seenNames = new Set();
let rowIndex = 0;

function closeSSE() {
    if (currentSource) {
        try { currentSource.close(); } catch (e) { }
        currentSource = null;
    }
}

async function enrichAsync(name, tr) {
    try {
        const r = await fetch(`/updates/pkg/${encodeURIComponent(name)}`);
        const j = await r.json();
        if (!j.ok) return;

        const arch = tr.getAttribute('data-arch') || '';
        j.arch = j.arch || arch;

        enrichRow(tr, j);
    } catch (e) {
        // ignore
    } finally {
        enrichedCount += 1;
        showEnriching();
        maybeEnableSecurityButton();
        if (totalExpected > 0 && enrichedCount >= totalExpected) {
            // All details are ready — now we can enable install buttons and stop the indicator
            disableInstallButtons(false);
            stopIndicator(`Found ${totalExpected} updates • ${ts()}`);
        }
    }
}

function startSSEScan() {
    closeSSE();
    startIndicator();
    seenNames = new Set();
    rowIndex = 0;
    totalExpected = 0;
    enrichedCount = 0;
    discoveredCount = 0;
    bodyEl.innerHTML = '';

    currentSource = new EventSource('/updates/scan/stream');

    currentSource.addEventListener('status', (ev) => {
        try {
            const data = JSON.parse(ev.data || '{}');
            if (data.stage === 'apt_update') {
                searchText.textContent = 'Refreshing package index…';
                setProgress(20);
            } else if (data.stage === 'list_upgradable') {
                searchText.textContent = 'Scanning upgradable packages…';
                setProgress(40);
            }
        } catch (e) { }
    });

    currentSource.addEventListener('pkg', (ev) => {
        try {
            const data = JSON.parse(ev.data || '{}');
            const rawName = data.name;
            const name = stripAnsi(rawName);
            if (!name || seenNames.has(name)) return;

            seenNames.add(name);
            discoveredCount = seenNames.size;

            const html = pkgRowSkeleton(name, data.candidate, data.arch, rowIndex++);
            bodyEl.insertAdjacentHTML('beforeend', html);

            const tr = bodyEl.lastElementChild.previousElementSibling?.classList.contains('pkg')
                ? bodyEl.lastElementChild.previousElementSibling
                : bodyEl.lastElementChild;

            if (tr && tr.classList.contains('pkg')) {
                tr.setAttribute('data-arch', data.arch || '');
                wireToggle(tr);
                // Enrich row in background
                enrichAsync(name, tr);

                // If this package was installed earlier in this session, grey out its button
                try {
                    if (INSTALLED_SET.has(name.toLowerCase())) {
                        const b = tr.querySelector('[data-install]');
                        if (b) { b.disabled = true; b.textContent = 'Installed'; b.classList.add('is-disabled'); }
                    }
                } catch (e) { }\n            searchText.textContent = `Scanning… (${discoveredCount})`;
            setProgress(Math.min(90, 40 + discoveredCount * 2));
        } catch (e) { }
    });

    currentSource.addEventListener('done', (ev) => {
        try {
            const data = JSON.parse(ev.data || '{}');
            totalExpected = data.count || discoveredCount || 0;

            // Show final count badge
            if (updatesCount) {
                updatesCount.style.display = 'inline-block';
                updatesCount.textContent = totalExpected > 0 ? `Found ${totalExpected}` : 'No updates';
            }

            if (!totalExpected) {
                bodyEl.innerHTML = '';
                emptyEl.style.display = '';
                disableInstallButtons(true);
                stopIndicator('No updates (' + ts() + ')');
            } else {
                // Move to “enriching” phase: keep spinner until enrichedCount == totalExpected
                showEnriching();
                // Actions stay disabled until enrichment complete
                disableInstallButtons(true);
            }
        } finally {
            closeSSE();
        }
    });

    currentSource.addEventListener('error', (ev) => {
        try {
            const data = JSON.parse(ev.data || '{}');
            bodyEl.innerHTML = `<tr><td colspan="4" style="padding:12px; color:#ffb3b3;">Error: ${escapeHTML(data.message || 'unknown')}</td></tr>`;
        } catch (e) {
            bodyEl.innerHTML = `<tr><td colspan="4" style="padding:12px; color:#ffb3b3;">Stream error</td></tr>`;
        } finally {
            disableInstallButtons(true);
            stopIndicator('Error at ' + ts());
            closeSSE();
        }
    });
}
function disableInstallButtons(disabled) {
    if (btnInstallAll) btnInstallAll.disabled = !!disabled;
    if (btnInstallSec) btnInstallSec.disabled = !!disabled;
    if (btnFull) btnFull.disabled = !!disabled;
    const rows = bodyEl ? bodyEl.querySelectorAll('[data-install]') : [];
    rows.forEach(b => { try { b.disabled = !!disabled; } catch (e) {} });
}
function maybeEnableSecurityButton() {
    // Enable security button only after ALL enriched AND at least one sec=true
    if (btnInstallSec && btnInstallSec.disabled && totalExpected > 0 && enrichedCount >= totalExpected) {
        const anySec = !!bodyEl.querySelector('.pill.sec');
        if (anySec) btnInstallSec.disabled = false;
    }
}

// ---- Wire buttons ----
document.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', async (e) => {
        if (btn.disabled) return; // ignore clicks while disabled
        const action = btn.getAttribute('data-action');
        await run(action);
    });
});

document.getElementById('btn-refresh')?.addEventListener('click', () => {
    checkReboot();
    startSSEScan();
});

btnInstallAll?.addEventListener('click', () => run('full_noob_update'));
btnInstallSec?.addEventListener('click', async () => {
    await run('apt_update');
    await run('apt_full_upgrade');
});
btnReboot?.addEventListener('click', rebootNow);

btnToggleAdvanced?.addEventListener('click', () => {
    const open = advancedBox.style.display !== 'none';
    advancedBox.style.display = open ? 'none' : '';
    btnToggleAdvanced.textContent = open ? 'Show advanced options' : 'Hide advanced options';
});

// Output collapse toggle and restore
btnToggleOutput?.addEventListener('click', () => {
    const key = 'upd.output.collapsed';
    const isCollapsed = out.style.display === 'none';
    if (isCollapsed) {
        out.style.display = '';
        btnToggleOutput.textContent = 'Collapse';
        localStorage.setItem(key, 'false');
    } else {
        out.style.display = 'none';
        btnToggleOutput.textContent = 'Expand';
        localStorage.setItem(key, 'true');
    }
});
(function restoreOutputCollapse(){
    const key = 'upd.output.collapsed';
    if (localStorage.getItem(key) === 'true') {
        out.style.display = 'none';
        if (btnToggleOutput) btnToggleOutput.textContent = 'Expand';
    }
})();

// Logs panel state + list rendering
logsToggle?.addEventListener('click', () => {
    const open = logsPanel.classList.contains('is-open');
    logsPanel.classList.toggle('is-open', !open);
    localStorage.setItem('upd.logs.expanded', String(!open));
});

function fmtBytes(n) {
    if (n == null) return '';
    const kb = 1024, mb = kb*1024;
    if (n >= mb) return (n/mb).toFixed(1) + ' MB';
    if (n >= kb) return (n/kb).toFixed(1) + ' kB';
    return n + ' B';
}

async function refreshLogsList() {
    try {
        const r = await fetch('/updates/logs', { cache: 'no-store' });
        const j = await r.json();
        const items = (j.items || []);
        if (logsCount) logsCount.textContent = String(items.length);
        if (!logsList) return;
        logsList.innerHTML = items.map(it => `
          <div class="log-item" data-id="${it.id}">
            <code>${it.id}</code>
            <span class="muted">${fmtBytes(it.size)}</span>
            <span class="spacer"></span>
            <button class="btn small ghost" data-view>View</button>
            <a class="btn small" href="/updates/logs/${encodeURIComponent(it.id)}?download=1">Download</a>
            <button class="btn small warn" data-del>Delete</button>
          </div>`).join('');
        logsList.querySelectorAll('.log-item').forEach(row => {
            const id = row.getAttribute('data-id');
            row.querySelector('[data-view]')?.addEventListener('click', async () => {
                const r2 = await fetch(`/updates/logs/${encodeURIComponent(id)}`);
                const txt = await r2.text();
                showLogViewer(id, txt);
            });
            row.querySelector('[data-del]')?.addEventListener('click', async () => {
                if (!confirm('Delete log ' + id + '?')) return;
                await fetch(`/updates/logs/${encodeURIComponent(id)}`, { method: 'DELETE' });
                refreshLogsList();
            });
        });
    } catch (e) { /* ignore */ }
}

function showLogViewer(id, txt) {
    if (!logsList) return;
    const existing = logsList.querySelector('.log-viewer');
    if (existing) existing.remove();
    const wrap = document.createElement('div');
    wrap.className = 'log-viewer';
    wrap.innerHTML = `
      <div class="hdr">
        <div><strong>${id}</strong></div>
        <div style="display:flex; gap:8px; align-items:center;">
          <button class="btn small" data-copy>Copy</button>
          <button class="btn small ghost" data-close>Close</button>
        </div>
      </div>
      <pre class="body"></pre>`;
    wrap.querySelector('.body').textContent = txt;
    logsList.prepend(wrap);
    wrap.querySelector('[data-copy]')?.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(txt); } catch (e) {}
    });
    wrap.querySelector('[data-close]')?.addEventListener('click', () => wrap.remove());
}

(function restoreLogsOpen(){
    const open = localStorage.getItem('upd.logs.expanded') !== 'false';
    if (open && logsPanel) logsPanel.classList.add('is-open');
    refreshLogsList();
})();

// Progress polling and rendering
function renderProgressCell(tr, pkg) {
    let td = tr.querySelector('td[data-prog]');
    if (!td) {
        td = document.createElement('td');
        td.setAttribute('data-prog', '');
        tr.appendChild(td);
    }
    const pct = Math.max(0, Math.min(100, parseInt(pkg.percent || 0)));
    const phase = pkg.phase || '';
    const done = pct >= 100;
    const cls = ['progress'];
    if (done) cls.push('is-done');
    td.innerHTML = `
      <div class="progress ${cls.join(' ')}" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" title="${phase}">
        <div class="bar" style="width:${pct}%"></div>
        <span class="label">${pct}% — ${phase || (done ? 'Done' : 'Installing')}</span>
      </div>`;
    if (done && tr) {
        const btn = tr.querySelector('[data-install]');
        if (btn) { btn.disabled = true; btn.textContent = 'Installed'; btn.classList.add('is-disabled'); }
    }
}

async function pollProgressOnce(run_id) {
    try {
        const r = await fetch(`/updates/progress/${encodeURIComponent(run_id)}`, { cache: 'no-store' });
        if (!r.ok) return null;
        const j = await r.json();
        renderProgressSnapshot(j);
        return j;
    } catch (e) { return null; }
}

function startProgressPolling(run_id) {
    if (pollProgressTimer) { clearInterval(pollProgressTimer); pollProgressTimer = null; }
    pollProgressTimer = setInterval(async () => {
        const j = await pollProgressOnce(run_id);
        if (j && j.done) {
            clearInterval(pollProgressTimer); pollProgressTimer = null;
            window.localStorage.removeItem('upd.run_id');
            refreshLogsList();
        }
    }, 1000);
}

async function pollLogOnce(run_id) {
    try {
        const r = await fetch(`/updates/logs/${encodeURIComponent(run_id)}`, { cache: 'no-store' });
        if (!r.ok) return;
        const txt = await r.text();
        if (lastLogTextLen < txt.length) {
            out.textContent = txt;
            out.scrollTop = out.scrollHeight;
            lastLogTextLen = txt.length;
        }
    } catch (e) { /* ignore */ }
}

function startLogPolling(run_id) {
    if (pollLogTimer) { clearInterval(pollLogTimer); pollLogTimer = null; }
    pollLogTimer = setInterval(async () => {
        await pollLogOnce(run_id);
        const j = await pollProgressOnce(run_id);
        if (j && j.done) {
            clearInterval(pollLogTimer); pollLogTimer = null;
        }
    }, 1000);
}

// Connection/OS line
async function showConnectionInfo() {
    // profiles -> Connected user@host
    try {
        const r = await fetch('/profiles/list', { cache: 'no-store' });
        const j = await r.json();
        const act = j.active_profile_id;
        const p = (j.profiles || []).find(x => x.id === act);
        if (p && connUserHost) {
            const uh = [p.pi_user, p.pi_host].filter(Boolean).join('@');
            connUserHost.textContent = uh ? `Connected ${uh}` : 'Connected';
        }
    } catch (e) {
        // ignore
    }
    // optional OS info if endpoint exists
    try {
        const r2 = await fetch('/updates/os', { cache: 'no-store' });
        if (r2.ok) {
            const j2 = await r2.json();
            if (j2 && j2.ok && j2.pretty && connOS) {
                connOS.textContent = ` — ${j2.pretty}`;
            }
        }
    } catch (e) {
        // ignore if endpoint not present
    }
}

// ---- Initial load ----
showConnectionInfo();
checkReboot();
startSSEScan();
// Resume active run if present
(async () => {
    const rid = localStorage.getItem('upd.run_id');
    if (rid) {
        currentRunId = rid;
        startProgressPolling(rid);
        startLogPolling(rid);
        setBusy(true);
    }
})();


// Per-package install action (event delegation)
async function installPackage(name) {
  try {
    setBusy(true);
    let sudo_password = window.prompt("Enter sudo password (if required):", "");
    if (sudo_password === null) { setBusy(false); return; }
    const r = await fetch("/updates/install_package", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, sudo_password }) });
    const j = await r.json();
    if (!j.ok) { append("Error: " + (j.error || "failed")); setBusy(false); return; }
    if (j.run_id) { currentRunId = j.run_id; localStorage.setItem("upd.run_id", currentRunId); lastLogTextLen = 0; startProgressPolling(currentRunId); startLogPolling(currentRunId); }
  } catch (e) { append("Network error: " + e); setBusy(false); }
}

bodyEl.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-install]');
  if (!btn) return;
  e.stopPropagation();
  const name = btn.getAttribute('data-name') || btn.closest('tr')?.getAttribute('data-name') || '';
  if (!name) return;
  installPackage(name);
});










