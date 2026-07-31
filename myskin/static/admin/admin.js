const TOKEN_KEY = "myskin_api_token";

const tokenInput = document.getElementById("token");
const statusEl = document.getElementById("status");
const sitesEl = document.getElementById("sites");
const createForm = document.getElementById("create-form");
const editForm = document.getElementById("edit-form");
const deleteSiteButton = document.getElementById("delete-site");
const emptyDetailEl = document.getElementById("empty-detail");
const detailContentEl = document.getElementById("detail-content");
const createPanelEl = document.getElementById("create-panel");
const detailNameEl = document.getElementById("detail-name");
const detailIdEl = document.getElementById("detail-id");
const statePill = document.getElementById("statePill");
const runMeta = document.getElementById("runMeta");
const compactBar = document.getElementById("compactBar");
const eventsEl = document.getElementById("events");
const queueTailEl = document.getElementById("queueTail");
const btnCrawl = document.getElementById("btn-crawl");
const btnSync = document.getElementById("btn-sync");
const btnToggle = document.getElementById("btn-toggle");

const summarySitesEl = document.getElementById("summary-sites");
const summaryEnabledEl = document.getElementById("summary-enabled");
const summaryRunningEl = document.getElementById("summary-running");
const summaryDocumentsEl = document.getElementById("summary-documents");

const oidcAuthEl = document.getElementById("oidc-auth");
const bearerAuthEl = document.getElementById("bearer-auth");
const userLabelEl = document.getElementById("user-label");
const loginBtn = document.getElementById("login-btn");
const logoutBtn = document.getElementById("logout-btn");

let selectedSiteId = null;
let selectedDetail = null;
let sitesCache = [];
let oidcEnabled = false;
let lastLiveData = null;
let chartBfsMode = false;
let activeTab = "live";

function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setStatus(message, kind = "ok") {
  statusEl.hidden = false;
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function redirectToLogin() {
  window.location.href = "/auth/login";
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const value = token();
  if (value) headers.Authorization = `Bearer ${value}`;

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && oidcEnabled && !value) {
    redirectToLogin();
    throw new Error("login_required");
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

function asArrayCsv(value) {
  if (Array.isArray(value)) return value.join(", ");
  return value || "";
}

function setFormValue(form, name, value) {
  const input = form.elements.namedItem(name);
  if (!input) return;
  if (input.type === "checkbox") {
    input.checked = Boolean(value);
    return;
  }
  input.value = value ?? "";
}

function getFormValue(form, name) {
  const input = form.elements.namedItem(name);
  if (!input) return "";
  if (input.type === "checkbox") return input.checked;
  return input.value.trim();
}

function normalizeNumber(value, { integer = false } = {}) {
  if (value === "") return null;
  const parsed = integer ? Number.parseInt(value, 10) : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function siteStatus(site) {
  if (site.crawl_running) return { label: "running", className: "running" };
  if (site.last_crawl_error) return { label: "error", className: "error" };
  if (!site.enabled) return { label: "disabled", className: "disabled" };
  return { label: "idle", className: "idle" };
}

function updateSummary(sites) {
  const enabled = sites.filter((site) => site.enabled).length;
  const running = sites.filter((site) => site.crawl_running).length;
  const documents = sites.reduce((sum, site) => sum + (site.document_count || 0), 0);
  summarySitesEl.textContent = String(sites.length);
  summaryEnabledEl.textContent = String(enabled);
  summaryRunningEl.textContent = String(running);
  summaryDocumentsEl.textContent = String(documents);
}

function updateUrl(siteId) {
  const url = new URL(window.location.href);
  if (siteId) url.searchParams.set("site_id", siteId);
  else url.searchParams.delete("site_id");
  window.history.replaceState({}, "", url);
}

function showCreatePanel() {
  selectedSiteId = null;
  selectedDetail = null;
  emptyDetailEl.hidden = true;
  detailContentEl.hidden = true;
  createPanelEl.hidden = false;
  updateUrl(null);
  renderCrawlerList();
}

function showEmptyDetail() {
  emptyDetailEl.hidden = false;
  detailContentEl.hidden = true;
  createPanelEl.hidden = true;
}

function showDetailContent() {
  emptyDetailEl.hidden = true;
  detailContentEl.hidden = false;
  createPanelEl.hidden = true;
}

function renderCrawlerList() {
  sitesEl.innerHTML = "";
  if (!sitesCache.length) {
    sitesEl.innerHTML = '<div class="empty-detail" style="padding:1rem"><p>No crawlers yet. Click + to add one.</p></div>';
    return;
  }

  for (const site of sitesCache) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "crawler-row";
    row.setAttribute("role", "listitem");
    if (site.site_id === selectedSiteId) row.classList.add("selected");

    const status = siteStatus(site);
    const flags = [
      site.enabled ? '<span class="badge on">enabled</span>' : '<span class="badge off">disabled</span>',
      site.scheduler_enabled ? '<span class="badge accent">sched</span>' : "",
      site.ragflow_enabled ? '<span class="badge on">ragflow</span>' : "",
      `<span class="badge">${site.document_count || 0} docs</span>`,
    ].filter(Boolean).join("");

    row.innerHTML = `
      <div class="crawler-row-top">
        <div>
          <h3>${escapeHtml(site.name)}</h3>
          <div class="site-id">${escapeHtml(site.site_id)}</div>
        </div>
        <span class="pill ${status.className}">${status.label}</span>
      </div>
      <div class="crawler-flags">${flags}</div>
    `;
    row.addEventListener("click", () => selectSite(site.site_id));
    sitesEl.appendChild(row);
  }
}

function fillEditForm(site) {
  setFormValue(editForm, "site_id", site.site_id);
  setFormValue(editForm, "site_id_display", site.site_id);
  setFormValue(editForm, "name", site.name);
  setFormValue(editForm, "public_base_url", site.public_base_url);
  setFormValue(editForm, "enabled", site.enabled);

  setFormValue(editForm, "crawler.seed_url", site.crawler?.seed_url);
  setFormValue(editForm, "crawler.sitemap_url", site.crawler?.sitemap_url);
  setFormValue(editForm, "crawler.local_sitemap", site.crawler?.local_sitemap);
  setFormValue(editForm, "crawler.local_sitemap_requeue", site.crawler?.local_sitemap_requeue);
  setFormValue(editForm, "crawler.max_depth", site.crawler?.max_depth);
  setFormValue(editForm, "crawler.max_pages", site.crawler?.max_pages);
  setFormValue(editForm, "crawler.request_delay", site.crawler?.request_delay);
  setFormValue(editForm, "crawler.user_agent", site.crawler?.user_agent);
  setFormValue(editForm, "crawler.respect_robots", site.crawler?.respect_robots);
  setFormValue(editForm, "crawler.refresh_known", site.crawler?.refresh_known);
  setFormValue(editForm, "crawler.resume_on_startup", site.crawler?.resume_on_startup);
  setFormValue(editForm, "crawler.sitemap_only", site.crawler?.sitemap_only);
  setFormValue(editForm, "crawler.follow_file_links", site.crawler?.follow_file_links);
  setFormValue(editForm, "crawler.html_to_markdown", site.crawler?.html_to_markdown);
  setFormValue(editForm, "crawler.progress", site.crawler?.progress);
  setFormValue(editForm, "crawler.passthrough.enabled", site.crawler?.passthrough?.enabled);
  setFormValue(editForm, "crawler.passthrough.extract_pdf_text", site.crawler?.passthrough?.extract_pdf_text);
  setFormValue(
    editForm,
    "crawler.passthrough.extensions",
    asArrayCsv(site.crawler?.passthrough?.extensions),
  );

  setFormValue(editForm, "scheduler.enabled", site.scheduler?.enabled);
  setFormValue(editForm, "scheduler.cron", site.scheduler?.cron);
  setFormValue(editForm, "scheduler.timezone", site.scheduler?.timezone);
  setFormValue(editForm, "scheduler.interval_hours", site.scheduler?.interval_hours);
  setFormValue(editForm, "scheduler.interval_minutes", site.scheduler?.interval_minutes);
  setFormValue(editForm, "scheduler.run_on_startup", site.scheduler?.run_on_startup);

  setFormValue(editForm, "ragflow.enabled", site.ragflow?.enabled);
  setFormValue(editForm, "ragflow.api_url", site.ragflow?.api_url);
  setFormValue(editForm, "ragflow.dataset_id", site.ragflow?.dataset_id);
  setFormValue(editForm, "ragflow.sync_on_crawl_complete", site.ragflow?.sync_on_crawl_complete);
  setFormValue(editForm, "ragflow.parse_on_upload", site.ragflow?.parse_on_upload);
  setFormValue(editForm, "ragflow.delete_missing", site.ragflow?.delete_missing);
}

function buildSiteUpdatePayload() {
  const extensionsRaw = getFormValue(editForm, "crawler.passthrough.extensions");
  return {
    name: getFormValue(editForm, "name"),
    public_base_url: getFormValue(editForm, "public_base_url"),
    enabled: getFormValue(editForm, "enabled"),
    crawler: {
      seed_url: getFormValue(editForm, "crawler.seed_url"),
      sitemap_url: getFormValue(editForm, "crawler.sitemap_url") || null,
      local_sitemap: getFormValue(editForm, "crawler.local_sitemap") || null,
      local_sitemap_requeue: getFormValue(editForm, "crawler.local_sitemap_requeue") || "always",
      max_depth: normalizeNumber(getFormValue(editForm, "crawler.max_depth"), { integer: true }),
      max_pages: normalizeNumber(getFormValue(editForm, "crawler.max_pages"), { integer: true }),
      request_delay: normalizeNumber(getFormValue(editForm, "crawler.request_delay")),
      user_agent: getFormValue(editForm, "crawler.user_agent"),
      respect_robots: getFormValue(editForm, "crawler.respect_robots"),
      refresh_known: getFormValue(editForm, "crawler.refresh_known"),
      resume_on_startup: getFormValue(editForm, "crawler.resume_on_startup"),
      sitemap_only: getFormValue(editForm, "crawler.sitemap_only"),
      follow_file_links: getFormValue(editForm, "crawler.follow_file_links"),
      html_to_markdown: getFormValue(editForm, "crawler.html_to_markdown"),
      progress: getFormValue(editForm, "crawler.progress") || "auto",
      passthrough: {
        enabled: getFormValue(editForm, "crawler.passthrough.enabled"),
        extract_pdf_text: getFormValue(editForm, "crawler.passthrough.extract_pdf_text"),
        extensions: extensionsRaw
          ? extensionsRaw.split(",").map((value) => value.trim()).filter(Boolean)
          : [],
      },
    },
    scheduler: {
      enabled: getFormValue(editForm, "scheduler.enabled"),
      cron: getFormValue(editForm, "scheduler.cron"),
      timezone: getFormValue(editForm, "scheduler.timezone") || "UTC",
      interval_hours: normalizeNumber(getFormValue(editForm, "scheduler.interval_hours")),
      interval_minutes: normalizeNumber(getFormValue(editForm, "scheduler.interval_minutes")),
      run_on_startup: getFormValue(editForm, "scheduler.run_on_startup"),
    },
    ragflow: {
      enabled: getFormValue(editForm, "ragflow.enabled"),
      api_url: getFormValue(editForm, "ragflow.api_url") || null,
      dataset_id: getFormValue(editForm, "ragflow.dataset_id"),
      sync_on_crawl_complete: getFormValue(editForm, "ragflow.sync_on_crawl_complete"),
      parse_on_upload: getFormValue(editForm, "ragflow.parse_on_upload"),
      delete_missing: getFormValue(editForm, "ragflow.delete_missing"),
    },
  };
}

function updateDetailHeader(summary, liveData) {
  const site = summary || sitesCache.find((s) => s.site_id === selectedSiteId);
  if (!site) return;

  detailNameEl.textContent = selectedDetail?.name || site.name;
  detailIdEl.textContent = site.site_id;

  const running = liveData?.running ?? site.crawl_running;
  if (running) {
    statePill.textContent = "running";
    statePill.className = "pill running";
  } else if (site.last_crawl_error || liveData?.last_error) {
    statePill.textContent = "error";
    statePill.className = "pill error";
  } else if (!site.enabled) {
    statePill.textContent = "disabled";
    statePill.className = "pill disabled";
  } else {
    statePill.textContent = "idle";
    statePill.className = "pill idle";
  }

  const live = liveData?.live;
  if (live?.run_id) {
    runMeta.textContent = `run #${live.run_id} · ${live.trigger || "—"} · ${live.seed_url || ""}`;
  } else if (liveData?.last_finished_at) {
    runMeta.textContent = `Last finished ${formatDate(liveData.last_finished_at)} · ${liveData.schedule || site.schedule}`;
  } else {
    runMeta.textContent = `Schedule: ${liveData?.schedule || site.schedule} · Next: ${formatDate(liveData?.next_run_at || site.next_run_at)}`;
  }

  btnToggle.textContent = site.enabled ? "Disable" : "Enable";
  btnToggle.dataset.enabled = String(site.enabled);
  btnCrawl.disabled = running;
}

/* —— Live stats / events / chart (from former crawl dashboard) —— */

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
  const keys = Object.keys(formats || {}).sort();
  if (!keys.length) return metric("formats", "none");
  return keys.map((fmt) =>
    metric(fmt.toUpperCase(), formats[fmt], fmt === "md" ? "accent" : "")
  ).join(sep());
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

function isBfsMode(detail, stats) {
  if (detail?.crawler?.sitemap_only === false) return true;
  if (detail?.crawler?.sitemap_only === true) return false;
  return !(stats?.sitemap_urls > 0);
}

function renderCompactBar(data) {
  const live = data?.live;
  const stats = live?.stats || {};
  const sections = [];
  const bfsMode = isBfsMode(selectedDetail, stats);
  const site = sitesCache.find((s) => s.site_id === selectedSiteId);

  if (site || selectedDetail) {
    const crawler = selectedDetail?.crawler || {};
    const passthrough = crawler.passthrough || {};
    sections.push(section("Catalog", [
      metric("documents", site?.document_count ?? 0, "accent"),
      metric("schedule", data?.schedule || site?.schedule || "—"),
    ].join(sep())));

    sections.push(`<div class="stat-section badges-only"><div class="section-body">${[
      crawler.sitemap_only ? badge("sitemap crawl", "accent") : badge("link crawl (BFS)"),
      badge(passthrough.enabled !== false ? "passthrough on" : "passthrough off", passthrough.enabled !== false ? "ok" : ""),
      badge(crawler.follow_file_links === false ? "file links off" : "file links on", crawler.follow_file_links === false ? "" : "ok"),
      (selectedDetail?.public_base_url || site?.public_base_url) ? badge("public URL", "ok") : badge("no public URL", "warn"),
      selectedDetail?.ragflow?.enabled || site?.ragflow_enabled ? badge("ragflow", "ok") : badge("ragflow off"),
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
  } else if (data?.last_error) {
    sections.push(`<div class="stat-section"><div class="section-body" style="color:var(--danger)">${escapeHtml(data.last_error)}</div></div>`);
  } else if (!sections.length) {
    sections.push('<div class="stat-section"><div class="section-body muted">Waiting for data…</div></div>');
  }

  compactBar.innerHTML = sections.join("");
}

function renderLive(data) {
  lastLiveData = data;
  updateDetailHeader(
    sitesCache.find((s) => s.site_id === selectedSiteId),
    data,
  );
  renderCompactBar(data);

  const live = data.live || {};
  const stats = live.stats || {};
  const bfsMode = isBfsMode(selectedDetail, stats);
  syncChart(live, bfsMode);

  const events = live.events || [];
  eventsEl.innerHTML = events.length
    ? events.slice().reverse().map((e) => {
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

const chartCtx = document.getElementById("chart");
const chart = new Chart(chartCtx, {
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

async function selectSite(siteId) {
  selectedSiteId = siteId;
  updateUrl(siteId);
  showDetailContent();
  renderCrawlerList();
  resetChart();
  chartRunId = null;

  try {
    selectedDetail = await api(`/api/sites/${siteId}`);
    fillEditForm(selectedDetail);
    updateDetailHeader(sitesCache.find((s) => s.site_id === siteId), null);
    await refreshLive();
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
}

async function loadSites() {
  const data = await api("/api/sites");
  sitesCache = data.items;
  updateSummary(sitesCache);
  renderCrawlerList();

  if (selectedSiteId) {
    const selected = sitesCache.find((site) => site.site_id === selectedSiteId);
    if (!selected) {
      selectedSiteId = null;
      selectedDetail = null;
      showEmptyDetail();
      updateUrl(null);
    } else {
      updateDetailHeader(selected, lastLiveData);
    }
  }
}

async function refreshLive() {
  if (!selectedSiteId || detailContentEl.hidden) return;
  try {
    const data = await api(`/api/sites/${selectedSiteId}/crawl/live`);
    renderLive(data);
  } catch (error) {
    if (error.message !== "login_required") {
      /* keep last live view; list poll will surface auth issues */
    }
  }
}

function setTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === tabName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    const match = panel.id === `panel-${tabName}`;
    panel.hidden = !match;
    panel.classList.toggle("active", match);
  });
  if (tabName === "charts") {
    chart.resize();
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => setTab(tab.dataset.tab));
});

document.getElementById("show-create").addEventListener("click", () => showCreatePanel());
document.getElementById("cancel-create").addEventListener("click", () => {
  createPanelEl.hidden = true;
  if (selectedSiteId) {
    showDetailContent();
    updateUrl(selectedSiteId);
  } else {
    showEmptyDetail();
    updateUrl(null);
  }
  renderCrawlerList();
});

document.getElementById("detail-actions").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button || !selectedSiteId) return;
  const action = button.dataset.action;
  try {
    if (action === "crawl") {
      setStatus(`Starting crawl for ${selectedSiteId}…`);
      await api(`/api/sites/${selectedSiteId}/crawl/start`, { method: "POST" });
      setStatus(`Crawl started for ${selectedSiteId}`);
      await refreshLive();
    } else if (action === "sync") {
      setStatus(`Syncing ${selectedSiteId} to RAGFlow…`);
      const result = await api(`/api/sites/${selectedSiteId}/ragflow/sync`, { method: "POST" });
      setStatus(`RAGFlow sync for ${selectedSiteId}: uploaded=${result.uploaded}, updated=${result.updated}, skipped=${result.skipped}`);
    } else if (action === "toggle") {
      const enabled = button.dataset.enabled !== "true";
      await api(`/api/sites/${selectedSiteId}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setStatus(`${selectedSiteId} ${enabled ? "enabled" : "disabled"}`);
      selectedDetail = await api(`/api/sites/${selectedSiteId}`);
      fillEditForm(selectedDetail);
    }
    await loadSites();
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

editForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const siteId = getFormValue(editForm, "site_id");
  if (!siteId) return;
  const body = buildSiteUpdatePayload();
  try {
    await api(`/api/sites/${siteId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    setStatus(`Saved configuration for ${siteId}`);
    selectedDetail = await api(`/api/sites/${siteId}`);
    fillEditForm(selectedDetail);
    await loadSites();
    updateDetailHeader(sitesCache.find((s) => s.site_id === siteId), lastLiveData);
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

deleteSiteButton.addEventListener("click", async () => {
  const siteId = getFormValue(editForm, "site_id");
  if (!siteId) return;
  if (!window.confirm(`Delete site ${siteId}?`)) return;
  try {
    await api(`/api/sites/${siteId}`, { method: "DELETE" });
    setStatus(`Deleted site ${siteId}`);
    selectedSiteId = null;
    selectedDetail = null;
    lastLiveData = null;
    showEmptyDetail();
    updateUrl(null);
    await loadSites();
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(createForm);
  const body = {
    site_id: form.get("site_id"),
    name: form.get("name"),
    enabled: true,
    public_base_url: form.get("public_base_url") || "",
    crawler: {
      seed_url: form.get("seed_url"),
      sitemap_only: true,
      html_to_markdown: true,
      follow_file_links: true,
      progress: "auto",
      passthrough: { enabled: true, extract_pdf_text: false },
    },
    scheduler: {
      enabled: form.get("scheduler_enabled") === "on",
      cron: form.get("cron") || "0 2 * * 0",
      timezone: form.get("timezone") || "UTC",
    },
    ragflow: {
      enabled: Boolean(form.get("dataset_id")),
      api_url: form.get("api_url") || "",
      dataset_id: form.get("dataset_id") || "",
      sync_on_crawl_complete: true,
      parse_on_upload: true,
      delete_missing: true,
    },
  };
  try {
    await api("/api/sites", { method: "POST", body: JSON.stringify(body) });
    createForm.reset();
    setStatus(`Created site ${body.site_id}`);
    await loadSites();
    await selectSite(body.site_id);
    setTab("config");
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

document.getElementById("save-token").addEventListener("click", () => {
  localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
  setStatus("Token saved");
});

document.getElementById("refresh").addEventListener("click", async () => {
  try {
    await loadSites();
    if (selectedSiteId) await refreshLive();
    setStatus("Refreshed");
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

loginBtn.addEventListener("click", () => redirectToLogin());
logoutBtn.addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  window.location.href = "/";
});

async function initAuth() {
  tokenInput.value = token();
  let config = { enabled: false, bearer_enabled: true };
  try {
    const response = await fetch("/auth/config", { credentials: "same-origin" });
    if (response.ok) config = await response.json();
  } catch {
    /* keep defaults */
  }

  oidcEnabled = Boolean(config.enabled);
  if (oidcEnabled) {
    oidcAuthEl.hidden = false;
    if (!config.bearer_enabled) bearerAuthEl.hidden = true;

    try {
      const meRes = await fetch("/auth/me", { credentials: "same-origin" });
      if (meRes.status === 401) {
        loginBtn.hidden = false;
        redirectToLogin();
        return false;
      }
      if (meRes.ok) {
        const me = await meRes.json();
        const user = me.user || {};
        userLabelEl.textContent =
          user.email || user.name || user.preferred_username || "Signed in";
        logoutBtn.hidden = false;
      }
    } catch {
      loginBtn.hidden = false;
    }
  }
  return true;
}

(async () => {
  const ready = await initAuth();
  if (!ready) return;

  try {
    await loadSites();
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }

  const params = new URLSearchParams(window.location.search);
  const fromQuery = params.get("site_id");
  if (fromQuery && sitesCache.some((s) => s.site_id === fromQuery)) {
    await selectSite(fromQuery);
  } else if (sitesCache.length === 1) {
    await selectSite(sitesCache[0].site_id);
  } else {
    showEmptyDetail();
  }

  setInterval(() => {
    loadSites().catch(() => {});
  }, 10000);
  setInterval(() => {
    refreshLive().catch(() => {});
  }, 1500);
})();
