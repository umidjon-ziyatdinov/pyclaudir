"""Convert Markdown to Slack mrkdwn format.

Slack uses a subset of its own markup called mrkdwn:
  https://api.slack.com/reference/surfaces/formatting

Key differences from Telegram HTML:
  - Bold: *text* (not <b>)
  - Italic: _text_ (not <i>)
  - Strikethrough: ~text~ (not <s>)
  - Code: `text` (same)
  - Code block: ```text``` (same delimiters, different rendering)
  - Link: <url|label> (not <a href>)
  - No HTML escaping needed
"""

from __future__ import annotations

import re


def markdown_to_slack(text: str) -> str:
    """Best-effort Markdown → Slack mrkdwn conversion."""
    code_blocks: list[str] = []

    def _stash_code_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = m.group(2).rstrip("\n")
        idx = len(code_blocks)
        prefix = f"```{lang}\n" if lang else "```\n"
        code_blocks.append(f"{prefix}{code}\n```")
        return f"\x00CODEBLOCK{idx}\x00"

    text = re.sub(r"```(\w+)?\n?(.*?)```", _stash_code_block, text, flags=re.DOTALL)

    inline_codes: list[str] = []

    def _stash_inline(m: re.Match) -> str:
        idx = len(inline_codes)
        inline_codes.append(f"`{m.group(1)}`")
        return f"\x00INLINE{idx}\x00"

    text = re.sub(r"`([^`]+)`", _stash_inline, text)

    # Bold+italic ***text***
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"*_\1_*", text, flags=re.DOTALL)
    # Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"*\1*", text, flags=re.DOTALL)
    # Italic *text* (careful not to conflict with bold)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"_\1_", text)
    # Italic _text_ (word-boundary only)
    text = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", r"_\1_", text)
    # Strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text, flags=re.DOTALL)

    # Links [label](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)

    # Strip heading markers (## Title → *Title*)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # Blockquotes: > text → > text (Slack supports > natively)
    # Already works as-is; no transformation needed.

    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{idx}\x00", block)
    for idx, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{idx}\x00", code)

    return text


def strip_mention(text: str, bot_user_id: str) -> str:
    """Remove leading ``<@BOTID>`` from an app_mention event text."""
    prefix = f"<@{bot_user_id}>"
    stripped = text.strip()
    if stripped.startswith(prefix):
        stripped = stripped[len(prefix) :].lstrip()
    return stripped
