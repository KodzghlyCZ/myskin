DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>myskin crawl dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f1419;
      --panel: #1a2332;
      --border: #2d3a4f;
      --text: #e8eef7;
      --muted: #8b9cb3;
      --accent: #5b9fd4;
      --ok: #6bcf7f;
      --warn: #e8b84a;
      --bad: #e86a6a;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.45;
    }
    header {
      padding: 1rem 1.25rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: center;
      justify-content: space-between;
    }
    h1 { margin: 0; font-size: 1.2rem; font-weight: 600; }
    .auth {
      display: flex;
      gap: 0.5rem;
      align-items: center;
      flex-wrap: wrap;
    }
    input, button {
      font: inherit;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      padding: 0.45rem 0.7rem;
    }
    button {
      cursor: pointer;
      background: #243044;
    }
    button:hover { border-color: var(--accent); }
    main { padding: 1rem 1.25rem 2rem; max-width: 1200px; margin: 0 auto; }
    .status-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1rem;
      align-items: center;
    }
    .pill {
      padding: 0.25rem 0.65rem;
      border-radius: 999px;
      font-size: 0.85rem;
      border: 1px solid var(--border);
      background: var(--panel);
    }
    .pill.running { border-color: var(--ok); color: var(--ok); }
    .pill.idle { color: var(--muted); }
    .stats-layout {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .stat-group {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.85rem 1rem 1rem;
    }
    .stat-group-title {
      margin: 0 0 0.75rem;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 0.6rem;
    }
    .stat-grid.cols-1 { grid-template-columns: 1fr; }
    .card {
      background: #121a26;
      border: 1px solid #223044;
      border-radius: 10px;
      padding: 0.65rem 0.75rem;
    }
    .card .label { color: var(--muted); font-size: 0.75rem; }
    .card .value { font-size: 1.35rem; font-weight: 600; margin-top: 0.1rem; line-height: 1.2; }
    .card .value.ok { color: var(--ok); }
    .card .value.warn { color: var(--warn); }
    .card .value.bad { color: var(--bad); }
    .card .value.accent { color: var(--accent); }
    .card .sub { color: var(--muted); font-size: 0.72rem; margin-top: 0.15rem; }
    .chart-wrap {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      margin-bottom: 1rem;
      height: 320px;
    }
    .events {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.75rem 1rem;
      max-height: 280px;
      overflow: auto;
      font-family: ui-monospace, monospace;
      font-size: 0.82rem;
    }
    .event { padding: 0.2rem 0; border-bottom: 1px solid #223044; }
    .event:last-child { border-bottom: none; }
    .event a {
      color: var(--accent);
      text-decoration: none;
    }
    .event a:hover { text-decoration: underline; }
    .outcome-updated { color: var(--ok); }
    .outcome-failed { color: var(--bad); }
    .outcome-skipped, .outcome-unchanged { color: var(--muted); }
    .meta { color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; }
    #error { color: var(--bad); min-height: 1.2rem; margin-bottom: 0.5rem; }
  </style>
</head>
<body>
  <header>
    <h1>myskin crawl dashboard</h1>
    <div class="auth">
      <input id="token" type="password" placeholder="API token" size="24" autocomplete="off">
      <button id="saveToken" type="button">Save token</button>
      <button id="startCrawl" type="button">Start crawl</button>
    </div>
  </header>
  <main>
    <div id="error"></div>
    <div class="status-row">
      <span id="statePill" class="pill idle">idle</span>
      <span id="runMeta" class="meta"></span>
    </div>
    <div class="stats-layout" id="statsGrid"></div>
    <div class="chart-wrap">
      <canvas id="chart"></canvas>
    </div>
    <h2 style="font-size:1rem;margin:0 0 0.5rem;">Recent pages</h2>
    <div class="events" id="events"></div>
  </main>
  <script>
    const TOKEN_KEY = "myskin_api_token";
    const tokenInput = document.getElementById("token");
    const errorEl = document.getElementById("error");
    const statePill = document.getElementById("statePill");
    const runMeta = document.getElementById("runMeta");
    const statsGrid = document.getElementById("statsGrid");
    const eventsEl = document.getElementById("events");

    tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";
    document.getElementById("saveToken").onclick = () => {
      localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
      errorEl.textContent = "";
    };

    const ctx = document.getElementById("chart");
    const chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Queue",
            data: [],
            borderColor: "#5b9fd4",
            backgroundColor: "rgba(91,159,212,0.12)",
            tension: 0.1,
            fill: true,
            pointRadius: 0,
          },
          {
            label: "In sitemap",
            data: [],
            borderColor: "#6bcf7f",
            backgroundColor: "rgba(107,207,127,0.08)",
            tension: 0.1,
            fill: false,
            pointRadius: 0,
          },
          {
            label: "Processed",
            data: [],
            borderColor: "#e8b84a",
            tension: 0.1,
            fill: false,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        animation: false,
        scales: {
          x: {
            title: { display: true, text: "Elapsed (s)", color: "#8b9cb3" },
            ticks: {
              color: "#8b9cb3",
              maxTicksLimit: 12,
              autoSkip: true,
            },
            grid: { color: "#223044" },
          },
          y: {
            beginAtZero: true,
            grace: "5%",
            ticks: { color: "#8b9cb3" },
            grid: { color: "#223044" },
          },
        },
        plugins: {
          legend: { labels: { color: "#e8eef7" } },
        },
      },
    });

    let chartRunId = null;
    let chartSampleLen = 0;

    function resetChart() {
      chart.data.labels = [];
      chart.data.datasets.forEach((ds) => { ds.data = []; });
      chartSampleLen = 0;
    }

    function sampleLabel(sample) {
      return `${sample.elapsed_s}s`;
    }

    function pushSample(sample) {
      chart.data.labels.push(sampleLabel(sample));
      chart.data.datasets[0].data.push(sample.queue);
      chart.data.datasets[1].data.push(sample.discovered);
      chart.data.datasets[2].data.push(sample.processed);
      chart.update("none");
    }

    function loadSamples(samples) {
      chart.data.labels = samples.map(sampleLabel);
      chart.data.datasets[0].data = samples.map((s) => s.queue);
      chart.data.datasets[1].data = samples.map((s) => s.discovered);
      chart.data.datasets[2].data = samples.map((s) => s.processed);
      chartSampleLen = samples.length;
      chart.update("none");
    }

    function syncChart(live) {
      const samples = live.samples || [];

      if (!live.run_id) {
        if (chartSampleLen > 0) {
          resetChart();
          chart.update("none");
        }
        chartRunId = null;
        return;
      }

      if (live.run_id !== chartRunId || samples.length < chartSampleLen) {
        chartRunId = live.run_id;
        resetChart();
        if (samples.length) loadSamples(samples);
        return;
      }

      for (let i = chartSampleLen; i < samples.length; i++) {
        pushSample(samples[i]);
      }
      chartSampleLen = samples.length;
    }

    function card(label, value, { tone = "", sub = "" } = {}) {
      const toneClass = tone ? ` ${tone}` : "";
      const subHtml = sub ? `<div class="sub">${sub}</div>` : "";
      return `<div class="card"><div class="label">${label}</div><div class="value${toneClass}">${value}</div>${subHtml}</div>`;
    }

    function statGroup(title, cards, { cols = 2 } = {}) {
      const gridClass = cols === 1 ? "stat-grid cols-1" : "stat-grid";
      return `<section class="stat-group"><h2 class="stat-group-title">${title}</h2><div class="${gridClass}">${cards.join("")}</div></section>`;
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function eventLabel(event) {
      const label = escapeHtml(event.label || event.url);
      const url = event.url || "";
      if (!url.startsWith("http://") && !url.startsWith("https://")) {
        return label;
      }
      return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    }

    function authHeaders() {
      const token = tokenInput.value.trim() || localStorage.getItem(TOKEN_KEY) || "";
      if (!token) throw new Error("Set your API token first");
      return { Authorization: `Bearer ${token}` };
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) },
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status} ${body}`);
      }
      return res.json();
    }

    function render(data) {
      const running = data.running;
      statePill.textContent = running ? "running" : "idle";
      statePill.className = "pill " + (running ? "running" : "idle");

      const live = data.live;
      const stats = live.stats;
      const processed = stats.pages_fetched + stats.pdfs_fetched;
      const pct = live.max_pages ? Math.min(100, Math.round((processed / live.max_pages) * 100)) : 0;
      const usesSitemap = stats.sitemap_urls > 0;

      chart.data.datasets[1].label = usesSitemap ? "In sitemap" : "Discovered";

      runMeta.textContent = live.run_id
        ? `run #${live.run_id} · ${live.trigger || "—"} · ${live.seed_url || ""}`
        : "No crawl run yet";

      const groups = [
        statGroup("Run", [
          card("Processed", `${processed}`, {
            tone: "accent",
            sub: `${pct}% of ${live.max_pages} max`,
          }),
          card("Queue", live.queue_pending, { tone: live.queue_pending ? "warn" : "" }),
        ]),
      ];

      if (usesSitemap) {
        groups.push(statGroup("Sitemap", [
          card("Discovered", stats.sitemap_urls, {
            tone: "accent",
            sub: "URLs in XML",
          }),
          card("To crawl", stats.sitemap_queued, {
            tone: stats.sitemap_queued ? "warn" : "",
            sub: "queued this run",
          }),
          card("Skipped", stats.sitemap_skipped, {
            sub: "unchanged by lastmod",
          }),
        ]));
      } else {
        groups.push(statGroup("Discovery", [
          card("Links found", stats.discovered, { tone: "accent" }),
        ], { cols: 1 }));
      }

      groups.push(statGroup("Pages", [
        card("Updated", stats.pages_updated, { tone: "ok" }),
        card("Unchanged", stats.pages_unchanged),
        card("Failed", stats.pages_failed, { tone: stats.pages_failed ? "bad" : "" }),
        card("Fetched", stats.pages_fetched),
      ]));

      groups.push(statGroup("PDFs", [
        card("Updated", stats.pdfs_updated, { tone: "ok" }),
        card("Unchanged", stats.pdfs_unchanged),
        card("Failed", stats.pdfs_failed, { tone: stats.pdfs_failed ? "bad" : "" }),
        card("Fetched", stats.pdfs_fetched),
      ]));

      statsGrid.innerHTML = groups.join("");

      syncChart(live);

      eventsEl.innerHTML = live.events.length
        ? live.events.slice().reverse().map((e) => {
            const cls = `outcome-${e.outcome}`;
            return `<div class="event"><span class="${cls}">[${e.kind}] ${e.outcome}</span> ${eventLabel(e)}</div>`;
          }).join("")
        : '<div class="event" style="color:#8b9cb3">Waiting for crawl events…</div>';
    }

    async function refresh() {
      try {
        const data = await api("/api/crawl/live");
        errorEl.textContent = "";
        render(data);
      } catch (err) {
        errorEl.textContent = err.message;
      }
    }

    document.getElementById("startCrawl").onclick = async () => {
      try {
        await api("/api/crawl/start", { method: "POST" });
        errorEl.textContent = "";
        await refresh();
      } catch (err) {
        errorEl.textContent = err.message;
      }
    };

    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>
"""
