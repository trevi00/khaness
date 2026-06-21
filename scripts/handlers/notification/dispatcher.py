"""Notification dispatcher — route (title, body) to configured channels.

One function per channel type + registry. New channel = new function + one
entry in _CHANNEL_REGISTRY. Dispatcher never raises; each channel failure
becomes a (type, False, error_str) tuple in the result list.
"""
from __future__ import annotations

from typing import Callable

from lib.webhook import post_json

from .config import Channel, NotificationConfig, load_config


def _send_slack(channel: Channel, title: str, body: str) -> tuple[bool, str]:
    if not channel.webhook:
        return False, "slack: missing webhook"
    ok, status, err = post_json(channel.webhook, {
        "text": f"*{title}*\n{body}",
    })
    return ok, err or f"HTTP {status}"


def _send_discord(channel: Channel, title: str, body: str) -> tuple[bool, str]:
    if not channel.webhook:
        return False, "discord: missing webhook"
    ok, status, err = post_json(channel.webhook, {
        "content": f"**{title}**\n{body}",
    })
    return ok, err or f"HTTP {status}"


def _send_telegram(channel: Channel, title: str, body: str) -> tuple[bool, str]:
    if not (channel.bot_token and channel.chat_id):
        return False, "telegram: missing bot_token or chat_id"
    url = f"https://api.telegram.org/bot{channel.bot_token}/sendMessage"
    ok, status, err = post_json(url, {
        "chat_id": channel.chat_id,
        "text": f"*{title}*\n{body}",
        "parse_mode": "Markdown",
    })
    return ok, err or f"HTTP {status}"


_CHANNEL_REGISTRY: dict[str, Callable[[Channel, str, str], tuple[bool, str]]] = {
    "slack": _send_slack,
    "discord": _send_discord,
    "telegram": _send_telegram,
}


def dispatch(
    title: str,
    body: str,
    config: NotificationConfig | None = None,
) -> list[tuple[str, bool, str]]:
    """Send (title, body) to every configured channel.

    Returns a list of (channel_type, ok, error_or_status). When config is
    disabled or has no channels, returns an empty list — never raises.
    """
    cfg = config or load_config()
    if not cfg.enabled or not cfg.channels:
        return []

    results: list[tuple[str, bool, str]] = []
    for ch in cfg.channels:
        sender = _CHANNEL_REGISTRY.get(ch.type)
        if not sender:
            results.append((ch.type, False, f"unknown channel type: {ch.type}"))
            continue
        try:
            ok, err = sender(ch, title, body)
            results.append((ch.type, ok, err))
        except Exception as e:
            results.append((ch.type, False, f"exception: {e!r}"))
    return results
