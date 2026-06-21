"""staging_guard — Layer-B runtime guard for D3 staging-only invariant.

debate-1779462559-c29f2b LOCK (gen-2 byte-identical, sha1
67c44483a06d6504209644d792edfd943c4ee3a9) accepted_decisions=['D3'].

Role
    Runtime authoritative backstop for the AST static validator
    (validators/skill_staging_isolation.py — Layer-A). Layer-A has
    accepted false-negatives (getattr-indirection, os.makedirs, shutil,
    subprocess, shell-out). Layer-B catches them at write time.

Public API
    assert_in_staging(path: Path) -> None
        Raise StagingInvariantViolation if `path` is not under any of
        the allowlisted staging roots:
            ~/.claude/skill-candidates/
            ~/.claude/state/skill-candidate-tracker/
        Emits telemetry event 'staging_invariant_violation' on raise.

Invariant scope (LOCK D3.invariant.write_scope)
    writes from skill_draft_pipeline + skill_candidate_detector confined
    to ~/.claude/skill-candidates/<cid>/ and tracker root.

Mutate-token invariant (LOCK D3.invariant.mutate_token_addition)
    No new tokens introduced. Existing {enable-skill, apply-user-preference,
    enable-cron-job, configure-critic-policy} unchanged.

Activation gate invariant (LOCK D3.invariant.activation_gate)
    skill activation remains enable-skill token-gated. Staging artifacts
    default activation.auto=false.

Caller contract
    Callers that write to staging paths SHOULD call assert_in_staging(path)
    immediately before the actual write call. Whether the detector adopts
    this guard at its write sites is governed by a separate debate cycle
    (D3.audit was rejected gen-2 — see debate events.jsonl).
"""
from __future__ import annotations

from pathlib import Path

from .logging import log_telemetry

_HOME = Path.home()
_CANDIDATES_ROOT = _HOME / ".claude" / "skill-candidates"
_TRACKER_ROOT = _HOME / ".claude" / "state" / "skill-candidate-tracker"

ALLOWED_ROOTS: tuple[Path, ...] = (_CANDIDATES_ROOT, _TRACKER_ROOT)


class StagingInvariantViolation(Exception):
    """Raised when a write target lies outside the staging allowlist."""


def _is_under(path: Path, root: Path) -> bool:
    try:
        resolved = Path(path).resolve(strict=False)
        root_resolved = root.resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    try:
        resolved.relative_to(root_resolved)
        return True
    except ValueError:
        return False


def assert_in_staging(path: Path | str) -> None:
    p = Path(path)
    if any(_is_under(p, root) for root in ALLOWED_ROOTS):
        return
    log_telemetry(
        "staging-invariant-violation",
        {
            "event": "staging_invariant_violation",
            "path": str(p),
            "allowed_roots": [str(r) for r in ALLOWED_ROOTS],
        },
    )
    raise StagingInvariantViolation(
        f"write target {p!s} not under any staging root "
        f"({', '.join(str(r) for r in ALLOWED_ROOTS)})"
    )
