/* =========================================================================
 * Linux/Pi Monitor – Terminal frontend (xterm.js + Socket.IO)
 * ========================================================================= */
(() => {
    // ---- Configuration ------------------------------------------------------
    const LS_CMDS_KEY = "terminal_saved_cmds_v1";

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
    const $search = document.getElementById("search-box");
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

    const API = {
        list: "/terminal/collections",
        collections: "/terminal/collections",
        collection: (id) => `/terminal/collections/${encodeURIComponent(id)}`,
        reorderCollections: "/terminal/collections/reorder",
        commands: "/terminal/commands",
        command: (id) => `/terminal/commands/${encodeURIComponent(id)}`,
        reorderCommands: "/terminal/commands/reorder",
        export: "/terminal/collections/export",
        import: "/terminal/collections/import",
    };

    const state = {
        collections: [],
        commands: [],
        activeCollection: "all",
        search: "",
        profileId: null,
    };

    const dragState = { type: null, id: null };

    const dom = {
        tabsWrap: document.getElementById("collections-tabs"),
        collectionsBar: document.getElementById("collections-bar"),
        addCollection: document.getElementById("add-collection-btn"),
        addCommand: document.getElementById("add-command-btn"),
        exportBtn: document.getElementById("export-btn"),
        importInput: document.getElementById("import-file"),
        commandList: document.getElementById("command-list"),
        feedback: document.getElementById("cmd-feedback"),
        actions: document.getElementById("collection-actions"),
        renameCollection: document.getElementById("rename-collection-btn"),
        deleteCollection: document.getElementById("delete-collection-btn"),
        commandModal: document.getElementById("command-modal"),
        commandForm: document.getElementById("command-form"),
        collectionModal: document.getElementById("collection-modal"),
        collectionForm: document.getElementById("collection-form"),
        cmdId: document.getElementById("cmd-id"),
        modalTitleInput: document.getElementById("modal-title"),
        modalCommandInput: document.getElementById("modal-command"),
        modalDescInput: document.getElementById("modal-desc"),
        modalCollectionSelect: document.getElementById("modal-collection"),
        modalSudo: document.getElementById("modal-sudo"),
        commandModalTitle: document.getElementById("commandModalTitle"),
        modalSaveBtn: document.getElementById("modal-save-btn"),
        collectionId: document.getElementById("collection-id"),
        collectionNameInput: document.getElementById("collection-name"),
        collectionModalTitle: document.getElementById("collectionModalTitle"),
        collectionSaveBtn: document.getElementById("collection-save-btn"),
    };

    function setFeedback(message = "", isError = false) {
        if (!dom.feedback) return;
        dom.feedback.textContent = message;
        dom.feedback.style.color = isError ? "#f87171" : "";
    }

    async function fetchJSON(url, options = {}) {
        const opts = { headers: { "Content-Type": "application/json" }, ...options };
        if (opts.body && typeof opts.body !== "string") {
            opts.body = JSON.stringify(opts.body);
        }
        const res = await fetch(url, opts);
        let data = null;
        try {
            data = await res.json();
        } catch (err) {
            /* no-op */
        }
        if (!res.ok || !data?.ok) {
            throw new Error(data?.error || `Request failed (${res.status})`);
        }
        return data;
    }

    async function loadCollections(runMigration = false) {
        try {
            const data = await fetchJSON(API.list);
            const snap = data.data || {};
            if (runMigration) {
                const migrated = await migrateLegacyIfNeeded(snap);
                if (migrated) {
                    return loadCollections(false);
                }
            }
            state.collections = snap.collections || [];
            state.commands = snap.commands || [];
            state.profileId = snap.profile_id || null;
            if (state.activeCollection !== "all") {
                const stillExists = state.collections.some((c) => c.id === state.activeCollection);
                if (!stillExists) state.activeCollection = "all";
            }
            renderTabs();
            renderCommands();
            updateCollectionActions();
            updateCount();
            setFeedback(state.commands.length ? "" : "No saved commands yet.");
        } catch (err) {
            setFeedback(err.message || "Failed to load commands", true);
        }
    }

    function filteredCommands() {
        const q = state.search.trim().toLowerCase();
        return state.commands.filter((cmd) => {
            const inCollection = state.activeCollection === "all" || cmd.group_id === state.activeCollection;
            if (!inCollection) return false;
            if (!q) return true;
            return [cmd.title, cmd.command, cmd.description]
                .some((field) => (field || "").toLowerCase().includes(q));
        });
    }

    function updateCount() {
        if (!$count) return;
        const total = state.commands.length;
        if (!total) {
            $count.textContent = "no saved commands";
            return;
        }
        const view = filteredCommands().length;
        if (state.activeCollection === "all") {
            $count.textContent = `${total} saved`;
        } else {
            $count.textContent = `${view} shown · ${total} total`;
        }
    }

    function renderTabs() {
        const wrap = dom.tabsWrap;
        if (!wrap) return;
        wrap.innerHTML = "";
        state.collections.forEach((col) => {
            const btn = document.createElement("button");
            btn.className = "collection-tab" + (state.activeCollection === col.id ? " active" : "");
            btn.dataset.id = col.id;
            btn.textContent = col.name || "Collection";
            btn.addEventListener("click", () => setActiveCollection(col.id));
            btn.draggable = true;
            btn.addEventListener("dragstart", handleCollectionDragStart);
            btn.addEventListener("dragover", handleCollectionDragOver);
            btn.addEventListener("drop", handleCollectionDrop);
            btn.addEventListener("dragend", () => finalizeCollectionDrag(true));
            wrap.appendChild(btn);
        });
        const allTab = dom.collectionsBar?.querySelector('[data-id="all"]');
        if (allTab) {
            allTab.classList.toggle("active", state.activeCollection === "all");
            allTab.addEventListener("click", () => setActiveCollection("all"));
        }
    }

    function renderCommands() {
        if (!dom.commandList) return;
        dom.commandList.innerHTML = "";
        const allowDrag = state.activeCollection !== "all";
        const cmds = filteredCommands();
        if (!cmds.length) {
            const empty = document.createElement("div");
            empty.className = "cmd-row";
            empty.style.opacity = ".7";
            empty.innerHTML = "<div></div><div>(no commands yet)</div><div></div><div></div><div></div>";
            dom.commandList.appendChild(empty);
            updateCount();
            return;
        }

        cmds.forEach((cmd) => {
            const row = document.createElement("div");
            row.className = "cmd-row";
            row.dataset.id = cmd.id;
            if (allowDrag) {
                row.draggable = true;
                row.addEventListener("dragstart", handleCommandDragStart);
                row.addEventListener("dragover", handleCommandDragOver);
                row.addEventListener("drop", handleCommandDrop);
                row.addEventListener("dragend", () => finalizeCommandDrag(true));
            }

            const dragCell = document.createElement("div");
            dragCell.className = "drag-col";
            dragCell.innerHTML = allowDrag ? `<span class="drag-handle" title="Drag">&#x2630;</span>` : "";

            const titleCol = document.createElement("div");
            titleCol.className = "cmd-title";
            titleCol.textContent = cmd.title || "(untitled)";
            if (state.activeCollection === "all") {
                const badge = document.createElement("span");
                badge.className = "collection-label";
                badge.textContent = collectionName(cmd.group_id);
                titleCol.appendChild(badge);
            }
            if (cmd.requires_sudo) {
                const badge = document.createElement("span");
                badge.className = "requires-sudo";
                badge.textContent = "sudo";
                titleCol.appendChild(badge);
            }

            const cmdCol = document.createElement("div");
            cmdCol.className = "cmd-command";
            cmdCol.innerHTML = `<code title="Click to insert">${escapeHTML(cmd.command || "")}</code>`;
            cmdCol.addEventListener("click", () => sendToTerm(cmd.command, false));

            const descCol = document.createElement("div");
            descCol.className = "cmd-desc";
            descCol.textContent = cmd.description || "";

            const actionCol = document.createElement("div");
            actionCol.className = "cmd-actions";
            const runBtn = document.createElement("button");
            runBtn.textContent = "Run";
            runBtn.addEventListener("click", () => sendToTerm(cmd.command, true));
            const insertBtn = document.createElement("button");
            insertBtn.textContent = "Insert";
            insertBtn.className = "ghost";
            insertBtn.addEventListener("click", () => sendToTerm(cmd.command, false));
            const editBtn = document.createElement("button");
            editBtn.textContent = "Edit";
            editBtn.className = "edit";
            editBtn.addEventListener("click", () => openCommandModal(cmd));
            const delBtn = document.createElement("button");
            delBtn.textContent = "Delete";
            delBtn.className = "danger";
            delBtn.addEventListener("click", () => deleteCommand(cmd));
            actionCol.append(runBtn, insertBtn, editBtn, delBtn);

            row.append(dragCell, titleCol, cmdCol, descCol, actionCol);
            dom.commandList.appendChild(row);
        });
        updateCount();
    }

    function setActiveCollection(id) {
        state.activeCollection = id;
        renderTabs();
        renderCommands();
        updateCollectionActions();
    }

    function populateCollectionSelect(defaultId) {
        if (!dom.modalCollectionSelect) return;
        dom.modalCollectionSelect.innerHTML = "";
        state.collections.forEach((col) => {
            const opt = document.createElement("option");
            opt.value = col.id;
            opt.textContent = col.name || "Collection";
            dom.modalCollectionSelect.appendChild(opt);
        });
        if (defaultId) {
            dom.modalCollectionSelect.value = defaultId;
        } else if (state.activeCollection !== "all") {
            dom.modalCollectionSelect.value = state.activeCollection;
        }
    }

    function defaultGroupId() {
        if (state.activeCollection !== "all") return state.activeCollection;
        const first = state.collections[0];
        return first ? first.id : "";
    }

    function openCommandModal(cmd = null) {
        if (!dom.commandModal) return;
        const editing = Boolean(cmd);
        dom.commandModalTitle.textContent = editing ? "Edit command" : "Add command";
        dom.modalSaveBtn.textContent = editing ? "Update command" : "Save command";
        dom.cmdId.value = editing ? cmd.id : "";
        dom.modalTitleInput.value = editing ? (cmd.title || "") : "";
        dom.modalCommandInput.value = editing ? (cmd.command || "") : "";
        dom.modalDescInput.value = editing ? (cmd.description || "") : "";
        dom.modalSudo.checked = Boolean(editing ? cmd.requires_sudo : false);
        populateCollectionSelect(editing ? cmd.group_id : defaultGroupId());
        dom.commandModal.hidden = false;
        setTimeout(() => dom.modalTitleInput?.focus(), 30);
    }

    function closeCommandModal() {
        if (!dom.commandModal) return;
        dom.commandForm?.reset();
        dom.commandModal.hidden = true;
    }

    function openCollectionModal(col = null) {
        if (!dom.collectionModal) return;
        const editing = Boolean(col);
        dom.collectionModalTitle.textContent = editing ? "Rename collection" : "New collection";
        dom.collectionSaveBtn.textContent = editing ? "Update" : "Save";
        dom.collectionId.value = editing ? col.id : "";
        dom.collectionNameInput.value = editing ? (col.name || "") : "";
        dom.collectionModal.hidden = false;
        setTimeout(() => dom.collectionNameInput?.focus(), 30);
    }

    function closeCollectionModal() {
        if (!dom.collectionModal) return;
        dom.collectionForm?.reset();
        dom.collectionModal.hidden = true;
    }

    function updateCollectionActions() {
        if (!dom.actions) return;
        if (state.activeCollection === "all") {
            dom.actions.hidden = true;
        } else {
            dom.actions.hidden = false;
        }
    }

    function collectionName(id) {
        const col = state.collections.find((c) => c.id === id);
        return col ? col.name : "Uncategorized";
    }

    async function saveCommand(e) {
        e.preventDefault();
        const payload = {
            title: dom.modalTitleInput.value.trim(),
            command: dom.modalCommandInput.value.trim(),
            description: dom.modalDescInput.value.trim(),
            group_id: dom.modalCollectionSelect.value || defaultGroupId(),
            requires_sudo: dom.modalSudo.checked,
        };
        if (!payload.title || !payload.command) return;
        const id = dom.cmdId.value;
        try {
            if (id) {
                await fetchJSON(API.command(id), { method: "PATCH", body: payload });
                setFeedback("Command updated.");
            } else {
                await fetchJSON(API.commands, { method: "POST", body: payload });
                setFeedback("Command saved.");
            }
            closeCommandModal();
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    async function deleteCommand(cmd) {
        if (!window.confirm(`Delete "${cmd.title || cmd.command}"?`)) return;
        try {
            await fetchJSON(API.command(cmd.id), { method: "DELETE" });
            setFeedback("Command deleted.");
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    async function saveCollection(e) {
        e.preventDefault();
        const name = dom.collectionNameInput.value.trim();
        if (!name) return;
        const id = dom.collectionId.value;
        try {
            if (id) {
                await fetchJSON(API.collection(id), { method: "PATCH", body: { name } });
                if (state.activeCollection === id) setActiveCollection(id);
                setFeedback("Collection renamed.");
            } else {
                await fetchJSON(API.collections, { method: "POST", body: { name } });
                setFeedback("Collection created.");
            }
            closeCollectionModal();
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    async function deleteActiveCollection() {
        if (state.activeCollection === "all") return;
        const col = state.collections.find((c) => c.id === state.activeCollection);
        if (!col) return;
        if (!window.confirm(`Delete collection "${col.name}"? Commands move to Uncategorized.`)) return;
        try {
            await fetchJSON(API.collection(col.id), { method: "DELETE" });
            state.activeCollection = "all";
            setFeedback(`Deleted collection "${col.name}".`);
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    function handleCollectionDragStart(e) {
        dragState.type = "collection";
        dragState.id = e.currentTarget.dataset.id;
        e.currentTarget.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
    }

    function handleCollectionDragOver(e) {
        if (dragState.type !== "collection") return;
        e.preventDefault();
        const dragging = dom.tabsWrap.querySelector(".collection-tab.dragging");
        const target = e.currentTarget;
        if (!dragging || dragging === target) return;
        const after = e.offsetX > target.offsetWidth / 2;
        dom.tabsWrap.insertBefore(dragging, after ? target.nextSibling : target);
    }

    function handleCollectionDrop(e) {
        if (dragState.type !== "collection") return;
        e.preventDefault();
        finalizeCollectionDrag();
    }

    async function finalizeCollectionDrag(skipRequest = false) {
        const dragging = dom.tabsWrap?.querySelectorAll(".collection-tab.dragging") || [];
        dragging.forEach((btn) => btn.classList.remove("dragging"));
        if (skipRequest || dragState.type !== "collection") {
            dragState.type = null;
            dragState.id = null;
            return;
        }
        const order = Array.from(dom.tabsWrap.querySelectorAll(".collection-tab")).map((btn) => btn.dataset.id);
        dragState.type = null;
        dragState.id = null;
        try {
            await fetchJSON(API.reorderCollections, { method: "POST", body: { order } });
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    function handleCommandDragStart(e) {
        if (state.activeCollection === "all") {
            e.preventDefault();
            return;
        }
        dragState.type = "command";
        dragState.id = e.currentTarget.dataset.id;
        e.currentTarget.classList.add("dragging");
        e.dataTransfer.effectAllowed = "move";
    }

    function handleCommandDragOver(e) {
        if (dragState.type !== "command") return;
        e.preventDefault();
        const dragging = dom.commandList.querySelector(".cmd-row.dragging");
        const target = e.currentTarget;
        if (!dragging || dragging === target) return;
        const rect = target.getBoundingClientRect();
        const after = (e.clientY - rect.top) > rect.height / 2;
        dom.commandList.insertBefore(dragging, after ? target.nextSibling : target);
    }

    function handleCommandDrop(e) {
        if (dragState.type !== "command") return;
        e.preventDefault();
        finalizeCommandDrag();
    }

    async function finalizeCommandDrag(skipRequest = false) {
        const dragging = dom.commandList?.querySelectorAll(".cmd-row.dragging") || [];
        dragging.forEach((row) => row.classList.remove("dragging"));
        if (state.activeCollection === "all") {
            dragState.type = null;
            dragState.id = null;
            return;
        }
        if (skipRequest || dragState.type !== "command") {
            dragState.type = null;
            dragState.id = null;
            return;
        }
        const order = Array.from(dom.commandList.querySelectorAll(".cmd-row"))
            .map((row) => row.dataset.id)
            .filter(Boolean);
        dragState.type = null;
        dragState.id = null;
        try {
            await fetchJSON(API.reorderCommands, {
                method: "POST",
                body: { group_id: state.activeCollection, order },
            });
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        }
    }

    async function migrateLegacyIfNeeded(snapshot) {
        const legacyRaw = getSavedCmds();
        if (!legacyRaw || !legacyRaw.length) return false;
        const existing = Array.isArray(snapshot.commands) && snapshot.commands.length > 0;
        if (existing) return false;
        const payload = {
            version: 1,
            collections: [{ name: "Uncategorized" }],
            commands: legacyRaw.map((item) => ({
                title: item.title,
                command: item.command,
                description: item.desc,
                collection_name: "Uncategorized",
                requires_sudo: /^\s*sudo\b/.test(item.command || ""),
            })),
        };
        try {
            await fetchJSON(API.import, { method: "POST", body: payload });
            localStorage.removeItem(LS_CMDS_KEY);
            setFeedback(`Imported ${payload.commands.length} legacy commands.`);
            return true;
        } catch (err) {
            console.warn("Legacy import failed:", err);
            return false;
        }
    }

    function handleExport() {
        window.location.href = `${API.export}?ts=${Date.now()}`;
    }

    async function handleImportChange(e) {
        const file = e.target.files?.[0];
        if (!file) return;
        const form = new FormData();
        form.append("file", file);
        try {
            const res = await fetch(API.import, { method: "POST", body: form });
            const data = await res.json();
            if (!res.ok || !data?.ok) {
                throw new Error(data?.error || "Import failed");
            }
            setFeedback(`Imported ${data.summary?.added_commands || 0} commands.`);
            await loadCollections(false);
        } catch (err) {
            setFeedback(err.message, true);
        } finally {
            e.target.value = "";
        }
    }

    function initCommandCollections() {
        if ($search) {
            $search.addEventListener("input", (evt) => {
                state.search = evt.target.value || "";
                renderCommands();
            });
        }
        dom.addCommand?.addEventListener("click", () => openCommandModal());
        dom.addCollection?.addEventListener("click", () => openCollectionModal());
        dom.exportBtn?.addEventListener("click", handleExport);
        dom.importInput?.addEventListener("change", handleImportChange);
        dom.renameCollection?.addEventListener("click", () => {
            if (state.activeCollection === "all") return;
            const col = state.collections.find((c) => c.id === state.activeCollection);
            if (col) openCollectionModal(col);
        });
        dom.deleteCollection?.addEventListener("click", deleteActiveCollection);
        dom.commandForm?.addEventListener("submit", saveCommand);
        dom.collectionForm?.addEventListener("submit", saveCollection);
        document.querySelectorAll("[data-close-command]").forEach((btn) =>
            btn.addEventListener("click", closeCommandModal)
        );
        document.querySelectorAll("[data-close-collection]").forEach((btn) =>
            btn.addEventListener("click", closeCollectionModal)
        );
        dom.commandModal?.addEventListener("click", (e) => {
            if (e.target === dom.commandModal) closeCommandModal();
        });
        dom.collectionModal?.addEventListener("click", (e) => {
            if (e.target === dom.collectionModal) closeCollectionModal();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                if (!dom.commandModal?.hidden) closeCommandModal();
                if (!dom.collectionModal?.hidden) closeCollectionModal();
            }
        });
        loadCollections(true);
    }

    initCommandCollections();
    term.writeln("\x1b[32mConnected. Type commands here, or use the list on the right.\x1b[0m\n");
})();
