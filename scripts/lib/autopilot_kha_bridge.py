"""autopilot_kha_bridge — kha↔harness composition bridge helpers (Wave 15).

Source: debate-1779314852-338b28 converged path (4-LOCK byte-identical
gen2→gen3 sha1 dc809a9257f23c472212ce55d426fdccb039624b).

Implements the producer-side machinery for the bridge from
``/harness-autopilot`` Phase 1 routing into ``kha-executor`` dispatch:

  - D4 dual-emit: when autopilot dispatches a kha-phase, write one
    ``bridge.dispatch`` event to the canonical debate event stream
    (``state/debates/<orch_sid>/events.jsonl`` via EventStore) AND one
    phase-lifecycle event to the orchestrator sibling stream
    (``state/orchestrator/<orch_sid>/phase_events.jsonl`` via
    append_phase_event). EventStore is source-of-truth for replay; the
    phase-events stream is a derived projection for precondition probes
    (per gen-3 condition S1 — precedence rule documented in caller doc).

  - D7+D7a continuation: build a ``<completed_tasks>`` table from
    ``git log --grep='({phase}-{plan})'`` matching kha-executor's
    commit format (``{type}({phase}-{plan}): <task>`` per
    agents/kha-executor.md:370-375). Output matches the CHECKPOINT
    format at agents/kha-executor.md:281-313 so kha-executor's
    ``<continuation_handling>`` (kha-executor.md:315-323) consumes it
    without translation.

  - D7a orphan detection: ``≥1 commit matching plan token`` AND
    ``SUMMARY.md absent`` → fail-closed escalation via advisory_ack
    (``aborted_kha_plan_validator_fail``) plus phase_event
    (``status='escalated'``, ``reason='orphan_commits_no_summary'``).

This module is the producer surface; the actual dispatch site lives in
``commands/harness-autopilot.md`` Phase 1.a (D3 ``--kha-phase`` route).

Public API:
  - ``BridgeDispatch`` dataclass (immutable record of one dispatch)
  - ``emit_bridge_dispatch(orch_sid, gen, phase, plan, mode)`` →
    EventStore.append + append_phase_event, returns BridgeDispatch
  - ``build_completed_tasks_table(repo_root, phase, plan)`` → markdown
    table str (empty if no matching commits)
  - ``detect_orphan_and_escalate(repo_root, phase, plan, orch_sid)`` →
    True if orphan condition fired (advisory acked + phase event written)

NOT covered here (intentionally): the CLI parse of ``--kha-phase X.Y``
(lives in commands/harness-autopilot.md) and the ralph pre-check
(``aborted_kha_plan_validator_fail`` site is the *caller* of
engine.ralph, NOT engine/ralph.py per gen-3 condition B1).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .advisory_ack import resolve as resolve_advisory
from .event_store import EventStore
from .phase_events import append_phase_event


# Mode discriminator for bridge dispatches.
BridgeMode = Literal["bare", "wrapped"]


@dataclass(frozen=True)
class BridgeDispatch:
    """Single bridge dispatch event — immutable record returned to caller."""

    orch_sid: str
    gen: int
    phase: str
    plan: str
    mode: BridgeMode
    phase_event_id: str  # synthesized "kha-{phase}-{plan}"


def _phase_event_id(phase: str, plan: str) -> str:
    return f"kha-{phase}-{plan}"


def emit_bridge_dispatch(
    orch_sid: str,
    gen: int,
    phase: str,
    plan: str,
    mode: BridgeMode = "wrapped",
) -> BridgeDispatch:
    """Dual-emit bridge dispatch: EventStore + phase_events.

    Source-of-truth precedence (gen-3 condition S1): EventStore is
    canonical for replay (immutable, schema-fixed, hash-stamped).
    phase_events is a derived projection — readers MUST treat EventStore
    as authoritative when streams disagree.

    Returns the BridgeDispatch record for caller forensics. Raises if
    EventStore append fails (no silent loss on the canonical stream);
    phase_events failure is fail-soft (returns False; caller observes
    the absence via reader probe but EventStore retains truth).
    """
    if not orch_sid:
        raise ValueError("orch_sid must be non-empty")
    if not phase:
        raise ValueError("phase must be non-empty")
    if not plan:
        raise ValueError("plan must be non-empty")
    if mode not in ("bare", "wrapped"):
        raise ValueError(f"mode must be 'bare' or 'wrapped', got {mode!r}")

    payload = {
        "kha_phase": phase,
        "kha_plan": plan,
        "mode": mode,
        "bridge_contract_version": "1",
    }
    # Canonical: write to debates/<sid>/events.jsonl. Raises on I/O fail
    # via jsonl_append (no fail-soft for source-of-truth).
    EventStore(orch_sid).append("bridge.dispatch", gen, "kha-bridge", payload)

    # Derived projection: phase lifecycle started. Fail-soft per
    # phase_events contract (oversize / I/O failure returns False).
    pe_id = _phase_event_id(phase, plan)
    append_phase_event(orch_sid, pe_id, "started", f"kha-bridge mode={mode}")

    return BridgeDispatch(
        orch_sid=orch_sid,
        gen=gen,
        phase=phase,
        plan=plan,
        mode=mode,
        phase_event_id=pe_id,
    )


# kha-executor commit subject format per agents/kha-executor.md:370-375:
#   "{type}({phase}-{plan}): {concise task description}"
# Types per agents/kha-executor.md:352-358: feat | fix | test | refactor | chore.
_COMMIT_SUBJECT_RE = re.compile(
    r"^(?P<hash>[0-9a-f]{7,40})\s+"
    r"(?P<type>feat|fix|test|refactor|chore)"
    r"\((?P<phase>[^)\-]+)-(?P<plan>[^)]+)\):\s+"
    r"(?P<desc>.+?)$"
)


def _git(repo_root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


@dataclass(frozen=True)
class CompletedTask:
    sha: str
    type_: str
    phase: str
    plan: str
    desc: str


def list_plan_commits(
    repo_root: Path, phase: str, plan: str
) -> list[CompletedTask]:
    """Return kha-executor commits matching (phase, plan), oldest first.

    Uses ``git log --grep='({phase}-{plan})' --pretty=oneline --reverse``
    which matches commit subjects emitted by kha-executor.md:370-375.
    Returns empty list on no matches OR git failure.
    """
    rc, out = _git(
        repo_root,
        "log",
        "--all",
        f"--grep=({phase}-{plan})",
        "--fixed-strings",
        "--pretty=format:%h %s",
        "--reverse",
    )
    if rc != 0:
        return []

    tasks: list[CompletedTask] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _COMMIT_SUBJECT_RE.match(line)
        if not m:
            continue
        if m.group("phase") != phase or m.group("plan") != plan:
            continue
        tasks.append(
            CompletedTask(
                sha=m.group("hash"),
                type_=m.group("type"),
                phase=m.group("phase"),
                plan=m.group("plan"),
                desc=m.group("desc"),
            )
        )
    return tasks


def build_completed_tasks_table(
    repo_root: Path, phase: str, plan: str
) -> str:
    """Build the ``Completed Tasks`` markdown table for kha-executor.

    Output shape matches agents/kha-executor.md:281-313 CHECKPOINT
    format (4-column table: Task | Name | Commit | Files). Files column
    is left as ``-`` (per-commit file enumeration would require an extra
    git pass; CHECKPOINT format permits abbreviated entries when files
    have not been tracked).

    Returns empty string when there are no matching commits — caller
    decides whether to treat as "fresh plan" or "orphan" (the latter
    requires SUMMARY.md absence too, see detect_orphan_and_escalate).
    """
    tasks = list_plan_commits(repo_root, phase, plan)
    if not tasks:
        return ""
    lines = [
        "### Completed Tasks",
        "",
        "| Task | Name | Commit | Files |",
        "| ---- | ---- | ------ | ----- |",
    ]
    for i, t in enumerate(tasks, start=1):
        lines.append(f"| {i} | {t.desc} | {t.sha} | - |")
    return "\n".join(lines) + "\n"


def _find_summary_md(
    repo_root: Path, phase: str, plan: str
) -> Path | None:
    """Locate ``{phase}-{plan}-SUMMARY.md`` under .planning/phases/.

    kha-executor writes ``{phase}-{plan}-SUMMARY.md`` at
    ``.planning/phases/XX-name/`` (kha-executor.md:385). Phase dir name
    is not canonical — glob for any phase dir containing the file.
    Returns None when absent.
    """
    planning = repo_root / ".planning" / "phases"
    if not planning.exists():
        return None
    needle = f"{phase}-{plan}-SUMMARY.md"
    for path in planning.glob(f"*/{needle}"):
        return path
    return None


def detect_orphan_and_escalate(
    repo_root: Path,
    phase: str,
    plan: str,
    orch_sid: str,
) -> bool:
    """Detect orphan-commits state and escalate via advisory + phase event.

    Orphan = ≥1 commit matching ({phase}-{plan}) AND SUMMARY.md absent.
    On orphan:
      1. ack ``aborted_kha_plan_validator_fail`` with key
         ``{orch_sid}:{phase}:{plan}:orphan``
      2. append phase event status=escalated reason=orphan_commits_no_summary

    Returns True iff orphan condition fired (caller should HALT iteration
    and surface advisory to user). Returns False when:
      - no commits matching the plan token (fresh plan, normal dispatch)
      - SUMMARY.md present (clean completion, normal continuation)
    """
    tasks = list_plan_commits(repo_root, phase, plan)
    if not tasks:
        return False
    summary = _find_summary_md(repo_root, phase, plan)
    if summary is not None:
        return False

    # Orphan condition confirmed.
    key = f"{orch_sid}:{phase}:{plan}:orphan"
    resolve_advisory("aborted_kha_plan_validator_fail").ack(key)
    append_phase_event(
        orch_sid,
        _phase_event_id(phase, plan),
        "escalated",
        "orphan_commits_no_summary",
    )
    return True
