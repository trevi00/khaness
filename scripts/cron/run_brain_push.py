#!/usr/bin/env python3
"""run_brain_push — deliberate brain force-snapshot (M29, enable-cron-job gated).

Consumes state/brain-push-ready.flag emitted by check_brain_push.py and FORCE-saves
the live learned-state into brain/ via brain_store.save() — bypassing the 900s
Stop-hook throttle for a deliberate snapshot (e.g. immediately before a machine
handoff, or to recover from a MISSED Stop tick). save() is the same idempotent
union the Stop-hook uses (committed ∪ live), so this is safe to run any time.

It then AUTO-PUSHES the just-saved brain/ to the dedicated ORPHAN `brain-snapshots`
branch (lib.brain_autopush) — full durability automation (M-brain-handoff D1). The
enable-cron-job token authorizes BOTH the force-SAVE and this brain-snapshots push;
pushing to a NON-default branch is not the default-branch hard gate, so it stays
automatable. The DEFAULT-branch (master) push of brain/ remains the operator's
hard-gated flow. A push failure (non-ff / no creds) is fail-soft — brain/ is saved
locally and the E1 SessionStart advisory (lib.brain_git_status) nudges.

Per CLAUDE.md §Mutation table (L0 invariant):
  cron job registration (this file's existence)   — auto OK
  cron job execution (force save() into brain/)    — requires `enable-cron-job` token

Token gate: set env HARNESS_MUTATION_TOKEN=enable-cron-job; without it, REFUSE → exit 1.

Run manually:  HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.run_brain_push
Exit code: 0 (success/idle), 1 (token missing or failure).
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.advisory_ack import resolve as resolve_advisory  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402

REQUIRED_TOKEN: str = "enable-cron-job"
TOKEN_ENV: str = "HARNESS_MUTATION_TOKEN"

FLAG_PATH: Path = STATE_DIR / "brain-push-ready.flag"


class TokenMissingError(RuntimeError):
    """Raised when the enable-cron-job token is absent."""


def _assert_token() -> None:
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"brain push blocked: env {TOKEN_ENV}={actual!r} != {REQUIRED_TOKEN!r}. "
            f"Operator action: set {TOKEN_ENV}={REQUIRED_TOKEN} to grant execution. "
            f"See CLAUDE.md §Mutation 분류 (L0 invariant)."
        )


def _consume_flag(ts_ms: int) -> bool:
    if not FLAG_PATH.exists():
        return False
    try:
        FLAG_PATH.rename(FLAG_PATH.with_name(f"{FLAG_PATH.name}.consumed.{ts_ms}"))
        return True
    except OSError:
        return False


def main() -> int:
    try:
        _assert_token()
    except TokenMissingError as e:
        print(str(e), file=sys.stderr)
        return 1

    # SC1: per-INVOCATION uuid — NEVER module-level.
    run_uuid_hex8 = uuid.uuid4().hex[:8]
    ts_ms = int(time.time() * 1000)
    ack_key = f"{ts_ms}:{run_uuid_hex8}"

    if not FLAG_PATH.exists():
        print(f"[idle] brain-push: flag absent; nothing to do (ack_key={ack_key} not recorded).")
        return 0

    from lib import brain_store
    try:
        summary = brain_store.save()
    except Exception as e:  # noqa: BLE001 — do NOT ack/consume on failure
        print(f"[error] brain-push: save() raised {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    resolve_advisory("brain_push_completed").ack(ack_key)
    _consume_flag(ts_ms)
    layers = ", ".join(f"{k}={v}" for k, v in sorted(summary.items()))
    print(f"[done] brain-push: force-saved {layers} ack_key={ack_key}")

    # D1 (M-brain-handoff): the enable-cron-job token already authorizes execution;
    # auto-push the just-saved brain/ to the dedicated ORPHAN `brain-snapshots` branch
    # (NOT the default branch — that push stays the operator's hard gate). Fail-soft:
    # a push failure (non-ff / no creds) leaves the E1 SessionStart advisory to nudge.
    from lib import brain_autopush
    res = brain_autopush.autopush()
    if res["pushed"]:
        state = "no change (already current)" if not res["committed"] else "committed + pushed"
        print(f"[auto-push] brain-snapshots: {state}")
    else:
        print(f"[auto-push] brain-snapshots NOT pushed ({res['reason']}) — "
              f"brain/ saved locally; SessionStart advisory will nudge. "
              f"master push stays your hard-gated flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
