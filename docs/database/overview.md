---
title: Database
---

# Database

Async SQLite via `aiosqlite`. WAL mode. Foreign keys enabled. All state except files lives here.

**Files:** `pyclaudir/db/database.py`, `pyclaudir/db/messages.py`, `pyclaudir/db/reminders.py`, `pyclaudir/db/migrations/`

## Schema

```mermaid
erDiagram
    users {
        int user_id PK
        text username
        text first_name
        text last_name
        datetime created_at
    }
    messages {
        int id PK
        int chat_id
        int user_id FK
        int message_id
        int reply_to_id
        text direction
        text content
        datetime created_at
    }
    reactions {
        int id PK
        int message_id FK
        int user_id FK
        text emoji
        datetime created_at
    }
    tool_calls {
        int id PK
        int message_id FK
        text tool_name
        text args_json
        text result_json
        bool is_error
        datetime created_at
    }
    reminders {
        int id PK
        int chat_id
        int user_id
        text text
        datetime trigger_at
        text cron_expr
        text status
        text auto_seed_key
        datetime created_at
    }
    rate_limits {
        int user_id PK
        int bucket_start
        int count
        bool notice_sent
    }
    schema_migrations {
        int version PK
        datetime applied_at
    }
    users ||--o{ messages : "sends"
    messages ||--o{ reactions : "has"
    messages ||--o{ tool_calls : "triggers"
```

## Migration Runner

Migrations live in `pyclaudir/db/migrations/NNN_name.sql`. On startup, the runner:

1. Creates `schema_migrations` if missing.
2. Reads all `.sql` files sorted by prefix number.
3. Applies any version not yet in `schema_migrations`.
4. Records each applied version.

Migrations are idempotent by version: applied once, never re-run.

## Migrations History

| Version | File | Adds |
|---------|------|------|
| 001 | `001_initial.sql` | messages, users, reactions, tool_calls, rate_limits |
| 002 | `002_reminders.sql` | reminders table |
| 003 | `003_cleanup.sql` | Performance indexes |
| 004 | `004_rate_limits_per_user.sql` | Per-user rate limit buckets |
| 005 | `005_reminder_auto_seed.sql` | `auto_seed_key` + `cron_expr` columns on reminders |

## Key Operations

**messages.py**
- `insert_message(chat_message)` → persists inbound and outbound messages
- `edit_message(message_id, new_text)` → updates content
- `delete_message(message_id)` → removes row
- `upsert_user(user)` → insert or ignore user record

**reminders.py**
- `create_reminder(chat_id, user_id, text, trigger_at, cron_expr, auto_seed_key)` → insert
- `list_pending(now)` → all reminders due and not sent
- `mark_sent(id)` → update status, compute next trigger for cron reminders
- `cancel(id)` → delete (tool layer blocks cancellation of auto_seed_key rows)

## Connection Settings

```python
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

WAL allows concurrent reads during writes, important for the reminder loop polling while the engine is active.
