#!/usr/bin/env python3
"""debate_converge_check — deterministic convergence consumer for the debate loop (M24).

Replaces harness-debate.md step-4's prose convergence computation (the orchestrator
recomputing `sha1(ontology_snapshot.fields)` by hand and eyeballing the rule) with a single
deterministic entrypoint the markdown invokes once per generation AFTER appending the
architect verdict event. It reads the session events, applies the A1 severity-invalidate
override, computes the canonical snapshot SHA-1, and OWNS the loop-control mutation: it
appends EXACTLY ONE `convergence {status: converged|conditional|rejected}` event (the
primary gen-verdict marker — distinct from M14's `convergence{status: early_hard_cap}`,
partitioned by `status`).

Control contract (the markdown branches mechanically on these):
  stdout: one JSON line {converged, status, this_sha, prev_sha, severity_invalidated, reason, gen, error}
  exit codes:  0 = not converged (continue to next generation)
               3 = CONVERGED (stop loop, emit step-5 converged output)
               4 = internal error / fail-CLOSED (verdict missing/parse) -> escalate
               2 = argparse usage error ONLY (reserved; never a semantic signal)

Idempotent per gen: a re-run that finds its own prior `convergence` event (status in
converged/conditional/rejected) for this gen is a no-op returning the prior decision. The
convergence RULE is unchanged — only its evaluation is deterministic. Mirrors M14's
cli.debate_stagnation_check style + fail-closed try/except.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.debate_convergence import evaluate_convergence  # noqa: E402
from lib.event_store import EventStore  # noqa: E402

EXIT_CONTINUE = 0
EXIT_CONVERGED = 3
EXIT_ERROR = 4

_PRIMARY_STATUSES = ("converged", "conditional", "rejected")


def _prior_convergence(store: EventStore, gen: int) -> dict | None:
    """Idempotency: a prior primary `convergence` event (NOT early_hard_cap) for this gen."""
    for ev in store.iter_by_type("convergence"):
        payload = ev.get("payload") or {}
        if ev.get("gen") == gen and payload.get("status") in _PRIMARY_STATUSES:
            return ev
    return None


def run(session_id: str, gen: int) -> tuple[dict, int]:
    """Evaluate convergence for one generation and append the single primary convergence
    event. Returns (result_dict, exit_code). The mutation is performed HERE so an LLM
    markdown step cannot silently skip it."""
    store = EventStore(session_id)

    prior = _prior_convergence(store, gen)
    if prior is not None:
        p = prior.get("payload") or {}
        converged = p.get("status") == "converged"
        return ({
            "converged": converged, "status": p.get("status"), "gen": gen,
            "reason": "idempotent replay (prior convergence event exists)",
            "this_sha": p.get("snapshot_sha1"), "prev_sha": p.get("prev_sha"),
            "severity_invalidated": p.get("severity_invalidated", False),
            "error": None, "skipped": True,
        }, EXIT_CONVERGED if converged else EXIT_CONTINUE)

    res = evaluate_convergence(store.replay(), gen)
    result = {
        "converged": res.converged, "status": res.status, "gen": gen,
        "declared_verdict": res.declared_verdict, "effective_verdict": res.effective_verdict,
        "severity_invalidated": res.severity_invalidated,
        "this_sha": res.this_sha, "prev_sha": res.prev_sha,
        "reason": res.reason, "error": res.error, "skipped": False,
    }
    if res.error:
        # Fail-CLOSED: do NOT append a convergence event on a parse/sequencing fault.
        return result, EXIT_ERROR

    store.append("convergence", gen, "debate_converge_check", {
        "status": res.status, "gen": gen, "reason": res.reason,
        "snapshot_sha1": res.this_sha, "prev_sha": res.prev_sha,
        "severity_invalidated": res.severity_invalidated, "terminal": res.converged,
    })
    return result, (EXIT_CONVERGED if res.converged else EXIT_CONTINUE)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cli.debate_converge_check",
        description="Deterministic convergence + severity-invalidate consumer (M24).",
    )
    p.add_argument("--session-id", required=True)
    p.add_argument("--gen", type=int, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse owns exit 2 (usage) ONLY
    try:
        result, code = run(args.session_id, args.gen)
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: any internal error -> exit 4
        result = {"converged": False, "status": "rejected", "gen": args.gen,
                  "error": f"{type(exc).__name__}: {exc}", "skipped": False}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stderr.write(f"[debate_converge_check] FAIL-CLOSED: {result['error']}\n")
        return EXIT_ERROR

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    if code == EXIT_ERROR and result.get("error"):
        sys.stderr.write(f"[debate_converge_check] FAIL-CLOSED: {result['error']}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
