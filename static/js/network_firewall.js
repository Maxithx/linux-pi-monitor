// network_firewall.js
// Adds Network|Firewall tabs to network.html and renders read-only firewall view

(function(){
  const root = document.getElementById('network-root');
  const fwRoot = document.getElementById('firewall-root');
  if (!root || !fwRoot) return;

  const LS_KEY = 'net.view';

  // Build tabs UI
  const tabs = document.createElement('div');
  tabs.className = 'net-tabs';
  tabs.innerHTML = `
    <div class="net-tabs-row">
      <button type="button" class="net-tab" data-view="network">Network</button>
      <button type="button" class="net-tab" data-view="firewall">Firewall</button>
    </div>`;
  root.parentNode.insertBefore(tabs, root); // place above network content

  function select(view){
    const isFw = (view === 'firewall');
    root.style.display = isFw ? 'none' : '';
    fwRoot.style.display = isFw ? '' : 'none';
    document.querySelectorAll('.net-tab').forEach(b => {
      b.classList.toggle('is-active', b.getAttribute('data-view') === view);
    });
    try {
      localStorage.setItem(LS_KEY, view);
      const hash = (view === 'firewall') ? '#firewall' : '#network';
      history.replaceState(null, '', location.pathname + hash);
    } catch {}
    if (isFw) ensureFirewallLoaded();
  }

  tabs.addEventListener('click', (e) => {
    const btn = e.target.closest('.net-tab');
    if (!btn) return;
    select(btn.getAttribute('data-view'));
  });

  // Initialize selected view from hash or LS
  (function init(){
    const h = (location.hash || '').replace('#','');
    const saved = (()=>{ try { return localStorage.getItem(LS_KEY)||''; } catch{ return ''; } })();
    select(h === 'firewall' ? 'firewall' : (saved || 'network'));
  })();

  // ---- Firewall rendering ----
  let loaded = false;
  async function fetchStatus(){
    const r = await fetch('/network/firewall/status', { cache:'no-store' });
    try { return await r.json(); } catch (e) {
      try { const txt = await r.text(); return { ok:false, error: txt.slice(0,400) }; } catch { return { ok:false, error: 'Invalid response' }; }
    }
  }

  function pill(el, enabled){
    el.textContent = enabled ? 'Enabled' : 'Disabled';
    el.className = 'badge ' + (enabled ? 'green' : '');
  }

  function renderUfw(j){
    const rules = j.rules || [];
    const rows = rules.map(r => `<tr><td>${r.number}</td><td>${escapeHtml(r.rule)}</td></tr>`).join('');
    return `
      <div class="card" style="padding:12px;">
        <div style="font-weight:600; margin-bottom:6px;">UFW Rules</div>
        <table style="width:100%; border-collapse:collapse;">
          <thead><tr>
            <th style="text-align:left; padding:8px; border-bottom:1px solid var(--card-border);">#</th>
            <th style="text-align:left; padding:8px; border-bottom:1px solid var(--card-border);">Rule</th>
          </tr></thead>
          <tbody>${rows || '<tr><td colspan="2" style="padding:8px;">No rules</td></tr>'}</tbody>
        </table>
      </div>`;
  }

  function renderFirewalld(j){
    const zones = j.zones || [];
    const parts = zones.map(z => {
      const svc = (z.services||[]).map(s=>`<span class="chip">${escapeHtml(s)}</span>`).join(' ');
      const ports = (z.ports||[]).map(p=>`<span class="chip">${escapeHtml(p.port)}/${escapeHtml(p.proto)}</span>`).join(' ');
      const ifs = (z.interfaces||[]).join(', ');
      return `
        <div class="card" style="padding:12px; margin-bottom:10px;">
          <div style="font-weight:600; margin-bottom:4px;">${escapeHtml(z.zone)} zone</div>
          <div class="muted" style="margin-bottom:6px;">Interfaces ${escapeHtml(ifs || '-')}</div>
          <div style="display:flex; flex-wrap:wrap; gap:6px;">${svc}${ports ? ' ' + ports : ''}</div>
        </div>`;
    }).join('');
    return parts || `<div class="muted" style="padding:10px;">No active zones</div>`;
  }

  function escapeHtml(s){
    return (s==null?'':String(s))
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  async function ensureFirewallLoaded(){
    if (!loaded) await renderFirewall();
  }

  async function renderFirewall(){
    const pillEl = document.getElementById('fw-pill');
    const fwEl = document.getElementById('fw-framework');
    const subEl = document.getElementById('fw-sub');
    const cont = document.getElementById('fw-content');
    const btn = document.getElementById('fw-refresh');

    async function load(){
      try {
        const j = await fetchStatus();
        if (!j || !j.ok){ cont.innerHTML = `<div class="card" style="padding:10px; color:#b91c1c;">Error: ${escapeHtml(j && j.error || 'unknown')}</div>`; return; }
        pill(pillEl, !!j.enabled);
        fwEl.textContent = j.framework && j.framework !== 'none' ? `Framework: ${j.framework}` : 'Framework: not detected';
        subEl.textContent = j.framework === 'ufw' && j.defaults
          ? `Incoming: ${j.defaults.incoming || '-'} • Outgoing: ${j.defaults.outgoing || '-'}`
          : '';
        if (j.framework === 'ufw') cont.innerHTML = renderUfw(j);
        else if (j.framework === 'firewalld') cont.innerHTML = renderFirewalld(j);
        else cont.innerHTML = `<div class="card" style="padding:10px;">No supported firewall detected (UFW/firewalld)</div>`;
        loaded = true;
      } catch(e){
        cont.innerHTML = `<div class="card" style="padding:10px; color:#b91c1c;">${escapeHtml(String(e))}</div>`;
      }
    }
    if (btn) btn.onclick = load;
    await load();
  }
})();
