---
title: Slack Setup Guide
---

# Slack Setup Guide

Step-by-step instructions to create a Slack App, configure pyclaudir for Slack, and run the bot.

---

## 1. Create a Slack App

Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**.

- **App name**: anything (e.g. `Claude Assistant`)
- **Workspace**: your target workspace

---

## 2. Enable Socket Mode

In the left sidebar: **Settings → Socket Mode** → toggle ON.

Click **Generate an App-Level Token**:
- Token name: `pyclaudir-socket`
- Scope: `connections:write`
- Click **Generate** → copy the `xapp-...` token → this is your `SLACK_APP_TOKEN`

---

## 3. Configure Bot Permissions (OAuth Scopes)

Left sidebar: **Features → OAuth & Permissions** → scroll to **Bot Token Scopes** → Add:

| Scope | Why |
|-------|-----|
| `chat:write` | Post messages |
| `chat:write.public` | Post to channels without joining |
| `im:history` | Read DM history |
| `im:write` | Open DMs with users |
| `channels:history` | Read messages in channels the bot is added to |
| `groups:history` | Read messages in private channels |
| `app_mentions:read` | Receive @mention events |
| `reactions:write` | Add emoji reactions |
| `files:write` | Upload images/files |
| `users:read` | Resolve user info (optional, for display names) |

Then click **Install to Workspace** at the top of the page.
Copy the `xoxb-...` token → this is your `SLACK_BOT_TOKEN`.

---

## 4. Enable Events

Left sidebar: **Features → Event Subscriptions** → toggle **Enable Events** ON.

Under **Subscribe to bot events**, add:

| Event | Why |
|-------|-----|
| `message.im` | DMs to the bot |
| `app_mention` | @mentions in channels |
| `reaction_added` | Emoji reactions (logged to DB) |

> **Note**: Socket Mode does not need a public Request URL — leave it blank or set to any placeholder.

---

## 5. Find Your Slack User ID (Owner)

In Slack: click your **profile photo** → **Profile** → click the **⋮** menu → **Copy member ID**.
This looks like `U012AB3CD` — save it as `SLACK_OWNER_ID`.

---

## 6. Configure Environment Variables

Add to your `.env`:

```env
# Platform switch
PYCLAUDIR_PLATFORM=slack

# Slack credentials
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token
SLACK_OWNER_ID=U012AB3CD

# Claude settings (same as Telegram)
PYCLAUDIR_MODEL=claude-opus-4-7
PYCLAUDIR_EFFORT=high

# Telegram token no longer required when platform=slack
# TELEGRAM_BOT_TOKEN= (leave unset or empty)
```

> `PYCLAUDIR_OWNER_ID` is automatically derived from `SLACK_OWNER_ID` when `platform=slack` — you don't need to set it separately.

---

## 7. Install Dependencies

```bash
uv sync
# or
pip install -e ".[dev]"
```

The `slack-bolt` and `slack-sdk` packages are now in `pyproject.toml` dependencies.

---

## 8. Run the Bot

```bash
python -m pyclaudir
```

You should see:
```
slack bot authenticated as Your Name (U012AB3CD)
slack dispatcher started (socket mode)
pyclaudir is live
```

---

## 9. Test It

**DM the bot:**
- Open Slack, find your app under **Apps** in the sidebar, send a message.
- The bot replies in the same thread.

**@mention in a channel:**
- Add the bot to a channel: `/invite @ClaudeAssistant`
- Type `@ClaudeAssistant hello` — bot replies in-thread.

---

## 10. Owner Commands

Send these as DMs to the bot. They only work from the account matching `SLACK_OWNER_ID`.

| Command | Action |
|---------|--------|
| `!health` | Show last message sent, self-reflection reminder status |
| `!kill` | Shut the bot down (SIGTERM) |
| `!audit` | Recent tool failures, prompt backup count, memory footprint |
| `!access` | Show current access policy |
| `!allow user <crc_id>` | Add a user to the allowlist |
| `!deny user <crc_id>` | Remove a user from the allowlist |
| `!policy owner_only` | Lock to owner DMs only |
| `!policy allowlist` | Allow listed users/groups |
| `!policy open` | Allow anyone |

> **Note**: `<crc_id>` is the CRC32 integer derived from the Slack user ID. To compute it: `python3 -c "import zlib; print(zlib.crc32('U012AB3CD'.encode()) & 0x7FFFFFFF)"`.
> A future release will accept raw Slack user IDs directly.

---

## 11. Add to Channels

For the bot to respond to @mentions:

1. Open the channel in Slack
2. `/invite @ClaudeAssistant`
3. @mention it: `@ClaudeAssistant summarize this thread`

The bot always replies in-thread to avoid cluttering the channel.

---

## 12. Docker

Same as Telegram — just update the `.env` file:

```yaml
# docker-compose.yml (no changes needed)
services:
  pyclaudir:
    build: .
    env_file: .env
    volumes:
      - ./data:/app/data
```

```bash
docker compose up -d --build
docker compose logs -f
```

---

## Architecture Differences vs. Telegram

| Aspect | Telegram | Slack |
|--------|---------|-------|
| Transport | Long polling (PTB) | WebSocket Socket Mode (Bolt) |
| Message ID | Integer `message_id` | String timestamp `ts` (e.g. `1614012345.001234`) |
| Threading | `reply_to_message_id` | `thread_ts` — always reply in same thread |
| Typing indicator | `send_chat_action(TYPING)` | Not supported for bots (no-op) |
| Formatting | Telegram HTML | Slack mrkdwn (`*bold*`, `_italic_`, `~strike~`) |
| Polls | Native Telegram poll | Block Kit buttons |
| File upload | `send_photo` (PTB) | `files_upload_v2` (Slack SDK) |
| Reactions | Fixed Telegram emoji set | Any Slack emoji name |
| Chat ID | Integer | CRC32 of Slack channel ID |

---

## Known MVP Limitations

1. **Rate-limit allowlist uses CRC32 integers** — the `!allow` command needs the numeric CRC32, not the raw Slack user ID. Use the Python one-liner above to compute it.
2. **Block Kit poll responses not wired** — poll vote buttons post `block_actions` events which are not yet handled. Treat polls as one-way straw polls for now.
3. **Reminders lose channel mapping on restart** — if the bot restarts, in-flight reminders will post to the owner's DM channel as fallback.
4. **No per-channel typing indicator** — Slack's API doesn't expose a bot typing indicator.
