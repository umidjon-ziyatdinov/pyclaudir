---
name: wiki-qa
description: Answer company knowledge questions by routing through meta memory, RAG KB, Atlassian Rovo, and Slack history, then synthesising a cited response.
license: MIT
compatibility: Requires pyclaudir runtime (kb_search, query_db, Atlassian Rovo MCP, GitHub MCP).
---

# Skill: wiki-qa

You are running the **wiki QA playbook**. Answer the question by following
every step below in order. Always include at least one citation in the final
answer (Confluence URL, Jira ticket key, Slack permalink, or KB document name).

## Step 1 — identify the topic

Read `meta/_index.md` via `read_memory`. Find the entry whose topic best
matches the question. If no entry matches, proceed without a topic file
(skip Step 2 and rely on Steps 3–5 only).

## Step 2 — load topic pointers

If a matching topic was found, read `meta/<topic>.md` via `read_memory`.
Collect all source pointers: Confluence URLs, Jira ticket keys, Slack
permalinks, KB document names.

## Step 3 — RAG KB search

Call `kb_search` with the user's question as the query (k=5, hybrid=true).
Keep any chunks with a relevance score above 0.5. Note the source document
names for citations.

## Step 4 — live Atlassian query

If Atlassian Rovo MCP is available:

- Call `searchConfluenceUsingCql` with a CQL query derived from the question
  keywords. Example: `text ~ "auth" ORDER BY lastModified DESC`.
- If the question involves tasks or tickets, also call `searchJiraIssuesUsingJql`
  with a relevant JQL query. Example: `text ~ "auth" ORDER BY updated DESC`.

Keep the top 3 results from each. Note page titles and URLs for citations.

## Step 5 — Slack context (recent topics only)

If the question appears to involve a recent decision or discussion (within
the past 30 days), call `query_db` to retrieve relevant Slack messages:

```sql
SELECT chat_id, text, timestamp, slack_channel_id, slack_message_ts
FROM messages
WHERE direction = 'in'
  AND timestamp > datetime('now', '-30 days')
  AND text LIKE '%<keyword>%'
ORDER BY timestamp DESC
LIMIT 20;
```

Construct Slack permalinks using:
`https://{SLACK_WORKSPACE_URL}/archives/{slack_channel_id}/p{ts_no_dot}`
where `ts_no_dot` is the `slack_message_ts` with the `.` removed.

## Step 6 — synthesise the answer

Combine findings from Steps 2–5 into a concise answer. Rules:

- Lead with the direct answer; citations follow inline.
- Include **at least one citation**. Prefer Confluence URL > Jira key >
  Slack permalink > KB document name.
- If sources contradict, note the conflict and cite both.
- If nothing relevant was found, say so clearly — do not fabricate.
- Keep the answer under 400 words unless the question demands detail.
