from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI

from myskin import __version__
from myskin.crawl_recovery import mark_interrupted_runs, recover_interrupted_crawl_on_startup
from myskin.routes import router
from myskin.scheduler import run_scheduled_crawl, start_scheduler, stop_scheduler
from myskin.scheduler_config import scheduler_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    start_scheduler()
    if scheduler_settings.run_on_startup:
        mark_interrupted_runs()
        asyncio.create_task(run_scheduled_crawl())
    else:
        asyncio.create_task(recover_interrupted_crawl_on_startup())
    yield
    stop_scheduler()


app = FastAPI(
    title="myskin",
    description="RAGFlow REST API data source — crawl, store, and serve documents",
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
