from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, HTMLResponse

from myskin.admin import load_admin_html, resolve_admin_static_file
from myskin.auth import require_token
from myskin.catalog import catalog_stats, resolve_document_path, scan_documents
from myskin.config import settings
from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.crawler.live import crawl_live
from myskin.crawler.state import CrawlState
from myskin.dashboard import (
    apple_touch_icon_path,
    brand_logo_path,
    favicon_path,
    load_dashboard_html,
    resolve_brand_static_file,
    resolve_crawl_static_file,
)
from myskin.formats import guess_mime_type
from myskin.models import (
    CrawlLiveEventModel,
    CrawlLiveQueueItemModel,
    CrawlLiveResponse,
    CrawlLiveSampleModel,
    CrawlLiveStateModel,
    CrawlStatsModel,
    CrawlStatusResponse,
    CrawlTriggerResponse,
    HealthResponse,
    SiteCreateRequest,
    SiteDetailResponse,
    SiteListResponse,
    SiteSummaryModel,
    SiteUpdateRequest,
)
from myskin.ragflow_sync import sync_site_to_ragflow
from myskin.scheduler import get_next_run_at, reload_scheduler
from myskin.sites.models import SiteRecord
from myskin.sites.service import site_service

router = APIRouter()

_CRAWL_STATIC_MEDIA = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}
_ADMIN_STATIC_MEDIA = _CRAWL_STATIC_MEDIA
_BRAND_STATIC_MEDIA = {
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _site_summary(site: SiteRecord) -> SiteSummaryModel:
    data_dir = site_service.data_dir_for(site)
    docs = scan_documents(
        data_dir=data_dir,
        file_url_builder=lambda doc_id: site_service.file_url_for(site, doc_id),
    )
    sched = site_service.scheduler_settings_for(site)
    ragflow = site_service.ragflow_settings_for(site)
    snapshot = crawl_runner.snapshot_for(site.site_id)
    return SiteSummaryModel(
        site_id=site.site_id,
        name=site.name,
        enabled=site.enabled,
        seed_url=site.seed_url,
        public_base_url=site.public_base_url,
        document_count=len(docs),
        crawl_running=crawl_runner.running and crawl_runner.running_site_id == site.site_id,
        scheduler_enabled=sched.enabled,
        schedule=sched.schedule_description,
        next_run_at=get_next_run_at(site.site_id),
        ragflow_enabled=ragflow.enabled,
        ragflow_dataset_id=ragflow.dataset_id,
        last_crawl_finished_at=snapshot.finished_at if snapshot else None,
        last_crawl_error=snapshot.error if snapshot else None,
    )


def _site_detail(site: SiteRecord) -> SiteDetailResponse:
    return SiteDetailResponse(
        site_id=site.site_id,
        name=site.name,
        enabled=site.enabled,
        public_base_url=site.public_base_url,
        crawler=site.crawler,
        scheduler=site.scheduler,
        ragflow=site.ragflow,
        created_at=site.created_at,
        updated_at=site.updated_at,
    )


def _resolve_site_or_404(site_id: str) -> SiteRecord:
    site = site_service.get_site(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


def _build_crawl_status(site: SiteRecord) -> CrawlStatusResponse:
    snap = crawl_runner.snapshot_for(site.site_id) or crawl_runner.last_snapshot
    stats = None
    if snap and snap.stats is not None:
        stats = CrawlStatsModel(**snap.stats.__dict__)
    sched = site_service.scheduler_settings_for(site)

    return CrawlStatusResponse(
        running=crawl_runner.running and crawl_runner.running_site_id == site.site_id,
        scheduler_enabled=sched.enabled,
        schedule_mode=sched.mode,
        schedule=sched.schedule_description,
        next_run_at=get_next_run_at(site.site_id),
        last_run_id=snap.run_id if snap else None,
        last_started_at=snap.started_at if snap else None,
        last_finished_at=snap.finished_at if snap else None,
        last_trigger=snap.trigger if snap else None,
        last_error=snap.error if snap else None,
        last_stats=stats,
    )


def _build_live_state() -> CrawlLiveStateModel:
    data = crawl_live.to_dict()
    stats = data["stats"]
    return CrawlLiveStateModel(
        active=data["active"],
        run_id=data["run_id"],
        seed_url=data["seed_url"],
        trigger=data["trigger"],
        max_pages=data["max_pages"],
        started_at=data["started_at"],
        finished_at=data["finished_at"],
        queue_pending=data["queue_pending"],
        stats=CrawlStatsModel(**stats.__dict__),
        samples=[CrawlLiveSampleModel(**s.__dict__) for s in data["samples"]],
        events=[
            CrawlLiveEventModel(
                at=e.at,
                kind=e.kind,
                outcome=e.outcome,
                label=e.label,
                url=e.url,
            )
            for e in data["events"]
        ],
        queue_tail=[
            CrawlLiveQueueItemModel(
                url=item.url,
                label=item.label,
                kind=item.kind,
                depth=item.depth,
            )
            for item in data["queue_tail"]
        ],
    )


@router.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    icon = favicon_path()
    if not icon.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(icon, media_type="image/x-icon")


@router.get("/static/brand/myskin-logo.png", include_in_schema=False)
async def brand_logo() -> FileResponse:
    logo = brand_logo_path()
    if not logo.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(logo, media_type="image/png")


@router.get("/static/brand/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon() -> FileResponse:
    icon = apple_touch_icon_path()
    if not icon.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return FileResponse(icon, media_type="image/png")


@router.get("/static/brand/{asset_name}", include_in_schema=False)
async def brand_static(asset_name: str) -> FileResponse:
    path = resolve_brand_static_file(asset_name)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_type = _BRAND_STATIC_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/admin", response_class=HTMLResponse, tags=["admin"])
async def admin_dashboard() -> HTMLResponse:
    return HTMLResponse(load_admin_html())


@router.get("/admin/static/{asset_name}", tags=["admin"])
async def admin_static(asset_name: str) -> FileResponse:
    path = resolve_admin_static_file(asset_name)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_type = _ADMIN_STATIC_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/crawl", response_class=HTMLResponse, tags=["crawl"])
async def crawl_dashboard() -> HTMLResponse:
    return HTMLResponse(load_dashboard_html())


@router.get("/crawl/static/{asset_name}", tags=["crawl"])
async def crawl_dashboard_static(asset_name: str) -> FileResponse:
    path = resolve_crawl_static_file(asset_name)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    media_type = _CRAWL_STATIC_MEDIA.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type)


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    sites = site_service.list_sites()
    total_docs = 0
    by_format: dict[str, int] = {}
    passthrough = 0
    with_url = 0
    crawl_resources = 0

    for site in sites:
        docs = scan_documents(data_dir=site_service.data_dir_for(site))
        total_docs += len(docs)
        stats = catalog_stats(docs)
        for fmt, count in stats["by_format"].items():
            by_format[fmt] = by_format.get(fmt, 0) + count
        passthrough += stats["passthrough_count"]
        with_url += stats["with_file_url"]
        state_db = site_service.state_db_for(site)
        if state_db.exists():
            crawl_resources += len(CrawlState(state_db).list_resources())

    default_site = site_service.default_site()
    crawl_cfg = (
        site_service.crawl_settings_for(default_site) if default_site else None
    )

    return HealthResponse(
        status="ok",
        document_count=total_docs,
        data_dir=str(settings.data_dir.resolve()),
        catalog_by_format=by_format,
        catalog_passthrough_count=passthrough,
        catalog_with_file_url=with_url,
        passthrough_enabled=crawl_cfg.passthrough_enabled if crawl_cfg else None,
        passthrough_extensions=sorted(crawl_cfg.passthrough_extensions) if crawl_cfg else None,
        sitemap_only=crawl_cfg.sitemap_only if crawl_cfg else None,
        follow_file_links=crawl_cfg.follow_file_links if crawl_cfg else None,
        public_base_url=default_site.public_base_url if default_site else None,
        crawl_resources=crawl_resources or None,
        scheduler_enabled=any(
            site_service.scheduler_settings_for(site).enabled for site in sites
        ),
        crawl_running=crawl_runner.running,
        site_count=len(sites),
    )


@router.get(
    "/api/sites",
    response_model=SiteListResponse,
    tags=["sites"],
    dependencies=[Depends(require_token)],
)
async def list_sites() -> SiteListResponse:
    sites = site_service.list_sites()
    items = [_site_summary(site) for site in sites]
    return SiteListResponse(items=items, total=len(items))


@router.post(
    "/api/sites",
    response_model=SiteDetailResponse,
    tags=["sites"],
    dependencies=[Depends(require_token)],
    status_code=status.HTTP_201_CREATED,
)
async def create_site(body: SiteCreateRequest) -> SiteDetailResponse:
    if site_service.get_site(body.site_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Site already exists: {body.site_id}",
        )
    if not body.crawler.get("seed_url"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="crawler.seed_url is required",
        )

    now = datetime.now(timezone.utc)
    record = SiteRecord(
        site_id=body.site_id,
        name=body.name,
        enabled=body.enabled,
        public_base_url=body.public_base_url,
        crawler=body.crawler,
        scheduler=body.scheduler,
        ragflow=body.ragflow,
        created_at=now,
        updated_at=now,
    )
    saved = site_service.upsert_site(record)
    reload_scheduler()
    return _site_detail(saved)


@router.get(
    "/api/sites/{site_id}",
    response_model=SiteDetailResponse,
    tags=["sites"],
    dependencies=[Depends(require_token)],
)
async def get_site(site_id: str) -> SiteDetailResponse:
    return _site_detail(_resolve_site_or_404(site_id))


@router.put(
    "/api/sites/{site_id}",
    response_model=SiteDetailResponse,
    tags=["sites"],
    dependencies=[Depends(require_token)],
)
async def update_site(site_id: str, body: SiteUpdateRequest) -> SiteDetailResponse:
    site = _resolve_site_or_404(site_id)
    updated = SiteRecord(
        site_id=site.site_id,
        name=body.name if body.name is not None else site.name,
        enabled=body.enabled if body.enabled is not None else site.enabled,
        public_base_url=(
            body.public_base_url
            if body.public_base_url is not None
            else site.public_base_url
        ),
        crawler=body.crawler if body.crawler is not None else site.crawler,
        scheduler=body.scheduler if body.scheduler is not None else site.scheduler,
        ragflow=body.ragflow if body.ragflow is not None else site.ragflow,
        created_at=site.created_at,
        updated_at=datetime.now(timezone.utc),
    )
    saved = site_service.upsert_site(updated)
    reload_scheduler()
    return _site_detail(saved)


@router.delete(
    "/api/sites/{site_id}",
    tags=["sites"],
    dependencies=[Depends(require_token)],
)
async def delete_site(site_id: str) -> dict[str, str]:
    if not site_service.delete_site(site_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    reload_scheduler()
    return {"status": "deleted", "site_id": site_id}


@router.get(
    "/api/sites/{site_id}/crawl/status",
    response_model=CrawlStatusResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def site_crawl_status(site_id: str) -> CrawlStatusResponse:
    return _build_crawl_status(_resolve_site_or_404(site_id))


@router.get(
    "/api/sites/{site_id}/crawl/live",
    response_model=CrawlLiveResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def site_crawl_live(site_id: str) -> CrawlLiveResponse:
    site = _resolve_site_or_404(site_id)
    snap = crawl_runner.snapshot_for(site.site_id) or crawl_runner.last_snapshot
    sched = site_service.scheduler_settings_for(site)
    return CrawlLiveResponse(
        running=crawl_runner.running and crawl_runner.running_site_id == site.site_id,
        live=_build_live_state(),
        scheduler_enabled=sched.enabled,
        schedule=sched.schedule_description,
        next_run_at=get_next_run_at(site.site_id),
        last_finished_at=snap.finished_at if snap else None,
        last_error=snap.error if snap else None,
        site_id=site.site_id,
    )


@router.post(
    "/api/sites/{site_id}/crawl/start",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def site_crawl_start(site_id: str) -> CrawlTriggerResponse:
    import asyncio

    _resolve_site_or_404(site_id)
    if crawl_runner.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl already in progress",
        )

    async def _run() -> None:
        try:
            await asyncio.to_thread(crawl_runner.run_site, site_id, trigger="api")
        except CrawlAlreadyRunningError:
            pass
        except Exception:
            pass

    asyncio.create_task(_run())
    return CrawlTriggerResponse(
        status="started",
        message=f"Crawl started in background for site {site_id}",
    )


@router.post(
    "/api/sites/{site_id}/crawl/run",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def site_crawl_run(site_id: str) -> CrawlTriggerResponse:
    import asyncio

    _resolve_site_or_404(site_id)
    if crawl_runner.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl already in progress",
        )

    try:
        result = await asyncio.to_thread(
            crawl_runner.run_site, site_id, trigger="api"
        )
    except CrawlAlreadyRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return CrawlTriggerResponse(
        status="completed",
        message=f"Crawl finished for site {site_id}",
        run_id=result.run_id,
    )


@router.post(
    "/api/sites/{site_id}/ragflow/sync",
    tags=["ragflow"],
    dependencies=[Depends(require_token)],
)
async def site_ragflow_sync(site_id: str) -> dict[str, int]:
    _resolve_site_or_404(site_id)
    try:
        return sync_site_to_ragflow(site_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get(
    "/api/sites/{site_id}/files/{doc_id}",
    tags=["files"],
    dependencies=[Depends(require_token)],
)
async def site_download_file(site_id: str, doc_id: str) -> FileResponse:
    site = _resolve_site_or_404(site_id)
    data_dir = site_service.data_dir_for(site)
    path = resolve_document_path(doc_id, data_dir=data_dir)
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(
        path,
        media_type=guess_mime_type(path),
        filename=path.name,
    )


# Legacy endpoints (default site) — kept for existing dashboards and file URLs.


@router.get(
    "/api/crawl/live",
    response_model=CrawlLiveResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_live_status(
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> CrawlLiveResponse:
    site = _resolve_site_or_404(site_id) if site_id else site_service.default_site()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return await site_crawl_live(site.site_id)


@router.post(
    "/api/crawl/start",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_start(
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> CrawlTriggerResponse:
    site = site_service.default_site() if site_id is None else _resolve_site_or_404(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return await site_crawl_start(site.site_id)


@router.get(
    "/api/crawl/status",
    response_model=CrawlStatusResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_status(
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> CrawlStatusResponse:
    site = site_service.default_site() if site_id is None else _resolve_site_or_404(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return _build_crawl_status(site)


@router.post(
    "/api/crawl/run",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_run(
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> CrawlTriggerResponse:
    site = site_service.default_site() if site_id is None else _resolve_site_or_404(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return await site_crawl_run(site.site_id)


@router.get(
    "/api/files/{doc_id}",
    tags=["files"],
    dependencies=[Depends(require_token)],
)
async def download_file(
    doc_id: str,
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> FileResponse:
    site = site_service.default_site() if site_id is None else _resolve_site_or_404(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return await site_download_file(site.site_id, doc_id)


@router.post(
    "/api/ragflow/sync",
    tags=["ragflow"],
    dependencies=[Depends(require_token)],
)
async def ragflow_sync(
    site_id: str | None = Query(None, description="Site id (defaults to first enabled site)"),
) -> dict[str, int]:
    site = site_service.default_site() if site_id is None else _resolve_site_or_404(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No sites configured")
    return await site_ragflow_sync(site.site_id)
