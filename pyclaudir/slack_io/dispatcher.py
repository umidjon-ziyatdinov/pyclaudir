"""Slack dispatcher — Bolt Socket Mode. Owner ``!`` commands delegated to :mod:`pyclaudir.slack_io.commands`."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from ..access import load_access
from ..config import Config
from ..db.database import Database
from ..db.messages import insert_message, upsert_user
from ..input_normalizer import normalize_inbound
from ..models import ChatMessage
from ..rate_limiter import RateLimitExceeded, RateLimiter
from ..secrets_scrubber import scrub
from ..transcript import log_inbound
from .attachments import process_slack_files
from .commands import dispatch_command
from .formatter import contains_bot_name, strip_mention
from .intro import handle_joined, maybe_post_intro

log = logging.getLogger("pyclaudir.slack_io")


class EnginePort(Protocol):
    async def submit(self, msg: ChatMessage) -> None: ...
    def prime_typing(self, chat_id: int) -> None: ...


def _int_id(slack_id: str) -> int:
    """Stable positive int from a Slack ID string (CRC32)."""
    return zlib.crc32(slack_id.encode()) & 0x7FFFFFFF


def _ts_to_int(ts: str) -> int:
    return int(ts.replace(".", ""))


def _clean(raw: str | None) -> tuple[str | None, frozenset[str]]:
    if not raw:
        return raw, frozenset()
    return normalize_inbound(scrub(raw))


def _is_bot_event(event: dict) -> bool:
    return bool(
        event.get("bot_id")
        or event.get("subtype")
        in {
            "bot_message",
            "message_changed",
            "message_deleted",
            "channel_join",
            "channel_leave",
        }
    )


_TITLES_FILE = "slack_chat_titles.json"


def _save_chat_titles(path: Path, titles: dict[int, str]) -> None:
    try:
        path.write_text(json.dumps({str(k): v for k, v in titles.items()}))
    except Exception as exc:
        log.warning("failed to save chat_titles: %s", exc)


class SlackDispatcher:
    def __init__(
        self,
        config: Config,
        db: Database,
        engine: EnginePort | None = None,
        *,
        chat_titles: dict[int, str] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.engine: EnginePort | None = engine
        self.chat_titles: dict[int, str] = chat_titles or {}
        self.rate_limiter = rate_limiter
        self._app = AsyncApp(token=config.slack_bot_token)
        self._handler: AsyncSocketModeHandler | None = None
        self._bot_user_id: str | None = None
        self._active_threads: set[str] = set()
        self._wire_handlers()

    @property
    def bot(self):
        return self._app.client

    def mark_thread_active(self, ts: str) -> None:
        self._active_threads.add(ts)

    async def send_text(self, chat_id: int, text: str) -> None:
        """Platform-agnostic send used by crash/giveup callbacks."""
        channel = self.config.slack_owner_id or str(chat_id)
        try:
            await self._app.client.chat_postMessage(channel=channel, text=text)
        except Exception as exc:
            log.warning("send_text to %s failed: %s", channel, exc)

    async def start_typing(self, chat_id: int) -> None:  # noqa: ARG002
        pass  # Slack bots cannot set typing indicators

    def _wire_handlers(self) -> None:
        self._app.event("message")(self._on_message)
        self._app.event("reaction_added")(self._on_reaction_added)
        self._app.event("member_joined_channel")(self._on_member_joined)
        self._app.event("app_mention")(self._on_app_mention)

    async def _on_app_mention(self, event: dict, client) -> None:  # noqa: ARG002
        pass  # handled via message event

    async def _on_message(self, event: dict, client) -> None:
        if _is_bot_event(event):
            return
        ct = event.get("channel_type", "")
        if ct == "im":
            await self._handle_dm(event, client)
        elif ct in ("channel", "group"):
            await self._handle_channel_msg(event, client)

    async def _handle_dm(self, event: dict, client) -> None:
        user, text = event.get("user", ""), event.get("text", "")
        if text.startswith("!") and self._is_owner(user):
            ch = event.get("channel", "")
            await dispatch_command(text[1:].strip(), ch, client, self.config, self.db)
            return
        await self._ingest_event(event, client, is_dm=True)

    async def _handle_channel_msg(self, event: dict, client) -> None:
        text = event.get("text") or ""
        bot_id = self._bot_user_id or ""
        if bot_id and f"<@{bot_id}>" in text:
            e = {**event, "text": strip_mention(text, bot_id)}
            await self._ingest_event(e, client, is_dm=False)
            return
        thread_ts = event.get("thread_ts")
        channel = event.get("channel", "")
        if (thread_ts and thread_ts in self._active_threads) or contains_bot_name(
            text, self.config.slack_bot_name
        ):
            await self._ingest_event(event, client, is_dm=False)
            return
        user_str = event.get("user", "")
        if user_str:
            name = self.config.slack_bot_name
            await maybe_post_intro(
                self._app.client, self.db, channel, user_str, thread_ts, name
            )

    async def _on_member_joined(self, event: dict, client) -> None:  # noqa: ARG002
        if event.get("user") == self._bot_user_id:
            return
        if channel := event.get("channel", ""):
            await handle_joined(self._app.client, channel, self.config.slack_bot_name)

    async def _on_reaction_added(self, event: dict, client) -> None:  # noqa: ARG002
        item_ts = event.get("item", {}).get("ts")
        log.debug("reaction_added: emoji=%s ts=%s", event.get("reaction"), item_ts)

    async def _ingest_event(self, event: dict, client, *, is_dm: bool) -> None:  # noqa: ARG002
        received_at = time.monotonic()
        cm = self._build_chat_message(event)
        if cm is None:
            return

        bot, channel = self._app.client, event.get("channel", "")
        ts, files = event.get("ts", ""), event.get("files") or []
        if files:
            markers = await process_slack_files(
                files, channel_id=channel, message_ts=ts, client=bot, config=self.config
            )
            if markers:
                suffix = "\n".join(markers)
                cm = cm.model_copy(
                    update={"text": f"{cm.text}\n{suffix}" if cm.text else suffix}
                )
        label = f"{'DM' if is_dm else 'CH'}:{channel}"
        if self.chat_titles.get(cm.chat_id) != label:
            self.chat_titles[cm.chat_id] = label
            _save_chat_titles(self.config.data_dir / _TITLES_FILE, self.chat_titles)
        await self._persist_inbound(cm)

        if not self._check_access(cm, is_dm):
            return
        if not await self._check_rate_limit(cm, is_dm):
            return
        if self.engine is None:
            log.error("dispatcher received message before engine was attached")
            return
        self.engine.prime_typing(cm.chat_id)
        t_ms = int((time.monotonic() - received_at) * 1000)
        log.info("submit chat=%s msg=%s t_ms=%d", cm.chat_id, cm.message_id, t_ms)
        await self.engine.submit(cm)

    def _build_chat_message(self, event: dict) -> ChatMessage | None:
        user_str = event.get("user", "")
        channel = event.get("channel", "")
        if not (user_str and channel and (ts := event.get("ts", ""))):
            return None
        text, flags = _clean(event.get("text") or "")
        return ChatMessage(
            chat_id=_int_id(channel),
            message_id=_ts_to_int(ts),
            user_id=_int_id(user_str),
            username=user_str,
            direction="in",
            timestamp=datetime.now(timezone.utc),
            text=text or "",
            thread_ts=event.get("thread_ts") or ts,
            input_flags=flags,
        )

    async def _persist_inbound(self, cm: ChatMessage) -> None:
        await insert_message(self.db, cm)
        await upsert_user(
            self.db, cm.chat_id, cm.user_id, cm.username, None, cm.timestamp
        )

    def _check_access(self, cm: ChatMessage, is_dm: bool) -> bool:
        owner_int = _int_id(self.config.slack_owner_id or "")
        access = load_access(self.config.access_path)
        if cm.user_id == owner_int:
            allowed = True
        elif access.policy == "owner_only":
            allowed = False
        elif access.policy == "open":
            allowed = True
        else:
            allowed = (
                is_dm and cm.user_id in {_int_id(str(u)) for u in access.allowed_users}
            ) or (
                not is_dm
                and cm.chat_id in {_int_id(str(c)) for c in access.allowed_chats}
            )
        log_inbound(
            chat_id=cm.chat_id,
            chat_type="im" if is_dm else "channel",
            chat_titles=self.chat_titles,
            user_id=cm.user_id,
            user_name=cm.username,
            message_id=cm.message_id,
            reply_to_id=None,
            text=cm.text,
            allowed=allowed,
        )
        return allowed

    async def _check_rate_limit(self, cm: ChatMessage, is_dm: bool) -> bool:
        if self.rate_limiter is None or not is_dm:
            return True
        try:
            await self.rate_limiter.check_and_record(cm.user_id)
        except RateLimitExceeded as exc:
            if exc.notify:
                try:
                    await self._app.client.chat_postMessage(
                        channel=cm.username or str(cm.chat_id),
                        text=f"Too fast: {exc.limit}/min, wait {exc.retry_after_s}s.",
                    )
                except Exception:
                    pass
            return False
        return True

    def _is_owner(self, slack_user_id: str) -> bool:
        return slack_user_id == (self.config.slack_owner_id or "")

    async def start(self) -> None:
        if self.engine is None:
            raise RuntimeError("SlackDispatcher.start: engine not attached")
        resp = await self._app.client.auth_test()
        self._bot_user_id = resp["user_id"]
        log.info("slack bot: %s (%s)", resp.get("user"), self._bot_user_id)
        self._handler = AsyncSocketModeHandler(
            self._app, self.config.slack_app_token or ""
        )
        asyncio.create_task(self._handler.start_async(), name="pyclaudir-slack-socket")
        log.info("slack dispatcher started (socket mode)")

    async def stop(self) -> None:
        if self._handler is not None:
            try:
                await self._handler.close_async()
            except Exception:
                log.exception("slack handler close failed")
        self._handler = None
