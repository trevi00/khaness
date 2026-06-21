#!/usr/bin/env python3
"""calendar_gate_emitter.py — Stop hook adapter for residual-norm deadlines.

Path 2 D6 (debate-1779229138-db17ce gen 3 LOCK SHA
c75bfaf403981c1fcd8cb45c0872c83ae564b777). Adapts pure
`lib.calendar_gate.scan_deadlines` results to the Stop-hook
`{"decision": "block", "reason": "..."}` payload shape.

## Hook ordering invariant (settings.json — registration is operator-gated)

This module is NOT auto-registered in settings.json (runtime policy
mutation per CLAUDE.md requires explicit `apply-user-preference` token).
Operator-side registration order suggestion:

  Stop:
    - response_guard.py            (existing — fires when no autopilot active)
    - autopilot_continue.py        (existing — fires when autopilot active)
    - calendar_gate_emitter.py     (this    — fires unconditionally; blocks
                                    on overdue residual-norm ledgers with
                                    known_defects > 0)

Each Stop hook can independently emit `{"decision": "block", ...}`; the
runtime aggregates blocking reasons into a single blockingError surfaced
to the model. This emitter is order-independent because it has no read/
write contention with the other two hooks (state/residual_norm/ vs
state/autopilot/ + cooldown file).

## Stop hook I/O contract

Input (stdin):
  {
    "hook_event_name": "Stop",
    "stop_hook_active": bool,
    "last_assistant_message": str | null,
    "session_id": str,
    "transcript_path": str,
    "cwd": str,
    "agent_id": str | null
  }

Output (stdout): JSON payload OR empty body (no block).
  Block:    {"decision": "block", "reason": "<calendar-gate findings>"}
  No-op:    {} (or empty body — runtime treats both as 'continue')

## Importable adapter (for D5 e2e + dispatcher pre-check reuse)

`build_block_payload(state_root, today) -> dict | None` is the pure
adapter. Returns None when no overdue ledgers exist (no block needed),
else returns the Stop-hook payload dict ready for json.dump(stdout).

`today` is INJECTED — no datetime.date.today() inside the adapter. CLI
`main()` is the only entry that resolves `today` from the system clock.
Testability invariant from blueprint L5.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.calendar_gate import ScanResult, scan_deadlines  # noqa: E402


# Maximum scan results to surface in the block reason — beyond this we
# summarize the tail count. Prevents huge Stop-hook payloads when many
# ledgers go overdue simultaneously (degenerate state).
MAX_SURFACED: int = 5


def _format_reason(results: list[ScanResult]) -> str:
    """Render a Stop-hook reason string from overdue ScanResults.

    Format:
      "calendar-gate: <N> residual-norm ledger(s) overdue with unresolved
      defects:
        - <gate_id>: deadline=<YYYY-MM-DD>, days_overdue=<N>,
          known_defects=<N> (ledger=<path>)
        ...
      Resolve each ledger's known_defects → 0 (real fix) or extend its
      deadline (explicit deferral) before continuing."
    """
    n = len(results)
    surfaced = results[:MAX_SURFACED]
    overflow = n - len(surfaced)

    lines = [
        f"calendar-gate: {n} residual-norm ledger(s) overdue with "
        f"unresolved defects:",
    ]
    for r in surfaced:
        lines.append(
            f"  - {r.gate_id}: deadline={r.deadline.isoformat()}, "
            f"days_overdue={r.days_overdue}, "
            f"known_defects={r.known_defects} "
            f"(ledger={r.ledger_path})"
        )
    if overflow > 0:
        lines.append(f"  ... and {overflow} more (truncated to {MAX_SURFACED})")
    lines.append(
        "Resolve each ledger's known_defects -> 0 (real fix) or extend "
        "its deadline (explicit deferral) before continuing."
    )
    return "\n".join(lines)


def build_block_payload(
    state_root: Path | str,
    today: date,
) -> dict | None:
    """Pure adapter — scan + format. Returns Stop-hook payload OR None.

    Returns None when scan_deadlines returns []; caller emits empty body
    (no block). Returns the {"decision": "block", "reason": "..."} dict
    when one or more ledgers are overdue with known_defects > 0.

    Pure: no date.today(), no env, no stdout/stderr. Caller (main / D5
    e2e test) provides `today`.
    """
    if not isinstance(today, date):
        raise TypeError(
            f"today must be datetime.date, got {type(today).__name__}"
        )
    errors: list = []
    results = scan_deadlines(state_root, today, on_error=errors)
    if not results:
        return None
    return {
        "decision": "block",
        "reason": _format_reason(results),
    }


def _resolve_state_root() -> Path:
    """Resolve state_root for the CLI entry.

    Priority:
      1. CLAUDE_HOME env (test override) → $CLAUDE_HOME/state
      2. ~/.claude/state (default home)
    """
    claude_home = os.environ.get("CLAUDE_HOME")
    if claude_home:
        return Path(claude_home) / "state"
    return Path.home() / ".claude" / "state"


def main() -> int:
    """Stop hook CLI entry. Returns process exit code.

    Reads Stop hook JSON from stdin (currently unused — adapter does not
    depend on hook input). Writes payload dict to stdout (decision=block
    OR empty body). Always exits 0 — hook contract requires non-error
    exit; the decision channel signals state.
    """
    try:
        # Drain stdin (Stop hook input schema). Not currently consumed —
        # calendar-gate is hook-input-agnostic by design — but must read
        # to honor pipe contract.
        try:
            _ = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            # Empty stdin or malformed input: still run the scan. The
            # gate's value is in unblocking work that should not proceed
            # silently when deadlines lapse; we tolerate hook-input
            # corruption rather than swallowing the gate.
            pass

        state_root = _resolve_state_root()
        today = date.today()
        payload = build_block_payload(state_root, today)
        if payload is None:
            # Empty body = continue. Match other Stop hook no-op convention.
            return 0
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        return 0
    except Exception as e:
        # Fail-open: emitter MUST NOT block the turn on its own bug.
        # Stop hook contract: nonzero exit blocks; zero exit + empty body
        # continues. We swallow + log to stderr (debug visibility) and
        # return 0 so the gate's bug does not freeze the conversation.
        sys.stderr.write(
            f"[calendar_gate_emitter] swallowed error: "
            f"{type(e).__name__}: {e}\n"
        )
        return 0


# ============================================================================
# Embedded self-check (single-file mutation surface invariant)
# ============================================================================


def _self_check() -> int:
    import json as _json
    import tempfile

    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # ---- Case 1: build_block_payload rejects non-date today ----
    try:
        build_block_payload("/x", "2026-05-20")  # type: ignore[arg-type]
        case("build_rejects_str_today", False, "expected TypeError")
    except TypeError:
        case("build_rejects_str_today", True)

    # ---- Case 2: missing state_root returns None (no block) ----
    payload = build_block_payload("/nonexistent/xyz", date(2026, 5, 20))
    case("missing_state_returns_none", payload is None)

    # ---- Case 3: empty residual_norm returns None ----
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "residual_norm").mkdir()
        payload = build_block_payload(td, date(2026, 5, 20))
        case("empty_returns_none", payload is None)

    # ---- Case 4: zero-defect overdue ledger returns None ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "clean.json").write_text(_json.dumps({
            "gate_id": "clean", "known_defects": 0,
            "deadline": "2026-01-01",
        }))
        payload = build_block_payload(td, date(2026, 5, 20))
        case("zero_defect_returns_none", payload is None)

    # ---- Case 5: one overdue ledger with defects returns block ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 2,
            "deadline": "2026-01-01",
        }))
        payload = build_block_payload(td, date(2026, 5, 20))
        case("one_overdue_returns_block",
             payload is not None and payload["decision"] == "block")
        case("block_reason_contains_gate_id",
             payload and "rlm_gate" in payload["reason"])
        case("block_reason_contains_days_overdue",
             payload and "days_overdue=" in payload["reason"])
        case("block_reason_contains_known_defects",
             payload and "known_defects=2" in payload["reason"])

    # ---- Case 6: N>MAX_SURFACED summarized with overflow line ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        for i in range(7):
            (rn / f"gate_{i:02d}.json").write_text(_json.dumps({
                "gate_id": f"gate_{i:02d}", "known_defects": 1,
                "deadline": "2026-01-01",
            }))
        payload = build_block_payload(td, date(2026, 5, 20))
        case("many_overdue_returns_block", payload is not None)
        case("many_overdue_truncates",
             payload and f"and {7 - MAX_SURFACED} more" in payload["reason"])

    # ---- Case 7: build_block_payload return shape json-serializable ----
    with tempfile.TemporaryDirectory() as td:
        rn = Path(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 1,
            "deadline": "2026-01-01",
        }))
        payload = build_block_payload(td, date(2026, 5, 20))
        try:
            _json.dumps(payload, ensure_ascii=False)
            case("payload_json_serializable", True)
        except (TypeError, ValueError) as e:
            case("payload_json_serializable", False, str(e))

    # ---- Case 8: _resolve_state_root honors CLAUDE_HOME env ----
    saved = os.environ.get("CLAUDE_HOME")
    try:
        os.environ["CLAUDE_HOME"] = "/tmp/override-root"
        resolved = _resolve_state_root()
        case("env_override_state_root",
             str(resolved) in ("/tmp/override-root/state",
                                "\\tmp\\override-root\\state",
                                "/tmp/override-root\\state"))
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_HOME", None)
        else:
            os.environ["CLAUDE_HOME"] = saved

    # ---- report ----
    for name, ok, detail in cases:
        marker = "[OK]" if ok else "[FAIL]"
        suffix = f": {detail}" if detail and not ok else ""
        print(f"  {marker} {name}{suffix}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(cases)} self-check assertions failed")
        return 1
    print(f"\n[OK] {len(cases)} self-check assertions passed")
    return 0


if __name__ == "__main__":
    # CLI entry split: --self-check runs embedded tests; otherwise behave
    # as Stop hook (read stdin, write stdout, exit 0).
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    sys.exit(main())
