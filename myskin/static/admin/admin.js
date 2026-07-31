const TOKEN_KEY = "myskin_api_token";

const tokenInput = document.getElementById("token");
const statusEl = document.getElementById("status");
const sitesEl = document.getElementById("sites");
const createForm = document.getElementById("create-form");
const editForm = document.getElementById("edit-form");
const deleteSiteButton = document.getElementById("delete-site");
const editorTitle = document.getElementById("editor-title");

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
let sitesCache = [];
let oidcEnabled = false;

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

function updateSummary(sites) {
  const enabled = sites.filter((site) => site.enabled).length;
  const running = sites.filter((site) => site.crawl_running).length;
  const documents = sites.reduce((sum, site) => sum + (site.document_count || 0), 0);
  summarySitesEl.textContent = String(sites.length);
  summaryEnabledEl.textContent = String(enabled);
  summaryRunningEl.textContent = String(running);
  summaryDocumentsEl.textContent = String(documents);
}

function renderSite(site) {
  const card = document.createElement("article");
  card.className = "site-card";
  if (site.site_id === selectedSiteId) {
    card.classList.add("selected");
  }
  const badges = [
    site.enabled ? '<span class="badge on">enabled</span>' : '<span class="badge off">disabled</span>',
    site.crawl_running ? '<span class="badge running">crawling</span>' : "",
    site.ragflow_enabled ? '<span class="badge on">ragflow</span>' : "",
  ].join(" ");

  card.innerHTML = `
    <header>
      <div>
        <h3>${site.name}</h3>
        <div class="muted">${site.site_id}</div>
      </div>
      <div>${badges}</div>
    </header>
    <div class="site-meta">
      <div><strong>Seed</strong><br><a href="${escapeHtml(site.seed_url || "#")}" target="_blank" rel="noreferrer">${escapeHtml(site.seed_url || "—")}</a></div>
      <div><strong>Public URL</strong><br>${site.public_base_url ? `<a href="${escapeHtml(site.public_base_url)}" target="_blank" rel="noreferrer">${escapeHtml(site.public_base_url)}</a>` : "—"}</div>
      <div><strong>Documents</strong><br>${site.document_count}</div>
      <div><strong>Schedule</strong><br>${site.schedule}</div>
      <div><strong>Dataset</strong><br>${site.ragflow_dataset_id || "—"}</div>
      <div><strong>Next run</strong><br>${formatDate(site.next_run_at)}</div>
      <div><strong>Last crawl</strong><br>${formatDate(site.last_crawl_finished_at)}</div>
    </div>
    ${site.last_crawl_error ? `<div class="site-error"><strong>Last error:</strong> ${escapeHtml(site.last_crawl_error)}</div>` : ""}
    <div class="site-actions">
      <button type="button" class="secondary" data-action="edit" data-site="${site.site_id}">Edit config</button>
      <button type="button" data-action="crawl" data-site="${site.site_id}">Run crawl</button>
      <button type="button" class="secondary" data-action="sync" data-site="${site.site_id}">RAGFlow sync</button>
      <button type="button" class="secondary" data-action="toggle" data-site="${site.site_id}" data-enabled="${site.enabled}">
        ${site.enabled ? "Disable" : "Enable"}
      </button>
      <a class="link-button" href="/crawl?site_id=${encodeURIComponent(site.site_id)}">Live dashboard</a>
      ${site.public_base_url ? `<a class="link-button" href="${escapeHtml(site.public_base_url)}" target="_blank" rel="noreferrer">Open site URL</a>` : ""}
    </div>
  `;
  return card;
}

function fillEditForm(site) {
  selectedSiteId = site.site_id;
  editorTitle.textContent = `Configuration: ${site.name}`;
  editForm.hidden = false;

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

async function loadSites() {
  const data = await api("/api/sites");
  sitesCache = data.items;
  updateSummary(sitesCache);
  sitesEl.innerHTML = "";
  for (const site of sitesCache) {
    sitesEl.appendChild(renderSite(site));
  }
  if (selectedSiteId) {
    const selected = sitesCache.find((site) => site.site_id === selectedSiteId);
    if (!selected) {
      selectedSiteId = null;
      editForm.hidden = true;
      editorTitle.textContent = "Configuration";
    }
  }
}

sitesEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const siteId = button.dataset.site;
  const action = button.dataset.action;
  try {
    if (action === "edit") {
      const site = await api(`/api/sites/${siteId}`);
      fillEditForm(site);
      await loadSites();
    } else if (action === "crawl") {
      setStatus(`Starting crawl for ${siteId}…`);
      await api(`/api/sites/${siteId}/crawl/start`, { method: "POST" });
      setStatus(`Crawl started for ${siteId}`);
    } else if (action === "sync") {
      setStatus(`Syncing ${siteId} to RAGFlow…`);
      const result = await api(`/api/sites/${siteId}/ragflow/sync`, { method: "POST" });
      setStatus(`RAGFlow sync for ${siteId}: uploaded=${result.uploaded}, updated=${result.updated}, skipped=${result.skipped}`);
    } else if (action === "toggle") {
      const enabled = button.dataset.enabled !== "true";
      const current = await api(`/api/sites/${siteId}`);
      await api(`/api/sites/${siteId}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      setStatus(`${siteId} ${enabled ? "enabled" : "disabled"}`);
      await loadSites();
    }
    if (action !== "toggle" && action !== "edit") await loadSites();
  } catch (error) {
    setStatus(error.message, "error");
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
    const site = await api(`/api/sites/${siteId}`);
    fillEditForm(site);
    await loadSites();
  } catch (error) {
    setStatus(error.message, "error");
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
    editForm.hidden = true;
    editorTitle.textContent = "Configuration";
    await loadSites();
  } catch (error) {
    setStatus(error.message, "error");
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
    const site = await api(`/api/sites/${body.site_id}`);
    fillEditForm(site);
  } catch (error) {
    setStatus(error.message, "error");
  }
});

document.getElementById("save-token").addEventListener("click", () => {
  localStorage.setItem(TOKEN_KEY, tokenInput.value.trim());
  setStatus("Token saved");
});

document.getElementById("refresh").addEventListener("click", async () => {
  try {
    await loadSites();
    setStatus("Refreshed");
  } catch (error) {
    if (error.message !== "login_required") setStatus(error.message, "error");
  }
});

loginBtn.addEventListener("click", () => redirectToLogin());
logoutBtn.addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  window.location.href = "/admin";
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
  loadSites().catch((error) => {
    if (error.message !== "login_required") setStatus(error.message, "error");
  });
  setInterval(() => {
    loadSites().catch(() => {});
  }, 10000);
})();
