#!/usr/bin/env python3
"""debate_stagnation_check — deterministic early-hard-cap consumer for the debate loop (M14).

Replaces harness-debate.md step 4.5's skip-prone prose-pseudocode with a single
deterministic entrypoint the markdown invokes once per non-converged generation.
It reads the session events, runs `lib.debate_stagnation.recommend_early_hard_cap`,
and OWNS the loop-control mutation so an LLM cannot silently skip it: on fire it
appends EXACTLY ONE terminal `convergence {status: "early_hard_cap"}` event; on
every evaluated gen it also appends a forensic `early_hard_cap_recommendation`
event (a NON-convergence type, so it does not contend with the single-convergence
-writer invariant). Idempotent per gen: a re-run that finds its own prior events
is a no-op.

Control contract (the markdown branches mechanically on these):
  stdout: one JSON line {recommend, early_hard_cap, reasons, skipped, error, gen}
  exit codes:  0 = ran cleanly, no fire           (continue the loop)
               3 = early_hard_cap fired            (stop loop, emit step-5 hard-cap output)
               4 = internal error / fail-CLOSED    (stop loop, escalate, operator-visible)
               2 = argparse usage error ONLY       (reserved; never a semantic signal)

Convergence-ownership invariant (LOAD-BEARING): the early_hard_cap `convergence`
event is the TERMINAL loop marker; step-4's per-gen `convergence {status:
conditional|rejected}` is the gen-verdict marker. They are partitioned by
`status` — consumers MUST filter by status, NEVER assume `last_by_type('convergence')`
is the gen-verdict marker.

Self-skip: `--verdict == "approved"` → skip (exit 0). Missing/None/empty/unknown
verdict → fail-CLOSED (exit 4) per the harness-debate.md §Failure-behavior
'verdict missing → parse_failure' contract — NOT a silent continue. The
`DEBATE_DISABLE_EARLY_HARDCAP` kill-switch is honored by the MARKDOWN (it
short-circuits before invoking this CLI).

Mirrors the cli.debate_aggregate template (M1).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.debate_stagnation import read_debate_events, recommend_early_hard_cap  # noqa: E402
from lib.event_store import EventStore  # noqa: E402

# Verdicts that warrant running the detectors — mirror harness-debate.md step-4 guard.
_RUNNABLE_VERDICTS = ("rejected", "conditional")

EXIT_CLEAN = 0
EXIT_FIRE = 3
EXIT_ERROR = 4


def _env_window(name: str, default: int) -> int:
    """Positive-int env override, else default (parse-fail / N<=0 -> default)."""
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except (ValueError, TypeError):
        return default


def _already_fired(store: EventStore, gen: int) -> bool:
    """Idempotency (D4): a prior same-gen early_hard_cap convergence already exists."""
    for ev in store.iter_by_type("convergence"):
        payload = ev.get("payload") or {}
        if payload.get("status") == "early_hard_cap" and ev.get("gen") == gen:
            return True
    return False


def _already_logged_recommendation(store: EventStore, gen: int) -> bool:
    """Idempotency for the forensic event: a prior same-gen recommendation exists."""
    for ev in store.iter_by_type("early_hard_cap_recommendation"):
        if ev.get("gen") == gen:
            return True
    return False


def evaluate_for_session(
    session_id: str,
    gen: int,
    verdict: str | None,
    *,
    oscillation_window: int = 4,
    stagnation_window: int = 3,
    blocker_window: int = 3,
) -> tuple[dict, int]:
    """Run the early-hard-cap decision for one debate generation.

    Returns (result_dict, exit_code). The mutations (forensic + terminal convergence
    events) are performed HERE so they cannot be skipped by an LLM markdown step.
    Raises nothing for the normal paths; the CLI's main() wraps this for fail-closed.
    """
    result: dict = {
        "recommend": False, "early_hard_cap": False, "reasons": [],
        "skipped": False, "error": None, "gen": gen,
    }
    # D5: self-skip on approved; only rejected/conditional gens are evaluated.
    if verdict == "approved":
        result["skipped"] = True
        return result, EXIT_CLEAN
    if verdict not in _RUNNABLE_VERDICTS:
        # missing / None / empty / unknown -> fail-CLOSED (NOT a silent skip).
        result["error"] = f"verdict missing/invalid ({verdict!r}) -> parse_failure"
        return result, EXIT_ERROR

    store = EventStore(session_id)

    # D4: a replayed gen that already fired is a no-op that still terminates correctly.
    if _already_fired(store, gen):
        result.update(recommend=True, early_hard_cap=True, skipped=True)
        return result, EXIT_FIRE

    events = read_debate_events(store.path)
    rec = recommend_early_hard_cap(
        events,
        oscillation_window=oscillation_window,
        stagnation_window=stagnation_window,
        blocker_window=blocker_window,
    )
    reasons = list(rec.reasons)
    result.update(recommend=rec.recommend, reasons=reasons)

    # Forensic event — preserves the recommend=False trail ('recommend=False도 누적가치').
    # NON-convergence type, so it never contends with the single-convergence-writer
    # invariant; dedup-guarded for per-gen idempotency.
    if not _already_logged_recommendation(store, gen):
        store.append("early_hard_cap_recommendation", gen, "debate_stagnation_check", {
            "recommend": rec.recommend,
            "reasons": reasons,
            "signals_summary": {k: rec.signals[k].detected for k in rec.signals},
        })

    if rec.recommend:
        # The SOLE writer of the terminal early_hard_cap convergence event (D1-conv-ownership).
        store.append("convergence", gen, "debate_stagnation_check", {
            "status": "early_hard_cap", "gen": gen, "reasons": reasons, "terminal": True,
        })
        result["early_hard_cap"] = True
        return result, EXIT_FIRE
    return result, EXIT_CLEAN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.debate_stagnation_check",
        description="Deterministic early-hard-cap consumer for the debate loop (M14).",
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--gen", type=int, required=True)
    parser.add_argument(
        "--verdict", default=None,
        help="this gen's architect verdict; approved->skip, rejected/conditional->run, missing->fail-closed",
    )
    parser.add_argument("--oscillation-window", type=int, default=None)
    parser.add_argument("--stagnation-window", type=int, default=None)
    parser.add_argument("--blocker-window", type=int, default=None)
    return parser


def _resolve_window(flag: int | None, env_name: str, default: int) -> int:
    if flag is not None and flag > 0:
        return flag
    return _env_window(env_name, default)


def main(argv: list[str] | None = None) -> int:
    # argparse owns exit 2 for usage errors ONLY — kept walled off from semantic codes.
    args = build_parser().parse_args(argv)
    osc = _resolve_window(args.oscillation_window, "DEBATE_OSCILLATION_WINDOW", 4)
    stg = _resolve_window(args.stagnation_window, "DEBATE_STAGNATION_WINDOW", 3)
    blk = _resolve_window(args.blocker_window, "DEBATE_BLOCKER_WINDOW", 3)
    try:
        result, code = evaluate_for_session(
            args.session_id, args.gen, args.verdict,
            oscillation_window=osc, stagnation_window=stg, blocker_window=blk,
        )
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: any internal error -> exit 4 + marker
        result = {
            "recommend": False, "early_hard_cap": False, "reasons": [],
            "skipped": False, "error": f"{type(exc).__name__}: {exc}", "gen": args.gen,
        }
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stderr.write(f"[debate_stagnation_check] FAIL-CLOSED: {result['error']}\n")
        return EXIT_ERROR

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    if code == EXIT_ERROR and result.get("error"):
        sys.stderr.write(f"[debate_stagnation_check] FAIL-CLOSED: {result['error']}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
