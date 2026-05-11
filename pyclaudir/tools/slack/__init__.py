"""Slack-specific tool implementations.

These replace the Telegram messaging tools when ``platform="slack"``.
Platform-agnostic tools (memory, query_db, render, etc.) are loaded
from the parent ``tools/`` package unchanged.
"""
