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


def _resolve_channel(channel_id: str, chat_titles: dict[int, str]) -> str:
    """Map an integer chat_id string back to a real Slack channel/DM string."""
    if not channel_id.lstrip("-").isdigit():
        return channel_id
    title = chat_titles.get(int(channel_id), "")
    return title.split(":", 1)[1] if ":" in title else channel_id


def _resolve_ts(ts: str) -> str:
    """Convert an integer message_id string back to a Slack ts (add the dot)."""
    if "." in ts or not ts.isdigit() or len(ts) != 16:
        return ts
    return f"{ts[:10]}.{ts[10:]}"


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

    def _fire_reply_callback(self, channel: str) -> None:
        if self.ctx.on_chat_replied is None:
            return
        try:
            self.ctx.on_chat_replied(zlib.crc32(channel.encode()) & 0x7FFFFFFF)
        except Exception:
            pass

    async def _finalize(
        self, channel: str, pairs: list[tuple[str, str]], text: str
    ) -> None:
        first_ts = pairs[0][0]
        log_outbound(
            chat_id=zlib.crc32(channel.encode()) & 0x7FFFFFFF,
            chat_titles=self.ctx.chat_titles,
            message_id=int(first_ts.replace(".", "")),
            reply_to_id=None,
            text=text,
        )
        for ts, raw in pairs:
            await _record_outbound(self.ctx, channel, ts, raw)

    async def run(self, args: SendMessageArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)

        channel = _resolve_channel(args.channel_id, self.ctx.chat_titles)
        thread_ts = _resolve_ts(args.thread_ts) if args.thread_ts else None
        raw_chunks = _chunk_text(args.text)
        timestamps: list[str] = []

        for i, chunk in enumerate(raw_chunks):
            body = markdown_to_slack(chunk)
            kwargs: dict = {"channel": channel, "text": body, "mrkdwn": True}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
                if args.reply_broadcast and i == 0:
                    kwargs["reply_broadcast"] = True
            resp = await self.ctx.bot.chat_postMessage(**kwargs)
            ts = resp["ts"]
            timestamps.append(ts)
            log.info(
                "slack send chunk=%d/%d channel=%s ts=%s",
                i + 1,
                len(raw_chunks),
                channel,
                ts,
            )
            if i == 0:
                self._fire_reply_callback(channel)

        await self._finalize(channel, list(zip(timestamps, raw_chunks)), args.text)
        first_ts = timestamps[0]
        n = len(timestamps)
        content = (
            f"sent ts={first_ts}" if n == 1 else f"sent {n} chunks, first ts={first_ts}"
        )
        return ToolResult(
            content=content,
            data={"ts": first_ts, "timestamps": timestamps, "channel_id": channel},
        )
