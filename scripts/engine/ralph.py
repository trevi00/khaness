"""Verify/fix persistence loop — Ouroboros-inspired, validators-driven.

Parallel in design to engine.debate: stateless orchestrator that records
each iteration to an event store. The caller drives actual LLM fix calls
between iterations (so engine/ stays DIP-clean, no provider imports).

Iteration cycle (managed by caller / commands/harness-ralph.md):
  1. run_validators(names, cwd)  — subprocess each selected validator
  2. check_iteration(i, outcomes, max_iterations) → IterationResult
  3. if result.converged → done
  4. if result.hard_cap  → escalate (report last failing set to user)
  5. else → build_fix_prompt(outcomes) → caller sends to Agent → goto 1

State: $CLAUDE_HOME/state/ralph/<session>/events.jsonl  (mirrors debate)
"""
from __future__ import annotations

import random
import string
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from lib.event_store import EventStore
from lib.paths import STATE_DIR, VALIDATORS_DIR, ensure_dir


RALPH_DIR: Path = STATE_DIR / "ralph"
MAX_ITERATIONS: int = 10


@dataclass(frozen=True)
class ValidatorOutcome:
    name: str
    passed: bool
    output: str          # tail of validator stdout (contains [PASS]/[FAIL] lines)


@dataclass(frozen=True)
class IterationResult:
    iteration: int
    outcomes: tuple[ValidatorOutcome, ...]
    all_passed: bool
    converged: bool
    hard_cap: bool
    next_action: str     # "converge" | "fix" | "escalate"


def new_session_id() -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"ralph-{int(time.time())}-{rand}"


def ralph_store(session_id: str) -> EventStore:
    """Return an EventStore rooted under state/ralph/ instead of state/debates/.

    Reuses the debate EventStore class by swapping its dir/path fields —
    the on-disk format (append-only jsonl) is identical.
    """
    store = EventStore.__new__(EventStore)
    store.session_id = session_id
    store.dir = ensure_dir(RALPH_DIR / session_id)
    store.path = store.dir / "events.jsonl"
    return store


def run_validators(
    validator_names: Iterable[str],
    cwd: str | Path | None = None,
    *,
    timeout_seconds: float = 60.0,
) -> list[ValidatorOutcome]:
    """Run each validator in a fresh subprocess; collect PASS/FAIL per name.

    Validator contract (from scripts/validators/*): writes [PASS]/[FAIL]/[WARN]
    lines to stdout, returncode 0 on success. We count it failed if either
    returncode != 0 OR the output contains '[FAIL]'.
    """
    outcomes: list[ValidatorOutcome] = []
    for name in validator_names:
        script = VALIDATORS_DIR / f"{name}.py"
        if not script.is_file():
            outcomes.append(ValidatorOutcome(
                name=name, passed=False,
                output=f"[FAIL] validator file missing: {script}",
            ))
            continue
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                cwd=str(cwd) if cwd else None,
                capture_output=True, text=True, encoding="utf-8",
                timeout=timeout_seconds,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            has_fail = "[FAIL]" in stdout
            passed = (proc.returncode == 0) and not has_fail
            # M10 (fixplan-meta debate Gen4): preserve stderr so syntax/import
            # tracebacks reach the fix prompt — stdout-only loses crash context.
            combined = stdout + (f"\n--- stderr ---\n{stderr}" if stderr else "")
            outcomes.append(ValidatorOutcome(
                name=name, passed=passed,
                output=combined[-2000:],
            ))
        except subprocess.TimeoutExpired:
            outcomes.append(ValidatorOutcome(
                name=name, passed=False,
                output=f"[FAIL] validator timeout ({timeout_seconds:.0f}s)",
            ))
        except Exception as e:
            outcomes.append(ValidatorOutcome(
                name=name, passed=False,
                output=f"[FAIL] validator exception: {e!r}",
            ))
    return outcomes


def check_iteration(
    iteration: int,
    outcomes: list[ValidatorOutcome],
    *,
    max_iterations: int = MAX_ITERATIONS,
) -> IterationResult:
    """Classify an iteration's outcomes into converge / fix / escalate."""
    all_passed = all(o.passed for o in outcomes) if outcomes else False
    if all_passed:
        return IterationResult(
            iteration=iteration,
            outcomes=tuple(outcomes),
            all_passed=True,
            converged=True,
            hard_cap=False,
            next_action="converge",
        )
    if iteration >= max_iterations:
        return IterationResult(
            iteration=iteration,
            outcomes=tuple(outcomes),
            all_passed=False,
            converged=False,
            hard_cap=True,
            next_action="escalate",
        )
    return IterationResult(
        iteration=iteration,
        outcomes=tuple(outcomes),
        all_passed=False,
        converged=False,
        hard_cap=False,
        next_action="fix",
    )


def build_fix_prompt(outcomes: list[ValidatorOutcome]) -> str:
    """Construct a fix-suggestion prompt from the failing outcomes.

    Caller (harness-ralph command / main agent) sends this to a fix agent
    (executor or debugger), applies edits, then re-runs validators.
    """
    failing = [o for o in outcomes if not o.passed]
    if not failing:
        return "(no failing validators — nothing to fix)"

    lines: list[str] = [
        f"The following {len(failing)} validators reported failures:",
        "",
    ]
    for o in failing:
        lines.append(f"### {o.name}")
        lines.append("```")
        lines.append(o.output[-800:])
        lines.append("```")
        lines.append("")
    lines.append(
        "Analyze each failure, apply MINIMUM-CHANGE fixes "
        "(no unrelated refactor, no test deletion), and re-run validators."
    )
    return "\n".join(lines)


def record_iteration(
    store: EventStore,
    result: IterationResult,
    *,
    fix_prompt: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "iteration": result.iteration,
        "all_passed": result.all_passed,
        "converged": result.converged,
        "hard_cap": result.hard_cap,
        "next_action": result.next_action,
        "outcomes": [
            {"name": o.name, "passed": o.passed, "output_tail": o.output[-500:]}
            for o in result.outcomes
        ],
    }
    if fix_prompt is not None:
        payload["fix_prompt_len"] = len(fix_prompt)
    event = store.append("iteration", result.iteration, "ralph", payload)
    return event


__all__ = [
    "IterationResult",
    "MAX_ITERATIONS",
    "RALPH_DIR",
    "ValidatorOutcome",
    "build_fix_prompt",
    "check_iteration",
    "new_session_id",
    "ralph_store",
    "record_iteration",
    "run_validators",
]
