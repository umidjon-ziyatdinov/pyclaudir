"""``stop_poll`` — no-op stub for Slack.

Slack has no native poll API; polls are Block Kit messages. To close a
poll, edit or delete the message that contains it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..base import BaseTool, ToolResult


class StopPollArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    ts: str = Field(description="The ts of the poll message to close.")


class StopPollTool(BaseTool):
    name = "stop_poll"
    description = (
        "Close a Slack poll. Since Slack polls are Block Kit messages, "
        "this deletes the poll message. Use edit_message instead to "
        "replace the buttons with a results summary."
    )
    args_model = StopPollArgs

    async def run(self, args: StopPollArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)
        try:
            await self.ctx.bot.chat_delete(channel=args.channel_id, ts=args.ts)
        except Exception as exc:
            return ToolResult(content=f"delete failed: {exc}", is_error=True)
        return ToolResult(content=f"poll message deleted ts={args.ts}")
