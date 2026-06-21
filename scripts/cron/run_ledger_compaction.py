#!/usr/bin/env python3
"""run_ledger_compaction — operator-ledger compactor (M29, enable-cron-job gated).

Consumes state/ledger-compaction-ready.flag emitted by check_ledger_compaction.py
and rewrites each qualifying operator-ledger JSONL: keeps the latest record per
task_hash (+ every human_override + every task_hash-less row), and ARCHIVES the
superseded duplicates to a `<ledger>.compacted.<ts_ms>` sibling — never hard-deletes
(mirrors run_l2_promotion's `.consumed` audit discipline). Idempotent: a re-run over
an already-compacted ledger finds 0 superseded and rewrites it unchanged.

Per CLAUDE.md §Mutation table (L0 invariant):
  cron job registration (this file's existence) — auto OK
  cron job execution (rewriting ledgers)        — requires `enable-cron-job` token

Token gate: set env HARNESS_MUTATION_TOKEN=enable-cron-job before invocation;
without it this script REFUSES and exits 1 with a remediation advisory on stderr.

Run sequence (on token-granted invocation):
  1. ASSERT enable-cron-job token (refuse otherwise → exit 1)
  2. Flag absent → no-op exit 0
  3. Per-INVOCATION uuid_hex8 (SC1: local var in main(), NEVER module-level)
  4. Re-scan + compact each qualifying ledger (re-evaluated at run time, not trusted
     from the flag → idempotent + safe if state changed since emission)
  5. Ack via advisory_ack.resolve('ledger_compaction_completed').ack(f'{ts}:{uuid}')
  6. Rename flag → state/ledger-compaction-ready.flag.consumed.<ts_ms>
  7. One-line summary

Run manually:  HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.run_ledger_compaction
Exit code: 0 (success/idle), 1 (token missing or failure).
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

# Reference the checker MODULE (not by-name imports) so thresholds + scanner are a
# single source of truth, patchable in one place (avoids by-name binding drift).
from cron import check_ledger_compaction as chk  # noqa: E402
from lib.ledger_compaction import compaction_plan, redundancy_ratio  # noqa: E402

FLAG_PATH = chk.FLAG_PATH


class TokenMissingError(RuntimeError):
    """Raised when the enable-cron-job token is absent."""


def _assert_token() -> None:
    actual = os.environ.get(TOKEN_ENV, "").strip()
    if actual != REQUIRED_TOKEN:
        raise TokenMissingError(
            f"ledger compaction blocked: env {TOKEN_ENV}={actual!r} != {REQUIRED_TOKEN!r}. "
            f"Operator action: set {TOKEN_ENV}={REQUIRED_TOKEN} to grant execution. "
            f"See CLAUDE.md §Mutation 분류 (L0 invariant)."
        )


def _write_jsonl_atomic(path: Path, records: tuple[dict, ...] | list[dict]) -> None:
    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body + ("\n" if body else ""), encoding="utf-8")
    tmp.replace(path)


def _archive_superseded(ledger: Path, superseded: tuple[dict, ...], ts_ms: int) -> Path:
    """Append superseded records to <ledger>.compacted.<ts_ms> (audit, never delete)."""
    archive = ledger.with_name(f"{ledger.name}.compacted.{ts_ms}")
    body = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in superseded)
    with archive.open("a", encoding="utf-8") as f:
        f.write(body + ("\n" if body else ""))
    return archive


def _consume_flag(ts_ms: int) -> bool:
    if not FLAG_PATH.exists():
        return False
    try:
        FLAG_PATH.rename(FLAG_PATH.with_name(f"{FLAG_PATH.name}.consumed.{ts_ms}"))
        return True
    except OSError:
        return False


def compact_all(ts_ms: int) -> dict:
    """Re-scan and compact every qualifying ledger. Returns a summary dict."""
    compacted: list[dict] = []
    total_reclaimed = 0
    for ledger in chk._iter_ledger_files(chk.LEDGER_ROOT):
        records = chk._read_jsonl(ledger)
        if len(records) < chk.MIN_RECORDS or redundancy_ratio(records) < chk.MIN_REDUNDANCY:
            continue
        plan = compaction_plan(records)
        if plan.reclaimed == 0:
            continue
        _archive_superseded(ledger, plan.superseded, ts_ms)
        _write_jsonl_atomic(ledger, plan.kept)
        total_reclaimed += plan.reclaimed
        compacted.append({"path": str(ledger), "kept": len(plan.kept),
                          "archived": plan.reclaimed})
    return {"compacted_ledgers": compacted, "total_reclaimed": total_reclaimed}


def main() -> int:
    try:
        _assert_token()
    except TokenMissingError as e:
        print(str(e), file=sys.stderr)
        return 1

    # SC1: per-INVOCATION uuid — NEVER a module-level constant.
    run_uuid_hex8 = uuid.uuid4().hex[:8]
    ts_ms = int(time.time() * 1000)
    ack_key = f"{ts_ms}:{run_uuid_hex8}"

    if not FLAG_PATH.exists():
        print(f"[idle] ledger-compaction: flag absent; nothing to do (ack_key={ack_key} not recorded).")
        return 0

    try:
        summary = compact_all(ts_ms)
    except Exception as e:  # noqa: BLE001 — do NOT ack/consume on failure
        print(f"[error] ledger-compaction: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    resolve_advisory("ledger_compaction_completed").ack(ack_key)
    _consume_flag(ts_ms)
    print(f"[done] ledger-compaction: ledgers={len(summary['compacted_ledgers'])} "
          f"records_archived={summary['total_reclaimed']} ack_key={ack_key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
