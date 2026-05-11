"""``add_reaction`` — add an emoji reaction to a Slack message.

Slack emoji names are plain text without colons (e.g. ``thumbsup``,
not ``:thumbsup:``). The tool accepts both forms and strips colons.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..base import BaseTool, ToolResult


def _normalize_emoji(raw: str) -> str:
    """Strip surrounding colons and map common Unicode to Slack names."""
    name = raw.strip(":").lower()
    # Map common Unicode emoji to Slack names when obvious
    _UNICODE_MAP: dict[str, str] = {
        "👍": "thumbsup",
        "👎": "thumbsdown",
        "❤": "heart",
        "🔥": "fire",
        "🎉": "tada",
        "✅": "white_check_mark",
        "❌": "x",
        "⭐": "star",
        "🚀": "rocket",
        "👀": "eyes",
        "💯": "100",
        "🤔": "thinking_face",
        "😂": "joy",
        "🙏": "pray",
        "💪": "muscle",
        "✍": "writing_hand",
    }
    return _UNICODE_MAP.get(name, name)


class AddReactionArgs(BaseModel):
    channel_id: str = Field(description="Slack channel ID.")
    ts: str = Field(description="The ts of the message to react to.")
    emoji: str = Field(
        description=(
            "Emoji name (with or without colons, e.g. 'thumbsup' or ':thumbsup:') "
            "or a Unicode emoji character."
        )
    )


class AddReactionTool(BaseTool):
    name = "add_reaction"
    description = (
        "Add an emoji reaction to a Slack message. "
        "Use Slack emoji names like 'thumbsup', 'tada', 'rocket'."
    )
    args_model = AddReactionArgs

    async def run(self, args: AddReactionArgs) -> ToolResult:
        if self.ctx.bot is None:
            return ToolResult(content="bot not configured", is_error=True)
        name = _normalize_emoji(args.emoji)
        if not re.match(r"^[a-z0-9_\-]+$", name):
            return ToolResult(
                content=f"invalid emoji name {name!r} — use Slack names like 'thumbsup'",
                is_error=True,
            )
        try:
            await self.ctx.bot.reactions_add(
                channel=args.channel_id, name=name, timestamp=args.ts
            )
        except Exception as exc:
            return ToolResult(content=f"reactions_add failed: {exc}", is_error=True)
        return ToolResult(content=f"reacted :{name}: to ts={args.ts}")
