# myskin — Operations & Architecture Runbook

> Maintainer reference for **why** this project exists, **how** the pieces fit together, and **what** has already been researched, built, and decided.
>
> Česká verze: [RUNBOOK.cs.md](RUNBOOK.cs.md)
>
> Last updated: 2026-07-07

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [The problem we are solving](#2-the-problem-we-are-solving)
3. [Architecture](#3-architecture)
4. [Why RAGFlow](#4-why-ragflow)
5. [Why myskin exists (instead of only RAGFlow)](#5-why-myskin-exists-instead-of-only-ragflow)
6. [What is built today](#6-what-is-built-today)
7. [Crawler, scheduler & sitemap](#7-crawler-scheduler--sitemap)
8. [Crawl dashboard & live API](#8-crawl-dashboard--live-api)
9. [RAGFlow deployment reference](#9-ragflow-deployment-reference)
10. [RAGFlow REST API connector spec](#10-ragflow-rest-api-connector-spec)
11. [myskin API contract](#11-myskin-api-contract)
12. [Web scraping strategy](#12-web-scraping-strategy)
13. [Target site: edu.gov.cz](#13-target-site-edugovcz)
14. [Tool evaluation history](#14-tool-evaluation-history)
15. [Legal & compliance](#15-legal--compliance)
16. [Operations procedures](#16-operations-procedures)
17. [Troubleshooting](#17-troubleshooting)
18. [Decision log](#18-decision-log)
19. [Source material (archived convos)](#19-source-material-archived-convos)
20. [Implementation session notes (2026-07)](#20-implementation-session-notes-2026-07)

---

## 1. Executive summary

**myskin** is a self-hosted **document bridge** between:

1. A **crawler** (implemented) that collects web content and PDFs, preprocesses them, and writes files into `data/`
2. A **FastAPI service** (implemented) that exposes those files as a JSON catalog over HTTP
3. **RAGFlow** (deployed separately), which **pulls** from that API on a schedule using its built-in **`rest_api`** data source connector, then chunks, embeds, and indexes into a knowledge base for chat/RAG

The name is a pun ([README](../README.md)): *crawling* in your skin (Chester Bennington) + *bindis embedded* in the skin (Clarence Claymore) → crawling + embedding.

**End goal:** A knowledge chatbot over Czech Ministry of Education content (`https://edu.gov.cz/`) and linked PDFs, self-hosted, free, commercially usable, with automatic periodic updates.

---

## 2. The problem we are solving

### Business need

- Primary target: **[edu.gov.cz](https://edu.gov.cz/)** — Czech Ministry of Education portal (legislation, methodology, Infoservis bulletins, PDF attachments).
- No public API exists to fetch documents programmatically.
- Scraping/crawling is permitted under `robots.txt` (verified in research convo).
- Intended use: **commercial knowledge chatbot** built on top of ingested data — **not** reselling RAGFlow itself.

### Technical need

We need a system that:

| Requirement | Notes |
|-------------|-------|
| Crawls & scrapes web pages | Including nested links |
| Downloads linked PDFs | edu.gov.cz is PDF-heavy |
| Preprocesses to ingestible text | Markdown preferred |
| Updates periodically | Weekly cron is reasonable for gov content |
| Feeds a RAG/knowledge base | Chunking + embedding + retrieval |
| Self-hosted & free | No SaaS lock-in |
| Commercial use OK | Apache 2.0 stack |

### What we explicitly rejected or deferred

| Approach | Why not (for now) |
|----------|-------------------|
| RAGFlow built-in web crawler UI | Not available in our RAGFlow v0.26.2 build — only file upload / empty file in dataset UI |
| RAGFlow Agent "Crawler" block | Also not present in our UI version |
| Push files via RAGFlow upload API | Works, but we wanted **pull-based** sync like Google Drive connectors |
| Dify + Firecrawl | Explored for another client; robots.txt bypass pain; different product |
| Chroma remote server | Explored for offloading vector retrieval; **not** our ingestion path — RAGFlow owns vectors |
| Vectorize.io / Cloudflare AutoRAG | Not self-hosted / not free |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INGESTION PIPELINE (implemented)                │
│                                                                         │
│  edu.gov.cz sitemap ──► CrawlEngine (httpx + BS4 + pypdf)              │
│         │                    │                                          │
│         │                    ▼                                          │
│         │           preprocess (HTML→MD, PDF→text/MD)                   │
│         │                    │                                          │
│         │                    ▼                                          │
│         └──────────► write files to  data/                              │
│                      ( .md + YAML frontmatter )                         │
│                      state in .myskin/crawl.db                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │  files on disk
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         MYSKIN (this repo) — IMPLEMENTED                 │
│                                                                         │
│  FastAPI  GET /api/documents?offset=&limit=                             │
│           GET /crawl  — live crawl dashboard                            │
│           scans data/ on each request → JSON { items, total }           │
│           Bearer auth, stable IDs, updated_at for incremental sync      │
│  APScheduler — weekly/interval crawls inside same process               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │  HTTP poll (must be public URL;
                                    │  RAGFlow blocks localhost/private IP)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         RAGFlow (separate deployment)                   │
│                                                                         │
│  rest_api connector  →  map JSON fields → Document blobs (.txt)         │
│  DeepDoc / chunking  →  Ollama embeddings  →  Elasticsearch/Infinity    │
│  Chat / API          →  knowledge base queries                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data flow in one sentence

**Crawl → write `data/` → myskin serves JSON → RAGFlow polls → embeds → chat.**

### Separation of concerns (intentional)

| Layer | Responsibility |
|-------|----------------|
| **Crawler** | Chaos: HTTP, PDFs, rate limits, site structure, retries |
| **myskin** | Thin, stable **catalog API** matching RAGFlow's `rest_api` schema |
| **RAGFlow** | Heavy lifting: parsing, chunking, embedding, vector store, chat UI |

This matches the insight from our research: don't force-feed RAGFlow via upload API; let it **reach for** documents like it does for Google Drive — via the **generic REST API connector** (RAGFlow v0.26+).

---

## 4. Why RAGFlow

From [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md):

- **Self-hosted**, Docker Compose, full UI + API
- **DeepDoc** — strong PDF/layout parsing (tables, multi-column) vs naive text extractors
- **Apache License 2.0** — commercial use allowed; no copyleft on our chatbot code
- Native data source connector system (30+ providers) — see [RAGFlow Data Source Connectors](https://deepwiki.com/infiniflow/ragflow/6.6-data-source-connectors)
- Ollama integration for free local embeddings (`bge-m3`, etc.) — Czech/multilingual

### RAGFlow version in use

Server: `jbi-sv-01`, image `infiniflow/ragflow:v0.26.2`

---

## 5. Why myskin exists (instead of only RAGFlow)

### The UI gap

On our RAGFlow build, dataset ingestion only offered **Upload file** and **Create empty file**. No web crawl button, no crawler agent block. Options discussed:

1. ~~RAGFlow Agent ingestion pipeline with Crawler component~~ — not in UI
2. ~~Push via `POST /api/v1/document/upload`~~ — works but push model
3. **Custom REST API data source** — ✅ RAGFlow v0.26 added `rest_api` connector with UI form
4. ~~RSS feed hack~~ — zero-code alternative; less control over PDF handling

We chose **#3**: build **myskin** as the REST endpoint RAGFlow polls.

### Why not modify RAGFlow source?

Possible (write a native connector driver in `common/data_source/`), but:

- Higher maintenance (fork, rebuild Docker)
- Generic `rest_api` connector already exists upstream ([PR #13545](https://github.com/infiniflow/ragflow/pull/13545))
- myskin keeps scraping logic **out** of RAGFlow entirely

---

## 6. What is built today

### Repository layout

```
myskin/
├── config.yaml             # main config (safe to commit)
├── config.docker.yaml      # Docker path overrides
├── config.local.yaml.example
├── myskin/
│   ├── main.py             # FastAPI + lifespan (scheduler, recovery)
│   ├── scheduler.py        # APScheduler internal cron/interval
│   ├── crawl_runner.py     # thread-safe crawl execution + status
│   ├── crawl_recovery.py   # resume interrupted runs on startup
│   ├── dashboard.py        # HTML crawl dashboard (/crawl)
│   ├── settings_loader.py  # yayaya config loader
│   ├── crawler/
│   │   ├── engine.py       # crawl loop, sitemap queue, frontier
│   │   ├── sitemap.py      # sitemap_index.xml parser + lastmod
│   │   ├── state.py        # SQLite resource + run tracking
│   │   ├── live.py         # in-memory live stats for dashboard
│   │   ├── progress.py     # terminal progress (tty/log/off)
│   │   ├── extract.py      # HTML→MD, PDF text
│   │   └── fetch.py        # httpx + robots.txt
│   └── routes.py           # API + /crawl + /api/crawl/*
├── Dockerfile
├── docker-compose.yml
├── data/                   # document store (Docker volume myskin-data)
├── .myskin/                # crawl.db (Docker volume myskin-state)
└── docs/RUNBOOK.md
```

Single **Docker Compose** service runs API + crawler + scheduler together.

### Configuration model

| Layer | File | Contents |
|-------|------|----------|
| **Secrets** | `.env` | `MYSKIN_API_TOKEN` only |
| **Main config** | `config.yaml` | API, crawler, scheduler settings |
| **Docker overlay** | `config.docker.yaml` | `/app/data`, `/app/.myskin/crawl.db` |
| **Local overrides** | `config.local.yaml` | Machine-specific (gitignored) |

Loaded via [yayaya](https://pypi.org/project/yayaya/) (`MYSKIN_CONFIG_FILES=config.yaml,config.docker.yaml` in Docker). See [§7](#7-crawler-scheduler--sitemap) for all crawler keys.

### myskin behavior

- Scans `data_dir` on every `/api/documents` request — always fresh
- Internal **APScheduler** triggers crawls (cron or interval, config-driven)
- Manual trigger: `POST /api/crawl/run` (blocking) or `POST /api/crawl/start` (background)
- CLI: `python -m myskin.crawl`
- Live dashboard: `GET /crawl` (Bearer token in browser)
- Volumes persist `data/` and `.myskin/crawl.db` across container restarts

**Important:** Docker bind-mounts `./data` on the host are **not** used by default — data lives in the named volume `myskin_myskin-data` → `/app/data`. Use `docker volume inspect` or `docker compose exec` to inspect files.

### Sample data

| File | Purpose |
|------|---------|
| `data/specs/embedded-bindi-spec.md` | Example with full frontmatter |
| `data/notes/crawling.md` | Example minimal doc |
| `data/crawl/edu-gov-cz/` | Crawled pages + PDFs (after first run; host slug uses hyphens) |

### Not implemented yet

- JavaScript-rendered pages (Playwright / Crawl4AI)
- Raw PDF binary retention in `data/` (only extracted text `.md`)

---

## 7. Crawler, scheduler & sitemap

**Status: implemented** — runs inside the main service process (Docker or `uvicorn`).

### Deploy

```bash
cp .env.example .env          # set MYSKIN_API_TOKEN
docker compose up -d --build
docker compose logs -f myskin
```

### Scheduler (`config.yaml` → `scheduler.*`)

| Key | Default | Purpose |
|-----|---------|---------|
| `enabled` | `true` | `false` = manual/API crawl only |
| `cron` | `0 2 * * 0` | 5-field cron (Sunday 02:00 UTC) |
| `interval_hours` / `interval_minutes` | — | Fixed interval (overrides cron when set) |
| `run_on_startup` | `false` | Crawl once when container boots |
| `timezone` | `UTC` | Cron timezone (`Europe/Prague`, …) |

### Crawler (`config.yaml` → `crawler.*`)

| Key | Default | Purpose |
|-----|---------|---------|
| `seed_url` | `https://edu.gov.cz/` | Scope anchor (host must match) |
| `max_depth` | `3` | Link-following depth (ignored when `sitemap_only: true`) |
| `max_pages` | `1000` | Max **fetched** resources per run (not lifetime total) |
| `request_delay` | `2.5` | Seconds between HTTP requests |
| `user_agent` | `MyskinCrawler/1.0 …` | Sent on every request |
| `respect_robots` | `true` | Honor `robots.txt` |
| `state_db` | `./.myskin/crawl.db` | SQLite crawl state |
| `refresh_known` | `true` | Re-queue all known URLs each run (**link-crawl mode only**) |
| `resume_on_startup` | `true` | Auto-resume after crash (see recovery below) |
| `progress` | `auto` | Terminal UI: `auto` \| `tty` \| `log` \| `off` |
| `sitemap_url` | — | Sitemap index or urlset URL (edu.gov.cz: [sitemap_index.xml](https://edu.gov.cz/sitemap_index.xml)) |
| `sitemap_only` | `true` | Only crawl sitemap URLs; do not follow `<a>` links |

**edu.gov.cz production config** (in repo `config.yaml`):

```yaml
crawler:
  sitemap_url: https://edu.gov.cz/sitemap_index.xml
  sitemap_only: true
  max_pages: 100000
  request_delay: 1.5
```

### Sitemap-driven discovery

When `sitemap_url` is set, the crawler:

1. Fetches the sitemap index and **all nested child sitemaps** (Yoast SEO emits ~30 files: `page-sitemap.xml`, `post-sitemap.xml`, `dlp_document-sitemap.xml`, …).
2. Collects every `<loc>` with optional `<lastmod>`.
3. **Queues a URL only if:**
   - never crawled before, **or**
   - `<lastmod>` is **newer** than `last_changed_at` in `crawl.db`
4. Skips unchanged URLs entirely — no HTTP fetch, no hash check.

| Run type | Expected behavior |
|----------|-------------------|
| **First run** | Long — every sitemap URL is new |
| **Incremental** | Fast — only changed pages queued |
| **Nothing changed** | ~30 sitemap fetches + done (seconds of overhead, zero page downloads) |

Log line example:

```
Sitemap https://edu.gov.cz/sitemap_index.xml: 12000 URLs, 42 queued, 11958 skipped (unchanged)
```

**Fallback:** if the sitemap fetch returns zero URLs, the engine falls back to link crawl from `seed_url` + `refresh_known`.

**Disable sitemap:** remove `sitemap_url` or set to `null` — reverts to BFS link discovery + `refresh_known`.

### How one crawl run works (no separate “scrape” phase)

There is **no two-phase** crawl-then-scrape pipeline. For each queued URL the engine does everything in one pass:

1. HTTP fetch (`Fetcher` + rate limit + optional `robots.txt`)
2. Extract (HTML → markdown via BeautifulSoup + html2text, or PDF → text via pypdf)
3. Hash compare against `crawl.db`
4. Write `.md` + frontmatter if changed (or update DB timestamps if unchanged)
5. Optionally discover new links (link-crawl mode only)

Log lines like `Updated … -> crawl/edu-gov-cz/pages/foo.md` are paths **relative to `data_dir`**, not relative to your shell cwd.

### Engine safeguards

Built during July 2026 hardening — all in `myskin/crawler/engine.py` + `urls.py`:

| Safeguard | What it prevents |
|-----------|------------------|
| **CSS skip** (`is_css_url`) | `.css` URLs skipped (query string stripped before extension check) |
| **Index canonicalization** | `/index`, `/index.html`, etc. normalized to `/` — avoids duplicate `index.md` loops |
| **Frontier URL dedup** (`enqueued_urls`) | Same URL not queued twice in one run |
| **Frontier path dedup** (`enqueued_paths`) | Same local path not queued under different URLs |
| **Per-run write guard** (`updated_paths`) | Once a path is written this run, it won't be fetched again even if a dynamic page keeps changing hash |
| **State path lookup** (`get_resource_by_local_path`) | DB dedup by filesystem path, not URL alone |

These matter most in **link-crawl mode**. With **sitemap-only**, the queue is fixed up front and link discovery is off.

### Terminal progress (`crawler.progress`)

| Mode | Behavior |
|------|----------|
| `auto` | Resolves to `log` in Docker/non-TTY; `tty` if attached to a real terminal |
| `tty` | Split-screen live UI (stats top, recent events bottom) — best via `docker attach` / local CLI |
| `log` | One-line periodic summaries — default in Docker |
| `off` | No progress output; engine logs only |

For rich terminal UI locally:

```bash
python -m myskin.crawl -v
# or force TTY mode in config.yaml: crawler.progress: tty
```

Prefer **`/crawl` dashboard** for Docker monitoring — TTY split-screen is awkward in `docker compose logs`.

### Link-crawl mode (legacy / fallback)

Without `sitemap_url`:

- Starts at `seed_url`, follows in-scope links up to `max_depth`
- Skips CSS URLs (`.css`, query-string variants)
- Canonicalizes `/index`, `/index.html` → `/` to avoid duplicate paths
- `refresh_known: true` re-queues every URL already in `crawl.db` each run
- Per-run dedup: frontier tracks enqueued URLs/paths; paths updated once per run are not re-fetched

### Crawler CLI

```bash
docker compose exec myskin python -m myskin.crawl --max-pages 50 -v
```

### Output layout

```
data/crawl/<host-slug>/
  pages/<path>.md      # HTML → markdown
  pdfs/<path>.md       # PDF → extracted text
```

Each file has YAML frontmatter: `title`, `source_url`, `category`, `content_hash`, `updated_at`.

### State & incremental updates

| Mechanism | Location | Behavior |
|-----------|----------|----------|
| Content hash | `crawl.db` → `resources` | Skip rewrite when SHA-256 of body unchanged |
| Sitemap `<lastmod>` | queue build | Skip fetch when `lastmod ≤ last_changed_at` |
| `updated_at` | frontmatter | HTTP `Last-Modified` or write time → RAGFlow `poll_timestamp_field` |
| 404 handling | state + filesystem | Remove stale local file and DB row |
| URL ↔ path dedup | `get_resource_by_local_path` | Same file path won't be processed twice under different URLs |

### Crash recovery

On startup (`crawl_recovery.py`):

1. Any `crawl_runs` row without `finished_at` is marked aborted.
2. If `resume_on_startup: true` and no `run_on_startup` crawl is scheduled → triggers a **recovery crawl** (`trigger=recovery`).

### Crawl stats (per run)

| Field | Meaning |
|-------|---------|
| `pages_fetched` / `pdfs_fetched` | HTTP requests made |
| `pages_updated` / `pdfs_updated` | Content changed (file rewritten) |
| `pages_unchanged` / `pdfs_unchanged` | Fetched but hash matched |
| `pages_failed` / `pdfs_failed` | HTTP/parse errors |
| `discovered` | **Sitemap mode:** total URLs in XML. **Link mode:** new links found |
| `sitemap_urls` | Total URLs parsed from sitemap |
| `sitemap_queued` | URLs queued this run |
| `sitemap_skipped` | Skipped by `<lastmod>` (unchanged) |

### Retriggering a crawl after config change

1. `docker compose up -d` (reload config if you changed `config.yaml`)
2. `POST /api/crawl/run` or wait for scheduler

`max_pages` applies **per run**, not as a lifetime cap on the corpus.

### Not yet in crawler

- JavaScript-rendered pages (Playwright / Crawl4AI)
- Raw PDF binary retention
- Per-sitemap-file caching (every run re-fetches all child sitemaps)
- Parallel sitemap fetching

---

## 8. Crawl dashboard & live API

Browser UI at **`GET /crawl`** — enter API token once (stored in `localStorage`), then:

- Start crawl (`POST /api/crawl/start`)
- Live stats grouped by **Run**, **Sitemap**, **Pages**, **PDFs**
- Recent page events with **clickable source URLs** (open failed pages in a new tab to verify)
- Chart (Chart.js, **no animation**): queue, in-sitemap count, processed vs elapsed time
  - Updates via `labels.push` + `data.push` + `chart.update("none")` each poll — instant redraw, no tweening (animated variants were tried and removed)

### Live API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/crawl/live` | Bearer | Running flag + live state, samples, events |
| `POST` | `/api/crawl/start` | Bearer | Start crawl in background (non-blocking) |
| `GET` | `/api/crawl/status` | Bearer | Scheduler + last finished run stats |
| `POST` | `/api/crawl/run` | Bearer | Run crawl synchronously (waits until done) |

### Dashboard stat groups

| Group | Cards |
|-------|-------|
| **Run** | Processed (% of max), Queue |
| **Sitemap** | Discovered (XML total), To crawl, Skipped (unchanged by lastmod) |
| **Pages** | Updated, Unchanged, Failed, Fetched |
| **PDFs** | Updated, Unchanged, Failed, Fetched |

The chart **“In sitemap”** line tracks `stats.discovered` (= sitemap URL count). Poll interval: 1.5 s.

### curl examples

```bash
# Live state
curl -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/live

# Blocking crawl
curl -X POST -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/run

# Background crawl
curl -X POST -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/start
```

---

## 9. RAGFlow deployment reference

From [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md) — server `jbi-sv-01`.

### Host prerequisites

```bash
# Required for Elasticsearch — or ES container crashes
sudo sysctl -w vm.max_map_count=262144
# Persist: add to /etc/sysctl.conf
```

### Docker Compose

```bash
git clone https://github.com/infiniflow/ragflow.git
cd ragflow/docker
cp .env.example .env
docker compose -f docker-compose.yml up -d
```

Use **`docker-compose.yml`** (not `docker-compose-base.yml` alone).

### Port conflict fix (MySQL 3306)

Host MySQL was occupying 3306. Options:

1. Stop host MySQL: `sudo systemctl stop mysql`
2. Change `MYSQL_PORT=3307` in `.env`
3. **Best:** remove DB port exposure entirely — containers talk on internal Docker network; only expose UI port

### Access URLs (our deployment)

| Service | Port | URL |
|---------|------|-----|
| Web UI | **9880** | `http://<host>:9880` |
| API | **9380** | `http://<host>:9380` |

Check live mapping: `docker compose ps`

First boot takes minutes (DB init, ES, models). `curl http://localhost:9880` may reset until ready — wait for HTML response.

### Ollama integration

Ollama on host port **15434**:

| Setting | Value |
|---------|-------|
| Base URL | `http://host.docker.internal:15434` or host LAN IP |
| API Key | dummy `ollama` (local Ollama has no real key) |
| Embedding model | `bge-m3` or similar |
| Chat model | `llama3`, `mistral`, etc. |

If `host.docker.internal` fails, add to `docker-compose.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### RAGFlow API key

Settings → API → generate key. Used for `POST /v1/connectors` etc.

### Linking connector to dataset

1. Create connector (UI: Settings → Data Sources → REST API, or API)
2. In dataset/knowledge base settings → link data source
3. Test: `POST /v1/connectors/{id}/test`
4. Rebuild if needed: `POST /v1/connectors/{id}/rebuild` with `{ "kb_id": "..." }`

---

## 10. RAGFlow REST API connector spec

Source: RAGFlow `common/data_source/rest_api_connector.py` ([PR #13545](https://github.com/infiniflow/ragflow/pull/13545)).

RAGFlow polls your endpoint, expects **JSON**, extracts an array of **objects**, maps fields → `Document` (always stored as `.txt`).

### UI form → `config` JSON

| UI field | Config key |
|----------|------------|
| Base URL | `url` |
| HTTP Method | `method` (`GET` or `POST`) |
| Query Parameters | `query_params` (dict or `key=value` lines) |
| Items Path | `items_path` (JSONPath, e.g. `$.items`) |
| ID Field | `id_field` |
| Auth Type | `auth_type`: `none`, `api_key_header`, `bearer`, `basic` |
| Content Fields | `content_fields` (**required**, comma-separated) |
| Metadata Fields | `metadata_fields` |
| Pagination Type | `pagination_type`: `none`, `page`, `offset`, `cursor` |
| Custom Headers | `headers` (JSON) |
| Max Pages | `max_pages` (default 1000) |
| Request Delay | `request_delay` seconds (default 0.5) |
| Poll Timestamp Field | `poll_timestamp_field` |
| Request Body | `request_body` (POST only) |

### Pagination config (`pagination_config`)

| Type | Keys | Defaults |
|------|------|----------|
| `page` | `start_page`, `page_param`, `page_size_param`, `page_size` | `page` |
| `offset` | `start_offset`, `offset_param`, `limit_param`, `limit` | `offset`, `limit` |
| `cursor` | `cursor_param`, `initial_cursor`, `next_cursor_path` | `cursor` |

### Items extraction

1. If `items_path` set → JSONPath (e.g. `$.items`)
2. Else auto-detect first list under: `items`, `results`, `data`, `records`, or first list value in response
3. Each item must be a **JSON object** (`dict`)

### Field path syntax

Dot notation with optional array indices:

- `title`
- `meta.author`
- `tags[0].name`
- `tags[*].name` (wildcards joined with `, `)

### Document mapping

- `id` = `hash128("rest_api:" + id_field_value)` — stable `id_field` critical for updates
- Content = join of `content_fields` values (HTML stripped) OR `content_template`
- `doc_updated_at` from `poll_timestamp_field` (ISO 8601, unix, common date formats)
- Incremental sync: without `poll_timestamp_field`, full re-fetch + in-memory filter

### SSRF restrictions (important)

RAGFlow **blocks** URLs that resolve to:

- `localhost`
- Private IPs (`10.x`, `192.168.x`, etc.)
- Link-local, reserved, multicast

**myskin must be reachable at a public hostname** for RAGFlow to connect. Use ngrok / Cloudflare Tunnel for local dev.

### Create connector via API

```http
POST /v1/connectors
Authorization: Bearer <ragflow-api-key>
Content-Type: application/json
```

```json
{
  "name": "myskin",
  "source": "rest_api",
  "refresh_freq": 5,
  "prune_freq": 720,
  "config": {
    "url": "https://<public-host>/api/documents",
    "method": "GET",
    "items_path": "$.items",
    "id_field": "id",
    "content_fields": "title,body",
    "metadata_fields": "author,category",
    "auth_type": "bearer",
    "credentials": { "token": "<MYSKIN_API_TOKEN>" },
    "pagination_type": "offset",
    "pagination_config": {
      "offset_param": "offset",
      "limit_param": "limit",
      "start_offset": 0,
      "limit": 50
    },
    "poll_timestamp_field": "updated_at",
    "request_delay": 2.5
  }
}
```

### Note on PDF URLs in content fields

Early research suggested RAGFlow might download `.pdf` URLs from content fields. The actual `rest_api` connector implementation **coerces field values to text** — it does **not** fetch binary URLs. **Pre-extract PDF text in the crawler** and write `.md` to `data/`.

### One myskin server vs multiple RAGFlow knowledge bases

**RAGFlow** supports many connectors and many datasets/KBs — not limited to one data source per server.

**myskin (today)** exposes **one unified catalog**: `GET /api/documents` walks all of `data/` recursively. One crawler config → one `seed_url` / `sitemap_url`.

| Goal | Approach |
|------|----------|
| **One KB, all content** | Single myskin + one `rest_api` connector (current edu.gov.cz setup) |
| **Multiple KBs, one host** | Not built-in — would need API filters (`path_prefix`, `category`) and multiple RAGFlow connectors with different `query_params` |
| **Multiple sites** | Multiple myskin containers (different ports/volumes/configs) or merge everything into one `data/` tree |
| **Same data in two KBs** | Two connectors hitting the same full `/api/documents` — works but duplicates embedding work |

RAGFlow's connector supports `query_params`; a future myskin extension could slice the catalog per dataset without running multiple containers.

---

## 11. myskin API contract

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Status, doc count, scheduler/crawl flags |
| `GET` | `/docs` | No | OpenAPI (Swagger) |
| `GET` | `/api/documents` | Bearer | Paginated catalog for RAGFlow |
| `GET` | `/api/documents/{id}` | Bearer | Single document |
| `GET` | `/crawl` | No | HTML crawl dashboard (token entered in UI) |
| `GET` | `/api/crawl/live` | Bearer | Live crawl state + chart samples |
| `GET` | `/api/crawl/status` | Bearer | Scheduler + last finished run |
| `POST` | `/api/crawl/run` | Bearer | Blocking crawl (waits for completion) |
| `POST` | `/api/crawl/start` | Bearer | Background crawl |

### Authentication (Bearer)

Protected routes expect:

```http
Authorization: Bearer <MYSKIN_API_TOKEN>
```

Token is set in `.env` only. Empty token = auth disabled (not recommended in production).

```bash
# Health — no auth
curl -s http://localhost:8080/health | jq

# Documents
curl -s -H "Authorization: Bearer $MYSKIN_API_TOKEN" \
  "http://localhost:8080/api/documents?offset=0&limit=10" | jq

# Crawl status
curl -s -H "Authorization: Bearer $MYSKIN_API_TOKEN" \
  http://localhost:8080/api/crawl/status | jq

# OpenAPI
open http://localhost:8080/docs
```

The `/crawl` dashboard HTML is unauthenticated; you paste the token in the UI (stored in browser `localStorage`).

### Query parameters (`/api/documents`)

| Param | Default | Description |
|-------|---------|-------------|
| `offset` | 0 | Pagination offset (RAGFlow offset mode) |
| `limit` | 50 | Page size (max 500) |
| `updated_since` | — | Optional ISO filter (myskin extension, not used by RAGFlow connector) |

### Response shape

```json
{
  "items": [
    {
      "id": "specs--embedded-bindi-spec.md",
      "title": "Embedded bindi spec",
      "body": "# Embedded bindi spec\n\n...",
      "updated_at": "2026-06-29T10:00:00Z",
      "author": "Clarence Claymore",
      "category": "specs"
    }
  ],
  "total": 42
}
```

### Configuration

| Source | Purpose |
|--------|---------|
| `config.yaml` | API host/port, `data_dir`, crawler, scheduler |
| `config.docker.yaml` | Docker path overrides (`MYSKIN_CONFIG_FILES`) |
| `config.local.yaml` | Optional local overrides (copy from `config.local.yaml.example`, gitignored) |
| `.env` | **`MYSKIN_API_TOKEN` only** (secrets) |

Config is read **once at process start**. After editing `config.yaml`, restart: `docker compose up -d` (or `--build` if code changed).

API bind host/port: `config.yaml` → `api.host`, `api.port` (default `0.0.0.0:8080`).

### Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn myskin.main:app --host 0.0.0.0 --port 8080
```

---

## 12. Web scraping strategy

### General principles

1. **Check robots.txt and ToS** before crawling — even with technical permission, commercial reuse may be restricted
2. **Rate limit** — 2–3 s between requests for government servers
3. **Transparent User-Agent** — e.g. `EduGovKnowledgeBot/1.0 (contact@yourdomain.com)`
4. **Incremental updates** — sitemap `<lastmod>` skip + content hash for fetched pages
5. **Idempotent output** — stable file paths → stable myskin IDs → RAGFlow upsert not duplicate

### Sitemap-first strategy (edu.gov.cz)

Yoast SEO publishes [sitemap_index.xml](https://edu.gov.cz/sitemap_index.xml) with child sitemaps per content type (`page-sitemap.xml`, `post-sitemap.xml`, `dlp_document-sitemap.xml`, …). Each URL entry includes `<lastmod>`.

**Prefer sitemap over link crawling** for large government sites:

| Approach | First run | Incremental run |
|----------|-----------|-----------------|
| Link crawl + `refresh_known` | Hours — revisits entire known set | Hours |
| **Sitemap + lastmod** | Hours — all URLs new | Minutes — only changed URLs |

Configure in `config.yaml` — see [§7](#7-crawler-scheduler--sitemap).

### edu.gov.cz specifics

- Central hub for school legislation, methodology, Infoservis
- Heavy use of **nested PDF attachments**
- Content changes periodically (monthly bulletins) — **weekly crawl** is enough
- `robots.txt` allows scraping (per project research)

### Firecrawl & robots.txt (separate client context)

From [convos/Bypassing-Firecrawl's-Robots.txt-Check.md](../convos/Bypassing-Firecrawl's-Robots.txt-Check.md):

Used with **Dify** knowledge sync + self-hosted Firecrawl when client contract allows scraping but `robots.txt` cannot be changed.

| Approach | Notes |
|----------|-------|
| Cloud Firecrawl | Cannot disable robots.txt |
| Self-hosted `SKIP_ROBOTS_TXT_CHECK=true` | Claimed in env; verify in your Firecrawl version |
| Per-request `ignoreRobotsTxt: true` | In `crawlerOptions` / `scrapeOptions` |
| Dify integration | Cannot pass custom headers/options — needs global env, proxy, or Dify fork |
| Kong/reverse proxy | Inject `ignoreRobotsTxt` into JSON body |
| Dify fork | Add UI toggle → `website_service.py` → Firecrawl payload |

**Not directly applicable to edu.gov.cz** (robots.txt allows crawling), but documents tooling knowledge for other targets.

### Dify fork workflow (if ever needed)

From convo — for maintaining custom Dify changes across upstream updates:

- **Git stash** — quick and dirty
- **Git patch** — `git diff > feature.patch` then `git apply` after pull
- **Fork + feature branches** — `feature/robots-bypass` for PRs, `production-custom` to merge all local features

PR tip: frame as "Advanced Crawler Options (JSON)" not "Ignore robots.txt" — maintainers unlikely to merge explicit bypass toggle.

---

## 13. Target site: edu.gov.cz

### Crawl configuration (production)

| Setting | Value |
|---------|-------|
| Seed URL | `https://edu.gov.cz/` |
| Sitemap | `https://edu.gov.cz/sitemap_index.xml` |
| `sitemap_only` | `true` |
| `max_pages` | `100000` (per-run fetch cap) |
| Delay | `1.5` s between requests |
| PDFs | Download + extract text to `.md` (incl. `dlp_document-sitemap.xml`) |
| Schedule | Weekly (Sunday 02:00 UTC) |

**First run:** expect a long initial crawl — all sitemap URLs are queued.  
**Subsequent runs:** only pages with newer `<lastmod>` than `last_changed_at` in `crawl.db`.

### Sitemap index contents (reference)

The index lists ~30 child sitemaps including: `page-sitemap.xml`, `post-sitemap.xml`, `job_listing-sitemap.xml`, `metodicky_materialy-sitemap.xml`, `dlp_document-sitemap.xml`, `tribe_events-sitemap.xml`, taxonomy sitemaps (`category-sitemap.xml`, …). Taxonomy/author URLs are crawled if in scope; most value is in `page`, `post`, and `dlp_document` entries.

### Content categories (suggested `category` frontmatter)

- `legislation`
- `methodology`
- `infoservis`
- `pdf`
- `news`

### Chunking in RAGFlow

Dataset config → **General** chunk method — uses DeepDoc for layout-aware chunking of both web-derived markdown and PDF-extracted text.

---

## 14. Tool evaluation history

| Tool | Self-hosted | PDF | Auto-update | Commercial | Outcome |
|------|-------------|-----|-------------|------------|---------|
| Vectorize.io | No (SaaS) | ? | Yes | ? | Rejected — not self-hosted |
| Cloudflare AutoRAG | CF platform | Yes | Yes | Yes | Rejected — not fully self-hosted |
| LangChain + Firecrawl | Partial | Via Firecrawl | Cron | Yes | Deferred |
| **RAGFlow** | Yes | DeepDoc | Connector sync | Apache 2.0 | **Selected** |
| Dify + Crawl4AI | Yes | Crawl4AI | Cron | Yes | Alternative; not chosen for edu.gov |
| Langflow + Crawl4AI | Yes | Yes | Cron | Yes | Alternative |
| RSS feed as data source | Yes | Enclosure tags | Poll | Yes | Hack; not chosen |
| Push upload API | Yes | Yes | Script | Yes | Works; push not pull |
| **myskin + rest_api** | Yes | Via crawler→md | Poll | Yes | **Selected architecture** |
| Chroma HttpClient | Yes | N/A | N/A | Apache 2.0 | Explored for remote vectors only — see [convos/Serving-Chroma-Vector-Store-Remotely.md](../convos/Serving-Chroma-Vector-Store-Remotely.md) |

### Chroma note

Chroma `HttpClient` can serve multiple collections from a remote machine. Useful if we ever split embedding/retrieval from the app server. **RAGFlow manages its own vector store** (Elasticsearch/Infinity) — Chroma is not part of this pipeline unless we build a separate app that queries Chroma directly.

---

## 15. Legal & compliance

| Topic | Guidance |
|-------|----------|
| RAGFlow license | Apache 2.0 — commercial use OK |
| myskin | TBD (set before production) |
| Scraped content | Verify site ToS + copyright for commercial chatbot use |
| edu.gov.cz | robots.txt allows crawling per our check; confirm ToS for commercial reuse |
| Other clients | Contractual scraping permission may exist even when robots.txt blocks — handle per site, document in writing |
| PII | Gov education docs — review for personal data before indexing |

---

## 16. Operations procedures

### Deploy myskin

1. Clone repo, `cp .env.example .env`, set `MYSKIN_API_TOKEN`
2. Tune `config.yaml` (crawler sitemap, scheduler, delays)
3. `docker compose up -d --build`
4. Run behind reverse proxy with TLS (Caddy, nginx, Traefik)
5. Expose **public** URL for RAGFlow (not localhost)
6. Open `https://<host>/crawl` to monitor crawls

### Docker data locations

| What | Where |
|------|-------|
| Crawled markdown | Volume `myskin_myskin-data` → `/app/data` |
| Crawl state DB | Volume `myskin_myskin-state` → `/app/.myskin/crawl.db` |
| Config | Baked into image + `MYSKIN_CONFIG_FILES` env |

Inspect data: `docker compose exec myskin ls /app/data/crawl/`

Read a crawled file from the container:

```bash
docker compose exec myskin cat /app/data/crawl/edu-gov-cz/pages/index.md | head
```

Copy volume to host (backup):

```bash
docker compose exec myskin tar -C /app/data -czf - crawl | tar -xzf - -C ./backup-data
```

### Retrigger crawl after config change

1. Edit `config.yaml` (or `config.local.yaml`)
2. `docker compose up -d` — reload config
3. `POST /api/crawl/run` or wait for scheduler

`.env` token changes also require container restart.

### Register RAGFlow connector

See [§10](#10-ragflow-rest-api-connector-spec) and [README](../README.md).

### Verify end-to-end

```bash
# 1. myskin health
curl https://<myskin-host>/health

# 2. myskin documents
curl -H "Authorization: Bearer $TOKEN" \
  "https://<myskin-host>/api/documents?offset=0&limit=5"

# 3. RAGFlow test connector
curl -X POST "http://<ragflow-host>:9380/v1/connectors/<id>/test" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"

# 4. Check sync logs in RAGFlow UI or:
curl "http://<ragflow-host>:9380/v1/connectors/<id>/logs" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY"
```

### Update content

1. Scheduler or `POST /api/crawl/run` → crawler writes/updates `data/`
2. Sitemap mode skips unchanged URLs before HTTP fetch
3. myskin picks up changes on next `/api/documents` request
4. RAGFlow polls per `refresh_freq` → re-embeds changed docs via `poll_timestamp_field`

### Monitor a crawl

- Dashboard: `GET /crawl` (save API token in UI)
- API: `GET /api/crawl/live`
- Logs: `docker compose logs -f myskin`

### Full re-index

`POST /v1/connectors/{id}/rebuild` with `{ "kb_id": "<dataset-id>" }`

---

## 17. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| RAGFlow connector test fails | myskin on localhost/private IP | Public URL or tunnel |
| RAGFlow 401 from myskin | Token mismatch | Align `MYSKIN_API_TOKEN` and connector `credentials.token` |
| myskin 401 on `/api/documents` | Missing `Authorization` header | `curl -H "Authorization: Bearer $TOKEN" …` |
| Log path not found on host | Path is relative to `data_dir` inside container | Use `docker compose exec myskin cat /app/data/…` |
| Repeated `[page] unchanged index.md` | Index URL aliases (fixed) | Update to build with index canonicalization |
| Queue inflates on cyclic links | Link-crawl without frontier dedup (fixed) | Update; or use `sitemap_only: true` |
| Same page re-fetched all run | Dynamic content / anti-bot (fixed) | `updated_paths` guard per run |
| Empty `items` in RAGFlow | Wrong `items_path` | Use `$.items` for myskin |
| Duplicate documents | Missing/unstable `id_field` | Ensure crawler uses stable paths → stable myskin `id` |
| No incremental updates | No `poll_timestamp_field` | Set to `updated_at` |
| PDFs not indexed | PDF in `data/` not supported | Crawler must extract text to `.md` |
| RAGFlow UI connection reset | Still booting | Wait, check `docker compose logs -f ragflow-cpu` |
| MySQL port bind error | Host MySQL on 3306 | Change port or unexpose DB |
| Ollama connection fail from Docker | Network | `host.docker.internal` or LAN IP + `extra_hosts` |
| Firecrawl blocked by robots (other projects) | Dify sends no bypass flag | Env var, proxy, or Dify fork |
| Crawl takes forever every week | Link crawl + `refresh_known` | Enable `sitemap_url` + `sitemap_only` |
| Incremental crawl still slow | Sitemap overhead (~30 XML fetches) | Normal; page fetches should be few |
| Dashboard shows 0 discovered | Run started before sitemap loaded | Wait for queue build; check logs |
| `409 Crawl already in progress` | Overlapping triggers | Wait or use `/api/crawl/start` once |
| Data not on host `./data` | Named Docker volume | `docker volume inspect myskin_myskin-data` |
| Recovery crawl on every boot | Interrupted previous run | Let it finish; or `resume_on_startup: false` |

---

## 18. Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-29 | Target RAGFlow over Dify/Langflow for edu.gov KB | Self-hosted, DeepDoc PDFs, Apache 2.0, connector system |
| 2026-06-29 | Use `rest_api` connector, not upload API | Pull-based sync like native data sources |
| 2026-06-29 | Build myskin as thin catalog layer | RAGFlow UI lacked web crawler; decouple scrape chaos from RAG |
| 2026-06-29 | FastAPI + filesystem `data/` | Simple, debuggable, crawler writes files, myskin serves JSON |
| 2026-06-29 | Text in `data/` not raw PDFs | `rest_api` connector maps text fields only |
| 2026-07-01 | Sitemap-first crawl for edu.gov.cz | `lastmod` skips unchanged URLs; incremental runs in minutes not hours |
| 2026-07-01 | `config.yaml` + yayaya for settings | Non-secrets in git; `.env` for token only |
| 2026-07-01 | Live crawl dashboard at `/crawl` | Grouped stats, chart, sitemap skipped/queued counts |
| 2026-07-01 | Chart.js: no animation | Animated updates caused line jumping; instant `update("none")` |
| 2026-07-01 | Crawler frontier hardening | CSS skip, index canonicalization, cycle + per-run rewrite guards |
| 2026-07-01 | Crash recovery crawl | `resume_on_startup` + `crawl_recovery.py` |
| 2026-07-07 | Document multi-KB topology | One myskin = one catalog; multiple RAGFlow KBs need filters or multiple instances |
| 2026-06-21 | Firecrawl robots bypass via env/fork/proxy | Documented for Dify client work; not needed for edu.gov.cz |
| 2026-05-21 | Chroma HttpClient for remote vectors | Explored; orthogonal to RAGFlow ingestion path |

---

## 19. Source material (archived convos)

Original AI conversations preserved as evidence of research and decisions:

| File | Topics |
|------|--------|
| [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md) | Tool selection, RAGFlow setup, Docker ports, Ollama, edu.gov.cz crawl plan, REST API connector spec, push vs pull architecture |
| [convos/Bypassing-Firecrawl's-Robots.txt-Check.md](../convos/Bypassing-Firecrawl's-Robots.txt-Check.md) | Self-hosted Firecrawl, Dify integration limits, robots.txt bypass strategies, fork/patch workflows |
| [convos/Serving-Chroma-Vector-Store-Remotely.md](../convos/Serving-Chroma-Vector-Store-Remotely.md) | Chroma HttpClient, multi-collection, remote vector serving (explored, not adopted) |

External references:

- [RAGFlow — Data Source Connectors (DeepWiki)](https://deepwiki.com/infiniflow/ragflow/6.6-data-source-connectors)
- [RAGFlow — Generic REST API connector PR #13545](https://github.com/infiniflow/ragflow/pull/13545)
- [RAGFlow GitHub](https://github.com/infiniflow/ragflow)
- [Target site: edu.gov.cz](https://edu.gov.cz/)
- [edu.gov.cz sitemap index](https://edu.gov.cz/sitemap_index.xml)

### Cursor implementation session (2026-07)

Interactive development transcript for the crawler/dashboard/sitemap work (Cursor agent chat, July 2026). Use alongside this runbook for **why** specific edge cases were fixed.

Topics covered in that session: Bearer auth & curl, Docker volume vs host `./data`, per-run `max_pages`, terminal progress → HTML dashboard, Chart.js iteration (animations removed), index.md duplicate loop, queue cycle prevention, per-run rewrite guard, YAML/yayaya config split, sitemap `lastmod` incremental crawl, dashboard stat groups, multi-RAGFlow-KB question.

---

## 20. Implementation session notes (2026-07)

Chronological log of what was built and decided during the July 2026 implementation session (Cursor chat). Cross-references earlier research in `convos/` and sections above.

| When | Topic | Outcome | Runbook |
|------|-------|---------|---------|
| Early | API auth | Bearer token on protected routes; `/health` and `/docs` public | [§11](#11-myskin-api-contract) |
| Early | Retrigger crawl | Restart container after config change; `POST /api/crawl/run` | [§16](#16-operations-procedures) |
| Early | Where is `data/`? | Docker named volume `myskin_myskin-data`, not host `./data` | [§6](#6-what-is-built-today), [§16](#16-operations-procedures) |
| Early | `max_pages` scope | Per-run cap on fetches, not lifetime corpus limit | [§7](#7-crawler-scheduler--sitemap) |
| Mid | Terminal progress | `progress.py` tty/log modes; dashboard preferred in Docker | [§7](#7-crawler-scheduler--sitemap), [§8](#8-crawl-dashboard--live-api) |
| Mid | CSS poisoning | Skip `.css` URLs (ignore query string) | [§7](#7-crawler-scheduler--sitemap) |
| Mid | Crash recovery | Abort unfinished runs; optional recovery crawl on startup | [§7](#7-crawler-scheduler--sitemap) |
| Mid | `index.md` loop | Canonicalize `/index` → `/` | [§7](#7-crawler-scheduler--sitemap), [§17](#17-troubleshooting) |
| Mid | Queue cycles | Frontier `enqueued_urls` / `enqueued_paths` | [§7](#7-crawler-scheduler--sitemap) |
| Mid | Dynamic page spam | `updated_paths` — no second write same path per run | [§7](#7-crawler-scheduler--sitemap) |
| Mid | Dashboard events | Clickable URLs in recent pages list | [§8](#8-crawl-dashboard--live-api) |
| Mid | YAML config | `config.yaml` + yayaya; `.env` secrets only | [§6](#6-what-is-built-today), [§11](#11-myskin-api-contract) |
| Late | Sitemap crawl | `sitemap_index.xml` + `<lastmod>` vs `last_changed_at` | [§7](#7-crawler-scheduler--sitemap), [§13](#13-target-site-edugovcz) |
| Late | Dashboard facelift | Grouped stats; `discovered` = sitemap URL count; `sitemap_skipped` | [§8](#8-crawl-dashboard--live-api) |
| Late | Chart animation | Tried push/animate patterns; **shipped with `animation: false`** | [§8](#8-crawl-dashboard--live-api) |
| Late | Multi-KB question | One myskin = one catalog; multiple RAGFlow KBs need design | [§10](#10-ragflow-rest-api-connector-spec) |

### Reference: prior art

Live chart UX was compared against a personal Chart.js demo and `sensorV3Website` (`mdetector.php` — full snapshot replace + `animation: false`). myskin dashboard uses incremental `push` + `update("none")` for the same stability without tweening.

---

## Appendix: naming

| Name | Meaning |
|------|---------|
| **myskin** | Repo/service name; crawling + embedding pun |
| **data/** | Landing zone for crawled preprocessed documents |
| **rest_api** | RAGFlow connector type string (`source: "rest_api"`) |
| **jbi-sv-01** | Server hostname where RAGFlow v0.26.2 runs (from convos) |

---

*When deployment URLs or crawl behavior change, update §7–§8, §13, §16, and §20. Add decision log entries for architectural changes.*
