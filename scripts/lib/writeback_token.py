"""writeback_token — D1 apply_gate per debate-1778236168-53dedd.

Two-step token arm/apply mechanism:
  1. `arm(proposal_id, pre_image_sha1)` writes
     state/writeback/tokens/<proposal_id>.token — a sha1(proposal_id +
     pre_image_sha1 + os.urandom(16)) string, file mode 0o600.
  2. `apply()` site validates `consume(proposal_id, presented_token,
     pre_image_sha1)` — token equality + TTL freshness + pre_image
     match → unlinks the token (single-use) and returns True.

TTL default 300s, env-overridable WRITEBACK_APPLY_TOKEN_TTL bounds
[60, 1800]; out-of-bounds or unparseable → fallback 300 + stderr warn-once.

The token is filesystem-based (no process memory) so the operator's
arm-then-apply CAN happen across two CLI invocations. Single-use is
enforced by atomic unlink on consume.

Public surface:
  - DEFAULT_TTL_SECONDS, MIN_TTL_SECONDS, MAX_TTL_SECONDS
  - resolve_ttl()           respects env override
  - arm(proposal_id, pre_image_sha1) -> str (token)
  - consume(proposal_id, presented_token, pre_image_sha1) -> ConsumeResult
  - ConsumeResult           OK | TOKEN_INVALID | TOKEN_EXPIRED | PRE_IMAGE_DRIFT
  - token_path(proposal_id) -> Path
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


DEFAULT_TTL_SECONDS: int = 300
MIN_TTL_SECONDS: int = 60
MAX_TTL_SECONDS: int = 1800


_TTL_WARN_EMITTED = False


def resolve_ttl() -> int:
    """Read WRITEBACK_APPLY_TOKEN_TTL env override; clamp/fallback as needed.

    Out-of-bounds or unparseable → return DEFAULT_TTL_SECONDS and emit
    one stderr warning per process (warn-once via module-global flag).
    """
    global _TTL_WARN_EMITTED
    raw = os.environ.get("WRITEBACK_APPLY_TOKEN_TTL")
    if raw is None or raw == "":
        return DEFAULT_TTL_SECONDS
    try:
        v = int(raw)
    except (TypeError, ValueError):
        if not _TTL_WARN_EMITTED:
            print(
                f"WRITEBACK_APPLY_TOKEN_TTL unparseable ({raw!r}), "
                f"using {DEFAULT_TTL_SECONDS}s",
                file=sys.stderr,
            )
            _TTL_WARN_EMITTED = True
        return DEFAULT_TTL_SECONDS
    if v < MIN_TTL_SECONDS or v > MAX_TTL_SECONDS:
        if not _TTL_WARN_EMITTED:
            print(
                f"WRITEBACK_APPLY_TOKEN_TTL={v} out of bounds "
                f"[{MIN_TTL_SECONDS}, {MAX_TTL_SECONDS}], "
                f"using {DEFAULT_TTL_SECONDS}s",
                file=sys.stderr,
            )
            _TTL_WARN_EMITTED = True
        return DEFAULT_TTL_SECONDS
    return v


class ConsumeResult(Enum):
    OK = "ok"
    TOKEN_INVALID = "token_invalid"     # missing or wrong token text
    TOKEN_EXPIRED = "token_expired"     # mtime older than TTL
    PRE_IMAGE_DRIFT = "pre_image_drift" # target sha1 changed since arm


@dataclass(frozen=True)
class ArmResult:
    token: str
    path: str


def _tokens_dir() -> Path:
    """Lazy STATE_DIR resolution (test-fixture-compatible)."""
    from .paths import STATE_DIR
    d = STATE_DIR / "writeback" / "tokens"
    d.mkdir(parents=True, exist_ok=True)
    return d


def token_path(proposal_id: str) -> Path:
    return _tokens_dir() / f"{proposal_id}.token"


def _compute_token(proposal_id: str, pre_image_sha1: str, nonce: bytes) -> str:
    """sha1(proposal_id || pre_image_sha1 || nonce) → 40-char hex."""
    h = hashlib.sha1()
    h.update(proposal_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(pre_image_sha1.encode("utf-8"))
    h.update(b"\x00")
    h.update(nonce)
    return h.hexdigest()


def arm(proposal_id: str, pre_image_sha1: str) -> ArmResult:
    """Mint a token bound to (proposal_id, pre_image_sha1) + random nonce.

    Writes token text to state/writeback/tokens/<proposal_id>.token
    (mode 0o600, overwrites any prior arm for the same proposal). The
    file's mtime is the issue time; consume() compares against TTL.

    ⚠️ TTL-source tradeoff (deep-audit pass-2 — honest characterization):
      The freshness window is the file's mtime, which is MUTABLE — a `touch`
      resets it (extending the TTL) and ordinary filesystem ops (copy/restore)
      can perturb it. This is NOT a boundary weakness: the token file is 0o600
      and arm() is freely callable by the same user, so an actor who can touch
      the file can simply re-arm() for a fresh token — mtime-mutability grants no
      capability they lack. The TTL is a self-imposed freshness DISCIPLINE (don't
      apply a stale arm), not a tamper-proof expiry. If a future caller needs a
      tamper-evident window, embed issued_at in the payload (3rd line) and compare
      against that instead of st_mtime — do NOT read this gate as adversary-proof.
    """
    if not isinstance(proposal_id, str) or not proposal_id:
        raise ValueError("proposal_id must be non-empty str")
    if not isinstance(pre_image_sha1, str) or len(pre_image_sha1) != 40:
        raise ValueError("pre_image_sha1 must be 40-char sha1 hex")

    nonce = os.urandom(16)
    token = _compute_token(proposal_id, pre_image_sha1, nonce)

    p = token_path(proposal_id)
    # Stash the bound pre_image_sha1 alongside the token so consume can
    # detect drift without re-deriving from disk.
    payload = f"{token}\n{pre_image_sha1}\n"
    # Atomic write: temp + os.replace
    import tempfile
    fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".",
                                     suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, str(p))
        tmp_name = ""
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass

    return ArmResult(token=token, path=str(p))


def consume(proposal_id: str, presented_token: str,
            pre_image_sha1: str) -> ConsumeResult:
    """Validate a presented token and unlink on success (single-use).

    Returns:
      OK              — token matches, TTL fresh, pre_image matches; file unlinked
      TOKEN_INVALID   — file missing OR token text mismatch
      TOKEN_EXPIRED   — file mtime older than TTL (file unlinked)
      PRE_IMAGE_DRIFT — token matches but pre_image_sha1 differs (file kept)

    The unlink-on-OK side effect makes this single-use: a re-presented
    token with the same proposal_id finds nothing and returns
    TOKEN_INVALID.
    """
    if not isinstance(proposal_id, str) or not proposal_id:
        return ConsumeResult.TOKEN_INVALID
    if not isinstance(presented_token, str) or not presented_token:
        return ConsumeResult.TOKEN_INVALID
    if not isinstance(pre_image_sha1, str) or len(pre_image_sha1) != 40:
        return ConsumeResult.TOKEN_INVALID

    p = token_path(proposal_id)
    if not p.is_file():
        return ConsumeResult.TOKEN_INVALID

    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ConsumeResult.TOKEN_INVALID

    parts = text.splitlines()
    if len(parts) < 2:
        return ConsumeResult.TOKEN_INVALID
    stored_token, stored_pre_image = parts[0], parts[1]

    # TTL check via mtime
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return ConsumeResult.TOKEN_INVALID
    age = max(0.0, time.time() - mtime)
    if age > resolve_ttl():
        try:
            p.unlink()
        except OSError:
            pass
        return ConsumeResult.TOKEN_EXPIRED

    if stored_token != presented_token:
        return ConsumeResult.TOKEN_INVALID

    if stored_pre_image != pre_image_sha1:
        return ConsumeResult.PRE_IMAGE_DRIFT

    # All checks passed — single-use unlink
    try:
        p.unlink()
    except OSError:
        pass
    return ConsumeResult.OK
