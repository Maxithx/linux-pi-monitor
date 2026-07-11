(function(){
    // Collapse & remember
    const header = document.querySelector('#kp-setup .card-header');
    const body = document.getElementById('kp-setup-body');
    const toggleBtn = document.getElementById('kp-expand-toggle');
    const LS_KEY = 'kpSetupExpanded';
    let expanded = true;
    function setExpanded(v){
      expanded = !!v; body.style.display = expanded ? 'block' : 'none';
      if (toggleBtn) toggleBtn.textContent = expanded ? 'Collapse' : 'Expand';
      try { localStorage.setItem(LS_KEY, expanded ? '1':'0'); } catch {}
    }
    try { const v = localStorage.getItem(LS_KEY); if (v==='1') expanded=true; else if (v==='0') expanded=false; } catch {}
    setExpanded(expanded);
    if (toggleBtn) toggleBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); });

    // Helpers
    const randInt = (n)=>Math.floor(Math.random()*n);
    const shuffle = (a)=>{ for(let i=a.length-1;i>0;i--){const j=randInt(i+1); [a[i],a[j]]=[a[j],a[i]];} return a; };
    function passwordStrengthMsg(p){
      if(!p||p.length<8) return 'Weak: too short';
      const cats=[/[a-z]/,/[A-Z]/,/[0-9]/,/[^\w]/]; let c=0; cats.forEach(rx=>{if(rx.test(p))c++;});
      if(p.length>=16 && c>=3) return 'Strong password';
      return c>=3? 'Okay password' : 'Weak: use more variety';
    }
    function genPassword(len){
      const pools=['abcdefghjkmnpqrstuvwxyz','ABCDEFGHJKLMNPQRSTUVWXYZ','23456789','!@#$%^&*()_+-='];
      const out=[]; for(const p of pools) out.push(p[randInt(p.length)]); const all=pools.join(''); while(out.length<len) out.push(all[randInt(all.length)]); return shuffle(out).join('');
    }
    const genBtn=document.getElementById('kp-smb-gen'); const pwdCopyBtn=document.getElementById('kp-smb-copy'); const pwdToggleBtn=document.getElementById('kp-smb-toggle'); const lenSel=document.getElementById('kp-smb-len');
    if(genBtn){ genBtn.onclick=()=>{ let L=parseInt(lenSel?.value||'16',10); if(!Number.isFinite(L))L=16; if(L<8)L=8; if(L>64)L=64; const v=genPassword(L); const p1=document.getElementById('kp-smb-pass'); const p2=document.getElementById('kp-smb-pass2'); if(p1)p1.value=v; if(p2)p2.value=v; const hint=document.getElementById('kp-smb-hint'); if(hint) hint.textContent=passwordStrengthMsg(v); }; }
    if(pwdCopyBtn){ pwdCopyBtn.onclick=async()=>{ const v=(document.getElementById('kp-smb-pass')?.value||'').trim(); if(!v) return; try{ await navigator.clipboard.writeText(v);}catch{} } }
    if(pwdToggleBtn){ pwdToggleBtn.onclick=()=>{ const p1=document.getElementById('kp-smb-pass'); const p2=document.getElementById('kp-smb-pass2'); const shown=p1?.type==='text'; if(p1) p1.type=shown?'password':'text'; if(p2) p2.type=shown?'password':'text'; pwdToggleBtn.textContent=shown?'Show':'Hide'; } }

    // Simple sudo modal helpers
    let kpRetry = null;
    function showSudoPrompt(onOk){
      const m = document.getElementById('kp-sudo-modal');
      const inp = document.getElementById('kp-sudo-modal-input');
      const err = document.getElementById('kp-sudo-err');
      const btnOk = document.getElementById('kp-sudo-ok');
      const btnCancel = document.getElementById('kp-sudo-cancel');
      const btnClose = document.getElementById('kp-sudo-close');
      err.style.display = 'none';
      m.style.display = 'flex';
      setTimeout(()=>{ try { inp.focus(); } catch{} }, 10);
      function cleanup(){ btnOk.onclick = btnCancel.onclick = btnClose.onclick = null; }
      btnCancel.onclick = btnClose.onclick = ()=>{ cleanup(); m.style.display='none'; onOk(null); };
      btnOk.onclick = ()=>{ const v=(inp.value||'').trim(); if(!v){ err.style.display='block'; return; } cleanup(); m.style.display='none'; onOk(v); };
    }

    async function runPhase(phase, body, logEl, resultEl){
      resultEl.textContent='Running...'; logEl.textContent='';
      const res = await fetch(`/api/keepass/setup/${phase}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{}) });
      if(!res.ok){ let msg=`HTTP ${res.status}`; try{ const e=await res.json(); if(e&&e.error) msg=`Error: ${e.error}`;}catch{} resultEl.textContent=msg; return; }
      const data = await res.json(); const { run_id } = data; let finished=false, exit_code=null, pd=null;
      while(!finished){ const pr=await fetch(`/api/keepass/setup/progress/${run_id}`); pd=await pr.json(); logEl.textContent=pd.log||''; try{ logEl.scrollTop=logEl.scrollHeight; }catch{} finished=!!pd.finished; exit_code=pd.exit_code; if(!finished) await new Promise(r=>setTimeout(r,800)); }
      if(exit_code===0){ resultEl.textContent='OK'; } else { const emsg = (pd&&pd.error)? String(pd.error):''; if(emsg==='sudo_requires_password' && !(body&&body.env&&body.env.SUDO_PASS)){ kpRetry={phase,body,logEl,resultEl}; showSudoPrompt(async (pw)=>{ if(!pw){ resultEl.textContent='Cancelled'; kpRetry=null; return; } try{ const b=JSON.parse(JSON.stringify(kpRetry.body||{})); b.env=Object.assign({}, b.env||{}, { SUDO_PASS: pw }); await runPhase(kpRetry.phase, b, kpRetry.logEl, kpRetry.resultEl); } finally{ kpRetry=null; } }); return; } else { resultEl.textContent = emsg? `Error: ${emsg}` : `Exit ${exit_code}`; } }
    }

    const g=(id)=>document.getElementById(id);

    // Samba share write lock. OFF keeps files readable but blocks create,
    // modify, overwrite and delete operations through SMB.
    const accessToggle = g('kp-access-toggle');
    const accessStatus = g('kp-access-status');
    const accessDescription = g('kp-access-description');
    const accessResult = g('kp-access-result');
    const accessLog = g('kp-log-access');
    let accessWritable = null;

    function renderAccess(writable, configured=true){
      accessWritable = configured ? !!writable : null;
      if (accessToggle) {
        accessToggle.checked = !!writable;
        accessToggle.disabled = !configured;
      }
      if (accessStatus) {
        accessStatus.textContent = configured ? (writable ? 'Read/write ON' : 'Read-only') : 'Not configured';
        accessStatus.className = `kp-access-status ${configured ? (writable ? 'is-writable' : 'is-readonly') : 'is-unknown'}`;
      }
      if (accessDescription) {
        accessDescription.textContent = !configured
          ? 'Run Phase 2 first to create the KeePass Samba share.'
          : writable
            ? 'Files can be read, created, changed and deleted through the share.'
            : 'Files can be read, but writing, overwriting and deletion are blocked.';
      }
    }

    async function loadAccessStatus(){
      if (accessToggle) accessToggle.disabled = true;
      try {
        const res = await fetch('/api/keepass/access', {cache:'no-store'});
        const data = await res.json();
        if (!res.ok || !data.ok) {
          renderAccess(false, false);
          if (accessResult) accessResult.textContent = data.error || `HTTP ${res.status}`;
          return;
        }
        renderAccess(!!data.writable, true);
        if (accessResult) accessResult.textContent = '';
      } catch (e) {
        renderAccess(false, false);
        if (accessResult) accessResult.textContent = `Unable to read status: ${e}`;
      }
    }

    async function setAccessMode(writable, sudoPass=''){
      if (accessToggle) accessToggle.disabled = true;
      if (accessResult) accessResult.textContent = writable ? 'Enabling write access…' : 'Enabling read-only mode…';
      if (accessLog) accessLog.textContent = '';
      const body = { writable: !!writable, env: { SUDO_PASS: sudoPass || g('kp-sudo-pass')?.value || '' } };
      try {
        const res = await fetch('/api/keepass/access', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const data = await res.json();
        if (!res.ok || !data.run_id) throw new Error(data.error || `HTTP ${res.status}`);
        let pd = null;
        do {
          await new Promise(r=>setTimeout(r, 600));
          const pr = await fetch(`/api/keepass/setup/progress/${encodeURIComponent(data.run_id)}`, {cache:'no-store'});
          pd = await pr.json();
          if (accessLog) { accessLog.textContent = pd.log || ''; accessLog.scrollTop = accessLog.scrollHeight; }
        } while (!pd.finished);
        if (pd.exit_code === 0) {
          renderAccess(writable, true);
          if (accessResult) accessResult.textContent = writable ? 'Write access enabled.' : 'Read-only protection enabled.';
          return;
        }
        if (pd.error === 'sudo_requires_password' && !sudoPass && !(g('kp-sudo-pass')?.value || '')) {
          showSudoPrompt(async pw => {
            if (pw) await setAccessMode(writable, pw);
            else { renderAccess(accessWritable, true); if (accessResult) accessResult.textContent='Cancelled'; }
          });
          return;
        }
        throw new Error(pd.error || `Exit ${pd.exit_code}`);
      } catch (e) {
        renderAccess(accessWritable, accessWritable !== null);
        if (accessResult) accessResult.textContent = `Error: ${e.message || e}`;
      } finally {
        if (accessToggle && accessWritable !== null) accessToggle.disabled = false;
      }
    }

    if (accessToggle) accessToggle.addEventListener('change', ()=>{
      const requested = accessToggle.checked;
      accessToggle.checked = accessWritable === true;
      setAccessMode(requested);
    });
    loadAccessStatus();

    // Build Windows mapping helper (fetch host from active profile)
    (async () => {
      try {
        const profs = await fetch('/profiles/list', { cache: 'no-store' }).then(r=>r.json());
        const pid = profs.active_profile_id || profs.default_profile_id;
        const prof = (profs.profiles||[]).find(p=>p.id===pid) || {};
        const host = (prof.pi_host||'').trim();
        const share = host ? `\\\\${host}\\keepass` : `\\\\<pi-host>\\keepass`;
        const line1 = `Share: ${share}`;
        const line2 = `net use Z: ${share} /user:keepass`;
        const pre = g('kp-win-ps');
        const sp = g('kp-share-path');
        if (sp) sp.textContent = line1;
        if (pre) pre.textContent = line2 + '\n\nTip: You will be prompted for the SMB password you set in Phase 2.';
        const copyBtn = g('kp-copy-ps');
        if (copyBtn) copyBtn.onclick = async () => {
          try { await navigator.clipboard.writeText(line2); copyBtn.textContent='Copied'; setTimeout(()=>copyBtn.textContent='Copy', 1200);} catch {}
        };

        // Auto-detect LAN_SUBNET from profile host and persist selection
        const lanInput = g('kp-lan-subnet');
        const lanHint = g('kp-lan-hint');
        function net24(ip){
          const p=(ip||'').split('.'); if(p.length!==4) return '';
          return `${p[0]}.${p[1]}.${p[2]}.0/24`;
        }
        // Prefer previously chosen value from localStorage
        let saved = null; try { saved = localStorage.getItem('kpLAN'); } catch {}
        if (lanInput){
          if (saved && /^\d+\.\d+\.\d+\.\d+\/\d+$/.test(saved)){
            lanInput.value = saved;
            if (lanHint) lanHint.textContent = `Using saved value (${saved})`;
          } else {
            const guess = net24(host);
            if (guess){
              // Only override the factory default to avoid clobbering a user-entered value
              if (lanInput.value === '192.168.0.0/24') lanInput.value = guess;
              if (lanHint) lanHint.textContent = `Detected from profile host ${host} → ${guess}`;
            }
          }
          lanInput.addEventListener('input', ()=>{ try { localStorage.setItem('kpLAN', lanInput.value.trim()); } catch {} });
        }
      } catch {}
    })();
    if(g('kp-run-phase1')) g('kp-run-phase1').onclick=()=> runPhase('phase1', { env:{ LAN_SUBNET: g('kp-lan-subnet').value || '192.168.0.0/24', SMB_PASS: g('kp-smb-pass').value || '', SUDO_PASS: g('kp-sudo-pass').value || '' } }, g('kp-log-phase1'), g('kp-phase1-result'));
    if(g('kp-run-phase2')) g('kp-run-phase2').onclick=()=>{
      const pwd=(g('kp-smb-pass').value||'').trim(); const pwd2=(g('kp-smb-pass2')?.value||'').trim(); const resEl=g('kp-phase2-result');
      if(!pwd){ resEl.textContent='SMB_PASS is required for Phase 2'; g('kp-smb-pass').focus(); return; }
      if(pwd2 && pwd!==pwd2){ resEl.textContent='Passwords do not match'; g('kp-smb-pass2').focus(); return; }
      const msg=passwordStrengthMsg(pwd); if(msg.startsWith('Weak')){ resEl.textContent=msg; g('kp-smb-pass').focus(); return; }
      runPhase('phase2', { env:{ LAN_SUBNET: g('kp-lan-subnet').value || '192.168.0.0/24', SMB_PASS: pwd, SUDO_PASS: g('kp-sudo-pass').value || '' } }, g('kp-log-phase2'), resEl);
    };
    if(g('kp-run-phase3')) g('kp-run-phase3').onclick=()=>{
      const openGl = g('kp-open-glances')?.checked ? '1' : '0';
      runPhase('phase3', { env:{ LAN_SUBNET: g('kp-lan-subnet').value || '192.168.0.0/24', SUDO_PASS: g('kp-sudo-pass').value || '', KP_OPEN_GLANCES: openGl } }, g('kp-log-phase3'), g('kp-phase3-result'));
    };
    if(g('kp-run-phase4')) g('kp-run-phase4').onclick=()=> runPhase('phase4', {}, g('kp-log-phase4'), g('kp-phase4-result'));
    if(g('kp-run-rollback')) g('kp-run-rollback').onclick=()=> runPhase('rollback', {}, g('kp-log-rollback'), g('kp-rollback-result'));
  })();
