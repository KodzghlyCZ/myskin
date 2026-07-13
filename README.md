<p align="center">
  <img src="assets/myskin-logo.png" alt="myskin logo — documents crawling into skin" width="180">
</p>

# myskin

> *Crawling in my skin…* — Chester Bennington  
> *Oh, oh yeah the bindis! Oh, there's bindis everywhere! Oh, embedded in the skin!* — Clarence Claymore

Self-hosted service that **crawls** web pages and linked documents, stores them in format-aware files (HTML→markdown, PDF/DOC/DOCX passthrough), and **serves** them to [RAGFlow](https://github.com/infiniflow/ragflow).

**Maintainers:** [docs/RUNBOOK.md](docs/RUNBOOK.md) · [Česky](docs/RUNBOOK.cs.md)

## Quick start (Docker)

```bash
cp .env.example .env
cp config.yaml.example config.yaml   # instance config — not baked into the image
docker compose up -d --build
```

- API: `http://localhost:8080`
- Health: `GET /health`
- Docs for RAGFlow: `GET /api/documents` (Bearer auth)
- Crawl status: `GET /api/crawl/status`
- Trigger crawl now: `POST /api/crawl/run`

The internal scheduler runs crawls automatically — no host cron required.

## What runs in one container

```
┌─────────────────────────────────────┐
│  myskin (single process)            │
│  ├─ FastAPI — RAGFlow catalog API   │
│  ├─ APScheduler — configurable cron │
│  └─ Crawler — HTML/PDF → data/     │
└─────────────────────────────────────┘
         │ volumes
         ├─ myskin-data  → /app/data
         └─ myskin-state → /app/.myskin (crawl.db)
```

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
| `GET` | `/health` | No | Status, doc count, scheduler/crawl flags |
| `GET` | `/api/documents` | Bearer | Paginated catalog for RAGFlow |
| `GET` | `/api/documents/{id}` | Bearer | Single document |
| `GET` | `/api/files/{id}` | Bearer | Download any catalog file (md, pdf, docx, …) |
| `GET` | `/api/crawl/status` | Bearer | Scheduler + last crawl run |
| `POST` | `/api/crawl/run` | Bearer | Trigger crawl immediately |

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

Two modes — use **one**, not both on the same dataset:

### Pull: `rest_api` connector (text only)

RAGFlow polls `GET /api/documents`. The connector coerces all content to `.txt` — fine for markdown summaries, useless for PDFs.

### Push: RAGFlow dataset API (recommended for binaries)

Enable `ragflow:` in config. After each crawl, myskin uploads **only changed** files via `POST /api/v1/datasets/{id}/documents`, tracks `myskin_id → ragflow_document_id` in `ragflow.state_db`, deletes removed docs, and triggers parsing.

```yaml
ragflow:
  enabled: true
  api_url: https://ragflow.example.com
  dataset_id: "<dataset-id>"
  sync_on_crawl_complete: true
```

Env: `MYSKIN_RAGFLOW_API_KEY=<ragflow-api-key>`

Manual trigger: `POST /api/ragflow/sync` (Bearer myskin token).

The catalog (`GET /api/documents`) still exposes metadata + `file_url` for debugging or other consumers.

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
