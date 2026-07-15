from datetime import datetime

from pydantic import BaseModel, Field


class DocumentItem(BaseModel):
    id: str
    title: str
    updated_at: datetime
    author: str = "myskin"
    category: str = "general"
    format: str = Field(default="md", description="File format (md, pdf, docx, …)")
    filename: str = Field(default="", description="On-disk filename with extension")
    mime_type: str = Field(default="application/octet-stream")
    source_url: str | None = Field(
        default=None,
        description="Original crawled URL (for RAG citations)",
    )
    file_url: str | None = Field(
        default=None,
        description="Download URL for the file (requires api.public_base_url)",
    )


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int = Field(description="Total documents across all pages")


class HealthResponse(BaseModel):
    status: str
    document_count: int
    data_dir: str
    catalog_by_format: dict[str, int] = Field(default_factory=dict)
    catalog_passthrough_count: int = 0
    catalog_with_file_url: int = 0
    passthrough_enabled: bool | None = None
    passthrough_extensions: list[str] | None = None
    sitemap_only: bool | None = None
    follow_file_links: bool | None = None
    public_base_url: str | None = None
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
    files_discovered: int = 0
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


class CrawlLiveQueueItemModel(BaseModel):
    url: str
    label: str
    kind: str
    depth: int


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
    queue_tail: list[CrawlLiveQueueItemModel] = Field(default_factory=list)


class CrawlLiveResponse(BaseModel):
    running: bool
    live: CrawlLiveStateModel
    scheduler_enabled: bool
    schedule: str
    next_run_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_error: str | None = None
