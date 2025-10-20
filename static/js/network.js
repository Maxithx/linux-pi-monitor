(() => {
    const $ = s => document.querySelector(s);
    const ifaceGrid = $('#iface-grid');
    const wifiGrid = $('#wifi-grid');
    const statusEl = $('#net-status');
    const filterEl = $('#wifi-filter');

    const qc = {
        ssid: $('#qc-ssid'), pass: $('#qc-pass'), hidden: $('#qc-hidden'),
        sudo: $('#qc-sudo'), connect: $('#qc-connect'), forget: $('#qc-forget')
    };

    const setStatus = (t = '') => statusEl.textContent = t;

    // ---------- Helpers ----------
    const esc = (s) => (s ?? '').toString()
        .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;').replaceAll("'", '&#39;');

    // map either 0-100 (nmcli) or negative dBm to 0-100
    function sigPercent(val) {
        if (val === '' || val === null || val === undefined) return 0;
        if (typeof val === 'number' && val <= 0) {
            const clamped = Math.max(-90, Math.min(-30, val)); // -90..-30
            return Math.round(((clamped + 90) / 60) * 100);    // 0..100
        }
        const n = Number(val);
        if (Number.isFinite(n)) return Math.max(0, Math.min(100, n));
        return 0;
    }

    // ---------- Interfaces ----------
    async function loadSummary() {
        setStatus('Refreshing…');
        try {
            const r = await fetch('/network/summary');
            const j = await r.json();
            if (!j.ok) throw new Error(j.error || 'summary failed');
            renderInterfaces(j.interfaces || []);
            setStatus(`Gateway ${j.gateway || '—'} • DNS ${j.dns || '—'}`);
        } catch (e) {
            renderInterfaces([]);
            setStatus('Failed to refresh');
            console.error(e);
        }
    }

    function renderInterfaces(list) {
        // clear rows (keep header)
        ifaceGrid.querySelectorAll('.row').forEach(el => el.remove());
        if (!list.length) {
            ifaceGrid.insertAdjacentHTML('beforeend',
                `<div class="row"><div class="cell-muted" style="grid-column:1 / -1">No interfaces.</div></div>`);
            return;
        }
        const rows = list.map(i => {
            const star = i.default_route ? '★' : '';
            const isWifi = (i.type || '').toLowerCase() === 'wifi';
            const p = isWifi ? sigPercent(i.signal ? parseInt(i.signal, 10) : 0) : 0;
            const sigCell = isWifi
              ? `<div class="sigwrap"><div class="sigbar"><div class="fill" style="width:${p}%"></div></div><span class="cell-muted">${esc(i.signal || '')}</span></div>`
              : `<div>-</div>`;
            return `
      <div class="row">
        <div style="text-align:center">${star}</div>
        <div><code>${esc(i.iface || '')}</code></div>
        <div>${esc(i.type || '')}</div>
        <div>${esc(i.ipv4 || '')}</div>
        <div><code>${esc(i.mac || '')}</code></div>
        <div>${esc(i.speed || '')}</div>
        <div>${esc(i.ssid || '')}</div>
        ${sigCell}
      </div>`;
        }).join('');
        ifaceGrid.insertAdjacentHTML('beforeend', rows);
    }

    // ---------- Scan ----------
    async function scan() {
        // NYT: Hent sudo password fra inputfeltet
        const sudo_pw = qc.sudo.value.trim();

        setStatus('Scanning Wi-Fi…');
        try {
            const r = await fetch('/network/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // NYT: Sender sudo password med i JSON body
                body: JSON.stringify({ sudo_pw: sudo_pw })
            });

            const j = await r.json();
            if (!j.ok) throw new Error(j.error || 'scan failed');
            const nets = (j.networks || [])
                .sort((a, b) => (a.in_use === b.in_use ? 0 : (a.in_use ? -1 : 1)) || ((b.signal || 0) - (a.signal || 0)));
            renderWifi(nets);
            setStatus(`Found ${nets.length} network${nets.length === 1 ? '' : 's'}.`);
        } catch (e) {
            renderWifi([]);
            setStatus('Scan failed');
            console.error(e);
        }
    }

    function renderWifi(nets) {
        wifiGrid.querySelectorAll('.row').forEach(el => el.remove());
        if (!nets.length) {
            wifiGrid.insertAdjacentHTML('beforeend',
                `<div class="row"><div class="cell-muted" style="grid-column:1 / -1">No networks.</div></div>`);
            return;
        }
        const q = (filterEl.value || '').toLowerCase();
        const rows = nets.filter(n => !q || (n.ssid || '').toLowerCase().includes(q)).map(n => {
            const p = sigPercent(n.signal);
            const ssid = esc(n.ssid || '');
            const used = n.in_use ? `<span class="chip used">Yes</span>` : 'No';
            const sec = `<span class="chip sec">${esc(n.security || 'OPEN')}</span>`;
            return `
      <div class="row">
        <div>${ssid || '<span class="muted">(hidden)</span>'}</div>
        <div class="sigwrap"><div class="sigbar"><div class="fill" style="width:${p}%"></div></div><span class="cell-muted">${esc(n.signal || '')}</span></div>
        <div>${sec}</div>
        <div>${used}</div>
        <div>
          <button class="secondary" data-act="pick" data-ssid="${ssid}">Pick</button>
          <button class="danger" data-act="forget" data-ssid="${ssid}">Forget</button>
        </div>
      </div>`;
        }).join('');
        wifiGrid.insertAdjacentHTML('beforeend', rows);
    }

    // ---------- Connect / Forget ----------
    async function doConnect() {
        // Bemærk: 'sudo_pw: qc.sudo.value || undefined' var allerede inkluderet her.
        const body = {
            ssid: qc.ssid.value.trim(),
            password: qc.pass.value,
            hidden: qc.hidden.checked,
            sudo_pw: qc.sudo.value || undefined
        };
        if (!body.ssid) return alert('Enter SSID');
        setStatus('Connecting…');
        try {
            const r = await fetch('/network/connect', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
            const j = await r.json();
            if (!j.ok) throw new Error(j.error || j.message || 'connect failed');
            setStatus('Connected (request sent). Refreshing…');
            await loadSummary();
        } catch (e) { setStatus('Connect failed'); alert(e); }
    }

    async function doForget(name) {
        const ssid = name || qc.ssid.value.trim();
        if (!ssid) return alert('Enter SSID');
        if (!confirm(`Forget saved network "${ssid}"?`)) return;

        // NYT: Inkluder sudo_pw i body for forget API kald
        const body = {
            ssid: ssid,
            sudo_pw: qc.sudo.value || undefined
        };

        setStatus('Forgetting…');
        try {
            const r = await fetch('/network/forget', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
            const j = await r.json();
            if (!j.ok) throw new Error(j.error || j.message || 'forget failed');
            setStatus('Removed. Refreshing…');
            await loadSummary();
        } catch (e) { setStatus('Forget failed'); alert(e); }
    }

    // ---------- Events ----------
    $('#btn-refresh').addEventListener('click', loadSummary);
    $('#btn-scan').addEventListener('click', scan);
    filterEl.addEventListener('input', () => renderWifi([...wifiGrid.querySelectorAll('.row')].length ? [] : [])); // no-op, kept simple
    qc.connect.addEventListener('click', doConnect);
    qc.forget.addEventListener('click', () => doForget());

    wifiGrid.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-act]');
        if (!btn) return;
        const act = btn.dataset.act; const ssid = btn.dataset.ssid || '';
        if (act === 'pick') { qc.ssid.value = ssid; qc.pass.focus(); }
        if (act === 'forget') { doForget(ssid); }
    });

    // Init
    loadSummary();
})();

