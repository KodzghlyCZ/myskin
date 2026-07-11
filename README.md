# myskin

> *Crawling in my skin…* — Chester Bennington  
> *Oh, oh yeah the bindis! Oh, there's bindis everywhere! Oh, embedded in the skin!* — Clarence Claymore

Self-hosted service that **crawls** web pages and PDFs, stores them as markdown, and **serves** them to [RAGFlow](https://github.com/infiniflow/ragflow) via the `rest_api` data source connector.

**Maintainers:** [docs/RUNBOOK.md](docs/RUNBOOK.md) · [Česky](docs/RUNBOOK.cs.md)

## Quick start (Docker)

```bash
cp .env.example .env          # set MYSKIN_API_TOKEN, tune crawler/scheduler
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
| `crawler.sitemap_only` | `true` | Only crawl sitemap URLs; skip link following |

When `sitemap_url` is set, the crawler loads all nested sitemaps and **only queues URLs whose `<lastmod>` is newer than the last stored change** (or URLs never seen before). Incremental runs stay fast instead of re-fetching the whole site.

Crawled files land in `data/crawl/<host>/pages/` and `pdfs/` with YAML frontmatter (`updated_at` for RAGFlow incremental sync).

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | No | Status, doc count, scheduler/crawl flags |
| `GET` | `/api/documents` | Bearer | Paginated catalog for RAGFlow |
| `GET` | `/api/documents/{id}` | Bearer | Single document |
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

## RAGFlow connector

Point the REST API connector at `https://<public-host>/api/documents` with `items_path=$.items`, `id_field=id`, `content_fields=title,body`, offset pagination, and `poll_timestamp_field=updated_at`. RAGFlow blocks private IPs — use a tunnel for local dev.

Full connector JSON and setup: [docs/RUNBOOK.md](docs/RUNBOOK.md) and `.env.example`.

## GitLab CI/CD

GitHub `main` is mirrored to GitLab via [`.github/workflows/sync-to-gitlab.yml`](.github/workflows/sync-to-gitlab.yml) (same pattern as [mcp-hooker](https://github.com/KodzghlyCZ/mcp-hooker)).

`.gitlab-ci.yml` builds the Docker image on a tagged runner and pushes to the GitLab Container Registry:

- `registry.gitlab.catania-service.cz/catania_dev/myskin:$CI_COMMIT_SHORT_SHA`
- `registry.gitlab.catania-service.cz/catania_dev/myskin:latest` (default branch only)

Register a GitLab runner with tag `myskin` (or change the tag in `.gitlab-ci.yml` to match your fleet).

**GitHub repo secrets** (for the sync workflow): `GITLAB_URL`, `USERNAME`, `GITLAB_PAT`.

## License

TBD.
