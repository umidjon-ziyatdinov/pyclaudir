"""``edit_message`` — edit a Slack message the bot previously sent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...db.messages import mark_edited
from ...slack_io.formatter import markdown_to_slack
from ...transcript import log_edit
from ..base import BaseTool, ToolResult
import zlib


class EditMessageArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    ts: str = Field(description="The ts of the message to edit.")
    text: str = Field(description="New message body.")


class EditMessageTool(BaseTool):
    name = "edit_message"
    description = "Edit a Slack message previously sent by the bot."
    args_model = EditMessageArgs

    async def run(self, args: EditMessageArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)
        body = markdown_to_slack(args.text)
        await self.ctx.bot.chat_update(
            channel=args.channel_id, ts=args.ts, text=body, mrkdwn=True
        )
        chat_id = zlib.crc32(args.channel_id.encode()) & 0x7FFFFFFF
        message_id = int(args.ts.replace(".", ""))
        log_edit(
            chat_id=chat_id,
            chat_titles=self.ctx.chat_titles,
            message_id=message_id,
            text=args.text,
        )
        if self.ctx.database is not None:
            await mark_edited(self.ctx.database, chat_id, message_id, args.text)
        return ToolResult(
            content=f"edited ts={args.ts}",
            data={"ts": args.ts, "channel_id": args.channel_id},
        )
