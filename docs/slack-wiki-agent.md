# Wiki Agent — Implementation Log (Steps 1–5)

## What Was Done

This document records what was implemented from `docs/wiki-agent-plan.md` Steps 1–5. Steps 6–8 (external MCP servers, skills, cron adjustment) were not part of this session.

---

### Step 1 — Database Migrations

Two new migration files:

- `pyclaudir/db/migrations/006_slack_message_ids.sql` — adds `slack_channel_id TEXT` and `slack_message_ts TEXT` columns to `messages`. Used for Slack permalink construction (`https://{SLACK_WORKSPACE_URL}/archives/{channel_id}/p{ts_no_dot}`).
- `pyclaudir/db/migrations/007_kb_ingestions.sql` — creates the `kb_ingestions` table with a `UNIQUE INDEX` on `source_url`. Records every document ingested into the knowledge base so `kb_upload` can skip unchanged content.

---

### Step 2 — ChatMessage Model

`pyclaudir/models.py` — added two `exclude=True` fields to `ChatMessage`:

```python
slack_channel_id: str | None = Field(default=None, exclude=True)
slack_message_ts:  str | None = Field(default=None, exclude=True)
```

`exclude=True` keeps them out of the XML envelope sent to the CC worker. They are persisted to SQLite directly by `insert_message`.

---

### Step 3 — Slack Dispatcher: Channel Message Capture

Changes in `pyclaudir/slack_io/dispatcher.py`:

1. **`_on_message`** — non-DM messages (channel events) now persist to SQLite instead of being silently dropped. Controlled by `config.save_channel_messages` (default `True`).
2. **`_build_chat_message`** — now populates `slack_channel_id` and `slack_message_ts` on every `ChatMessage`.
3. **`_apply_files`** — extracted from `_ingest_event` to keep that function under the 40-line limit.
4. **`_resolve_policy`** — extracted from `_check_access` to reduce cyclomatic complexity from 11 to ≤5 per function.

`pyclaudir/db/messages.py` — `insert_message` writes the two new columns when present on the `ChatMessage`.

---

### Step 4 — Config Extensions

`pyclaudir/config.py` — seven new fields on `Config`:

| Field | Env Var | Default |
|---|---|---|
| `openwebui_api_url` | `OPENWEBUI_API_URL` | `None` |
| `openwebui_api_key` | `OPENWEBUI_API_KEY` | `None` |
| `openwebui_kb_uuid` | `OPENWEBUI_KB_UUID` | `None` |
| `atlassian_api_token` | `ATLASSIAN_API_TOKEN` | `None` |
| `github_token` | `GITHUB_TOKEN` | `None` |
| `slack_workspace_url` | `SLACK_WORKSPACE_URL` | `None` |
| `save_channel_messages` | `PYCLAUDIR_SAVE_CHANNEL_MESSAGES` | `True` |

All are optional at boot. Tools log a warning and no-op gracefully when credentials are missing.

Two module-level helpers were extracted (`_resolve_auth`, `_from_env_kwargs`) to keep `from_env()` under the 40-line function limit while accommodating all new kwargs.

---

### Step 5 — RAG Tools

Three changes:

**`pyclaudir/tools/base.py`** — `ToolContext` gets three new optional fields:
```python
openwebui_api_url: str | None = None
openwebui_api_key: str | None = None
openwebui_kb_uuid: str | None = None
```

**`pyclaudir/__main__.py`** — `ToolContext` construction now passes the three new fields from `config`.

**`pyclaudir/tools/kb_search.py`** (new, 75 lines) — `kb_search` tool. Calls `POST /api/v1/retrieval/query/collection`. Returns formatted chunks as `[score] source\ntext` blocks. Logs a warning and returns an error result when OpenWebUI config is missing.

**`pyclaudir/tools/kb_upload.py`** (new, 108 lines) — `kb_upload` tool. Flow:
1. SHA-256 content hash.
2. Check `kb_ingestions` — skip if `source_url` exists with same hash.
3. `POST /api/v1/files/` — upload as `.md` file.
4. `POST /api/v1/knowledge/{KB_UUID}/file/add` with `"process": true`.
5. Upsert `kb_ingestions` row (`INSERT OR REPLACE`).

Both tools use `httpx.AsyncClient` (now an explicit dependency).

---

## Files Changed

| File | Lines | Notes |
|---|---|---|
| `pyclaudir/db/migrations/006_slack_message_ids.sql` | 2 | new |
| `pyclaudir/db/migrations/007_kb_ingestions.sql` | 9 | new |
| `pyclaudir/models.py` | 72 | +5 lines |
| `pyclaudir/config.py` | 300 | refactored to stay ≤300 |
| `pyclaudir/db/messages.py` | 266 | +4 lines |
| `pyclaudir/tools/base.py` | 171 | +3 lines |
| `pyclaudir/tools/kb_search.py` | 75 | new |
| `pyclaudir/tools/kb_upload.py` | 108 | new |
| `pyclaudir/slack_io/dispatcher.py` | 293 | refactored CCN + channel capture |
| `pyclaudir/__main__.py` | 597 | +3 lines (pre-existing 300-line violation) |

---

## New Dependency

`httpx>=0.27` added to `pyproject.toml` (was already a transitive dep; now explicit).

---

## Env Vars the Operator Must Set

```env
# Required for kb_search and kb_upload:
OPENWEBUI_API_URL=https://your-openwebui-instance.example.com
OPENWEBUI_API_KEY=sk-...
OPENWEBUI_KB_UUID=<uuid of the target knowledge base collection>

# Required for Atlassian Rovo MCP (Step 6, not yet wired):
ATLASSIAN_API_TOKEN=<Atlassian API token>

# Required for GitHub MCP (Step 6, not yet wired):
GITHUB_TOKEN=ghp_...

# Required for Slack permalink construction in citations:
SLACK_WORKSPACE_URL=https://yourworkspace.slack.com

# Optional — set to "false" to stop saving non-mention channel messages:
PYCLAUDIR_SAVE_CHANNEL_MESSAGES=true
```

---

## Known Pre-existing Violations (Not Introduced Here)

- `__main__.py`: 597 lines (pre-existing, > 300 limit).
- `SlackDispatcher.__init__` and `TelegramDispatcher.__init__`: 6 params each (pre-existing).
- Several functions in `db/messages.py` and `tools/base.py`: 5–6 params (pre-existing).
- 3 test failures (`test_progress_notify`, `test_add_reaction_validation`): pre-existing, confirmed by `git stash` verification.
