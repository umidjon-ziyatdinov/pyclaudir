"""kb_upload — ingest a text document into the knowledge base (OpenWebUI RAG API)."""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult

log = logging.getLogger(__name__)

_ALREADY_INDEXED = "already indexed, skipping"


class KbUploadArgs(BaseModel):
    content: str = Field(description="Document text to ingest")
    title: str = Field(description="Display name used as the filename stem")
    source_url: str = Field(description="Canonical URL for citation and dedup key")
    source_type: str = Field(description='Source type, e.g. "confluence" or "manual"')


class KbUploadTool(BaseTool):
    name = "kb_upload"
    description = (
        "Ingest a text document into the knowledge base. Records the upload "
        "in kb_ingestions to prevent duplicate indexing of unchanged content."
    )
    args_model = KbUploadArgs

    async def run(self, args: KbUploadArgs) -> ToolResult:
        url = self.ctx.openwebui_api_url
        key = self.ctx.openwebui_api_key
        kb = self.ctx.openwebui_kb_uuid
        if not (url and key and kb):
            log.warning(
                "kb_upload: missing OpenWebUI config (OPENWEBUI_API_URL/KEY/KB_UUID)"
            )
            return ToolResult(
                content="kb_upload unavailable: missing OpenWebUI config", is_error=True
            )
        if self.ctx.database is None:
            return ToolResult(
                content="kb_upload unavailable: no database", is_error=True
            )

        content_hash = hashlib.sha256(args.content.encode()).hexdigest()
        if await _check_dedup(self.ctx.database, args.source_url, content_hash):
            return ToolResult(content=_ALREADY_INDEXED)

        try:
            file_id = await _upload_file(url, key, args.title, args.content)
            await _add_to_kb(url, key, kb, file_id)
        except Exception as exc:
            log.warning("kb_upload failed: %s", exc)
            return ToolResult(content=f"kb_upload failed: {exc}", is_error=True)

        await _upsert_ingestion(
            self.ctx.database, args.source_url, content_hash, args.source_type
        )
        return ToolResult(content=f"indexed: {args.title} (file_id={file_id})")


async def _check_dedup(db, source_url: str, content_hash: str) -> bool:
    row = await db.fetch_one(
        "SELECT content_hash FROM kb_ingestions WHERE source_url = ?", (source_url,)
    )
    return row is not None and row["content_hash"] == content_hash


async def _upload_file(base_url: str, api_key: str, title: str, content: str) -> str:
    filename = f"{title}.md"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/api/v1/files/",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (filename, io.BytesIO(content.encode()), "text/markdown")},
        )
        resp.raise_for_status()
        return str(resp.json()["id"])


async def _add_to_kb(base_url: str, api_key: str, kb_uuid: str, file_id: str) -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{base_url}/api/v1/knowledge/{kb_uuid}/file/add",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"file_id": file_id, "process": True},
        )
        resp.raise_for_status()


async def _upsert_ingestion(
    db, source_url: str, content_hash: str, source_type: str
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute(
        """
        INSERT OR REPLACE INTO kb_ingestions
            (source_url, content_hash, ingested_at, source_type)
        VALUES (?, ?, ?, ?)
        """,
        (source_url, content_hash, now, source_type),
    )
