"""``delete_message`` — delete a Slack message the bot sent."""

from __future__ import annotations

import zlib

from pydantic import BaseModel, Field

from ...db.messages import mark_deleted
from ...transcript import log_delete
from ..base import BaseTool, ToolResult


class DeleteMessageArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    ts: str = Field(description="The ts of the message to delete.")


class DeleteMessageTool(BaseTool):
    name = "delete_message"
    description = (
        "Delete a Slack message by ts. Bots can only delete their own messages."
    )
    args_model = DeleteMessageArgs

    async def run(self, args: DeleteMessageArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)
        await self.ctx.bot.chat_delete(channel=args.channel_id, ts=args.ts)
        chat_id = zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF
        message_id = int(args.ts.replace(".", ""))
        log_delete(
            chat_id=chat_id,
            chat_titles=self.ctx.chat_titles,
            message_id=message_id,
        )
        if self.ctx.database is not None:
            await mark_deleted(self.ctx.database, chat_id, message_id)
        return ToolResult(content=f"deleted ts={args.ts}")
