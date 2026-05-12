"""Slack Socket Mode dispatcher (mirrors TelegramDispatcher lifecycle)."""

from __future__ import annotations

import logging
import time
import zlib
from datetime import datetime, timezone
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
from .formatter import strip_mention

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
        self.chat_titles: dict[int, str] = (
            chat_titles if chat_titles is not None else {}
        )
        self.rate_limiter = rate_limiter
        self._app = AsyncApp(token=config.slack_bot_token)
        self._handler: AsyncSocketModeHandler | None = None
        self._bot_user_id: str | None = None
        self._wire_handlers()

    @property
    def bot(self):
        return self._app.client

    async def send_text(self, chat_id: int, text: str) -> None:
        """Platform-agnostic send used by crash/giveup callbacks."""
        channel = self.config.slack_owner_id or str(chat_id)
        try:
            await self._app.client.chat_postMessage(channel=channel, text=text)
        except Exception as exc:
            log.warning("send_text to %s failed: %s", channel, exc)

    async def start_typing(self, chat_id: int) -> None:  # noqa: ARG002
        """No-op — Slack bots cannot set typing indicators."""

    def _wire_handlers(self) -> None:
        self._app.event("message")(self._on_message)
        self._app.event("app_mention")(self._on_app_mention)
        self._app.event("reaction_added")(self._on_reaction_added)

    async def _on_message(self, event: dict, client) -> None:
        if _is_bot_event(event):
            return
        if event.get("channel_type") != "im":
            if self.config.save_channel_messages:
                cm = self._build_chat_message(event)
                if cm is not None:
                    await self._persist_inbound(cm)
            return
        user = event.get("user", "")
        text = event.get("text", "")
        if text.startswith("!") and self._is_owner(user):
            await dispatch_command(
                text[1:].strip(),
                event.get("channel", ""),
                client,
                self.config,
                self.db,
            )
            return
        await self._ingest_event(event, client, is_dm=True)

    async def _on_app_mention(self, event: dict, client) -> None:
        log.info("app_mention received user=%s channel=%s", event.get("user"), event.get("channel"))
        if _is_bot_event(event):
            return
        patched = dict(event)
        patched["text"] = strip_mention(event.get("text", ""), self._bot_user_id or "")
        await self._ingest_event(patched, client, is_dm=False)

    async def _on_reaction_added(self, event: dict, client) -> None:  # noqa: ARG002
        log.debug(
            "reaction_added: emoji=%s ts=%s",
            event.get("reaction"),
            event.get("item", {}).get("ts"),
        )

    async def _apply_files(self, event: dict, cm: ChatMessage) -> ChatMessage:
        files = event.get("files") or []
        if not files:
            return cm
        markers = await process_slack_files(
            files,
            channel_id=event.get("channel", ""),
            message_ts=event.get("ts", ""),
            client=self._app.client,
            config=self.config,
        )
        if not markers:
            return cm
        suffix = "\n".join(markers)
        return cm.model_copy(
            update={"text": f"{cm.text}\n{suffix}" if cm.text else suffix}
        )

    async def _ingest_event(self, event: dict, client, *, is_dm: bool) -> None:  # noqa: ARG002
        received_at = time.monotonic()
        cm = self._build_chat_message(event)
        if cm is None:
            return
        cm = await self._apply_files(event, cm)
        channel = event.get("channel", "")
        self.chat_titles[cm.chat_id] = f"{'DM' if is_dm else 'CH'}:{channel}"
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
        log.info(
            "hot-path stage=submit chat=%s msg=%s t_ms=%d",
            cm.chat_id,
            cm.message_id,
            t_ms,
        )
        await self.engine.submit(cm)

    def _build_chat_message(self, event: dict) -> ChatMessage | None:
        user_str = event.get("user", "")
        channel = event.get("channel", "")
        ts = event.get("ts", "")
        if not (user_str and channel and ts):
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
            slack_channel_id=channel,
            slack_message_ts=ts,
        )

    async def _persist_inbound(self, cm: ChatMessage) -> None:
        await insert_message(self.db, cm)
        await upsert_user(
            self.db,
            chat_id=cm.chat_id,
            user_id=cm.user_id,
            username=cm.username,
            first_name=None,
            timestamp=cm.timestamp,
        )

    def _resolve_policy(self, cm: ChatMessage, is_dm: bool) -> bool:
        owner_int = _int_id(self.config.slack_owner_id or "")
        access = load_access(self.config.access_path)
        if cm.user_id == owner_int:
            return True
        if access.policy == "owner_only":
            return False
        if access.policy == "open":
            return True
        if is_dm:
            return cm.user_id in {_int_id(str(u)) for u in access.allowed_users}
        return cm.chat_id in {_int_id(str(c)) for c in access.allowed_chats}

    def _check_access(self, cm: ChatMessage, is_dm: bool) -> bool:
        allowed = self._resolve_policy(cm, is_dm)
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
                        text=(
                            f"You're sending messages too fast ({exc.limit}/min). "
                            f"Try again in ~{exc.retry_after_s}s."
                        ),
                    )
                except Exception:
                    pass
            return False
        return True

    def _is_owner(self, slack_user_id: str) -> bool:
        return slack_user_id == (self.config.slack_owner_id or "")

    async def start(self) -> None:
        if self.engine is None:
            raise RuntimeError(
                "SlackDispatcher.start() called with no engine attached."
            )
        resp = await self._app.client.auth_test()
        self._bot_user_id = resp["user_id"]
        log.info(
            "slack bot authenticated as %s (%s)", resp.get("user"), self._bot_user_id
        )
        self._handler = AsyncSocketModeHandler(
            self._app, self.config.slack_app_token or ""
        )
        import asyncio

        asyncio.create_task(self._handler.start_async(), name="pyclaudir-slack-socket")
        log.info("slack dispatcher started (socket mode)")

    async def stop(self) -> None:
        if self._handler is not None:
            try:
                await self._handler.close_async()
            except Exception:
                log.exception("slack handler close failed")
        self._handler = None
