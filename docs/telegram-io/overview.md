---
title: Telegram I/O
---

# Telegram I/O

Receives Telegram updates, validates them, persists them, and forwards to the engine. Also handles owner-only operator commands.

**Files:** `pyclaudir/telegram_io/dispatcher.py`, `pyclaudir/telegram_io/attachments.py`

## Inbound Message Flow

```mermaid
flowchart TD
    UPD[Telegram Update] --> HAND[Message handler]
    HAND --> NORM[input_normalizer\nstrip obfuscation]
    NORM --> GATE[access.gate()\nallow / deny]
    GATE -->|denied| DROP[transcript DROP\nno reply]
    GATE -->|allowed| RL[rate_limiter\ncheck bucket]
    RL -->|exceeded| THROTTLE[Send throttle notice\nif first in bucket]
    RL -->|ok| ATCH[attachments.py\ndownload media if any]
    ATCH --> DB[messages.py\ninsert + upsert_user]
    DB --> TX[transcript RX log]
    TX --> ENG[engine.submit\nChatMessage]
```

## Owner Commands

All owner commands respond only to `PYCLAUDIR_OWNER_ID`. No other user can trigger them, even if access policy is `open`.

| Command | Action |
|---------|--------|
| `/kill` | Terminate CC worker process |
| `/health` | Show CC worker status + DB row counts |
| `/audit` | Dump recent transcript lines |
| `/access` | Show current `access.json` policy |
| `/allow <user_id>` | Add user to allowlist |
| `/deny <user_id>` | Remove user from allowlist |
| `/policy <owner_only\|allowlist\|open>` | Change policy (hot-writes `access.json`) |

## Message Edits & Reactions

- **Edits**: Dispatcher intercepts `MessageEdit` updates, updates the SQLite row, logs `[EDIT]` to transcript, and resubmits to engine so Claude can respond to the correction.
- **Reactions**: Recorded in `reactions` table. Logged as `[RX↺]`. Not forwarded to engine by default (agent can query via `query_db`).

## Attachment Handling (`attachments.py`)

Photos and documents are downloaded before the message is submitted to the engine:

1. Telegram sends `file_id` in the update.
2. `bot.get_file(file_id)` returns a download URL.
3. File downloaded to `data/attachments/<file_id>`.
4. `ChatMessage.attachment_path` set.
5. Agent calls `read_attachment` tool to access content.

Max file size: 20 MB (configurable via `PYCLAUDIR_ATTACHMENT_MAX_BYTES`).

## Chat Title Cache

Dispatcher maintains an in-memory `dict[chat_id, str]` of chat titles. Populated on every inbound message, used by `transcript.py` to produce human-readable outbound logs like:

```
[TX] G "team"[-1001234] bot[111] m999 | replied
```
