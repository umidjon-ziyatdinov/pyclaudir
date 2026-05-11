"""``create_poll`` — post a poll to Slack using Block Kit buttons.

Slack has no native poll API, so we use a section block with the question
plus button action blocks for each option. Responses come via block_action
events (not wired in MVP — treat it as a one-way straw poll for now).
"""

from __future__ import annotations

import zlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from ...db.messages import insert_message
from ...models import ChatMessage
from ...transcript import log_outbound
from ..base import BaseTool, ToolResult


class CreatePollArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    question: str = Field(min_length=1, max_length=300)
    options: list[str] = Field(min_length=2, max_length=10)
    thread_ts: str | None = Field(
        default=None, description="Post inside an existing thread."
    )

    @model_validator(mode="after")
    def _validate_options(self) -> "CreatePollArgs":
        for i, opt in enumerate(self.options):
            if not (1 <= len(opt) <= 75):
                raise ValueError(f"option {i} must be 1–75 chars")
        return self


def _build_blocks(question: str, options: list[str]) -> list[dict]:
    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{question}*"}},
        {"type": "divider"},
    ]
    for i, opt in enumerate(options):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": opt},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"Vote {i + 1}"},
                    "action_id": f"poll_vote_{i}",
                    "value": str(i),
                },
            }
        )
    return blocks


class CreatePollTool(BaseTool):
    name = "create_poll"
    description = (
        "Post a poll to a Slack channel using Block Kit. "
        "Each option gets a Vote button. Pass thread_ts to post in a thread."
    )
    args_model = CreatePollArgs

    async def run(self, args: CreatePollArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)

        blocks = _build_blocks(args.question, args.options)
        kwargs: dict = {
            "channel": args.channel_id,
            "text": args.question,
            "blocks": blocks,
        }
        if args.thread_ts:
            kwargs["thread_ts"] = args.thread_ts

        resp = await self.ctx.bot.chat_postMessage(**kwargs)
        ts = resp["ts"]
        chat_id = zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF
        message_id = int(ts.replace(".", ""))

        if self.ctx.on_chat_replied is not None:
            try:
                self.ctx.on_chat_replied(chat_id)
            except Exception:
                pass

        transcript_text = f"[poll] {args.question}"
        log_outbound(
            chat_id=chat_id,
            chat_titles=self.ctx.chat_titles,
            message_id=message_id,
            reply_to_id=None,
            text=transcript_text,
        )

        if self.ctx.database is not None:
            stored = transcript_text + "\n" + "\n".join(f"- {o}" for o in args.options)
            await insert_message(
                self.ctx.database,
                ChatMessage(
                    chat_id=chat_id,
                    message_id=message_id,
                    user_id=0,
                    direction="out",
                    timestamp=datetime.now(timezone.utc),
                    text=stored,
                ),
            )

        return ToolResult(
            content=f"poll posted ts={ts}",
            data={"ts": ts, "channel_id": args.channel_id},
        )
