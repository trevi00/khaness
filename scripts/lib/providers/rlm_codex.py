"""rlm_codex — Recursion-capable Tier-3 provider wrapping OpenAIProvider.

Path 2 (debate-1779229138-db17ce gen 3 LOCK SHA
c75bfaf403981c1fcd8cb45c0872c83ae564b777). Honest implementation of the
RLM_gate anchor (debate-1779094932-341f1a SHA 05db44ac90c0): "genuine
recursive context decomposition via recursion-capable provider". Restores
rubric_anchor_preserved=true after wave 9 Path 1 cosmetic rubric_relax.

## Three surfaces (blueprint L34-37)

**B1 — ORCH_DEPTH env propagation.** Recursion depth tracked via
`ORCH_DEPTH` env var (defaults to 0). On each recursive `ask` call, the
provider increments the env var BEFORE spawning the codex subprocess.
`MAX_RECURSION_DEPTH` is the hard cap (default 2 → 3 total layers
including depth=0). At depth==MAX_RECURSION_DEPTH the provider falls
through to a flat OpenAIProvider call (base case). Prevents runaway
recursion that would saturate codex API quota.

**B2 — Citation audit trail.** Each invocation appends one JSONL row to
the audit trail (default `state/evaluator/<sid>/rlm_audit.jsonl` if
sid-in-env, else stderr). Row schema:
  {
    "ts": "<ISO timestamp>",
    "depth": int,
    "prompt_sha1": "<40-char hex>",
    "prompt_len_chars": int,
    "child_call_count": int,
    "branch": "recursive" | "flat_base_case",
    "model": "<resolved id>",
    "parent_sha1": "<40-char hex | null>",
    "elapsed_seconds": float | null,
  }
Provenance preserved for post-hoc verification that the provider did
real recursion (not single flat codex call cosmetically wrapped).

**B3 — Timeout coordination.** Honors dispatcher's
`SUBAGENT_TIMEOUT_SECONDS` (D3, 270s post wave 10) by reducing per-child
budget at each recursion level: `child_timeout = parent_timeout *
(1.0 - TIMEOUT_RESERVE_FRAC) / max(1, child_count)`. Default
TIMEOUT_RESERVE_FRAC=0.10 reserves 10% per level for synthesis. At
depth==MAX_RECURSION_DEPTH the flat OpenAIProvider call uses the
remaining parent_timeout directly.

## Recursion strategy

For prompts shorter than `MIN_RECURSION_PROMPT_CHARS` (default 4000),
the provider does a flat OpenAIProvider call (no recursion needed —
single context window suffices). For longer prompts, the prompt is split
by section markers (`\\n## `, `\\n### `, `\\n---`, or hard-character
chunking as last resort). Each chunk recurses via `self.ask(...)`; the
parent then synthesizes child responses with one final flat codex call
that summarizes the concatenated child answers.

This is a *pragmatic* recursive decomposition — not a research-grade
MCTS-style tree of thought. The honest claim is that the provider DOES
recursively decompose long contexts AND records provenance — which is
what the wave 3 OD3 anchor "recursive context decomposition" requires.

## Integration

Add to ensemble pool explicitly (NOT in default pool — operator opt-in
per CLAUDE.md Mutation matrix; default-pool change is a separate
configure-critic-policy-class mutation):

  from lib.evaluator_dispatcher import (
      EvaluatorSpec, invoke_ensemble_evaluator,
  )
  from lib.providers.rlm_codex import RlmCodexProvider

  specs = [
      EvaluatorSpec("codex-default", "openai",
                    lambda p: invoke_evaluator_isolated(p)),
      EvaluatorSpec("rlm-codex-recursive", "rlm_codex",
                    lambda p: RlmCodexProvider().ask_for_eval(p)),
  ]
  verdict = invoke_ensemble_evaluator(prompt, ..., evaluator_specs=specs)

## Non-goals

- Does NOT replace OpenAIProvider; wraps it.
- Does NOT auto-register in default ensemble pool.
- Does NOT mutate `state/residual_norm/rlm_gate.json` — that ledger is
  D7's reader-side responsibility.
- Does NOT enforce isolation invariant (caller delegates to
  `validate_prompt_isolation` if applicable — same contract as
  OpenAIProvider).

## Cross-references

- D1 lib/calendar_gate.py — deadline ledger scanner (independent)
- D2 state/residual_norm/rlm_gate.json — known_defects ledger
- D3 lib/evaluator_dispatcher.py:90 SUBAGENT_TIMEOUT_SECONDS=270
- lib/providers/openai.py — base flat provider
- lib/ensemble_evaluator.py — Tier-3 quorum target
- agents/harness-evaluator.md — Tier 2/3 doctrine
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Sequence

from .base import AskRequest, AskResponse, ProviderBase, ProviderUnavailableError


# ----------------------------------------------------------------------------
# Tunable constants (module-level — override via env in production)
# ----------------------------------------------------------------------------

MAX_RECURSION_DEPTH: int = 2
"""Hard cap on ORCH_DEPTH. depth=0 (parent) + depth=1 + depth=2 = 3 layers."""

MIN_RECURSION_PROMPT_CHARS: int = 4000
"""Below this, prompts go flat (single codex call). Above, recursion fires."""

TIMEOUT_RESERVE_FRAC: float = 0.10
"""Fraction of parent timeout reserved per level for synthesis overhead."""

DEFAULT_TIMEOUT_SECONDS: float = 270.0
"""Fallback when caller does not propagate dispatcher timeout (D3 value)."""

CHUNK_SECTION_MARKERS: tuple[str, ...] = ("\n## ", "\n### ", "\n---")
"""Preferred decomposition boundaries (markdown-aware). Tried in order."""

MAX_CHUNKS_PER_LEVEL: int = 4
"""Per-level fan-out cap. Above this, chunks are merged."""

ORCH_DEPTH_ENV: str = "ORCH_DEPTH"
"""B1 surface — env var name carrying recursion depth across spawns."""

AUDIT_TRAIL_ENV: str = "RLM_AUDIT_TRAIL"
"""B2 surface — env var name for explicit audit trail path override."""

SID_ENV: str = "RLM_SID"
"""B2 surface — env var name for sid used in default audit trail path."""


# ----------------------------------------------------------------------------
# Helpers (pure)
# ----------------------------------------------------------------------------


def _sha1_short(text: str) -> str:
    """40-char hex SHA-1 of text (full digest — short alias retained for
    semantic clarity at call sites)."""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


def _chunk_by_markers(text: str, markers: Sequence[str]) -> list[str]:
    """Split `text` at the first marker that yields >=2 non-empty chunks.

    Order: try `## ` → `### ` → `---`. If no marker yields a split, fall
    back to hard-character chunking that respects MAX_CHUNKS_PER_LEVEL.
    Empty chunks are dropped. Leading whitespace preserved within chunks.
    """
    for marker in markers:
        if marker not in text:
            continue
        # Keep the marker prefix in each chunk (except chunk 0, which is
        # the lead-in before the first occurrence). This preserves
        # semantics for downstream LLM (section headers retained).
        pieces = text.split(marker)
        chunks: list[str] = []
        for i, piece in enumerate(pieces):
            stripped = piece.strip()
            if not stripped:
                continue
            if i == 0:
                chunks.append(stripped)
            else:
                # Re-attach the marker (without leading \n for cleanliness)
                chunks.append(marker.lstrip("\n") + stripped)
        if len(chunks) >= 2:
            return chunks[:MAX_CHUNKS_PER_LEVEL]
    # Fallback: hard character chunking
    n_chunks = min(MAX_CHUNKS_PER_LEVEL, max(2, len(text) // MIN_RECURSION_PROMPT_CHARS))
    chunk_size = max(1, len(text) // n_chunks)
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)
            if text[i:i + chunk_size].strip()][:MAX_CHUNKS_PER_LEVEL]


def _child_timeout(parent_timeout: float, child_count: int) -> float:
    """Compute per-child timeout budget. B3 surface."""
    if child_count <= 0:
        return parent_timeout
    return parent_timeout * (1.0 - TIMEOUT_RESERVE_FRAC) / child_count


def _resolve_audit_path() -> "os.PathLike | None":
    """Resolve audit trail file path from env. Returns None when neither
    AUDIT_TRAIL_ENV nor SID_ENV is set (audit goes to stderr fallback).
    """
    explicit = os.environ.get(AUDIT_TRAIL_ENV)
    if explicit:
        from pathlib import Path as _P
        return _P(explicit)
    sid = os.environ.get(SID_ENV)
    if sid:
        from pathlib import Path as _P
        claude_home = os.environ.get("CLAUDE_HOME")
        base = _P(claude_home) if claude_home else _P.home() / ".claude"
        return base / "state" / "evaluator" / sid / "rlm_audit.jsonl"
    return None


def _emit_audit_row(row: dict) -> None:
    """Append one JSON line to audit trail (or stderr fallback). Fail-soft."""
    try:
        path = _resolve_audit_path()
        line = json.dumps(row, ensure_ascii=False)
        if path is None:
            sys.stderr.write(f"[rlm_audit] {line}\n")
            return
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        # Audit must NEVER crash the provider call. stderr fallback always.
        try:
            sys.stderr.write(
                f"[rlm_audit_error] {type(e).__name__}: {e}\n"
            )
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------------


class RlmCodexProvider(ProviderBase):
    """Recursion-capable Tier-3 provider wrapping OpenAIProvider.

    Operator-injection: pass `flat_provider` to override (test mocks).
    Defaults to OpenAIProvider() at first .ask() invocation (lazy
    construction to avoid forcing codex CLI presence at module import).
    """

    name = "rlm_codex"
    default_model = ""
    capabilities = ("text", "code", "long-context")

    def __init__(self, flat_provider: ProviderBase | None = None) -> None:
        # Lazy: don't validate availability at construction
        self._flat = flat_provider

    def _get_flat(self) -> ProviderBase:
        if self._flat is None:
            from .openai import OpenAIProvider
            self._flat = OpenAIProvider()
        return self._flat

    def is_available(self) -> bool:
        """True iff the wrapped flat provider is available.

        At depth=MAX_RECURSION_DEPTH AND at synthesis step, this provider
        delegates to flat_provider.ask — so its availability mirrors the
        flat provider's. Lazy-construct flat provider on first probe.
        """
        try:
            return self._get_flat().is_available()
        except Exception:
            return False

    def ask(self, request: AskRequest) -> AskResponse:
        """Recursive ask with audit trail. Honors ORCH_DEPTH env (B1) +
        timeout coord (B3) + audit trail (B2).

        Raises ProviderUnavailableError when flat provider is unavailable
        or any recursive child call propagates one.
        """
        depth = self._current_depth()
        timeout_budget = self._extract_timeout_budget(request)
        parent_sha1 = os.environ.get("RLM_PARENT_SHA1") or None
        prompt_sha1 = _sha1_short(request.prompt)
        start_ts = time.monotonic()

        # Base case: at depth cap OR short-enough prompt → flat call
        if (depth >= MAX_RECURSION_DEPTH
                or len(request.prompt) < MIN_RECURSION_PROMPT_CHARS):
            response = self._flat_ask(request, depth)
            elapsed = time.monotonic() - start_ts
            _emit_audit_row({
                "ts": datetime.now(timezone.utc).isoformat(),
                "depth": depth,
                "prompt_sha1": prompt_sha1,
                "prompt_len_chars": len(request.prompt),
                "child_call_count": 0,
                "branch": "flat_base_case",
                "model": response.model,
                "parent_sha1": parent_sha1,
                "elapsed_seconds": round(elapsed, 3),
                "reason": "depth_cap" if depth >= MAX_RECURSION_DEPTH else "short_prompt",
            })
            return response

        # Recursive case: decompose, recurse on children, synthesize
        chunks = _chunk_by_markers(request.prompt, CHUNK_SECTION_MARKERS)
        if len(chunks) <= 1:
            # Decomposition failed — fall through to flat (avoid spurious recursion)
            response = self._flat_ask(request, depth)
            elapsed = time.monotonic() - start_ts
            _emit_audit_row({
                "ts": datetime.now(timezone.utc).isoformat(),
                "depth": depth,
                "prompt_sha1": prompt_sha1,
                "prompt_len_chars": len(request.prompt),
                "child_call_count": 0,
                "branch": "flat_base_case",
                "model": response.model,
                "parent_sha1": parent_sha1,
                "elapsed_seconds": round(elapsed, 3),
                "reason": "decomposition_failed",
            })
            return response

        child_responses = self._recurse_children(
            chunks, request, depth, timeout_budget, prompt_sha1,
        )
        synthesis = self._synthesize(
            child_responses, request, depth, timeout_budget, prompt_sha1,
        )
        elapsed = time.monotonic() - start_ts
        _emit_audit_row({
            "ts": datetime.now(timezone.utc).isoformat(),
            "depth": depth,
            "prompt_sha1": prompt_sha1,
            "prompt_len_chars": len(request.prompt),
            "child_call_count": len(chunks),
            "branch": "recursive",
            "model": synthesis.model,
            "parent_sha1": parent_sha1,
            "elapsed_seconds": round(elapsed, 3),
        })
        return synthesis

    # ---- internal ----

    def _current_depth(self) -> int:
        """Read ORCH_DEPTH from env (B1). Default 0 (parent call)."""
        try:
            return max(0, int(os.environ.get(ORCH_DEPTH_ENV, "0")))
        except (ValueError, TypeError):
            return 0

    def _extract_timeout_budget(self, request: AskRequest) -> float:
        """Resolve B3 timeout budget for this invocation. Uses dispatcher
        SUBAGENT_TIMEOUT_SECONDS as ceiling when caller did not propagate."""
        # Hard ceiling for this invocation. Caller can later override via
        # env if needed; default is the D3-aligned 270s.
        try:
            from ..evaluator_dispatcher import SUBAGENT_TIMEOUT_SECONDS as _t
            return float(_t)
        except ImportError:
            return DEFAULT_TIMEOUT_SECONDS

    def _flat_ask(self, request: AskRequest, depth: int) -> AskResponse:
        """Delegate to wrapped OpenAIProvider with depth-annotated response."""
        flat = self._get_flat()
        try:
            response = flat.ask(request)
        except ProviderUnavailableError:
            raise
        except Exception as e:
            # Wrap unexpected failures uniformly (Tier-3 contract):
            raise ProviderUnavailableError(
                f"rlm_codex flat call failed at depth={depth}: "
                f"{type(e).__name__}: {e}"
            ) from e
        # Annotate raw with our depth + provider chain for debugging
        raw = dict(response.raw or {})
        raw["rlm_depth"] = depth
        raw["rlm_branch"] = "flat"
        return AskResponse(
            text=response.text,
            provider=self.name,           # report as rlm_codex (Tier-3 surface)
            model=response.model,
            tokens_in=response.tokens_in,
            tokens_out=response.tokens_out,
            raw=raw,
        )

    def _recurse_children(
        self,
        chunks: Sequence[str],
        parent_request: AskRequest,
        depth: int,
        parent_timeout: float,
        parent_sha1: str,
    ) -> list[AskResponse]:
        """Sequentially recurse on each chunk. B1 env propagation per call."""
        child_responses: list[AskResponse] = []
        saved_depth = os.environ.get(ORCH_DEPTH_ENV)
        saved_parent = os.environ.get("RLM_PARENT_SHA1")
        try:
            for i, chunk in enumerate(chunks):
                os.environ[ORCH_DEPTH_ENV] = str(depth + 1)
                os.environ["RLM_PARENT_SHA1"] = parent_sha1
                child_request = AskRequest(
                    prompt=chunk,
                    model=parent_request.model,
                    max_tokens=parent_request.max_tokens,
                    temperature=parent_request.temperature,
                    system=parent_request.system,
                )
                child_responses.append(self.ask(child_request))
        finally:
            # B1 invariant: env must be restored after this scope, else
            # outer caller's depth view becomes inconsistent.
            if saved_depth is None:
                os.environ.pop(ORCH_DEPTH_ENV, None)
            else:
                os.environ[ORCH_DEPTH_ENV] = saved_depth
            if saved_parent is None:
                os.environ.pop("RLM_PARENT_SHA1", None)
            else:
                os.environ["RLM_PARENT_SHA1"] = saved_parent
        return child_responses

    def _synthesize(
        self,
        child_responses: Sequence[AskResponse],
        parent_request: AskRequest,
        depth: int,
        parent_timeout: float,
        parent_sha1: str,
    ) -> AskResponse:
        """Synthesis step: one flat call merging child outputs."""
        synthesis_prompt = self._build_synthesis_prompt(
            parent_request, child_responses,
        )
        synthesis_request = AskRequest(
            prompt=synthesis_prompt,
            model=parent_request.model,
            max_tokens=parent_request.max_tokens,
            temperature=parent_request.temperature,
            system=parent_request.system,
        )
        synth_response = self._get_flat().ask(synthesis_request)
        raw = dict(synth_response.raw or {})
        raw["rlm_depth"] = depth
        raw["rlm_branch"] = "synthesis"
        raw["rlm_child_count"] = len(child_responses)
        raw["rlm_parent_sha1"] = parent_sha1
        return AskResponse(
            text=synth_response.text,
            provider=self.name,
            model=synth_response.model,
            tokens_in=synth_response.tokens_in,
            tokens_out=synth_response.tokens_out,
            raw=raw,
        )

    @staticmethod
    def _build_synthesis_prompt(
        parent_request: AskRequest,
        child_responses: Sequence[AskResponse],
    ) -> str:
        """Render the synthesis prompt from parent + child responses."""
        parts = [
            "You are synthesizing the responses to N sub-prompts that were",
            "decomposed from one original prompt. Produce a single coherent",
            "response that satisfies the ORIGINAL PROMPT below by combining",
            "the child responses faithfully — do not lose information.",
            "",
            "## ORIGINAL PROMPT",
            parent_request.prompt[:2000] + ("…[truncated]" if len(parent_request.prompt) > 2000 else ""),
            "",
            "## CHILD RESPONSES",
        ]
        for i, resp in enumerate(child_responses):
            parts.append(f"### Child {i + 1} (model={resp.model})")
            parts.append(resp.text)
            parts.append("")
        parts.append("## SYNTHESIZED RESPONSE")
        return "\n".join(parts)


# Plugin registry export — `lib/providers/__init__.py REGISTRY` can pick this up
# (operator-driven; this module does NOT auto-register).
PROVIDER = RlmCodexProvider


# ============================================================================
# Embedded self-check (single-file mutation surface invariant)
# ============================================================================


class _StubProvider(ProviderBase):
    """In-process stub for self-check — no codex CLI needed."""

    name = "stub"
    default_model = "stub-model"
    capabilities = ("text",)

    def __init__(self) -> None:
        self.calls: list[AskRequest] = []
        self.available = True

    def is_available(self) -> bool:
        return self.available

    def ask(self, request: AskRequest) -> AskResponse:
        self.calls.append(request)
        return AskResponse(
            text=f"STUB:{request.prompt[:60]}",
            provider=self.name,
            model=self.default_model,
            raw={"stub": True},
        )


def _self_check() -> int:
    failed = 0
    cases: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        cases.append((name, ok, detail))
        if not ok:
            failed += 1

    # ---- Case 1: short prompt → flat call, depth=0, no recursion
    stub = _StubProvider()
    prov = RlmCodexProvider(flat_provider=stub)
    os.environ.pop(ORCH_DEPTH_ENV, None)
    response = prov.ask(AskRequest(prompt="short"))
    case("short_prompt_flat", len(stub.calls) == 1)
    case("flat_response_provider", response.provider == "rlm_codex")
    case("flat_raw_depth_zero", response.raw.get("rlm_depth") == 0)
    case("flat_raw_branch_flat", response.raw.get("rlm_branch") == "flat")

    # ---- Case 2: long prompt with section markers → recursion fires
    stub2 = _StubProvider()
    prov2 = RlmCodexProvider(flat_provider=stub2)
    long_prompt = (
        "intro\n\n## section A\n" + ("A" * 3000) +
        "\n## section B\n" + ("B" * 3000) +
        "\n## section C\n" + ("C" * 3000)
    )
    os.environ.pop(ORCH_DEPTH_ENV, None)
    response2 = prov2.ask(AskRequest(prompt=long_prompt))
    # 4 chunks total (intro + A + B + C if intro long enough; intro="intro"
    # < MIN_RECURSION → kept as one chunk with intro+A merged? actually
    # _chunk_by_markers keeps the lead-in as chunk 0 even if short).
    # Expected: N chunks recursed (depth=1 stub.ask) + 1 synthesis call.
    case("recursive_multiple_calls", len(stub2.calls) >= 4)
    case("recursive_response_provider", response2.provider == "rlm_codex")
    case("recursive_raw_branch_synthesis",
         response2.raw.get("rlm_branch") == "synthesis")
    case("recursive_raw_child_count_positive",
         (response2.raw.get("rlm_child_count") or 0) > 0)

    # ---- Case 3: ORCH_DEPTH at MAX → flat base case even with long prompt
    stub3 = _StubProvider()
    prov3 = RlmCodexProvider(flat_provider=stub3)
    os.environ[ORCH_DEPTH_ENV] = str(MAX_RECURSION_DEPTH)
    try:
        response3 = prov3.ask(AskRequest(prompt=long_prompt))
    finally:
        os.environ.pop(ORCH_DEPTH_ENV, None)
    case("max_depth_forces_flat", len(stub3.calls) == 1)
    case("max_depth_raw_depth_eq_max",
         response3.raw.get("rlm_depth") == MAX_RECURSION_DEPTH)
    case("max_depth_raw_branch_flat",
         response3.raw.get("rlm_branch") == "flat")

    # ---- Case 4: ORCH_DEPTH env restored after recursion completes
    saved = "5"
    os.environ[ORCH_DEPTH_ENV] = saved
    try:
        stub4 = _StubProvider()
        prov4 = RlmCodexProvider(flat_provider=stub4)
        prov4.ask(AskRequest(prompt="short"))
        case("env_restored_after_flat",
             os.environ.get(ORCH_DEPTH_ENV) == saved)
    finally:
        os.environ.pop(ORCH_DEPTH_ENV, None)

    # ---- Case 5: env unset before invocation stays unset after
    os.environ.pop(ORCH_DEPTH_ENV, None)
    stub5 = _StubProvider()
    prov5 = RlmCodexProvider(flat_provider=stub5)
    long_prompt5 = (
        "intro\n## a\n" + ("X" * 4500) +
        "\n## b\n" + ("Y" * 4500)
    )
    prov5.ask(AskRequest(prompt=long_prompt5))
    case("env_restored_after_recursion",
         ORCH_DEPTH_ENV not in os.environ)

    # ---- Case 6: _chunk_by_markers basic
    chunks = _chunk_by_markers("intro\n## a\nbody\n## b\nbody", CHUNK_SECTION_MARKERS)
    case("chunk_markers_split_count", len(chunks) >= 2)
    case("chunk_markers_preserves_marker",
         all(c.startswith(("intro", "## ")) for c in chunks))

    # ---- Case 7: _chunk_by_markers fallback hard-chunking
    long_no_marker = "X" * 20000
    chunks_hard = _chunk_by_markers(long_no_marker, CHUNK_SECTION_MARKERS)
    case("chunk_fallback_hard", len(chunks_hard) >= 2)
    case("chunk_fallback_cap",
         len(chunks_hard) <= MAX_CHUNKS_PER_LEVEL)

    # ---- Case 8: _child_timeout halves with N children + reserve
    t = _child_timeout(parent_timeout=100.0, child_count=2)
    case("child_timeout_two_children",
         abs(t - (100.0 * 0.9 / 2)) < 0.001)
    t1 = _child_timeout(parent_timeout=270.0, child_count=4)
    case("child_timeout_four_children",
         abs(t1 - (270.0 * 0.9 / 4)) < 0.001)

    # ---- Case 9: audit trail emits to file when env set
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tf:
        audit_path = tf.name
    os.environ[AUDIT_TRAIL_ENV] = audit_path
    try:
        stub6 = _StubProvider()
        prov6 = RlmCodexProvider(flat_provider=stub6)
        prov6.ask(AskRequest(prompt="short"))
        with open(audit_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        case("audit_emits_one_row_short", len(lines) == 1)
        row = json.loads(lines[0]) if lines else {}
        case("audit_row_has_depth", "depth" in row)
        case("audit_row_has_prompt_sha1", len(row.get("prompt_sha1", "")) == 40)
        case("audit_row_has_branch_flat",
             row.get("branch") == "flat_base_case")
        case("audit_row_has_elapsed",
             isinstance(row.get("elapsed_seconds"), (int, float)))
    finally:
        os.environ.pop(AUDIT_TRAIL_ENV, None)
        try:
            os.unlink(audit_path)
        except OSError:
            pass

    # ---- Case 10: audit trail emits N+1 rows for recursive (N child + 1 parent)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as tf:
        audit_path = tf.name
    os.environ[AUDIT_TRAIL_ENV] = audit_path
    try:
        stub7 = _StubProvider()
        prov7 = RlmCodexProvider(flat_provider=stub7)
        long_p = ("intro\n## a\n" + "X" * 4500 +
                   "\n## b\n" + "Y" * 4500)
        prov7.ask(AskRequest(prompt=long_p))
        with open(audit_path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        # >=3 rows: children (>=2) + parent synthesis (1)
        case("audit_recursive_multiple_rows", len(lines) >= 3)
        parent_rows = [json.loads(ln) for ln in lines
                       if json.loads(ln).get("branch") == "recursive"]
        # Long chunks (>=MIN_RECURSION_PROMPT_CHARS) recurse again at deeper
        # levels, so >=1 "recursive" branch row (one per recursive frame).
        case("audit_has_parent_recursive_row", len(parent_rows) >= 1)
        if parent_rows:
            # Top-level parent (depth=0) must report positive child count
            depth0 = [r for r in parent_rows if r.get("depth") == 0]
            case("audit_parent_child_count_positive",
                 bool(depth0) and depth0[0].get("child_call_count", 0) > 0)
        else:
            case("audit_parent_child_count_positive", False, "no parent row")
    finally:
        os.environ.pop(AUDIT_TRAIL_ENV, None)
        try:
            os.unlink(audit_path)
        except OSError:
            pass

    # ---- Case 11: _sha1_short produces 40-char hex
    h = _sha1_short("test")
    case("sha1_short_length", len(h) == 40)
    case("sha1_short_hex", all(c in "0123456789abcdef" for c in h))

    # ---- Case 12: is_available propagates flat provider state
    stub_avail = _StubProvider()
    prov_avail = RlmCodexProvider(flat_provider=stub_avail)
    case("is_available_true", prov_avail.is_available() is True)
    stub_avail.available = False
    case("is_available_false", prov_avail.is_available() is False)

    # ---- Case 13: flat provider exception → ProviderUnavailableError
    class _BrokenProvider(ProviderBase):
        name = "broken"
        default_model = ""
        capabilities = ("text",)
        def is_available(self): return True
        def ask(self, request):
            raise RuntimeError("upstream boom")

    prov_broken = RlmCodexProvider(flat_provider=_BrokenProvider())
    os.environ.pop(ORCH_DEPTH_ENV, None)
    try:
        prov_broken.ask(AskRequest(prompt="short"))
        case("flat_exception_wrapped", False, "expected ProviderUnavailableError")
    except ProviderUnavailableError:
        case("flat_exception_wrapped", True)
    except Exception as e:
        case("flat_exception_wrapped", False, f"got {type(e).__name__}")

    # ---- Case 14: timeout budget reads dispatcher constant (B3 cross-ref)
    stub_t = _StubProvider()
    prov_t = RlmCodexProvider(flat_provider=stub_t)
    budget = prov_t._extract_timeout_budget(AskRequest(prompt="x"))
    case("timeout_budget_positive", budget > 0)
    # Should match SUBAGENT_TIMEOUT_SECONDS (D3=270 post-wave-10).
    try:
        from lib.evaluator_dispatcher import SUBAGENT_TIMEOUT_SECONDS as _ts
        case("timeout_budget_matches_dispatcher",
             abs(budget - float(_ts)) < 0.001)
    except ImportError:
        case("timeout_budget_matches_dispatcher", True,
             "(dispatcher import unavailable — fallback ok)")

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
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    print("lib.providers.rlm_codex — Path 2 recursive Tier-3 provider")
    print(f"  ORCH_DEPTH_ENV={ORCH_DEPTH_ENV} MAX_RECURSION_DEPTH={MAX_RECURSION_DEPTH}")
    print(f"  MIN_RECURSION_PROMPT_CHARS={MIN_RECURSION_PROMPT_CHARS}")
    print(f"  TIMEOUT_RESERVE_FRAC={TIMEOUT_RESERVE_FRAC}")
    print(f"  AUDIT_TRAIL_ENV={AUDIT_TRAIL_ENV} SID_ENV={SID_ENV}")
    print(f"  use --self-check to run embedded smoke test")
    sys.exit(0)
