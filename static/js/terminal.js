/* =========================================================================
 * Linux/Pi Monitor – Terminal frontend (xterm.js + Socket.IO)
 * ========================================================================= */
(() => {
    // ---- Configuration ------------------------------------------------------
    const LS_CMDS_KEY = "terminal_saved_cmds_v1";

    // Seed examples on first load
    const DEFAULT_CMDS = [
        { title: "Reboot", command: "sudo reboot", desc: "Restart the machine" },
        { title: "Show memory", command: "free -h", desc: "Human-readable RAM usage" },
        { title: "Show disk usage", command: "df -h", desc: "Mounted filesystems usage" }
    ];

    const EV = {
        start: ["terminal_start", "pty-start", "start"],
        input: ["terminal_input", "pty-input", "input", "stdin"],
        output: ["terminal_output", "pty-output", "output", "pty-data", "data", "stdout"],
        resize: ["terminal_resize", "pty-resize", "resize"],
        welcome: ["terminal_welcome", "pty-welcome", "welcome"]
    };

    const uniq = (a) => [...new Set(a)];
    const emitAll = (s, n, p) => uniq(n).forEach(x => s.emit(x, p));
    const onAll = (s, n, h) => uniq(n).forEach(x => s.on(x, h));

    // ---- DOM ----------------------------------------------------------------
    const $termHost = document.getElementById("terminal");
    const $stopBtn = document.getElementById("stop-process-btn");
    const $pasteBtn = document.getElementById("paste-btn");
    const $list = document.getElementById("command-list");
    const $search = document.getElementById("search-box");
    const $form = document.getElementById("add-command-form");
    const $count = document.getElementById("cmd-count");
    const $status = document.getElementById("term-status");

    if (!$termHost) { console.error("terminal.js: #terminal not found."); return; }

    // ---- xterm.js -----------------------------------------------------------
    const fitAddon = new window.FitAddon.FitAddon();
    const canvasAddon = new window.CanvasAddon.CanvasAddon();

    const term = new window.Terminal({
        cursorBlink: true,
        fontFamily: "JetBrains Mono, Fira Code, Consolas, monospace",
        fontSize: 14,
        bellStyle: "none",
        scrollback: 2000,
        convertEol: true,
        theme: {
            background: "#1A1A1A", // match sidebar
            foreground: "#e5e7eb",
            cursor: "#00BCD4",
            black: "#000000",
        }
    });

    term.loadAddon(fitAddon);
    term.loadAddon(canvasAddon);
    term.open($termHost);
    function enableWrap() {
        try { term.write('\x1b[?7h'); } catch {}
    }
    // Ensure wraparound mode (DECSET 7) so long lines wrap to the next row
    enableWrap();
    term.focus();
    safeFit();

    // ---- Persist size + debounce --------------------------------------------
    const LS_SIZE_KEY = "term.size.v1";
    function loadSavedSize(){
        try { const j = JSON.parse(localStorage.getItem(LS_SIZE_KEY)||"null"); if(j && j.cols && j.rows) return j; } catch{} return null;
    }
    function saveSize(cols, rows){
        try { localStorage.setItem(LS_SIZE_KEY, JSON.stringify({cols, rows})); } catch{}
    }
    let resizeTimer = null;
    function emitResizeDebounced(){
        if(resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            const payload = { cols: term.cols, rows: term.rows };
            saveSize(payload.cols, payload.rows);
            emitAll(socket, EV.resize, payload);
        }, 140);
    }
    term.onResize(({cols, rows}) => saveSize(cols, rows));

    // ---- Socket.IO ----------------------------------------------------------
    const socket = window.io();

    socket.on("connect", () => {
        const saved = loadSavedSize();
        const payload = saved && saved.cols && saved.rows ? saved : { cols: term.cols, rows: term.rows };
        emitAll(socket, EV.start, payload);
        emitAll(socket, EV.resize, payload);
        enableWrap();
    });

    socket.on("connect_error", (err) => {
        console.error("[terminal] connect_error:", err);
        term.writeln("\r\n\x1b[31m[Socket.IO] Connection error.\x1b[0m");
    });

    onAll(socket, EV.output, (chunk) => {
        enableWrap();
        if (typeof chunk === "string" && chunk.length) {
            if (chunk.startsWith("[resize error]")) {
                if ($status) { $status.textContent = chunk; $status.style.display = 'block'; setTimeout(() => { $status.style.display = 'none'; }, 2500); }
                console.warn(chunk);
                return;
            }
            term.write(chunk);
        }
        else if (chunk && chunk.data && typeof chunk.data === "string") term.write(chunk.data);
    });

    onAll(socket, EV.welcome, (msg) => { enableWrap(); if (msg) term.writeln(msg); });

    socket.on("disconnect", () => {
        term.writeln("\r\n\x1b[33m[Socket.IO] Disconnected.\x1b[0m");
    });

    term.onData((data) => emitAll(socket, EV.input, data));

    if ($stopBtn) $stopBtn.addEventListener("click", () => emitAll(socket, EV.input, "\x03"));

    function safeFit() {
        try {
            fitAddon.fit();
            if (socket && socket.connected) emitResizeDebounced();
            else saveSize(term.cols, term.rows);
        } catch { }
    }
    new ResizeObserver(() => safeFit()).observe($termHost);
    window.addEventListener("resize", safeFit);
    window.addEventListener("orientationchange", safeFit);

    // Mobile focus + paste button
    $termHost.addEventListener('click', () => { term.focus(); term.scrollToBottom(); });
    $termHost.addEventListener('touchstart', () => { term.focus(); term.scrollToBottom(); });
    async function doPaste(){
        try { const txt = await navigator.clipboard.readText(); if (txt) term.paste(txt); }
        catch(e){ console.warn('Paste failed', e); if ($status){ $status.textContent='Clipboard permission denied'; $status.style.display='block'; setTimeout(()=>{ $status.style.display='none'; }, 2000);} }
    }
    if ($pasteBtn) $pasteBtn.addEventListener('click', doPaste);

    // ---- Commands store -----------------------------------------------------
    function getSavedCmds() {
        try { return JSON.parse(localStorage.getItem(LS_CMDS_KEY) || "[]") ?? []; }
        catch { return []; }
    }
    function setSavedCmds(arr) {
        try { localStorage.setItem(LS_CMDS_KEY, JSON.stringify(arr)); } catch { }
    }
    function seedIfEmpty() {
        const cur = getSavedCmds();
        if (!cur || cur.length === 0) setSavedCmds(DEFAULT_CMDS);
    }

    function escapeHTML(s) {
        return (s || "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;");
    }

    function sendToTerm(text, execute = false) {
        if (!text) return;
        emitAll(socket, EV.input, execute ? (text + "\n") : text);
        term.focus();
    }

    // ---- Render grid table --------------------------------------------------
    function renderCmds(filter = "") {
        if (!$list) return;
        const q = (filter || "").trim().toLowerCase();
        const cmds = getSavedCmds();

        $list.innerHTML = "";
        if ($count) $count.textContent = cmds.length ? `${cmds.length} saved` : "no saved commands";

        const filtered = cmds
            .map((c, idx) => ({ ...c, idx }))
            .filter(c =>
                !q ||
                (c.title || "").toLowerCase().includes(q) ||
                (c.command || "").toLowerCase().includes(q) ||
                (c.desc || "").toLowerCase().includes(q)
            );

        if (!filtered.length) {
            const empty = document.createElement("div");
            empty.className = "cmd-row";
            empty.style.opacity = ".7";
            empty.innerHTML = `<div>(none)</div><div></div><div></div><div></div>`;
            $list.appendChild(empty);
            return;
        }

        filtered.forEach(({ title, command, desc, idx }) => {
            const row = document.createElement("div");
            row.className = "cmd-row";

            const colTitle = document.createElement("div");
            colTitle.className = "cmd-title";
            colTitle.textContent = title || "(untitled)";

            const colCmd = document.createElement("div");
            colCmd.className = "cmd-command";
            colCmd.innerHTML = `<code title="Click to insert">${escapeHTML(command || "")}</code>`;
            colCmd.addEventListener("click", () => sendToTerm(command, false));

            const colDesc = document.createElement("div");
            colDesc.className = "cmd-desc";
            colDesc.textContent = desc || "";

            const colAct = document.createElement("div");
            colAct.className = "cmd-actions";
            const btnRun = document.createElement("button");
            btnRun.textContent = "Run";
            btnRun.addEventListener("click", () => sendToTerm(command, true));
            const btnIns = document.createElement("button");
            btnIns.textContent = "Insert";
            btnIns.className = "ghost";
            btnIns.addEventListener("click", () => sendToTerm(command, false));
            const btnDel = document.createElement("button");
            btnDel.textContent = "Delete";
            btnDel.className = "danger";
            btnDel.addEventListener("click", () => {
                setSavedCmds(getSavedCmds().filter((_, i) => i !== idx));
                renderCmds($search?.value || "");
            });
            colAct.append(btnRun, btnIns, btnDel);

            row.append(colTitle, colCmd, colDesc, colAct);
            $list.appendChild(row);
        });
    }

    if ($search) $search.addEventListener("input", () => renderCmds($search.value || ""));
    if ($form) {
        $form.addEventListener("submit", (e) => {
            e.preventDefault();
            const title = document.getElementById("cmd-title")?.value || "";
            const command = document.getElementById("cmd-command")?.value || "";
            const desc = document.getElementById("cmd-desc")?.value || "";
            if (!command.trim()) return;

            const all = getSavedCmds();
            all.push({ title: title.trim(), command: command.trim(), desc: desc.trim() });
            setSavedCmds(all);

            document.getElementById("cmd-title").value = "";
            document.getElementById("cmd-command").value = "";
            document.getElementById("cmd-desc").value = "";
            renderCmds($search?.value || "");
        });
    }

    seedIfEmpty();
    renderCmds("");
    term.writeln("\x1b[32mConnected. Type commands here, or use the list on the right.\x1b[0m\n");
})();
