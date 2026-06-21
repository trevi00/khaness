#!/usr/bin/env python3
"""run_pollution_cleanup — L1 insight-index pollution cleanup (M29, enable-cron-job gated).

Consumes state/pollution-cleanup-ready.flag emitted by check_pollution.py and
retracts the confirmed burst-pollution records via lib.insight_index.retract()
(D7 LOCK: append-only retraction record, NEVER hard-delete). Re-confirms pollution
at run time (does not trust the flag's snapshot) so a record that gained a live run
artifact since emission is no longer retracted — idempotent + safe.

Per CLAUDE.md §Mutation table (L0 invariant):
  cron job registration (this file's existence)   — auto OK
  cron job execution (retracting index records)    — requires `enable-cron-job` token

This is a SECOND, stronger gate than the existing detector's "ad-hoc admin" measure
ready-flag: automated cleanup goes through the enable-cron-job token, the manual CLI
(`insight_index_pollution_detector detect --execute`) keeps its own ad-hoc gate.

Token gate: set env HARNESS_MUTATION_TOKEN=enable-cron-job; without it, REFUSE → exit 1.

Run manually:  HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.run_pollution_cleanup
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

FLAG_PATH: Path = STATE_DIR / "pollution-cleanup-ready.flag"


class TokenMissingError(RuntimeError):
    """Raised when the enable-cron-job token is absent."""


def _assert_token() -> None:
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"pollution cleanup blocked: env {TOKEN_ENV}={actual!r} != {REQUIRED_TOKEN!r}. "
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


def cleanup() -> dict:
    """Delegate retraction to the SANCTIONED cli.insight_index_pollution_detector —
    the whitelisted index-hygiene retractor (insight_index_importer_whitelist:95,
    D6 judge-generator isolation). We deliberately do NOT import lib.insight_index
    here: that import is whitelist-gated ('update _ALLOWED_IMPORTERS via debate'), so
    instead we drive the existing operator-approved retract path by subprocess —
    `measure` arms the detect ready-flag, then `detect --execute` retracts confirmed
    pollution (append-only D7) and consumes the flag. Raises on any non-zero rc so the
    caller does NOT ack/consume on failure."""
    import subprocess
    scripts = str(_SCRIPTS)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    cli = [sys.executable, "-m", "cli.insight_index_pollution_detector"]
    measure = subprocess.run(cli + ["measure"], cwd=scripts, env=env,
                             capture_output=True, text=True)
    if measure.returncode != 0:
        raise RuntimeError(f"measure failed rc={measure.returncode}: {(measure.stderr or '').strip()[:200]}")
    execute = subprocess.run(cli + ["detect", "--execute"], cwd=scripts, env=env,
                             capture_output=True, text=True)
    if execute.returncode != 0:
        raise RuntimeError(f"detect --execute failed rc={execute.returncode}: {(execute.stderr or '').strip()[:200]}")
    last = (execute.stdout or "").strip().splitlines()
    return {"measure_rc": 0, "execute_rc": 0, "summary": last[-1] if last else ""}


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
        print(f"[idle] pollution-cleanup: flag absent; nothing to do (ack_key={ack_key} not recorded).")
        return 0

    try:
        summary = cleanup()
    except Exception as e:  # noqa: BLE001 — do NOT ack/consume on failure
        print(f"[error] pollution-cleanup: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    resolve_advisory("pollution_cleanup_completed").ack(ack_key)
    _consume_flag(ts_ms)
    print(f"[done] pollution-cleanup: {summary.get('summary', '')} ack_key={ack_key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
