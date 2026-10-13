/*
 * LOSTFinder dashboard: draws the charts from the server-rendered metrics,
 * then polls the metrics endpoint so cards and charts follow the database.
 */
(function () {
    "use strict";

    const script = document.currentScript;
    const metricsUrl = script.dataset.metricsUrl;
    const refreshMs = Number(script.dataset.refreshSeconds || 30) * 1000;

    // Validated two-series palette (blue / orange) plus recessive chrome,
    // read from CSS so light and dark each get their own steps.
    function readColors() {
        const css = getComputedStyle(document.documentElement);
        const token = (name) => css.getPropertyValue(name).trim();
        return {
            lost: token("--lf-series-lost"),
            found: token("--lf-series-found"),
            grid: token("--lf-grid"),
            axisText: token("--lf-axis-text"),
            surface: token("--lf-chart-surface"),
        };
    }

    let COLORS = readColors();

    Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
    Chart.defaults.color = COLORS.axisText;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.boxPadding = 4;

    function integerAxis() {
        return {
            beginAtZero: true,
            ticks: { precision: 0, color: COLORS.axisText },
            grid: { color: COLORS.grid },
            border: { display: false },
        };
    }

    function categoryAxis() {
        return {
            ticks: { color: COLORS.axisText },
            grid: { display: false },
            border: { color: COLORS.grid },
        };
    }

    function lineDataset(label, data, colorKey) {
        return {
            label,
            data,
            colorKey,
            borderColor: COLORS[colorKey],
            backgroundColor: COLORS[colorKey],
            borderWidth: 2,
            pointRadius: 4,           // 8px markers
            pointHoverRadius: 6,
            pointBorderColor: COLORS.surface,
            pointBorderWidth: 2,      // surface ring where marks overlap
            tension: 0,               // whole-number counts: no spline overshoot
        };
    }

    function barDataset(label, data) {
        return {
            label,
            data,
            colorKey: "lost",
            backgroundColor: COLORS.lost,
            borderRadius: 4,
            borderSkipped: "start",   // rounded data-end, anchored to baseline
            maxBarThickness: 18,
        };
    }

    function horizontalBarOptions() {
        return {
            indexAxis: "y",
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: integerAxis(), y: categoryAxis() },
        };
    }

    const initial = JSON.parse(
        document.getElementById("dashboard-metrics").textContent
    );

    const charts = {
        activity: new Chart(document.getElementById("chart-activity"), {
            type: "line",
            data: {
                labels: initial.charts.activity.labels,
                datasets: [
                    lineDataset("Lost", initial.charts.activity.lost, "lost"),
                    lineDataset("Found", initial.charts.activity.found, "found"),
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        position: "top",
                        align: "end",
                        labels: {
                            usePointStyle: true,
                            pointStyle: "circle",
                            boxWidth: 8,
                            boxHeight: 8,
                            padding: 16,
                        },
                    },
                },
                scales: { x: categoryAxis(), y: integerAxis() },
            },
        }),
        status: new Chart(document.getElementById("chart-status"), {
            type: "bar",
            data: {
                labels: initial.charts.status.labels,
                datasets: [barDataset("Count", initial.charts.status.values)],
            },
            options: horizontalBarOptions(),
        }),
        categories: new Chart(document.getElementById("chart-categories"), {
            type: "bar",
            data: {
                labels: initial.charts.categories.labels,
                datasets: [barDataset("Reports", initial.charts.categories.values)],
            },
            options: horizontalBarOptions(),
        }),
    };

    // ---------- accessible table views ----------

    function renderTable(key, headers, rows) {
        const host = document.querySelector(`[data-table-for="${key}"]`);
        if (!host) return;

        const table = document.createElement("table");
        table.className = "table table-sm mb-0";
        const head = table.createTHead().insertRow();
        headers.forEach((text) => {
            const th = document.createElement("th");
            th.scope = "col";
            th.textContent = text;
            head.appendChild(th);
        });
        const body = table.createTBody();
        rows.forEach((cells) => {
            const tr = body.insertRow();
            cells.forEach((text) => { tr.insertCell().textContent = text; });
        });
        host.replaceChildren(table);
    }

    function renderTables(data) {
        const a = data.charts.activity;
        renderTable("activity", ["Day", "Lost", "Found"],
            a.labels.map((day, i) => [day, a.lost[i], a.found[i]]));

        const s = data.charts.status;
        renderTable("status", ["Status", "Count"],
            s.labels.map((label, i) => [label, s.values[i]]));

        const c = data.charts.categories;
        renderTable("categories", ["Category", "Reports"],
            c.labels.map((label, i) => [label, c.values[i]]));

        const empty = document.querySelector('[data-empty-for="categories"]');
        if (empty) empty.classList.toggle("d-none", c.labels.length > 0);
    }

    // ---------- live refresh ----------

    function updateMetrics(values) {
        Object.entries(values).forEach(([key, value]) => {
            document.querySelectorAll(`[data-metric="${key}"]`).forEach((el) => {
                const text = String(value);
                if (el.textContent.trim() === text) return;
                el.textContent = text;
                const box = el.closest(".small-box, .info-box");
                if (box) {
                    box.classList.remove("lf-pulse");
                    void box.offsetWidth;   // restart the animation
                    box.classList.add("lf-pulse");
                }
            });
        });
    }

    function updateCharts(data) {
        const a = data.charts.activity;
        charts.activity.data.labels = a.labels;
        charts.activity.data.datasets[0].data = a.lost;
        charts.activity.data.datasets[1].data = a.found;

        charts.status.data.labels = data.charts.status.labels;
        charts.status.data.datasets[0].data = data.charts.status.values;

        charts.categories.data.labels = data.charts.categories.labels;
        charts.categories.data.datasets[0].data = data.charts.categories.values;

        Object.values(charts).forEach((chart) => chart.update("none"));
    }

    async function refresh() {
        if (document.hidden) return;
        try {
            const response = await fetch(metricsUrl, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });
            // A redirect means the session ended; stop quietly.
            if (!response.ok || response.redirected) return;
            const data = await response.json();
            updateMetrics(data.values);
            updateCharts(data);
            renderTables(data);
            document.getElementById("lf-updated").textContent = data.generated_at;
        } catch (error) {
            console.warn("Dashboard refresh failed", error);
        }
    }

    // ---------- theme switching ----------

    function applyTheme() {
        COLORS = readColors();
        Chart.defaults.color = COLORS.axisText;

        Object.values(charts).forEach((chart) => {
            chart.data.datasets.forEach((ds) => {
                const color = COLORS[ds.colorKey];
                ds.backgroundColor = color;
                if (ds.borderColor) ds.borderColor = color;
                if (ds.pointBorderColor) ds.pointBorderColor = COLORS.surface;
            });

            const horizontal = chart.options.indexAxis === "y";
            chart.options.scales.x = horizontal ? integerAxis() : categoryAxis();
            chart.options.scales.y = horizontal ? categoryAxis() : integerAxis();
            if (chart.options.plugins.legend.labels) {
                chart.options.plugins.legend.labels.color = COLORS.axisText;
            }
            chart.update("none");
        });
    }

    // AdminLTE stamps data-bs-theme on <html> when the colour mode changes.
    new MutationObserver(applyTheme).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-bs-theme"],
    });

    applyTheme();
    renderTables(initial);
    setInterval(refresh, refreshMs);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) refresh();
    });
})();
