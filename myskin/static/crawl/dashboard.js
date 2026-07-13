const TOKEN_KEY = "myskin_api_token";
const tokenInput = document.getElementById("token");
const errorEl = document.getElementById("error");
const statePill = document.getElementById("statePill");
const runMeta = document.getElementById("runMeta");
const compactBar = document.getElementById("compactBar");
const eventsEl = document.getElementById("events");

let lastHealth = null;
let lastLiveData = null;

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
        borderColor: "#e8b84a",
        backgroundColor: "rgba(232,184,74,0.12)",
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
        borderColor: "#5b9fd4",
        backgroundColor: "rgba(91,159,212,0.08)",
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

function metric(label, value, tone = "") {
  const toneClass = tone ? ` ${tone}` : "";
  return `<span class="metric${toneClass}"><span class="m-label">${label}</span><span class="m-val">${value}</span></span>`;
}

function sep() {
  return `<span class="sep">·</span>`;
}

function badge(text, tone = "") {
  const toneClass = tone ? ` ${tone}` : "";
  return `<span class="badge${toneClass}">${text}</span>`;
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

function renderCompactBar() {
  const health = lastHealth;
  const data = lastLiveData;
  const live = data?.live;
  const stats = live?.stats || {};
  const rows = [];

  if (health) {
    const formats = health.catalog_by_format || {};
    const fmtParts = Object.keys(formats).sort().map((fmt) =>
      metric(fmt.toUpperCase(), formats[fmt], fmt === "md" ? "accent" : "")
    );

    const catalogParts = [
      metric("Docs", health.document_count, "accent"),
      metric("PT catalog", health.catalog_passthrough_count || 0),
      metric("URLs", health.catalog_with_file_url || 0, health.catalog_with_file_url ? "ok" : "warn"),
      ...fmtParts,
    ];

    rows.push(`<div class="compact-row">${catalogParts.join(sep())}</div>`);
    rows.push(`<div class="compact-row badges">${[
      badge(health.passthrough_enabled ? "passthrough" : "no passthrough", health.passthrough_enabled ? "ok" : ""),
      badge(health.follow_file_links === false ? "file links off" : "file links", health.follow_file_links === false ? "" : "ok"),
      health.sitemap_only ? badge("sitemap", "accent") : badge("link crawl"),
      health.public_base_url ? badge("public URL", "ok") : badge("no public URL", "warn"),
    ].join("")}</div>`);
  }

  if (live?.run_id) {
    const processed = (stats.pages_fetched || 0) + (stats.pdfs_fetched || 0);
    const pct = live.max_pages ? Math.min(100, Math.round((processed / live.max_pages) * 100)) : 0;
    const usesSitemap = (stats.sitemap_urls || 0) > 0;

    const runParts = [
      metric("Processed", `${processed} (${pct}%)`, "accent"),
      metric("Queue", live.queue_pending, live.queue_pending ? "warn" : ""),
    ];

    if (usesSitemap) {
      runParts.push(metric("Sitemap", stats.sitemap_urls));
      runParts.push(metric("Queued", stats.sitemap_queued, stats.sitemap_queued ? "warn" : ""));
      runParts.push(metric("Skipped", stats.sitemap_skipped));
    } else {
      runParts.push(metric("Links", stats.discovered, "accent"));
    }

    rows.push(`<div class="compact-row">${runParts.join(sep())}</div>`);
    rows.push(`<div class="compact-row">${[
      '<span class="row-label">Pages</span>',
      metric("upd", stats.pages_updated, "ok"),
      metric("same", stats.pages_unchanged),
      metric("fail", stats.pages_failed, stats.pages_failed ? "bad" : ""),
      metric("fetch", stats.pages_fetched),
    ].join(sep())}</div>`);
    rows.push(`<div class="compact-row">${[
      '<span class="row-label">Files</span>',
      metric("found", stats.files_discovered || 0, "accent"),
      metric("upd", stats.pdfs_updated, "ok"),
      metric("same", stats.pdfs_unchanged),
      metric("fail", stats.pdfs_failed, stats.pdfs_failed ? "bad" : ""),
      metric("fetch", stats.pdfs_fetched),
    ].join(sep())}</div>`);
  } else if (!health) {
    rows.push('<div class="compact-row" style="color:var(--muted)">Waiting for data…</div>');
  }

  compactBar.innerHTML = rows.join("");
}

function render(data) {
  lastLiveData = data;
  const running = data.running;
  statePill.textContent = running ? "running" : "idle";
  statePill.className = "pill " + (running ? "running" : "idle");

  const live = data.live;
  const stats = live.stats || {};
  const usesSitemap = (stats.sitemap_urls || 0) > 0;

  chart.data.datasets[1].label = usesSitemap ? "In sitemap" : "Discovered";

  runMeta.textContent = live.run_id
    ? `run #${live.run_id} · ${live.trigger || "—"} · ${live.seed_url || ""}`
    : "No crawl run yet";

  renderCompactBar();
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
    lastHealth = await res.json();
    renderCompactBar();
  } catch (_) {
    lastHealth = null;
    renderCompactBar();
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
