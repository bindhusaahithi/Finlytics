if ("serviceWorker" in navigator) {
    window.addEventListener("load", function() {
        navigator.serviceWorker.register("/service-worker.js");
    });
}

window.addEventListener("DOMContentLoaded", function() {
    const navItems = Array.from(
        document.querySelectorAll("[data-tab-target]")
    );
    const tabSections = Array.from(
        document.querySelectorAll(".dashboard-tab-section[data-tab]")
    );

    if (!navItems.length || !tabSections.length) {
        return;
    }

    function setActiveTab(tabName) {
        navItems.forEach(function(item) {
            const isActive = item.dataset.tabTarget === tabName;
            item.classList.toggle("is-active", isActive);
            item.classList.toggle("active", isActive);
            item.setAttribute("aria-current", isActive ? "page" : "false");
        });

        tabSections.forEach(function(section) {
            const shouldShow = section.dataset.tab === tabName;
            section.classList.toggle("is-hidden", !shouldShow);
        });

        if (
            tabName === "charts" &&
            typeof Chart !== "undefined" &&
            Chart.instances
        ) {
            requestAnimationFrame(function() {
                Object.values(Chart.instances).forEach(function(chart) {
                    if (chart && typeof chart.resize === "function") {
                        chart.resize();
                    }
                });
            });
        }
    }

    navItems.forEach(function(item) {
        item.addEventListener("click", function(event) {
            event.preventDefault();
            const tabName = item.dataset.tabTarget;

            if (!tabName) {
                return;
            }

            setActiveTab(tabName);
            window.history.replaceState(null, "", "#" + tabName);
        });
    });

    const initialHash = window.location.hash.replace("#", "");
    const defaultTab = navItems.some(function(item) {
        return item.dataset.tabTarget === initialHash;
    }) ? initialHash : "account";

    setActiveTab(defaultTab);
});
