// === SIDEBAR.JS ===
// Handles sidebar toggle logic and state persistence across sessions

document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.querySelector(".sidebar");
    const closeBtn = document.querySelector("#btn");
    const navLinks = document.querySelectorAll(".nav-list li");

    // === Show/hide link names and tooltips depending on sidebar state ===
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

    // === Update hamburger icon based on sidebar state ===
    function updateToggleIcon() {
        if (sidebar.classList.contains("open")) {
            closeBtn.classList.replace("bx-menu", "bx-menu-alt-right");
        } else {
            closeBtn.classList.replace("bx-menu-alt-right", "bx-menu");
        }
    }

    // === Load saved state from localStorage ===
    function getState() {
        return localStorage.getItem("sidebarState") || "open";
    }

    // === Save new sidebar state to localStorage ===
    function setState(state) {
        localStorage.setItem("sidebarState", state);
    }

    // === Apply current sidebar state on load ===
    const currentState = document.documentElement.classList.contains("sidebar-open") ? "open" : "closed";
    sidebar.classList.toggle("open", currentState === "open");
    updateLinkVisibility();
    updateToggleIcon();

    // === Toggle sidebar on button click ===
    closeBtn.addEventListener("click", () => {
        const isOpen = sidebar.classList.contains("open");
        const newState = isOpen ? "closed" : "open";

        // Update <html> class to reflect state (used in CSS)
        document.documentElement.classList.remove("sidebar-open", "sidebar-closed");
        document.documentElement.classList.add(`sidebar-${newState}`);
        sidebar.classList.toggle("open", newState === "open");

        setState(newState);
        updateToggleIcon();
        updateLinkVisibility();
    });
});
