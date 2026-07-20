const TOKEN_KEY = "myskin_api_token";

const tokenInput = document.getElementById("token");
const statusEl = document.getElementById("status");
const sitesEl = document.getElementById("sites");
const createForm = document.getElementById("create-form");

function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setStatus(message, kind = "ok") {
  statusEl.hidden = false;
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const value = token();
  if (value) headers.Authorization = `Bearer ${value}`;

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function renderSite(site) {
  const card = document.createElement("article");
  card.className = "site-card";
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
      <div><strong>Seed</strong><br>${site.seed_url || "—"}</div>
      <div><strong>Documents</strong><br>${site.document_count}</div>
      <div><strong>Schedule</strong><br>${site.schedule}</div>
      <div><strong>Dataset</strong><br>${site.ragflow_dataset_id || "—"}</div>
      <div><strong>Last crawl</strong><br>${site.last_crawl_finished_at || "—"}</div>
    </div>
    <div class="site-actions">
      <button type="button" data-action="crawl" data-site="${site.site_id}">Run crawl</button>
      <button type="button" class="secondary" data-action="sync" data-site="${site.site_id}">RAGFlow sync</button>
      <button type="button" class="secondary" data-action="toggle" data-site="${site.site_id}" data-enabled="${site.enabled}">
        ${site.enabled ? "Disable" : "Enable"}
      </button>
      <a class="link" href="/crawl?site_id=${encodeURIComponent(site.site_id)}">Live dashboard</a>
    </div>
  `;
  return card;
}

async function loadSites() {
  const data = await api("/api/sites");
  sitesEl.innerHTML = "";
  for (const site of data.items) {
    sitesEl.appendChild(renderSite(site));
  }
}

sitesEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const siteId = button.dataset.site;
  const action = button.dataset.action;
  try {
    if (action === "crawl") {
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
    if (action !== "toggle") await loadSites();
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
      passthrough: { enabled: true, extract_pdf_text: false },
    },
    scheduler: { enabled: true, cron: "0 2 * * 0", timezone: "UTC" },
    ragflow: {
      enabled: Boolean(form.get("dataset_id")),
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
    setStatus(error.message, "error");
  }
});

tokenInput.value = token();
loadSites().catch((error) => setStatus(error.message, "error"));
setInterval(() => {
  loadSites().catch(() => {});
}, 10000);
