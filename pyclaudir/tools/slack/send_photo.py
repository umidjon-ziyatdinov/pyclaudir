"""``send_photo`` — upload a rendered image to a Slack channel."""

from __future__ import annotations

import asyncio
import zlib

from pydantic import BaseModel, Field

from ...transcript import log_outbound
from ..base import BaseTool, ToolResult

_CAPTION_LIMIT = 3000


class SendPhotoArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    path: str = Field(
        description=(
            "Relative path under data/renders/ — the value returned by render_html. "
            "No '..', no absolute paths."
        ),
    )
    caption: str | None = Field(default=None, max_length=_CAPTION_LIMIT)
    thread_ts: str | None = Field(
        default=None,
        description="Thread timestamp — post the image inside an existing thread.",
    )


class SendPhotoTool(BaseTool):
    name = "send_photo"
    description = (
        "Upload a rendered image (under data/renders/) to a Slack channel. "
        "Pass thread_ts to keep the image in the same thread."
    )
    args_model = SendPhotoArgs

    async def run(self, args: SendPhotoArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)
        store = self.ctx.render_store
        if store is None:
            return ToolResult(content="render store unavailable", is_error=True)

        try:
            resolved = await asyncio.to_thread(store.resolve_path, args.path)
        except Exception as exc:
            return ToolResult(content=f"{type(exc).__name__}: {exc}", is_error=True)

        if not resolved.exists() or not resolved.is_file():
            return ToolResult(content=f"render not found: {args.path}", is_error=True)

        kwargs: dict = {
            "channel": args.channel_id,
            "file": str(resolved),
            "filename": resolved.name,
            "title": resolved.stem,
        }
        if args.caption:
            kwargs["initial_comment"] = args.caption
        if args.thread_ts:
            kwargs["thread_ts"] = args.thread_ts

        resp = await self.ctx.bot.files_upload_v2(**kwargs)
        file_id = resp.get("file", {}).get("id", "unknown")

        if self.ctx.on_chat_replied is not None:
            try:
                chat_id = zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF
                self.ctx.on_chat_replied(chat_id)
            except Exception:
                pass

        transcript_text = f"[photo] {args.path}"
        if args.caption:
            transcript_text += f" — {args.caption}"
        log_outbound(
            chat_id=zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF,
            chat_titles=self.ctx.chat_titles,
            message_id=0,
            reply_to_id=None,
            text=transcript_text,
        )
        return ToolResult(
            content=f"uploaded file_id={file_id} ({resolved.name})",
            data={
                "file_id": file_id,
                "channel_id": args.channel_id,
                "filename": resolved.name,
            },
        )
