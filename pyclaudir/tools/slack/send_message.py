"""``send_message`` — send a text message to a Slack channel or DM."""

from __future__ import annotations

import logging
import zlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ...db.messages import insert_message
from ...models import ChatMessage
from ...slack_io.formatter import markdown_to_slack
from ...transcript import log_outbound
from ..base import BaseTool, ToolContext, ToolResult

log = logging.getLogger(__name__)

_SLACK_TEXT_LIMIT = 3000


def _chunk_text(text: str, limit: int = _SLACK_TEXT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        for sep in ("\n\n", "\n", " "):
            idx = window.rfind(sep)
            if idx > 0:
                chunks.append(remaining[:idx])
                next_start = idx + len(sep)
                while next_start < len(remaining) and remaining[next_start] == "\n":
                    next_start += 1
                remaining = remaining[next_start:]
                break
        else:
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]
    if remaining:
        chunks.append(remaining)
    return chunks


async def _record_outbound(
    ctx: ToolContext, channel_id: str, ts: str, text: str
) -> None:
    if ctx.database is None or ctx.bot is None:
        return
    try:
        resp = await ctx.bot.auth_test()
        bot_uid = resp.get("user_id", "")
        bot_user_id = zlib.crc32(bot_uid.encode()) & 0x7FFFFFFF
    except Exception:
        bot_user_id = 0
    chat_id = zlib.crc32(channel_id.encode()) & 0x7FFFFFFF
    message_id = int(ts.replace(".", ""))
    await insert_message(
        ctx.database,
        ChatMessage(
            chat_id=chat_id,
            message_id=message_id,
            user_id=bot_user_id,
            direction="out",
            timestamp=datetime.now(timezone.utc),
            text=text,
        ),
    )


class SendMessageArgs(BaseModel):
    channel_id: str = Field(
        description="Slack channel ID (e.g. C012AB3CD) or DM channel."
    )
    text: str = Field(description="Message body (Markdown supported).")
    thread_ts: str | None = Field(
        default=None,
        description="Thread timestamp to reply into. Use the thread_ts from the inbound message.",
    )
    reply_broadcast: bool = Field(
        default=False, description="Also post to channel when replying in thread."
    )


class SendMessageTool(BaseTool):
    name = "send_message"
    description = (
        "Send a text message to a Slack channel or DM. Always pass thread_ts "
        "to keep replies in the same thread. Long messages are chunked automatically."
    )
    args_model = SendMessageArgs

    async def run(self, args: SendMessageArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)

        raw_chunks = _chunk_text(args.text)
        timestamps: list[str] = []

        for i, chunk in enumerate(raw_chunks):
            body = markdown_to_slack(chunk)
            kwargs: dict = {"channel": args.channel_id, "text": body, "mrkdwn": True}
            if args.thread_ts:
                kwargs["thread_ts"] = args.thread_ts
                if args.reply_broadcast and i == 0:
                    kwargs["reply_broadcast"] = True
            resp = await self.ctx.bot.chat_postMessage(**kwargs)
            ts = resp["ts"]
            timestamps.append(ts)
            log.info(
                "slack send chunk=%d/%d channel=%s ts=%s",
                i + 1,
                len(raw_chunks),
                args.channel_id,
                ts,
            )

            if i == 0 and self.ctx.on_chat_replied is not None:
                try:
                    chat_id = zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF
                    self.ctx.on_chat_replied(chat_id)
                except Exception:
                    pass

        first_ts = timestamps[0]
        log_outbound(
            chat_id=zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF,
            chat_titles=self.ctx.chat_titles,
            message_id=int(first_ts.replace(".", "")),
            reply_to_id=None,
            text=args.text,
        )
        for ts, raw in zip(timestamps, raw_chunks):
            await _record_outbound(self.ctx, args.channel_id, ts, raw)

        content = (
            f"sent ts={first_ts}"
            if len(timestamps) == 1
            else f"sent {len(timestamps)} chunks, first ts={first_ts}"
        )
        return ToolResult(
            content=content,
            data={
                "ts": first_ts,
                "timestamps": timestamps,
                "channel_id": args.channel_id,
            },
        )
