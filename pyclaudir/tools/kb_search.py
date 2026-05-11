"""kb_search — search the company knowledge base via OpenWebUI RAG API."""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from .base import BaseTool, ToolResult

log = logging.getLogger(__name__)


class KbSearchArgs(BaseModel):
    query: str = Field(description="Search query")
    k: int = Field(default=5, description="Number of results to return")
    hybrid: bool = Field(default=True, description="Use hybrid BM25+vector search")


class KbSearchTool(BaseTool):
    name = "kb_search"
    description = (
        "Search the company knowledge base. Returns relevant document chunks "
        "with source names and relevance scores."
    )
    args_model = KbSearchArgs

    async def run(self, args: KbSearchArgs) -> ToolResult:
        url = self.ctx.openwebui_api_url
        key = self.ctx.openwebui_api_key
        kb = self.ctx.openwebui_kb_uuid
        if not (url and key and kb):
            log.warning(
                "kb_search: missing OpenWebUI config (OPENWEBUI_API_URL/KEY/KB_UUID)"
            )
            return ToolResult(
                content="kb_search unavailable: missing OpenWebUI config", is_error=True
            )
        payload = {
            "collection_names": [kb],
            "query": args.query,
            "k": args.k,
            "hybrid": args.hybrid,
            "hybrid_bm25_weight": 0.4,
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{url}/api/v1/retrieval/query/collection",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            log.warning("kb_search request failed: %s", exc)
            return ToolResult(content=f"kb_search failed: {exc}", is_error=True)
        return _format_results(data)


def _format_results(data: dict) -> ToolResult:
    docs = (data.get("documents") or [[]])[0]
    metas = (data.get("metadatas") or [[]])[0]
    dists = (data.get("distances") or [[]])[0]
    if not docs:
        return ToolResult(content="(no results)")
    lines: list[str] = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        dist = dists[i] if i < len(dists) else 0.0
        source = meta.get("source", "unknown")
        text = meta.get("raw_text") or doc
        lines.append(f"[{dist:.2f}] {source}\n{text}")
    return ToolResult(content="\n\n".join(lines))
