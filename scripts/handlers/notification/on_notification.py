#!/usr/bin/env python3
"""Notification hook entry — forward Claude Code notifications to webhooks.

Registered in settings.json as the Notification event handler. When the
notification type is filtered out by `triggers` or the config is disabled,
silently exits 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.io import read_hook_input
from lib.logging import log_telemetry

# Absolute import: this module is run as a SCRIPT by the settings.json Notification
# hook (no package context), so `from . import ...` raised ImportError on every
# invocation (deep-audit rank 6). scripts/ is on sys.path (above), so the
# fully-qualified package import resolves.
from handlers.notification import dispatch, load_config


def main() -> None:
    payload = read_hook_input()
    cfg = load_config()
    if not cfg.enabled or not cfg.channels:
        sys.exit(0)

    notif_type = str(payload.get("notification_type") or payload.get("type") or "").strip()
    if cfg.triggers and notif_type and notif_type not in cfg.triggers:
        sys.exit(0)

    title = (
        payload.get("title")
        or (f"Claude Code — {notif_type}" if notif_type else "Claude Code notification")
    )
    body = payload.get("message") or payload.get("content") or str(payload)[:1500]

    results = dispatch(title, body, cfg)
    log_telemetry("notifications-sent", {
        "notification_type": notif_type,
        "cwd": payload.get("cwd", ""),
        "results": [
            {"type": t, "ok": ok, "error": err} for (t, ok, err) in results
        ],
    })
    # Notification hooks have no additionalContext schema; silent exit.
    sys.exit(0)


if __name__ == "__main__":
    main()
