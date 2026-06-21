"""wonder — 2-Strike strategic reflection step before mechanical fix (v15.26 W).

debate-1778987814-41b475 D-WONDER-2STRIKE: evaluator verdict='iterate' with
same fingerprint 2회 연속 → Wonder triggers strategic re-think (1×) BEFORE
ralph mechanical fix runs.

Pattern (CLAUDE.md L0 2-Strike Rule):
1. Generator produces artifact.
2. Evaluator: verdict='iterate' (1st strike, advisory fail).
3. Ralph mechanical fix.
4. Evaluator: verdict='iterate' (2nd strike, same fingerprint) → Wonder.
5. Wonder writes reflection note ("strategic re-think").
6. Ralph then runs with reflection note as input.

Cumulative depth cap: 5 per orch_sid (seed.md). On overflow, emit
`wonder.depth_exhausted` + force verdict='escalate' upstream.

Fingerprint construction: SHA-1[:16] of canonical JSON of {verdict, axis_or_gate,
normalized_failure_signature}. Same as repeat_error_tracker.py hash family
(D1 — lib-layer detector uniformity).

State layout:
- state/wonder/<orch_sid>.json — {strikes_by_fingerprint: {fp: count}, total_depth: int, reflections: [path]}

Public API:
- record_strike(orch_sid, fingerprint) -> StrikeRecord — count++, return (count, triggered)
- should_trigger_wonder(strike_count) -> bool — true at count >= 2
- depth(orch_sid) -> int — cumulative reflection count
- write_reflection(orch_sid, fingerprint, summary, *, emit_fn) -> ReflectionResult
- depth_exhausted(orch_sid) -> bool — count >= 5

Invariant: NO LLM, NO embedder. Pure stdlib hashlib + json.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict


_HASH_PREFIX_LEN = 16
WONDER_STRIKE_THRESHOLD = 2  # 2-Strike Rule
WONDER_DEPTH_CAP = 5  # cumulative per orch_sid (seed.md G2.1)


class StructuredPayload(TypedDict):
    """S1 wonder→skill auto-propose structured emission shape.

    debate-1779255461-3fd149 D7+D8 (converged gen 4, sha1
    90d354d71a7316880e6377ee39edb201951d0ffb). Caller-provided dict that
    upgrades the reflection's free-form `summary` body with three
    machine-readable fields downstream `lib.skill_candidate_detector
    ._build_candidate_from_reflection` (S1 PR-B) consumes to synthesize
    a skill-candidate manifest with category='wonder-gotcha'.

    TypedDict is static-only per PEP 589; `write_reflection` adds a
    runtime isinstance + required-key check per gen-3 C1 adjudication
    (architect verdict: "MUST add explicit runtime isinstance/required-
    key check"). The static hint here is documentation + mypy lift; the
    runtime guard is the load-bearing contract.

    Fields:
      axis: short identifier of which evaluator axis triggered the
        reflection (e.g., "completeness", "stability"). Single-line.
      target_skill_hint: optional file path the gotcha SHOULD likely
        codify into (e.g., "skills/_common/foo.md"). None when unknown.
      gotcha_body: markdown body the candidate manifest will carry as
        the proposed skill gotcha entry. Single-line for v1 (no embedded
        newlines — defer multi-line support to a follow-up if needed).
    """
    axis: str
    target_skill_hint: str | None
    gotcha_body: str
_SID_SAFE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or Path.home() / ".claude")


def _wonder_dir() -> Path:
    p = _claude_home() / "state" / "wonder"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_sid(sid: str) -> None:
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"orch_sid must be non-empty string, got {sid!r}")
    if not _SID_SAFE_RE.match(sid):
        raise ValueError(f"orch_sid failed safety regex: {sid!r}")


def compute_fingerprint(verdict: str, axis: str, failure_signature: str) -> str:
    """SHA-1[:16] of canonical JSON {verdict, axis, signature}."""
    payload = {"verdict": verdict, "axis": axis, "signature": failure_signature}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]


@dataclass
class StrikeRecord:
    fingerprint: str
    count: int
    triggered: bool  # True iff count >= WONDER_STRIKE_THRESHOLD on THIS call


@dataclass
class ReflectionResult:
    orch_sid: str
    fingerprint: str
    reflection_path: str
    depth_after: int
    exhausted: bool


def _load_state(orch_sid: str) -> dict:
    target = _wonder_dir() / f"{orch_sid}.json"
    if not target.exists():
        return {"strikes_by_fingerprint": {}, "total_depth": 0, "reflections": []}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"strikes_by_fingerprint": {}, "total_depth": 0, "reflections": []}


def _save_state(orch_sid: str, state: dict) -> None:
    target = _wonder_dir() / f"{orch_sid}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def record_strike(orch_sid: str, fingerprint: str) -> StrikeRecord:
    """Increment strike counter for (orch_sid, fingerprint). Return record with triggered flag."""
    _validate_sid(orch_sid)
    if not isinstance(fingerprint, str) or len(fingerprint) != _HASH_PREFIX_LEN:
        raise ValueError(f"fingerprint must be {_HASH_PREFIX_LEN}-char hex, got {fingerprint!r}")
    state = _load_state(orch_sid)
    strikes = state.setdefault("strikes_by_fingerprint", {})
    new_count = int(strikes.get(fingerprint, 0)) + 1
    strikes[fingerprint] = new_count
    _save_state(orch_sid, state)
    return StrikeRecord(
        fingerprint=fingerprint,
        count=new_count,
        triggered=new_count >= WONDER_STRIKE_THRESHOLD,
    )


def should_trigger_wonder(strike_count: int) -> bool:
    return strike_count >= WONDER_STRIKE_THRESHOLD


def depth(orch_sid: str) -> int:
    """Cumulative reflection count for orch_sid."""
    _validate_sid(orch_sid)
    return int(_load_state(orch_sid).get("total_depth", 0))


def depth_exhausted(orch_sid: str) -> bool:
    return depth(orch_sid) >= WONDER_DEPTH_CAP


def _validate_structured_payload(payload: Any) -> None:
    """Runtime guard for StructuredPayload — gen-3 C1 contract.

    PEP 589 TypedDict is static-only; this function provides the runtime
    isinstance + required-key + single-line constraints the architect's
    gen-3 verdict mandated ("MUST add explicit runtime isinstance/key-
    presence check"). Raises ValueError on any shape violation so the
    failure surfaces at write time, not silently in downstream
    lib.skill_candidate_detector._build_candidate_from_reflection.

    Required keys: {'axis', 'target_skill_hint', 'gotcha_body'}. Values
    must be str (axis, gotcha_body) or (str | None) (target_skill_hint).
    No embedded newlines in any string field (v1 single-line constraint
    so the simple line-based reader in PR-B does not need a YAML lib).
    """
    if not isinstance(payload, dict):
        raise ValueError(
            f"structured_payload must be a dict, got {type(payload).__name__}"
        )
    required = {"axis", "target_skill_hint", "gotcha_body"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(
            f"structured_payload missing required keys: {sorted(missing)}"
        )
    extra = payload.keys() - required
    if extra:
        raise ValueError(
            f"structured_payload has unexpected keys: {sorted(extra)}"
        )
    if not isinstance(payload["axis"], str) or not payload["axis"]:
        raise ValueError("structured_payload['axis'] must be non-empty str")
    if not isinstance(payload["gotcha_body"], str) or not payload["gotcha_body"]:
        raise ValueError("structured_payload['gotcha_body'] must be non-empty str")
    tsh = payload["target_skill_hint"]
    if tsh is not None and not isinstance(tsh, str):
        raise ValueError(
            "structured_payload['target_skill_hint'] must be str or None"
        )
    for field in ("axis", "gotcha_body"):
        if "\n" in payload[field] or "\r" in payload[field]:
            raise ValueError(
                f"structured_payload['{field}'] must be single-line "
                f"(v1 constraint — no embedded newlines)"
            )
    if isinstance(tsh, str) and ("\n" in tsh or "\r" in tsh):
        raise ValueError(
            "structured_payload['target_skill_hint'] must be single-line"
        )


def write_reflection(
    orch_sid: str,
    fingerprint: str,
    summary: str,
    *,
    emit_fn: Callable[[str, dict], None] | None = None,
    structured_payload: StructuredPayload | None = None,
) -> ReflectionResult:
    """Write reflection note + increment total_depth. Emit wonder.triggered.

    If depth >= WONDER_DEPTH_CAP AFTER this increment, emit wonder.depth_exhausted.
    Caller(autopilot) should treat exhausted=True as forced 'escalate' upstream.

    S1 extension (wave 12, debate-1779255461-3fd149 LOCK SHA
    90d354d71a73): optional `structured_payload` upgrades the
    reflection frontmatter with a machine-readable
    `structured_payload:` nested mapping that
    `lib.skill_candidate_detector._build_candidate_from_reflection` (PR-B)
    consumes to synthesize a skill-candidate. structured_payload=None
    (default) preserves byte-identical legacy body — the original
    f-string template is reused verbatim in that path (PR-C gen-3 C2
    byte-identity contract).
    """
    _validate_sid(orch_sid)
    if not isinstance(fingerprint, str) or len(fingerprint) != _HASH_PREFIX_LEN:
        raise ValueError("fingerprint must be 16-char hex")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("reflection summary must be non-empty string")
    if structured_payload is not None:
        _validate_structured_payload(structured_payload)

    state = _load_state(orch_sid)
    new_depth = int(state.get("total_depth", 0)) + 1
    reflections_dir = _wonder_dir() / orch_sid
    reflections_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    reflection_path = reflections_dir / f"reflection_{new_depth:03d}_{fingerprint}.md"
    if structured_payload is None:
        # gen-3 C2 byte-identity contract: legacy path uses ORIGINAL
        # f-string template byte-for-byte. Do not refactor this branch.
        body = (
            f"---\n"
            f"orch_sid: {orch_sid}\n"
            f"fingerprint: {fingerprint}\n"
            f"depth: {new_depth}\n"
            f"ts: {ts}\n"
            f"---\n\n"
            f"{summary.rstrip()}\n"
        )
    else:
        tsh = structured_payload["target_skill_hint"]
        tsh_yaml = "null" if tsh is None else tsh
        body = (
            f"---\n"
            f"orch_sid: {orch_sid}\n"
            f"fingerprint: {fingerprint}\n"
            f"depth: {new_depth}\n"
            f"ts: {ts}\n"
            f"structured_payload:\n"
            f"  axis: {structured_payload['axis']}\n"
            f"  target_skill_hint: {tsh_yaml}\n"
            f"  gotcha_body: {structured_payload['gotcha_body']}\n"
            f"---\n\n"
            f"{summary.rstrip()}\n"
        )
    reflection_path.write_text(body, encoding="utf-8")
    state["total_depth"] = new_depth
    reflections_list = state.setdefault("reflections", [])
    reflections_list.append(str(reflection_path))
    _save_state(orch_sid, state)
    exhausted = new_depth >= WONDER_DEPTH_CAP
    if emit_fn is not None:
        try:
            emit_fn("wonder.triggered", {
                "orch_sid": orch_sid,
                "fingerprint": fingerprint,
                "depth": new_depth,
            })
            if exhausted:
                emit_fn("wonder.depth_exhausted", {
                    "orch_sid": orch_sid,
                    "depth": new_depth,
                    "cap": WONDER_DEPTH_CAP,
                })
        except Exception:
            pass
    return ReflectionResult(
        orch_sid=orch_sid,
        fingerprint=fingerprint,
        reflection_path=str(reflection_path),
        depth_after=new_depth,
        exhausted=exhausted,
    )
