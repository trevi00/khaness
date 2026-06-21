#!/usr/bin/env python3
"""autopilot_continue.py — single-hook merge for autopilot iteration loop.

Per debate-1778224899-c24de4 (converged at gen 3):
  - D1'' = "unified"   — single tag <autopilot mode='execute'|'advisory'>
  - D2'' = "merged"    — single read/write via lib.autopilot_state
  - D3'' = "single"    — ONE Stop hook subsumes response_guard logic when
                          autopilot session is active

Hook ordering invariant (settings.json):
  Stop:
    - response_guard.py    (existing)  — fires when NO autopilot active
    - autopilot_continue.py (this)     — fires when autopilot active

response_guard.py is updated to check autopilot-active and skip; this hook
takes over the decision=block channel and emits ONE combined payload that
includes BOTH response_guard findings (via response_guard_core.analyze)
AND the autopilot directive.

Stop hook input schema (same as response_guard):
  {
    "hook_event_name": "Stop",
    "stop_hook_active": bool,
    "last_assistant_message": str | null,
    "session_id": str,
    "transcript_path": str,
    "cwd": str,
    "agent_id": str | null
  }

Output (Stop hooks only honor top-level decision/reason — addenda C4):
  {"decision": "block", "reason": "<combined response_guard findings + autopilot directive>"}

Retry taxonomy (D3'' addenda):
  - tag_miss        : counter++, terminal `tag_miss_exhausted` at MAX_TAG_MISS=2
  - json_error      : counter++, terminal `json_error_exhausted` at MAX_JSON_ERROR=2
  - empty_body      : no counter, re-emits block each turn; NO per-occurrence
                      terminal (`empty_body_persisted` is UNIMPLEMENTED — deep-audit
                      pass-2 rank 8). Termination falls back to the global wallclock
                      cap (MAX_WALLCLOCK_SECONDS=1800) checked at can_continue() top —
                      NOT an unbounded loop, but no dedicated retry ceiling.

Tag parser (D1'' addenda):
  - Case-insensitive regex with whitespace tolerance
  - Quotes optional (single, double, or none)
  - mode token lowercased before equality
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

# Stream reconfigure for the CLI-shell runtime (the hook reads JSON from stdin /
# writes the decision to stdout in utf-8). Runs at import, so it must be
# import-SAFE: under pytest / any importer, sys.stdin|stdout may be a capture
# object (DontReadFromInput, StringIO) with no .reconfigure → AttributeError at
# import time, which silently breaks test collection for every module that
# imports this hook (E2-review finding #3, debate-1780564679-8mgxsd). Guard on
# the method's existence + swallow stream errors — hook discipline: NEVER raise
# at import. Real TextIOWrapper streams (the live CLI) still get reconfigured.
for _stream in (sys.stdin, sys.stdout):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handlers.stop.response_guard_core import (  # noqa: E402
    analyze_response,
    format_finding_lines,
)
from lib.autopilot_state import (  # noqa: E402
    AutopilotState,
    advance_iter,
    list_active_sids,
    read_state,
    write_state,
)
from lib.logging import log_telemetry  # noqa: E402


# D1'' addenda: case-insensitive whitespace-tolerant unified tag parser.
# Captures mode token; comparison done after .lower() per addendum spec.
_AUTOPILOT_TAG_RE = re.compile(
    r"<autopilot\s+mode\s*=\s*['\"]?(execute|advisory)['\"]?\s*>",
    re.IGNORECASE,
)

# Iteration result body MAY come in either:
#   <iteration-result>...</iteration-result>
# or inside the autopilot tag:
#   <autopilot mode='execute'>...</autopilot>
# We capture the FULL inner content (any chars, lazy) — JSON validity is
# decided by json.loads, not regex. This separates "no body" (whitespace
# only) from "body present but malformed" per D3'' addenda taxonomy.
_ITER_RESULT_RE = re.compile(
    r"<iteration-result>(.*?)</iteration-result>",
    re.IGNORECASE | re.DOTALL,
)
_INSIDE_AUTOPILOT_TAG_RE = re.compile(
    r"<autopilot\s+mode\s*=\s*['\"]?execute['\"]?\s*>(.*?)</autopilot>",
    re.IGNORECASE | re.DOTALL,
)


def parse_autopilot_tag(message: str) -> dict | None:
    """Return one of:
      - {"kind": "ok",        "mode": ..., "body": dict}   tag found, body parsed
      - {"kind": "json_error","mode": ..., "raw": str}     tag found, body present but JSON malformed
      - {"kind": "empty_body","mode": ...}                 tag found but body absent/whitespace-only
      - None                                                no tag found (= tag_miss)

    Per D3'' addenda taxonomy:
      tag_miss   → return None             (caller: tag_miss_count++)
      json_error → return kind=json_error  (caller: json_error_count++)
      empty_body → return kind=empty_body  (caller: single immediate retry, no counter)
      ok         → return kind=ok          (caller proceeds with body)
    """
    if not isinstance(message, str) or not message.strip():
        return None

    m = _AUTOPILOT_TAG_RE.search(message)
    if not m:
        return None

    mode = m.group(1).lower()  # addendum: lowercase before comparison

    # Extract inner content from execute-tagged block first, then fall back
    # to <iteration-result>. Either may carry the JSON.
    body_match = (
        _INSIDE_AUTOPILOT_TAG_RE.search(message)
        or _ITER_RESULT_RE.search(message)
    )

    if body_match is None:
        # Tag found by _AUTOPILOT_TAG_RE, but no closing-pair block to extract
        # content from. Treat as empty_body (model emitted opening tag but
        # didn't close + provide content).
        return {"kind": "empty_body", "mode": mode}

    raw = body_match.group(1).strip()
    if not raw:
        return {"kind": "empty_body", "mode": mode}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"kind": "json_error", "mode": mode, "raw": raw[:500]}

    if not isinstance(body, dict):
        # Body parsed but not a JSON object — treat as malformed for our schema
        return {"kind": "json_error", "mode": mode, "raw": raw[:500]}

    return {"kind": "ok", "mode": mode, "body": body}


def _build_combined_reason(
    *,
    findings: list[tuple[str, str, str]],
    state: AutopilotState,
    parsed: dict | None,
) -> str:
    """Compose the merged Stop-hook reason text.

    Layout:
      [response_guard findings if any]
      ---
      <autopilot mode='execute' sid='...' iter='N'>
      directive: read state at <path>, run Phase 1-4, emit
      <iteration-result>{validators_passed, tests_passed, blocking_question_count, summary}</iteration-result>
      </autopilot>
    """
    parts: list[str] = []

    if findings:
        parts.append("[응답 품질 경고]")
        parts.append(format_finding_lines(findings))
        parts.append("---")

    next_iter = state.iter + 1
    state_path = f"~/.claude/state/autopilot/{state.sid}.json"

    # Retry taxonomy directive selection (D3'' addenda)
    retry_note = ""
    if parsed is None:
        # tag_miss path
        retry_note = (
            "이전 응답에 <autopilot mode='execute'> 태그가 없었습니다. "
            f"tag_miss_count={state.tag_miss_count + 1}/2. "
            "이번에는 반드시 태그를 emit하고 그 안에 JSON body를 포함하세요."
        )
    elif parsed.get("kind") == "json_error":
        retry_note = (
            "<autopilot> 태그는 발견됐으나 안의 JSON이 malformed였습니다. "
            f"json_error_count={state.json_error_count + 1}/2. "
            "올바른 JSON으로 재발화하세요."
        )
    elif parsed.get("kind") == "empty_body":
        retry_note = (
            "<autopilot> 태그가 있으나 body가 비었습니다. "
            "한 번 더 시도해주세요 — body 비어있으면 terminal."
        )

    parts.append(
        f"<autopilot mode='execute' sid='{state.sid}' iter='{next_iter}'>\n"
        f"{retry_note}\n"
        f"DIRECTIVE: 다음 iteration을 진행하세요.\n"
        f"  1. 상태 파일 읽기: {state_path}\n"
        f"  2. Phase 1-4 실행 (구현 → 검증 → 필요 시 fix loop)\n"
        f"  3. 응답 끝에 다음 형식으로 결과 emit:\n"
        f"     <iteration-result>{{\"validators_passed\":bool,\"tests_passed\":bool,\"blocking_question_count\":int,\"summary\":\"...\"}}</iteration-result>\n"
        f"  4. 또는 goal 도달 시 <autopilot mode='execute'>{{\"goal_reached\":true}}</autopilot>\n"
        f"이 태그를 텍스트로 논의하지 말고 위 단계를 실행하세요.\n"
        f"</autopilot>"
    )

    return "\n".join(parts)


def _select_active_sid(cwd: str) -> str | None:
    """Pick at most one active sid for this cwd. Returns None if 0; if >1,
    picks the most recently heartbeated (deterministic).
    """
    sids = list_active_sids(cwd_filter=cwd)
    if not sids:
        return None
    if len(sids) == 1:
        return sids[0]
    # Multiple active sessions — pick most recent
    states = [(read_state(s), s) for s in sids]
    states_filt = [(s, sid) for s, sid in states if s is not None]
    if not states_filt:
        return None
    states_filt.sort(key=lambda pair: pair[0].last_heartbeat_ts, reverse=True)
    return states_filt[0][1]


def _emit_block(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def _terminal(state: AutopilotState, reason_code: str) -> None:
    """Mark state as failed + write atomically. Caller exits after."""
    failed = AutopilotState(
        sid=state.sid,
        iter=state.iter,
        goal_hash=state.goal_hash,
        status="failed",
        started_ts=state.started_ts,
        last_heartbeat_ts=state.last_heartbeat_ts,
        tag_miss_count=state.tag_miss_count,
        json_error_count=state.json_error_count,
    )
    write_state(failed)
    # C1 definitive save on authoritative autopilot terminal (failed) transition.
    try:
        from lib import work_unit_store
        work_unit_store.force_autosave()
        work_unit_store.record_work_unit(state.sid, "", f"autopilot terminal: {reason_code}", status="failed")
    except Exception:
        pass
    _ = reason_code  # reserved for future event log emit


def _reduce_ac_leaf_events(orch_sid: str) -> str | None:
    """v15.28 (debate-1778990144-679cb8 D2): reduce ac.leaf_evaluated events to verdict.

    Reads state/debates/<orch_sid>/events.jsonl via EventStore.iter_by_type and
    applies the same aggregation rule as lib.ac_tree.aggregate (S1 short-circuit
    composition at the caller — orchestrator signature unchanged).

    Per-leaf event tail wins: if same leaf_id emitted N times, only the last
    emission contributes to the verdict (later evaluations supersede earlier).

    Aggregation rule (identical to lib.ac_tree.aggregate):
      - any gate (axis='gate', passed=False) → 'escalate'
      - all gates True + (any advisory score <= 2 OR mean < 3) → 'iterate'
      - all gates True + (all advisory score >= 3 AND mean >= 3) → 'approved'
      - no ac.leaf_evaluated events found → None (caller falls through)

    Returns None on any error or empty event stream — fail-open invariant
    preserves Stop hook discipline (never raises, never blocks).
    """
    try:
        from lib.event_store import EventStore
    except Exception:
        return None
    try:
        store = EventStore(orch_sid)
    except Exception:
        return None
    if not store.path.exists():
        return None

    # Collect per-leaf tail: leaf_id → (axis, passed, score)
    by_leaf: dict[str, tuple[str, bool, int | None]] = {}
    try:
        for ev in store.iter_by_type("ac.leaf_evaluated"):
            payload = ev.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            leaf_id = payload.get("leaf_id")
            axis = payload.get("axis")
            passed = payload.get("passed")
            score = payload.get("score")
            if not isinstance(leaf_id, str) or not isinstance(axis, str):
                continue
            if not isinstance(passed, bool):
                continue
            if score is not None and not isinstance(score, int):
                continue
            by_leaf[leaf_id] = (axis, passed, score)
    except Exception:
        return None

    if not by_leaf:
        return None

    gate_pass: list[bool] = []
    advisory_scores: list[int] = []
    for axis, passed, score in by_leaf.values():
        if axis == "gate":
            gate_pass.append(passed)
        elif score is not None and 1 <= score <= 5:
            advisory_scores.append(score)
        # silently skip malformed entries (fail-open)

    if gate_pass and not all(gate_pass):
        return "escalate"
    if not advisory_scores:
        return "approved" if gate_pass else None
    mean = sum(advisory_scores) / len(advisory_scores)
    if any(s <= 2 for s in advisory_scores) or mean < 3.0:
        return "iterate"
    return "approved"


def main() -> None:
    try:
        input_data = json.load(sys.stdin)

        # Skip non-Stop / subagent / re-entry
        if input_data.get("hook_event_name", "") not in ("Stop", ""):
            sys.exit(0)
        if input_data.get("stop_hook_active", False):
            sys.exit(0)
        if input_data.get("agent_id"):
            sys.exit(0)

        message = input_data.get("last_assistant_message")
        if not message:
            sys.exit(0)

        cwd = input_data.get("cwd", "") or os.getcwd()

        # C1 (debate-1781431026-af5f83, ontology 32808a52c893): throttled brain
        # auto-save + resume breadcrumb. Placed BEFORE the sid-None guard below so
        # it fires for BOTH autopilot AND non-autopilot Stop turns (the guard exits
        # early when no autopilot session exists — putting this after it would make
        # the non-autopilot common case capture nothing). Throttle BOUNDS frequency
        # (≤ once / 900s, NOT per-turn); brain divergence gates the actual save.
        # Fail-soft side-effect — never breaks the hook chain.
        #
        # kha SDLC one-way state mirror (debate-1781871696-sdoggn, 24-field LOCK):
        # derive .planning/STATE.md -> breadcrumb `extra.kha` so a non-autopilot
        # resume surfaces where the kha project stands. The LOCK named the learner
        # digest block, but Generator-phase reading found THIS is the sole every-Stop
        # breadcrumb writer (a second writer would clobber it), so the inline read
        # was relocated here with operator sign-off. Read-only; never writes .planning/.
        _wu_sid = str(input_data.get("session_id") or "session")
        _kha_resolved = False
        _kha_changed = False
        try:
            from lib import work_unit_store
            _msg = str(message)
            _kha = work_unit_store.read_planning_state(cwd)
            _kha_resolved = _kha is not None
            _extra = None
            if _kha is not None:
                _sha = hashlib.sha1(
                    json.dumps(_kha, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                # none-safe prior-sha read (LOCK g5_sha_read_guard): read_work_unit
                # is None on first run and legacy breadcrumbs carry no 'extra'.
                _prior = (work_unit_store.read_work_unit(_wu_sid) or {}).get("extra", {}).get("planning_sha")
                _kha_changed = _sha != _prior
                _extra = {"kha": _kha, "planning_sha": _sha}
            work_unit_store.record_work_unit(
                _wu_sid, cwd, _msg[:500],
                next_steps=work_unit_store.extract_next_steps(_msg),
                extra=_extra,
            )
            work_unit_store.maybe_autosave()
        except Exception:
            pass
        # Falsifiability counter (LOCK g5_falsifiability_counter): emit OUTSIDE the
        # bare except so a broken/absent kha feed is observable, not silently
        # swallowed — closes the dead-seam class the seam exists to avoid.
        try:
            log_telemetry("kha-state-feed", {
                "resolved": _kha_resolved,
                "changed": _kha_changed,
                "sid": _wu_sid,
            })
        except Exception:
            pass

        # Find active autopilot session for this cwd. If none, this hook is silent
        # (response_guard.py handles the turn as before).
        sid = _select_active_sid(cwd)
        if sid is None:
            sys.exit(0)

        state = read_state(sid)
        if state is None:
            sys.exit(0)

        # Termination check — if caps already exhausted, mark failed + emit terminal
        if not state.can_continue():
            terminal_reason = (
                "tag_miss_exhausted" if state.tag_miss_exhausted()
                else "json_error_exhausted" if state.json_error_exhausted()
                else "iter_cap" if state.iter_cap_hit()
                else "wallclock_cap" if state.wallclock_cap_hit()
                else "unknown"
            )
            _terminal(state, terminal_reason)
            _emit_block(
                f"[autopilot terminal] sid={sid} reason={terminal_reason}. "
                f"세션 종료. /harness-autopilot --resume {sid}로 재개하려면 "
                f"state file 수동 점검 후 status='in_progress'로 복구."
            )
            sys.exit(0)

        # Run response_guard logic too — this is the merge (D3'' single hook)
        findings, _has_blocking = analyze_response(message)

        # Parse autopilot tag (D1'' regex)
        parsed = parse_autopilot_tag(message)

        # Update state per retry taxonomy (D3'' addenda)
        if parsed is None:
            # tag_miss
            new_state = AutopilotState(
                sid=state.sid,
                iter=state.iter,
                goal_hash=state.goal_hash,
                status=state.status,
                started_ts=state.started_ts,
                last_heartbeat_ts=state.last_heartbeat_ts,
                tag_miss_count=state.tag_miss_count + 1,
                json_error_count=state.json_error_count,
            )
            write_state(new_state)
            _emit_block(_build_combined_reason(
                findings=findings, state=state, parsed=None,
            ))
            sys.exit(0)

        kind = parsed.get("kind", "")
        if kind == "json_error":
            new_state = AutopilotState(
                sid=state.sid,
                iter=state.iter,
                goal_hash=state.goal_hash,
                status=state.status,
                started_ts=state.started_ts,
                last_heartbeat_ts=state.last_heartbeat_ts,
                tag_miss_count=state.tag_miss_count,
                json_error_count=state.json_error_count + 1,
            )
            write_state(new_state)
            _emit_block(_build_combined_reason(
                findings=findings, state=state, parsed=parsed,
            ))
            sys.exit(0)

        if kind == "empty_body":
            # No counter increment (addendum: empty_body bypasses counter)
            _emit_block(_build_combined_reason(
                findings=findings, state=state, parsed=parsed,
            ))
            sys.exit(0)

        # kind == "ok" — model emitted valid tag + body
        body = parsed.get("body") or {}
        if body.get("goal_reached") is True:
            # Ground-truth gate. Tries orchestrator's evaluate_completion first
            # (when autopilot followed Phase 5 protocol of shared sid — both
            # state/autopilot/<sid>.json and state/orchestrator/<sid>/ exist),
            # else falls back to inline boolean gate. Both paths prevent
            # false-positive termination from hallucinated goal_reached.
            validators_passed = bool(body.get("validators_passed", False))
            tests_passed = bool(body.get("tests_passed", False))
            blocking_q = int(body.get("blocking_question_count", 0) or 0)

            verdict: str | None = None
            # E2 verdict captured for the escalate-routing reason below; stays
            # None unless the shared-sid path resolves one (debate-1780564679).
            ev_verdict: str | None = None

            # v15.26 Ouroboros S1 short-circuit (debate-1778987814-41b475 D3):
            # If body carries 'ac_verdict' (Generator computed ac_tree.aggregate),
            # gate failure ('escalate') or 'iterate' bypasses evaluate_completion.
            # 'approved' defers to existing orchestrator gate. No orchestrator sig
            # change — composition lives entirely at this caller.
            # ac_verdict normalization: ac_tree returns {'approved','iterate','escalate'};
            # 'approved' maps to existing 'complete' verdict via fall-through to evaluate_completion.
            #
            # v15.28 (debate-1778990144-679cb8 D2): if body.ac_verdict is absent,
            # reduce ac.leaf_evaluated events from orchestrator EventStore via
            # iter_by_type. Same {gate-False→escalate; advisory<=2 OR mean<3→iterate;
            # else→approved} semantic as lib.ac_tree.aggregate, reconstructed from
            # per-leaf event tail (last emission per leaf_id wins). Fail-open: any
            # error path returns None, falls through to evaluate_completion below.
            #
            # Evaluator-side emit-binding contract (Phase 2 call site, future cycle):
            #     sess = load_session(orch_sid)
            #     ac_tree.evaluate_emit(leaves, ctx, emit_fn=sess.event_store.append)
            # Events land in state/debates/<orch_sid>/events.jsonl; this reduction
            # consumes them via the same EventStore instance on the next Stop turn.
            ac_verdict_raw = body.get("ac_verdict")
            if isinstance(ac_verdict_raw, str) and ac_verdict_raw in ("escalate", "iterate"):
                verdict = ac_verdict_raw
            elif ac_verdict_raw is None:
                # No scalar — try event-store reduction (v15.28).
                try:
                    reduced = _reduce_ac_leaf_events(state.sid)
                    if isinstance(reduced, str) and reduced in ("escalate", "iterate"):
                        verdict = reduced
                    # 'approved' or None falls through to evaluate_completion below.
                except Exception:
                    # Fail-open: never crash Stop hook on reduction failure.
                    pass

            if verdict is None:
                # Track whether we have CONFIRMED the shared-sid path before
                # any exception, so the except can fail CLOSED there (E2
                # enforcement) while preserving the legacy inline fallback for
                # the pre-detection / cold-start path. See except below.
                _shared_sid_confirmed = False
                try:
                    # lib-tier adjudication (handler → lib only). Bypass
                    # the prior `from engine.orchestrator import (...)` path
                    # which violated commit_layer_adjacency 4-tier model.
                    # See lib/completion_gate.py module docstring for trail.
                    from lib.completion_gate import (  # noqa: E402
                        count_orchestrator_iterations,
                        decide_completion,
                        iteration_started_ts,
                        latest_fresh_evaluator_verdict,
                    )
                    iter_count = count_orchestrator_iterations(state.sid)
                    if iter_count is not None:
                        _shared_sid_confirmed = True
                        # E2 platform enforcement (debate-1780564679-8mgxsd):
                        # resolve the DGE E2 verdict ONLY from the durable
                        # axis_scores log, bound to the CURRENT iteration so a
                        # stale prior-iteration 'approved' cannot complete a
                        # changed iteration. The agent-controlled <autopilot>
                        # body is deliberately NOT a completion source (B3 —
                        # no ts/provenance, hallucinatable). A missing or
                        # unresolvable verdict under require_evaluator=True
                        # yields 'iterate' (fail-closed), bounded by
                        # iteration>=max_iterations → escalate (D4). This is
                        # the shared-sid path only (iter_count is not None);
                        # the legacy cold-start path below keeps its inline
                        # boolean gate (require_evaluator stays effectively
                        # off, D5).
                        since_ts = iteration_started_ts(state.sid)
                        ev_verdict = latest_fresh_evaluator_verdict(
                            state.sid, since_ts,
                        )
                        verdict = decide_completion(
                            iter_count,
                            validators_passed=validators_passed,
                            tests_passed=tests_passed,
                            blocking_question_count=blocking_q,
                            evaluator_verdict=ev_verdict,
                            require_evaluator=True,
                        )
                except Exception:
                    # Hook discipline: lib import / replay failures must NOT
                    # crash the Stop hook. But the degrade direction matters
                    # for E2 enforcement (debate-1780564679-8mgxsd E2-review
                    # finding #1): once the shared-sid path is confirmed, an
                    # exception must fail CLOSED ('iterate') — NEVER fall back
                    # to the Tier-1 inline gate, which would silently re-open
                    # the E2 skip gap. Before shared-sid is confirmed (import
                    # failure / cold-start replay error) we cannot know it is
                    # an E2-governed run, so we preserve the legacy inline
                    # fallback (verdict=None → inline boolean gate, D5).
                    verdict = "iterate" if _shared_sid_confirmed else None

            inline_pass = (
                validators_passed and tests_passed and blocking_q == 0
            )

            if verdict == "complete" or (verdict is None and inline_pass):
                done = AutopilotState(
                    sid=state.sid,
                    iter=state.iter,
                    goal_hash=state.goal_hash,
                    status="done",
                    started_ts=state.started_ts,
                    last_heartbeat_ts=state.last_heartbeat_ts,
                    tag_miss_count=state.tag_miss_count,
                    json_error_count=state.json_error_count,
                )
                write_state(done)
                # C1 definitive save on authoritative autopilot terminal (done).
                try:
                    from lib import work_unit_store
                    work_unit_store.force_autosave()
                    work_unit_store.record_work_unit(state.sid, "", "autopilot terminal: done", status="done")
                except Exception:
                    pass
                # No block emit — let the turn complete naturally
                sys.exit(0)
            if verdict == "escalate":
                # decide_completion / ac_tree returned 'escalate' — a hard
                # operator-decision signal (E2 evaluator structural concern,
                # blocking question, or iteration cap), NOT a retryable
                # 'iterate'. It MUST surface as terminal, not be folded into
                # advance_iter (which would bury it as another iteration that
                # loops to the autopilot hard cap, never reaching the operator).
                # debate-1780564679-8mgxsd E2-review finding #2: my D2 wiring
                # made an E2 'escalate' verdict newly reachable here, so the
                # escalate→iterate misrouting is now in-scope to fix.
                if blocking_q > 0:
                    esc_reason = "blocking_question"
                elif ev_verdict == "escalate":
                    esc_reason = "evaluator_escalate"
                else:
                    esc_reason = "escalate"
                _terminal(state, esc_reason)
                _emit_block(
                    f"[autopilot escalate] sid={state.sid} reason={esc_reason}. "
                    f"decide_completion='escalate' — 사람 결정 필요(retry 불가). "
                    f"세션 종료. /harness-autopilot --resume {state.sid}로 재개하려면 "
                    f"state file 점검 후 status='in_progress'로 복구."
                )
                sys.exit(0)
            # verdict == 'iterate' OR inline gate failed → next iter
            next_state = advance_iter(state)
            write_state(next_state)
            _emit_block(_build_combined_reason(
                findings=findings, state=next_state, parsed=parsed,
            ))
            sys.exit(0)

        # Iteration completed — advance + ask for next
        next_state = advance_iter(state)
        write_state(next_state)
        _emit_block(_build_combined_reason(
            findings=findings, state=next_state, parsed=parsed,
        ))

    except Exception:
        # Hook discipline: NEVER crash. Silent exit on any error.
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
