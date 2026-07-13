const TOKEN_KEY = "myskin_api_token";
const tokenInput = document.getElementById("token");
const errorEl = document.getElementById("error");
const statePill = document.getElementById("statePill");
const runMeta = document.getElementById("runMeta");
const statsGrid = document.getElementById("statsGrid");
const catalogGrid = document.getElementById("catalogGrid");
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

function renderCatalog(health) {
  if (!health) {
    catalogGrid.innerHTML = "";
    return;
  }
  const formats = health.catalog_by_format || {};
  const formatCards = Object.keys(formats).sort().map((fmt) =>
    card(fmt.toUpperCase(), formats[fmt], { tone: fmt === "md" ? "accent" : "" })
  );
  const extList = (health.passthrough_extensions || []).join(", ") || "—";
  const groups = [
    statGroup("Catalog", [
      card("Documents", health.document_count, { tone: "accent" }),
      card("With file URL", health.catalog_with_file_url || 0, {
        tone: health.catalog_with_file_url ? "ok" : "warn",
        sub: health.public_base_url ? "ready for RAGFlow" : "set api.public_base_url",
      }),
    ]),
    statGroup("Formats", formatCards.length ? formatCards : [
      card("No documents", "0", { sub: "Run a crawl to populate data/" }),
    ], { cols: formatCards.length > 2 ? 2 : 1 }),
    statGroup("Ingestion", [
      card("Passthrough", health.passthrough_enabled ? "on" : "off", {
        tone: health.passthrough_enabled ? "ok" : "",
        sub: extList,
      }),
      card("File links", health.follow_file_links === false ? "off" : "on", {
        tone: health.follow_file_links === false ? "" : "ok",
        sub: health.sitemap_only ? "hybrid sitemap mode" : "link crawl",
      }),
      card("Public URL", health.public_base_url || "not set", {
        sub: health.public_base_url ? "file_url enabled" : "set api.public_base_url",
      }),
    ], { cols: 1 }),
  ];
  catalogGrid.innerHTML = groups.join("");
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

  groups.push(statGroup("Passthrough files", [
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

async function refreshHealth() {
  try {
    const res = await fetch("/health");
    if (!res.ok) return;
    renderCatalog(await res.json());
  } catch (_) {
    catalogGrid.innerHTML = "";
  }
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

refreshHealth();
refresh();
setInterval(refresh, 1500);
setInterval(refreshHealth, 5000);
