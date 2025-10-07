document.addEventListener("DOMContentLoaded", function () {
    const font = new FontFaceObserver("Fira Mono");

    font.load().then(() => {
        const term = new Terminal({
            cursorBlink: true,
            scrollback: 1000,
            fontFamily: '"Fira Mono", monospace',
            fontSize: 14,
            lineHeight: 1,
            fontWeight: 'normal',
            letterSpacing: 0,
            theme: { background: '#000000', foreground: '#00FF00' },
            allowProposedApi: true,
            allowTransparency: true,
            lineWrap: true
        });

        const fitAddon = new FitAddon.FitAddon();
        const canvasAddon = new CanvasAddon.CanvasAddon();
        const serializeAddon = new SerializeAddon.SerializeAddon();

        term.loadAddon(fitAddon);
        term.loadAddon(canvasAddon);
        term.loadAddon(serializeAddon);

        term.open(document.getElementById("terminal"));
        fitAddon.fit();
        term.focus();

        const savedBuffer = sessionStorage.getItem("terminalSerialized");
        if (savedBuffer) {
            try {
                serializeAddon.deserialize(savedBuffer);
                console.log("Tidligere terminal-buffer gendannet.");
            } catch (err) {
                console.error("Fejl under gendannelse af buffer:", err);
            }
        } else {
            console.log("Ingen tidligere terminal-buffer fundet.");
        }

        setTimeout(() => {
            console.log("Opretter socket-forbindelse...");
            const socket = io();

            term.onData(data => {
                socket.emit("input", data);
            });

            socket.on("output", data => {
                term.write(data);
                const serialized = serializeAddon.serialize();
                sessionStorage.setItem("terminalSerialized", serialized);
            });

            const stopBtn = document.getElementById("stop-process-btn");
            if (stopBtn) {
                stopBtn.addEventListener("click", () => {
                    socket.emit("input", "\x03");
                    term.focus();
                });
            }
        }, 500);

        window.addEventListener("beforeunload", () => {
            const serialized = serializeAddon.serialize();
            sessionStorage.setItem("terminalSerialized", serialized);
        });

        window.addEventListener("resize", () => {
            fitAddon.fit();
            term.focus();
        });

        // === Kommandooversigt ===
        const defaultCommands = [
            { title: "List directory", command: "ls", desc: "Show files in directory" },
            { title: "Change directory", command: "cd <dir>", desc: "Navigate to another folder" },
            { title: "Current path", command: "pwd", desc: "Show current path" },
            { title: "CPU usage", command: "top", desc: "Show CPU usage and processes" },
            { title: "RAM info", command: "free -h", desc: "Show RAM and swap usage" },
            { title: "Network info", command: "ip a", desc: "Show IP and network interfaces" }
        ];

        let commands = loadCommands();
        renderCommandList();

        function loadCommands() {
            const saved = localStorage.getItem("linuxCommands");
            return saved ? JSON.parse(saved) : defaultCommands;
        }

        function saveCommands(cmds) {
            localStorage.setItem("linuxCommands", JSON.stringify(cmds));
        }

        function renderCommandList() {
            const listDiv = document.getElementById("command-list");
            const filter = document.getElementById("search-box").value.toLowerCase();
            listDiv.innerHTML = "";

            const ul = document.createElement("ul");
            ul.classList.add("command-list");

            commands.forEach((cmd, index) => {
                if (
                    cmd.title.toLowerCase().includes(filter) ||
                    cmd.command.toLowerCase().includes(filter) ||
                    (cmd.desc && cmd.desc.toLowerCase().includes(filter))
                ) {
                    const li = document.createElement("li");
                    li.classList.add("command-item");

                    const content = document.createElement("div");
                    content.classList.add("command-content");

                    const title = document.createElement("span");
                    title.classList.add("command-title");
                    title.textContent = `${cmd.title}: `;

                    const command = document.createElement("code");
                    command.textContent = cmd.command;

                    const desc = document.createElement("span");
                    if (cmd.desc) {
                        desc.classList.add("command-desc");
                        desc.textContent = " – " + cmd.desc;
                    }

                    const deleteBtn = document.createElement("button");
                    deleteBtn.textContent = "Delete";
                    deleteBtn.classList.add("command-delete");
                    deleteBtn.addEventListener("click", () => {
                        commands.splice(index, 1);
                        saveCommands(commands);
                        renderCommandList();
                    });

                    title.addEventListener("click", () => {
                        term.paste(cmd.command);
                        term.focus();
                    });

                    content.appendChild(title);
                    content.appendChild(command);
                    if (cmd.desc) content.appendChild(desc);
                    li.appendChild(content);
                    li.appendChild(deleteBtn);
                    ul.appendChild(li);
                }
            });

            listDiv.appendChild(ul);
        }

        document.getElementById("add-command-form").addEventListener("submit", function (e) {
            e.preventDefault();
            const title = document.getElementById("cmd-title").value.trim();
            const command = document.getElementById("cmd-command").value.trim();
            const desc = document.getElementById("cmd-desc").value.trim();
            if (!title || !command) return;
            commands.push({ title, command, desc });
            saveCommands(commands);
            renderCommandList();
            this.reset();
        });

        document.getElementById("search-box").addEventListener("input", renderCommandList);
    });
});
