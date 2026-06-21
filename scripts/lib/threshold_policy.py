"""threshold_policy — config-override resolution + token-gated apply for tunable thresholds (M22 D4).

Converged design: debate-1781603679-a14912 gen 2 (D4). Mirrors lib/critic_policy.py's
config+token closure, for NUMERIC thresholds instead of the binary invoke/skip decision.

  resolve_threshold(name, default)         -> override-or-default (read by call-sites)
  apply_threshold_override(name, value, *, token) -> bool (token-gated writer)

Token reuse (gen-1 Critic B5 — NO new mutate token, NO L0 Mutation-table edit): the
risky/unsafe direction reuses graduate-validator's TOKEN_GRADUATE plus the per-threshold
ready-flag (emitted by threshold_proposer ONLY on gate-accept); the safe direction needs
only apply-user-preference. Direction is derived from the registry entry's direction_safety:
'either' is treated as risky (conservative — cannot prove safe). apply_threshold_override
RE-CHECKS LOCKED_DENY at apply time, so a token can NEVER touch a locked invariant even if
mis-called. Forensics on every apply via state/threshold-policy-history.jsonl.

Persistence: ~/.claude/config/threshold-overrides.yaml (lazy, tiny-YAML numeric subset —
no PyYAML dependency, like critic_policy).
"""
from __future__ import annotations

from pathlib import Path

from .paths import CLAUDE_HOME, STATE_DIR
from .graduation import TOKEN_GRADUATE, TOKEN_DEMOTE  # "graduate-validator" / "apply-user-preference"
from .calibration import threshold_registry as reg

POLICY_PATH: Path = CLAUDE_HOME / "config" / "threshold-overrides.yaml"

TOKEN_RISKY: str = TOKEN_GRADUATE   # "graduate-validator" — unsafe direction (+ ready-flag)
TOKEN_SAFE: str = TOKEN_DEMOTE      # "apply-user-preference" — safe direction


def _coerce_num(raw: str) -> float | int | None:
    raw = raw.strip()
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return None


def _safe_yaml_load(text: str) -> dict:
    """Tiny-YAML subset: `version: <int>` + `overrides:` mapping of name -> number."""
    out: dict = {"version": 1, "overrides": {}}
    in_overrides = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "overrides:":
            in_overrides = True
            continue
        if line.startswith("version:"):
            in_overrides = False
            try:
                out["version"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if in_overrides and line.startswith((" ", "\t")) and ":" in line:
            k, v = line.strip().split(":", 1)
            num = _coerce_num(v)
            if k.strip() and num is not None:
                out["overrides"][k.strip()] = num
    return out


def _safe_yaml_dump(policy: dict) -> str:
    lines = [f"version: {int(policy.get('version', 1))}", "overrides:"]
    for k in sorted(policy.get("overrides", {}) or {}):
        lines.append(f"  {k}: {policy['overrides'][k]}")
    return "\n".join(lines) + "\n"


def load_policy() -> dict:
    if not POLICY_PATH.exists():
        return {"version": 1, "overrides": {}}
    try:
        return _safe_yaml_load(POLICY_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {"version": 1, "overrides": {}}


def resolve_threshold(name: str, default):
    """Return the override for `name` if present and the name is a registered tunable,
    else `default`. Fail-soft: a malformed/missing config or an UNREGISTERED name always
    returns `default`, so a tunable call-site can never crash nor read an off-allowlist value.
    """
    if name not in reg.REGISTRY:
        return default
    override = load_policy().get("overrides", {}).get(name)
    return override if override is not None else default


def _ready_flag_path(name: str) -> Path:
    safe = name.replace("/", "_").replace("\\", "_")
    return STATE_DIR / "threshold-ready" / f"{safe}.flag"


def _is_risky(entry: reg.TunableThreshold, value: float) -> bool:
    """Risky = the less-conservative direction. raise_safe→lowering risky; lower_safe→raising
    risky; 'either'→always risky (cannot prove safe — conservative)."""
    if entry.direction_safety == "raise_safe":
        return value < entry.default
    if entry.direction_safety == "lower_safe":
        return value > entry.default
    return True  # 'either'


def _append_history(record: dict) -> None:
    try:
        from .logging import jsonl_append, now_iso
        from .paths import ensure_dir
        ensure_dir(STATE_DIR)
        jsonl_append(STATE_DIR / "threshold-policy-history.jsonl", {"ts": now_iso(), **record})
    except Exception:
        pass


def apply_threshold_override(name: str, value, *, token: str | None) -> bool:
    """Set `name`'s override to `value`, gated by direction-dependent token + (risky) ready-flag.

    Returns True on a persisted change, False on no-op (already at value).
    Raises:
      ValueError      : name not registered OR (apply-time deny re-check) name is LOCKED.
      PermissionError : token wrong for the direction, OR risky direction without the ready-flag.
    """
    entry = reg.REGISTRY.get(name)
    if entry is None:
        raise ValueError(f"{name!r} is not a registered tunable threshold")
    # Apply-time deny re-check (D4): a token can NEVER touch a locked invariant.
    if reg.is_locked(entry.qualified()):
        raise ValueError(f"{name!r} -> {entry.qualified()} is LOCKED (invariant; never tunable)")

    if resolve_threshold(name, entry.default) == value:
        return False

    risky = _is_risky(entry, value)
    required = TOKEN_RISKY if risky else TOKEN_SAFE
    if (token or "").strip() != required:
        direction = "risky/unsafe" if risky else "safe"
        raise PermissionError(
            f"applying {name}={value} ({direction} direction) requires token {required!r}, got {token!r}"
        )
    if risky:
        flag = _ready_flag_path(name)
        if not flag.exists():
            raise PermissionError(
                f"{name}={value} is the risky direction and has no ready-flag — a gate-accepted "
                f"proposal must exist first (run cli.calibration_review / threshold_proposer)"
            )

    policy = load_policy()
    overrides = dict(policy.get("overrides", {}) or {})
    overrides[name] = value
    policy["overrides"] = overrides
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(_safe_yaml_dump(policy), encoding="utf-8")

    # Consume the ready-flag (anti-replay) on a risky apply.
    if risky:
        try:
            _ready_flag_path(name).unlink()
        except OSError:
            pass

    _append_history({
        "action": "apply_threshold_override", "name": name, "value": value,
        "direction": "risky" if risky else "safe", "token_used": required,
    })
    return True
