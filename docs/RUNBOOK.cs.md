# myskin — Provozní a architektonická příručka

> Referenční materiál pro správce: **proč** tento projekt existuje, **jak** jednotlivé části zapadají dohromady a **co** už bylo prozkoumáno, postaveno a rozhodnuto.
>
> Anglická verze: [RUNBOOK.md](RUNBOOK.md)
>
> Poslední aktualizace: 2026-07-07

---

## Obsah

1. [Shrnutí](#1-shrnutí)
2. [Problém, který řešíme](#2-problém-který-řešíme)
3. [Architektura](#3-architektura)
4. [Proč RAGFlow](#4-proč-ragflow)
5. [Proč existuje myskin (místo pouze RAGFlow)](#5-proč-existuje-myskin-místo-pouze-ragflow)
6. [Co je dnes postaveno](#6-co-je-dnes-postaveno)
7. [Crawler, plánovač a sitemap](#7-crawler-plánovač-a-sitemap)
8. [Crawl dashboard a live API](#8-crawl-dashboard-a-live-api)
9. [Referenční nasazení RAGFlow](#9-referenční-nasazení-ragflow)
10. [Specifikace REST API konektoru RAGFlow](#10-specifikace-rest-api-konektoru-ragflow)
11. [API kontrakt myskin](#11-api-kontrakt-myskin)
12. [Strategie web scrapingu](#12-strategie-web-scrapingu)
13. [Cílový web: edu.gov.cz](#13-cílový-web-edugovcz)
14. [Historie hodnocení nástrojů](#14-historie-hodnocení-nástrojů)
15. [Právní otázky a compliance](#15-právní-otázky-a-compliance)
16. [Provozní postupy](#16-provozní-postupy)
17. [Řešení problémů](#17-řešení-problémů)
18. [Deník rozhodnutí](#18-deník-rozhodnutí)
19. [Zdrojové materiály (archivované konverzace)](#19-zdrojové-materiály-archivované-konverzace)
20. [Poznámky ze sessions implementace (2026-07)](#20-poznámky-ze-sessions-implementace-2026-07)

---

## 1. Shrnutí

**myskin** je self-hosted **most mezi dokumenty**:

1. **Crawlerem** (implementováno), který sbírá webový obsah a PDF, předzpracuje je a zapisuje soubory do `data/`
2. **FastAPI službou** (implementováno), která tyto soubory vystavuje jako JSON katalog přes HTTP
3. **RAGFlow** (nasazeno samostatně), který z tohoto API **stahuje** data podle plánu pomocí vestavěného konektoru datového zdroje **`rest_api`**, poté chunkuje, embeduje a indexuje do znalostní báze pro chat/RAG

Název je slovní hříčka ([README](../README.md)): *crawling* v kůži (Chester Bennington) + *bindis embedded* v kůži (Clarence Claymore) → crawling + embedding.

**Cílový stav:** Znalostní chatbot nad obsahem českého Ministerstva školství (`https://edu.gov.cz/`) a propojených PDF, self-hosted, zdarma, komerčně použitelný, s automatickými periodickými aktualizacemi.

---

## 2. Problém, který řešíme

### Obchodní potřeba

- Primární cíl: **[edu.gov.cz](https://edu.gov.cz/)** — portál českého Ministerstva školství (legislativa, metodika, bulletiny Infoservis, PDF přílohy).
- Neexistuje veřejné API pro programové stahování dokumentů.
- Scraping/crawling je povolen podle `robots.txt` (ověřeno ve výzkumné konverzaci).
- Zamýšlené použití: **komerční znalostní chatbot** postavený na ingestovaných datech — **ne** přeprodej samotného RAGFlow.

### Technická potřeba

Potřebujeme systém, který:

| Požadavek | Poznámky |
|-----------|----------|
| Crawluje a scrapuje webové stránky | Včetně vnořených odkazů |
| Stahuje propojená PDF | edu.gov.cz je PDF-heavy |
| Předzpracuje do ingestovatelného textu | Preferovaný Markdown |
| Aktualizuje se periodicky | Týdenní cron je pro gov obsah rozumný |
| Napájí RAG/znalostní bázi | Chunking + embedding + retrieval |
| Self-hosted a zdarma | Bez SaaS lock-in |
| Komerční použití OK | Apache 2.0 stack |

### Co jsme výslovně odmítli nebo odložili

| Přístup | Proč ne (zatím) |
|---------|-----------------|
| Vestavěné web crawler UI v RAGFlow | V naší sestavě RAGFlow v0.26.2 není k dispozici — v UI datasetu jen upload souboru / prázdný soubor |
| RAGFlow Agent blok „Crawler“ | V naší verzi UI také není |
| Push souborů přes RAGFlow upload API | Funguje, ale chtěli jsme **pull-based** synchronizaci jako u Google Drive konektorů |
| Dify + Firecrawl | Prozkoumáno pro jiného klienta; bolest s obcházením robots.txt; jiný produkt |
| Chroma remote server | Prozkoumáno pro offload vektorového retrievalu; **není** naše cesta ingestu — vektory vlastní RAGFlow |
| Vectorize.io / Cloudflare AutoRAG | Není self-hosted / není zdarma |

---

## 3. Architektura

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

### Tok dat jednou větou

**Crawl → zápis do `data/` → myskin servíruje JSON → RAGFlow polluje → embeduje → chat.**

### Oddělení zodpovědností (záměrné)

| Vrstva | Zodpovědnost |
|--------|--------------|
| **Crawler** | Chaos: HTTP, PDF, rate limity, struktura webu, retry |
| **myskin** | Tenká, stabilní **katalogová API** odpovídající schématu `rest_api` v RAGFlow |
| **RAGFlow** | Těžká práce: parsing, chunking, embedding, vektorové úložiště, chat UI |

To odpovídá poznatku z našeho výzkumu: netlačit data do RAGFlow přes upload API; nechat ho, aby si dokumenty **sáhl** jako u Google Drive — přes **generický REST API konektor** (RAGFlow v0.26+).

---

## 4. Proč RAGFlow

Z [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md):

- **Self-hosted**, Docker Compose, plné UI + API
- **DeepDoc** — silný PDF/layout parsing (tabulky, více sloupců) oproti naivním textovým extraktorům
- **Apache License 2.0** — komerční použití povoleno; žádný copyleft na náš chatbot kód
- Nativní systém konektorů datových zdrojů (30+ providerů) — viz [RAGFlow Data Source Connectors](https://deepwiki.com/infiniflow/ragflow/6.6-data-source-connectors)
- Integrace Ollama pro bezplatné lokální embeddingy (`bge-m3` atd.) — čeština/multilingual

### Používaná verze RAGFlow

Server: `jbi-sv-01`, image `infiniflow/ragflow:v0.26.2`

---

## 5. Proč existuje myskin (místo pouze RAGFlow)

### Mezera v UI

V naší sestavě RAGFlow dataset ingest nabízel jen **Upload file** a **Create empty file**. Žádné tlačítko web crawl, žádný crawler agent blok. Diskutované možnosti:

1. ~~RAGFlow Agent ingestion pipeline s komponentou Crawler~~ — není v UI
2. ~~Push přes `POST /api/v1/document/upload`~~ — funguje, ale push model
3. **Vlastní REST API datový zdroj** — ✅ RAGFlow v0.26 přidal konektor `rest_api` s UI formulářem
4. ~~RSS feed hack~~ — alternativa bez kódu; méně kontroly nad zpracováním PDF

Zvolili jsme **#3**: postavit **myskin** jako REST endpoint, který RAGFlow polluje.

### Proč nemodifikovat zdroják RAGFlow?

Možné (napsat nativní connector driver v `common/data_source/`), ale:

- Vyšší údržba (fork, rebuild Docker)
- Generický konektor `rest_api` už existuje upstream ([PR #13545](https://github.com/infiniflow/ragflow/pull/13545))
- myskin drží scraping logiku **mimo** RAGFlow úplně

---

## 6. Co je dnes postaveno

### Rozložení repozitáře

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

Jedna služba **Docker Compose** spouští API + crawler + plánovač společně.

### Model konfigurace

| Vrstva | Soubor | Obsah |
|--------|--------|-------|
| **Tajemství** | `.env` | Pouze `MYSKIN_API_TOKEN` |
| **Hlavní config** | `config.yaml` | API, crawler, scheduler nastavení |
| **Docker overlay** | `config.docker.yaml` | `/app/data`, `/app/.myskin/crawl.db` |
| **Lokální přepsání** | `config.local.yaml` | Specifické pro stroj (gitignored) |

Načítáno přes [yayaya](https://pypi.org/project/yayaya/) (`MYSKIN_CONFIG_FILES=config.yaml,config.docker.yaml` v Dockeru). Viz [§7](#7-crawler-plánovač-a-sitemap) pro všechny klíče crawleru.

### Chování myskin

- Při každém požadavku `/api/documents` skenuje `data_dir` — vždy aktuální
- Interní **APScheduler** spouští crawly (cron nebo interval, řízeno configem)
- Ruční spuštění: `POST /api/crawl/run` (blokující) nebo `POST /api/crawl/start` (na pozadí)
- CLI: `python -m myskin.crawl`
- Live dashboard: `GET /crawl` (Bearer token v prohlížeči)
- Volumes perzistují `data/` a `.myskin/crawl.db` přes restarty kontejneru

**Důležité:** Docker bind-mounty `./data` na hostiteli se **ve výchozím stavu nepoužívají** — data žijí v pojmenovaném volume `myskin_myskin-data` → `/app/data`. Pro inspekci souborů použijte `docker volume inspect` nebo `docker compose exec`.

### Ukázková data

| Soubor | Účel |
|--------|------|
| `data/specs/embedded-bindi-spec.md` | Příklad s plným frontmatter |
| `data/notes/crawling.md` | Příklad minimálního dokumentu |
| `data/crawl/edu-gov-cz/` | Nacrawlované stránky + PDF (po prvním běhu; host slug používá pomlčky) |

### Zatím neimplementováno

- Stránky renderované JavaScriptem (Playwright / Crawl4AI)
- Uchovávání surových PDF binárek v `data/` (pouze extrahovaný text `.md`)

---

## 7. Crawler, plánovač a sitemap

**Stav: implementováno** — běží uvnitř hlavního procesu služby (Docker nebo `uvicorn`).

### Nasazení

```bash
cp .env.example .env          # set MYSKIN_API_TOKEN
docker compose up -d --build
docker compose logs -f myskin
```

### Plánovač (`config.yaml` → `scheduler.*`)

| Klíč | Výchozí | Účel |
|------|---------|------|
| `enabled` | `true` | `false` = pouze manuální/API crawl |
| `cron` | `0 2 * * 0` | 5-polní cron (neděle 02:00 UTC) |
| `interval_hours` / `interval_minutes` | — | Pevný interval (přepíše cron, když je nastaven) |
| `run_on_startup` | `false` | Crawl jednou při startu kontejneru |
| `timezone` | `UTC` | Časová zóna cronu (`Europe/Prague`, …) |

### Crawler (`config.yaml` → `crawler.*`)

| Klíč | Výchozí | Účel |
|------|---------|------|
| `seed_url` | `https://edu.gov.cz/` | Kotva rozsahu (host musí sedět) |
| `max_depth` | `3` | Hloubka sledování odkazů (ignorováno při `sitemap_only: true`) |
| `max_pages` | `1000` | Max **stažených** zdrojů na běh (ne celkový limit) |
| `request_delay` | `2.5` | Sekundy mezi HTTP požadavky |
| `user_agent` | `MyskinCrawler/1.0 …` | Odesíláno u každého požadavku |
| `respect_robots` | `true` | Respektovat `robots.txt` |
| `state_db` | `./.myskin/crawl.db` | SQLite stav crawlu |
| `refresh_known` | `true` | Znovu zařadit všechny známé URL každý běh (**pouze link-crawl režim**) |
| `resume_on_startup` | `true` | Auto-resume po pádu (viz recovery níže) |
| `progress` | `auto` | Terminálové UI: `auto` \| `tty` \| `log` \| `off` |
| `sitemap_url` | — | Sitemap index nebo urlset URL (edu.gov.cz: [sitemap_index.xml](https://edu.gov.cz/sitemap_index.xml)) |
| `sitemap_only` | `true` | Crawlovat pouze URL ze sitemap; nesledovat odkazy `<a>` |

**Produkční config edu.gov.cz** (v repu `config.yaml`):

```yaml
crawler:
  sitemap_url: https://edu.gov.cz/sitemap_index.xml
  sitemap_only: true
  max_pages: 100000
  request_delay: 1.5
```

### Objevování řízené sitemapou

Když je nastaveno `sitemap_url`, crawler:

1. Stáhne sitemap index a **všechny vnořené child sitemapy** (Yoast SEO emituje ~30 souborů: `page-sitemap.xml`, `post-sitemap.xml`, `dlp_document-sitemap.xml`, …).
2. Shromáždí každý `<loc>` s volitelným `<lastmod>`.
3. **Zařadí URL do fronty pouze pokud:**
   - nikdy nebyla nacrawlována, **nebo**
   - `<lastmod>` je **novější** než `last_changed_at` v `crawl.db`
4. Nezměněné URL přeskočí úplně — žádný HTTP fetch, žádná hash kontrola.

| Typ běhu | Očekávané chování |
|----------|-------------------|
| **První běh** | Dlouhý — každá URL ze sitemap je nová |
| **Inkrementální** | Rychlý — do fronty jen změněné stránky |
| **Nic se nezměnilo** | ~30 fetchů sitemap + hotovo (sekundy overheadu, nula stažených stránek) |

Příklad řádku v logu:

```
Sitemap https://edu.gov.cz/sitemap_index.xml: 12000 URLs, 42 queued, 11958 skipped (unchanged)
```

**Fallback:** pokud fetch sitemap vrátí nulu URL, engine přejde na link crawl ze `seed_url` + `refresh_known`.

**Vypnutí sitemap:** odstraňte `sitemap_url` nebo nastavte na `null` — vrátí se BFS objevování odkazů + `refresh_known`.

### Jak funguje jeden crawl běh (žádná samostatná „scrape“ fáze)

**Neexistuje dvoufázový** pipeline crawl-then-scrape. Pro každou URL ve frontě engine udělá vše v jednom průchodu:

1. HTTP fetch (`Fetcher` + rate limit + volitelný `robots.txt`)
2. Extrakce (HTML → markdown přes BeautifulSoup + html2text, nebo PDF → text přes pypdf)
3. Porovnání hashe proti `crawl.db`
4. Zápis `.md` + frontmatter při změně (nebo aktualizace časových razítek v DB, pokud beze změny)
5. Volitelně objev nových odkazů (pouze link-crawl režim)

Řádky logu jako `Updated … -> crawl/edu-gov-cz/pages/foo.md` jsou cesty **relativní k `data_dir`**, ne k cwd vašeho shellu.

### Ochranné mechanismy engine

Postavené během hardeningu v červenci 2026 — vše v `myskin/crawler/engine.py` + `urls.py`:

| Ochrana | Co brání |
|---------|----------|
| **CSS skip** (`is_css_url`) | URL `.css` přeskočeny (query string odstraněn před kontrolou přípony) |
| **Index canonicalization** | `/index`, `/index.html` atd. normalizováno na `/` — vyhýbá se duplicitním smyčkám `index.md` |
| **Frontier URL dedup** (`enqueued_urls`) | Stejná URL nezařazena dvakrát v jednom běhu |
| **Frontier path dedup** (`enqueued_paths`) | Stejná lokální cesta nezařazena pod různými URL |
| **Per-run write guard** (`updated_paths`) | Jakmile je cesta v tomto běhu zapsána, znovu se nestáhne, i když dynamická stránka mění hash |
| **State path lookup** (`get_resource_by_local_path`) | DB dedup podle cesty v souborovém systému, ne jen URL |

Nejvíc záleží v **link-crawl režimu**. Při **sitemap-only** je fronta fixní předem a objevování odkazů je vypnuto.

### Terminálový progress (`crawler.progress`)

| Režim | Chování |
|-------|---------|
| `auto` | V Dockeru/non-TTY se přeloží na `log`; `tty` při připojení k reálnému terminálu |
| `tty` | Split-screen live UI (statistiky nahoře, nedávné události dole) — nejlépe přes `docker attach` / lokální CLI |
| `log` | Jednořádkové periodické souhrny — výchozí v Dockeru |
| `off` | Žádný progress výstup; jen logy engine |

Pro bohaté terminálové UI lokálně:

```bash
python -m myskin.crawl -v
# or force TTY mode in config.yaml: crawler.progress: tty
```

Pro monitoring v Dockeru preferujte **dashboard `/crawl`** — TTY split-screen je v `docker compose logs` nepohodlný.

### Link-crawl režim (legacy / fallback)

Bez `sitemap_url`:

- Začíná na `seed_url`, sleduje odkazy v rozsahu do `max_depth`
- Přeskočí CSS URL (`.css`, varianty s query stringem)
- Kanonizuje `/index`, `/index.html` → `/` kvůli duplicitním cestám
- `refresh_known: true` znovu zařadí každou URL už v `crawl.db` každý běh
- Per-run dedup: frontier sleduje zařazené URL/cesty; cesty aktualizované jednou za běh se znovu nestahují

### Crawler CLI

```bash
docker compose exec myskin python -m myskin.crawl --max-pages 50 -v
```

### Rozložení výstupu

```
data/crawl/<host-slug>/
  pages/<path>.md      # HTML → markdown
  pdfs/<path>.md       # PDF → extracted text
```

Každý soubor má YAML frontmatter: `title`, `source_url`, `category`, `content_hash`, `updated_at`.

### Stav a inkrementální aktualizace

| Mechanismus | Umístění | Chování |
|-------------|----------|---------|
| Content hash | `crawl.db` → `resources` | Přeskočit přepis, když SHA-256 těla beze změny |
| Sitemap `<lastmod>` | sestavení fronty | Přeskočit fetch, když `lastmod ≤ last_changed_at` |
| `updated_at` | frontmatter | HTTP `Last-Modified` nebo čas zápisu → RAGFlow `poll_timestamp_field` |
| 404 handling | state + filesystem | Odstranit zastaralý lokální soubor a řádek DB |
| URL ↔ path dedup | `get_resource_by_local_path` | Stejná cesta souboru nebude zpracována dvakrát pod různými URL |

### Obnova po pádu

Při startu (`crawl_recovery.py`):

1. Každý řádek `crawl_runs` bez `finished_at` je označen jako přerušený.
2. Pokud `resume_on_startup: true` a není naplánován crawl `run_on_startup` → spustí **recovery crawl** (`trigger=recovery`).

### Statistiky crawlu (na běh)

| Pole | Význam |
|------|--------|
| `pages_fetched` / `pdfs_fetched` | Provedené HTTP požadavky |
| `pages_updated` / `pdfs_updated` | Obsah se změnil (soubor přepsán) |
| `pages_unchanged` / `pdfs_unchanged` | Staženo, ale hash seděl |
| `pages_failed` / `pdfs_failed` | HTTP/parse chyby |
| `discovered` | **Sitemap režim:** celkový počet URL v XML. **Link režim:** nově nalezené odkazy |
| `sitemap_urls` | Celkový počet URL parsovaných ze sitemap |
| `sitemap_queued` | URL zařazené v tomto běhu |
| `sitemap_skipped` | Přeskočeno podle `<lastmod>` (beze změny) |

### Znovuspuštění crawlu po změně configu

1. `docker compose up -d` (reload configu po změně `config.yaml`)
2. `POST /api/crawl/run` nebo počkat na plánovač

`max_pages` platí **na běh**, ne jako celoživotní strop korpusu.

### Zatím ne v crawleru

- Stránky renderované JavaScriptem (Playwright / Crawl4AI)
- Uchovávání surových PDF binárek
- Cache per-sitemap-file (každý běh znovu stahuje všechny child sitemapy)
- Paralelní stahování sitemap

---

## 8. Crawl dashboard a live API

UI v prohlížeči na **`GET /crawl`** — jednou zadáte API token (uložen v `localStorage`), poté:

- Spuštění crawlu (`POST /api/crawl/start`)
- Live statistiky seskupené podle **Běh**, **Sitemap**, **Stránky**, **PDF**
- Nedávné události stránek s **klikatelnými source URL** (otevřete neúspěšné stránky v novém tabu pro ověření)
- Graf (Chart.js, **bez animace**): fronta, počet ve sitemap, zpracováno vs. uplynulý čas
  - Aktualizace přes `labels.push` + `data.push` + `chart.update("none")` při každém pollu — okamžité překreslení, bez tweeningu (animované varianty byly vyzkoušeny a odstraněny)

### Live API

| Metoda | Cesta | Auth | Popis |
|--------|-------|------|-------|
| `GET` | `/api/crawl/live` | Bearer | Běžící příznak + live stav, vzorky, události |
| `POST` | `/api/crawl/start` | Bearer | Spustit crawl na pozadí (neblokující) |
| `GET` | `/api/crawl/status` | Bearer | Plánovač + statistiky posledního dokončeného běhu |
| `POST` | `/api/crawl/run` | Bearer | Spustit crawl synchronně (čeká do dokončení) |

### Skupiny statistik dashboardu

| Skupina | Karty |
|---------|-------|
| **Běh** | Zpracováno (% z max), Fronta |
| **Sitemap** | Objeveno (celkem v XML), Ke crawlování, Přeskočeno (beze změny podle lastmod) |
| **Stránky** | Aktualizováno, Beze změny, Selhalo, Staženo |
| **PDF** | Aktualizováno, Beze změny, Selhalo, Staženo |

Graf **„In sitemap“** sleduje `stats.discovered` (= počet URL ve sitemap). Interval pollu: 1,5 s.

### Příklady curl

```bash
# Live state
curl -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/live

# Blocking crawl
curl -X POST -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/run

# Background crawl
curl -X POST -H "Authorization: Bearer $MYSKIN_API_TOKEN" http://localhost:8080/api/crawl/start
```

---

## 9. Referenční nasazení RAGFlow

Z [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md) — server `jbi-sv-01`.

### Předpoklady na hostiteli

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

Použijte **`docker-compose.yml`** (ne `docker-compose-base.yml` samostatně).

### Oprava konfliktu portů (MySQL 3306)

Hostitelský MySQL obsazoval 3306. Možnosti:

1. Zastavit host MySQL: `sudo systemctl stop mysql`
2. Změnit `MYSQL_PORT=3307` v `.env`
3. **Nejlépe:** úplně odstranit expozici portu DB — kontejnery komunikují na interní Docker síti; exponovat jen UI port

### Přístupové URL (naše nasazení)

| Služba | Port | URL |
|--------|------|-----|
| Web UI | **9880** | `http://<host>:9880` |
| API | **9380** | `http://<host>:9380` |

Zkontrolujte živé mapování: `docker compose ps`

První boot trvá minuty (init DB, ES, modely). `curl http://localhost:9880` může resetovat, dokud není ready — počkejte na HTML odpověď.

### Integrace Ollama

Ollama na host portu **15434**:

| Nastavení | Hodnota |
|-----------|---------|
| Base URL | `http://host.docker.internal:15434` nebo LAN IP hostitele |
| API Key | dummy `ollama` (lokální Ollama nemá skutečný klíč) |
| Embedding model | `bge-m3` nebo podobný |
| Chat model | `llama3`, `mistral` atd. |

Pokud `host.docker.internal` selže, přidejte do `docker-compose.yml`:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### RAGFlow API klíč

Settings → API → vygenerovat klíč. Používá se pro `POST /v1/connectors` atd.

### Propojení konektoru s datasetem

1. Vytvořit konektor (UI: Settings → Data Sources → REST API, nebo API)
2. V nastavení datasetu/znalostní báze → propojit datový zdroj
3. Test: `POST /v1/connectors/{id}/test`
4. Rebuild pokud potřeba: `POST /v1/connectors/{id}/rebuild` s `{ "kb_id": "..." }`

---

## 10. Specifikace REST API konektoru RAGFlow

Zdroj: RAGFlow `common/data_source/rest_api_connector.py` ([PR #13545](https://github.com/infiniflow/ragflow/pull/13545)).

RAGFlow polluje váš endpoint, očekává **JSON**, extrahuje pole **objektů**, mapuje pole → `Document` (vždy uloženo jako `.txt`).

### UI formulář → `config` JSON

| UI pole | Config klíč |
|---------|-------------|
| Base URL | `url` |
| HTTP Method | `method` (`GET` nebo `POST`) |
| Query Parameters | `query_params` (dict nebo řádky `key=value`) |
| Items Path | `items_path` (JSONPath, např. `$.items`) |
| ID Field | `id_field` |
| Auth Type | `auth_type`: `none`, `api_key_header`, `bearer`, `basic` |
| Content Fields | `content_fields` (**povinné**, čárkou oddělené) |
| Metadata Fields | `metadata_fields` |
| Pagination Type | `pagination_type`: `none`, `page`, `offset`, `cursor` |
| Custom Headers | `headers` (JSON) |
| Max Pages | `max_pages` (výchozí 1000) |
| Request Delay | `request_delay` sekundy (výchozí 0.5) |
| Poll Timestamp Field | `poll_timestamp_field` |
| Request Body | `request_body` (pouze POST) |

### Konfigurace stránkování (`pagination_config`)

| Typ | Klíče | Výchozí |
|-----|-------|---------|
| `page` | `start_page`, `page_param`, `page_size_param`, `page_size` | `page` |
| `offset` | `start_offset`, `offset_param`, `limit_param`, `limit` | `offset`, `limit` |
| `cursor` | `cursor_param`, `initial_cursor`, `next_cursor_path` | `cursor` |

### Extrakce položek

1. Pokud je nastaveno `items_path` → JSONPath (např. `$.items`)
2. Jinak auto-detekce prvního seznamu pod: `items`, `results`, `data`, `records`, nebo první list hodnota v odpovědi
3. Každá položka musí být **JSON objekt** (`dict`)

### Syntaxe cest polí

Tečková notace s volitelnými indexy polí:

- `title`
- `meta.author`
- `tags[0].name`
- `tags[*].name` (wildcardy spojené `, `)

### Mapování dokumentů

- `id` = `hash128("rest_api:" + id_field_value)` — stabilní `id_field` kritické pro aktualizace
- Content = spojení hodnot `content_fields` (HTML odstraněno) NEBO `content_template`
- `doc_updated_at` z `poll_timestamp_field` (ISO 8601, unix, běžné formáty dat)
- Inkrementální sync: bez `poll_timestamp_field` plné znovunačtení + filtr v paměti

### SSRF omezení (důležité)

RAGFlow **blokuje** URL, které se resolvují na:

- `localhost`
- Soukromé IP (`10.x`, `192.168.x` atd.)
- Link-local, reserved, multicast

**myskin musí být dosažitelný na veřejném hostname**, aby se RAGFlow mohl připojit. Pro lokální vývoj použijte ngrok / Cloudflare Tunnel.

### Vytvoření konektoru přes API

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

### Poznámka k PDF URL v content polích

Raný výzkum naznačoval, že RAGFlow může stahovat `.pdf` URL z content polí. Skutečná implementace konektoru `rest_api` **převádí hodnoty polí na text** — **nestahuje** binární URL. **Předextrahujte text z PDF v crawleru** a zapište `.md` do `data/`.

### Jeden myskin server vs. více znalostních bází RAGFlow

**RAGFlow** podporuje mnoho konektorů a mnoho datasetů/KB — není limit jeden datový zdroj na server.

**myskin (dnes)** vystavuje **jeden sjednocený katalog**: `GET /api/documents` projde celé `data/` rekurzivně. Jeden config crawleru → jeden `seed_url` / `sitemap_url`.

| Cíl | Přístup |
|-----|---------|
| **Jedna KB, veškerý obsah** | Jeden myskin + jeden konektor `rest_api` (současné nastavení edu.gov.cz) |
| **Více KB, jeden host** | Není vestavěné — potřeba API filtrů (`path_prefix`, `category`) a více RAGFlow konektorů s různými `query_params` |
| **Více webů** | Více myskin kontejnerů (různé porty/volumes/configy) nebo sloučení všeho do jednoho stromu `data/` |
| **Stejná data ve dvou KB** | Dva konektory na stejné plné `/api/documents` — funguje, ale duplikuje embedding práci |

Konektor RAGFlow podporuje `query_params`; budoucí rozšíření myskin by mohlo rozdělit katalog per dataset bez více kontejnerů.

---

## 11. API kontrakt myskin

### Endpointy

| Metoda | Cesta | Auth | Popis |
|--------|-------|------|-------|
| `GET` | `/health` | Ne | Stav, počet dokumentů, příznaky scheduler/crawl |
| `GET` | `/docs` | Ne | OpenAPI (Swagger) |
| `GET` | `/api/documents` | Bearer | Stránkovaný katalog pro RAGFlow |
| `GET` | `/api/documents/{id}` | Bearer | Jeden dokument |
| `GET` | `/crawl` | Ne | HTML crawl dashboard (token zadaný v UI) |
| `GET` | `/api/crawl/live` | Bearer | Live stav crawlu + vzorky grafu |
| `GET` | `/api/crawl/status` | Bearer | Plánovač + poslední dokončený běh |
| `POST` | `/api/crawl/run` | Bearer | Blokující crawl (čeká na dokončení) |
| `POST` | `/api/crawl/start` | Bearer | Crawl na pozadí |

### Autentizace (Bearer)

Chráněné routy očekávají:

```http
Authorization: Bearer <MYSKIN_API_TOKEN>
```

Token je pouze v `.env`. Prázdný token = auth vypnuto (v produkci nedoporučeno).

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

HTML dashboard `/crawl` je bez autentizace; token vložíte v UI (uložen v `localStorage` prohlížeče).

### Query parametry (`/api/documents`)

| Param | Výchozí | Popis |
|-------|---------|-------|
| `offset` | 0 | Offset stránkování (RAGFlow offset režim) |
| `limit` | 50 | Velikost stránky (max 500) |
| `updated_since` | — | Volitelný ISO filtr (rozšíření myskin, RAGFlow konektor nepoužívá) |

### Tvar odpovědi

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

### Konfigurace

| Zdroj | Účel |
|-------|------|
| `config.yaml` | API host/port, `data_dir`, crawler, scheduler |
| `config.docker.yaml` | Docker path overrides (`MYSKIN_CONFIG_FILES`) |
| `config.local.yaml` | Volitelná lokální přepsání (kopie z `config.local.yaml.example`, gitignored) |
| `.env` | **Pouze `MYSKIN_API_TOKEN`** (tajemství) |

Config se čte **jednou při startu procesu**. Po úpravě `config.yaml` restart: `docker compose up -d` (nebo `--build` při změně kódu).

API bind host/port: `config.yaml` → `api.host`, `api.port` (výchozí `0.0.0.0:8080`).

### Lokální spuštění

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn myskin.main:app --host 0.0.0.0 --port 8080
```

---

## 12. Strategie web scrapingu

### Obecné principy

1. **Zkontrolujte robots.txt a ToS** před crawlem — i s technickým povolením může být komerční reuse omezen
2. **Rate limit** — 2–3 s mezi požadavky pro vládní servery
3. **Transparentní User-Agent** — např. `EduGovKnowledgeBot/1.0 (contact@yourdomain.com)`
4. **Inkrementální aktualizace** — přeskočení sitemap `<lastmod>` + content hash pro stažené stránky
5. **Idempotentní výstup** — stabilní cesty souborů → stabilní myskin ID → RAGFlow upsert, ne duplikát

### Strategie sitemap-first (edu.gov.cz)

Yoast SEO publikuje [sitemap_index.xml](https://edu.gov.cz/sitemap_index.xml) s child sitemapami per typ obsahu (`page-sitemap.xml`, `post-sitemap.xml`, `dlp_document-sitemap.xml`, …). Každý záznam URL obsahuje `<lastmod>`.

**Preferujte sitemap před link crawlingem** pro velké vládní weby:

| Přístup | První běh | Inkrementální běh |
|---------|-----------|-------------------|
| Link crawl + `refresh_known` | Hodiny — znovu navštíví celou známou množinu | Hodiny |
| **Sitemap + lastmod** | Hodiny — všechny URL nové | Minuty — jen změněné URL |

Nastavte v `config.yaml` — viz [§7](#7-crawler-plánovač-a-sitemap).

### Specifika edu.gov.cz

- Centrální uzel pro školní legislativu, metodiku, Infoservis
- Silné využití **vnořených PDF příloh**
- Obsah se mění periodicky (měsíční bulletiny) — **týdenní crawl** stačí
- `robots.txt` povoluje scraping (dle výzkumu projektu)

### Firecrawl a robots.txt (kontext jiného klienta)

Z [convos/Bypassing-Firecrawl's-Robots.txt-Check.md](../convos/Bypassing-Firecrawl's-Robots.txt-Check.md):

Použito s **Dify** knowledge sync + self-hosted Firecrawl, když smlouva klienta povoluje scraping, ale `robots.txt` nelze změnit.

| Přístup | Poznámky |
|---------|----------|
| Cloud Firecrawl | Nelze vypnout robots.txt |
| Self-hosted `SKIP_ROBOTS_TXT_CHECK=true` | Tvrdí env; ověřte ve vaší verzi Firecrawl |
| Per-request `ignoreRobotsTxt: true` | V `crawlerOptions` / `scrapeOptions` |
| Dify integrace | Nelze poslat vlastní hlavičky/opce — potřeba globální env, proxy nebo Dify fork |
| Kong/reverse proxy | Injektovat `ignoreRobotsTxt` do JSON těla |
| Dify fork | Přidat UI toggle → `website_service.py` → Firecrawl payload |

**Nepřímo použitelné pro edu.gov.cz** (robots.txt crawlování povoluje), ale dokumentuje znalosti nástrojů pro jiné cíle.

### Dify fork workflow (pokud by bylo potřeba)

Z konverzace — pro udržení vlastních změn Dify přes upstream aktualizace:

- **Git stash** — rychlé a špinavé
- **Git patch** — `git diff > feature.patch` pak `git apply` po pull
- **Fork + feature branches** — `feature/robots-bypass` pro PR, `production-custom` pro sloučení všech lokálních feature

Tip na PR: formulovat jako „Advanced Crawler Options (JSON)“, ne „Ignore robots.txt“ — maintaineři explicitní bypass toggle pravděpodobně nesloučí.

---

## 13. Cílový web: edu.gov.cz

### Konfigurace crawlu (produkce)

| Nastavení | Hodnota |
|-----------|---------|
| Seed URL | `https://edu.gov.cz/` |
| Sitemap | `https://edu.gov.cz/sitemap_index.xml` |
| `sitemap_only` | `true` |
| `max_pages` | `100000` (strop fetchů na běh) |
| Delay | `1.5` s mezi požadavky |
| PDF | Stažení + extrakce textu do `.md` (vč. `dlp_document-sitemap.xml`) |
| Plán | Týdně (neděle 02:00 UTC) |

**První běh:** očekávejte dlouhý počáteční crawl — všechny URL ze sitemap jsou ve frontě.  
**Další běhy:** pouze stránky s novějším `<lastmod>` než `last_changed_at` v `crawl.db`.

### Obsah sitemap indexu (reference)

Index uvádí ~30 child sitemap včetně: `page-sitemap.xml`, `post-sitemap.xml`, `job_listing-sitemap.xml`, `metodicky_materialy-sitemap.xml`, `dlp_document-sitemap.xml`, `tribe_events-sitemap.xml`, taxonomické sitemapy (`category-sitemap.xml`, …). Taxonomické/autor URL se crawluje, pokud jsou v rozsahu; největší hodnota je v záznamech `page`, `post` a `dlp_document`.

### Kategorie obsahu (doporučený frontmatter `category`)

- `legislation`
- `methodology`
- `infoservis`
- `pdf`
- `news`

### Chunking v RAGFlow

Konfigurace datasetu → **General** chunk method — používá DeepDoc pro layout-aware chunking webového markdownu i textu extrahovaného z PDF.

---

## 14. Historie hodnocení nástrojů

| Nástroj | Self-hosted | PDF | Auto-update | Komerční | Výsledek |
|---------|-------------|-----|-------------|----------|----------|
| Vectorize.io | Ne (SaaS) | ? | Ano | ? | Odmítnuto — není self-hosted |
| Cloudflare AutoRAG | CF platform | Ano | Ano | Ano | Odmítnuto — není plně self-hosted |
| LangChain + Firecrawl | Částečně | Přes Firecrawl | Cron | Ano | Odloženo |
| **RAGFlow** | Ano | DeepDoc | Connector sync | Apache 2.0 | **Vybráno** |
| Dify + Crawl4AI | Ano | Crawl4AI | Cron | Ano | Alternativa; nezvoleno pro edu.gov |
| Langflow + Crawl4AI | Ano | Ano | Cron | Ano | Alternativa |
| RSS feed jako datový zdroj | Ano | Enclosure tagy | Poll | Ano | Hack; nezvoleno |
| Push upload API | Ano | Ano | Skript | Ano | Funguje; push ne pull |
| **myskin + rest_api** | Ano | Přes crawler→md | Poll | Ano | **Vybraná architektura** |
| Chroma HttpClient | Ano | N/A | N/A | Apache 2.0 | Prozkoumáno jen pro vzdálené vektory — viz [convos/Serving-Chroma-Vector-Store-Remotely.md](../convos/Serving-Chroma-Vector-Store-Remotely.md) |

### Poznámka k Chroma

Chroma `HttpClient` může servírovat více kolekcí ze vzdáleného stroje. Užitečné, pokud bychom někdy oddělili embedding/retrieval od app serveru. **RAGFlow spravuje vlastní vektorové úložiště** (Elasticsearch/Infinity) — Chroma není součástí tohoto pipeline, pokud nepostavíme samostatnou aplikaci dotazující Chroma přímo.

---

## 15. Právní otázky a compliance

| Téma | Doporučení |
|------|------------|
| Licence RAGFlow | Apache 2.0 — komerční použití OK |
| myskin | TBD (nastavit před produkcí) |
| Scrapovaný obsah | Ověřit ToS webu + copyright pro komerční chatbot |
| edu.gov.cz | robots.txt povoluje crawling dle naší kontroly; potvrdit ToS pro komerční reuse |
| Jiní klienti | Smluvní povolení scrapingu může existovat i když robots.txt blokuje — řešit per web, dokumentovat písemně |
| PII | Vládní vzdělávací dokumenty — zkontrolovat osobní údaje před indexací |

---

## 16. Provozní postupy

### Nasazení myskin

1. Klonovat repo, `cp .env.example .env`, nastavit `MYSKIN_API_TOKEN`
2. Vyladit `config.yaml` (crawler sitemap, scheduler, delay)
3. `docker compose up -d --build`
4. Spustit za reverse proxy s TLS (Caddy, nginx, Traefik)
5. Exponovat **veřejné** URL pro RAGFlow (ne localhost)
6. Otevřít `https://<host>/crawl` pro monitoring crawlů

### Umístění dat v Dockeru

| Co | Kde |
|----|-----|
| Nacrawlovaný markdown | Volume `myskin_myskin-data` → `/app/data` |
| DB stavu crawlu | Volume `myskin_myskin-state` → `/app/.myskin/crawl.db` |
| Config | Zapečený v image + env `MYSKIN_CONFIG_FILES` |

Inspekce dat: `docker compose exec myskin ls /app/data/crawl/`

Čtení nacrawlovaného souboru z kontejneru:

```bash
docker compose exec myskin cat /app/data/crawl/edu-gov-cz/pages/index.md | head
```

Kopie volume na host (záloha):

```bash
docker compose exec myskin tar -C /app/data -czf - crawl | tar -xzf - -C ./backup-data
```

### Znovuspuštění crawlu po změně configu

1. Upravit `config.yaml` (nebo `config.local.yaml`)
2. `docker compose up -d` — reload configu
3. `POST /api/crawl/run` nebo počkat na plánovač

Změny tokenu v `.env` také vyžadují restart kontejneru.

### Registrace RAGFlow konektoru

Viz [§10](#10-specifikace-rest-api-konektoru-ragflow) a [README](../README.md).

### Ověření end-to-end

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

### Aktualizace obsahu

1. Plánovač nebo `POST /api/crawl/run` → crawler zapisuje/aktualizuje `data/`
2. Sitemap režim přeskočí nezměněné URL před HTTP fetchem
3. myskin načte změny při dalším požadavku `/api/documents`
4. RAGFlow polluje dle `refresh_freq` → znovu embeduje změněné dokumenty přes `poll_timestamp_field`

### Monitoring crawlu

- Dashboard: `GET /crawl` (uložit API token v UI)
- API: `GET /api/crawl/live`
- Logy: `docker compose logs -f myskin`

### Plná reindexace

`POST /v1/connectors/{id}/rebuild` s `{ "kb_id": "<dataset-id>" }`

---

## 17. Řešení problémů

| Příznak | Pravděpodobná příčina | Oprava |
|---------|----------------------|--------|
| Test RAGFlow konektoru selže | myskin na localhost/soukromé IP | Veřejné URL nebo tunel |
| RAGFlow 401 od myskin | Neshoda tokenu | Sjednotit `MYSKIN_API_TOKEN` a `credentials.token` konektoru |
| myskin 401 na `/api/documents` | Chybí hlavička `Authorization` | `curl -H "Authorization: Bearer $TOKEN" …` |
| Cesta v logu nenalezena na hostiteli | Cesta je relativní k `data_dir` uvnitř kontejneru | Použít `docker compose exec myskin cat /app/data/…` |
| Opakované `[page] unchanged index.md` | Aliasy index URL (opraveno) | Aktualizovat na build s index canonicalization |
| Fronta nafukuje na cyklických odkazech | Link-crawl bez frontier dedup (opraveno) | Aktualizovat; nebo `sitemap_only: true` |
| Stejná stránka se stahuje každý běh | Dynamický obsah / anti-bot (opraveno) | Ochrana `updated_paths` na běh |
| Prázdné `items` v RAGFlow | Špatné `items_path` | Pro myskin použít `$.items` |
| Duplicitní dokumenty | Chybějící/nestabilní `id_field` | Zajistit stabilní cesty crawleru → stabilní myskin `id` |
| Žádné inkrementální aktualizace | Chybí `poll_timestamp_field` | Nastavit na `updated_at` |
| PDF nejsou indexována | PDF v `data/` není podporováno | Crawler musí extrahovat text do `.md` |
| RAGFlow UI connection reset | Stále bootuje | Počkat, zkontrolovat `docker compose logs -f ragflow-cpu` |
| Chyba bind MySQL portu | Host MySQL na 3306 | Změnit port nebo neexponovat DB |
| Selhání připojení Ollama z Dockeru | Síť | `host.docker.internal` nebo LAN IP + `extra_hosts` |
| Firecrawl blokován robots (jiné projekty) | Dify neposílá bypass flag | Env var, proxy nebo Dify fork |
| Crawl trvá věčně každý týden | Link crawl + `refresh_known` | Zapnout `sitemap_url` + `sitemap_only` |
| Inkrementální crawl stále pomalý | Overhead sitemap (~30 XML fetchů) | Normální; fetchů stránek by mělo být málo |
| Dashboard ukazuje 0 discovered | Běh začal před načtením sitemap | Počkat na sestavení fronty; zkontrolovat logy |
| `409 Crawl already in progress` | Překrývající se triggery | Počkat nebo `/api/crawl/start` jednou |
| Data nejsou na host `./data` | Pojmenovaný Docker volume | `docker volume inspect myskin_myskin-data` |
| Recovery crawl při každém bootu | Přerušený předchozí běh | Nechat doběhnout; nebo `resume_on_startup: false` |

---

## 18. Deník rozhodnutí

| Datum | Rozhodnutí | Zdůvodnění |
|-------|------------|------------|
| 2026-06-29 | Cílit na RAGFlow místo Dify/Langflow pro edu.gov KB | Self-hosted, DeepDoc PDF, Apache 2.0, systém konektorů |
| 2026-06-29 | Použít konektor `rest_api`, ne upload API | Pull-based sync jako nativní datové zdroje |
| 2026-06-29 | Postavit myskin jako tenkou katalogovou vrstvu | RAGFlow UI postrádalo web crawler; oddělit scraping chaos od RAG |
| 2026-06-29 | FastAPI + filesystem `data/` | Jednoduché, laditelné, crawler zapisuje soubory, myskin servíruje JSON |
| 2026-06-29 | Text v `data/`, ne surová PDF | Konektor `rest_api` mapuje pouze textová pole |
| 2026-07-01 | Sitemap-first crawl pro edu.gov.cz | `lastmod` přeskočí nezměněné URL; inkrementální běhy za minuty, ne hodiny |
| 2026-07-01 | `config.yaml` + yayaya pro nastavení | Ne-tajemství v gitu; `.env` pouze pro token |
| 2026-07-01 | Live crawl dashboard na `/crawl` | Seskupené statistiky, graf, počty sitemap skipped/queued |
| 2026-07-01 | Chart.js: bez animace | Animované aktualizace způsobovaly skákání čar; okamžité `update("none")` |
| 2026-07-01 | Hardening frontier crawleru | CSS skip, index canonicalization, ochrany proti cyklům a přepisům na běh |
| 2026-07-01 | Recovery crawl po pádu | `resume_on_startup` + `crawl_recovery.py` |
| 2026-07-07 | Dokumentace multi-KB topologie | Jeden myskin = jeden katalog; více RAGFlow KB potřebuje filtry nebo více instancí |
| 2026-06-21 | Firecrawl robots bypass přes env/fork/proxy | Zdokumentováno pro Dify klientskou práci; pro edu.gov.cz není potřeba |
| 2026-05-21 | Chroma HttpClient pro vzdálené vektory | Prozkoumáno; ortogonální k ingest cestě RAGFlow |

---

## 19. Zdrojové materiály (archivované konverzace)

Původní AI konverzace zachované jako důkaz výzkumu a rozhodnutí:

| Soubor | Témata |
|--------|--------|
| [convos/Automated-Web-Scraping-and-Retrieval-Tools.md](../convos/Automated-Web-Scraping-and-Retrieval-Tools.md) | Výběr nástrojů, nastavení RAGFlow, Docker porty, Ollama, plán crawlu edu.gov.cz, spec REST API konektoru, push vs pull architektura |
| [convos/Bypassing-Firecrawl's-Robots.txt-Check.md](../convos/Bypassing-Firecrawl's-Robots.txt-Check.md) | Self-hosted Firecrawl, limity Dify integrace, strategie obcházení robots.txt, fork/patch workflow |
| [convos/Serving-Chroma-Vector-Store-Remotely.md](../convos/Serving-Chroma-Vector-Store-Remotely.md) | Chroma HttpClient, multi-collection, vzdálené servírování vektorů (prozkoumáno, neadoptováno) |

Externí reference:

- [RAGFlow — Data Source Connectors (DeepWiki)](https://deepwiki.com/infiniflow/ragflow/6.6-data-source-connectors)
- [RAGFlow — Generic REST API connector PR #13545](https://github.com/infiniflow/ragflow/pull/13545)
- [RAGFlow GitHub](https://github.com/infiniflow/ragflow)
- [Cílový web: edu.gov.cz](https://edu.gov.cz/)
- [edu.gov.cz sitemap index](https://edu.gov.cz/sitemap_index.xml)

### Cursor implementační session (2026-07)

Interaktivní přepis vývoje pro práci crawler/dashboard/sitemap (Cursor agent chat, červenec 2026). Použijte vedle této příručky pro **proč** byly opraveny konkrétní edge cases.

Témata v té session: Bearer auth a curl, Docker volume vs host `./data`, per-run `max_pages`, terminálový progress → HTML dashboard, iterace Chart.js (animace odstraněny), smyčka duplicitního index.md, prevence cyklů ve frontě, ochrana přepisu na běh, rozdělení YAML/yayaya config, inkrementální crawl sitemap `lastmod`, skupiny statistik dashboardu, otázka multi-RAGFlow-KB.

---

## 20. Poznámky ze sessions implementace (2026-07)

Chronologický log toho, co bylo postaveno a rozhodnuto během implementační session v červenci 2026 (Cursor chat). Odkazuje na dřívější výzkum v `convos/` a sekce výše.

| Kdy | Téma | Výsledek | Příručka |
|-----|------|----------|----------|
| Začátek | API auth | Bearer token na chráněných routách; `/health` a `/docs` veřejné | [§11](#11-api-kontrakt-myskin) |
| Začátek | Znovuspuštění crawlu | Restart kontejneru po změně configu; `POST /api/crawl/run` | [§16](#16-provozní-postupy) |
| Začátek | Kde je `data/`? | Docker pojmenovaný volume `myskin_myskin-data`, ne host `./data` | [§6](#6-co-je-dnes-postaveno), [§16](#16-provozní-postupy) |
| Začátek | Rozsah `max_pages` | Strop fetchů na běh, ne celoživotní limit korpusu | [§7](#7-crawler-plánovač-a-sitemap) |
| Střed | Terminálový progress | `progress.py` tty/log režimy; v Dockeru preferován dashboard | [§7](#7-crawler-plánovač-a-sitemap), [§8](#8-crawl-dashboard-a-live-api) |
| Střed | CSS poisoning | Přeskočit URL `.css` (ignorovat query string) | [§7](#7-crawler-plánovač-a-sitemap) |
| Střed | Obnova po pádu | Přerušit nedokončené běhy; volitelný recovery crawl při startu | [§7](#7-crawler-plánovač-a-sitemap) |
| Střed | Smyčka `index.md` | Kanonizovat `/index` → `/` | [§7](#7-crawler-plánovač-a-sitemap), [§17](#17-řešení-problémů) |
| Střed | Cykly ve frontě | Frontier `enqueued_urls` / `enqueued_paths` | [§7](#7-crawler-plánovač-a-sitemap) |
| Střed | Spam dynamických stránek | `updated_paths` — žádný druhý zápis stejné cesty za běh | [§7](#7-crawler-plánovač-a-sitemap) |
| Střed | Události dashboardu | Klikatelné URL v seznamu nedávných stránek | [§8](#8-crawl-dashboard-a-live-api) |
| Střed | YAML config | `config.yaml` + yayaya; `.env` pouze tajemství | [§6](#6-co-je-dnes-postaveno), [§11](#11-api-kontrakt-myskin) |
| Pozdě | Sitemap crawl | `sitemap_index.xml` + `<lastmod>` vs `last_changed_at` | [§7](#7-crawler-plánovač-a-sitemap), [§13](#13-cílový-web-edugovcz) |
| Pozdě | Facelift dashboardu | Seskupené statistiky; `discovered` = počet URL ve sitemap; `sitemap_skipped` | [§8](#8-crawl-dashboard-a-live-api) |
| Pozdě | Animace grafu | Vyzkoušeny push/animate vzory; **nasazeno s `animation: false`** | [§8](#8-crawl-dashboard-a-live-api) |
| Pozdě | Otázka multi-KB | Jeden myskin = jeden katalog; více RAGFlow KB potřebuje návrh | [§10](#10-specifikace-rest-api-konektoru-ragflow) |

### Reference: prior art

Live chart UX bylo porovnáno s osobním Chart.js demem a `sensorV3Website` (`mdetector.php` — plná náhrada snapshotu + `animation: false`). Dashboard myskin používá inkrementální `push` + `update("none")` pro stejnou stabilitu bez tweeningu.

---

## Příloha: pojmenování

| Název | Význam |
|-------|--------|
| **myskin** | Název repa/služby; slovní hříčka crawling + embedding |
| **data/** | Přistávací zóna pro nacrawlované předzpracované dokumenty |
| **rest_api** | Řetězec typu konektoru RAGFlow (`source: "rest_api"`) |
| **jbi-sv-01** | Hostname serveru, kde běží RAGFlow v0.26.2 (z konverzací) |

---

*Při změně deployment URL nebo chování crawlu aktualizujte §7–§8, §13, §16 a §20. Pro architektonické změny přidávejte záznamy do deníku rozhodnutí.*
