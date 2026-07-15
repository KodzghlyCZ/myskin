from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from myskin.catalog import resolve_document_path, scan_documents
from myskin.models import DocumentItem
from myskin.ragflow_sync_state import RagflowSyncRecord, RagflowSyncState
from myskin.settings_loader import cfg_bool, cfg_get, ensure_config_loaded, secrets

logger = logging.getLogger(__name__)


class RagflowApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class RagflowSettings:
    enabled: bool
    api_url: str
    dataset_id: str
    state_db: Path
    sync_on_crawl_complete: bool
    parse_on_upload: bool
    delete_missing: bool

    @classmethod
    def load(cls) -> RagflowSettings:
        ensure_config_loaded()
        api_url = str(cfg_get("ragflow.api_url", default="")).strip().rstrip("/")
        dataset_id = str(cfg_get("ragflow.dataset_id", default="")).strip()
        state_db_raw = str(cfg_get("ragflow.state_db", default="./.myskin/ragflow_sync.db")).strip()
        return cls(
            enabled=cfg_bool("ragflow.enabled", False),
            api_url=api_url,
            dataset_id=dataset_id,
            state_db=Path(state_db_raw),
            sync_on_crawl_complete=cfg_bool("ragflow.sync_on_crawl_complete", True),
            parse_on_upload=cfg_bool("ragflow.parse_on_upload", True),
            delete_missing=cfg_bool("ragflow.delete_missing", True),
        )

    @property
    def api_key(self) -> str:
        return secrets().ragflow_api_key


@dataclass
class RagflowSyncResult:
    uploaded: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    parsed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "uploaded": self.uploaded,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "failed": self.failed,
            "parsed": self.parsed,
        }


class RagflowClient:
    def __init__(self, settings: RagflowSettings) -> None:
        self.settings = settings
        self._headers = {"Authorization": f"Bearer {settings.api_key}"}

    def _dataset_url(self, suffix: str) -> str:
        base = f"{self.settings.api_url}/api/v1/datasets/{self.settings.dataset_id}"
        return f"{base}/{suffix}" if suffix else base

    @staticmethod
    def _unwrap(response: httpx.Response) -> Any:
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RagflowApiError(str(payload.get("message") or "RAGFlow API error"))
        return payload.get("data")

    def upload_document(self, client: httpx.Client, *, path: Path, filename: str, mime_type: str) -> str:
        with path.open("rb") as handle:
            response = client.post(
                self._dataset_url("documents"),
                files={"file": (filename, handle, mime_type)},
            )
        data = self._unwrap(response)
        if not isinstance(data, list) or not data:
            raise RagflowApiError("RAGFlow upload returned no document")
        doc_id = data[0].get("id")
        if not doc_id:
            raise RagflowApiError("RAGFlow upload response missing document id")
        return str(doc_id)

    def update_document(
        self,
        client: httpx.Client,
        *,
        document_id: str,
        name: str | None = None,
        meta_fields: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if meta_fields:
            body["meta_fields"] = meta_fields
        if not body:
            return
        response = client.put(
            self._dataset_url(f"documents/{document_id}"),
            json=body,
        )
        self._unwrap(response)

    def delete_documents(self, client: httpx.Client, document_ids: list[str]) -> None:
        if not document_ids:
            return
        response = client.request(
            "DELETE",
            self._dataset_url("documents"),
            json={"ids": document_ids},
        )
        self._unwrap(response)

    def parse_documents(self, client: httpx.Client, document_ids: list[str]) -> None:
        if not document_ids:
            return
        response = client.post(
            self._dataset_url("chunks"),
            json={"document_ids": document_ids},
        )
        self._unwrap(response)


def _file_digest(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _needs_sync(doc: DocumentItem, path: Path, record: RagflowSyncRecord | None) -> tuple[bool, str]:
    digest = _file_digest(path)
    if record is None:
        return True, digest
    if record.content_hash != digest:
        return True, digest
    doc_updated = doc.updated_at
    if doc_updated.tzinfo is None:
        doc_updated = doc_updated.replace(tzinfo=timezone.utc)
    if record.updated_at != doc_updated:
        return True, digest
    return False, digest


def _ragflow_meta_fields(doc: DocumentItem) -> dict[str, str]:
    """Fields RAGFlow forwards to Dify as doc_metadata when retrieval includes metadata."""
    fields: dict[str, str] = {
        "myskin_id": doc.id,
        "title": doc.title,
        "author": doc.author,
        "category": doc.category,
        "format": doc.format,
    }
    if doc.source_url:
        # RAGFlow chat cites `url` in reference chunks — primary link for Spliffy/Dify.
        fields["url"] = doc.source_url
        fields["source_url"] = doc.source_url
    if doc.file_url:
        fields["file_url"] = doc.file_url
    return fields


def sync_documents_to_ragflow(
    *,
    documents: list[DocumentItem] | None = None,
    ragflow: RagflowSettings | None = None,
) -> dict[str, int]:
    """Incrementally push catalog files to RAGFlow with native extensions."""
    settings = ragflow or RagflowSettings.load()
    if not settings.enabled:
        return RagflowSyncResult().as_dict()
    if not settings.api_url or not settings.dataset_id:
        raise ValueError("ragflow.api_url and ragflow.dataset_id are required when ragflow.enabled=true")
    if not settings.api_key:
        raise ValueError("MYSKIN_RAGFLOW_API_KEY is required when ragflow.enabled=true")

    items = documents if documents is not None else scan_documents()
    state = RagflowSyncState(settings.state_db)
    known = state.list_records()
    catalog_ids = {doc.id for doc in items}

    result = RagflowSyncResult()
    client_api = RagflowClient(settings)
    to_parse: list[str] = []
    now = datetime.now(timezone.utc)

    with httpx.Client(timeout=120.0, headers=client_api._headers) as client:
        if settings.delete_missing:
            removed_ids = [myskin_id for myskin_id in known if myskin_id not in catalog_ids]
            for myskin_id in removed_ids:
                record = known[myskin_id]
                try:
                    client_api.delete_documents(client, [record.ragflow_document_id])
                    state.delete(myskin_id)
                    result.deleted += 1
                    logger.info("RAGFlow sync: deleted %s (%s)", myskin_id, record.ragflow_document_id)
                except Exception as exc:
                    result.failed += 1
                    logger.warning("RAGFlow sync: failed to delete %s: %s", myskin_id, exc)

        for doc in items:
            path = resolve_document_path(doc.id)
            if path is None or not path.is_file():
                result.failed += 1
                logger.warning("RAGFlow sync: missing file for %s", doc.id)
                continue

            record = known.get(doc.id)
            changed, digest = _needs_sync(doc, path, record)
            if not changed:
                if record is not None:
                    try:
                        client_api.update_document(
                            client,
                            document_id=record.ragflow_document_id,
                            name=doc.title or doc.filename,
                            meta_fields=_ragflow_meta_fields(doc),
                        )
                    except Exception as exc:
                        logger.warning(
                            "RAGFlow sync: metadata refresh failed for %s: %s",
                            doc.id,
                            exc,
                        )
                result.skipped += 1
                continue

            filename = doc.filename or path.name
            is_update = record is not None

            if is_update and record is not None:
                try:
                    client_api.delete_documents(client, [record.ragflow_document_id])
                except Exception as exc:
                    result.failed += 1
                    logger.warning(
                        "RAGFlow sync: failed to delete old doc for %s: %s",
                        doc.id,
                        exc,
                    )
                    continue

            try:
                ragflow_doc_id = client_api.upload_document(
                    client,
                    path=path,
                    filename=filename,
                    mime_type=doc.mime_type,
                )
                client_api.update_document(
                    client,
                    document_id=ragflow_doc_id,
                    name=doc.title or filename,
                    meta_fields=_ragflow_meta_fields(doc),
                )
            except Exception as exc:
                result.failed += 1
                logger.warning("RAGFlow sync: upload failed for %s: %s", doc.id, exc)
                continue

            doc_updated = doc.updated_at
            if doc_updated.tzinfo is None:
                doc_updated = doc_updated.replace(tzinfo=timezone.utc)

            state.upsert(
                RagflowSyncRecord(
                    myskin_id=doc.id,
                    ragflow_document_id=ragflow_doc_id,
                    content_hash=digest,
                    updated_at=doc_updated,
                    synced_at=now,
                )
            )
            known[doc.id] = RagflowSyncRecord(
                myskin_id=doc.id,
                ragflow_document_id=ragflow_doc_id,
                content_hash=digest,
                updated_at=doc_updated,
                synced_at=now,
            )
            to_parse.append(ragflow_doc_id)

            if is_update:
                result.updated += 1
                logger.info("RAGFlow sync: updated %s -> %s", doc.id, ragflow_doc_id)
            else:
                result.uploaded += 1
                logger.info("RAGFlow sync: uploaded %s -> %s", doc.id, ragflow_doc_id)

        if settings.parse_on_upload and to_parse:
            try:
                client_api.parse_documents(client, to_parse)
                result.parsed = len(to_parse)
            except Exception as exc:
                logger.warning(
                    "RAGFlow sync: parse failed for %d documents (uploads kept): %s",
                    len(to_parse),
                    exc,
                )

    logger.info(
        "RAGFlow sync complete: uploaded=%d updated=%d deleted=%d skipped=%d failed=%d parsed=%d",
        result.uploaded,
        result.updated,
        result.deleted,
        result.skipped,
        result.failed,
        result.parsed,
    )
    return result.as_dict()


def maybe_sync_after_crawl() -> None:
    settings = RagflowSettings.load()
    if not settings.enabled or not settings.sync_on_crawl_complete:
        return
    try:
        sync_documents_to_ragflow(ragflow=settings)
    except Exception:
        logger.exception("RAGFlow post-crawl sync failed")
