from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from myskin.catalog import resolve_document_path, scan_documents
from myskin.models import DocumentItem
from myskin.settings_loader import cfg_bool, cfg_get, ensure_config_loaded, secrets

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagflowSettings:
    enabled: bool
    api_url: str
    dataset_id: str
    sync_on_crawl_complete: bool

    @classmethod
    def load(cls) -> RagflowSettings:
        ensure_config_loaded()
        api_url = str(cfg_get("ragflow.api_url", default="")).strip().rstrip("/")
        dataset_id = str(cfg_get("ragflow.dataset_id", default="")).strip()
        return cls(
            enabled=cfg_bool("ragflow.enabled", False),
            api_url=api_url,
            dataset_id=dataset_id,
            sync_on_crawl_complete=cfg_bool("ragflow.sync_on_crawl_complete", True),
        )

    @property
    def api_key(self) -> str:
        return secrets().ragflow_api_key


def _upload_url(ragflow: RagflowSettings) -> str:
    return f"{ragflow.api_url}/api/v1/datasets/{ragflow.dataset_id}/documents"


def _should_upload(doc: DocumentItem) -> bool:
    return bool(doc.file_url)


def sync_documents_to_ragflow(
    *,
    documents: list[DocumentItem] | None = None,
    ragflow: RagflowSettings | None = None,
) -> dict[str, int]:
    """Upload catalog files to RAGFlow with native extensions (bypasses rest_api .txt coercion)."""
    ragflow = ragflow or RagflowSettings.load()
    if not ragflow.enabled:
        return {"skipped": 0, "uploaded": 0, "failed": 0}
    if not ragflow.api_url or not ragflow.dataset_id:
        raise ValueError("ragflow.api_url and ragflow.dataset_id are required when ragflow.enabled=true")
    if not ragflow.api_key:
        raise ValueError("MYSKIN_RAGFLOW_API_KEY is required when ragflow.enabled=true")

    items = documents if documents is not None else scan_documents()
    uploaded = 0
    failed = 0
    skipped = 0

    headers = {"Authorization": f"Bearer {ragflow.api_key}"}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        for doc in items:
            if not _should_upload(doc):
                skipped += 1
                continue
            path = resolve_document_path(doc.id)
            if path is None or not path.is_file():
                failed += 1
                logger.warning("RAGFlow sync: missing file for %s", doc.id)
                continue
            filename = doc.filename or path.name
            try:
                with path.open("rb") as handle:
                    response = client.post(
                        _upload_url(ragflow),
                        files={"file": (filename, handle, doc.mime_type)},
                    )
                response.raise_for_status()
                uploaded += 1
            except Exception as exc:
                failed += 1
                logger.warning("RAGFlow sync failed for %s: %s", doc.id, exc)

    logger.info(
        "RAGFlow sync complete: uploaded=%d failed=%d skipped=%d",
        uploaded,
        failed,
        skipped,
    )
    return {"uploaded": uploaded, "failed": failed, "skipped": skipped}


def maybe_sync_after_crawl() -> None:
    ragflow = RagflowSettings.load()
    if not ragflow.enabled or not ragflow.sync_on_crawl_complete:
        return
    try:
        sync_documents_to_ragflow(ragflow=ragflow)
    except Exception:
        logger.exception("RAGFlow post-crawl sync failed")
