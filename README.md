<p align="center">
  <img src="assets/myskin-logo.png" alt="myskin logo — documents crawling into skin" width="180">
</p>

# myskin

> *Crawling in my skin…* — Chester Bennington  
> *Oh, oh yeah the bindis! Oh, there's bindis everywhere! Oh, embedded in the skin!* — Clarence Claymore

Self-hosted service that **crawls** web pages and linked documents, stores them in format-aware files (HTML→markdown, PDF/DOC/DOCX passthrough), and **pushes** them to [RAGFlow](https://github.com/infiniflow/ragflow) datasets via the dataset API.

**Maintainers:** [docs/RUNBOOK.md](docs/RUNBOOK.md) · [Česky](docs/RUNBOOK.cs.md)

## Quick start (Docker)

```bash
cp .env.example .env
cp config.yaml.example config.yaml   # instance config — not baked into the image
docker compose up -d --build
```

- API: `http://localhost:8080`
- Health: `GET /health`
- Admin UI: `GET /admin` (manage sites, trigger crawls and RAGFlow sync)
- Crawl dashboard: `GET /crawl`
- Trigger crawl: `POST /api/sites/{site_id}/crawl/run`

The internal scheduler runs crawls automatically — no host cron required.

## What runs in one container

```
┌─────────────────────────────────────┐
│  myskin (single process)            │
│  ├─ FastAPI — site admin + crawl API│
│  ├─ APScheduler — per-site cron     │
│  ├─ Site registry — SQLite          │
│  └─ Crawler — HTML/PDF → data/     │
└─────────────────────────────────────┘
         │ volumes
         ├─ myskin-data  → /app/data
         └─ myskin-state → /app/.myskin (sites.db, crawl state)
```

One instance can manage **multiple sites**, each with its own crawl config, schedule, and RAGFlow `dataset_id`. Configure sites in `config.yaml` (`sites:` array) or via the admin UI / `POST /api/sites`.

## Scheduler configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSKIN_SCHEDULER_ENABLED` | `true` | Internal scheduler on/off |
| `MYSKIN_SCHEDULER_CRON` | `0 2 * * 0` | 5-field cron (Sunday 02:00 UTC) |
| `MYSKIN_SCHEDULER_INTERVAL_HOURS` | — | Use interval instead of cron |
| `MYSKIN_SCHEDULER_INTERVAL_MINUTES` | — | Shorter interval alternative |
| `MYSKIN_SCHEDULER_RUN_ON_STARTUP` | `false` | Crawl once when container starts |
| `MYSKIN_SCHEDULER_TIMEZONE` | `UTC` | Cron timezone (`Europe/Prague`, etc.) |

**Cron** (default): `MYSKIN_SCHEDULER_CRON=0 2 * * 0`  
**Interval**: set `MYSKIN_SCHEDULER_INTERVAL_HOURS=168` (weekly) or `INTERVAL_MINUTES=30`  
**Manual only**: `MYSKIN_SCHEDULER_ENABLED=false` + `POST /api/crawl/run`

## Crawler configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSKIN_CRAWL_SEED_URL` | `https://edu.gov.cz/` | Start URL |
| `MYSKIN_CRAWL_MAX_DEPTH` | `3` | Link depth from seed |
| `MYSKIN_CRAWL_MAX_PAGES` | `1000` | Max resources per run |
| `MYSKIN_CRAWL_REQUEST_DELAY` | `2.5` | Seconds between HTTP requests |
| `MYSKIN_CRAWL_RESPECT_ROBOTS` | `true` | Honor robots.txt |
| `MYSKIN_CRAWL_REFRESH_KNOWN` | `true` | Re-check all known URLs each run (link-crawl mode) |
| `crawler.sitemap_url` | — | Sitemap index/URL set (e.g. `https://edu.gov.cz/sitemap_index.xml`) |
| `crawler.sitemap_only` | `true` | Only crawl sitemap URLs; skip following page `<a>` links |
| `crawler.follow_file_links` | `true` | In sitemap mode, still queue PDF/DOC/etc. links found on crawled pages |
| `crawler.html_to_markdown` | `true` | Convert HTML pages to markdown (RAGFlow cannot ingest HTML) |
| `crawler.passthrough.enabled` | `true` | Store PDF/DOC/DOCX/etc. as native binaries for RAGFlow DeepDoc |
| `crawler.passthrough.extract_pdf_text` | `false` | Legacy: extract PDF text to `.md` instead of passthrough |
| `api.public_base_url` | — | **Required** — base URL for `file_url` in catalog (`/api/files/{id}`) |

When `sitemap_url` is set, the crawler loads all nested sitemaps and **only queues URLs whose `<lastmod>` is newer than the last stored change** (or URLs never seen before). Incremental runs stay fast instead of re-fetching the whole site.

Crawled files land in `data/crawl/<host>/pages/` (markdown) and `files/` (binary) with metadata sidecars. The catalog lists every file and points to its download URL — content is never inlined in JSON.

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Status, doc counts, site count |
| `GET` | `/admin` | No | Web UI for site management |
| `GET` | `/api/sites` | Bearer | List configured sites |
| `POST` | `/api/sites` | Bearer | Create a site |
| `PUT` | `/api/sites/{id}` | Bearer | Update a site |
| `POST` | `/api/sites/{id}/crawl/run` | Bearer | Trigger crawl for one site |
| `POST` | `/api/sites/{id}/ragflow/sync` | Bearer | Push site files to RAGFlow |
| `GET` | `/api/sites/{id}/files/{doc_id}` | Bearer | Download a crawled file |

Legacy single-site endpoints (`/api/crawl/*`, `/api/files/*`, `/api/ragflow/sync`) still work against the default site.

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn myskin.main:app --host 0.0.0.0 --port 8080
```

One-shot crawl from CLI (also works while service is running if no overlap):

```bash
python -m myskin.crawl --max-depth 2 --max-pages 50 -v
```

## RAGFlow integration

myskin uses **push sync only** — files are uploaded to each site's RAGFlow dataset via `POST /api/v1/datasets/{id}/documents`. After each crawl, myskin uploads **only changed** files, sets **`meta_fields`** (`url`, `source_url`, `file_url`, `site_id`, `title`, …), tracks `myskin_id → ragflow_document_id` in per-site sync state, deletes removed docs, and triggers parsing.

```yaml
ragflow:
  api_url: https://ragflow.example.com   # shared

sites:
  - id: edu-gov-cz
    ragflow:
      enabled: true
      dataset_id: "<dataset-id>"
      sync_on_crawl_complete: true
```

Env: `MYSKIN_RAGFLOW_API_KEY=<ragflow-api-key>`

Manual trigger: `POST /api/sites/{site_id}/ragflow/sync` (Bearer myskin token).

Full setup: [docs/RUNBOOK.md](docs/RUNBOOK.md) and `config.yaml.example`.

## GitLab CI/CD

GitHub `main` is mirrored to GitLab via [`.github/workflows/sync-to-gitlab.yml`](.github/workflows/sync-to-gitlab.yml) (same pattern as [mcp-hooker](https://github.com/KodzghlyCZ/mcp-hooker)).

`.gitlab-ci.yml` builds the Docker image on a tagged runner and pushes to the GitLab Container Registry:

- `registry.gitlab.catania-service.cz/catania_dev/myskin:$CI_COMMIT_SHORT_SHA`
- `registry.gitlab.catania-service.cz/catania_dev/myskin:latest` (default branch only)

Register a GitLab runner with tag `myskin` (or change the tag in `.gitlab-ci.yml` to match your fleet).

**GitHub repo secrets** (for the sync workflow): `GITLAB_URL`, `USERNAME`, `GITLAB_PAT`.

## License

TBD.
