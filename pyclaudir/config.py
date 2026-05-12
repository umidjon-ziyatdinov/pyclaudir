"""All settings for pyclaudir, loaded from environment variables via Config.from_env()."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# python-dotenv loads variables from a .env file. It's optional so tests
# don't have to install it.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - best effort
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def _required(name: str) -> str:
    value = _env(name)
    if value is None:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from exc


def _resolve_auth(platform: str, slack_owner_id: str | None) -> tuple[str, int]:
    import zlib

    if platform != "slack":
        return _required("TELEGRAM_BOT_TOKEN"), int(_required("PYCLAUDIR_OWNER_ID"))
    tg_token = _env("TELEGRAM_BOT_TOKEN", "") or ""
    owner_id = zlib.crc32(slack_owner_id.encode()) & 0x7FFFFFFF if slack_owner_id else 0
    return tg_token, owner_id


def _from_env_kwargs(
    tg_token: str, owner_id: int, platform: str, slack_owner_id: str | None
) -> dict:
    cron = _env("PYCLAUDIR_SELF_REFLECTION_CRON", "30 8 * * *") or "30 8 * * *"
    save_raw = _env("PYCLAUDIR_SAVE_CHANNEL_MESSAGES", "true") or "true"
    return dict(
        telegram_bot_token=tg_token,
        owner_id=owner_id,
        model=_required("PYCLAUDIR_MODEL"),
        effort=_required("PYCLAUDIR_EFFORT"),
        claude_code_bin=_env("CLAUDE_CODE_BIN", "claude") or "claude",
        data_dir=Path(_env("PYCLAUDIR_DATA_DIR", "./data") or "./data").resolve(),
        self_reflection_cron=cron,
        debounce_ms=_int("PYCLAUDIR_DEBOUNCE_MS", 0),
        rate_limit_per_min=_int("PYCLAUDIR_RATE_LIMIT_PER_MIN", 20),
        attachment_max_bytes=_int("PYCLAUDIR_ATTACHMENT_MAX_BYTES", 20_000_000),
        tool_error_max_count=_int("PYCLAUDIR_TOOL_ERROR_MAX_COUNT", 3),
        tool_error_window_seconds=_float("PYCLAUDIR_TOOL_ERROR_WINDOW_SECONDS", 30.0),
        progress_notify_seconds=_float("PYCLAUDIR_PROGRESS_NOTIFY_SECONDS", 60.0),
        liveness_timeout_seconds=_float("PYCLAUDIR_LIVENESS_TIMEOUT_SECONDS", 300.0),
        liveness_poll_seconds=_float("PYCLAUDIR_LIVENESS_POLL_SECONDS", 30.0),
        crash_backoff_base=_float("PYCLAUDIR_CRASH_BACKOFF_BASE", 2.0),
        crash_backoff_cap=_float("PYCLAUDIR_CRASH_BACKOFF_CAP", 64.0),
        crash_limit=_int("PYCLAUDIR_CRASH_LIMIT", 10),
        crash_window_seconds=_float("PYCLAUDIR_CRASH_WINDOW_SECONDS", 600.0),
        platform=platform,
        slack_bot_token=_env("SLACK_BOT_TOKEN"),
        slack_app_token=_env("SLACK_APP_TOKEN"),
        slack_owner_id=slack_owner_id,
        slack_bot_name=_env("SLACK_BOT_NAME"),
        openwebui_api_url=_env("OPENWEBUI_API_URL"),
        openwebui_api_key=_env("OPENWEBUI_API_KEY"),
        openwebui_kb_uuid=_env("OPENWEBUI_KB_UUID"),
        atlassian_api_token=_env("ATLASSIAN_API_TOKEN"),
        github_token=_env("GITHUB_TOKEN"),
        slack_workspace_url=_env("SLACK_WORKSPACE_URL"),
        save_channel_messages=save_raw.lower() not in {"false", "0", "no"},
    )


@dataclass(frozen=True)
class Config:
    """All settings the bot uses at runtime."""

    #: The bot's API token from @BotFather. Used to log in to Telegram.
    #: Env var: ``TELEGRAM_BOT_TOKEN`` (required).
    telegram_bot_token: str
    #: Telegram user ID of the bot's owner (you). Owner-only commands
    #: like ``/kill`` and ``/access`` check this. Direct-message-only
    #: mode also uses it to decide who can talk to the bot.
    #: Env var: ``PYCLAUDIR_OWNER_ID`` (required).
    owner_id: int
    #: Which Claude model to use. Passed to ``claude --model``.
    #: Env var: ``PYCLAUDIR_MODEL`` (required).
    model: str
    #: How hard Claude thinks before answering. Passed to ``claude --effort``.
    #: Env var: ``PYCLAUDIR_EFFORT`` (required, e.g. ``"high"``).
    effort: str
    #: Name or full path of the ``claude`` program to run.
    #: Env var: ``CLAUDE_CODE_BIN`` (default ``"claude"``).
    claude_code_bin: str
    #: Folder where the bot stores its data: the database, memory files,
    #: claude logs, the access list, and the session ID. The folder is
    #: created automatically by ``ensure_dirs``.
    #: Env var: ``PYCLAUDIR_DATA_DIR`` (default ``"./data"``).
    data_dir: Path
    #: When the daily self-reflection task runs. Standard cron format,
    #: in UTC time.
    #: Env var: ``PYCLAUDIR_SELF_REFLECTION_CRON`` (default ``"30 8 * * *"``,
    #: which means 08:30 UTC / 17:30 KST every day).
    self_reflection_cron: str
    #: How long to wait (in milliseconds) after a message before sending
    #: it to Claude. If more messages come in during this wait, they are
    #: bundled together into one turn. Set to ``0`` to send each message
    #: right away.
    #: Env var: ``PYCLAUDIR_DEBOUNCE_MS`` (default ``0``).
    debounce_ms: int
    #: Max messages per minute the bot will accept from one user in
    #: direct messages. The owner is not limited. Group chats are not
    #: limited either.
    #: Env var: ``PYCLAUDIR_RATE_LIMIT_PER_MIN`` (default ``20``).
    rate_limit_per_min: int
    # Tool-group toggles (subagents / bash / code) live in
    # ``plugins.json`` ``tool_groups`` — single source of truth.
    # Boot-time only: edit the file and restart.
    #: Per-file size cap (bytes) for inbound attachments. Files larger than
    #: this are rejected without download. 20 MB by default.
    #: Env var: ``PYCLAUDIR_ATTACHMENT_MAX_BYTES`` (default 20_000_000).
    attachment_max_bytes: int
    #: Which messaging platform to use. ``"telegram"`` (default) or
    #: ``"slack"``. Env var: ``PYCLAUDIR_PLATFORM``.
    platform: str
    #: Slack Bot Token (``xoxb-...``). Required when ``platform="slack"``.
    #: Env var: ``SLACK_BOT_TOKEN``.
    slack_bot_token: str | None
    #: Slack App-Level Token (``xapp-...``) for Socket Mode.
    #: Required when ``platform="slack"``. Env var: ``SLACK_APP_TOKEN``.
    slack_app_token: str | None
    #: Slack User ID of the bot owner (e.g. ``"U012AB3CD"``).
    #: Required when ``platform="slack"``. Env var: ``SLACK_OWNER_ID``.
    slack_owner_id: str | None

    # ----- Settings for handling tool errors -----
    #: How many tool errors are allowed before the bot gives up. Used
    #: in two places: (1) inside one turn — too many failed tool calls
    #: stops the turn; (2) across turns — too many empty replies in a
    #: row stops retrying.
    #: Env var: ``PYCLAUDIR_TOOL_ERROR_MAX_COUNT`` (default 3).
    tool_error_max_count: int
    #: Time-based version of the rule above. If errors keep coming in
    #: for this many seconds after the first one, the bot stops the
    #: turn — even if the count is still under the limit.
    #: Env var: ``PYCLAUDIR_TOOL_ERROR_WINDOW_SECONDS`` (default 30).
    tool_error_window_seconds: float
    #: If Claude hasn't sent a message to a chat after this many seconds,
    #: the bot posts "One moment..." as a reply to the
    #: user's original message, so they know it's still working.
    #: Env var: ``PYCLAUDIR_PROGRESS_NOTIFY_SECONDS`` (default 60).
    progress_notify_seconds: float

    # ----- Settings for spotting a stuck Claude process -----
    #: Max seconds of silence allowed during a turn. If Claude produces
    #: no output and no tool activity for longer than this, the watcher
    #: kills it. Silence between turns (when the bot is idle) is fine
    #: and ignored.
    #: Env var: ``PYCLAUDIR_LIVENESS_TIMEOUT_SECONDS`` (default 300).
    liveness_timeout_seconds: float
    #: How often the watcher wakes up to check. Smaller numbers catch a
    #: stuck process sooner but use a bit more CPU.
    #: Env var: ``PYCLAUDIR_LIVENESS_POLL_SECONDS`` (default 30).
    liveness_poll_seconds: float

    # ----- Settings for restarting Claude after a crash -----
    #: How long to wait before the first restart, in seconds. Each
    #: extra crash doubles the wait (``base * 2^(n-1)``), up to
    #: ``crash_backoff_cap``. Smaller = recovers faster from a one-off
    #: glitch but spins more on real problems.
    #: Env var: ``PYCLAUDIR_CRASH_BACKOFF_BASE`` (default 2.0).
    crash_backoff_base: float
    #: Maximum wait between restarts. Once the wait reaches this value,
    #: it stops growing. Stops the bot from waiting minutes between
    #: retries when something is really wrong.
    #: Env var: ``PYCLAUDIR_CRASH_BACKOFF_CAP`` (default 64.0).
    crash_backoff_cap: float
    #: How many crashes within ``crash_window_seconds`` count as "too
    #: many". When this is reached, the bot tells the owner and active
    #: chats, then exits.
    #: Env var: ``PYCLAUDIR_CRASH_LIMIT`` (default 10).
    crash_limit: int
    #: Time window used together with ``crash_limit``. Only crashes
    #: from the last ``crash_window_seconds`` are counted.
    #: Env var: ``PYCLAUDIR_CRASH_WINDOW_SECONDS`` (default 600.0,
    #: which is 10 minutes).
    crash_window_seconds: float

    # ----- Wiki / RAG / external integration -----
    #: Trigger name for channel messages — bot responds when this word appears
    #: (whole-word match, case-insensitive). E.g. ``"lloyd"``.
    #: Env var: ``SLACK_BOT_NAME``.
    slack_bot_name: str | None = None
    openwebui_api_url: str | None = None  # OPENWEBUI_API_URL
    openwebui_api_key: str | None = None  # OPENWEBUI_API_KEY
    openwebui_kb_uuid: str | None = None  # OPENWEBUI_KB_UUID
    atlassian_api_token: str | None = None  # ATLASSIAN_API_TOKEN
    github_token: str | None = None  # GITHUB_TOKEN
    slack_workspace_url: str | None = None  # SLACK_WORKSPACE_URL
    save_channel_messages: bool = True  # PYCLAUDIR_SAVE_CHANNEL_MESSAGES

    # Derived paths
    db_path: Path = field(init=False)
    memories_dir: Path = field(init=False)
    session_id_path: Path = field(init=False)
    cc_logs_dir: Path = field(init=False)
    access_path: Path = field(init=False)
    attachments_dir: Path = field(init=False)
    renders_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", self.data_dir / "pyclaudir.db")
        object.__setattr__(self, "memories_dir", self.data_dir / "memories")
        object.__setattr__(self, "session_id_path", self.data_dir / "session_id")
        object.__setattr__(self, "cc_logs_dir", self.data_dir / "cc_logs")
        # access.json sits at the repo root alongside plugins.json — both
        # are operator-edited config files, not runtime state, so they
        # don't belong in data/. Tests override this via for_test().
        project_root = Path(__file__).resolve().parent.parent
        object.__setattr__(self, "access_path", project_root / "access.json")
        object.__setattr__(self, "attachments_dir", self.data_dir / "attachments")
        object.__setattr__(self, "renders_dir", self.data_dir / "renders")

    @classmethod
    def from_env(cls) -> "Config":
        platform = _env("PYCLAUDIR_PLATFORM", "telegram") or "telegram"
        slack_owner_id = _env("SLACK_OWNER_ID")
        tg_token, owner_id = _resolve_auth(platform, slack_owner_id)
        return cls(**_from_env_kwargs(tg_token, owner_id, platform, slack_owner_id))

    @classmethod
    def for_test(cls, data_dir: Path) -> "Config":
        """Config with fixed test values — no environment variable reads."""
        cfg = cls(
            telegram_bot_token="test-token",
            owner_id=0,
            model="claude-opus-4-7",
            effort="high",
            claude_code_bin="claude",
            data_dir=data_dir.resolve(),
            self_reflection_cron="0 0 * * *",
            debounce_ms=1000,
            rate_limit_per_min=20,
            attachment_max_bytes=20_000_000,
            tool_error_max_count=3,
            tool_error_window_seconds=30.0,
            progress_notify_seconds=60.0,
            liveness_timeout_seconds=300.0,
            liveness_poll_seconds=30.0,
            crash_backoff_base=2.0,
            crash_backoff_cap=64.0,
            crash_limit=10,
            crash_window_seconds=600.0,
            platform="telegram",
            slack_bot_token=None,
            slack_app_token=None,
            slack_owner_id=None,
            slack_bot_name=None,
            openwebui_api_url=None,
            openwebui_api_key=None,
            openwebui_kb_uuid=None,
            atlassian_api_token=None,
            github_token=None,
            slack_workspace_url=None,
            save_channel_messages=True,
        )
        # Tests use isolated tmp dirs — keep access.json inside data_dir
        # so each test gets its own copy and never touches the repo root.
        object.__setattr__(cfg, "access_path", data_dir.resolve() / "access.json")
        return cfg

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        self.cc_logs_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
