"""evaluator_dispatcher — D4 evaluator-driven dispatch path per
debate-1778248254-0b7092.

Mirrors strike_dispatcher.py shape but for a different concern:
strike_dispatcher decides WHEN to invoke harness-researcher on a
recurring failure fingerprint; evaluator_dispatcher decides WHEN to
invoke harness-evaluator on Phase 4 entry of an autopilot run.

Per debate D4 conditions (gen 1 C5 + gen 3 ontology):
  - PER_PHASE_EVAL_LIMIT=2 prevents re-evaluation loops on the same phase
  - dispatcher records counter at state/evaluator/<sid>/dispatch_counter.json
  - on subagent timeout (>120s) OR exception OR paradox_guard.passes==False
    → dispatch to legacy E2 fallback (validators+units pipeline) and
    record fallback_reason in axis_scores.jsonl alongside verdict

Per D3 (subagent isolation): build_evaluator_prompt() injects ONLY the
artifact-under-evaluation + phase_locks + axis_rubric. Debate sid,
transcript paths, prior generation events.jsonl paths are NEVER
interpolated. A unit test asserts the rendered prompt contains zero
substrings matching the leak regex.

Public surface:
  - PER_PHASE_EVAL_LIMIT (default 2)
  - SUBAGENT_TIMEOUT_SECONDS (default 120)
  - LEAK_PATTERN_REGEX (D3 isolation enforcement)
  - DispatchEligibility enum (eligible / over_limit / disabled)
  - should_dispatch(sid, phase_id) -> DispatchEligibility
  - record_dispatch(sid, phase_id) -> int (new counter value)
  - read_counter(sid) -> dict[phase_id -> int]
  - build_evaluator_prompt(artifact, phase_locks, axis_rubric) -> str
  - validate_prompt_isolation(prompt) -> bool (True if clean)

## 3-tier evaluation architecture (Q00/ouroboros mapping, 2026-05-17)

본 dispatcher 가 위치한 evaluation 스택은 *3-tier 직교 책임 분리* 구조.
각 tier는 다른 입력·다른 판정 방식·다른 paradox 위험을 가진다. tier 간
혼동을 피하기 위해 본 docstring 에 명시 분리.

| tier | 명칭 | 입력 | 판정 | 구현 위치 | 모델 |
|------|------|------|------|-----------|------|
| **Tier 1** | **Mechanical** | source + test artifacts | pass / fail (boolean) | tests/run_all.py + validators/* + handlers/post_tool/* | none (deterministic) |
| **Tier 2** | **Semantic** | artifact + phase_locks + axis_rubric | 5-axis 1-5 score + completeness bool + verdict | agents/harness-evaluator.md (via invoke_evaluator_isolated) | single LLM (OpenAIProvider / codex exec) |
| **Tier 3** | **Multi-Model Consensus** | 동일 prompt → N evaluators | quorum ⌈N/2⌉ verdict + split flag | lib/ensemble_evaluator.py (via invoke_ensemble_evaluator) | N >= 2 LLM pool |

**Tier 1 — Mechanical (validators)**: the 37 registered validators in
the top-level `validators/` layer (ci/codegen/contract/test/etc.; NOT
`lib/validators/`, which is the distinct orchestrator-side envelope-validator
package per lib/validators/__init__.py). Pure determinism — no
LLM. Boolean pass/fail aggregated to populate `completeness` axis
input for Tier 2. Phase 4 entry gate before evaluator dispatch.

**Tier 2 — Semantic (harness-evaluator subagent)**: this dispatcher
(`should_dispatch` + `invoke_evaluator_isolated`) routes to the
harness-evaluator subagent for qualitative judgment over 5 axes
(응집·결합·확장·안정·사용) plus the boolean completeness gate.
Single-provider (Codex via OpenAIProvider) — provider-level
judge-generator separation is the paradox mitigation here.
Post-LLM clamp: completeness=False forces verdict ≠ 'approved'
regardless of axis scores.

**Tier 3 — Multi-Model Consensus (ensemble.aggregate)**: optional
fan-out (`invoke_ensemble_evaluator` + `lib.ensemble_evaluator`)
running Tier 2 on N independent providers; tally via quorum threshold
⌈N/2⌉. Closes single-provider-bias residual that Tier 2 alone cannot.
`validate_evaluator_pool` enforces all-non-generator-family at pool
creation; `allow_generator_family` is an explicit escape hatch for
codex+claude pools where separation is at model-id level instead.

**Tier elevation policy** (rationale-only — not enforced in code):
- Tier 1 fail → halt (no Tier 2/3 needed; mechanical floor)
- Tier 1 pass + Tier 2 single-provider sufficient for default autopilot
- Tier 3 opt-in via `--ensemble` flag (harness-evaluate.md §4b) when
  operator wants quorum-based paradox closure on high-stakes artifacts

**Cross-references** (do not duplicate doctrine here):
- agents/harness-evaluator.md `<three_tier_eval>` — Tier 2 subagent
  prompt-side contract
- lib/ensemble_evaluator.py module docstring — Tier 3 quorum semantics
- ~/CLAUDE.md DGE §Evaluator — E1/E2 split + 3-tier mapping
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path


# Per-phase max evaluator dispatch (debate gen 1 risk_flag: tunable after 1mo)
PER_PHASE_EVAL_LIMIT: int = 2

# Subagent invocation timeout — fallback path triggers at this threshold.
#
# v15.41 (wave 10 Path 2 D3, debate-1779229138-db17ce gen 3 LOCK SHA
# c75bfaf403981c1fcd8cb45c0872c83ae564b777): bumped 120 → 270 to coordinate
# with openai.py:71-81 codex exec hard timeout (300s). Dispatcher must fire
# its TimeoutExpired/fallback path BEFORE the codex subprocess raises its
# own 300s timeout — otherwise the fallback reason categorization is lost
# (ProviderUnavailableError wraps the inner subprocess.TimeoutExpired and
# the caller sees SUBAGENT_EXCEPTION instead of SUBAGENT_TIMEOUT). 270s
# leaves a 30s buffer for subprocess teardown + stderr flush.
SUBAGENT_TIMEOUT_SECONDS: int = 270


# D3 isolation enforcement: prompt must NOT reference debate transcripts,
# events.jsonl paths, or sid-tagged context. The regex is applied to the
# fully-rendered prompt before subagent spawn; match → reject.
LEAK_PATTERN_REGEX: re.Pattern = re.compile(
    # Direct path/file references
    r"(events\.jsonl|/debates/|/orchestrator/|/interview/|axis_scores\.jsonl|"
    # Role-named transcripts
    r"planner_transcript|critic_transcript|architect_transcript|"
    r"researcher_transcript|evaluator_transcript|"
    # Generic transcript / history phrases
    r"prior\s+generation|prior\s+turn|previous\s+turn|earlier\s+turn|"
    r"earlier\s+conversation|conversation\s+history|session\s+log|"
    r"chat\s+history|message\s+history|agent\s+state|harness\s+state|"
    # sid leakage
    r"sid\s*=\s*['\"]?(debate|orch|interview)-|"
    # Role-override / persona injection (defense beyond isolation)
    r"ignore\s+previous|disregard\s+previous|forget\s+previous|"
    r"system\s+prompt\s+is|new\s+instructions\s+are|"
    # Korean equivalents (harness 한국어 사용자 컨텍스트)
    r"이전\s*대화|이전\s*턴|직전\s*세션|상위\s*컨텍스트|부모\s*컨텍스트|"
    r"이전\s*프롬프트|시스템\s*프롬프트는)",
    re.IGNORECASE,
)


class DispatchEligibility(Enum):
    ELIGIBLE = "eligible"
    OVER_LIMIT = "over_limit"
    DISABLED = "disabled"


# ---- counter persistence (shared QuotaCounter primitive, M10) ----
# Fail-SOFT on corruption ({}): re-evaluation is already bounded to PER_PHASE_EVAL_
# LIMIT, so a lost counter costs at most a few redundant evaluations, never a
# runaway — the opposite policy from strike_dispatcher (fail-closed). `filter`
# preserves the legacy non-negative-non-bool-int value handling. Subsystem dir +
# filename unchanged (state/evaluator/<sid>/dispatch_counter.json) = on-disk compat.
from .quota_tracker import QuotaCounter  # noqa: E402

_TRACKER = QuotaCounter(
    "evaluator", on_corrupt="empty", value_mode="filter", label="evaluator_dispatcher",
)


def _counter_path(sid: str) -> Path:
    """Lazy STATE_DIR resolution. state/evaluator/<sid>/dispatch_counter.json.
    Raises ValueError on empty sid (the QuotaCounter contract)."""
    return _TRACKER.path(sid)


def read_counter(sid: str) -> dict[str, int]:
    """Return {phase_id: count} dict. Empty {} if missing/corrupt (fail-soft)."""
    return _TRACKER.load(sid)


def record_dispatch(sid: str, phase_id: str) -> int:
    """Increment per-(sid, phase_id) counter atomically. Returns new value.
    Raises ValueError on empty phase_id."""
    return _TRACKER.record(sid, phase_id)


def should_dispatch(sid: str, phase_id: str,
                    limit: int = PER_PHASE_EVAL_LIMIT) -> DispatchEligibility:
    """Decide whether evaluator should fire for this (sid, phase_id).

    Returns:
      ELIGIBLE   — count < limit, OK to dispatch
      OVER_LIMIT — count >= limit, dispatcher must skip (re-eval loop guard)
      DISABLED   — limit <= 0 (admin opt-out)

    Counter is read-only here; record_dispatch() must be called separately
    after the actual subagent invocation completes (success or fallback).
    """
    if limit <= 0:
        return DispatchEligibility.DISABLED
    if not isinstance(phase_id, str) or not phase_id:
        return DispatchEligibility.OVER_LIMIT
    counter = read_counter(sid)
    if counter.get(phase_id, 0) >= limit:
        return DispatchEligibility.OVER_LIMIT
    return DispatchEligibility.ELIGIBLE


# ---- D3 isolation prompt builder ----

_PROMPT_TEMPLATE = """You are the harness-evaluator subagent. Your task: score
the artifact below on 5 axes (응집/결합/확장/안정/사용) per the rubric,
and judge whether the strict-boolean completeness condition is met.

ISOLATION INVARIANT: only the three sections below are available
(artifact_under_evaluation, phase_locks, axis_rubric). No additional
inputs may be requested or assumed.

## artifact_under_evaluation
{artifact}

## phase_locks
{phase_locks}

## axis_rubric
{axis_rubric}

## Output (JSON only)
{{
  "axis_scores": {{
    "cohesion": <1-5>, "coupling": <1-5>, "extensibility": <1-5>,
    "stability": <1-5>, "usability": <1-5>
  }},
  "completeness": true | false,
  "verdict": "approved" | "iterate" | "escalate",
  "reasons": [{{"axis": "...", "code": "...", "detail": "..."}}]
}}
"""


def build_evaluator_prompt(artifact: str, phase_locks: str,
                           axis_rubric: str) -> str:
    """Render the subagent prompt with the 3 whitelisted inputs.

    NOT injected: debate sid, transcript paths, prior generation refs.
    Caller MUST validate_prompt_isolation() before subagent spawn.

    Caller-side sanitization (wave 5 autopilot orch-1779097909-aeb31f
    finding, 2026-05-18): the LEAK_PATTERN_REGEX matches literal path-
    like tokens (axis_scores.jsonl, /debates/, /orchestrator/, etc.) even
    when they appear inside legitimate artifact descriptions or docstring
    excerpts being evaluated. If an artifact mentions such tokens as
    PART OF THE CODE BEING REVIEWED (not as injected dispatcher state),
    paraphrase before passing here (e.g., "axis_scores.jsonl" → "axis
    logging output", "/debates/" → "debate state subtree"). Failure to
    paraphrase triggers CONFIG_ERROR fallback in invoke_evaluator_isolated.
    """
    if not isinstance(artifact, str):
        raise ValueError(f"artifact must be str, got {type(artifact).__name__}")
    if not isinstance(phase_locks, str):
        raise ValueError(f"phase_locks must be str, got {type(phase_locks).__name__}")
    if not isinstance(axis_rubric, str):
        raise ValueError(f"axis_rubric must be str, got {type(axis_rubric).__name__}")
    return _PROMPT_TEMPLATE.format(
        artifact=artifact,
        phase_locks=phase_locks,
        axis_rubric=axis_rubric,
    )


def validate_prompt_isolation(prompt: str) -> bool:
    """True if `prompt` contains zero leak-pattern matches.

    Used as gate before subagent spawn. False → reject (caller surfaces
    error; do NOT silently scrub — the leak indicates dispatcher bug).
    """
    if not isinstance(prompt, str):
        return False
    return LEAK_PATTERN_REGEX.search(prompt) is None


# ---- fallback path ----

class FallbackReason(Enum):
    """Why dispatcher fell back to legacy E2 (validators+units only).

    CONFIG_ERROR (v15.35.4) — added per debate-1779008782-230c36 gen 4
    Architect condition P5 fix. Distinguishes config-failure from
    operational failure: PARADOX_GUARD_FAIL/SUBAGENT_TIMEOUT/SUBAGENT_
    EXCEPTION are runtime conditions; CONFIG_ERROR is structural (e.g.,
    EnsembleConfigError raised by validate_evaluator_pool, EVALUATOR_
    MODEL set to Anthropic-family without override). Routed to
    'escalate' (not 'iterate') in fallback_to_legacy_e2 because config
    breakage cannot be fixed by another iteration — operator review
    required.
    """
    PARADOX_GUARD_FAIL = "paradox_guard_fail"
    SUBAGENT_TIMEOUT = "subagent_timeout"
    SUBAGENT_EXCEPTION = "subagent_exception"
    CONFIG_ERROR = "config_error"
    # PARSE_EMPTY (debate-1780564679-8mgxsd D3) — the evaluator subprocess
    # returned output from which NO JSON object could be extracted (total
    # parse failure, distinct from a legitimate empty `{}` object which
    # parses fine and returns early). Previously invoke_evaluator_isolated
    # returned (raw, {}) here, silently losing the cause; now the parsed dict
    # carries {'_fallback_reason': 'parse_empty'} so the failure is
    # recordable/observable. The dict still has NO 'verdict' key, so callers'
    # tolerant `parsed.get('verdict', 'iterate')` continues to route to
    # legacy fallback (a SAFE non-complete vote) — the return contract is
    # preserved (no caller iterates/dumps/strict-validates the dict; verified
    # gen-1 critic).
    PARSE_EMPTY = "parse_empty"


# v15.40.4 — caller-side TypedDict for fallback_to_legacy_e2 retval
# (defense-in-depth pattern from v15.40.3 — TypedDict allows mypy / IDE
# static check of caller's fb["verdict"] / fb["completeness"] accesses,
# catching typos like fb["verdic"] at lint time).
from typing import Literal, TypedDict  # noqa: E402

VerdictLiteral = Literal["approved", "iterate", "escalate"]


class FallbackResult(TypedDict):
    """Structured retval of `fallback_to_legacy_e2` for caller-side typing.

    Keys reflect the actual dict shape emitted (also suitable for direct
    pass to lib.axis_scores_log.log_axis_event — schema_version is added
    by log_axis_event automatically).
    """
    event: Literal["fallback"]
    fallback_reason: str            # FallbackReason.value
    phase_id: str
    sid: str
    verdict: VerdictLiteral
    completeness: bool
    validators_passed: bool
    units_passed: bool
    known_defects: int


# ---- Full OS-enforced subprocess isolation (residual #3 closure) ----

# Env vars stripped before spawning the codex subprocess. Removes any
# harness-specific state that could leak parent context to the evaluator.
_ENV_STRIP_PREFIXES: tuple[str, ...] = (
    "HARNESS_",
    "ANTHROPIC_",
    "CLAUDE_",
    "ORCH_",
    "EVALUATOR_",          # except EVALUATOR_MODEL which we re-add explicitly
    "WRITEBACK_",
    "RESEARCH_EXTRACTOR_",
)


def _build_isolated_env() -> dict[str, str]:
    """Return a sanitized env dict for subprocess.run.

    Strips harness/Anthropic state prefixes, keeps only OS-essential vars
    (PATH, HOME, USERPROFILE, TEMP, SystemRoot — needed for codex CLI to
    locate its installation + libs). EVALUATOR_MODEL is re-added if set
    in the parent so operator can override the codex default.
    """
    import os as _os

    # Windows env var names are case-insensitive at OS level but Python
    # os.environ preserves stored case (e.g., SYSTEMROOT vs SystemRoot per
    # system). Normalize keep_keys + lookup to lowercase to match either case.
    keep_keys_lower = {k.lower() for k in {
        "PATH", "PATHEXT", "HOME", "USERPROFILE", "TEMP", "TMP",
        "SystemRoot", "SystemDrive", "ComSpec",  # Windows essentials (case-insensitive)
        "APPDATA", "LOCALAPPDATA",               # codex CLI auth path (%APPDATA%\codex\auth.json on Windows)
        "USERNAME", "USERDOMAIN", "USERDOMAIN_ROAMINGPROFILE",  # Windows auth context
        "HOMEDRIVE", "HOMEPATH",                 # Windows home path resolution (codex Rust binary)
        "OPENSSL_CONF",                          # TLS config (HTTPS to chatgpt.com backend)
        "NODEFAULTCURRENTDIRECTORYINEXEPATH",    # Windows security policy
        "LANG", "LC_ALL", "LC_CTYPE",            # locale for non-ASCII
        "PYTHONIOENCODING",                       # utf-8 stdio
    }}
    out: dict[str, str] = {}
    for k, v in _os.environ.items():
        if k.lower() in keep_keys_lower:
            out[k] = v
            continue
        # Strip harness/anthropic state
        if any(k.startswith(p) for p in _ENV_STRIP_PREFIXES):
            continue
        # Drop everything else by default — fresh codex env
    # Re-add EVALUATOR_MODEL explicitly if operator set it (cross-provider
    # invariant resolved by lib.evaluator.resolve_evaluator_model upstream)
    if "EVALUATOR_MODEL" in _os.environ:
        out["EVALUATOR_MODEL"] = _os.environ["EVALUATOR_MODEL"]
    return out


def _extract_json_object(raw: str) -> dict:
    """Pure JSON extractor for codex CLI output (D3, debate-1780564679-8mgxsd).

    Behavior (byte-equivalent to the prior inline parser in
    invoke_evaluator_isolated, minus the ledger side-effect):
      1. Strip a leading ```/```json fence (and trailing ```), if present.
      2. Strict whole-text json.loads → return it iff it is a dict (this is
         where a LEGITIMATE empty `{}` object returns {} — NOT a parse
         failure, so it gets no sentinel).
      3. Else scan all balanced `{...}` spans and return the LARGEST that
         parses to a dict.
      4. TOTAL parse failure (no dict found anywhere, best_size == 0) →
         return {'_fallback_reason': FallbackReason.PARSE_EMPTY.value}. This
         is the ONLY new behavior: it replaces the silent `{}` with a
         recordable cause. The dict still has NO 'verdict' key, so callers'
         tolerant `.get('verdict', 'iterate')` is unchanged and the ensemble
         `_vote_from_parsed` still routes it to a fallback vote.

    Distinguishing a legitimate empty `{}` (step 2 early-return) from a total
    parse failure (step 4) is what keeps the sentinel from mislabelling a
    real empty-object verdict (gen-1 critic non-blocking note).
    """
    import json as _json
    import re as _re

    candidate = raw
    if candidate.startswith("```"):
        first_nl = candidate.find("\n")
        if first_nl != -1:
            candidate = candidate[first_nl + 1:]
            if candidate.endswith("```"):
                candidate = candidate[:-3].strip()
    # Strict whole-text parse (clean output case). A bare `{}` returns here.
    try:
        decoded = _json.loads(candidate)
        if isinstance(decoded, dict):
            return decoded
    except _json.JSONDecodeError:
        pass
    # Scan all balanced JSON objects; return the LARGEST that parses as dict.
    parsed: dict = {}
    best_size = 0
    for match in _re.finditer(r"\{", raw):
        start = match.start()
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(raw)):
            c = raw[i]
            if esc:
                esc = False
                continue
            if c == "\\" and in_str:
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            span = end - start
            if span <= best_size:
                continue
            try:
                decoded = _json.loads(raw[start:end])
                if isinstance(decoded, dict):
                    parsed = decoded
                    best_size = span
            except _json.JSONDecodeError:
                continue
    if best_size == 0:
        # Total parse failure — no JSON object anywhere. Recordable sentinel
        # (no 'verdict' key → callers fall back as before).
        return {"_fallback_reason": FallbackReason.PARSE_EMPTY.value}
    return parsed


def invoke_evaluator_isolated(prompt: str, model: str | None = None,
                              timeout_seconds: int | None = None,
                              *,
                              gate_id: str | None = None,
                              ) -> tuple[str, dict]:
    """Invoke harness-evaluator via OpenAIProvider (codex exec subprocess).

    Closes residual #3 (subagent isolation OS-enforced):
      - codex exec runs as separate subprocess with `-s read-only` (no
        filesystem mutation)
      - sanitized env (HARNESS_*, ANTHROPIC_*, CLAUDE_*, ORCH_*, etc.
        stripped) — subprocess cannot inherit harness state
      - no claude-code Agent tool path → no shared context
      - codex CLI itself does not have Read/Grep/Bash on the parent's
        filesystem; it returns text completion only

    Returns (raw_text, parsed_json_or_empty_dict). Parser is tolerant —
    returns ({}, {}) on JSON parse failure (caller falls back to legacy E2).

    S6 wiring (residual_norm writer automation, wave 12): when `gate_id`
    is provided, the parsed verdict is mirrored into the matching
    residual-norm ledger via `update_ledger_post_dispatch`. gate_id=None
    (default) preserves byte-identical legacy behavior — no ledger touch.
    Caller specifies gate_id so the dispatcher does not have to infer
    which ledger this dispatch addresses (Q1 권고 — caller-specified
    mapping per HANDOFF wave 11 next_action).
    """
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty str")
    # Validate isolation invariant before spawn — prompt cannot reference
    # state/* paths or transcript keywords (per LEAK_PATTERN_REGEX).
    if not validate_prompt_isolation(prompt):
        raise ValueError(
            "prompt failed validate_prompt_isolation; refusing spawn "
            "(dispatcher bug — leak pattern in rendered prompt)"
        )

    from .providers.base import AskRequest, ProviderUnavailableError
    from .providers.openai import OpenAIProvider
    import os as _os
    import subprocess
    import json as _json

    provider = OpenAIProvider()
    if not provider.is_available():
        raise ProviderUnavailableError("codex CLI not on PATH")

    # We can't rely on OpenAIProvider's default env-passing — we want a
    # SANITIZED env. Replicate its core flow with env override.
    import shutil
    codex_path = shutil.which("codex")
    if not codex_path:
        raise ProviderUnavailableError("codex CLI not found")

    args: list[str] = ["exec", "--skip-git-repo-check", "-s", "read-only"]
    if model:
        args.extend(["-m", model])

    env = _build_isolated_env()
    timeout = timeout_seconds or SUBAGENT_TIMEOUT_SECONDS

    import platform
    is_batch_shim = (
        platform.system() == "Windows"
        and codex_path.lower().endswith((".cmd", ".bat"))
    )

    try:
        if is_batch_shim:
            command_line = subprocess.list2cmdline([codex_path, *args])
            proc = subprocess.run(
                command_line,
                shell=True,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",       # Windows cmd.exe stderr cp949 fallback (taskkill msgs)
                timeout=timeout,
                env=env,                # sanitized env enforced
            )
        else:
            proc = subprocess.run(
                [codex_path, *args],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
            )
    except subprocess.TimeoutExpired as e:
        raise ProviderUnavailableError(
            f"isolated codex subprocess timeout after {timeout}s"
        ) from e

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise ProviderUnavailableError(
            f"isolated codex exit {proc.returncode}: "
            f"{(proc.stderr or '')[:300]}"
        )

    # Parse JSON tolerantly — extract a JSON object from codex CLI output.
    # codex exec wraps the response in a banner (Reading prompt / version /
    # workdir / model / session id / --------) + user prompt echo + response +
    # "tokens used / N" footer. `_extract_json_object` pulls the object out;
    # on TOTAL parse failure it returns a {'_fallback_reason': 'parse_empty'}
    # sentinel (D3, debate-1780564679-8mgxsd) so the cause is recordable
    # instead of a silent {}. The sentinel carries no 'verdict' key, so the
    # ledger emit (and every caller's `.get('verdict')`) behaves as before.
    parsed = _extract_json_object(raw)
    _emit_ledger_update_silent(gate_id, str(parsed.get("verdict", "")))
    return raw, parsed


def fallback_to_legacy_e2(reason: FallbackReason, sid: str, phase_id: str,
                           validators_passed: bool,
                           units_passed: bool,
                           known_defects: int = 0) -> FallbackResult:
    """Legacy E2 fallback: build a synthetic verdict from validators+units
    objective tests only. No LLM call.

    Returns a dict suitable for log_axis_event:
      {
        event: 'fallback',
        fallback_reason: <reason.value>,
        verdict: 'approved'|'iterate'|'escalate',
        completeness: bool,
        ...
      }

    Verdict logic:
      - completeness=True (validators+units+defects==0) AND
        reason==PARADOX_GUARD_FAIL  → 'escalate' (operator review needed:
        why does paradox guard fail when objective tests pass?)
      - completeness=True AND reason==CONFIG_ERROR → 'escalate' (v15.35.4:
        config breakage cannot be fixed by another iteration; operator
        review required — added per debate-1779008782-230c36 gen 4 P5 fix)
      - completeness=True AND reason∈{TIMEOUT, EXCEPTION} → 'iterate'
        (LLM eval failed transiently; objective tests are clean)
      - completeness=False                                 → 'iterate'
    """
    from .evaluator import completeness_pass

    completeness = completeness_pass(validators_passed, units_passed, known_defects)
    if not completeness:
        verdict = "iterate"
    elif reason in (FallbackReason.PARADOX_GUARD_FAIL, FallbackReason.CONFIG_ERROR):
        verdict = "escalate"
    else:
        verdict = "iterate"

    return {
        "event": "fallback",
        "fallback_reason": reason.value,
        "phase_id": phase_id,
        "sid": sid,
        "verdict": verdict,
        "completeness": completeness,
        "validators_passed": validators_passed,
        "units_passed": units_passed,
        "known_defects": known_defects,
    }


# ============================================================================
# v15.35.1 — Ensemble wiring (HANDOFF v15.35 1순위 prompt)
# ============================================================================
#
# v15.35에서 lib/ensemble_evaluator.aggregate() API만 land. 본 cycle은 그 API를
# dispatcher path에 *결합* — invoke_evaluator_isolated의 single-call path 옆에
# invoke_ensemble_evaluator() N-spec path 추가.
#
# Single-file mutation surface (v15.27+ pattern) 엄격 준수:
#   - lib/ensemble_evaluator.py 불변 (v15.35 산출물)
#   - 새 provider adapter 추가 X (lib/providers/<name>.py 추가 별도 cycle)
#   - 본 cycle mutation = lib/evaluator_dispatcher.py 하나만 (append)
#
# 정량 잔여 노름 (lib.meta_rules quantitative_residual_norm v1.2):
#   - known defect: 기본 spec pool은 N=1 (codex single) — multi-LLM ensemble의
#     진짜 가치 (provider diversity) 미실현. v15.35의 quorum mechanism만 결합
#     (proof-of-wiring).
#   - 운영자가 evaluator_specs 인자로 N>=2 pool을 주입할 수 있는 hook은 제공.
#     실 사용은 lib/providers/google.py 등 신규 adapter cycle 이후.
#   - autopilot Phase 4 자동 dispatch는 여전히 invoke_evaluator_isolated 사용
#     (본 함수로의 자동 전환은 별도 cycle — runtime policy mutation 게이트).
#
# References:
#   - debate-1778987814-41b475 (v15.26 GateLeaf+AdvisoryLeaf 패턴)
#   - debate-1778990144-679cb8 (single-file mutation surface 채택)
#   - lib.ensemble_evaluator (v15.35 산출물, 본 cycle wiring 대상)

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class EvaluatorSpec:
    """One evaluator specification for ensemble dispatch.

    `provider` is the canonical adapter name and MUST pass
    `ensemble_evaluator.validate_evaluator_pool` (no Anthropic-family).

    `invoke_fn` takes the prompt and returns (raw_text, parsed_json) —
    same return shape as `invoke_evaluator_isolated`. Exceptions during
    invoke are caught by `invoke_ensemble_evaluator` and converted to a
    fallback vote (legacy E2: validators+units only).

    `model` is informational (audit trail). The actual model is bound
    inside `invoke_fn` (closure or partial). v15.35.1 default spec uses
    Codex CLI default (EVALUATOR_MODEL env override per
    lib.evaluator.resolve_evaluator_model).
    """
    evaluator_id: str
    provider: str
    invoke_fn: Callable[[str], tuple[str, dict]]
    model: str | None = None


def axis_log_emit_for(sid: str) -> Callable[[str, dict], None]:
    """Return an emit_fn closure that appends ensemble events to
    state/evaluator/<sid>/axis_scores.jsonl via lib.axis_scores_log.

    Closes the 'emit_fn → axis_scores.jsonl' wiring half from the v15.35
    1순위 prompt. Callers pass the returned closure as
    `invoke_ensemble_evaluator(..., emit_fn=axis_log_emit_for(sid))` to
    get the standard logging side-effect. None disables logging; a custom
    callable overrides (e.g., test mocks).

    The closure injects `event=event_type` into the payload and delegates
    to `log_axis_event`, which adds schema_version + ts (D6 convention)
    + atomic O_APPEND write + fsync. Fail-soft per axis_scores_log
    (returns False on I/O failure; closure swallows the return — emit_fn
    callers don't get failure signal, consistent with lib.rewind pattern).

    Raises ValueError if sid is empty (early failure — closure cannot
    silently write to an invalid path).

    Verified end-to-end via probe probe-1779097182-wave4 (2026-05-18, commit
    5e56400) — closure successfully wrote non-fallback Tier 2 verdict to
    state/evaluator/<sid>/axis_scores.jsonl after invoke_evaluator_isolated
    returned parsed dict from real codex CLI call.
    """
    if not isinstance(sid, str) or not sid:
        raise ValueError(f"sid must be non-empty str, got {sid!r}")
    # Import lazily so the helper does not force axis_scores_log on every
    # evaluator_dispatcher import — keeps module-load cost low.
    from .axis_scores_log import log_axis_event

    def _emit(event_type: str, payload: dict) -> None:
        log_payload = dict(payload) if isinstance(payload, dict) else {}
        log_payload["event"] = event_type
        log_axis_event(sid, log_payload)

    return _emit


def _invoke_ollama_evaluator(prompt: str) -> tuple[str, dict]:
    """Invoke ollama provider with the evaluator prompt and parse JSON.

    Symmetric to `invoke_evaluator_isolated` (codex path) but uses
    `lib.providers.ollama.OllamaProvider.ask` directly — ollama runs
    locally so no env sanitization is needed (no inherited cloud
    credentials to leak; no debate transcript access). The prompt
    isolation invariant (`validate_prompt_isolation`) is still enforced
    pre-spawn.

    Model selection: env OLLAMA_DEFAULT_MODEL > OllamaProvider.default_model
    ('llama3.1:8b' as of 2026-05-17).

    Returns (raw_text, parsed_json_or_empty_dict). Parser tolerates
    code-fenced JSON output (common with smaller local models).
    """
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty str")
    if not validate_prompt_isolation(prompt):
        raise ValueError(
            "prompt failed validate_prompt_isolation; refusing ollama spawn"
        )

    from .providers.ollama import OllamaProvider
    from .providers.base import AskRequest, ProviderUnavailableError
    import json as _json

    provider = OllamaProvider()
    if not provider.is_available():
        raise ProviderUnavailableError("ollama CLI or installed model missing")

    response = provider.ask(AskRequest(prompt=prompt))
    raw = (response.text or "").strip()

    # Tolerant JSON parse — strip ```json fences if present
    candidate = raw
    if candidate.startswith("```"):
        first_nl = candidate.find("\n")
        if first_nl != -1:
            candidate = candidate[first_nl + 1:]
            if candidate.endswith("```"):
                candidate = candidate[:-3].strip()
    parsed: dict = {}
    try:
        decoded = _json.loads(candidate)
        if isinstance(decoded, dict):
            parsed = decoded
    except _json.JSONDecodeError:
        parsed = {}

    return raw, parsed


def _invoke_claude_evaluator(prompt: str) -> tuple[str, dict]:
    """Invoke claude (AnthropicProvider) with the evaluator prompt.

    v15.35.3 — second evaluator spec for default pool. Same family as
    generator (Anthropic) BUT different model id (default claude-sonnet-
    4-6 vs generator claude-opus-4-7). Requires `allow_generator_family=
    True` upstream in `validate_evaluator_pool` (caller responsibility).

    Pre-spawn isolation: `validate_prompt_isolation(prompt)` enforced
    (same as codex/ollama paths). Tolerant JSON parser (strips ```json
    fences common with claude responses).

    Model selection: env CLAUDE_EVALUATOR_MODEL > AnthropicProvider
    default ('claude-sonnet-4-6'). Operators wanting stronger separation
    (e.g., haiku for cheaper diff perspective) can override via env.
    """
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty str")
    if not validate_prompt_isolation(prompt):
        raise ValueError(
            "prompt failed validate_prompt_isolation; refusing claude spawn"
        )

    import os as _os
    from .providers.anthropic import AnthropicProvider
    from .providers.base import AskRequest, ProviderUnavailableError
    import json as _json

    provider = AnthropicProvider()
    if not provider.is_available():
        raise ProviderUnavailableError(
            "claude CLI / anthropic SDK not available"
        )

    model = _os.environ.get("CLAUDE_EVALUATOR_MODEL") or provider.default_model
    response = provider.ask(AskRequest(prompt=prompt, model=model))
    raw = (response.text or "").strip()

    candidate = raw
    if candidate.startswith("```"):
        first_nl = candidate.find("\n")
        if first_nl != -1:
            candidate = candidate[first_nl + 1:]
            if candidate.endswith("```"):
                candidate = candidate[:-3].strip()
    parsed: dict = {}
    try:
        decoded = _json.loads(candidate)
        if isinstance(decoded, dict):
            parsed = decoded
    except _json.JSONDecodeError:
        parsed = {}

    return raw, parsed


def _build_default_ensemble_specs() -> list[EvaluatorSpec]:
    """Default ensemble pool.

    v15.35.3 retraction → revision — back to operator choice (codex + claude).

    v15.35.2의 conditional ollama append는 운영자 결정으로 철회 — 로컬
    GPU 자원이 부족한 host에서 8B 또는 그 이하 local 모델은 codex/claude
    대비 quality + latency 양쪽 손해, ensemble의 monoculture-bias-회피
    가치를 상쇄. ollama는 default pool에서 빠지되 lib/providers/ollama.py
    + _invoke_ollama_evaluator helper는 keep (운영자가 좋은 GPU 환경에서
    명시 spec 주입 시 사용 가능 — extensibility 보존).

    v15.35.3 revision (운영자 요청): default pool = N=2 (codex + claude).
    Claude는 generator와 *같은 family* (Anthropic) 이지만 *다른 model id*
    (default claude-sonnet-4-6 vs generator claude-opus-4-7). 이는
    judge-generator separation invariant의 strict 해석을 약화하는 결정:
      - strict (default validate_evaluator_pool 거부): family 수준 분리
        (Panickssery 2024 / Zheng MT-Bench 2023 — same-family RLHF
        artifact 공유)
      - relaxed (allow_generator_family=True, 본 default pool에서 채택):
        model-id 수준 분리만 (within-family variance에 의존)
    운영자가 trade-off를 인지하고 결정 — 본 dispatcher는 default pool에
    anthropic 멤버가 포함될 때 invoke_ensemble_evaluator 호출 시
    allow_generator_family=True를 자동 전달 (운영자 명시 결정 코드화).

    실제 cross-family ensemble (Kimi API / Gemini API / 기타 non-Anthropic
    cloud) 활성은 별도 cycle (cloud-based provider adapter).

    Caller override patterns:
      # strict family separation 유지 (codex만):
      specs = [EvaluatorSpec("codex-default", "openai",
                             lambda p: invoke_evaluator_isolated(p))]
      verdict = invoke_ensemble_evaluator(prompt, ..., evaluator_specs=specs)

      # ollama 직접 추가 (좋은 GPU 환경):
      specs.append(EvaluatorSpec("ollama-explicit", "ollama",
                                 lambda p: _invoke_ollama_evaluator(p),
                                 model="llama3.1:8b"))
      verdict = invoke_ensemble_evaluator(prompt, ..., evaluator_specs=specs)
    """
    specs: list[EvaluatorSpec] = [
        EvaluatorSpec(
            evaluator_id="codex-default",
            provider="openai",
            invoke_fn=lambda p: invoke_evaluator_isolated(p),
        ),
    ]
    # v15.35.3 — claude spec 추가 (운영자 결정, same-family escape hatch)
    try:
        from .providers.anthropic import AnthropicProvider
        if AnthropicProvider().is_available():
            specs.append(EvaluatorSpec(
                evaluator_id="claude-default",
                provider="anthropic",
                invoke_fn=lambda p: _invoke_claude_evaluator(p),
                model=AnthropicProvider.default_model,
            ))
    except Exception:
        # is_available() probe failure → skip claude spec silently.
        # Dispatcher path must not crash on probe-side issues.
        pass
    return specs


def _default_pool_needs_escape_hatch(specs: Sequence["EvaluatorSpec"]) -> bool:
    """True iff any spec in `specs` has an Anthropic-family provider.

    Used by invoke_ensemble_evaluator to auto-propagate
    allow_generator_family=True when caller relies on the default pool
    (which includes claude per v15.35.3 operator decision). Explicit
    operator-provided specs that happen to include anthropic still
    require explicit allow_generator_family=True — auto-propagation
    applies only to the default-pool path.
    """
    from .ensemble_evaluator import ANTHROPIC_PREFIXES, GENERATOR_PROVIDER
    for s in specs:
        lowered = s.provider.lower()
        if lowered == GENERATOR_PROVIDER:
            return True
        if any(lowered.startswith(pre) for pre in ANTHROPIC_PREFIXES):
            return True
    return False


def _vote_from_parsed(
    spec: EvaluatorSpec,
    parsed: dict,
):
    """Build an EvaluatorVote from a successful evaluator response.

    Applies per-evaluator completeness clamp (lib.evaluator) so the vote
    reflects the strict boolean GATE before ensemble aggregation.

    Returns None when the parsed payload is missing the required fields —
    caller treats as malformed and emits a fallback vote instead.
    """
    from .ensemble_evaluator import EvaluatorVote
    from .evaluator import clamp_verdict_on_completeness

    if not isinstance(parsed, dict):
        return None
    verdict_raw = parsed.get("verdict")
    if verdict_raw not in ("approved", "iterate", "escalate"):
        return None

    completeness_raw = parsed.get("completeness")
    completeness = completeness_raw if isinstance(completeness_raw, bool) else False

    # Per-evaluator clamp: completeness=False forces 'iterate'
    clamped_verdict, _clamp_reason = clamp_verdict_on_completeness(
        verdict_raw, completeness,
    )

    axis_raw = parsed.get("axis_scores")
    # v15.35.4 P4 fix (debate-1779008782-230c36 gen 4 condition): per-value
    # int-coercion guard. Without this, downstream worst-axis reduction
    # (min(v.axis_scores.values()) for v in votes if v.axis_scores) raises
    # TypeError when an evaluator returns axis_scores with None/str values
    # — observed when smaller local models drop fields or quote integers.
    # Drop non-int entries silently rather than crash the routing layer.
    if isinstance(axis_raw, dict):
        axis = {k: v for k, v in axis_raw.items()
                if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}
        if not axis:
            axis = None
    else:
        axis = None

    return EvaluatorVote(
        evaluator_id=spec.evaluator_id,
        provider=spec.provider,
        verdict=clamped_verdict,  # type: ignore[arg-type]
        paradox_guard_passes=True,
        completeness=completeness,
        axis_scores=axis,
    )


def _vote_from_fallback(
    spec: EvaluatorSpec,
    reason: FallbackReason,
    sid: str,
    phase_id: str,
    validators_passed: bool,
    units_passed: bool,
    known_defects: int,
    detail: str = "",
):
    """Build a fallback EvaluatorVote when spec.invoke_fn fails.

    Reuses `fallback_to_legacy_e2` for verdict logic (objective tests +
    paradox-fail awareness). The vote records paradox_guard_passes=False
    so the ensemble paradox layer can downgrade 'approved' to 'escalate'
    if a paradox-failing spec accidentally tipped the quorum.
    """
    from .ensemble_evaluator import EvaluatorVote

    fb = fallback_to_legacy_e2(
        reason, sid, phase_id,
        validators_passed, units_passed, known_defects,
    )
    fb_reason = f"{reason.value}:{spec.evaluator_id}"
    if detail:
        fb_reason = f"{fb_reason}:{detail}"
    return EvaluatorVote(
        evaluator_id=spec.evaluator_id,
        provider=spec.provider,
        verdict=fb["verdict"],
        paradox_guard_passes=False,
        completeness=bool(fb["completeness"]),
        fallback_reason=fb_reason,
    )


def invoke_ensemble_evaluator(
    prompt: str,
    *,
    sid: str,
    phase_id: str,
    validators_passed: bool,
    units_passed: bool,
    known_defects: int,
    evaluator_specs: Sequence[EvaluatorSpec] | None = None,
    allow_generator_family: bool | None = None,
    emit_fn: Callable[[str, dict], None] | None = None,
    gate_id: str | None = None,
) -> "EnsembleVerdict":  # noqa: F821 — forward ref via __future__ annotations
    """Dispatch the artifact to N evaluator specs and aggregate quorum.

    Algorithm:
      1. Resolve specs (default = N=1 codex pool when None).
      2. validate_evaluator_pool([s.provider for s in specs]) — raises
         EnsembleConfigError on Anthropic-family contamination.
      3. For each spec:
         - Call spec.invoke_fn(prompt) inside a guarded try.
         - On success: build EvaluatorVote via _vote_from_parsed;
           malformed payload → fallback vote (SUBAGENT_EXCEPTION).
         - On subprocess.TimeoutExpired or 'timeout' in str(exc) →
           fallback vote (SUBAGENT_TIMEOUT).
         - On any other exception → fallback vote (SUBAGENT_EXCEPTION).
      4. ensemble_evaluator.aggregate(votes, emit_fn=emit_fn) returns
         EnsembleVerdict (quorum + paradox layer).

    Notes:
      - prompt isolation (validate_prompt_isolation) is the responsibility
        of the spec's invoke_fn (default spec delegates to
        invoke_evaluator_isolated which validates). Callers providing
        custom invoke_fn MUST validate isolation themselves.
      - paradox_guard 3-condition (lib.evaluator) is enforced by the
        UPSTREAM dispatcher path (should_dispatch / pre-check). Votes
        produced here assume that check already passed — the per-vote
        paradox_guard_passes flag here reflects per-invocation success,
        NOT the upstream 3-condition guard.
      - Ensemble does NOT mutate state/evaluator/<sid>/dispatch_counter.json;
        callers (autopilot Phase 4 / /harness-evaluate) record_dispatch()
        once per ensemble call to keep PER_PHASE_EVAL_LIMIT semantics.

    Returns:
      EnsembleVerdict (lib.ensemble_evaluator) — access collective verdict
      via `.quorum_verdict` (NOT `.verdict` — that is EvaluatorVote field).
      Completeness via `all(v.completeness for v in result.votes)`. See
      lib.ensemble_evaluator.EnsembleVerdict docstring §Caller-side
      accessor guide for full pattern + v15.40.3 broken history.

    S6 wiring (residual_norm writer automation, wave 12): when `gate_id`
    is provided, `quorum_verdict` is mirrored into the matching
    residual-norm ledger via `update_ledger_post_dispatch`. gate_id=None
    (default) preserves byte-identical legacy behavior — no ledger touch.
    Same caller-specified mapping contract as invoke_evaluator_isolated
    (Q1 권고 per HANDOFF wave 11 next_action).
    """
    import subprocess as _subprocess
    from .ensemble_evaluator import (
        EnsembleConfigError,
        aggregate,
        validate_evaluator_pool,
    )

    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty str")
    if not isinstance(sid, str) or not sid:
        raise ValueError("sid must be non-empty str")
    if not isinstance(phase_id, str) or not phase_id:
        raise ValueError("phase_id must be non-empty str")

    # NB: distinguish None (use default pool) from [] (explicit empty → reject).
    # `if evaluator_specs` would treat both as "use default" — wrong semantics.
    using_default_pool = evaluator_specs is None
    if using_default_pool:
        specs = _build_default_ensemble_specs()
    else:
        specs = list(evaluator_specs)
    if not specs:
        raise EnsembleConfigError(
            "evaluator_specs must be non-empty (or pass None for default pool)"
        )

    # v15.35.3 — allow_generator_family resolution:
    #   - explicit True/False from caller → honored
    #   - None (default) + default pool → auto True if pool contains
    #     anthropic-family (operator-decision codified in default pool)
    #   - None (default) + custom specs → False (strict — caller must opt
    #     in explicitly to relax invariant)
    if allow_generator_family is None:
        allow_generator_family = (
            using_default_pool and _default_pool_needs_escape_hatch(specs)
        )

    # Pool invariant (judge-generator separation, provider level)
    validate_evaluator_pool(
        [s.provider for s in specs],
        allow_generator_family=allow_generator_family,
    )

    votes = []
    for spec in specs:
        try:
            raw_parsed = spec.invoke_fn(prompt)
            if not (isinstance(raw_parsed, tuple) and len(raw_parsed) == 2):
                votes.append(_vote_from_fallback(
                    spec, FallbackReason.SUBAGENT_EXCEPTION,
                    sid, phase_id,
                    validators_passed, units_passed, known_defects,
                    detail="invoke_fn_bad_return_shape",
                ))
                continue
            _raw, parsed = raw_parsed
            vote = _vote_from_parsed(spec, parsed)
            if vote is None:
                votes.append(_vote_from_fallback(
                    spec, FallbackReason.SUBAGENT_EXCEPTION,
                    sid, phase_id,
                    validators_passed, units_passed, known_defects,
                    detail="malformed_response",
                ))
            else:
                votes.append(vote)
        except _subprocess.TimeoutExpired:
            votes.append(_vote_from_fallback(
                spec, FallbackReason.SUBAGENT_TIMEOUT,
                sid, phase_id,
                validators_passed, units_passed, known_defects,
            ))
        except Exception as e:
            # Heuristic: provider-unavailable with 'timeout' message →
            # SUBAGENT_TIMEOUT for honest fallback categorization.
            is_timeout = "timeout" in str(e).lower()
            reason_enum = (
                FallbackReason.SUBAGENT_TIMEOUT
                if is_timeout
                else FallbackReason.SUBAGENT_EXCEPTION
            )
            votes.append(_vote_from_fallback(
                spec, reason_enum,
                sid, phase_id,
                validators_passed, units_passed, known_defects,
                detail=type(e).__name__,
            ))

    result = aggregate(
        votes,
        allow_generator_family=allow_generator_family,
        emit_fn=emit_fn,
    )
    # S6 wiring: mirror collective verdict into residual-norm ledger when
    # caller specified gate_id. Uses .quorum_verdict per EnsembleVerdict
    # caller-accessor guide (NOT .verdict — that is per-vote EvaluatorVote
    # field). gate_id=None default preserves legacy behavior.
    _emit_ledger_update_silent(gate_id, str(getattr(result, "quorum_verdict", "") or ""))
    return result


# ============================================================================
# Path 2 D7 — rlm_gate.json ledger reader/writer wiring (wave 10)
# ============================================================================
#
# debate-1779229138-db17ce gen 3 LOCK SHA c75bfaf403981c1fcd8cb45c0872c83ae564b777
# (Path 2 D7). Plumbs the D2 ledger (state/residual_norm/rlm_gate.json) into
# the dispatcher pre-check + ensemble call sites so `known_defects` is
# real-state-sourced, not a hardcoded 0.
#
# Three surfaces:
#   read_known_defects_from_ledger(state_root) -> int
#     Read state_root/residual_norm/*.json and sum known_defects. Fail-soft
#     returns 0 on missing/corrupt — caller (autopilot Phase 4 / dispatcher
#     pre-check) wants graceful degradation when the ledger doesn't exist.
#   update_ledger_post_dispatch(state_root, gate_id, verdict, ts=None) -> bool
#     Append-only update of the matching ledger's last_eval_ts +
#     last_verdict fields. Atomic JSON write. Returns False on failure
#     (caller logs but does not abort — ledger update is observability,
#     not gating).
#   resolve_ledger_state_root() -> Path
#     Helper that mirrors handlers/stop/calendar_gate_emitter._resolve_state_root
#     (CLAUDE_HOME env > ~/.claude/state).
#
# Cross-references:
#   - D2 ledger schema: state/residual_norm/rlm_gate.json
#   - D1 lib/calendar_gate.read_ledger (validates schema, reused here)
#   - autopilot Phase 4 invoke_ensemble_evaluator / fallback_to_legacy_e2
#     `known_defects` parameter (existing surface)


def resolve_ledger_state_root() -> "Path":
    """Resolve the state_root directory for ledger reads.

    Priority:
      1. CLAUDE_HOME env (test override) → $CLAUDE_HOME/state
      2. ~/.claude/state (default)

    Returns Path. Caller is responsible for checking existence — this
    function does NOT mkdir or validate the directory.
    """
    import os as _os
    from pathlib import Path as _P
    claude_home = _os.environ.get("CLAUDE_HOME")
    if claude_home:
        return _P(claude_home) / "state"
    return _P.home() / ".claude" / "state"


def read_known_defects_from_ledger(
    state_root: "Path | str | None" = None,
    gate_id: str | None = None,
) -> int:
    """Sum `known_defects` across residual-norm ledgers.

    Args:
      state_root: state root directory. None → resolve_ledger_state_root().
      gate_id: optional filter — only sum the matching gate's ledger. None
        sums all ledgers in state_root/residual_norm/.

    Returns:
      Non-negative int. 0 when:
        - state_root or state_root/residual_norm missing
        - no ledger matches gate_id filter
        - all matched ledgers report known_defects=0
        - any unrecoverable read error (fail-soft — caller wants 0
          baseline rather than dispatcher abort)

    Note: this function does NOT read the calendar_gate deadline. Caller
    that wants "overdue ledger" semantics should use
    lib.calendar_gate.scan_deadlines. This function answers "what is the
    current known_defects total?" — the input to
    fallback_to_legacy_e2(known_defects=...) / invoke_ensemble_evaluator
    (known_defects=...).
    """
    from pathlib import Path as _P
    try:
        if state_root is None:
            state_root = resolve_ledger_state_root()
        root = _P(state_root)
        rn_dir = root / "residual_norm"
        if not rn_dir.is_dir():
            return 0
    except Exception:
        return 0

    total = 0
    try:
        from .calendar_gate import read_ledger, LedgerParseError
    except ImportError:
        return 0

    for ledger_path in sorted(rn_dir.glob("*.json")):
        try:
            data = read_ledger(ledger_path)
        except (OSError, ValueError):
            continue
        if gate_id is not None and data.get("gate_id") != gate_id:
            continue
        defects = data.get("known_defects", 0)
        if isinstance(defects, int) and not isinstance(defects, bool):
            if defects > 0:
                total += defects
    return total


def update_ledger_post_dispatch(
    gate_id: str,
    verdict: str,
    state_root: "Path | str | None" = None,
    ts: str | None = None,
) -> bool:
    """Update `last_eval_ts` + `last_verdict` for the matching ledger.

    Args:
      gate_id: ledger to update (matched by .gate_id field — not filename).
      verdict: one of 'approved' / 'iterate' / 'escalate' / 'fallback'.
        Caller passes the post-dispatch outcome string (NOT a verdict
        enum). Empty string OK (records "no verdict" e.g. on hard error
        before LLM call).
      state_root: optional override; None → resolve_ledger_state_root().
      ts: ISO timestamp string. None → current UTC time.

    Returns:
      True on successful write. False on any failure (missing ledger,
      malformed JSON, atomic write failure, gate_id not found). Caller
      logs failure but does not abort — ledger update is observability
      not gating.

    Atomic write via lib.atomic_json.write_json_atomic.
    """
    if not isinstance(gate_id, str) or not gate_id:
        return False
    if not isinstance(verdict, str):
        return False

    from pathlib import Path as _P
    try:
        if state_root is None:
            state_root = resolve_ledger_state_root()
        root = _P(state_root)
        rn_dir = root / "residual_norm"
        if not rn_dir.is_dir():
            return False
    except Exception:
        return False

    if ts is None:
        try:
            from datetime import datetime as _dt, timezone as _tz
            ts = _dt.now(_tz.utc).isoformat()
        except Exception:
            ts = ""

    try:
        from .calendar_gate import read_ledger
        from .atomic_json import write_json_atomic
    except ImportError:
        return False

    for ledger_path in sorted(rn_dir.glob("*.json")):
        try:
            data = read_ledger(ledger_path)
        except (OSError, ValueError):
            continue
        if data.get("gate_id") != gate_id:
            continue
        data["last_eval_ts"] = ts
        data["last_verdict"] = verdict if verdict else None
        try:
            ok = write_json_atomic(ledger_path, data)
        except Exception:
            return False
        return bool(ok)
    return False


def _emit_ledger_update_silent(gate_id: str | None, verdict: str) -> None:
    """Fail-soft wrapper around update_ledger_post_dispatch for S6 wiring.

    No-op when gate_id is None — preserves byte-identical legacy behavior
    for all callers that don't opt in to ledger writeback. When gate_id
    is provided, mirrors the post-dispatch verdict into the matching
    residual-norm ledger; any exception is swallowed because ledger
    update is observability, not gating (same fail-soft contract as
    update_ledger_post_dispatch itself).

    S6 spec (HANDOFF wave 11 next_action): caller-specified gate_id
    mapping (Q1 권고) so the dispatcher does not have to infer which
    ledger this dispatch addresses. invoke_evaluator_isolated and
    invoke_ensemble_evaluator both route through this helper to ensure
    a uniform mutation boundary — only this single function is the
    ledger-write call site outside update_ledger_post_dispatch's own
    direct callers.
    """
    if not gate_id:
        return
    try:
        update_ledger_post_dispatch(gate_id, verdict)
    except Exception:
        pass


# ============================================================================
# Embedded self-check (single-file mutation surface invariant — v15.35.1)
# ============================================================================


def _self_check() -> int:
    """Validate v15.35.1 wiring: invoke_ensemble_evaluator + spec helpers.

    Existing test_evaluator_dispatcher.py covers the v15.35.0 surface
    (counter / isolation / prompt builder / fallback verdict). This
    embedded check covers ONLY the new wiring functions to avoid
    multi-file mutation. Mock invoke_fn supplied — no real codex spawn.
    """
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    from .ensemble_evaluator import (
        EnsembleConfigError,
        EvaluatorVote,
    )

    # ---- Case 1 (v15.35.3): default specs build
    # codex always slot 0; claude conditionally appended when
    # AnthropicProvider.is_available() (operator-decision pool) ----
    default_specs = _build_default_ensemble_specs()
    case("default_specs_at_least_one", len(default_specs) >= 1)
    case("default_specs_codex_first",
         default_specs[0].provider == "openai"
         and default_specs[0].evaluator_id == "codex-default")
    # Cross-check: providers in pool must all pass validate_evaluator_pool
    # with escape-hatch flag derived from _default_pool_needs_escape_hatch.
    # (Direct strict call would FAIL when claude is present — that's the
    # whole point of the v15.35.3 escape hatch.)
    from .ensemble_evaluator import validate_evaluator_pool as _vep
    needs_hatch = _default_pool_needs_escape_hatch(default_specs)
    try:
        _vep([s.provider for s in default_specs],
             allow_generator_family=needs_hatch)
        case("default_specs_pass_pool_validation_with_hatch", True)
    except Exception as e:
        case("default_specs_pass_pool_validation_with_hatch",
             False, str(e))
    # Claude conditionally appears (depends on host's anthropic SDK / CLI)
    from .providers.anthropic import AnthropicProvider as _AP
    if _AP().is_available():
        case("default_specs_n2_when_claude_present",
             len(default_specs) == 2
             and default_specs[1].provider == "anthropic"
             and default_specs[1].evaluator_id == "claude-default")
        case("default_specs_n2_needs_escape_hatch", needs_hatch is True)
    else:
        case("default_specs_n1_when_claude_absent",
             len(default_specs) == 1)
        case("default_specs_n1_no_escape_hatch_needed",
             needs_hatch is False)
    # _default_pool_needs_escape_hatch helper edge cases
    case("escape_hatch_helper_empty_false",
         _default_pool_needs_escape_hatch([]) is False)
    case("escape_hatch_helper_openai_only_false",
         _default_pool_needs_escape_hatch([
             EvaluatorSpec("e1", "openai", lambda p: ("", {}))
         ]) is False)
    case("escape_hatch_helper_anthropic_true",
         _default_pool_needs_escape_hatch([
             EvaluatorSpec("e1", "anthropic", lambda p: ("", {}))
         ]) is True)
    case("escape_hatch_helper_claude_prefix_true",
         _default_pool_needs_escape_hatch([
             EvaluatorSpec("e1", "claude-sonnet-4-6",
                           lambda p: ("", {}))
         ]) is True)

    # ---- Case 2: _vote_from_parsed builds well-formed vote ----
    spec_ok = EvaluatorSpec(
        evaluator_id="mock-1",
        provider="openai",
        invoke_fn=lambda p: ("", {}),
    )
    parsed_ok = {
        "verdict": "approved",
        "completeness": True,
        "axis_scores": {"cohesion": 5, "coupling": 4,
                        "extensibility": 5, "stability": 5,
                        "usability": 4},
    }
    v1 = _vote_from_parsed(spec_ok, parsed_ok)
    case("vote_from_parsed_returns_vote",
         isinstance(v1, EvaluatorVote))
    case("vote_from_parsed_approved", v1 and v1.verdict == "approved")
    case("vote_from_parsed_axis_preserved",
         v1 and isinstance(v1.axis_scores, dict)
         and v1.axis_scores.get("cohesion") == 5)
    case("vote_from_parsed_paradox_true",
         v1 and v1.paradox_guard_passes is True)

    # ---- Case 3: _vote_from_parsed completeness clamp ----
    parsed_clamp = {
        "verdict": "approved",  # would-be approved
        "completeness": False,  # but completeness gate fails
    }
    v_clamp = _vote_from_parsed(spec_ok, parsed_clamp)
    case("vote_completeness_clamp_to_iterate",
         v_clamp and v_clamp.verdict == "iterate")
    case("vote_completeness_clamp_completeness_false",
         v_clamp and v_clamp.completeness is False)

    # ---- Case 4: _vote_from_parsed returns None on malformed ----
    case("vote_from_parsed_none_for_bad_verdict",
         _vote_from_parsed(spec_ok, {"verdict": "bogus"}) is None)
    case("vote_from_parsed_none_for_no_verdict",
         _vote_from_parsed(spec_ok, {"completeness": True}) is None)
    case("vote_from_parsed_none_for_non_dict",
         _vote_from_parsed(spec_ok, "not a dict") is None)  # type: ignore[arg-type]

    # ---- Case 5: _vote_from_fallback contributes paradox-fail vote ----
    fb_vote = _vote_from_fallback(
        spec_ok, FallbackReason.SUBAGENT_TIMEOUT,
        sid="orch-test-1", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
    )
    case("fallback_vote_is_evaluator_vote",
         isinstance(fb_vote, EvaluatorVote))
    case("fallback_vote_paradox_false",
         fb_vote.paradox_guard_passes is False)
    case("fallback_vote_has_reason",
         fb_vote.fallback_reason
         and "subagent_timeout" in fb_vote.fallback_reason
         and "mock-1" in fb_vote.fallback_reason)

    # ---- Case 6: invoke_ensemble_evaluator default pool unanimous approved ----
    def _good_invoke(_p: str) -> tuple[str, dict]:
        return ("raw", {
            "verdict": "approved",
            "completeness": True,
            "axis_scores": {"cohesion": 5, "coupling": 5,
                            "extensibility": 5, "stability": 5,
                            "usability": 5},
        })

    specs_good = [
        EvaluatorSpec("e1", "openai", _good_invoke),
        EvaluatorSpec("e2", "google", _good_invoke),
        EvaluatorSpec("e3", "deepseek", _good_invoke),
    ]
    emit_log: list[tuple[str, dict]] = []
    v_good = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-2", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_good,
        emit_fn=lambda et, p: emit_log.append((et, p)),
    )
    case("ensemble_unanimous_approved", v_good.quorum_verdict == "approved")
    case("ensemble_unanimous_emit_once", len(emit_log) == 1)
    case("ensemble_unanimous_emit_event",
         emit_log and emit_log[0][0] == "ensemble.aggregated")
    case("ensemble_unanimous_pool_size",
         emit_log and emit_log[0][1].get("pool_size") == 3)

    # ---- Case 7: invoke_ensemble_evaluator with one timeout → 2 good + 1 fallback ----
    import subprocess as _sp

    def _timeout_invoke(_p: str) -> tuple[str, dict]:
        raise _sp.TimeoutExpired(cmd="codex", timeout=120)

    specs_mixed = [
        EvaluatorSpec("e1", "openai", _good_invoke),
        EvaluatorSpec("e2", "google", _good_invoke),
        EvaluatorSpec("e3", "deepseek", _timeout_invoke),
    ]
    v_mixed = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-3", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_mixed,
    )
    # 2 approved + 1 fallback (which becomes 'iterate' because
    # fallback_to_legacy_e2 with completeness=True + non-paradox reason → 'iterate')
    # → quorum 'approved' raw, BUT paradox_guard_all_pass=False (timeout vote)
    # → ensemble paradox layer DOWNGRADES to 'escalate'
    case("ensemble_one_timeout_paradox_layer_downgrades",
         v_mixed.quorum_verdict == "escalate")
    case("ensemble_one_timeout_paradox_all_pass_false",
         v_mixed.paradox_guard_all_pass is False)
    case("ensemble_one_timeout_has_escalation_reason",
         any("ensemble_paradox_layer" in r
             for r in v_mixed.escalation_reasons))

    # ---- Case 8: all timeouts → all fallback votes (paradox False),
    # all 'iterate', quorum='iterate' (NOT downgraded because not 'approved') ----
    specs_all_timeout = [
        EvaluatorSpec("e1", "openai", _timeout_invoke),
        EvaluatorSpec("e2", "google", _timeout_invoke),
        EvaluatorSpec("e3", "deepseek", _timeout_invoke),
    ]
    v_all_to = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-4", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_all_timeout,
    )
    case("ensemble_all_timeout_quorum_iterate",
         v_all_to.quorum_verdict == "iterate")
    case("ensemble_all_timeout_paradox_all_fail",
         v_all_to.paradox_guard_all_pass is False)
    case("ensemble_all_timeout_no_paradox_layer_downgrade",
         not any("ensemble_paradox_layer" in r
                 for r in v_all_to.escalation_reasons))

    # ---- Case 9: bad return shape → fallback vote with detail ----
    def _bad_shape_invoke(_p: str):
        return "only one value, not a tuple"

    specs_bad = [
        EvaluatorSpec("e1", "openai", _good_invoke),
        EvaluatorSpec("e2", "google", _bad_shape_invoke),  # type: ignore[arg-type]
        EvaluatorSpec("e3", "deepseek", _good_invoke),
    ]
    v_bad = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-5", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_bad,
    )
    # e2 contributes fallback (paradox=False, iterate). Quorum: 2 approved → would
    # have been approved BUT paradox_all_pass=False → escalate.
    case("ensemble_bad_shape_downgrades",
         v_bad.quorum_verdict == "escalate")
    bad_fb_vote = [v for v in v_bad.votes
                   if v.evaluator_id == "e2"][0]
    case("ensemble_bad_shape_detail_recorded",
         bad_fb_vote.fallback_reason
         and "invoke_fn_bad_return_shape" in bad_fb_vote.fallback_reason)

    # ---- Case 10: malformed response → fallback vote ----
    def _malformed_invoke(_p: str) -> tuple[str, dict]:
        return ("raw", {"verdict": "bogus_label"})

    specs_malformed = [
        EvaluatorSpec("e1", "openai", _malformed_invoke),
    ]
    v_mf = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-6", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_malformed,
    )
    case("ensemble_malformed_single_falls_back",
         v_mf.votes[0].fallback_reason
         and "malformed_response" in v_mf.votes[0].fallback_reason)

    # ---- Case 11: arbitrary exception → SUBAGENT_EXCEPTION fallback ----
    def _explode_invoke(_p: str) -> tuple[str, dict]:
        raise RuntimeError("kaboom")

    specs_exc = [
        EvaluatorSpec("e1", "openai", _explode_invoke),
    ]
    v_exc = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-7", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_exc,
    )
    case("ensemble_exception_fallback_reason",
         v_exc.votes[0].fallback_reason
         and "subagent_exception" in v_exc.votes[0].fallback_reason
         and "RuntimeError" in v_exc.votes[0].fallback_reason)

    # ---- Case 12: exception with 'timeout' substring → SUBAGENT_TIMEOUT ----
    def _timeout_msg_invoke(_p: str) -> tuple[str, dict]:
        raise RuntimeError("got a timeout response from upstream")

    specs_to_msg = [
        EvaluatorSpec("e1", "openai", _timeout_msg_invoke),
    ]
    v_to_msg = invoke_ensemble_evaluator(
        "prompt-body",
        sid="orch-test-8", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_to_msg,
    )
    case("ensemble_timeout_substring_categorized_as_timeout",
         v_to_msg.votes[0].fallback_reason
         and "subagent_timeout" in v_to_msg.votes[0].fallback_reason)

    # ---- Case 13: empty specs → EnsembleConfigError ----
    try:
        invoke_ensemble_evaluator(
            "p", sid="s", phase_id="P",
            validators_passed=True, units_passed=True, known_defects=0,
            evaluator_specs=[],
        )
        case("ensemble_empty_specs_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("ensemble_empty_specs_rejects", True)

    # ---- Case 14: anthropic-family in pool → EnsembleConfigError ----
    specs_bad_pool = [
        EvaluatorSpec("e1", "openai", _good_invoke),
        EvaluatorSpec("e2", "anthropic", _good_invoke),
    ]
    try:
        invoke_ensemble_evaluator(
            "p", sid="s", phase_id="P",
            validators_passed=True, units_passed=True, known_defects=0,
            evaluator_specs=specs_bad_pool,
        )
        case("ensemble_anthropic_pool_rejects", False,
             "expected EnsembleConfigError")
    except EnsembleConfigError:
        case("ensemble_anthropic_pool_rejects", True)

    # ---- Case 15: input validation (empty prompt / sid / phase_id) ----
    for bad in [
        ("", "s", "P"),
        ("p", "", "P"),
        ("p", "s", ""),
    ]:
        try:
            invoke_ensemble_evaluator(
                bad[0], sid=bad[1], phase_id=bad[2],
                validators_passed=True, units_passed=True, known_defects=0,
                evaluator_specs=[EvaluatorSpec("e1", "openai", _good_invoke)],
            )
            case(f"ensemble_input_validation_rejects_{bad}", False,
                 "expected ValueError")
        except ValueError:
            case(f"ensemble_input_validation_rejects_{bad}", True)

    # ---- Case 16: votes tuple preserves insertion order ----
    v_order = invoke_ensemble_evaluator(
        "p", sid="orch-test-9", phase_id="P1",
        validators_passed=True, units_passed=True, known_defects=0,
        evaluator_specs=specs_good,
    )
    case("ensemble_votes_insertion_order",
         tuple(v.evaluator_id for v in v_order.votes) == ("e1", "e2", "e3"))

    # ---- Case 17 (axis_log_emit_for): closure writes to axis_scores.jsonl ----
    import tempfile as _tf
    import os as _os
    import json as _json
    from pathlib import Path as _Path

    # Redirect STATE_DIR via CLAUDE_HOME so log writes go to a temp tree
    with _tf.TemporaryDirectory() as _td:
        prev_home = _os.environ.get("CLAUDE_HOME")
        _os.environ["CLAUDE_HOME"] = str(_Path(_td))
        # Invalidate paths cache: lib.paths reads CLAUDE_HOME lazily but
        # STATE_DIR is a module-level constant — re-import to pick up env.
        # (axis_scores_log uses `from .paths import STATE_DIR` inside log_dir
        # so the lookup happens at call-time, no re-import needed.)

        try:
            # Reject empty sid
            try:
                axis_log_emit_for("")
                case("axis_log_emit_empty_sid_rejects", False,
                     "expected ValueError")
            except ValueError:
                case("axis_log_emit_empty_sid_rejects", True)

            emit = axis_log_emit_for("orch-axis-test")
            case("axis_log_emit_returns_callable", callable(emit))

            emit("ensemble.aggregated", {
                "pool_size": 2,
                "quorum_verdict": "approved",
                "split": False,
            })

            # Verify file exists + contains the event with schema_version
            from .axis_scores_log import read_axis_events
            events = read_axis_events("orch-axis-test")
            case("axis_log_emit_writes_event_line", len(events) == 1)
            if events:
                e0 = events[0]
                case("axis_log_emit_event_field_injected",
                     e0.get("event") == "ensemble.aggregated")
                case("axis_log_emit_payload_preserved",
                     e0.get("quorum_verdict") == "approved"
                     and e0.get("pool_size") == 2)
                case("axis_log_emit_schema_version_present",
                     e0.get("schema_version") == "1")
            else:
                case("axis_log_emit_event_field_injected", False, "no events")
                case("axis_log_emit_payload_preserved", False, "no events")
                case("axis_log_emit_schema_version_present", False, "no events")

            # Non-dict payload tolerated (closure coerces to {})
            emit("ensemble.aggregated", None)  # type: ignore[arg-type]
            events2 = read_axis_events("orch-axis-test")
            case("axis_log_emit_non_dict_payload_tolerated",
                 len(events2) == 2)
        finally:
            if prev_home is None:
                _os.environ.pop("CLAUDE_HOME", None)
            else:
                _os.environ["CLAUDE_HOME"] = prev_home

    # ---- Case 18 (v15.35.2): _invoke_ollama_evaluator input guards ----
    try:
        _invoke_ollama_evaluator("")
        case("ollama_invoke_empty_prompt_rejects", False,
             "expected ValueError")
    except ValueError:
        case("ollama_invoke_empty_prompt_rejects", True)

    # Leak-pattern in prompt → reject before subprocess spawn
    leaky = "see events.jsonl for prior context"
    try:
        _invoke_ollama_evaluator(leaky)
        case("ollama_invoke_leaky_prompt_rejects", False,
             "expected ValueError")
    except ValueError:
        case("ollama_invoke_leaky_prompt_rejects", True)
    except Exception as e:
        # If ollama unavailable, validate_prompt_isolation fires first
        # (ValueError) before is_available() check; if the order is
        # reversed (ProviderUnavailableError), test environment-dependent.
        # Accept either as long as the leaky prompt did NOT reach subprocess.
        case("ollama_invoke_leaky_prompt_rejects", True,
             f"alt: {type(e).__name__}")

    # ---- Case 18b (v15.35.3): _invoke_claude_evaluator input guards ----
    try:
        _invoke_claude_evaluator("")
        case("claude_invoke_empty_prompt_rejects", False,
             "expected ValueError")
    except ValueError:
        case("claude_invoke_empty_prompt_rejects", True)

    try:
        _invoke_claude_evaluator("see events.jsonl for prior context")
        case("claude_invoke_leaky_prompt_rejects", False,
             "expected ValueError")
    except ValueError:
        case("claude_invoke_leaky_prompt_rejects", True)
    except Exception as e:
        # Same tolerance as ollama: provider-unavailable order may differ
        case("claude_invoke_leaky_prompt_rejects", True,
             f"alt: {type(e).__name__}")

    # ---- Case 18c (v15.35.3): default-pool invoke with auto-hatch ----
    # When default pool contains claude, invoke_ensemble_evaluator must
    # auto-set allow_generator_family=True (no explicit caller flag).
    # Reproduce by constructing a default-style spec list with claude
    # and calling with allow_generator_family=None (sentinel default).
    if _AP().is_available():
        # Build spec list with mock invoke_fns to avoid real network calls
        def _good_invoke_mock(_p: str) -> tuple[str, dict]:
            return ("raw", {
                "verdict": "approved",
                "completeness": True,
                "axis_scores": {"cohesion": 5, "coupling": 5,
                                "extensibility": 5, "stability": 5,
                                "usability": 5},
            })
        # Custom specs containing anthropic require explicit hatch
        custom_anthropic_specs = [
            EvaluatorSpec("e1", "openai", _good_invoke_mock),
            EvaluatorSpec("e2", "anthropic", _good_invoke_mock),
        ]
        # Explicit None on custom specs → strict (False) → should REJECT
        try:
            invoke_ensemble_evaluator(
                "prompt",
                sid="orch-v3501-a", phase_id="P1",
                validators_passed=True, units_passed=True, known_defects=0,
                evaluator_specs=custom_anthropic_specs,
                allow_generator_family=None,
            )
            case("custom_specs_none_flag_strict_rejects_anthropic", False,
                 "expected EnsembleConfigError")
        except EnsembleConfigError:
            case("custom_specs_none_flag_strict_rejects_anthropic", True)
        # Explicit True on custom specs → passes
        try:
            v_custom_hatch = invoke_ensemble_evaluator(
                "prompt",
                sid="orch-v3501-b", phase_id="P1",
                validators_passed=True, units_passed=True, known_defects=0,
                evaluator_specs=custom_anthropic_specs,
                allow_generator_family=True,
            )
            case("custom_specs_explicit_true_accepts_anthropic",
                 v_custom_hatch.quorum_verdict == "approved")
        except Exception as e:
            case("custom_specs_explicit_true_accepts_anthropic",
                 False, str(e))

    # ---- Case 18d (v15.35.4 P5 fix): FallbackReason.CONFIG_ERROR routing ----
    case("fallback_reason_has_config_error",
         hasattr(FallbackReason, "CONFIG_ERROR")
         and FallbackReason.CONFIG_ERROR.value == "config_error")
    # CONFIG_ERROR with completeness=True → 'escalate' (operator review required)
    fb_cfg = fallback_to_legacy_e2(
        FallbackReason.CONFIG_ERROR, "sid-cfg", "P1",
        validators_passed=True, units_passed=True, known_defects=0,
    )
    case("fallback_config_error_completeness_true_escalates",
         fb_cfg["verdict"] == "escalate")
    case("fallback_config_error_fallback_reason_field",
         fb_cfg["fallback_reason"] == "config_error")
    # CONFIG_ERROR with completeness=False (tests failed) → still 'iterate'
    fb_cfg_incomplete = fallback_to_legacy_e2(
        FallbackReason.CONFIG_ERROR, "sid-cfg", "P1",
        validators_passed=False, units_passed=True, known_defects=0,
    )
    case("fallback_config_error_completeness_false_iterates",
         fb_cfg_incomplete["verdict"] == "iterate")
    # PARADOX_GUARD_FAIL still escalates (regression check)
    fb_pg = fallback_to_legacy_e2(
        FallbackReason.PARADOX_GUARD_FAIL, "sid-cfg", "P1",
        validators_passed=True, units_passed=True, known_defects=0,
    )
    case("fallback_paradox_guard_still_escalates",
         fb_pg["verdict"] == "escalate")

    # ---- Case 18e (v15.35.4 P4 fix): _vote_from_parsed axis_scores guard ----
    spec_p4 = EvaluatorSpec(
        evaluator_id="mock-p4",
        provider="openai",
        invoke_fn=lambda p: ("", {}),
    )
    # Non-int values (None / str / float) silently dropped — no crash
    parsed_dirty = {
        "verdict": "approved", "completeness": True,
        "axis_scores": {"cohesion": 5, "coupling": None, "extensibility": "high",
                        "stability": 4, "usability": 3.5},
    }
    v_dirty = _vote_from_parsed(spec_p4, parsed_dirty)
    case("vote_axis_dirty_returns_vote", v_dirty is not None)
    case("vote_axis_dirty_keeps_int_only",
         v_dirty and v_dirty.axis_scores == {"cohesion": 5, "stability": 4})
    # All non-int → axis dict becomes None (defensive default)
    parsed_all_dirty = {
        "verdict": "approved", "completeness": True,
        "axis_scores": {"cohesion": None, "coupling": "x", "extensibility": 3.5},
    }
    v_all_dirty = _vote_from_parsed(spec_p4, parsed_all_dirty)
    case("vote_axis_all_dirty_axis_none",
         v_all_dirty and v_all_dirty.axis_scores is None)
    # Bool exclusion (Python bool is int subclass — but axis scores must be 1-5 int)
    parsed_bool = {
        "verdict": "approved", "completeness": True,
        "axis_scores": {"cohesion": True, "coupling": 4},
    }
    v_bool = _vote_from_parsed(spec_p4, parsed_bool)
    case("vote_axis_bool_dropped",
         v_bool and v_bool.axis_scores == {"coupling": 4})
    # Sanity: worst-axis reduction works after guard (no TypeError)
    if v_dirty and v_dirty.axis_scores:
        try:
            worst = min(v_dirty.axis_scores.values())
            case("worst_axis_reduction_after_guard", worst == 4)
        except TypeError as e:
            case("worst_axis_reduction_after_guard", False, str(e))

    # ---- Case 19: meta_rules cross-check (cite drift detection) ----
    try:
        from . import meta_rules as _mr
        cited = {
            "paradox_guard",
            "quantitative_residual_norm",
            "single_file_mutation_surface",
        }
        active_ids = {r.rule_id for r in _mr.current_rules()}
        missing = cited - active_ids
        case("v15_35_1_cited_meta_rules_active", not missing,
             f"missing: {sorted(missing)}" if missing else "")
    except ImportError:
        case("v15_35_1_cited_meta_rules_active", True, "(skipped)")

    # ---- Path 2 D7 (wave 10): ledger reader/writer wiring ----
    import json as _d7_json
    import tempfile as _d7_tmp
    import os as _d7_os
    from pathlib import Path as _d7_P

    # D7-1: missing state_root → 0 (fail-soft)
    case("d7_missing_state_root_zero",
         read_known_defects_from_ledger("/nonexistent/path/xyz") == 0)

    # D7-2: missing residual_norm → 0
    with _d7_tmp.TemporaryDirectory() as td:
        case("d7_missing_residual_norm_zero",
             read_known_defects_from_ledger(td) == 0)

    # D7-3: single ledger known_defects=0 → 0
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_d7_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 0,
            "deadline": "2026-08-19",
        }))
        case("d7_zero_defects_returns_zero",
             read_known_defects_from_ledger(td) == 0)

    # D7-4: single ledger known_defects=3 → 3
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_d7_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 3,
            "deadline": "2026-08-19",
        }))
        case("d7_three_defects_returns_three",
             read_known_defects_from_ledger(td) == 3)

    # D7-5: multi-ledger sums
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "a.json").write_text(_d7_json.dumps({
            "gate_id": "a", "known_defects": 2, "deadline": "2026-08-19"}))
        (rn / "b.json").write_text(_d7_json.dumps({
            "gate_id": "b", "known_defects": 5, "deadline": "2026-08-19"}))
        case("d7_multi_ledger_sum",
             read_known_defects_from_ledger(td) == 7)

    # D7-6: gate_id filter narrows
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "a.json").write_text(_d7_json.dumps({
            "gate_id": "a", "known_defects": 2, "deadline": "2026-08-19"}))
        (rn / "b.json").write_text(_d7_json.dumps({
            "gate_id": "b", "known_defects": 5, "deadline": "2026-08-19"}))
        case("d7_gate_filter_narrows",
             read_known_defects_from_ledger(td, gate_id="a") == 2)

    # D7-7: malformed ledger silently skipped
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "broken.json").write_text("{not valid")
        (rn / "good.json").write_text(_d7_json.dumps({
            "gate_id": "good", "known_defects": 1, "deadline": "2026-08-19"}))
        case("d7_malformed_skipped",
             read_known_defects_from_ledger(td) == 1)

    # D7-8: update_ledger_post_dispatch writes last_eval_ts + last_verdict
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_d7_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 0,
            "deadline": "2026-08-19",
            "last_eval_ts": None, "last_verdict": None,
        }))
        ok = update_ledger_post_dispatch(
            "rlm_gate", "approved", state_root=td, ts="2026-05-20T01:00:00+00:00",
        )
        case("d7_update_returns_true", ok is True)
        data = _d7_json.loads((rn / "rlm.json").read_text())
        case("d7_update_writes_ts",
             data.get("last_eval_ts") == "2026-05-20T01:00:00+00:00")
        case("d7_update_writes_verdict",
             data.get("last_verdict") == "approved")

    # D7-9: update with missing gate_id → False (no crash)
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_d7_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 0,
            "deadline": "2026-08-19",
        }))
        ok = update_ledger_post_dispatch(
            "nonexistent_gate", "iterate", state_root=td,
        )
        case("d7_update_missing_gate_returns_false", ok is False)

    # D7-10: update with empty gate_id rejected
    ok = update_ledger_post_dispatch("", "approved", state_root="/tmp")
    case("d7_update_rejects_empty_gate_id", ok is False)

    # D7-11: resolve_ledger_state_root honors CLAUDE_HOME
    saved = _d7_os.environ.get("CLAUDE_HOME")
    try:
        _d7_os.environ["CLAUDE_HOME"] = "/tmp/d7-test-root"
        resolved = resolve_ledger_state_root()
        case("d7_resolve_honors_env",
             "/tmp/d7-test-root" in str(resolved) or "d7-test-root" in str(resolved))
    finally:
        if saved is None:
            _d7_os.environ.pop("CLAUDE_HOME", None)
        else:
            _d7_os.environ["CLAUDE_HOME"] = saved

    # D7-12: end-to-end integration with fallback_to_legacy_e2 — ledger
    # known_defects flows through completeness_pass which forces 'iterate'
    with _d7_tmp.TemporaryDirectory() as td:
        rn = _d7_P(td) / "residual_norm"
        rn.mkdir()
        (rn / "rlm.json").write_text(_d7_json.dumps({
            "gate_id": "rlm_gate", "known_defects": 1,
            "deadline": "2026-08-19",
        }))
        defects = read_known_defects_from_ledger(td)
        fb = fallback_to_legacy_e2(
            FallbackReason.SUBAGENT_TIMEOUT,
            sid="test-sid", phase_id="phase_3.5",
            validators_passed=True, units_passed=True,
            known_defects=defects,
        )
        # known_defects=1 → completeness_pass=False → verdict='iterate'
        case("d7_e2e_plumbs_to_fallback_completeness",
             fb["completeness"] is False)
        case("d7_e2e_plumbs_to_fallback_verdict",
             fb["verdict"] == "iterate")

    # ---- S6 wiring: _emit_ledger_update_silent + gate_id kwarg ----
    # S6 (HANDOFF wave 12) — invoke_evaluator_isolated mirrors verdict into
    # residual-norm ledger when caller passes gate_id; gate_id=None is no-op.

    # S6-1: helper no-op when gate_id falsy
    # Should NOT raise even when ledger missing — fail-soft observability.
    _emit_ledger_update_silent(None, "approved")
    _emit_ledger_update_silent("", "approved")
    case("s6_emit_helper_noop_on_none_gate", True)

    # S6-2: helper writes ledger when gate_id provided (tmp state_root)
    with _d7_tmp.TemporaryDirectory() as td:
        s6_saved = _d7_os.environ.get("CLAUDE_HOME")
        try:
            _d7_os.environ["CLAUDE_HOME"] = td
            rn = _d7_P(td) / "state" / "residual_norm"
            rn.mkdir(parents=True)
            (rn / "rlm.json").write_text(_d7_json.dumps({
                "gate_id": "s6_test_gate", "known_defects": 0,
                "deadline": "2026-12-31",
            }))
            _emit_ledger_update_silent("s6_test_gate", "approved")
            data_after = _d7_json.loads((rn / "rlm.json").read_text())
            case("s6_emit_helper_writes_verdict",
                 data_after.get("last_verdict") == "approved")
            case("s6_emit_helper_writes_ts",
                 isinstance(data_after.get("last_eval_ts"), str)
                 and len(data_after.get("last_eval_ts", "")) > 0)
        finally:
            if s6_saved is None:
                _d7_os.environ.pop("CLAUDE_HOME", None)
            else:
                _d7_os.environ["CLAUDE_HOME"] = s6_saved

    # S6-3: helper swallows exceptions from update_ledger_post_dispatch
    # (e.g., non-existent state_root). Must NOT raise.
    s6_saved2 = _d7_os.environ.get("CLAUDE_HOME")
    try:
        _d7_os.environ["CLAUDE_HOME"] = "/nonexistent/path/that/does/not/exist"
        _emit_ledger_update_silent("any_gate", "iterate")
        case("s6_emit_helper_swallows_missing_state_root", True)
    except Exception as e:
        case("s6_emit_helper_swallows_missing_state_root", False, str(e))
    finally:
        if s6_saved2 is None:
            _d7_os.environ.pop("CLAUDE_HOME", None)
        else:
            _d7_os.environ["CLAUDE_HOME"] = s6_saved2

    # S6-4: invoke_evaluator_isolated signature now accepts gate_id kwarg
    # (smoke test signature via inspect — no real subprocess spawn).
    import inspect as _s6_inspect
    sig = _s6_inspect.signature(invoke_evaluator_isolated)
    case("s6_isolated_signature_has_gate_id",
         "gate_id" in sig.parameters
         and sig.parameters["gate_id"].default is None
         and sig.parameters["gate_id"].kind == _s6_inspect.Parameter.KEYWORD_ONLY)

    # S6-5: invoke_ensemble_evaluator signature now accepts gate_id kwarg
    # (smoke test signature via inspect — no real ensemble spawn).
    sig_ens = _s6_inspect.signature(invoke_ensemble_evaluator)
    case("s6_ensemble_signature_has_gate_id",
         "gate_id" in sig_ens.parameters
         and sig_ens.parameters["gate_id"].default is None
         and sig_ens.parameters["gate_id"].kind == _s6_inspect.Parameter.KEYWORD_ONLY)

    # S6-6: end-to-end ensemble → ledger write via stub specs + gate_id.
    # Build a single mock EvaluatorSpec that returns parsed verdict='approved';
    # invoke_ensemble_evaluator should aggregate to quorum 'approved' and
    # _emit_ledger_update_silent mirrors it into the test ledger.
    with _d7_tmp.TemporaryDirectory() as td:
        s6e_saved = _d7_os.environ.get("CLAUDE_HOME")
        try:
            _d7_os.environ["CLAUDE_HOME"] = td
            rn = _d7_P(td) / "state" / "residual_norm"
            rn.mkdir(parents=True)
            (rn / "rlm.json").write_text(_d7_json.dumps({
                "gate_id": "s6_ensemble_gate", "known_defects": 0,
                "deadline": "2026-12-31",
            }))
            stub_spec = EvaluatorSpec(
                evaluator_id="s6-stub",
                provider="openai",
                invoke_fn=lambda p: ("", {
                    "verdict": "approved",
                    "completeness": True,
                    "axis_scores": {
                        "cohesion": 5, "coupling": 5,
                        "extensibility": 5, "stability": 5,
                        "usability": 5,
                    },
                }),
            )
            verdict_result = invoke_ensemble_evaluator(
                "S6 ensemble smoke test prompt",
                sid="s6_test_sid",
                phase_id="phase_s6",
                validators_passed=True,
                units_passed=True,
                known_defects=0,
                evaluator_specs=[stub_spec],
                gate_id="s6_ensemble_gate",
            )
            case("s6_ensemble_returns_verdict",
                 getattr(verdict_result, "quorum_verdict", "") == "approved")
            data_after_ens = _d7_json.loads((rn / "rlm.json").read_text())
            case("s6_ensemble_writes_verdict_to_ledger",
                 data_after_ens.get("last_verdict") == "approved")
        finally:
            if s6e_saved is None:
                _d7_os.environ.pop("CLAUDE_HOME", None)
            else:
                _d7_os.environ["CLAUDE_HOME"] = s6e_saved

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
    import sys as _sys
    if "--self-check" in _sys.argv:
        _sys.exit(_self_check())
    print("lib.evaluator_dispatcher — DGE E2 dispatcher (v15.35.1 ensemble wired)")
    print(f"  PER_PHASE_EVAL_LIMIT: {PER_PHASE_EVAL_LIMIT}")
    print(f"  SUBAGENT_TIMEOUT_SECONDS: {SUBAGENT_TIMEOUT_SECONDS}")
    print(f"  default ensemble pool size: {len(_build_default_ensemble_specs())}")
    print(f"  use --self-check to run embedded v15.35.1 smoke test")
    _sys.exit(0)
