from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from myskin import __version__
from myskin.auth import configure_oauth, router as auth_router
from myskin.config import settings
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
    configure_oauth()
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
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_https_only,
)
app.include_router(auth_router)
app.include_router(router)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "myskin.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
