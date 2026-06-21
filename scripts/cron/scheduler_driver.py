#!/usr/bin/env python3
"""scheduler_driver — cadence driver for the harness cron jobs + GC tasks (M20).

The harness had NO scheduler ("Cron thin — 잡 2개, 스케줄러 없음"): the cron check/run
pairs (l2_promotion + the M29 ledger/pollution/brain_push jobs) had to be run by hand,
and the 6 maintenance GC tasks were amortized one-per-SessionStart (handlers/session/
init.py). This driver is the missing central cadence: ONE deterministic, idempotent,
fail-soft entrypoint an external OS scheduler (Windows Task Scheduler / cron / systemd
timer) calls periodically; it runs each job only when its per-job watermark says the
cadence has elapsed.

The NEVER-AUTO boundary is preserved two ways:
  1. REGISTRATION is file existence only — this script touches NO settings.json/hooks.
     The operator registers it with their OS scheduler (the hand-off); nothing here
     auto-registers.
  2. The token GATE is respected, not bypassed. check_* jobs and GC tasks are auto-OK
     and always run on cadence. A token-gated run_* job (enable-cron-job) fires ONLY if
     the operator has set HARNESS_MUTATION_TOKEN=enable-cron-job in the scheduler's OWN
     environment — a deliberate, env-level opt-in. Without it, run_* jobs are reported
     'gated' and skipped (watermark NOT advanced, so they fire the moment the operator
     opts in). The driver never injects the token itself.

Idempotent: safe to run every minute — a job runs only when (now - last_run) >= cadence.
Fail-soft: a job that raises/fails does NOT block the others; its failure is recorded.

Run manually (auto-OK jobs only, no token):   python -m cron.scheduler_driver
Dry-run (list what is due, run nothing):       python -m cron.scheduler_driver --dry-run
With gated run_* enabled (operator opt-in):    HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.scheduler_driver
Operator OS registration (the hand-off): point Task Scheduler / crontab at the above.

Exit code: 0 (all due jobs ok / nothing due), 1 (>=1 job failed).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

ENABLE_CRON_TOKEN = "enable-cron-job"
TOKEN_ENV = "HARNESS_MUTATION_TOKEN"
_HOUR_MS = 60 * 60 * 1000

# Failure backoff (M-cron D1): a failed job retries after a SHORT interval that doubles
# each consecutive failure, capped at the job's normal cadence — so a transient failure
# is retried in minutes instead of waiting a full 6-24h cadence, while a permanently
# failing job settles at (never worse than) its cadence. min(cadence, ...) clamps it.
_BASE_BACKOFF_H = 0.25            # first retry 15min after a failure
# Run-history retention (D3): time-primary with a line-count safety valve.
_HISTORY_KEEP_DAYS = 30
_HISTORY_MAX_LINES = 5000
# Liveness (D4): warn if no scheduler pass in this many hours. Generous vs the shortest
# (6h) cadence so a laptop asleep overnight is not flagged, but a multi-day gap is.
_LIVENESS_MAX_H = 36
_JOB_TIMEOUT_S = 600             # per-job subprocess timeout (mirrors _default_cron_runner)


@dataclass(frozen=True)
class CronJob:
    name: str
    module: str            # cron.<module> invoked as `python -m`
    cadence_hours: float
    token: str | None      # None = auto-OK; else required HARNESS_MUTATION_TOKEN value


# Cron check/run pairs (M25 l2_promotion + M29 jobs). check_* auto-OK; run_* gated.
CRON_JOBS: tuple[CronJob, ...] = (
    CronJob("l2_promotion_check", "cron.check_l2_promotion", 24, None),
    CronJob("ledger_compaction_check", "cron.check_ledger_compaction", 24, None),
    CronJob("pollution_check", "cron.check_pollution", 6, None),
    CronJob("brain_push_check", "cron.check_brain_push", 12, None),
    CronJob("l2_promotion_run", "cron.run_l2_promotion", 24, ENABLE_CRON_TOKEN),
    CronJob("ledger_compaction_run", "cron.run_ledger_compaction", 24, ENABLE_CRON_TOKEN),
    CronJob("pollution_cleanup_run", "cron.run_pollution_cleanup", 6, ENABLE_CRON_TOKEN),
    CronJob("brain_push_run", "cron.run_brain_push", 12, ENABLE_CRON_TOKEN),
)


def _gc_tasks() -> list[tuple[str, object]]:
    """The 6 maintenance GC tasks (auto-OK), each a no-arg fail-soft callable.

    Built lazily so a missing module never breaks the whole driver at import time —
    each entry is (name, callable); the callable is invoked inside a try/except.
    """
    tasks: list[tuple[str, object]] = []

    def _safe(modname: str, fnname: str, **kw):
        def _call():
            import importlib
            mod = importlib.import_module(modname)
            return getattr(mod, fnname)(**kw)
        return _call

    tasks.append(("autopilot_cleanup", _safe("lib.autopilot_state", "cleanup_terminal_sessions")))
    tasks.append(("writeback_sidecar_gc", _safe("lib.writeback_store", "gc_old_sidecars")))
    tasks.append(("evaluator_axis_gc", _safe("lib.axis_scores_log", "gc_old_axis_scores")))
    tasks.append(("subagent_gc", _safe("lib.subagent_invocation_log", "gc_old_logs")))
    tasks.append(("work_unit_gc", _safe("lib.work_unit_store", "gc_old_work_units")))

    def _graduation_tick():
        import importlib
        graduation = importlib.import_module("lib.graduation")
        validators = importlib.import_module("validators")
        return graduation.run_tracked_scans_and_tick(scan_fn=validators.graduation_scan_drift)
    tasks.append(("graduation_streak_tick", _graduation_tick))
    # D3: GC the scheduler's own run-history (returns lines kept).
    tasks.append(("cron_history_gc", gc_history))
    return tasks


# --------------------------------------------------------------------------
# State (per-job watermark)
# --------------------------------------------------------------------------

def _state_dir() -> Path:
    from lib.paths import STATE_DIR, ensure_dir
    return ensure_dir(STATE_DIR / "cron" / "scheduler")


def _state_path(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "._-") or "job"
    return _state_dir() / f"{safe}.json"


def _read_state(name: str) -> dict:
    p = _state_path(name)
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_ok_status(status: str) -> bool:
    """A status counts as success iff it is 'ok' or an 'ok:<n>' GC result."""
    return status == "ok" or status.startswith("ok:")


def _write_state(name: str, last_run_ts_ms: int, status: str) -> None:
    from lib.atomic_json import write_json_atomic
    prev = _read_state(name)
    # D1: consecutive_failures drives the backoff. Reset on success, increment on
    # failure. Legacy state files (no key) start at 0. The gated-skip path never
    # reaches here, so the counter only accrues from real run attempts.
    cf = 0 if _is_ok_status(status) else int(prev.get("consecutive_failures", 0)) + 1
    write_json_atomic(str(_state_path(name)), {
        "last_run_ts_ms": last_run_ts_ms,
        "last_status": status,
        "run_count": int(prev.get("run_count", 0)) + 1,
        "consecutive_failures": cf,
    })


# --------------------------------------------------------------------------
# Pure cadence decision
# --------------------------------------------------------------------------

def is_due(last_run_ts_ms: int | None, now_ms: int, cadence_hours: float) -> bool:
    """True iff the job has never run OR the cadence has elapsed. Pure. UNCHANGED
    (the backoff path composes this with an effective interval, so existing callers
    and the pinned test_is_due keep their contract)."""
    if not isinstance(last_run_ts_ms, int) or last_run_ts_ms <= 0:
        return True
    return (now_ms - last_run_ts_ms) >= int(cadence_hours * _HOUR_MS)


def effective_interval_hours(cadence_hours: float, consecutive_failures: int) -> float:
    """D1 backoff: the interval until the next attempt. 0 failures → the normal
    cadence; otherwise BASE_BACKOFF doubled per failure, CLAMPED to the cadence (so
    backoff is never longer than the normal schedule). Pure."""
    if consecutive_failures <= 0:
        return cadence_hours
    return min(cadence_hours, _BASE_BACKOFF_H * (2 ** (consecutive_failures - 1)))


def is_due_backoff(last_run_ts_ms: int | None, now_ms: int, cadence_hours: float,
                   consecutive_failures: int) -> bool:
    """Due-check that honors the failure backoff — composes the pure is_due with the
    effective (possibly shortened) interval. Pure."""
    return is_due(last_run_ts_ms, now_ms,
                  effective_interval_hours(cadence_hours, consecutive_failures))


# --------------------------------------------------------------------------
# Pass lock (D2) — prevent overlapping passes (a long pass + a frequent OS trigger)
# --------------------------------------------------------------------------

def _lock_path() -> Path:
    return _state_dir() / ".pass.lock"


def _stale_lock_ms() -> int:
    """Worst-case legitimate pass duration: every cron job + GC task could be due and
    each runs sequentially up to the subprocess timeout. Size the stale window to that
    (+ margin) so a genuinely long pass is NEVER falsely reclaimed mid-run."""
    worst_jobs = len(CRON_JOBS) + 8  # +8 ≈ GC tasks, generous margin
    return worst_jobs * _JOB_TIMEOUT_S * 1000


def _pid_alive(pid: int) -> bool:
    """Best-effort liveness of a PID (to reclaim a CRASHED pass's lock fast instead of
    waiting the full stale window). Any uncertainty → True ('assume alive', rely on the
    stale window) so we never falsely reclaim a live pass's lock. PID reuse only risks
    waiting longer, never a false concurrent run."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False  # process gone → safe to reclaim
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:  # noqa: BLE001 — can't determine → assume alive (safe)
        return True


def _acquire_pass_lock(now_ms: int) -> bool:
    """Try to take the pass lock. Returns False iff another pass is currently running
    (lock fresh AND its PID alive). Reclaims a stale (old) or dead-PID lock. Fail-soft:
    any lock-infra error → proceed (the lock is a best-effort guard, never a blocker)."""
    from lib.atomic_json import write_json_atomic
    p = _lock_path()
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            lock_ts = int(data.get("ts_ms", 0))
            lock_pid = int(data.get("pid", 0))
            fresh = (now_ms - lock_ts) < _stale_lock_ms()
            if fresh and _pid_alive(lock_pid):
                return False  # a live pass holds the lock
    except Exception:  # noqa: BLE001 — unreadable lock → fall through and reclaim
        pass
    try:
        write_json_atomic(str(p), {"pid": os.getpid(), "ts_ms": now_ms})
    except Exception:  # noqa: BLE001
        pass
    return True


def _release_pass_lock() -> None:
    try:
        _lock_path().unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------
# Run history (D3) + heartbeat / liveness (D4)
# --------------------------------------------------------------------------

def _history_path() -> Path:
    return _state_dir() / "history.jsonl"


def _heartbeat_path() -> Path:
    return _state_dir() / "_heartbeat.json"


def _append_history(summary: dict) -> None:
    """Append one pass summary line. Fail-soft (history is advisory)."""
    try:
        rec = {"ts_ms": summary.get("now_ms"), "acted": summary.get("acted"),
               "gated": summary.get("gated"), "failures": summary.get("failures"),
               "jobs": [{"job": r["job"], "status": r["status"]} for r in summary.get("ran", [])]}
        with open(_history_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def gc_history(now_ms: int | None = None) -> int:
    """GC the run-history: keep lines newer than _HISTORY_KEEP_DAYS, then cap at
    _HISTORY_MAX_LINES (time-primary, count is the safety valve). Returns lines kept.
    A registered GC task (auto-OK state write)."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    p = _history_path()
    if not p.exists():
        return 0
    cutoff = now_ms - _HISTORY_KEEP_DAYS * 24 * _HOUR_MS
    kept: list[str] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ts = int(json.loads(line).get("ts_ms", 0))
            except Exception:  # noqa: BLE001 — keep unparseable lines (don't lose data)
                kept.append(line)
                continue
            if ts >= cutoff:
                kept.append(line)
        if len(kept) > _HISTORY_MAX_LINES:
            kept = kept[-_HISTORY_MAX_LINES:]
        tmp = p.with_suffix(".jsonl.tmp")     # atomic replace via temp + os.replace
        tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        tmp.replace(p)
    except Exception:  # noqa: BLE001
        return 0
    return len(kept)


def _write_heartbeat(now_ms: int) -> None:
    from lib.atomic_json import write_json_atomic
    try:
        write_json_atomic(str(_heartbeat_path()), {"last_pass_ts_ms": now_ms})
    except Exception:  # noqa: BLE001
        pass


def liveness_status(now_ms: int | None = None) -> dict:
    """Scheduler liveness from the last-pass heartbeat. {'state': never_run|ok|stale,
    'hours_since': float|None}. 'never_run' (no heartbeat yet) is NOT a warning — it
    just means the scheduler hasn't been registered/run yet (cold start). 'stale' =
    no pass in > _LIVENESS_MAX_H (scheduler down OR machine was off for that long)."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    p = _heartbeat_path()
    if not p.exists():
        return {"state": "never_run", "hours_since": None}
    try:
        last = int(json.loads(p.read_text(encoding="utf-8")).get("last_pass_ts_ms", 0))
    except Exception:  # noqa: BLE001
        return {"state": "never_run", "hours_since": None}
    hours = (now_ms - last) / _HOUR_MS
    return {"state": "stale" if hours > _LIVENESS_MAX_H else "ok",
            "hours_since": round(hours, 1)}


def cron_health(now_ms: int | None = None) -> dict:
    """Read-only health view: per-job {last_status, consecutive_failures, next_due_in_h}
    + a `failing` list (consecutive_failures >= 3) + liveness. No side effects."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    jobs: list[dict] = []
    failing: list[str] = []
    for job in CRON_JOBS:
        st = _read_state(job.name)
        cf = int(st.get("consecutive_failures", 0))
        last = st.get("last_run_ts_ms")
        interval = effective_interval_hours(job.cadence_hours, cf)
        if isinstance(last, int) and last > 0:
            next_in = round(max(0.0, interval - (now_ms - last) / _HOUR_MS), 2)
        else:
            next_in = 0.0
        jobs.append({"job": job.name, "last_status": st.get("last_status"),
                     "consecutive_failures": cf, "next_due_in_h": next_in,
                     "token_gated": job.token is not None})
        if cf >= 3:
            failing.append(job.name)
    return {"jobs": jobs, "failing": failing, "liveness": liveness_status(now_ms)}


# --------------------------------------------------------------------------
# Pass
# --------------------------------------------------------------------------

def run_pass(
    *,
    now_ms: int | None = None,
    dry_run: bool = False,
    env: dict | None = None,
    cron_runner=None,
    gc_runner=None,
    jobs: tuple[CronJob, ...] = CRON_JOBS,
    gc_tasks: list[tuple[str, object]] | None = None,
) -> dict:
    """One scheduler pass. Returns a summary dict. Injectable for tests.

    cron_runner(module, env) -> int (exit code); gc_runner(callable) -> any.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    env = dict(os.environ) if env is None else env
    if cron_runner is None:
        cron_runner = _default_cron_runner
    if gc_runner is None:
        gc_runner = _default_gc_runner
    if gc_tasks is None:
        gc_tasks = _gc_tasks()

    # D2 overlap lock: real passes only (a dry-run is read-only). If another pass holds
    # a live lock, skip this pass entirely (idempotent — the next trigger retries).
    locked = False
    if not dry_run:
        if not _acquire_pass_lock(now_ms):
            return {"now_ms": now_ms, "ran": [], "failures": 0, "gated": 0,
                    "acted": 0, "status": "pass_in_progress"}
        locked = True

    try:
        ran: list[dict] = []
        failures = 0
        gated = 0
        token = (env.get(TOKEN_ENV) or "").strip()

        for job in jobs:
            st = _read_state(job.name)
            cf = int(st.get("consecutive_failures", 0))
            # D1: backoff-aware due — a failed job retries on a shortened interval.
            if not is_due_backoff(st.get("last_run_ts_ms"), now_ms, job.cadence_hours, cf):
                continue
            # Token gate: a gated run_* fires ONLY if the operator put the token in env.
            # Watermark is NOT advanced on a gated skip, so it fires the moment they opt in.
            if job.token is not None and token != job.token:
                gated += 1
                ran.append({"job": job.name, "status": "gated", "due": True})
                continue
            if dry_run:
                ran.append({"job": job.name, "status": "due_dry_run"})
                continue
            try:
                rc = cron_runner(job.module, env)
                status = "ok" if rc == 0 else f"fail_rc{rc}"
                if rc != 0:
                    failures += 1
            except Exception as e:  # noqa: BLE001 — fail-soft, one job never blocks others
                status = f"error:{type(e).__name__}"
                failures += 1
            _write_state(job.name, now_ms, status)
            ran.append({"job": job.name, "status": status})

        for name, fn in gc_tasks:
            st = _read_state(name)
            cf = int(st.get("consecutive_failures", 0))
            if not is_due_backoff(st.get("last_run_ts_ms"), now_ms, 24, cf):
                continue
            if dry_run:
                ran.append({"job": name, "status": "due_dry_run"})
                continue
            try:
                result = gc_runner(fn)
                status = f"ok:{result}" if isinstance(result, int) else "ok"
            except Exception as e:  # noqa: BLE001 — fail-soft
                status = f"error:{type(e).__name__}"
                failures += 1
            _write_state(name, now_ms, status)
            ran.append({"job": name, "status": status})

        summary = {"now_ms": now_ms, "ran": ran, "failures": failures, "gated": gated,
                   "acted": len([r for r in ran if r["status"] not in ("gated", "due_dry_run")])}
        # D4 heartbeat + D3 history: real passes only (dry-run must not mark the
        # scheduler 'alive' nor pollute history).
        if not dry_run:
            _write_heartbeat(now_ms)
            _append_history(summary)
        return summary
    finally:
        if locked:
            _release_pass_lock()


def _default_cron_runner(module: str, env: dict) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", module], cwd=str(_SCRIPTS),
        env={**env, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, timeout=600,
    )
    return proc.returncode


def _default_gc_runner(fn) -> object:
    return fn()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cron.scheduler_driver",
        description="Cadence driver for harness cron jobs + GC tasks (M20).",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="list jobs that are due without running them")
    p.add_argument("--status", action="store_true",
                   help="print per-job health + liveness (read-only; runs nothing, no heartbeat)")
    return p


def _print_status() -> int:
    """Read-only health/liveness view (D3/D4). Runs NOTHING, writes NO heartbeat."""
    h = cron_health()
    lv = h["liveness"]
    print(f"[cron status] liveness={lv['state']}"
          + (f" ({lv['hours_since']}h since last pass)" if lv["hours_since"] is not None else "")
          + (f"  ⚠ failing: {', '.join(h['failing'])}" if h["failing"] else ""))
    for j in h["jobs"]:
        flag = "  ⚠" if j["consecutive_failures"] >= 3 else ""
        gate = " [token-gated]" if j["token_gated"] else ""
        print(f"  - {j['job']}{gate}: last={j['last_status']} "
              f"fails={j['consecutive_failures']} next_due_in={j['next_due_in_h']}h{flag}")
    return 1 if (h["failing"] or lv["state"] == "stale") else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.status:
        return _print_status()
    try:
        summary = run_pass(dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001 — fail-soft top level
        sys.stderr.write(f"[scheduler_driver] FAIL-SOFT: {type(e).__name__}: {e}\n")
        return 1
    if summary.get("status") == "pass_in_progress":
        print("[scheduler] another pass is in progress — skipped")
        return 0
    acted = summary["acted"]
    print(f"[scheduler] acted={acted} gated={summary['gated']} failures={summary['failures']} "
          f"(of {len(summary['ran'])} due)")
    for r in summary["ran"]:
        print(f"  - {r['job']}: {r['status']}")
    return 0 if summary["failures"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
