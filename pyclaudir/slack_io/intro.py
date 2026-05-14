"""Channel introduction helpers.

Posts a brief self-introduction when a new member joins a channel, or as a
fallback when a first-time user sends a message the bot otherwise ignores.
"""

from __future__ import annotations

import logging
import zlib

from ..db.database import Database

log = logging.getLogger("pyclaudir.slack_io")

_INTRO = (
    "Hi! I'm *{name}*, your AI assistant powered by Claude. "
    "Mention my name or tag me to chat, get answers, or help with tasks. "
    "I reply in threads to keep the channel tidy."
)


def _crc(s: str) -> int:
    return zlib.crc32(s.encode()) & 0x7FFFFFFF


async def is_new_channel_user(db: Database, user_id: int, chat_id: int) -> bool:
    """True if the user has no prior messages in this channel."""
    row = await db.fetch_one(
        "SELECT 1 FROM messages WHERE chat_id=? AND user_id=? LIMIT 1",
        (chat_id, user_id),
    )
    return row is None


async def _post(
    client, channel: str, thread_ts: str | None, bot_name: str | None
) -> None:
    name = bot_name or "Assistant"
    kwargs: dict = {"channel": channel, "text": _INTRO.format(name=name)}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    try:
        await client.chat_postMessage(**kwargs)
    except Exception as exc:
        log.warning("intro post failed channel=%s: %s", channel, exc)


async def maybe_post_intro(
    client,
    db: Database,
    channel: str,
    user_str: str,
    thread_ts: str | None,
    bot_name: str | None,
) -> None:
    """Post intro on a user's first message in a channel (fallback for missed join events)."""
    if await is_new_channel_user(db, _crc(user_str), _crc(channel)):
        await _post(client, channel, thread_ts, bot_name)


async def handle_joined(client, channel: str, bot_name: str | None) -> None:
    """Post intro when a member_joined_channel event fires."""
    await _post(client, channel, None, bot_name)
