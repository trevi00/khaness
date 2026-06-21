#!/usr/bin/env python3
"""strike_research_consume — deterministic consumer for the strike->research->skill loop (M18).

Converged design: debate-1781594208-53fee4 gen 3 (snapshot sha1
286f4c8e18a4427dcc897e2b86a4e1844b5a6c79). Sibling of cli.debate_stagnation_check (M14):
it replaces prose-only "the orchestrator is responsible for spawning the researcher" and
"the dispatcher routes the artifact to git-master" wiring (harness-ralph.md / harness-autopilot.md)
with a single deterministic CLI an LLM cannot silently skip.

Two subcommands across the necessarily-split seam (a cli/ process CANNOT call the Agent
tool — only the LLM orchestrator can spawn a subagent, so that one spawn is the irreducible
LLM step):

  dispatch  (decide_dispatch)  — PRE-spawn gate. should_dispatch + record_dispatch (locked
            lib.strike_dispatcher) + emits a research_dispatched event + prints the exact
            harness-researcher payload. exit 3 = SPAWN (markdown spawns the researcher with
            the printed payload); exit 0 = skip (below threshold / quota exhausted / standalone).

  consume   (consume_artifact) — POST-artifact. Parses state/research/strikes/<fp>.md, routes
            per D3 (skill_gotcha -> no-degradation gate -> stage|escalate; hook_rule/settings_change
            -> operator-escalation-only; no_research/escalate -> forensic-only), stages via the
            reused lib.skill_candidate_detector primitives with the D3 clobber-guard, and records
            a strike_research_consumed forensic event. exit 0 = clean; exit 4 = fail-closed.

Exit-code contract (markdown branches mechanically; mirrors debate_stagnation_check):
  0 = ran cleanly                              2 = argparse usage error ONLY (reserved)
  3 = dispatch fired (spawn researcher)        4 = internal error / fail-CLOSED (never stages)

INVARIANTS (D4): consume_artifact NEVER calls record_dispatch (dispatch-side quota only).
Idempotency: consume scans prior strike_research_consumed events for (sid, fingerprint) — a
replay is a no-op returning the prior outcome. Fail-CLOSED: any error -> exit 4, NOTHING staged.
Forensics + idempotency share the orchestrator's canonical events.jsonl at
state/orchestrator/<sid>/events.jsonl (co-located with strike_dispatcher's dispatch_counter.json).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
_LIB = _SCRIPTS / "lib"
for _p in (str(_SCRIPTS), str(_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.logging import jsonl_append, now_iso  # noqa: E402
from lib.paths import STATE_DIR  # noqa: E402
from lib.strike_dispatcher import (  # noqa: E402
    should_dispatch,
    record_dispatch,
    remaining_quota,
)
from lib.repro_probe import build_probe  # noqa: E402
from lib.no_degradation_gate import evaluate_skill_gotcha  # noqa: E402
# Imported BARE (not `lib.skill_candidate_detector`) because the module uses a bare
# `from atomic_json import ...` — it is loaded as a top-level module (lib/ on sys.path),
# matching how handlers/post_tool/skill_candidate_extractor.py imports it so both share
# one module object (mock.patch in tests targets the same instance).
import skill_candidate_detector as scd  # noqa: E402

EXIT_CLEAN = 0
EXIT_FIRE = 3
EXIT_ERROR = 4

_ORCH_DIR = STATE_DIR / "orchestrator"
_STRIKES_DIR = STATE_DIR / "research" / "strikes"
# Path-safe fingerprint: hash hex / alnum slug only — no separators, no dots, no
# '..' (the fingerprint becomes a filename; rank-11 traversal guard).
_SAFE_FINGERPRINT_RE = re.compile(r"[0-9A-Za-z_-]+")

_VALID_VERDICTS = ("accepted_change", "no_research_available", "escalate_to_user")
_CHANGE_TYPES = ("skill_gotcha", "hook_rule", "settings_change")
# Change types that MUST NOT auto-stage (touch settings.json / hooks = NEVER-auto invariant).
_ESCALATE_ONLY_TYPES = ("hook_rule", "settings_change")


# ---------- orchestrator-canonical event log (shape matches engine.orchestrator) ----------

def _events_path(sid: str) -> Path:
    return _ORCH_DIR / sid / "events.jsonl"


def _append_event(sid: str, event_type: str, payload: dict) -> None:
    record = {"ts": now_iso(), "type": event_type, "sid": sid, "payload": payload}
    jsonl_append(_events_path(sid), record)


def _prior_consumed(sid: str, fingerprint: str) -> dict | None:
    """Idempotency (D4): the prior strike_research_consumed event for (sid, fingerprint)."""
    path = _events_path(sid)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "strike_research_consumed" \
                        and (rec.get("payload") or {}).get("fingerprint") == fingerprint:
                    return rec
    except OSError:
        return None
    return None


# ---------- dispatch (pre-spawn gate) ----------

def decide_dispatch(
    session_id: str,
    fingerprint: str,
    *,
    strike_count: int,
    tool_name: str,
    error_excerpt: str,
) -> tuple[dict, int]:
    """Pre-spawn gate. Reuses the locked lib.strike_dispatcher primitives.

    Returns (result, exit_code): exit 3 carries the researcher payload (markdown spawns
    the Agent), exit 0 = skip. Standalone (no super-session sid / no orchestrator dir) ->
    skip per harness-ralph.md item 5 (no auto-dispatch without a super-session).
    """
    result: dict = {"action": "skip", "fingerprint": fingerprint, "payload": None,
                    "reason": None, "error": None}
    if not session_id or not fingerprint:
        result["reason"] = "missing session_id/fingerprint"
        return result, EXIT_CLEAN
    if not (_ORCH_DIR / session_id).exists():
        result["reason"] = "standalone (no super-session) -> no auto-dispatch"
        return result, EXIT_CLEAN
    if not should_dispatch(fingerprint, session_id, strike_count=strike_count):
        result["reason"] = "gate denied (below threshold or per-fingerprint quota exhausted)"
        return result, EXIT_CLEAN

    new_count = record_dispatch(fingerprint, session_id)
    payload = {
        "subagent_type": "harness-researcher",
        "fingerprint": fingerprint,
        "error_excerpt": (error_excerpt or "")[:400],
        "tool_name": tool_name,
        "attempts": strike_count,
        "sid": session_id,
        "dispatch_count_for_fingerprint": new_count,
        "remaining_quota": remaining_quota(fingerprint, session_id),
    }
    _append_event(session_id, "research_dispatched", payload)
    result.update(action="dispatch", payload=payload, reason="threshold met, quota available")
    return result, EXIT_FIRE


# ---------- consume (post-artifact) ----------

def _section(text: str, header: str) -> str:
    """Return the body of a `## <header>` markdown section (until the next `## ` or EOF)."""
    m = re.search(rf"(?mi)^##\s+{re.escape(header)}\s*$", text)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"(?m)^##\s+", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return text[start:end].strip()


def _parse_strike_artifact(text: str) -> dict:
    """Parse a harness-researcher strikes/<fp>.md artifact (tolerant).

    Returns {verdict, change_type, gotcha_body, tool, target_skill_hint, signature}.
    verdict/change_type are None when not recognizable (-> escalate/forensic, never stage).
    """
    title_m = re.search(r"(?m)^#\s+Strike\s+\S+\s+—\s+(.+)$", text) or \
        re.search(r"(?m)^#\s+Strike\s+\S+\s+-\s+(.+)$", text)
    title = (title_m.group(1).strip() if title_m else "")
    tool_m = re.search(r"(?mi)^\*\*Tool\*\*:\s*(.+)$", text)
    tool = (tool_m.group(1).strip() if tool_m else "")

    verdict_sec = _section(text, "Verdict")
    verdict = next((v for v in _VALID_VERDICTS if v in verdict_sec), None)

    change_sec = _section(text, "Proposed permanent change")
    change_type = next((t for t in _CHANGE_TYPES if t in change_sec), None)

    # target skill hint: a skills/<...>.md path mentioned in the change section.
    hint_m = re.search(r"skills[\\/][\w./\\-]+\.md", change_sec)
    target_skill_hint = hint_m.group(0) if hint_m else None

    root = _section(text, "Root cause")
    signature = (title + " " + root).strip()[:400]
    return {
        "verdict": verdict, "change_type": change_type, "gotcha_body": change_sec,
        "tool": tool, "target_skill_hint": target_skill_hint, "signature": signature,
    }


def _escalate(sid: str, fingerprint: str, artifact_path: Path, reason: str,
              change_type: str | None) -> dict:
    """Operator-escalation-only: write <fp>.escalation.json + emit an event. NO candidate."""
    esc_path = artifact_path.with_suffix(".escalation.json")
    payload = {"fingerprint": fingerprint, "reason": reason, "change_type": change_type,
               "requires": "operator", "artifact": str(artifact_path)}
    try:
        esc_path.parent.mkdir(parents=True, exist_ok=True)
        esc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    _append_event(sid, "strike_research_escalated", payload)
    return payload


def consume_artifact(
    session_id: str,
    fingerprint: str,
    *,
    artifact_path: str | None = None,
) -> tuple[dict, int]:
    """Consume a researcher strike artifact: route -> gate -> stage|escalate -> forensics.

    Idempotent per (sid, fingerprint). NEVER calls record_dispatch (D4). Fail-CLOSED is the
    caller's main() responsibility — here the normal routes return cleanly; the only raises
    are programmer errors that main() maps to exit 4 with nothing staged.
    """
    result: dict = {"fingerprint": fingerprint, "staged": False, "candidate_id": None,
                    "verdict": None, "change_type": None, "escalated": False,
                    "deduped": False, "reason": None, "error": None}
    if not session_id or not fingerprint:
        result["error"] = "missing session_id/fingerprint -> parse_failure"
        return result, EXIT_ERROR
    # Path-safety (deep-audit pass-2 rank 11): the fingerprint becomes a filename
    # (_STRIKES_DIR/<fp>.md and the .escalation.json derived from it). Reject any
    # separator / '..' / dot so a crafted fingerprint cannot traverse out of the
    # strikes dir. Legit fingerprints are hash hex / alnum slugs.
    if not _SAFE_FINGERPRINT_RE.fullmatch(fingerprint):
        result["error"] = "invalid fingerprint (path-unsafe) -> parse_failure"
        return result, EXIT_ERROR

    # D4 idempotency: a prior consume for this (sid, fingerprint) is a no-op.
    prior = _prior_consumed(session_id, fingerprint)
    if prior is not None:
        p = prior.get("payload") or {}
        result.update({k: p.get(k, result[k]) for k in result if k in p})
        result["deduped"] = True
        result["reason"] = "idempotent replay (prior consume exists)"
        return result, EXIT_CLEAN

    path = Path(artifact_path) if artifact_path else (_STRIKES_DIR / f"{fingerprint}.md")
    if not path.exists():
        result["error"] = f"artifact missing: {path}"
        return result, EXIT_ERROR
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        result["error"] = f"artifact unreadable: {e}"
        return result, EXIT_ERROR

    parsed = _parse_strike_artifact(text)
    result["verdict"] = parsed["verdict"]
    result["change_type"] = parsed["change_type"]

    verdict = parsed["verdict"]
    change_type = parsed["change_type"]

    # Routing (D3).
    if verdict in (None, "no_research_available", "escalate_to_user"):
        result["reason"] = f"forensic-only (verdict={verdict})"
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    # verdict == accepted_change from here.
    if change_type in _ESCALATE_ONLY_TYPES:
        _escalate(session_id, fingerprint, path,
                  reason=f"{change_type} touches NEVER-auto surface (settings/hooks)",
                  change_type=change_type)
        result.update(escalated=True, reason=f"operator-escalation-only ({change_type})")
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    if change_type != "skill_gotcha":
        # accepted_change but unrecognized change type -> escalate (never stage on ambiguity).
        _escalate(session_id, fingerprint, path,
                  reason="accepted_change with unrecognized change_type", change_type=change_type)
        result.update(escalated=True, reason="unrecognized change_type -> escalate")
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    # skill_gotcha + accepted_change -> probe -> gate -> stage|escalate.
    probe = build_probe(fingerprint, parsed["tool"] or "unknown", parsed["signature"])
    if probe is None:
        # B6: non-deterministic / precondition-fidelity-lost -> operator-escalation (NOT silent).
        _escalate(session_id, fingerprint, path,
                  reason="non-deterministic fingerprint (probe unbuildable)", change_type="skill_gotcha")
        result.update(escalated=True, reason="probe None -> operator-escalation (B6)")
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    candidate = scd._build_candidate_from_strike(
        fingerprint, parsed["gotcha_body"], parsed["target_skill_hint"], str(path))
    if candidate is None:
        result["reason"] = "candidate build failed (bad fingerprint/empty body)"
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    clean = scd._secret_scan_pass(candidate)
    candidate = dataclasses.replace(candidate, secret_scan_clean=clean)
    gate = evaluate_skill_gotcha(candidate, probe)
    if not gate.accept:
        if not clean:
            scd._write_blocked_marker(candidate)
        result["reason"] = f"gate reject: {gate.reason}"
        _append_event(session_id, "strike_research_consumed", result)
        return result, EXIT_CLEAN

    # Accept -> stage with the D3 clobber-guard, then surface the research artifact path
    # onto the surviving candidate regardless of write-vs-skip outcome.
    write_status = scd._write_candidate(candidate, collision_policy="priority")
    scd._surface_strike_artifact(candidate.id, str(path))
    result.update(staged=True, candidate_id=candidate.id,
                  deduped=(write_status == "skipped_lower_priority"),
                  reason=f"staged ({write_status}); awaiting enable-skill")
    _append_event(session_id, "strike_research_consumed", result)
    return result, EXIT_CLEAN


# ---------- CLI ----------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.strike_research_consume",
        description="Deterministic strike->research->skill-candidate consumer (M18).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("dispatch", help="pre-spawn gate (exit 3 = spawn researcher)")
    d.add_argument("--session-id", required=True)
    d.add_argument("--fingerprint", required=True)
    d.add_argument("--strike-count", type=int, required=True)
    d.add_argument("--tool-name", default="unknown")
    d.add_argument("--error-excerpt", default="")

    c = sub.add_parser("consume", help="post-artifact consume (stage|escalate|forensic)")
    c.add_argument("--session-id", required=True)
    c.add_argument("--fingerprint", required=True)
    c.add_argument("--artifact-path", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # argparse owns exit 2 (usage) ONLY
    try:
        if args.cmd == "dispatch":
            result, code = decide_dispatch(
                args.session_id, args.fingerprint,
                strike_count=args.strike_count, tool_name=args.tool_name,
                error_excerpt=args.error_excerpt,
            )
        else:
            result, code = consume_artifact(
                args.session_id, args.fingerprint, artifact_path=args.artifact_path,
            )
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: any internal error -> exit 4
        result = {"error": f"{type(exc).__name__}: {exc}", "staged": False}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stderr.write(f"[strike_research_consume] FAIL-CLOSED: {result['error']}\n")
        return EXIT_ERROR

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    if code == EXIT_ERROR and result.get("error"):
        sys.stderr.write(f"[strike_research_consume] FAIL-CLOSED: {result['error']}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
