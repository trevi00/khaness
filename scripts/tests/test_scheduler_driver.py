#!/usr/bin/env python3
"""Tests for cron.scheduler_driver (M20) — cadence + token-gate respect + fail-soft.
Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cron.scheduler_driver import CronJob, is_due, run_pass  # noqa: E402

_HOUR_MS = 60 * 60 * 1000


# ---- pure cadence ----

def test_is_due():
    assert is_due(None, 1000, 24) is True            # never run
    assert is_due(0, 1000, 24) is True               # zero ts
    now = 100 * _HOUR_MS
    assert is_due(now - 25 * _HOUR_MS, now, 24) is True   # 25h >= 24h
    assert is_due(now - 1 * _HOUR_MS, now, 24) is False   # 1h < 24h


def _with_state(fn):
    """Run fn with lib.paths.STATE_DIR patched to a temp dir."""
    import lib.paths as paths
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(paths, "STATE_DIR", Path(td) / "state"):
            fn()


# ---- token gate respected ----

def test_run_star_gated_without_token_and_watermark_not_advanced():
    job = CronJob("x_run", "cron.run_x", 24, "enable-cron-job")
    calls = []

    def _run():
        from cron import scheduler_driver as m
        env = {}  # no token
        s1 = run_pass(now_ms=1000, env=env, jobs=(job,), gc_tasks=[],
                      cron_runner=lambda mod, e: calls.append(mod) or 0)
        assert s1["gated"] == 1 and calls == []  # not invoked
        assert s1["ran"][0]["status"] == "gated"
        # watermark NOT advanced -> still due next pass; now WITH token it fires
        env2 = {"HARNESS_MUTATION_TOKEN": "enable-cron-job"}
        s2 = run_pass(now_ms=2000, env=env2, jobs=(job,), gc_tasks=[],
                      cron_runner=lambda mod, e: calls.append(mod) or 0)
        assert s2["gated"] == 0 and calls == ["cron.run_x"]
        assert s2["ran"][0]["status"] == "ok"
    _with_state(_run)


def test_check_jobs_run_without_token():
    job = CronJob("x_check", "cron.check_x", 24, None)  # auto-OK

    def _run():
        ran = []
        s = run_pass(now_ms=1000, env={}, jobs=(job,), gc_tasks=[],
                     cron_runner=lambda mod, e: ran.append(mod) or 0)
        assert ran == ["cron.check_x"] and s["acted"] == 1 and s["failures"] == 0
    _with_state(_run)


# ---- cadence: not due on second pass within window ----

def test_cadence_skips_within_window():
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        ran = []
        run_pass(now_ms=10 * _HOUR_MS, env={}, jobs=(job,), gc_tasks=[],
                 cron_runner=lambda mod, e: ran.append(mod) or 0)
        # 1h later -> not due
        run_pass(now_ms=11 * _HOUR_MS, env={}, jobs=(job,), gc_tasks=[],
                 cron_runner=lambda mod, e: ran.append(mod) or 0)
        assert ran == ["cron.check_x"]  # only the first pass ran it
        # 25h after first -> due again
        run_pass(now_ms=35 * _HOUR_MS, env={}, jobs=(job,), gc_tasks=[],
                 cron_runner=lambda mod, e: ran.append(mod) or 0)
        assert ran == ["cron.check_x", "cron.check_x"]
    _with_state(_run)


# ---- fail-soft: one job failing does not block others ----

def test_failure_is_recorded_others_continue():
    j1 = CronJob("a_check", "cron.check_a", 24, None)
    j2 = CronJob("b_check", "cron.check_b", 24, None)

    def _run():
        def runner(mod, e):
            if mod == "cron.check_a":
                raise RuntimeError("boom")
            return 0
        s = run_pass(now_ms=1000, env={}, jobs=(j1, j2), gc_tasks=[], cron_runner=runner)
        statuses = {r["job"]: r["status"] for r in s["ran"]}
        assert statuses["a_check"].startswith("error:") and statuses["b_check"] == "ok"
        assert s["failures"] == 1 and s["acted"] == 2  # both attempted
    _with_state(_run)


def test_cron_nonzero_rc_counts_as_failure():
    job = CronJob("x_run", "cron.run_x", 24, "enable-cron-job")

    def _run():
        s = run_pass(now_ms=1000, env={"HARNESS_MUTATION_TOKEN": "enable-cron-job"},
                     jobs=(job,), gc_tasks=[], cron_runner=lambda mod, e: 1)
        assert s["failures"] == 1 and s["ran"][0]["status"] == "fail_rc1"
    _with_state(_run)


# ---- GC tasks run via gc_runner, fail-soft ----

def test_gc_tasks_run_and_failsoft():
    def _run():
        good = ("good_gc", lambda: 5)
        bad = ("bad_gc", lambda: (_ for _ in ()).throw(ValueError("x")))
        s = run_pass(now_ms=1000, env={}, jobs=(), gc_tasks=[good, bad],
                     gc_runner=lambda fn: fn())
        statuses = {r["job"]: r["status"] for r in s["ran"]}
        assert statuses["good_gc"] == "ok:5" and statuses["bad_gc"].startswith("error:")
        assert s["failures"] == 1
    _with_state(_run)


# ---- dry-run lists due, runs nothing ----

def test_dry_run_runs_nothing():
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        ran = []
        s = run_pass(now_ms=1000, env={}, dry_run=True, jobs=(job,),
                     gc_tasks=[("g", lambda: ran.append("gc"))],
                     cron_runner=lambda mod, e: ran.append(mod) or 0)
        assert ran == []  # nothing actually invoked
        assert all(r["status"] == "due_dry_run" for r in s["ran"]) and len(s["ran"]) == 2
    _with_state(_run)


# ---- real manifest is well-formed ----

def test_real_manifest_well_formed():
    from cron.scheduler_driver import CRON_JOBS, _gc_tasks
    names = [j.name for j in CRON_JOBS]
    assert len(names) == len(set(names))  # unique
    checks = [j for j in CRON_JOBS if j.token is None]
    runs = [j for j in CRON_JOBS if j.token == "enable-cron-job"]
    assert len(checks) == 4 and len(runs) == 4  # 4 check + 4 run pairs
    gc = _gc_tasks()
    assert len(gc) == 7 and all(callable(fn) for _, fn in gc)  # 6 maintenance + cron_history_gc


# ---- D1: failure backoff ----

def test_effective_interval_backoff_and_cap():
    from cron.scheduler_driver import effective_interval_hours
    assert effective_interval_hours(24, 0) == 24       # no failures -> normal cadence
    assert effective_interval_hours(24, 1) == 0.25     # first retry 15min
    assert effective_interval_hours(24, 2) == 0.5      # doubles
    assert effective_interval_hours(24, 3) == 1.0
    # capped at cadence — a permanently failing job never waits longer than its cadence
    assert effective_interval_hours(6, 20) == 6
    assert effective_interval_hours(24, 100) == 24


def test_failed_job_retries_before_full_cadence():
    """A check job that fails retries on the backoff interval (15min), NOT after the
    full 24h cadence."""
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        n = [0]
        def runner(mod, e):
            n[0] += 1
            return 1  # always fails
        base = 10 * _HOUR_MS  # realistic non-zero ts (last<=0 is the 'never run' sentinel)
        # fails -> consecutive_failures=1 -> next due in 0.25h
        run_pass(now_ms=base, env={}, jobs=(job,), gc_tasks=[], cron_runner=runner)
        # +0.1h: NOT yet due (< 0.25h backoff)
        run_pass(now_ms=base + int(0.1 * _HOUR_MS), env={}, jobs=(job,), gc_tasks=[], cron_runner=runner)
        assert n[0] == 1, "should not retry before the 15min backoff"
        # +0.3h: due again (>= 0.25h) — retries far before the 24h cadence
        run_pass(now_ms=base + int(0.3 * _HOUR_MS), env={}, jobs=(job,), gc_tasks=[], cron_runner=runner)
        assert n[0] == 2, "should retry after the backoff interval, not wait 24h"
    _with_state(_run)


def test_success_resets_backoff_counter():
    from cron.scheduler_driver import _read_state, _write_state
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        # two failures then a success
        _write_state(job.name, 0, "fail_rc1")
        _write_state(job.name, 0, "fail_rc1")
        assert _read_state(job.name)["consecutive_failures"] == 2
        _write_state(job.name, 0, "ok")
        assert _read_state(job.name)["consecutive_failures"] == 0
        # GC-style ok:5 also counts as success
        _write_state(job.name, 0, "fail_rc1")
        _write_state(job.name, 0, "ok:5")
        assert _read_state(job.name)["consecutive_failures"] == 0
    _with_state(_run)


# ---- D2: overlap lock ----

def test_overlap_lock_skips_concurrent_pass():
    from cron.scheduler_driver import _acquire_pass_lock, run_pass
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        # simulate a live pass holding the lock (this process's pid -> alive)
        assert _acquire_pass_lock(1000) is True
        ran = []
        s = run_pass(now_ms=2000, env={}, jobs=(job,), gc_tasks=[],
                     cron_runner=lambda mod, e: ran.append(mod) or 0)
        assert s.get("status") == "pass_in_progress" and ran == []
    _with_state(_run)


def test_stale_lock_is_reclaimed():
    from cron.scheduler_driver import _acquire_pass_lock, _lock_path, _stale_lock_ms
    import json as _json

    def _run():
        # write a lock far in the past with a dead pid -> reclaimable
        _lock_path().write_text(_json.dumps({"pid": 999999999, "ts_ms": 0}), encoding="utf-8")
        now = _stale_lock_ms() + 1
        assert _acquire_pass_lock(now) is True  # stale -> reclaimed
    _with_state(_run)


# ---- D3/D4: history + heartbeat + liveness + status ----

def test_real_pass_writes_heartbeat_and_history():
    from cron.scheduler_driver import run_pass, liveness_status, _history_path
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        run_pass(now_ms=5 * _HOUR_MS, env={}, jobs=(job,), gc_tasks=[],
                 cron_runner=lambda mod, e: 0)
        lv = liveness_status(now_ms=5 * _HOUR_MS)
        assert lv["state"] == "ok" and lv["hours_since"] == 0.0
        assert _history_path().exists()
        assert "x_check" in _history_path().read_text(encoding="utf-8")
    _with_state(_run)


def test_dry_run_writes_no_heartbeat():
    from cron.scheduler_driver import run_pass, liveness_status
    job = CronJob("x_check", "cron.check_x", 24, None)

    def _run():
        run_pass(now_ms=1000, env={}, dry_run=True, jobs=(job,), gc_tasks=[],
                 cron_runner=lambda mod, e: 0)
        assert liveness_status(now_ms=1000)["state"] == "never_run"  # dry-run didn't mark alive
    _with_state(_run)


def test_liveness_stale_after_threshold():
    from cron.scheduler_driver import run_pass, liveness_status, _LIVENESS_MAX_H

    def _run():
        run_pass(now_ms=0, env={}, jobs=(), gc_tasks=[], cron_runner=lambda mod, e: 0)
        later = int((_LIVENESS_MAX_H + 1) * _HOUR_MS)
        assert liveness_status(now_ms=later)["state"] == "stale"
    _with_state(_run)


def test_gc_history_trims_old_lines():
    from cron.scheduler_driver import gc_history, _history_path, _HOUR_MS as H, _HISTORY_KEEP_DAYS
    import json as _json

    def _run():
        now = 1000 * H
        old_ts = now - (_HISTORY_KEEP_DAYS + 5) * 24 * H
        lines = [_json.dumps({"ts_ms": old_ts}), _json.dumps({"ts_ms": now})]
        _history_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
        kept = gc_history(now_ms=now)
        assert kept == 1  # the old line dropped, the recent kept
    _with_state(_run)


def test_cron_health_flags_failing_jobs():
    from cron.scheduler_driver import cron_health, _write_state, CRON_JOBS

    def _run():
        name = CRON_JOBS[0].name
        for _ in range(3):
            _write_state(name, 0, "fail_rc1")
        h = cron_health(now_ms=1000)
        assert name in h["failing"]
        jrow = next(j for j in h["jobs"] if j["job"] == name)
        assert jrow["consecutive_failures"] == 3
    _with_state(_run)


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
