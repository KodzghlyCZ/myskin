from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from myskin import __version__
from myskin.crawl_recovery import mark_interrupted_runs, recover_interrupted_crawl_on_startup
from myskin.routes import router
from myskin.scheduler import run_startup_crawls, start_scheduler, stop_scheduler
from myskin.sites.service import site_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    site_service.bootstrap()
    start_scheduler()
    startup_scheduled = any(
        site_service.scheduler_settings_for(site).run_on_startup
        for site in site_service.list_sites(enabled_only=True)
    )
    if startup_scheduled:
        mark_interrupted_runs()
        asyncio.create_task(run_startup_crawls())
    else:
        asyncio.create_task(recover_interrupted_crawl_on_startup())
    yield
    stop_scheduler()


app = FastAPI(
    title="myskin",
    description="Multi-site web crawler with RAGFlow dataset push sync",
    version=__version__,
    lifespan=lifespan,
)
app.include_router(router)


def main() -> None:
    import uvicorn

    from myskin.config import settings

    uvicorn.run(
        "myskin.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
