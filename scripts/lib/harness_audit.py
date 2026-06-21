"""harness_audit — deterministic IMPACT-axis evidence for /harness-audit.

Closes the harness-audit gap: the 6-axis IMPACT scoring is LLM judgment with the
checklist "pseudo-code, not production implementation" (aspirational). This provides
OBJECTIVE, deterministic facts per axis (file/config existence + counts) that the LLM
scoring cites as EVIDENCE, so a score is grounded in measurable harness state rather
than pure impression. Read-only, fail-soft (a missing/unreadable artifact → that fact
is 0/False, never raises).

IMPACT = Intent / Memory / Planning / Authority / Control flow / Tools.
"""
from __future__ import annotations

import json
from pathlib import Path

_AXES = ("Intent", "Memory", "Planning", "Authority", "Control", "Tools")


def _home(home) -> Path:
    if home is None:
        from .paths import CLAUDE_HOME
        return Path(CLAUDE_HOME)
    return Path(home)


def _count_files(d: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in d.glob(pattern)) if d.is_dir() else 0
    except Exception:  # noqa: BLE001
        return 0


def _line_count(p: Path) -> int:
    try:
        return sum(1 for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except Exception:  # noqa: BLE001
        return 0


def _bytes(p: Path) -> int:
    try:
        return p.stat().st_size if p.is_file() else 0
    except Exception:  # noqa: BLE001
        return 0


def _load_json(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _validators_count() -> int:
    """Count validator modules WITHOUT importing the validators package — lib must not
    import upward into validators (the commit_layer_adjacency one-directional layer
    rule). A glob of validators/*.py (minus __init__) is a deterministic-enough count
    for audit evidence."""
    try:
        from .paths import SCRIPTS_DIR
        vd = Path(SCRIPTS_DIR) / "validators"
        return sum(1 for p in vd.glob("*.py") if p.name != "__init__.py") if vd.is_dir() else 0
    except Exception:  # noqa: BLE001
        return 0


def impact_evidence(home=None) -> dict:
    """Per-axis deterministic evidence facts. Each axis maps to a dict of measurable
    facts the audit LLM cites when scoring that axis. Pure read, fail-soft."""
    h = _home(home)
    settings = _load_json(h / "settings.json")
    perms = settings.get("permissions") if isinstance(settings.get("permissions"), dict) else {}
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    claude_md = h / "CLAUDE.md"
    return {
        "Intent": {
            "claude_md_exists": claude_md.is_file(),
            "claude_md_bytes": _bytes(claude_md),
            "commands_count": _count_files(h / "commands", "*.md"),
        },
        "Memory": {
            "brain_l1_lines": _line_count(h / "brain" / "l1" / "insight-index.jsonl"),
            "brain_l2_lines": _line_count(h / "brain" / "l2" / "global-facts.jsonl"),
            "memory_index_exists": (h / "memory").is_dir() or (h / "projects").is_dir(),
        },
        "Planning": {
            "handoff_exists": (h / "HANDOFF.md").is_file(),
            "orchestrator_sessions": _count_files(h / "state" / "orchestrator", "*"),
        },
        "Authority": {
            "settings_exists": (h / "settings.json").is_file(),
            "allow_rules": len(perms.get("allow") or []),
            "deny_rules": len(perms.get("deny") or []),
        },
        "Control": {
            "hook_events_registered": len([k for k in hooks if hooks.get(k)]),
            "validators_count": _validators_count(),
        },
        "Tools": {
            "validators_count": _validators_count(),
            "skills_count": _count_files(h / "skills", "**/*.md"),
            "agents_count": _count_files(h / "agents", "*.md"),
        },
    }


def render_evidence(home=None) -> str:
    ev = impact_evidence(home)
    lines = ["[IMPACT evidence] deterministic facts (cite these in the 6-axis scoring):"]
    for ax in _AXES:
        facts = ev.get(ax, {})
        kv = ", ".join(f"{k}={v}" for k, v in facts.items())
        lines.append(f"  {ax}: {kv}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    print(render_evidence())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
