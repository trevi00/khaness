"""Notification config loader — reads settings.json `notifications` section.

Single responsibility: parse config into immutable dataclasses. No I/O beyond
reading the JSON file; no network calls; no hook-payload awareness.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lib.paths import CLAUDE_HOME


SETTINGS_PATH: Path = CLAUDE_HOME / "settings.json"


@dataclass(frozen=True)
class Channel:
    type: str                           # "slack" | "discord" | "telegram"
    webhook: str | None = None          # slack, discord
    bot_token: str | None = None        # telegram
    chat_id: str | None = None          # telegram


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool
    channels: tuple[Channel, ...]
    triggers: frozenset[str]            # when non-empty, only listed types are dispatched


def load_config(path: Path = SETTINGS_PATH) -> NotificationConfig:
    """Load and parse notifications settings. Returns disabled config on any error."""
    try:
        with path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return NotificationConfig(False, (), frozenset())

    notif = cfg.get("notifications") or {}
    if not notif.get("enabled"):
        return NotificationConfig(False, (), frozenset())

    raw_channels = notif.get("channels") or []
    channels: tuple[Channel, ...] = tuple(
        Channel(
            type=str(c.get("type", "")).lower(),
            webhook=c.get("webhook"),
            bot_token=c.get("bot_token"),
            chat_id=c.get("chat_id"),
        )
        for c in raw_channels
        if isinstance(c, dict) and c.get("type")
    )
    triggers = frozenset(
        str(t) for t in (notif.get("triggers") or []) if t
    )
    return NotificationConfig(enabled=True, channels=channels, triggers=triggers)
