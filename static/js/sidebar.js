document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.querySelector(".sidebar");
    const closeBtn = document.querySelector("#btn");
    const navLinks = document.querySelectorAll(".nav-list li");

    function updateLinkVisibility() {
        navLinks.forEach(link => {
            const linkName = link.querySelector(".links_name");
            const tooltip = link.querySelector(".tooltip");

            if (sidebar.classList.contains("open")) {
                if (linkName) linkName.style.opacity = "1";
                if (tooltip) tooltip.style.display = "none";
            } else {
                if (linkName) linkName.style.opacity = "0";
                if (tooltip) tooltip.style.display = "block";
            }
        });
    }

    function updateToggleIcon() {
        if (sidebar.classList.contains("open")) {
            closeBtn.classList.replace("bx-menu", "bx-menu-alt-right");
        } else {
            closeBtn.classList.replace("bx-menu-alt-right", "bx-menu");
        }
    }

    function getState() {
        return localStorage.getItem("sidebarState") || "open";
    }

    function setState(state) {
        localStorage.setItem("sidebarState", state);
    }

    // Apply state (read from <html> class)
    const currentState = document.documentElement.classList.contains("sidebar-open") ? "open" : "closed";
    sidebar.classList.toggle("open", currentState === "open");
    updateLinkVisibility();
    updateToggleIcon();

    closeBtn.addEventListener("click", () => {
        const isOpen = sidebar.classList.contains("open");
        const newState = isOpen ? "closed" : "open";

        // Toggle classes
        document.documentElement.classList.remove("sidebar-open", "sidebar-closed");
        document.documentElement.classList.add(`sidebar-${newState}`);
        sidebar.classList.toggle("open", newState === "open");

        setState(newState);
        updateToggleIcon();
        updateLinkVisibility();
    });
});
