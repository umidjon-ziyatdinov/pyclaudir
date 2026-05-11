---
title: Wiki Agent — Implementation Plan
---

# Wiki Agent

## Goal

Turn the Slack bot into a company-wide knowledge assistant. It watches every
channel it is invited to, learns from Confluence, Jira, GitHub, and the RAG
knowledge base, and answers questions with citations back to the original
source — Confluence URL, Jira ticket, Slack message permalink, or KB document.

## Business Value

Company knowledge is scattered: engineering decisions live in Slack threads,
specs in Confluence, tickets in Jira, code context in GitHub, and processed
documents in the RAG KB. A new team member (or any employee) currently has to
search all four manually. The wiki agent consolidates retrieval into a single
`@mention` and builds an incrementally-updated meta memory that gets smarter
every night.

---

## Architecture

```
INBOUND
  Slack DM / @mention ──────────────────────► Engine ──► Claude Code (CC)
  Slack channel message (bot invited) ──► SQLite only (no engine)

SOURCES CC CAN QUERY
  Rovo MCP (cloud)   ── Confluence read + search ──► searchConfluenceUsingCql
                     ── Jira read + search        ──► searchJiraIssuesUsingJql
  GitHub MCP (cloud) ── repo read / issues / PRs  ──► (repos supplied by user)
  RAG KB (tools)     ── kb_search tool            ──► POST /api/v1/retrieval/query/collection
  SQLite             ── query_db tool              ──► messages table (all channels)

NIGHTLY CRON  30 8 * * *  (05:30 KST = 08:30 UTC)
  1. Self-reflection (existing)
  2. Slack analysis  — query_db → extract topics/decisions → update meta/
  3. Confluence watch — searchConfluenceUsingCql lastModified≥today → kb_upload → update meta/
  4. Meta index rebuild — write_memory meta/_index.md

META MEMORY  data/memories/meta/
  _index.md          master topic map (agent-maintained)
  <topic>.md         per-topic summary + source links (Confluence URL,
                     Jira ticket, Slack permalink, KB doc name)
```

---

## Components

### Slack Multi-Channel Capture

The bot already saves DMs and @mentions to SQLite. Channel messages where the
bot is not mentioned are currently dropped before persistence. We change
`_on_message` to persist every channel message the bot receives (because it is
invited and the Slack API sends it), but without submitting to the engine. The
engine path (Claude) is only triggered by DMs and @mentions, exactly as today.

A `save_channel_messages` config flag (default `true`) lets an operator opt
out if needed.

Two new columns on `messages`:
- `slack_channel_id TEXT` — original Slack channel string (e.g. `C01234567`)
- `slack_message_ts TEXT` — original Slack timestamp (e.g. `1614012345.001234`)

Permalink formula used for citations:
```
https://{SLACK_WORKSPACE_URL}/archives/{slack_channel_id}/p{ts_no_dot}
```

### RAG Knowledge Base Tools

Two new `BaseTool` subclasses wrapping the OpenWebUI API:

**`kb_search`** — search the knowledge base.  
**`kb_upload`** — ingest a text document into the knowledge base (used by the
nightly skill to push new Confluence pages). Records every upload in the
`kb_ingestions` table to avoid re-indexing unchanged content.

Both tools use `OPENWEBUI_API_URL` and `OPENWEBUI_API_KEY`. The target
knowledge base is identified by `OPENWEBUI_KB_UUID`.

### Atlassian Rovo MCP

Cloud-hosted MCP server covering Confluence, Jira, Compass, and Bitbucket
under one endpoint. Auth is a Bearer API token — no local install.

```
url:  https://mcp.atlassian.com/v1/mcp/authv2
auth: Authorization: Bearer {ATLASSIAN_API_TOKEN}
```

Registered as an `extra_server` in `mcp_server.write_mcp_config`. Permission
groups on the Atlassian side are restricted to read-only scopes
(`read_confluence`, `search_confluence`, `read_jira`, `search_jira`) for v1.
Write support is designed in but not enabled.

### GitHub MCP

Official GitHub MCP server. Registered as an `extra_server` alongside Rovo.
The user supplies repo names in conversation; the agent uses the MCP tools for
README reads, open issues, recent PRs, and file lookups. No writes.

```
url:   https://api.githubcopilot.com/mcp/
auth:  Authorization: Bearer {GITHUB_TOKEN}
```

### Meta Memory Layer

Plain markdown files under `data/memories/meta/`. The agent writes and updates
these via existing `write_memory` and `append_memory` tools — no new code.

```
meta/_index.md        master topic list; checked before every QA answer
meta/<topic>.md       summary + links to Confluence pages, Jira tickets,
                      Slack permalinks, KB document names
```

A SKILL.md encodes the convention so the agent knows to maintain this
structure. Obsidian can be pointed at `data/memories/` for graph visualization
at any time — no code changes required.

### Wiki QA Skill (`skills/wiki-qa/SKILL.md`)

Routing playbook for answering questions:

1. Read `meta/_index.md` — identify relevant topic.
2. Read `meta/<topic>.md` — get source pointers.
3. Query RAG KB with `kb_search` for document chunks.
4. Query Rovo MCP (`searchConfluenceUsingCql` / `searchJiraIssuesUsingJql`) for live data.
5. Query `query_db` for relevant recent Slack messages if the topic is recent.
6. Synthesize answer — always include at least one citation (Confluence URL,
   Jira ticket key, Slack permalink, or KB document name).

### Wiki Nightly Skill (`skills/wiki-nightly/SKILL.md`)

Runs inside the existing self-reflection cron turn at `30 8 * * *`:

1. **Self-reflection** (existing) — query_db → analyse today's conversations.
2. **Slack analysis** — query_db for today's messages across all channels;
   extract decisions, open questions, recurring topics; append findings to
   relevant `meta/<topic>.md` files; add Slack permalinks as citations.
3. **Confluence watch** — `searchConfluenceUsingCql` with
   `lastModified >= startOfDay()`; for each page, compute content hash, compare
   against `kb_ingestions`; if new or changed, call `kb_upload` then update
   `kb_ingestions`; update `meta/<topic>.md` with page title + URL.
4. **Meta index update** — rewrite `meta/_index.md` to reflect any new topics
   discovered today.

---

## RAG API Reference (MVP subset)

Base URL: `OPENWEBUI_API_URL`  
Auth header: `Authorization: Bearer OPENWEBUI_API_KEY`

### Search — `POST /api/v1/retrieval/query/collection`

```json
{
  "collection_names": ["<OPENWEBUI_KB_UUID>"],
  "query": "How does auth work?",
  "k": 5,
  "hybrid": true,
  "hybrid_bm25_weight": 0.4
}
```

Response — parallel arrays indexed by chunk position:

```json
{
  "ids":       [["chunk-id-1", "chunk-id-2"]],
  "documents": [["chunk text 1", "chunk text 2"]],
  "metadatas": [[{"source": "file.pdf", "file_id": "uuid", "page_number": 3}]],
  "distances": [[0.92, 0.85]]
}
```

Access chunk `i` as `documents[0][i]`, `metadatas[0][i]`, `distances[0][i]`.
When `metadatas[0][i]["raw_text"]` exists, prefer it over `documents[0][i]`
(preserves table/HTML structure).

If Cognee is enabled on the KB, `documents[0][0]` will have
`metadatas[0][0]["source"] == "cognee-graph"` with `distances[0][0] == 1.0`.

### Upload — `POST /api/v1/knowledge/{OPENWEBUI_KB_UUID}/file/add`

First upload the file content:

```
POST /api/v1/files/
Content-Type: multipart/form-data
file=<bytes>         (filename: <title>.md or <title>.txt)
```

Returns `{"id": "<file_uuid>", ...}`.

Then add to the knowledge base with processing:

```
POST /api/v1/knowledge/{OPENWEBUI_KB_UUID}/file/add
{
  "file_id": "<file_uuid>",
  "process": true
}
```

The `process: true` flag triggers immediate chunking and embedding. The file is
indexed under the KB UUID collection and is searchable via `query/collection`
as soon as the response returns.

---

## Environment Variables

| Variable | Purpose | Required |
|---|---|---|
| `OPENWEBUI_API_URL` | Base URL of the OpenWebUI RAG platform | yes |
| `OPENWEBUI_API_KEY` | Bearer token for RAG API | yes |
| `OPENWEBUI_KB_UUID` | UUID of the target knowledge base collection | yes |
| `ATLASSIAN_API_TOKEN` | Bearer token for Rovo MCP | yes |
| `GITHUB_TOKEN` | Bearer token for GitHub MCP | yes |
| `SLACK_WORKSPACE_URL` | Base URL for Slack permalink construction (no trailing slash) | yes |
| `PYCLAUDIR_SAVE_CHANNEL_MESSAGES` | Save non-mention channel messages to SQLite (`true`/`false`, default `true`) | no |

---

## Implementation Steps

### Step 1 — Database Migrations

**`pyclaudir/db/migrations/006_slack_message_ids.sql`**

Add two columns to `messages`:

```sql
ALTER TABLE messages ADD COLUMN slack_channel_id TEXT;
ALTER TABLE messages ADD COLUMN slack_message_ts  TEXT;
```

**`pyclaudir/db/migrations/007_kb_ingestions.sql`**

```sql
CREATE TABLE IF NOT EXISTS kb_ingestions (
    id           INTEGER PRIMARY KEY,
    source_url   TEXT    NOT NULL,
    content_hash TEXT    NOT NULL,
    ingested_at  DATETIME NOT NULL,
    source_type  TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_ingestions_url
    ON kb_ingestions (source_url);
```

---

### Step 2 — ChatMessage Model

Add two optional fields to `ChatMessage` in `pyclaudir/models.py`:

```python
slack_channel_id: str | None = Field(default=None, exclude=True)
slack_message_ts:  str | None = Field(default=None, exclude=True)
```

`exclude=True` keeps them out of the XML envelope sent to the CC worker; they
are written to SQLite by `insert_message` directly.

---

### Step 3 — Slack Dispatcher: Channel Message Capture

Changes in `pyclaudir/slack_io/dispatcher.py`:

1. `_build_chat_message` — populate `slack_channel_id` from `event["channel"]`
   and `slack_message_ts` from `event["ts"]`.

2. `_on_message` — replace the hard `return` for non-DM messages with a
   persist-only path:

```python
if event.get("channel_type") != "im":
    if self.config.save_channel_messages:
        cm = self._build_chat_message(event)
        if cm is not None:
            await self._persist_inbound(cm)
    return
```

3. `_persist_inbound` — pass `slack_channel_id` and `slack_message_ts` through
   to `insert_message`.

Update `pyclaudir/db/messages.py` → `insert_message` to write the two new
columns when present.

---

### Step 4 — Config Extensions

Add to `Config` in `pyclaudir/config.py`:

```python
openwebui_api_url:          str | None   # OPENWEBUI_API_URL
openwebui_api_key:          str | None   # OPENWEBUI_API_KEY
openwebui_kb_uuid:          str | None   # OPENWEBUI_KB_UUID
atlassian_api_token:        str | None   # ATLASSIAN_API_TOKEN
github_token:               str | None   # GITHUB_TOKEN
slack_workspace_url:        str | None   # SLACK_WORKSPACE_URL
save_channel_messages:      bool         # PYCLAUDIR_SAVE_CHANNEL_MESSAGES (default True)
```

All are optional at boot; the RAG tools and MCP wiring log a warning and
no-op gracefully when missing.

---

### Step 5 — RAG Tools

**`pyclaudir/tools/kb_search.py`**

```
name:        kb_search
description: Search the company knowledge base. Returns relevant document
             chunks with source names and relevance scores.
args:
  query:   str
  k:       int = 5
  hybrid:  bool = True
```

Calls `POST /api/v1/retrieval/query/collection`. Returns formatted chunks:
`[score] source_name\n<chunk text>` for each result.

**`pyclaudir/tools/kb_upload.py`**

```
name:        kb_upload
description: Ingest a text document into the knowledge base. Records the
             upload in kb_ingestions to prevent duplicate indexing.
args:
  content:     str          (document text)
  title:       str          (display name / filename stem)
  source_url:  str          (canonical URL for citation and dedup)
  source_type: str          (e.g. "confluence", "manual")
```

Flow:
1. Compute `sha256(content)`.
2. Query `kb_ingestions` — if `source_url` exists and hash unchanged, return
   "already indexed, skipping".
3. `POST /api/v1/files/` with content as a `.md` file.
4. `POST /api/v1/knowledge/{KB_UUID}/file/add` with `{"file_id": ..., "process": true}`.
5. Upsert `kb_ingestions` row.

Both tools read credentials from `ToolContext` (passed through from `Config`
via the existing `ToolContext` construction in `__main__.py`). Add
`openwebui_api_url`, `openwebui_api_key`, `openwebui_kb_uuid` to `ToolContext`
in `pyclaudir/tools/base.py`.

---

### Step 6 — External MCP Servers

In `pyclaudir/__main__.py` (or wherever `write_mcp_config` is called), build
`extra_servers` from config:

```python
extra_servers: dict[str, dict] = {}

if config.atlassian_api_token:
    extra_servers["atlassian"] = {
        "type": "http",
        "url": "https://mcp.atlassian.com/v1/mcp/authv2",
        "headers": {"Authorization": f"Bearer {config.atlassian_api_token}"},
    }

if config.github_token:
    extra_servers["github"] = {
        "type": "http",
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": f"Bearer {config.github_token}"},
    }
```

Pass `extra_servers` to `mcp_server.write_mcp_config(extra_servers=extra_servers)`.
The `write_mcp_config` method already supports this — no changes to
`mcp_server.py` needed.

---

### Step 7 — Skills

**`skills/wiki-qa/SKILL.md`** — QA routing playbook (see Components section).

**`skills/wiki-nightly/SKILL.md`** — nightly pipeline playbook (see Components
section). Encodes the CQL query for Confluence:
`lastModified >= startOfDay() ORDER BY lastModified DESC`.

Both files require standard SKILL.md frontmatter:

```yaml
---
name: wiki-qa          # or wiki-nightly
description: <one line>
---
```

---

### Step 8 — Cron Adjustment

Change `PYCLAUDIR_SELF_REFLECTION_CRON` default from `0 0 * * *` to
`30 8 * * *` in `config.py`.

The cron expression `30 8 * * *` fires at 08:30 UTC = **17:30 KST (5:30 PM
Korean Standard Time, UTC+9)**.

Set the env var explicitly to override:

```env
PYCLAUDIR_SELF_REFLECTION_CRON=30 8 * * *
```

---

## Definition of Done

For each step, run before marking complete:

```bash
ruff check
ruff format --check
mypy
pytest
lizard -C 10 -L 40 -a 4
```

Fix all violations in the same step. No file >300 lines. No function >40 lines
or complexity >10. Type hints on every signature. `from __future__ import
annotations` at the top of every new file.
