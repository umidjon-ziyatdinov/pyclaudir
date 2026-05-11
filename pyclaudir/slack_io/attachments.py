"""Inbound-attachment download for Slack.

Mirrors ``telegram_io/attachments.py``: classifies files, enforces the size
cap, downloads to ``<attachments_dir>/<channel_id>/``, scrubs text files,
and returns marker strings the dispatcher appends to the message body.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Config
from ..secrets_scrubber import scrub

log = logging.getLogger("pyclaudir.slack_io")

_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_TEXT_EXTS = {
    "md",
    "txt",
    "log",
    "csv",
    "json",
    "yaml",
    "yml",
    "toml",
    "ini",
    "conf",
    "py",
    "js",
    "ts",
    "tsx",
    "jsx",
    "html",
    "css",
    "sh",
    "sql",
    "xml",
    "rst",
}


def _ext_of(name: str | None) -> str:
    if not name:
        return ""
    _, _, ext = name.rpartition(".")
    return ext.lower() if ext and ext != name else ""


def _safe_filename(name: str | None, fallback: str) -> str:
    if not name:
        return fallback
    cleaned = name.replace("/", "_").replace("\\", "_").replace("\x00", "").strip(". ")
    if not cleaned:
        return fallback
    return cleaned[:120]


def _classify(ext: str, mime: str | None) -> str | None:
    if ext in _IMAGE_EXTS or (mime and mime.startswith("image/")):
        return "image"
    if ext == "pdf" or mime == "application/pdf":
        return "pdf"
    if ext in _TEXT_EXTS:
        return "text"
    return None


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def _scrub_text_file(dest: Path) -> None:
    try:
        raw = dest.read_text(encoding="utf-8", errors="replace")
        cleaned = scrub(raw)
        if cleaned != raw:
            dest.write_text(cleaned, encoding="utf-8")
    except Exception as exc:
        log.warning("attachment scrub failed path=%s err=%s", dest, exc)


async def process_slack_files(
    files: list[dict],
    channel_id: str,
    message_ts: str,
    client,
    config: Config,
) -> list[str]:
    """Download Slack file attachments and return marker strings.

    ``files`` is the ``files`` array from a Slack message event.
    Each file dict has ``id``, ``name``, ``mimetype``, ``size``,
    ``url_private_download``.
    """
    if not files:
        return []
    dest_dir = config.attachments_dir / channel_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    markers: list[str] = []
    for f in files:
        marker = await _process_one(f, channel_id, message_ts, dest_dir, client, config)
        markers.append(marker)
    return markers


async def _process_one(
    f: dict,
    channel_id: str,
    message_ts: str,
    dest_dir: Path,
    client,
    config: Config,
) -> str:
    name = f.get("name") or f"file_{message_ts}"
    mime = f.get("mimetype")
    size = f.get("size", 0)
    ext = _ext_of(name)
    kind = _classify(ext, mime)

    if kind is None:
        return f"[attachment rejected: filename={name} reason=unsupported_type]"
    if size and size > config.attachment_max_bytes:
        return (
            f"[attachment rejected: filename={name} "
            f"reason=too_large size={_human_size(size)}]"
        )

    safe_name = _safe_filename(name, fallback=f"file_{message_ts}")
    ts_clean = message_ts.replace(".", "")
    dest = dest_dir / f"{ts_clean}_{safe_name}"
    url = f.get("url_private_download") or f.get("url_private", "")
    if not url:
        return f"[attachment download failed: filename={name} reason=no_url]"

    try:
        resp = await client.http_client.get(
            url, headers={"Authorization": f"Bearer {client.token}"}
        )
        dest.write_bytes(resp.body)
    except Exception as exc:
        log.warning("slack attachment download failed %s: %s", name, exc)
        return (
            f"[attachment download failed: filename={name} reason={type(exc).__name__}]"
        )

    if kind == "text":
        _scrub_text_file(dest)

    actual_size = dest.stat().st_size if dest.exists() else size
    log.info(
        "slack attachment saved channel=%s path=%s size=%d kind=%s",
        channel_id,
        dest,
        actual_size,
        kind,
    )
    return (
        f"[attachment: {dest} type={mime or kind} "
        f"size={_human_size(actual_size)} filename={name}]"
    )
