"""Notification subpackage — webhook dispatch for Claude Code Notification hooks.

Configuration lives at `settings.json` top-level `notifications` key:

  "notifications": {
    "enabled": true,
    "channels": [
      {"type": "slack",    "webhook": "https://hooks.slack.com/..."},
      {"type": "discord",  "webhook": "https://discord.com/api/webhooks/..."},
      {"type": "telegram", "bot_token": "123:ABC", "chat_id": "-1001234567890"}
    ],
    "triggers": ["stop_error", "permission_denied"]
  }

When `enabled` is false (or the key is absent), all dispatch calls are no-ops.
"""
from .config import Channel, NotificationConfig, load_config
from .dispatcher import dispatch

__all__ = ["Channel", "NotificationConfig", "dispatch", "load_config"]
