"""evidence_fabrication detector (v15.10 D1, debate-1778946602-jj7vxk).

Two arms — neither involves an LLM grader (judge_generator_separation):

  Arm (a) — 1-shot file referential integrity:
    For every envelope.evidence[i].file_path X, if os.stat(X) raises
    FileNotFoundError, verdict = fabrication_confirmed immediately.

  Arm (b) — N=2 test_result replay:
    For every envelope.evidence[i] where test_result == 'passed' AND
    replay_cmd is non-empty, run the cmd via subprocess up to TWO times
    with REPLAY_BACKOFF_SEC between attempts.
      - both attempts returncode != 0 → fabrication_confirmed
      - first attempt rc != 0, second attempt rc == 0 → flake_observed
        (telemetry only, NOT a trip — circuit breaker stays calm)
      - first attempt rc == 0 → clean (no second attempt needed)

  Composition rule:
    arm (a) > arm (b). Any single fabrication_confirmed in arm (a) short-
    circuits the whole envelope. arm (b) is run only if arm (a) passes.

  Verdict precedence within arm (b):
    fabrication_confirmed > flake_observed > clean.

The detector is intentionally tolerant of malformed envelopes — missing
keys, non-list evidence, non-string file_path all degrade to `clean`. The
philosophy is "loud on confirmed fabrication, silent on shape weirdness"
because shape errors are schema_violation territory (lib.validators.structural).

Side effects:
  - Calls os.stat() (one stat per evidence entry with a file_path).
  - Calls subprocess.run() (up to 2 invocations per evidence entry with a
    replay_cmd; respects optional `cwd` and `timeout` from the entry).
  - Calls time.sleep(REPLAY_BACKOFF_SEC) between arm (b) attempts.

NO writes, NO network, NO mutation of the envelope.

Module return contract (lock):
  detect(envelope: dict) -> EvidenceVerdict
"""
from __future__ import annotations

import os
import subprocess
import time
from enum import Enum
from typing import Any, Iterable

from ..replay.constants import REPLAY_BACKOFF_SEC


class EvidenceVerdict(str, Enum):
    """Tri-state outcome of evidence_fabrication detection.

    str-Enum so JSONL telemetry can serialize the value directly. Order
    is precedence (clean < flake_observed < fabrication_confirmed).
    """

    CLEAN = "clean"
    FLAKE_OBSERVED = "flake_observed"
    FABRICATION_CONFIRMED = "fabrication_confirmed"


_DEFAULT_REPLAY_TIMEOUT_SEC: float = 30.0


def _iter_evidence(envelope: Any) -> Iterable[dict]:
    """Yield evidence dicts; silently skip if envelope shape is malformed.

    Accepts both {'evidence': [...]} and {'envelope': {'evidence': [...]}}
    because subagent JSON has converged on the inner shape but a few
    callers still pass the outer wrapper.
    """
    if not isinstance(envelope, dict):
        return
    candidates = envelope.get("evidence")
    if candidates is None:
        inner = envelope.get("envelope")
        if isinstance(inner, dict):
            candidates = inner.get("evidence")
    if not isinstance(candidates, list):
        return
    for item in candidates:
        if isinstance(item, dict):
            yield item


def _file_path_missing(entry: dict) -> bool:
    """Arm (a) — True iff entry.file_path is a non-empty str and os.stat raises FileNotFoundError."""
    fp = entry.get("file_path")
    if not isinstance(fp, str) or not fp:
        return False
    try:
        os.stat(fp)
    except FileNotFoundError:
        return True
    except OSError:
        # Permission errors, invalid encoding, etc. are NOT fabrication —
        # they belong to a different failure mode (tool_misuse / env).
        return False
    return False


def _replay_once(cmd, cwd, timeout: float) -> int:
    """Single replay attempt — returns subprocess returncode.

    Any exception (FileNotFoundError on cmd[0], TimeoutExpired, OSError)
    is mapped to a non-zero rc so the caller treats it as a failed
    attempt rather than a Python crash.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return int(proc.returncode)
    except subprocess.TimeoutExpired:
        return 124  # POSIX `timeout` convention
    except (FileNotFoundError, OSError):
        return 127  # shell "command not found" convention


def _classify_replay(entry: dict) -> EvidenceVerdict:
    """Arm (b) — replay a claimed 'passed' test up to N=2 times.

    Returns CLEAN if entry has no replay_cmd, or test_result is not
    'passed', or the first attempt succeeds.
    """
    if entry.get("test_result") != "passed":
        return EvidenceVerdict.CLEAN

    cmd = entry.get("replay_cmd")
    if not cmd or not isinstance(cmd, (list, tuple)):
        return EvidenceVerdict.CLEAN
    cmd_list = [str(x) for x in cmd]
    if not cmd_list:
        return EvidenceVerdict.CLEAN

    cwd = entry.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        cwd = None
    timeout_raw = entry.get("timeout", _DEFAULT_REPLAY_TIMEOUT_SEC)
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = _DEFAULT_REPLAY_TIMEOUT_SEC

    first_rc = _replay_once(cmd_list, cwd, timeout)
    if first_rc == 0:
        return EvidenceVerdict.CLEAN

    # First attempt failed — back off then retry once.
    backoff = REPLAY_BACKOFF_SEC
    if backoff and backoff > 0:
        time.sleep(backoff)
    second_rc = _replay_once(cmd_list, cwd, timeout)
    if second_rc == 0:
        # Single-fail → telemetry-only flake, NOT a trip.
        return EvidenceVerdict.FLAKE_OBSERVED
    return EvidenceVerdict.FABRICATION_CONFIRMED


def detect(envelope: Any) -> EvidenceVerdict:
    """Apply arm (a) then arm (b) across all evidence entries.

    Returns the worst-case verdict encountered (precedence:
    fabrication_confirmed > flake_observed > clean).

    Malformed envelope or zero evidence entries → CLEAN. Schema problems
    are intentionally not surfaced here; they belong to the structural
    validator (D2).
    """
    entries = list(_iter_evidence(envelope))
    if not entries:
        return EvidenceVerdict.CLEAN

    # Arm (a) — short-circuit on first missing file_path.
    for entry in entries:
        if _file_path_missing(entry):
            return EvidenceVerdict.FABRICATION_CONFIRMED

    # Arm (b) — escalate up the precedence ladder across all entries.
    worst = EvidenceVerdict.CLEAN
    for entry in entries:
        v = _classify_replay(entry)
        if v == EvidenceVerdict.FABRICATION_CONFIRMED:
            return v
        if v == EvidenceVerdict.FLAKE_OBSERVED and worst == EvidenceVerdict.CLEAN:
            worst = v
    return worst
