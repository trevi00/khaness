"""team_policy — deterministic stall-detect / quorum-guarded kill / frozen-N aggregate (M28).

Replaces the PROSE in `commands/harness-team.md` §5 "Monitor" (and the stall
clause in §"Error handling") — the markdown told an LLM orchestrator to "poll
worker-<i>.out tail", "flag flat heartbeat ≥120s", and decide whether to kill a
stalled worker by eyeballing liveness. Prose loop-control is skippable and the
kill decision was unguarded (could kill the team below quorum). This module makes
the three decisions deterministic + pure; `cli.team_policy_check` is the consumer
that owns the IO (read artifacts, terminate, append the single events.jsonl line).

The four converged decisions (debate-1781614063-b713e7 gen 2, LOCK sha1
6712249b2537c460725f5d75dee825fb8164bb97):

  D1 evaluate_stall  — PRIMARY progress = growth in worker-<i>.out byte-count OR
     heartbeat.jsonl out_bytes (the standalone-active artifacts). mailbox_depth is
     supplementary (OR, never sole). pane-hash corroborates only (may VETO a stall
     = tighten, never trigger one = never loosen, never sole). Combine with AND:
     stalled ⇔ alive AND every live progress signal flat AND elapsed ≥ stall_seconds.
     Watermark persists last_progress_ts UNCHANGED on flat cycles; rewritten only on
     observed growth. read error / None / missing → never kill (status='unknown').

  D2 should_kill     — guard on responded_count (final answers in hand), NOT
     alive_count. Kill ⇔ (responded_count + survivor_capacity_after_this_kill) ≥
     frozen_quorum_threshold; else skip_below_quorum (→ operator escalation). Pure;
     the caller performs the idempotent terminate_worker.

  D3 aggregate_quorum — denominator FROZEN at the initial N (persisted by the CLI),
     never the surviving count, so killing workers can't lower the bar. Reuses
     ensemble_evaluator.quorum_threshold + replicates its tally/tie branch (NOT
     aggregate(), which validates a provider pool, and NOT tally_verdicts(), which
     requires EvaluatorVote objects — team results are free-form labels). split /
     unreachable → escalate.

All three are pure: evaluate_stall takes an injected `read_fn` (returning a
WorkerSignals struct) + injectable watermark IO, so the logic is testable with
fakes and never touches a real psmux session or disk during unit tests.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lib.ensemble_evaluator import quorum_threshold


DEFAULT_STALL_SECONDS: float = 180.0
_TERMINAL_MARKER: str = "DONE"


# ============================================================================
# D1 — stall detection
# ============================================================================


@dataclass(frozen=True)
class WorkerSignals:
    """Live progress signals for one worker, produced by an injected read_fn.

    `out_bytes` / `heartbeat_out_bytes` are the two views of the PRIMARY signal
    (byte count of worker-<i>.out — the .out file size directly, and the last
    `out_bytes` field emitted into worker-<i>.heartbeat.jsonl). `mailbox_depth`
    is the SUPPLEMENTARY signal (OR-combined, never sole). `pane_hash` is the
    CORROBORATION signal (may veto a stall, never trigger one). `alive` is the
    AND-gate: a completed worker (terminal DONE marker / dead session) is not a
    kill target. Any field may be None when its source is unreadable/absent;
    `alive=None` means liveness is indeterminate → fail-closed 'unknown'.
    """
    out_bytes: int | None = None
    heartbeat_out_bytes: int | None = None
    mailbox_depth: int | None = None
    pane_hash: str | None = None
    alive: bool | None = None


@dataclass(frozen=True)
class StallResult:
    status: str                 # 'progressing' | 'stalled' | 'unknown'
    worker_id: str
    elapsed: float | None
    last_progress_ts: float | None
    grew: bool
    reason: str


def _primary_progress(sig: WorkerSignals) -> int | None:
    """The PRIMARY progress scalar: max of the two .out-size views (both monotonic)."""
    vals = [v for v in (sig.out_bytes, sig.heartbeat_out_bytes) if isinstance(v, int)]
    return max(vals) if vals else None


def _grew(prev: int | None, cur: int | None) -> bool:
    """PRIMARY growth: a new non-None value, or a strict increase over baseline."""
    if cur is None:
        return False
    return prev is None or cur > prev


def _changed(prev, cur) -> bool:
    """SUPPLEMENTARY / CORROBORATION change: any non-None value != baseline."""
    return cur is not None and cur != prev


def _decide_stall(
    worker_id: str,
    prior_wm: dict | None,
    signals: WorkerSignals | None,
    now: float,
    stall_seconds: float,
) -> tuple[StallResult, dict | None]:
    """Pure stall decision. Returns (result, new_watermark).

    new_watermark is None when the watermark must stay UNCHANGED — i.e. fail-closed
    ('unknown') OR a flat cycle (the spec: "persists last_progress_ts UNCHANGED on
    flat cycles; rewrite only on observed growth"). A non-None dict is written by the
    caller (first-observation baseline, or a growth advance).
    """
    if signals is None or signals.alive is None:
        why = "read returned None" if signals is None else "aliveness indeterminate"
        return (
            StallResult("unknown", worker_id, None, None, False,
                        f"{why} -> fail-closed (never kill)"),
            None,
        )

    alive = bool(signals.alive)
    cur_primary = _primary_progress(signals)
    cur_supp = signals.mailbox_depth
    cur_pane = signals.pane_hash

    if prior_wm is None:
        # First observation — establish baseline; cannot judge a stall yet.
        baseline = {"last_progress_ts": now, "primary": cur_primary,
                    "supp": cur_supp, "pane": cur_pane}
        return (
            StallResult("progressing", worker_id, 0.0, now, False,
                        "first observation -> baseline established"),
            baseline,
        )

    last_ts = prior_wm.get("last_progress_ts")
    if not isinstance(last_ts, (int, float)):
        last_ts = now  # malformed watermark -> reset clock defensively
    prev_primary = prior_wm.get("primary")
    prev_supp = prior_wm.get("supp")
    prev_pane = prior_wm.get("pane")

    primary_grew = _grew(prev_primary, cur_primary)
    supp_changed = _changed(prev_supp, cur_supp)        # supplementary: OR, resets clock
    pane_changed = _changed(prev_pane, cur_pane)        # corroboration: veto only

    progressed = primary_grew or supp_changed
    elapsed = now - (now if progressed else last_ts)    # 0 on progress, else age of baseline

    if progressed:
        advanced = {"last_progress_ts": now, "primary": cur_primary,
                    "supp": cur_supp, "pane": cur_pane}
        return (
            StallResult("progressing", worker_id, 0.0, now, True,
                        "observed growth (primary grew or mailbox changed) -> clock reset"),
            advanced,
        )

    # Flat cycle — watermark NOT rewritten (last_progress_ts frozen at last growth).
    if not alive:
        return (
            StallResult("progressing", worker_id, elapsed, last_ts, False,
                        "flat but worker not alive (terminal/completed) -> not a kill target"),
            None,
        )
    if elapsed >= stall_seconds:
        if pane_changed:
            # Pane corroborates liveness — VETO the stall (tighten, never loosen).
            # Pane is never sole: it does NOT reset last_progress_ts.
            return (
                StallResult("progressing", worker_id, elapsed, last_ts, False,
                            f"flat {elapsed:.0f}s but pane-hash changed -> stall vetoed "
                            f"(corroboration; clock not reset)"),
                None,
            )
        return (
            StallResult("stalled", worker_id, elapsed, last_ts, False,
                        f"alive AND all live progress flat for {elapsed:.0f}s "
                        f">= {stall_seconds:.0f}s"),
            None,
        )
    return (
        StallResult("progressing", worker_id, elapsed, last_ts, False,
                    f"flat {elapsed:.0f}s < {stall_seconds:.0f}s (not yet stalled)"),
        None,
    )


def evaluate_stall(
    team_sid: str,
    worker_id: str,
    now: float,
    *,
    stall_seconds: float = DEFAULT_STALL_SECONDS,
    read_fn: Callable[[str, str], WorkerSignals | None],
    read_watermark: Callable[[str, str], dict | None] | None = None,
    write_watermark: Callable[[str, str, dict], None] | None = None,
) -> StallResult:
    """Decide whether `worker_id` is stalled (D1). Pure given injected IO.

    `read_fn(team_sid, worker_id) -> WorkerSignals | None` supplies live signals;
    raising or returning None → fail-closed 'unknown' (never a kill target). The
    watermark IO defaults to a STATE_DIR-backed JSON sidecar but is injectable for
    tests. The watermark is rewritten only on first-observation or observed growth.
    """
    if read_watermark is None or write_watermark is None:
        store = _FileWatermarkStore()
        read_watermark = read_watermark or store.read
        write_watermark = write_watermark or store.write

    try:
        signals = read_fn(team_sid, worker_id)
    except Exception as exc:  # noqa: BLE001 — fail-closed: a read fault never kills
        return StallResult("unknown", worker_id, None, None, False,
                           f"read_fn raised {type(exc).__name__} -> fail-closed (never kill)")

    try:
        prior = read_watermark(team_sid, worker_id)
    except Exception:  # noqa: BLE001
        prior = None

    result, new_wm = _decide_stall(worker_id, prior, signals, float(now), float(stall_seconds))
    if new_wm is not None:
        try:
            write_watermark(team_sid, worker_id, new_wm)
        except Exception:  # noqa: BLE001 — watermark write best-effort
            pass
    return result


class _FileWatermarkStore:
    """STATE_DIR/team/<sid>/stall-watermark/<worker_id>.json default watermark IO."""

    def _path(self, team_sid: str, worker_id: str) -> Path:
        from lib.paths import STATE_DIR, ensure_dir
        d = ensure_dir(STATE_DIR / "team" / team_sid / "stall-watermark")
        safe = "".join(c for c in worker_id if c.isalnum() or c in "._-") or "worker"
        return d / f"{safe}.json"

    def read(self, team_sid: str, worker_id: str) -> dict | None:
        p = self._path(team_sid, worker_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def write(self, team_sid: str, worker_id: str, wm: dict) -> None:
        from lib.atomic_json import write_json_atomic
        write_json_atomic(str(self._path(team_sid, worker_id)), wm)


# ============================================================================
# D2 — quorum-guarded kill decision
# ============================================================================


@dataclass(frozen=True)
class KillDecision:
    kill: bool
    action: str                 # 'kill' | 'skip_below_quorum'
    responded_count: int
    survivor_capacity: int
    reachable_after_kill: int
    threshold: int
    reason: str


def should_kill(
    team_sid: str,
    stalled_worker_id: str,
    *,
    responded_count: int,
    frozen_quorum_threshold: int,
    survivor_capacity: int,
) -> KillDecision:
    """Decide whether killing a stalled worker keeps quorum reachable (D2). Pure.

    Guard is on `responded_count` (final answers already in hand) NOT alive_count —
    a live-but-silent worker that may never finish must not prop up the quorum math.
    `survivor_capacity` is the count of OTHER still-viable workers remaining AFTER
    this kill (the caller decrements it as it kills multiple workers in one pass).

    Kill ⇔ responded_count + survivor_capacity ≥ frozen_quorum_threshold. Otherwise
    skip_below_quorum: killing would make quorum unreachable, so the worker is kept
    and the caller escalates to the operator instead of silently dropping below the
    floor. terminate_worker itself is performed by the caller (idempotent).
    """
    reachable = int(responded_count) + int(survivor_capacity)
    threshold = int(frozen_quorum_threshold)
    if reachable >= threshold:
        return KillDecision(
            kill=True, action="kill", responded_count=int(responded_count),
            survivor_capacity=int(survivor_capacity), reachable_after_kill=reachable,
            threshold=threshold,
            reason=(f"quorum still reachable after kill: responded({responded_count}) + "
                    f"survivors({survivor_capacity}) = {reachable} >= threshold({threshold})"),
        )
    return KillDecision(
        kill=False, action="skip_below_quorum", responded_count=int(responded_count),
        survivor_capacity=int(survivor_capacity), reachable_after_kill=reachable,
        threshold=threshold,
        reason=(f"killing would break quorum: responded({responded_count}) + "
                f"survivors({survivor_capacity}) = {reachable} < threshold({threshold}) "
                f"-> escalate to operator (keep worker)"),
    )


# ============================================================================
# D3 — frozen-denominator quorum aggregation
# ============================================================================


@dataclass(frozen=True)
class QuorumResult:
    verdict: str                # winning label, or 'escalate'
    status: str                 # 'quorum' | 'split' | 'unreachable'
    winning_label: str | None
    winning_count: int
    threshold: int
    frozen_denominator: int
    responded: int
    counts: dict[str, int]
    reason: str


def _normalize_labels(results) -> list[str]:
    """Coerce free-form team results into verdict-label strings. Skips malformed."""
    labels: list[str] = []
    for r in results or []:
        if isinstance(r, str) and r:
            labels.append(r)
        elif isinstance(r, dict) and isinstance(r.get("verdict"), str) and r["verdict"]:
            labels.append(r["verdict"])
    return labels


def aggregate_quorum(results, *, frozen_denominator: int) -> QuorumResult:
    """Aggregate worker results into a quorum verdict against the FROZEN N (D3).

    threshold = ⌈frozen_denominator / 2⌉ (ensemble_evaluator.quorum_threshold) — the
    denominator is the INITIAL team size, never the surviving count, so killing a
    worker can never lower the bar. Replicates ensemble_evaluator's tally/tie branch
    on free-form labels (team verdicts are not EvaluatorVote objects, so neither
    aggregate() nor tally_verdicts() apply). Returns 'escalate' on a split (tie or no
    majority) or when quorum is unreachable (fewer responses than threshold).
    """
    threshold = quorum_threshold(frozen_denominator) if int(frozen_denominator) > 0 else 1
    labels = _normalize_labels(results)
    counts: dict[str, int] = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    responded = len(labels)

    if responded == 0:
        return QuorumResult("escalate", "unreachable", None, 0, threshold,
                            int(frozen_denominator), 0, counts,
                            "no results -> quorum unreachable")

    max_count = max(counts.values())
    winners = sorted(k for k, v in counts.items() if v == max_count)
    tie = len(winners) > 1

    if responded < threshold:
        return QuorumResult("escalate", "unreachable", None, max_count, threshold,
                            int(frozen_denominator), responded, counts,
                            f"responded({responded}) < threshold({threshold}) on frozen "
                            f"N={frozen_denominator} -> quorum unreachable")
    if tie or max_count < threshold:
        reason = (f"tie at count={max_count} across {winners} (threshold={threshold})"
                  if tie else
                  f"max_count={max_count} < threshold={threshold} (label={winners[0]!r})")
        return QuorumResult("escalate", "split", None, max_count, threshold,
                            int(frozen_denominator), responded, counts, reason)

    return QuorumResult(winners[0], "quorum", winners[0], max_count, threshold,
                        int(frozen_denominator), responded, counts,
                        f"{winners[0]!r} reached {max_count} >= threshold({threshold})")


# ============================================================================
# Pass orchestration (pure) — consumed by cli.team_policy_check
# ============================================================================


@dataclass(frozen=True)
class WorkerAssessment:
    worker_id: str
    status: str                 # mirror of StallResult.status
    responded: bool
    alive: bool | None
    reason: str


@dataclass(frozen=True)
class PassAction:
    worker_id: str
    action: str                 # 'kill' | 'escalate'
    reason: str


@dataclass(frozen=True)
class PassDecision:
    actions: tuple[PassAction, ...]
    exit_code: int
    frozen_n: int
    threshold: int
    responded_count: int
    stalled_count: int
    unknown_count: int
    summary: str


# Exit-code contract (mirrors the CLI):
EXIT_NOOP = 0          # nothing stalled / all progressing or terminal
EXIT_ACTED = 3         # killed >=1 stalled worker, quorum still reachable
EXIT_SKIPPED = 4       # fail-closed: unknown worker(s), deferred for safety
EXIT_ESCALATE = 5      # a stalled worker is load-bearing for quorum -> halt
EXIT_ERROR = 2         # argparse / internal (CLI only)


def decide_pass(
    team_sid: str,
    assessments: list[WorkerAssessment],
    *,
    frozen_n: int,
    already_killed: set[str] | None = None,
) -> PassDecision:
    """Pure single-pass policy decision over all workers' assessments (D2 driver).

    Processes stalled workers in deterministic worker_id order, applying the D2
    quorum guard with a survivor_capacity that decrements as workers are killed.
    The first skip_below_quorum halts further kills (we are at the quorum floor) and
    yields EXIT_ESCALATE. Exit-code precedence: escalate(5) > acted(3) > skipped(4) >
    noop(0).
    """
    already_killed = already_killed or set()
    threshold = quorum_threshold(frozen_n) if int(frozen_n) > 0 else 1

    live = [a for a in assessments if a.worker_id not in already_killed]
    responded_count = sum(1 for a in live if a.responded)
    unknown_count = sum(1 for a in live if a.status == "unknown")
    stalled = sorted((a for a in live if a.status == "stalled"),
                     key=lambda a: a.worker_id)

    # Viable = alive AND not-responded AND not-already-killed (includes stalled-alive
    # workers until they are killed this pass).
    viable: set[str] = {a.worker_id for a in live if a.alive and not a.responded}

    actions: list[PassAction] = []
    killed: set[str] = set()
    escalated = False
    for a in stalled:
        w = a.worker_id
        survivor_capacity = len(viable - {w} - killed)
        dec = should_kill(team_sid, w, responded_count=responded_count,
                           frozen_quorum_threshold=threshold,
                           survivor_capacity=survivor_capacity)
        if dec.kill:
            actions.append(PassAction(w, "kill", dec.reason))
            killed.add(w)
            viable.discard(w)
        else:
            actions.append(PassAction(w, "escalate", dec.reason))
            escalated = True
            break

    if escalated:
        code = EXIT_ESCALATE
    elif killed:
        code = EXIT_ACTED
    elif unknown_count:
        code = EXIT_SKIPPED
    else:
        code = EXIT_NOOP

    summary = (f"workers={len(live)} responded={responded_count} stalled={len(stalled)} "
               f"unknown={unknown_count} killed={len(killed)} "
               f"escalated={escalated} threshold={threshold} frozen_n={frozen_n}")
    return PassDecision(
        actions=tuple(actions), exit_code=code, frozen_n=int(frozen_n),
        threshold=threshold, responded_count=responded_count,
        stalled_count=len(stalled), unknown_count=unknown_count, summary=summary,
    )


# ============================================================================
# Default file-based read_fn (used by the CLI; injectable in tests)
# ============================================================================


def _read_heartbeat_out_bytes(path: Path) -> int | None:
    """Last (max) `out_bytes` field across worker-<i>.heartbeat.jsonl lines."""
    if not path.exists():
        return None
    best: int | None = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                v = obj.get("out_bytes")
                if isinstance(v, int):
                    best = v if best is None else max(best, v)
    except OSError:
        return None
    return best


def has_terminal_marker(out_text: str) -> bool:
    """True iff worker-<i>.out carries the run-worker.sh terminal `DONE` line."""
    if not out_text:
        return False
    return any(line.strip() == _TERMINAL_MARKER for line in out_text.splitlines())


def make_file_read_fn(
    team_dir,
    *,
    alive_fn: Callable[[str, str], bool] | None = None,
    mailbox_depth_fn: Callable[[str, str], int | None] | None = None,
    capture_pane_fn: Callable[[str, str], str | None] | None = None,
) -> Callable[[str, str], WorkerSignals | None]:
    """Build a read_fn over the real worker artifacts under `team_dir`.

    Reads `<team_dir>/<worker_id>.out` (size = primary), `<worker_id>.heartbeat.jsonl`
    (last out_bytes), optional mailbox depth (supplementary) and pane capture
    (corroboration). Aliveness: a live psmux session (autopilot) → True; else a
    terminal DONE marker → False; else an existing .out with no marker (standalone
    running) → True; else indeterminate → None.
    """
    base = Path(team_dir)

    def read_fn(team_sid: str, worker_id: str) -> WorkerSignals | None:
        out_path = base / f"{worker_id}.out"
        hb_path = base / f"{worker_id}.heartbeat.jsonl"
        out_exists = out_path.exists()

        out_bytes: int | None = None
        if out_exists:
            try:
                out_bytes = out_path.stat().st_size
            except OSError:
                out_bytes = None

        out_text = ""
        if out_exists:
            try:
                out_text = out_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                out_text = ""

        hb_bytes = _read_heartbeat_out_bytes(hb_path)

        mbox: int | None = None
        if mailbox_depth_fn is not None:
            try:
                mbox = mailbox_depth_fn(team_sid, worker_id)
            except Exception:  # noqa: BLE001
                mbox = None

        pane_hash: str | None = None
        if capture_pane_fn is not None:
            try:
                pane = capture_pane_fn(team_sid, worker_id)
                if pane:
                    pane_hash = hashlib.sha1(pane.encode("utf-8", "replace")).hexdigest()[:12]
            except Exception:  # noqa: BLE001
                pane_hash = None

        # Aliveness derivation.
        alive: bool | None
        psmux_alive = False
        if alive_fn is not None:
            try:
                psmux_alive = bool(alive_fn(team_sid, worker_id))
            except Exception:  # noqa: BLE001
                psmux_alive = False
        if psmux_alive:
            alive = True
        elif has_terminal_marker(out_text):
            alive = False
        elif out_exists:
            alive = True
        else:
            alive = None

        # Fail-closed: nothing readable at all -> unknown signals.
        if out_bytes is None and hb_bytes is None and mbox is None and not out_exists:
            return WorkerSignals(alive=None)

        return WorkerSignals(out_bytes=out_bytes, heartbeat_out_bytes=hb_bytes,
                             mailbox_depth=mbox, pane_hash=pane_hash, alive=alive)

    return read_fn
