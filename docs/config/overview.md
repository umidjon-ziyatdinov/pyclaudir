---
title: Config
---

# Config

All configuration lives in `config.py` as a frozen dataclass. Loaded once at startup from environment variables (via `.env`).

**File:** `pyclaudir/config.py`

## Required Variables

| Variable | Type | Description |
|----------|------|-------------|
| `TELEGRAM_BOT_TOKEN` | str | Bot API token from @BotFather |
| `PYCLAUDIR_OWNER_ID` | int | Numeric Telegram user ID of the owner |
| `PYCLAUDIR_MODEL` | str | Claude model ID, e.g. `claude-opus-4-7` |
| `PYCLAUDIR_EFFORT` | str | `low` / `medium` / `high` / `max` |

Missing any required variable raises a startup error with a clear message.

## Optional Variables

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_CODE_BIN` | `"claude"` | Path to the `claude` binary |
| `PYCLAUDIR_DATA_DIR` | `./data` | Root directory for all persisted data |
| `PYCLAUDIR_DEBOUNCE_MS` | `0` | Message batching window in milliseconds |
| `PYCLAUDIR_RATE_LIMIT_PER_MIN` | `20` | Max DMs per minute per user (owner exempt) |
| `PYCLAUDIR_SELF_REFLECTION_CRON` | `"0 0 * * *"` | UTC cron for daily self-reflection skill |

### Timeouts

| Variable | Default | Description |
|----------|---------|-------------|
| `PYCLAUDIR_TOOL_ERROR_MAX_COUNT` | `3` | Errors before engine stops a turn |
| `PYCLAUDIR_TOOL_ERROR_WINDOW_SECONDS` | `30.0` | Rolling window for error counting |
| `PYCLAUDIR_PROGRESS_NOTIFY_SECONDS` | `60.0` | Seconds before "One moment…" is sent |
| `PYCLAUDIR_LIVENESS_TIMEOUT_SECONDS` | `300.0` | CC silence threshold before kill+respawn |
| `PYCLAUDIR_LIVENESS_POLL_SECONDS` | `30.0` | Watchdog check interval |
| `PYCLAUDIR_ATTACHMENT_MAX_BYTES` | `20_000_000` | Max inbound media size (20 MB) |

### Crash Recovery

| Variable | Default | Description |
|----------|---------|-------------|
| `PYCLAUDIR_CRASH_BACKOFF_BASE` | `2.0` | First restart wait (seconds) |
| `PYCLAUDIR_CRASH_BACKOFF_CAP` | `64.0` | Maximum restart wait (seconds) |
| `PYCLAUDIR_CRASH_LIMIT` | `10` | Crash count before CrashLoop |
| `PYCLAUDIR_CRASH_WINDOW_SECONDS` | `600.0` | Time window for crash counting |

## Derived Paths

Computed in `__post_init__` from `PYCLAUDIR_DATA_DIR`:

| Attribute | Path |
|-----------|------|
| `db_path` | `data/pyclaudir.db` |
| `memories_dir` | `data/memories/` |
| `session_id_path` | `data/session_id` |
| `cc_logs_dir` | `data/cc_logs/` |
| `attachments_dir` | `data/attachments/` |
| `renders_dir` | `data/renders/` |
| `access_path` | `access.json` (repo root) |

## File-Based Config

These files are not environment variables but complement `config.py`:

| File | Git-tracked | Purpose |
|------|-------------|---------|
| `.env` | No | All env vars (secrets) |
| `prompts/project.md` | No | Bot personality overlay |
| `access.json` | No | Chat access policy (hot-reloaded) |
| `plugins.json` | No | Tool groups + external MCPs |
| `prompts/system.md` | Yes | Base system prompt (read-only) |

## Config Dataclass Pattern

```python
@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    owner_id: int
    model: str
    effort: str
    ...
    
    @classmethod
    def from_env(cls) -> Config: ...
    
    @classmethod
    def for_test(cls, **overrides) -> Config: ...
```

`frozen=True` prevents accidental mutation after startup. `for_test()` provides test fixtures with sensible defaults.
