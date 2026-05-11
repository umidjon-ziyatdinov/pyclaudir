"""``reply_to_message`` — reply in a Slack thread."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import BaseTool, ToolResult
from .send_message import SendMessageArgs, SendMessageTool


class ReplyToMessageArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    thread_ts: str = Field(
        description="The ts of the message to reply to (becomes thread anchor)."
    )
    text: str = Field(description="Reply body.")


class ReplyToMessageTool(BaseTool):
    name = "reply_to_message"
    description = (
        "Reply to a specific Slack message by ts, keeping the reply in-thread."
    )
    args_model = ReplyToMessageArgs

    async def run(self, args: ReplyToMessageArgs) -> ToolResult:
        delegate = SendMessageTool(self.ctx)
        return await delegate.run(
            SendMessageArgs(
                channel_id=args.channel_id,
                text=args.text,
                thread_ts=args.thread_ts,
            )
        )
