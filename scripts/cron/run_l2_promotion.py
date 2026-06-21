#!/usr/bin/env python3
"""run_l2_promotion — L2 Global Facts promoter (S2, debate-1779328283-9076f2 LOCK).

debate-1779328283-9076f2 14-LOCK sha1 59cc1bab06a1af2019763d414cf345a2db7626df.

Consumes the `state/l2-promotion-ready.flag` emitted by check_l2_promotion.py
(W14 emitter — already shipped) and runs the L1 → L2 projection via
lib.l2_promoter.promote_all().

Per CLAUDE.md §Mutation 분류 (L0 invariant):
  cron job *registration*   — auto OK (this file's existence)
  cron job *execution*       — requires `enable-cron-job` token gate

Token gate (D11 LOCK + ops contract):
  Set env `HARNESS_MUTATION_TOKEN=enable-cron-job` before invocation.
  Without the token, this script REFUSES execution and exits with the
  remediation advisory printed to stderr.

Run sequence (on token-granted invocation):
  1. ASSERT enable-cron-job token present (refuse otherwise)
  2. Check state/l2-promotion-ready.flag exists (no-op if absent)
  3. Generate per-run uuid_hex8 LOCALLY (SC1 LOCK: per-INVOCATION,
     NEVER cached at module load)
  4. Invoke lib.l2_promoter.promote_all() → (facts, edges, cascades)
  5. Ack via lib.advisory_ack.resolve('l2_promotion_completed').ack(
     f'{ts_ms}:{uuid_hex8}'
   )
  6. Rename flag → state/l2-promotion-ready.flag.consumed.<ts_ms> (audit
     trail; do NOT delete)
  7. Reset p99_consecutive_over to 0 in state/l2-promotion-check.json
     (closes Q-trigger-loop: L2 promotion itself can reduce L1 query load)
  8. Print one-line summary to stdout

Per gen-3 SC1 explicit remediation: uuid_hex8 lives as a LOCAL var in main(),
never as a module-level constant — multiple invocations within the same
Python process produce distinct keys.
"""
from __future__ import annotations

import json
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

FLAG_PATH: Path = STATE_DIR / "l2-promotion-ready.flag"
CHECK_STATE_PATH: Path = STATE_DIR / "l2-promotion-check.json"


class TokenMissingError(RuntimeError):
    """Raised when enable-cron-job token is absent."""


def _assert_token() -> None:
    """D11 ops contract — REFUSE without the enable-cron-job token.

    Per CLAUDE.md Mutation table: cron job execution is token-gated.
    Refuse early to avoid producing partial L2 state.
    """
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"L2 promoter blocked: env {TOKEN_ENV}={actual!r} != {REQUIRED_TOKEN!r}. "
            f"Operator action: set {TOKEN_ENV}={REQUIRED_TOKEN} to grant execution. "
            f"See CLAUDE.md §Mutation 분류 (L0 invariant)."
        )


def _consume_flag(ts_ms: int) -> bool:
    """Rename flag → .consumed.<ts_ms>. Returns True iff flag existed.

    Renaming preserves audit trail; deletion would lose evidence of when
    the promoter ran. Multiple .consumed.<ts> files accumulate — operator
    can prune via standard FS tooling.
    """
    if not FLAG_PATH.exists():
        return False
    consumed_path = FLAG_PATH.with_name(f"{FLAG_PATH.name}.consumed.{ts_ms}")
    try:
        FLAG_PATH.rename(consumed_path)
        return True
    except OSError:
        return False


def _reset_p99_streak() -> None:
    """Reset p99_consecutive_over to 0 in l2-promotion-check.json.

    Closes the trigger feedback loop: L2 promotion may have reduced L1
    query load (smaller working set after cascade), so the streak should
    not pre-fire the trigger on next cron tick.
    """
    if not CHECK_STATE_PATH.exists():
        return
    try:
        state = json.loads(CHECK_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if state.get("p99_consecutive_over", 0) == 0:
        return
    state["p99_consecutive_over"] = 0
    state["last_promotion_run_ts_ms"] = int(time.time() * 1000)
    try:
        CHECK_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def main() -> int:
    """Main entry. Returns 0 on success, 1 on token missing or failure.

    Token absent → exit 1 + advisory on stderr (no L2 mutation).
    Flag absent → exit 0 (no-op, normal idle state).
    """
    try:
        _assert_token()
    except TokenMissingError as e:
        print(str(e), file=sys.stderr)
        return 1

    # SC1 LOCK: per-INVOCATION uuid generation. NEVER promote this to a
    # module-level constant. If `main()` is called twice within the same
    # Python process (e.g., test harness), each call produces a DISTINCT
    # uuid_hex8 so ack keys never collide.
    run_uuid_hex8 = uuid.uuid4().hex[:8]
    ts_ms = int(time.time() * 1000)
    ack_key = f"{ts_ms}:{run_uuid_hex8}"

    flag_present = FLAG_PATH.exists()
    if not flag_present:
        print(
            f"[idle] l2-promotion: flag absent; no work to do "
            f"(ack_key={ack_key} not recorded)."
        )
        return 0

    # Late import: promoter pulls in l2_facts which performs ModuleSpec
    # writer-whitelist checks. Importing inside main() keeps test-time
    # mocking simpler and avoids importing the writer chain when the
    # token check fails.
    from lib import l2_promoter

    try:
        result = l2_promoter.promote_all()
    except Exception as e:
        # Do NOT ack on failure (token grant is per-invocation; partial
        # state means the operator should re-inspect).
        print(
            f"[error] l2-promotion: promote_all raised {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 1

    # Successful execution — ack + consume flag + reset streak.
    resolve_advisory("l2_promotion_completed").ack(ack_key)
    _consume_flag(ts_ms)
    _reset_p99_streak()

    print(
        f"[done] l2-promotion: facts_emitted={result['facts_emitted']} "
        f"evidence_edges={result['evidence_edges_emitted']} "
        f"cascade_retracted={result['cascade_retracted']} "
        f"support_below_threshold={result['support_below_threshold_retracted']} "
        f"ack_key={ack_key}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
