---
name: wiki-nightly
description: Nightly pipeline that runs self-reflection, then analyses today's Slack messages and Confluence changes to update the meta memory layer with fresh citations.
license: MIT
compatibility: Requires pyclaudir runtime (kb_search, kb_upload, query_db, write_memory, read_memory, Atlassian Rovo MCP).
metadata:
  pyclaudir-auto-seed-key: wiki-nightly-default
  pyclaudir-invocation: '<skill name="wiki-nightly">run</skill>'
---

# Skill: wiki-nightly

You are running the **wiki nightly pipeline**. Follow every phase below in
order. This skill extends the self-reflection cron turn — run it after the
self-reflection skill completes.

## Phase 1 — self-reflection

Run the `self-reflection` skill first (standard playbook). This phase is
unchanged from the base bot. Complete it fully before continuing to Phase 2.

## Phase 2 — Slack analysis

Summarise today's channel messages and update meta memory with discoveries.

### 2.1 — pull today's messages

```sql
SELECT chat_id, text, timestamp, slack_channel_id, slack_message_ts, username
FROM messages
WHERE direction = 'in'
  AND timestamp > datetime('now', '-1 day')
ORDER BY timestamp ASC;
```

### 2.2 — extract signal

From the messages, identify:

- **Decisions made** — "we decided to…", "going with…", "approved".
- **Open questions** — "does anyone know…", "who owns…", unresolved threads.
- **Recurring topics** — any subject that appears in 3+ messages.

Skip casual chat, greetings, and noise.

### 2.3 — update meta files

For each significant finding:

1. Map it to a topic slug (e.g. `auth`, `deploy`, `onboarding`).
2. `read_memory(f"meta/{topic}.md")` — create from scratch if absent.
3. Append a dated entry with the finding and Slack citations:

```
## <YYYY-MM-DD> Slack

- <one-line summary>
  Source: https://{SLACK_WORKSPACE_URL}/archives/{channel_id}/p{ts_no_dot}
```

4. `write_memory(f"meta/{topic}.md", <updated content>)`.

Build Slack permalinks as:
`https://{SLACK_WORKSPACE_URL}/archives/{slack_channel_id}/p{ts_no_dot}`
where `ts_no_dot` = `slack_message_ts` with `.` removed.

## Phase 3 — Confluence watch

Ingest pages modified today into the RAG KB and update meta memory.

### 3.1 — search for today's changes

Call `searchConfluenceUsingCql`:

```
lastModified >= startOfDay() ORDER BY lastModified DESC
```

### 3.2 — ingest changed pages

For each page returned:

1. Retrieve the page content (use Rovo MCP `getConfluencePage` or equivalent).
2. Call `kb_upload` with:
   - `content` = page body (plain text or markdown)
   - `title` = page title
   - `source_url` = Confluence page URL
   - `source_type` = "confluence"
3. If `kb_upload` returns "already indexed, skipping" the content is
   unchanged — skip the meta update for that page.

### 3.3 — update meta files

For each newly ingested page:

1. Map the page space/title to a topic slug.
2. `read_memory(f"meta/{topic}.md")`.
3. Append a dated entry:

```
## <YYYY-MM-DD> Confluence

- <page title>
  URL: <Confluence page URL>
```

4. `write_memory(f"meta/{topic}.md", <updated content>)`.

## Phase 4 — meta index rebuild

Rewrite `meta/_index.md` to reflect all topics now present.

1. List all files under `meta/` (use `list_memories` if available, or
   track topics from Phases 2–3 in memory).
2. `read_memory("meta/_index.md")` — create from scratch if absent.
3. Rebuild as a simple markdown table:

```
## Topic index — updated <YYYY-MM-DD>

| Topic | Latest entry | Key sources |
|---|---|---|
| auth | 2025-01-15 | Confluence: ..., Slack: ... |
```

4. `write_memory("meta/_index.md", <new content>)`.

## Completion

After Phase 4, send a short message to the owner DM. Write it like a
brief note to a colleague, not a log entry. What actually stood out
today. What might need attention. One or two specific details, not
just counts.

Example shape (do not copy verbatim, adapt to what actually happened):

```
[One honest sentence about the day's volume or tone]

[One or two specific things that stood out, with a detail. A topic
that keeps coming up. A conflict between docs. A Jira ticket that is
overdue but frequently mentioned. A Slack decision that never reached
Confluence.]

[What was indexed and what was skipped, one short line.]
```

If nothing interesting happened, say that plainly. "Quiet day. No
conflicts, no surprises. Two Confluence pages indexed." is fine.

Then `stop`.
