from datetime import datetime

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    id: str
    title: str
    body: str
    updated_at: datetime
    author: str = "myskin"
    category: str = "general"


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int = Field(description="Total documents across all pages")


class HealthResponse(BaseModel):
    status: str
    document_count: int
    data_dir: str
    crawl_resources: int | None = None
    scheduler_enabled: bool | None = None
    crawl_running: bool | None = None


class CrawlStatsModel(BaseModel):
    pages_fetched: int = 0
    pdfs_fetched: int = 0
    pages_updated: int = 0
    pdfs_updated: int = 0
    pages_unchanged: int = 0
    pdfs_unchanged: int = 0
    pages_failed: int = 0
    pdfs_failed: int = 0
    discovered: int = 0
    sitemap_urls: int = 0
    sitemap_queued: int = 0
    sitemap_skipped: int = 0


class CrawlStatusResponse(BaseModel):
    running: bool
    scheduler_enabled: bool
    schedule_mode: str
    schedule: str
    next_run_at: datetime | None = None
    last_run_id: int | None = None
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_trigger: str | None = None
    last_error: str | None = None
    last_stats: CrawlStatsModel | None = None


class CrawlTriggerResponse(BaseModel):
    status: str
    message: str
    run_id: int | None = None


class CrawlLiveSampleModel(BaseModel):
    elapsed_s: float
    queue: int
    discovered: int
    processed: int


class CrawlLiveEventModel(BaseModel):
    at: datetime
    kind: str
    outcome: str
    label: str
    url: str


class CrawlLiveStateModel(BaseModel):
    active: bool
    run_id: int | None = None
    seed_url: str = ""
    trigger: str = ""
    max_pages: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_pending: int = 0
    stats: CrawlStatsModel = Field(default_factory=CrawlStatsModel)
    samples: list[CrawlLiveSampleModel] = Field(default_factory=list)
    events: list[CrawlLiveEventModel] = Field(default_factory=list)


class CrawlLiveResponse(BaseModel):
    running: bool
    live: CrawlLiveStateModel
    scheduler_enabled: bool
    schedule: str
    next_run_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error: str | None = None
