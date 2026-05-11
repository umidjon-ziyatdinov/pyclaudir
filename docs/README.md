# docs/

The top-level [README](../README.md) is the high-level intro; everything below is for people (and agents) who need to go deeper.

## Mindmap

### [mindmap.md](mindmap.md)
Full system mindmap: every module, feature, and data flow in one Mermaid diagram. Start here for a bird's-eye view.

## Feature Areas

| Area | Overview |
|------|----------|
| [engine/](engine/overview.md) | Debounce buffer, turn control, liveness watchdog |
| [cc-worker/](cc-worker/overview.md) | Claude Code subprocess management, crash recovery, session persistence |
| [tools/](tools/overview.md) | 20 built-in MCP tools, tool framework, auto-discovery |
| [database/](database/overview.md) | SQLite schema, migrations, messages/reminders CRUD |
| [storage/](storage/overview.md) | Memory files, attachments, render PNGs, path safety |
| [telegram-io/](telegram-io/overview.md) | Dispatcher, inbound flow, owner commands, attachments |
| [access-control/](access-control/overview.md) | access.json policies, per-user rate limiting |
| [security/](security/overview.md) | 6 invariants, secrets scrubber, input normalizer, path safety |
| [skills/](skills/overview.md) | Agent Skills spec, built-in skills, self-reflection |
| [config/](config/overview.md) | All env vars, timeouts, derived paths, file-based config |

## Reference Files

### [documentation.md](documentation.md)
Full technical manual: every env var, four-process architecture, how to add tools and skills, security model with all invariants, monitoring, end-to-end checklist, repo layout.

### [tools.md](tools.md)
Canonical tool reference: always-on built-ins, opt-in groups, `plugins.json` schema, how to add an external MCP, how to disable a tool or skill.

### [deployment.md](deployment.md)
VPS deployment via Docker + continuous-deployment workflow.

### [reference-architectures.md](reference-architectures.md)
Ancestry: Anthropic Telegram plugin + Rust Claudir. Read before proposing architectural changes.

### [changelog.md](changelog.md)
Session log for docs changes.

## Quick Reference

| You want to… | Read |
|---|---|
| Get a bird's-eye view | [mindmap.md](mindmap.md) |
| Understand message flow end-to-end | [engine/overview.md](engine/overview.md) + [cc-worker/overview.md](cc-worker/overview.md) |
| Add a new tool | [tools/overview.md](tools/overview.md) |
| Change who can use the bot | [access-control/overview.md](access-control/overview.md) |
| Understand the security model | [security/overview.md](security/overview.md) |
| Add an external MCP | [tools.md](tools.md) |
| Deploy to a server | [deployment.md](deployment.md) |
| Propose a structural change | [reference-architectures.md](reference-architectures.md) then [documentation.md](documentation.md) |
| Run the bot locally | [../README.md](../README.md) |
