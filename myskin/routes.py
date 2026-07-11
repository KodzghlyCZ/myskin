from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from myskin.auth import require_token
from myskin.catalog import paginate, scan_documents
from myskin.config import settings
from myskin.crawl_runner import CrawlAlreadyRunningError, crawl_runner
from myskin.crawler.config import crawl_settings
from myskin.crawler.live import crawl_live
from myskin.crawler.state import CrawlState
from myskin.dashboard import DASHBOARD_HTML
from myskin.models import (
    CrawlLiveEventModel,
    CrawlLiveResponse,
    CrawlLiveSampleModel,
    CrawlLiveStateModel,
    CrawlStatsModel,
    CrawlStatusResponse,
    CrawlTriggerResponse,
    DocumentItem,
    DocumentListResponse,
    HealthResponse,
)
from myskin.scheduler import get_next_run_at
from myskin.scheduler_config import scheduler_settings

router = APIRouter()


def _build_crawl_status() -> CrawlStatusResponse:
    snap = crawl_runner.last_snapshot
    stats = None
    if snap.stats is not None:
        stats = CrawlStatsModel(**snap.stats.__dict__)

    return CrawlStatusResponse(
        running=crawl_runner.running,
        scheduler_enabled=scheduler_settings.enabled,
        schedule_mode=scheduler_settings.mode,
        schedule=scheduler_settings.schedule_description,
        next_run_at=get_next_run_at(),
        last_run_id=snap.run_id,
        last_started_at=snap.started_at,
        last_finished_at=snap.finished_at,
        last_trigger=snap.trigger,
        last_error=snap.error,
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
    )


@router.get("/crawl", response_class=HTMLResponse, tags=["crawl"])
async def crawl_dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


@router.get(
    "/api/crawl/live",
    response_model=CrawlLiveResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_live_status() -> CrawlLiveResponse:
    snap = crawl_runner.last_snapshot
    return CrawlLiveResponse(
        running=crawl_runner.running,
        live=_build_live_state(),
        scheduler_enabled=scheduler_settings.enabled,
        schedule=scheduler_settings.schedule_description,
        next_run_at=get_next_run_at(),
        last_finished_at=snap.finished_at,
        last_error=snap.error,
    )


@router.post(
    "/api/crawl/start",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_start() -> CrawlTriggerResponse:
    import asyncio

    if crawl_runner.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl already in progress",
        )

    async def _run() -> None:
        try:
            await asyncio.to_thread(crawl_runner.run, trigger="api")
        except CrawlAlreadyRunningError:
            pass
        except Exception:
            pass

    asyncio.create_task(_run())
    return CrawlTriggerResponse(
        status="started",
        message="Crawl started in background",
    )


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    docs = scan_documents()
    crawl_count = None
    if crawl_settings.state_db.exists():
        crawl_count = len(CrawlState(crawl_settings.state_db).list_resources())
    return HealthResponse(
        status="ok",
        document_count=len(docs),
        data_dir=str(settings.data_dir.resolve()),
        crawl_resources=crawl_count,
        scheduler_enabled=scheduler_settings.enabled,
        crawl_running=crawl_runner.running,
    )


@router.get(
    "/api/crawl/status",
    response_model=CrawlStatusResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_status() -> CrawlStatusResponse:
    return _build_crawl_status()


@router.post(
    "/api/crawl/run",
    response_model=CrawlTriggerResponse,
    tags=["crawl"],
    dependencies=[Depends(require_token)],
)
async def crawl_run() -> CrawlTriggerResponse:
    import asyncio

    if crawl_runner.running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Crawl already in progress",
        )

    try:
        result = await asyncio.to_thread(crawl_runner.run, trigger="api")
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
        message="Crawl finished successfully",
        run_id=result.run_id,
    )


@router.get(
    "/api/documents",
    response_model=DocumentListResponse,
    tags=["documents"],
    dependencies=[Depends(require_token)],
)
async def list_documents(
    offset: int = Query(0, ge=0, description="Pagination offset for RAGFlow"),
    limit: int = Query(50, ge=1, le=500, description="Page size for RAGFlow"),
    updated_since: str | None = Query(
        None,
        description="ISO-8601 timestamp; return only docs updated at or after this time",
    ),
) -> DocumentListResponse:
    documents = scan_documents()

    if updated_since:
        try:
            since = updated_since.replace("Z", "+00:00")
            threshold = datetime.fromisoformat(since)
            if threshold.tzinfo is None:
                threshold = threshold.replace(tzinfo=timezone.utc)
            documents = [d for d in documents if d.updated_at >= threshold]
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid updated_since: {exc}",
            ) from exc

    page, total = paginate(documents, offset=offset, limit=limit)
    return DocumentListResponse(items=page, total=total)


@router.get(
    "/api/documents/{doc_id}",
    response_model=DocumentItem,
    tags=["documents"],
    dependencies=[Depends(require_token)],
)
async def get_document(doc_id: str) -> DocumentItem:
    for doc in scan_documents():
        if doc.id == doc_id:
            return doc
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
