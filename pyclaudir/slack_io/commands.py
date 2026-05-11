"""Owner-only command handlers for the Slack dispatcher.

Commands arrive as DM messages prefixed with ``!`` from the account
matching ``SLACK_OWNER_ID``. Each handler receives the argument list,
target channel, and the Slack client.
"""

from __future__ import annotations

import logging
import os
import signal

from ..access import load_access, save_access
from ..config import Config
from ..db.database import Database

log = logging.getLogger("pyclaudir.slack_io")

_HELP = (
    "Available commands: !health !kill !audit !access "
    "!allow user <id> !deny user <id> !policy <owner_only|allowlist|open>"
)


async def dispatch_command(
    cmd: str,
    channel: str,
    client,
    config: Config,
    db: Database,
) -> None:
    """Route a ``!command`` string to the appropriate handler."""
    parts = cmd.split()
    verb = parts[0].lower() if parts else ""
    args = parts[1:]
    handlers = {
        "health": _cmd_health,
        "kill": _cmd_kill,
        "audit": _cmd_audit,
        "access": _cmd_access,
        "allow": _cmd_allow,
        "deny": _cmd_deny,
        "policy": _cmd_policy,
    }
    handler = handlers.get(verb)
    if handler:
        await handler(args, channel, client, config, db)
    else:
        await client.chat_postMessage(channel=channel, text=_HELP)


async def _cmd_health(args, channel, client, config, db) -> None:
    lines = ["*pyclaudir health*"]
    try:
        row = await db.fetch_one(
            "SELECT MAX(timestamp) AS last FROM messages WHERE direction='out'"
        )
        last = row["last"] if row and row["last"] else "(none)"
        lines.append(f"- last bot send: `{last}` UTC")
    except Exception as exc:
        lines.append(f"- last bot send: error ({exc})")
    try:
        row = await db.fetch_one(
            "SELECT status, cron_expr, trigger_at FROM reminders "
            "WHERE auto_seed_key = 'self-reflection-default' ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            lines.append("- self-reflection: MISSING (re-seeds on restart)")
        else:
            lines.append(
                f"- self-reflection: {row['status']} "
                f"(cron `{row['cron_expr']}`, next `{row['trigger_at']}` UTC)"
            )
    except Exception as exc:
        lines.append(f"- self-reflection: error ({exc})")
    await client.chat_postMessage(channel=channel, text="\n".join(lines), mrkdwn=True)


async def _cmd_kill(args, channel, client, config, db) -> None:
    await client.chat_postMessage(channel=channel, text="Shutting down…")
    os.kill(os.getpid(), signal.SIGTERM)


async def _cmd_audit(args, channel, client, config, db) -> None:
    lines = ["*pyclaudir audit*"]
    try:
        rows = await db.fetch_all(
            "SELECT tool_name, error, created_at FROM tool_calls "
            "WHERE error IS NOT NULL AND error != '' ORDER BY id DESC LIMIT 5"
        )
        if rows:
            lines.append("*recent tool failures:*")
            for r in rows:
                lines.append(
                    f"  • `{r['created_at']}` {r['tool_name']} — {(r['error'] or '')[:80]}"
                )
        else:
            lines.append("*recent tool failures:* none")
    except Exception as exc:
        lines.append(f"*recent tool failures:* error ({exc})")
    mem_dir = config.memories_dir
    total = (
        sum(p.stat().st_size for p in mem_dir.rglob("*") if p.is_file())
        if mem_dir.exists()
        else 0
    )
    lines.append(f"*memory footprint:* {total:,} bytes")
    await client.chat_postMessage(channel=channel, text="\n".join(lines), mrkdwn=True)


async def _cmd_access(args, channel, client, config, db) -> None:
    access = load_access(config.access_path)
    await client.chat_postMessage(
        channel=channel,
        text=(
            f"Policy: {access.policy}\n"
            f"Allowed users: {access.allowed_users or '(none)'}\n"
            f"Allowed chats: {access.allowed_chats or '(none)'}\n"
            f"Owner: {config.slack_owner_id} (always allowed)"
        ),
    )


async def _cmd_allow(args, channel, client, config, db) -> None:
    if len(args) < 2 or args[0] not in ("user", "group"):
        await client.chat_postMessage(channel=channel, text="Usage: !allow user <id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await client.chat_postMessage(channel=channel, text="ID must be a number.")
        return
    access = load_access(config.access_path)
    bucket = access.allowed_users if args[0] == "user" else access.allowed_chats
    if target_id not in bucket:
        bucket.append(target_id)
        save_access(config.access_path, access)
    await client.chat_postMessage(
        channel=channel, text=f"Added {target_id} to allowlist."
    )


async def _cmd_deny(args, channel, client, config, db) -> None:
    if len(args) < 2 or args[0] not in ("user", "group"):
        await client.chat_postMessage(channel=channel, text="Usage: !deny user <id>")
        return
    try:
        target_id = int(args[1])
    except ValueError:
        await client.chat_postMessage(channel=channel, text="ID must be a number.")
        return
    access = load_access(config.access_path)
    bucket = access.allowed_users if args[0] == "user" else access.allowed_chats
    if target_id in bucket:
        bucket.remove(target_id)
        save_access(config.access_path, access)
        await client.chat_postMessage(channel=channel, text=f"Removed {target_id}.")
    else:
        await client.chat_postMessage(
            channel=channel, text=f"{target_id} not in allowlist."
        )


async def _cmd_policy(args, channel, client, config, db) -> None:
    valid = ("owner_only", "allowlist", "open")
    if not args or args[0] not in valid:
        await client.chat_postMessage(
            channel=channel, text=f"Usage: !policy <{'|'.join(valid)}>"
        )
        return
    access = load_access(config.access_path)
    access.policy = args[0]  # type: ignore[assignment]
    save_access(config.access_path, access)
    await client.chat_postMessage(channel=channel, text=f"Policy set to: {args[0]}")
