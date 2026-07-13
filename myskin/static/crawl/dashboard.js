const TOKEN_KEY = "myskin_api_token";
const tokenInput = document.getElementById("token");
const errorEl = document.getElementById("error");
const statePill = document.getElementById("statePill");
const runMeta = document.getElementById("runMeta");
const compactBar = document.getElementById("compactBar");
const eventsEl = document.getElementById("events");
const queueTailEl = document.getElementById("queueTail");

let lastHealth = null;
let lastLiveData = null;
let chartBfsMode = false;

tokenInput.value = localStorage.getItem(TOKEN_KEY) || "";
document.getElementById("saveToken").onclick = () => {
  localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
  errorEl.textContent = "";
};

const ctx = document.getElementById("chart");

function buildChartDatasets(bfsMode) {
  const datasets = [
    {
      label: "Queue",
      data: [],
      borderColor: "#e8b84a",
      backgroundColor: "rgba(232,184,74,0.12)",
      tension: 0.1,
      fill: true,
      pointRadius: 0,
    },
  ];
  if (bfsMode) {
    datasets.push({
      label: "Discovered",
      data: [],
      borderColor: "#6bcf7f",
      backgroundColor: "rgba(107,207,127,0.08)",
      tension: 0.1,
      fill: false,
      pointRadius: 0,
    });
  }
  datasets.push({
    label: "Processed",
    data: [],
    borderColor: "#5b9fd4",
    backgroundColor: "rgba(91,159,212,0.08)",
    tension: 0.1,
    fill: false,
    pointRadius: 0,
  });
  return datasets;
}

const chart = new Chart(ctx, {
  type: "line",
  data: {
    labels: [],
    datasets: buildChartDatasets(false),
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

function isBfsMode(health, stats) {
  if (health?.sitemap_only === false) return true;
  if (health?.sitemap_only === true) return false;
  return !(stats?.sitemap_urls > 0);
}

function chartQueueIndex() {
  return 0;
}

function chartDiscoveredIndex() {
  return chartBfsMode ? 1 : -1;
}

function chartProcessedIndex() {
  return chartBfsMode ? 2 : 1;
}

function configureChartMode(bfsMode) {
  if (bfsMode === chartBfsMode) return;
  chartBfsMode = bfsMode;
  chart.data.datasets = buildChartDatasets(bfsMode);
  chartRunId = null;
  chartSampleLen = 0;
}

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
  chart.data.datasets[chartQueueIndex()].data.push(sample.queue);
  if (chartBfsMode) {
    chart.data.datasets[chartDiscoveredIndex()].data.push(sample.discovered);
  }
  chart.data.datasets[chartProcessedIndex()].data.push(sample.processed);
  chart.update("none");
}

function loadSamples(samples) {
  chart.data.labels = samples.map(sampleLabel);
  chart.data.datasets[chartQueueIndex()].data = samples.map((s) => s.queue);
  if (chartBfsMode) {
    chart.data.datasets[chartDiscoveredIndex()].data = samples.map((s) => s.discovered);
  }
  chart.data.datasets[chartProcessedIndex()].data = samples.map((s) => s.processed);
  chartSampleLen = samples.length;
  chart.update("none");
}

function syncChart(live, bfsMode) {
  const samples = live.samples || [];
  configureChartMode(bfsMode);

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

function section(title, body) {
  return `<div class="stat-section"><div class="section-title">${title}</div><div class="section-body">${body}</div></div>`;
}

function formatBreakdown(formats) {
  const keys = Object.keys(formats).sort();
  if (!keys.length) return metric("formats", "none");
  return keys.map((fmt) =>
    metric(fmt.toUpperCase(), formats[fmt], fmt === "md" ? "accent" : "")
  ).join(sep());
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const FILE_ICON_BY_EXT = {
  md: "markdown",
  pdf: "file-pdf",
  doc: "file-text",
  docx: "file-text",
  xls: "table",
  xlsx: "table",
  ppt: "file-media",
  pptx: "file-media",
  csv: "table",
  json: "json",
  html: "code",
  htm: "code",
  css: "symbol-color",
  txt: "file-text",
  zip: "file-zip",
  png: "file-media",
  jpg: "file-media",
  jpeg: "file-media",
  gif: "file-media",
  svg: "file-media",
};

const FILE_ICON_BY_KIND = {
  page: "globe",
  pdf: "file-pdf",
  file: "file",
};

function fileExtension(label, url) {
  const source = (label || url || "").split("?")[0].split("#")[0];
  const match = source.match(/\.([a-z0-9]+)$/i);
  return match ? match[1].toLowerCase() : "";
}

function fileIconClass(label, kind, url = "") {
  const ext = fileExtension(label, url);
  return FILE_ICON_BY_EXT[ext] || FILE_ICON_BY_KIND[kind] || "file";
}

function fileIcon(label, kind, url = "") {
  const iconClass = fileIconClass(label, kind, url);
  return `<span class="codicon codicon-${iconClass} file-icon" aria-hidden="true"></span>`;
}

function itemLabel(label, url) {
  const text = escapeHtml(label || url);
  const href = url || "";
  if (!href.startsWith("http://") && !href.startsWith("https://")) {
    return text;
  }
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
}

function eventLabel(event) {
  return itemLabel(event.label || event.url, event.url);
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
  const sections = [];
  const bfsMode = isBfsMode(health, stats);

  if (health) {
    const formats = health.catalog_by_format || {};
    const mdCount = formats.md || 0;
    const binaryCount = health.catalog_passthrough_count || 0;

    sections.push(section("Catalog", [
      metric("documents", health.document_count, "accent"),
      metric("pages", mdCount),
      metric("binary files", binaryCount),
      metric("download URLs", health.catalog_with_file_url || 0, health.catalog_with_file_url ? "ok" : "warn"),
    ].join(sep())));

    sections.push(section("Formats on disk", formatBreakdown(formats)));

    sections.push(`<div class="stat-section badges-only"><div class="section-body">${[
      health.sitemap_only ? badge("sitemap crawl", "accent") : badge("link crawl (BFS)"),
      badge(health.passthrough_enabled ? "passthrough on" : "passthrough off", health.passthrough_enabled ? "ok" : ""),
      badge(health.follow_file_links === false ? "file links off" : "file links on", health.follow_file_links === false ? "" : "ok"),
      health.public_base_url ? badge("public URL", "ok") : badge("no public URL", "warn"),
    ].join("")}</div></div>`);
  }

  if (live?.run_id) {
    const processed = (stats.pages_fetched || 0) + (stats.pdfs_fetched || 0);
    const pct = live.max_pages ? Math.min(100, Math.round((processed / live.max_pages) * 100)) : 0;

    sections.push(section("This run", [
      metric("processed", `${processed} / ${live.max_pages} (${pct}%)`, "accent"),
      metric("queue", live.queue_pending, live.queue_pending ? "warn" : ""),
    ].join(sep())));

    if (bfsMode) {
      sections.push(section("Link discovery", [
        metric("links found", stats.discovered, "accent"),
      ].join(sep())));
    } else if ((stats.sitemap_urls || 0) > 0) {
      sections.push(section("Sitemap", [
        metric("in XML", stats.sitemap_urls),
        metric("queued", stats.sitemap_queued, stats.sitemap_queued ? "warn" : ""),
        metric("skipped (unchanged)", stats.sitemap_skipped),
      ].join(sep())));
    }

    sections.push(section("HTML pages", [
      metric("updated", stats.pages_updated, "ok"),
      metric("unchanged", stats.pages_unchanged),
      metric("failed", stats.pages_failed, stats.pages_failed ? "bad" : ""),
      metric("fetched", stats.pages_fetched),
    ].join(sep())));

    sections.push(section("Passthrough files", [
      metric("links queued", stats.files_discovered || 0, "accent"),
      metric("updated", stats.pdfs_updated, "ok"),
      metric("unchanged", stats.pdfs_unchanged),
      metric("failed", stats.pdfs_failed, stats.pdfs_failed ? "bad" : ""),
      metric("fetched", stats.pdfs_fetched),
    ].join(sep())));
  } else if (!health) {
    sections.push('<div class="stat-section"><div class="section-body muted">Waiting for data…</div></div>');
  }

  compactBar.innerHTML = sections.join("");
}

function render(data) {
  lastLiveData = data;
  const running = data.running;
  statePill.textContent = running ? "running" : "idle";
  statePill.className = "pill " + (running ? "running" : "idle");

  const live = data.live;
  const stats = live.stats || {};
  const bfsMode = isBfsMode(lastHealth, stats);

  runMeta.textContent = live.run_id
    ? `run #${live.run_id} · ${live.trigger || "—"} · ${live.seed_url || ""}`
    : "No crawl run yet";

  renderCompactBar();
  syncChart(live, bfsMode);

  eventsEl.innerHTML = live.events.length
    ? live.events.slice().reverse().map((e) => {
        const cls = `outcome-${e.outcome}`;
        return `<div class="event">${fileIcon(e.label, e.kind, e.url)}<span class="${cls}">[${e.kind}] ${e.outcome}</span> ${eventLabel(e)}</div>`;
      }).join("")
    : '<div class="event" style="color:#8b9cb3">Waiting for crawl events…</div>';

  const tail = live.queue_tail || [];
  queueTailEl.innerHTML = tail.length
    ? tail.slice().reverse().map((item) =>
        `<div class="event">${fileIcon(item.label, item.kind, item.url)}<span class="queue-meta">[${item.kind}] d${item.depth}</span> ${itemLabel(item.label, item.url)}</div>`
      ).join("")
    : '<div class="event" style="color:#8b9cb3">Queue empty or waiting for crawl…</div>';
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
