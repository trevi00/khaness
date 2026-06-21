#!/usr/bin/env python3
"""PostToolUse hook — v15.10 D1+D2+D3+D5 integrated runtime audit.

For every `Agent` tool invocation this hook:
  1. Captures the agent's response envelope (parses tool_response as JSON
     if possible, otherwise treats it as free-form text).
  2. D2 — runs lib.validators.structural.validate against the agent's
     declared `output_schema` frontmatter (loaded once per agent via
     lib.agent_tool_audit / frontmatter parser). free_text declarations
     skip layer 1.
  3. D1 — runs lib.observers.evidence_fab.detect on the envelope when an
     `evidence` array is present.
  4. D3 — looks up the (agent_type, failure_mode) CompositeBreaker;
     records success on all-clean, failure on any layer report. Emits
     `breaker.*` events via lib.event_store.append.
  5. D5 — appends an outcome record to lib.operator_ledger with the
     verdicts from D1/D2/D3 + critic decision (read from ORCH_CRITIC_DECISION
     env var set by the D4 pre_tool advisor).

Fail-soft contract (same as agent_invocation_audit.py):
  - Hook MUST NOT raise. All exceptions are routed through log_telemetry
    with category `agent-outcome-hook-failed` so silent regression is
    visible on harness_health.
  - Silent no-op for non-Agent tools.

Hook input (Claude Code PostToolUse, matcher=\"Agent\"):
  stdin JSON: {"tool_name", "tool_input", "tool_response", "session_id"}

Hook output: empty (audit-only, no agent-visible feedback).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _safe_call(name: str, fn, *args, **kwargs):
    """Run fn(*args, **kwargs); on failure emit telemetry, return default."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        try:
            from lib.logging import log_telemetry
            log_telemetry(
                "agent-outcome-hook-failed",
                {
                    "stage": name,
                    "error_type": type(exc).__name__,
                    "error_repr": repr(exc)[:200],
                },
            )
        except Exception:
            pass
        return None


def _load_envelope(tool_response):
    """Best-effort JSON parse of agent response. Free-text → empty dict.

    Claude Code Agent tool returns a string (the agent's final assistant
    message). When the agent emits structured JSON we get a dict-shaped
    envelope; otherwise we fall back to a synthetic envelope with the raw
    text under `_raw_text` so D2 layer-1 can still operate on the agent's
    declared output_schema (which is typically `free_text`).
    """
    if isinstance(tool_response, dict):
        return tool_response
    if isinstance(tool_response, str) and tool_response.strip():
        try:
            parsed = json.loads(tool_response)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"_raw_text": tool_response}
    return {}


def _load_spec_for_agent(subagent_type: str) -> dict:
    """Read declared output_schema + tool_allowlist from agent .md frontmatter.

    Returns {} when the agent file is missing or has no frontmatter — D2
    treats that as 'no schema, layer 1 skipped' (per validate() contract).
    """
    if not subagent_type:
        return {}
    try:
        from lib.frontmatter import parse_frontmatter
        from lib.paths import AGENTS_DIR
    except Exception:
        return {}
    path = AGENTS_DIR / f"{subagent_type}.md"
    if not path.exists():
        return {}
    parsed = parse_frontmatter(path)
    if parsed is None:
        return {}
    meta, _body = parsed
    spec: dict = {}
    raw_schema = meta.get("output_schema", "").strip()
    if raw_schema and raw_schema != "free_text":
        # Try JSON parse; if it fails the schema is non-machine-readable
        # (probably the legacy <output_schema> XML block) — leave layer 1
        # disabled rather than fail-noisy on every Agent dispatch.
        try:
            schema_obj = json.loads(raw_schema)
            if isinstance(schema_obj, dict):
                spec["output_schema"] = schema_obj
        except json.JSONDecodeError:
            pass
    raw_tools = meta.get("tools", "")
    if raw_tools:
        # `tools` in agent frontmatter is comma-separated string per Claude Code convention.
        tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        if tools:
            spec["tool_allowlist"] = tools
    return spec


def _project_root_for_session() -> str:
    """Pick a project root for the operator-ledger entry.

    Order: PROJECT_ROOT env (caller-supplied) → cwd at hook fire time.
    The cwd-fallback matches the existing repeat_error_tracker convention.
    """
    return os.environ.get("PROJECT_ROOT") or os.getcwd()


def _raw_event_emit(event_type: str, payload: dict) -> None:
    """Low-level emit to event_store. Used by _event_emit which adds taxonomy validation."""
    try:
        from lib.event_store import append as event_append
        event_append({"event_type": event_type, **payload})
    except Exception:
        pass


def _event_emit(event_type: str, payload: dict) -> None:
    """v15.23 — taxonomy-validated emit (unknown event_types → telemetry warn).

    Wraps event_store.append with lib.event_taxonomy.emit_with_validation. Both
    raw emit + validation are fail-open (observability layer, not flow control).
    """
    try:
        from lib.event_taxonomy import emit_with_validation
        emit_with_validation(event_type, payload, _raw_event_emit)
    except Exception:
        # Fail-open even on validator import failure — never block flow.
        _raw_event_emit(event_type, payload)


def _resolve_verified_by(d2_result, semantic_result, cross_ref_result=None,
                         boilerplate_result=None) -> str:
    """Refine ledger.verified_by with D2 + D2.5 + D2.6 + D2.7 (v15.13+v15.21+v15.25).

    9-grade ladder (precedence: cross_ref strong > boilerplate strong >
                    semantic strong > cross_ref weak > semantic weak >
                    semantic clean > default):
      D2 fail                            → "self_only"
      D2 ok + cross_ref STRONG_PLAGIA    → "evidence_validator_plagiarized_strong"
      D2 ok + cross_ref CHERRY_PICKED    → "evidence_validator_cherry_picked"
      D2 ok + cross_ref SUSPI_PLAGIA     → "evidence_validator_plagiarized_suspicious"
      D2 ok + boilerplate BOILERPLATE    → "evidence_validator_boilerplate_evidence"
      D2 ok + semantic STRONG_SUSP       → "evidence_validator_lexical_strong_suspicion"
      D2 ok + semantic SUSPICIOUS        → "evidence_validator_lexical_suspicious"
      D2 ok + semantic CLEAN             → "evidence_validator_lexical_clean"
      D2 ok + 모두 SKIPPED/None           → "evidence_validator"

    String literals are stable — operator-ledger consumers (calibration proposer,
    grafana) read these. cross_ref tier > boilerplate > semantic because:
    - cross_ref strong = direct prompt copy-paste (most blatant fabrication signal)
    - boilerplate = evidence file carries no domain semantic (clear fabrication)
    - semantic strong = zero lexical overlap (may be false positive on paraphrase)

    LIKELY_BOILERPLATE은 own grade 없음 — 이벤트만 emit하고 다음 tier로 fall-through.
    """
    if d2_result is None or not getattr(d2_result, "ok", False):
        return "self_only"

    # v15.21 cross_ref strong tier first
    if cross_ref_result is not None:
        try:
            from lib.validators.cross_ref import CrossRefVerdict
            cv = cross_ref_result.verdict
            if cv == CrossRefVerdict.STRONG_PLAGIARIZED:
                return "evidence_validator_plagiarized_strong"
            if cv == CrossRefVerdict.SUSPICIOUS_CHERRY_PICKED:
                return "evidence_validator_cherry_picked"
            if cv == CrossRefVerdict.SUSPICIOUS_PLAGIARIZED:
                return "evidence_validator_plagiarized_suspicious"
        except Exception:
            pass

    # v15.25 boilerplate strong tier (D2.7)
    if boilerplate_result is not None:
        try:
            from lib.validators.boilerplate import BoilerplateVerdict
            bv = boilerplate_result.verdict
            if bv == BoilerplateVerdict.BOILERPLATE:
                return "evidence_validator_boilerplate_evidence"
        except Exception:
            pass

    # v15.13 semantic tier
    if semantic_result is not None:
        try:
            from lib.validators.semantic import SemanticVerdict
            v = semantic_result.verdict
            if v == SemanticVerdict.STRONG_SUSPICION:
                return "evidence_validator_lexical_strong_suspicion"
            if v == SemanticVerdict.SUSPICIOUS:
                return "evidence_validator_lexical_suspicious"
            if v == SemanticVerdict.CLEAN:
                return "evidence_validator_lexical_clean"
        except Exception:
            pass

    return "evidence_validator"


def _resolve_failure_mode(d1_verdict, d2_result) -> str | None:
    """Combine D1 + D2 results into a single failure_mode string for D3.

    Precedence:
      1. D2 SCHEMA_VIOLATION   → "schema_violation"
      2. D1 FABRICATION_CONFIRMED OR D2 EVIDENCE_FABRICATION → "evidence_fabrication"
      3. D2 TOOL_MISUSE        → "tool_misuse"
      4. None (clean — record success)
    """
    try:
        from lib.observers.evidence_fab import EvidenceVerdict
        from lib.validators.structural import StructuralFailureMode
    except Exception:
        return None

    if d2_result is not None and not getattr(d2_result, "ok", True):
        mode = d2_result.failure_mode
        if mode == StructuralFailureMode.SCHEMA_VIOLATION:
            return "schema_violation"
        if mode == StructuralFailureMode.EVIDENCE_FABRICATION:
            return "evidence_fabrication"
        if mode == StructuralFailureMode.TOOL_MISUSE:
            return "tool_misuse"

    if d1_verdict == EvidenceVerdict.FABRICATION_CONFIRMED:
        return "evidence_fabrication"

    return None


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw.strip():
        return
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    if payload.get("tool_name") != "Agent":
        return

    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response")
    subagent_type = tool_input.get("subagent_type", "") if isinstance(tool_input, dict) else ""
    if not subagent_type:
        return
    prompt_text = tool_input.get("prompt", "") if isinstance(tool_input, dict) else ""

    envelope = _load_envelope(tool_response)
    spec = _load_spec_for_agent(subagent_type)

    # D2 structural validation
    d2_result = _safe_call(
        "d2_validate",
        lambda: __import__("lib.validators.structural", fromlist=["validate"]).validate(envelope, spec),
    )

    # D1 evidence fabrication detection
    d1_verdict = _safe_call(
        "d1_detect",
        lambda: __import__("lib.observers.evidence_fab", fromlist=["detect"]).detect(envelope),
    )

    # D2.5 — semantic lexical layer (v15.13, Architect self_doubt partial mitigation)
    # advisory only: never blocks, never trips breaker. Refines `verified_by`
    # ledger field; emits `ledger.semantic_suspicion` event on STRONG_SUSPICION.
    semantic_result = _safe_call(
        "d2_5_semantic",
        lambda: __import__("lib.validators.semantic", fromlist=["check"]).check(envelope),
    )
    if semantic_result is not None:
        try:
            from lib.validators.semantic import SemanticVerdict
            if semantic_result.verdict == SemanticVerdict.STRONG_SUSPICION:
                _event_emit("ledger.semantic_suspicion", {
                    "agent_type": subagent_type,
                    "verdict": "strong_suspicion",
                    "evidence_count": len(semantic_result.evidence_breakdown),
                })
        except Exception:
            pass

    # D2.6 — cross-reference layer (v15.21, plagiarized-summary + cherry-picked)
    # advisory only. summary_vs_prompt가 STRONG_PLAGIARIZED면 event_emit;
    # cherry_picked는 worse-of-two로 ledger 분류.
    def _run_cross_ref():
        from lib.validators.cross_ref import (
            check_summary_vs_prompt, check_cross_file_consensus, CrossRefVerdict,
        )
        plag = check_summary_vs_prompt(envelope, prompt_text)
        consensus = check_cross_file_consensus(envelope)
        # worst-of-two for ledger purpose
        order = {
            CrossRefVerdict.SKIPPED: 0,
            CrossRefVerdict.CLEAN: 1,
            CrossRefVerdict.SUSPICIOUS_CHERRY_PICKED: 2,
            CrossRefVerdict.SUSPICIOUS_PLAGIARIZED: 3,
            CrossRefVerdict.STRONG_PLAGIARIZED: 4,
        }
        worst = plag if order[plag.verdict] >= order[consensus.verdict] else consensus
        return worst
    cross_ref_result = _safe_call("d2_6_cross_ref", _run_cross_ref)
    if cross_ref_result is not None:
        try:
            from lib.validators.cross_ref import CrossRefVerdict
            if cross_ref_result.verdict in (
                CrossRefVerdict.STRONG_PLAGIARIZED,
                CrossRefVerdict.SUSPICIOUS_PLAGIARIZED,
                CrossRefVerdict.SUSPICIOUS_CHERRY_PICKED,
            ):
                _event_emit("ledger.cross_ref_suspicion", {
                    "agent_type": subagent_type,
                    "verdict": cross_ref_result.verdict.value,
                    "overlap_ratio": cross_ref_result.overlap_ratio,
                })
        except Exception:
            pass

    # D2.7 — boilerplate file classifier (v15.25 M)
    # advisory only: evidence file이 LICENSE/.gitkeep/__init__.py 등 boilerplate
    # 일 때 verdict emit. semantic + cross_ref가 못 잡는 의미-무관 fabrication
    # 시나리오 (file_path는 존재 + summary는 plausible + 파일 자체가 도메인 무관)
    # 직접 해소.
    boilerplate_result = _safe_call(
        "d2_7_boilerplate",
        lambda: __import__("lib.validators.boilerplate", fromlist=["check"]).check(envelope),
    )
    if boilerplate_result is not None:
        try:
            from lib.validators.boilerplate import BoilerplateVerdict
            if boilerplate_result.verdict in (
                BoilerplateVerdict.BOILERPLATE,
                BoilerplateVerdict.LIKELY_BOILERPLATE,
            ):
                _event_emit("ledger.boilerplate_suspicion", {
                    "agent_type": subagent_type,
                    "verdict": boilerplate_result.verdict.value,
                    "evidence_count": len(boilerplate_result.per_file),
                })
        except Exception:
            pass

    # v15.20 budget tracker (advisory record) + v15.24 cap check + emit-on-exceeded
    def _record_budget():
        from lib.budget import (
            record_invocation, check_and_emit_exceeded,
            DEFAULT_SESSION_CHAR_BUDGET,
        )
        sid = payload.get("session_id") or "default"
        text = tool_response if isinstance(tool_response, str) else json.dumps(envelope, ensure_ascii=False)
        record_invocation(sid, text)
        cap_env = os.environ.get("BUDGET_CHAR_CAP")
        try:
            cap = int(cap_env) if cap_env else DEFAULT_SESSION_CHAR_BUDGET
        except (TypeError, ValueError):
            cap = DEFAULT_SESSION_CHAR_BUDGET
        check_and_emit_exceeded(sid, emit_fn=_event_emit, cap=cap)
    _safe_call("budget_record", _record_budget)

    # v15.23 heartbeat (per-session liveness signal)
    def _record_heartbeat():
        from lib.heartbeat import emit as heartbeat_emit
        sid = payload.get("session_id") or "default"
        heartbeat_emit(sid, subagent_type)
        _event_emit("heartbeat.emitted", {
            "session_id": sid,
            "agent_type": subagent_type,
        })
    _safe_call("heartbeat_record", _record_heartbeat)

    # D3 composite breaker
    failure_mode = _resolve_failure_mode(d1_verdict, d2_result)
    project_root = _project_root_for_session()
    breaker_state_before = None
    breaker_state_after = None
    if failure_mode is not None:
        def _breaker_failure():
            from lib.breakers.composite import CompositeBreaker
            from lib.operator_ledger import project_id_for
            pid = project_id_for(project_root)
            br = CompositeBreaker(
                agent_type=subagent_type,
                failure_mode=failure_mode,
                project_id=pid,
                emit_fn=_event_emit,
            )
            before = br.snapshot().state.value
            after = br.record_failure().value
            return before, after
        result = _safe_call("d3_breaker_failure", _breaker_failure)
        if result is not None:
            breaker_state_before, breaker_state_after = result
    else:
        # No-op success path — only update the breaker if there's an existing
        # composite key on disk for this (agent, mode). Otherwise creating one
        # eagerly would inflate disk usage. Skip silently.
        pass

    # D4 — critic decision read from env (set by pre_tool advisor)
    critic_decision = os.environ.get("ORCH_CRITIC_DECISION")  # "invoke" | "skip" | None
    critic_invoked = (critic_decision == "invoke")

    # D5 — operator ledger append
    def _ledger_append():
        from lib.operator_ledger import append_record, task_hash_for
        tools = spec.get("tool_allowlist") or []
        thash = task_hash_for(project_root, prompt_text, tools)
        evidence_paths = []
        if isinstance(envelope.get("evidence"), list):
            for e in envelope["evidence"]:
                if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                    evidence_paths.append(e["file_path"])
        record = {
            "parent_sid": payload.get("session_id"),
            "agent_type": subagent_type,
            "task_hash": thash,
            "failure_modes": [failure_mode] if failure_mode else [],
            "success": failure_mode is None,
            "evidence_paths": evidence_paths,
            "breaker_state_before": breaker_state_before,
            "breaker_state_after": breaker_state_after,
            "critic_invoked": critic_invoked,
            "critic_verdict": None,
            "replay_hash": None,
            "verified_by": _resolve_verified_by(
                d2_result, semantic_result, cross_ref_result, boilerplate_result,
            ),
            "downstream_used": True,
            "human_override": None,
            "retry_count": 0,
        }
        append_record(project_root, subagent_type, record, emit_fn=_event_emit)
    _safe_call("d5_ledger_append", _ledger_append)


if __name__ == "__main__":
    main()
