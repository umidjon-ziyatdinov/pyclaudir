---
title: Skills
---

# Skills

Operator-curated playbooks the agent can discover and execute. Follows the [Agent Skills specification](https://agentskills.io/specification).

**Files:** `pyclaudir/skills_store.py`, `skills/`

## Skill Format

Each skill lives at `skills/<name>/SKILL.md`:

```
skills/
  self-reflection/SKILL.md
  render-style/SKILL.md
  trend-digest/SKILL.md
  reminder-format/SKILL.md
```

Every `SKILL.md` requires YAML frontmatter:

```yaml
---
name: render-style
description: House style guide for render_html — read before every render call.
---
```

Constraints on frontmatter fields:
- `name` must match the parent directory name
- `name`: lowercase, alphanumeric + hyphens, single component, ≤64 chars
- `description`: ≤1024 chars

## Tools

| Tool | Description |
|------|-------------|
| `list_skills` | Return all enabled skills with name + description. |
| `read_skill` | Return full `SKILL.md` body for a named skill (≤256 KiB). |

Skills are read-only from the agent's perspective. The operator edits them on disk.

## Built-in Skills

| Skill | Purpose | Special |
|-------|---------|---------|
| `self-reflection` | Daily learning loop: analyze conversations, propose improvements, save to project.md | Mandatory — auto-seeded cron reminder, cannot be cancelled by agent |
| `render-style` | CSS + typography house style guide for `render_html` | Read before every render call |
| `trend-digest` | Example market intelligence playbook | Template / example |
| `reminder-format` | Format rules for reminders | Guidance skill |

## self-reflection (Mandatory)

Runs on a cron schedule (default `0 0 * * *`, midnight UTC). Configured via `PYCLAUDIR_SELF_REFLECTION_CRON`.

Flow:
1. Reminder fires → engine submits reminder turn.
2. Agent reads `self-reflection/SKILL.md` for instructions.
3. Queries recent conversation history via `query_db`.
4. Proposes behavior changes.
5. Saves conclusions to `data/memories/` or proposes `append_instructions`.
6. Owner reviews and approves via Telegram.

The cron reminder is auto-seeded in the DB on startup with `auto_seed_key = "self-reflection"`. The `cancel_reminder` tool refuses to cancel it.

## Disabling Skills

Add skill directory names to `skills_disabled` in `plugins.json`:

```json
{ "skills_disabled": ["trend-digest"] }
```

Disabled skills are hidden from `list_skills` output. The files remain on disk but the agent cannot see or read them.

## Validation

`python -m pyclaudir.scripts.validate_skills` checks all `SKILL.md` files for frontmatter compliance before deployment.

## Adding a Skill

1. Create `skills/<name>/SKILL.md` with valid frontmatter.
2. Restart the bot (SkillsStore is loaded at startup).
3. Run `validate_skills` to confirm.
4. No code changes required.
