---
title: Wiki Agent — Testing & Exploration Plan
purpose: Validate, optimize, and discover the wiki agent's capabilities and limitations
---

# Wiki Agent — Testing & Exploration Plan

Primary goal: **explore, brainstorm new features, find flaws and fix, optimize, test**

This plan treats the wiki agent as an MVP ready for real-world use. We will stress-test it, measure quality, find edge cases, and plan v2 improvements.

---

## Phase 1 — Setup Verification

### 1.1 Config & Environment

**Checklist:**
- [ ] All env vars set: `OPENWEBUI_API_URL`, `OPENWEBUI_API_KEY`, `OPENWEBUI_KB_UUID`, `ATLASSIAN_API_TOKEN`, `GITHUB_TOKEN`, `SLACK_WORKSPACE_URL`
- [ ] `.env` file loaded correctly: `python -c "from pyclaudir.config import Config; c = Config.from_env(); print(c.openwebui_api_url)"`
- [ ] Bot started without config errors: `python -m pyclaudir 2>&1 | grep -i error | head -5`
- [ ] MCP servers loaded: check CC logs for "registered MCP tool" entries for Rovo + GitHub
- [ ] SQLite migrations applied: `sqlite3 data/pyclaudir.db "SELECT name FROM sqlite_master WHERE type='table';" | grep kb_ingestions`

### 1.2 Tool Availability

In a Slack DM, send: `@bot list_skills` (should include `wiki-qa` and `wiki-nightly`)

Then test tool discovery:
```
@bot I want to test kb_search. Can you try searching the KB for "authentication"?
```

Expected: bot calls `kb_search`, returns chunks with scores, or logs "kb_search unavailable: missing config" if OpenWebUI is down.

### 1.3 Memory System

Check that meta memory structure exists and is readable:

```bash
ls -la data/memories/meta/
```

Expected: empty at start (agent creates files on first nightly run).

---

## Phase 2 — MVP Functionality Tests

### 2.1 Single-Source QA (no meta memory yet)

**Test: Confluence-only answer**

1. In Slack, add a Confluence page (or use an existing one) with clear text: "Our authentication uses OAuth2 with Azure AD."
2. DM the bot: `@bot How do we authenticate users?`
3. Expected: bot finds the Confluence page via Rovo MCP, cites the URL.
4. Measure: latency, citation accuracy.

**Test: Jira-only answer**

1. Create a Jira ticket with a clear title: "Deploy service to production"
2. DM: `@bot What's the status of the production deployment?`
3. Expected: bot finds the Jira ticket via Rovo, cites the ticket key.

**Test: KB-only answer**

1. Upload a markdown file to the OpenWebUI KB: "## Refund Policy: All refunds within 30 days."
2. DM: `@bot What's the refund policy?`
3. Expected: bot finds the KB doc via `kb_search`, cites the document name.

**Test: Slack-only answer (no other sources)**

1. In a channel where the bot is invited, post: "We decided to use PostgreSQL for the main DB on 2026-05-08."
2. Wait for the channel message to be saved (should happen immediately via dispatcher).
3. DM: `@bot What database did we choose?`
4. Expected: bot queries `query_db`, finds the message, constructs the Slack permalink, cites it.

### 2.2 Multi-Source Answer (the power test)

**Test: Synthesis across all four sources**

Set up test data:
- **Confluence**: "Authentication is OAuth2"
- **Jira**: "Ticket AUTH-456: Add OIDC support (In Progress)"
- **KB**: "OAuth2 requires client_id and client_secret"
- **Slack**: "Let's also support SAML for enterprise customers"

DM: `@bot What are the authentication requirements?`

Expected: bot synthesizes all four sources, orders them (Confluence → Jira → KB → Slack), and provides one unified answer with citations to all.

**Measure:**
- Latency (how long does parallel search take?)
- Citation accuracy (are the URLs/keys correct?)
- Relevance ranking (does the bot prioritize the right sources?)

### 2.3 Slack Multi-Channel Capture

**Test: Channel messages are persisted but bot doesn't respond**

1. Create a test channel, invite the bot, post 10 messages without @mentioning.
2. DM the bot: `@bot What did we discuss about X in the test channel?`
3. Expected: bot finds the message via `query_db`, cites the Slack permalink, but the nightly run hasn't extracted a meta file yet.
4. Check SQLite: `sqlite3 data/pyclaudir.db "SELECT chat_id, text, slack_channel_id, slack_message_ts FROM messages WHERE slack_channel_id IS NOT NULL LIMIT 5;"`

Expected: all 10 messages have `slack_channel_id` and `slack_message_ts` populated.

**Test: Slack permalink construction is correct**

Given `slack_message_ts = "1714300012.002100"`:
- `ts_no_dot = "17143000120021"`
- Permalink: `https://{SLACK_WORKSPACE_URL}/archives/{channel_id}/p17143000120021`
- Click it in Slack — does it jump to the exact message? **YES = PASS**

### 2.4 Citation Correctness (critical quality gate)

For each source type, verify:

| Source | Citation form | How to verify |
|---|---|---|
| Confluence | Full page URL | Open in browser, check page title matches |
| Jira | Ticket key (e.g. AUTH-456) | Click Jira link, verify ticket exists |
| KB | Document name / chunk source | Search KB directly, find the doc |
| Slack | Permalink (archives/channel_id/p...) | Click in Slack, jumps to exact message |

**Acceptance criteria**: 95%+ of citations are clickable and accurate.

---

## Phase 3 — Nightly Cron Testing

### 3.1 Manual trigger (before waiting 24h)

The nightly skill can be invoked manually in a DM:

```
@bot run the wiki-nightly skill for today's data
```

Or, for testing, modify the cron to run in 1 minute and wait.

**What to observe:**
1. Slack analysis completes without errors
2. Confluence watch queries `lastModified >= startOfDay()`
3. New Confluence pages are uploaded to KB via `kb_upload`
4. Meta files are created/updated under `data/memories/meta/`
5. `data/memories/meta/_index.md` is rebuilt with new topics

**Check logs:**
```bash
tail -100 data/cc_logs/*.log | grep -E "wiki-nightly|kb_upload|meta"
```

### 3.2 Deduplication (kb_ingestions table)

**Test: Re-running nightly doesn't re-ingest unchanged content**

1. Run nightly, observe a Confluence page is uploaded (check `kb_ingestions` table).
2. Run nightly again without changing the Confluence page.
3. Expected: `kb_upload` detects same content hash, skips, returns "already indexed".
4. Query: `sqlite3 data/pyclaudir.db "SELECT source_url, COUNT(*) FROM kb_ingestions GROUP BY source_url;"`
Expected: no duplicate rows.

### 3.3 Meta Memory Structure

After first nightly run, check:

```bash
cat data/memories/meta/_index.md
cat data/memories/meta/authentication.md  (if that topic emerged)
```

Expected:
- `_index.md` lists discovered topics with brief descriptions
- `<topic>.md` files contain summaries + source links (Confluence URLs, Slack permalinks)
- No agent hallucination (e.g., topics that don't actually exist in the sources)

---

## Phase 4 — Performance & Scale

### 4.1 Latency Baselines

Create a test script that measures response times:

```
Questions to ask:
  1. "How do we authenticate users?" (tests KB search)
  2. "What's the status of AUTH-456?" (tests Jira)
  3. "What database did we choose?" (tests Slack query_db)
  4. "Synthesize auth requirements" (tests multi-source)
```

For each, measure:
- **Time-to-first-chunk**: when the first message arrives
- **Time-to-completion**: when the answer is fully sent
- **MCP latency**: how long does Rovo MCP take?
- **KB latency**: how long does `kb_search` take?
- **SQLite latency**: how long does `query_db` take?

**Target baseline**: first-chunk <5s, completion <15s.

### 4.2 SQLite Query Performance

As Slack messages accumulate (thousands per day), check `query_db` performance:

```bash
sqlite3 data/pyclaudir.db "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE text LIKE '%auth%' AND timestamp > datetime('now', '-30 days');"
```

Expected: uses indexes, not full table scans.

If slow, add an index:

```sql
CREATE INDEX idx_messages_text_timestamp
  ON messages (text, timestamp)
  WHERE direction = 'in';
```

### 4.3 Concurrent Users

When multiple users ask questions simultaneously:
- Does the bot handle concurrent CC turns? (pyclaudir serializes per chat, so single-chat is fine)
- Do parallel API calls to Rovo / OpenWebUI / GitHub MCP fail? (should not — they're concurrent in the skill)

### 4.4 KB Size Impact

Test with increasing KB sizes:
- 10 MB: 100 documents
- 100 MB: 1000 documents
- 1 GB: 10000 documents

Measure: does `kb_search` latency degrade? Is the embedding model still fast?

---

## Phase 5 — Quality & Accuracy

### 5.1 Hallucination Detection

Ask questions with **no correct answer** and watch for fabrication:

```
@bot When was the company founded?
(if not in any source, bot should say "I found no information about...")

@bot What's the CEO's favorite food?
(should clearly state "I have no sources for this")
```

**Pass criteria**: bot says "I found no sources" or cites from sources only, zero fabrication.

### 5.2 Source Accuracy

For 20 random bot answers:
- [ ] Citation is correct (links work, content matches)
- [ ] Citation is necessary (not just a random document from the KB)
- [ ] Citation is the most relevant (better sources not omitted)

Measure: citation accuracy rate.

### 5.3 Contradiction Detection

Create conflicting data:
- **Confluence**: "We use PostgreSQL"
- **Slack (recent)**: "We're migrating to MySQL"

Question: `@bot What database do we use?`

Expected behavior: bot notes the conflict and cites both sources, letting the human decide.

### 5.4 Staleness Detection

- **Confluence page**: "Updated 2026-04-01"
- **Slack**: "Updated 2026-05-08 — we changed the approach"

Does bot detect recency and prefer the Slack message? Test this.

---

## Phase 6 — Feature Exploration & Brainstorming

### 6.1 Gaps in Current MVP

**Limitations to document:**

| Limitation | Impact | Workaround |
|---|---|---|
| No write access to Confluence | Can't create summary docs automatically | Manual creation or GitHub integration |
| GitHub requires user to name repos | Can't auto-discover all relevant repos | Add a config list of "important repos" |
| No graph search on KB | Can't find "related documents" | User must be specific in queries |
| Meta memory is markdown only | No machine-queryable relationships | Could add SQLite graph table later |
| Nightly cron is once-per-day | Stale by end of day | Could add faster updates for #announcements |

### 6.2 Potential v1.5 Features

**Quick wins** (no architecture change):

1. **GitHub PR summary**: When a user mentions a repo/PR, bot summarizes the PR for context
2. **Confluence page summary**: When bot finds a Confluence page, auto-summarize it
3. **Trend detection**: Nightly skill extracts "most discussed topics this week" → surfaces in meta
4. **Slack thread threading**: If bot is mentioned in a thread, it stays in that thread (already works via thread_ts)

**Moderate effort** (small code additions):

5. **Cognee graph search**: Enable Cognee on the KB, query the knowledge graph alongside vector search
6. **SQLite knowledge graph**: Add `kb_edges` table, agent builds "authentication → OAuth → Azure AD" relationships
7. **Cross-KB search**: Search multiple KBs in one query
8. **Custom models**: Let admins create custom retrieval models on top of KBs (OpenWebUI feature)

**Higher effort** (new infrastructure):

9. **Real-time updates**: Subscribe to Confluence webhooks, push changes to KB immediately instead of nightly
10. **Slack thread analysis**: Automatically extract Q&A from threads, index to KB
11. **Write back to Confluence**: Create "Daily Digest" pages automatically

### 6.3 New Use Cases to Try

**Use case 1: Onboarding acceleration**
- New hire joins Slack
- Asks: `@bot Tell me about the architecture, deployment, and team structure`
- Bot synthesizes from KB + Confluence + Slack history
- Expected: new hire gets ramped up 10x faster

**Use case 2: Decision traceability**
- PM asks: `@bot Why did we choose PostgreSQL over MongoDB?`
- Bot finds original Slack thread + Jira discussion + linked Confluence doc
- Expected: full decision context with citations, rationale is traceable

**Use case 3: Incident post-mortem assistance**
- On-call engineer: `@bot Summarize past outages related to auth`
- Bot finds Jira tickets tagged "outage", Slack #incidents posts, KB incident runbooks
- Expected: quick context for the current incident

**Use case 4: API documentation augmentation**
- Developer: `@bot What's the /auth endpoint do and what are the error codes?`
- Bot searches KB + GitHub code comments + Jira API tickets
- Expected: developer gets answer + code example + known issues

---

## Phase 7 — Known Limitations & Edge Cases

### 7.1 Documented Limitations

| Scenario | Current behavior | Desired behavior | Effort |
|---|---|---|---|
| **Confluence HTML formatting** | Bot strips HTML, only uses text | Preserve tables / code blocks | medium |
| **Slack emoji reactions** | Not captured in messages | Use reactions as "agree/disagree" signals | low |
| **Private channels** | Not saved (bot not invited) | Explicitly allow opt-in private channels | low |
| **Very long documents** | KB chunks them; agent sees snippets | Show document structure / table of contents | medium |
| **Ambiguous questions** | Bot guesses which source to search | Bot asks for clarification | high |
| **Cross-source conflicts** | Bot notes them | Bot shows confidence scores per source | medium |
| **Ancient Slack history** | Only queries last 30 days | Configurable retention window | low |

### 7.2 Edge Cases to Test

**Edge case 1: Empty sources**
```
@bot Tell me about our marketing strategy
(no Confluence page, no Jira ticket, nothing in KB, no Slack discussion)
```
Expected: "I found no information about..."
Actual: ?

**Edge case 2: Ambiguous citations**
```
Question: "What's our policy?"
- Confluence: "Policy v1.0 from 2026-01-01"
- Slack: "New policy v2.0 from 2026-05-08"
```
Expected: bot prefers newer source, cites both
Actual: ?

**Edge case 3: Circular references**
```
Meta memory says "see KB doc X"
KB doc says "see Slack thread Y"
Slack says "see Confluence Z"
Confluence says "see meta topic A"
```
Expected: bot stops before infinite loop
Actual: ?

**Edge case 4: Jargon / acronyms**
```
@bot What's the deal with KST?
```
Does the bot search for "Korea Standard Time" or fail on the acronym?

**Edge case 5: Multi-language questions**
```
@bot 우리 인증 시스템은 어떻게 작동하나요? (Korean)
```
Does Rovo MCP / KB search handle non-English?

---

## Phase 8 — Optimization Targets

### 8.1 Latency Optimization

**Baseline measurement** (Phase 4) → identify bottleneck.

Likely candidates:
1. **Rovo MCP latency**: If >5s, consider caching frequently-asked questions
2. **KB search latency**: If >3s, consider reducing k from 5 to 3
3. **Meta memory reads**: If missing meta/_index.md makes a query slower, pre-load it

Action: profile CC logs with `profile_enabled=true`, find the slowest tool calls.

### 8.2 Query Relevance Tuning

**Measure**: For 50 test queries, manually rate the bot's answer (1-5 stars). Average score = relevance baseline.

**Tuning knobs**:
- `k` in `kb_search` (currently 5) → reduce to 3 if noisy, increase to 10 if missing relevant chunks
- `hybrid_bm25_weight` in `kb_search` (currently 0.4) → increase to 0.6 if keyword search is underweighted
- Confluence CQL query → add `space = "ENGINEERING"` to reduce noise from unrelated spaces
- Jira JQL query → add `project = "AUTH"` for focused searches

### 8.3 Cost Optimization

Measure OpenWebUI + Atlassian API call volume:
- `kb_search` calls per day
- Confluence CQL queries per day
- Jira searches per day

If cost is high:
- Cache frequent searches
- Deduplicate concurrent queries (two identical requests should reuse one result)
- Reduce `k` (fewer embeddings = cheaper)

### 8.4 Accuracy Optimization

For each failed citation (broken link or wrong content):
1. Log the failure
2. Identify: was it `kb_search`, Rovo MCP, or `query_db`?
3. Retune that source's parameters

Example: If 20% of KB citations are wrong, consider:
- Lowering relevance threshold (include lower-scoring chunks)
- Checking if KB was chunked incorrectly (re-process with different chunk size)
- Increasing `k_reranker` to keep more candidates

---

## Phase 9 — Test Scenarios Checklist

Print this and check off as you test:

```
SETUP & CONFIG
[ ] All env vars loaded
[ ] MCP servers registered
[ ] SQLite migrations applied
[ ] Memory directory exists

MVP FUNCTIONALITY
[ ] Confluence-only QA works
[ ] Jira-only QA works
[ ] KB-only QA works
[ ] Slack-only QA works
[ ] Multi-source synthesis works

SLACK MULTI-CHANNEL
[ ] Non-mention messages persisted to SQLite
[ ] Slack permalinks constructed correctly
[ ] Bot responds only to @mentions / DMs

NIGHTLY CRON
[ ] Slack analysis runs
[ ] Confluence watcher runs
[ ] KB ingestion completes
[ ] Meta files created/updated
[ ] Deduplication works (no re-ingests)

QUALITY
[ ] No hallucination (bot says "no sources" when true)
[ ] All citations are clickable
[ ] Citations match answer content
[ ] Conflicts are noted
[ ] Staleness is detected

PERFORMANCE
[ ] First chunk <5s
[ ] Completion <15s
[ ] SQLite queries use indexes
[ ] Concurrent users work
[ ] KB size scales linearly

EDGE CASES
[ ] Empty sources handled
[ ] Ambiguous questions handled
[ ] Acronyms work
[ ] Multi-language attempts detected
```

---

## Phase 10 — Reporting Template

After each phase, document findings in a test report:

```markdown
# Phase X Test Report — [Date]

## Summary
[1-2 sentences on what was tested and outcome]

## Results
| Scenario | Status | Notes |
|---|---|---|
| Setup config | PASS | All env vars loaded |
| Confluence search | FAIL | Rovo MCP timing out |

## Failures & Root Causes
1. **Rovo MCP timeout** — DNS issue, resolved by using IP instead of hostname
2. **KB search noisy** — k=5 too high, reduced to k=3

## Optimizations Applied
1. Added index to messages table on (text, timestamp)
2. Reduced KB search k from 5 to 3
3. Cached meta/_index.md for 1 minute

## Next Steps
- [ ] Test multi-language support
- [ ] Measure cost per query
- [ ] Brainstorm v1.5 features
```

---

## How to Run This Plan

1. **Phase 1** (30 min): Verify setup
2. **Phase 2** (2 hrs): Test single and multi-source
3. **Phase 3** (1 hr): Trigger nightly, check results
4. **Phase 4** (2 hrs): Measure latency baselines
5. **Phase 5** (1 hr): Test quality, hallucination
6. **Phase 6** (brainstorm): Discuss with team (1 hr)
7. **Phase 7** (1 hr): Document known limitations
8. **Phase 8** (2 hrs): Identify and apply optimizations
9. **Phase 9** (1 hr): Full checklist pass
10. **Phase 10** (30 min): Write summary report

**Total: ~12 hours of hands-on testing + brainstorming**

After Phase 10, you'll have:
- Baseline performance metrics
- List of bugs / limitations
- Feature wishlist for v1.5
- Optimized parameters
- Documented known issues
- Confidence in production readiness
