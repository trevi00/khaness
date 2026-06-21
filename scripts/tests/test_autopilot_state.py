#!/usr/bin/env python3
"""Unit tests for lib/autopilot_state.py — D2''/D5/D7 from debate-1778224899-c24de4.

Coverage:
  - AutopilotState.__post_init__ 4-field manual validation (D7)
  - hash_goal: 40-char sha1 (D5 inline assertion key)
  - new_state / write_state / read_state round-trip (D2'')
  - advance_iter: bumps iter + heartbeat
  - can_continue: D4 iter+wallclock + D3'' retry counters
  - is_stale: D2'' resume window
  - list_active_sids: scan filter
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---------- D7 dataclass validation ----------

def test_post_init_rejects_empty_sid():
    from lib.autopilot_state import AutopilotState
    try:
        AutopilotState(
            sid="", iter=0, goal_hash="a"*40, status="in_progress",
            started_ts=0.0, last_heartbeat_ts=0.0,
        )
    except ValueError as e:
        assert "sid" in str(e)
        return
    raise AssertionError("expected ValueError on empty sid")


def test_post_init_rejects_iter_out_of_range():
    from lib.autopilot_state import AutopilotState
    for bad in (-1, 31, 100):
        try:
            AutopilotState(
                sid="x", iter=bad, goal_hash="a"*40, status="in_progress",
                started_ts=0.0, last_heartbeat_ts=0.0,
            )
        except ValueError as e:
            assert "iter" in str(e)
            continue
        raise AssertionError(f"expected ValueError on iter={bad}")


def test_post_init_rejects_bad_goal_hash():
    from lib.autopilot_state import AutopilotState
    for bad in ("short", "x"*41, 12345):
        try:
            AutopilotState(
                sid="x", iter=0, goal_hash=bad, status="in_progress",
                started_ts=0.0, last_heartbeat_ts=0.0,
            )
        except ValueError as e:
            assert "goal_hash" in str(e)
            continue
        raise AssertionError(f"expected ValueError on goal_hash={bad!r}")


def test_post_init_rejects_invalid_status():
    from lib.autopilot_state import AutopilotState
    try:
        AutopilotState(
            sid="x", iter=0, goal_hash="a"*40, status="weird",
            started_ts=0.0, last_heartbeat_ts=0.0,
        )
    except ValueError as e:
        assert "status" in str(e)
        return
    raise AssertionError("expected ValueError on bad status")


def test_post_init_rejects_negative_counters():
    from lib.autopilot_state import AutopilotState
    try:
        AutopilotState(
            sid="x", iter=0, goal_hash="a"*40, status="in_progress",
            started_ts=0.0, last_heartbeat_ts=0.0,
            tag_miss_count=-1,
        )
    except ValueError as e:
        assert "negative" in str(e)
        return
    raise AssertionError("expected ValueError on negative counter")


# ---------- hash_goal (D5) ----------

def test_hash_goal_returns_40_char_sha1():
    from lib.autopilot_state import hash_goal
    h = hash_goal("ship feature X")
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_goal_is_deterministic():
    from lib.autopilot_state import hash_goal
    assert hash_goal("same goal") == hash_goal("same goal")
    assert hash_goal("goal A") != hash_goal("goal B")


# ---------- new_state / write_state / read_state ----------

def test_new_state_starts_at_iter_0_in_progress():
    from lib.autopilot_state import new_state
    s = new_state("orch-test-aaa", "goal text")
    assert s.iter == 0
    assert s.status == "in_progress"
    assert s.tag_miss_count == 0
    assert s.json_error_count == 0


def test_write_read_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state, read_state

        s = new_state("orch-rt-aaa", "rt goal")
        assert write_state(s) is True

        loaded = read_state("orch-rt-aaa")
        assert loaded is not None
        assert loaded.sid == s.sid
        assert loaded.iter == s.iter
        assert loaded.goal_hash == s.goal_hash
        assert loaded.status == s.status


def test_read_state_returns_none_for_missing_sid():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import read_state
        assert read_state("orch-missing-aaa") is None


def test_read_state_returns_none_on_corrupt_json():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import read_state, state_path

        # Write garbage to the state file path
        sid = "orch-corrupt-aaa"
        state_path(sid).write_text("not json {{{", encoding="utf-8")
        assert read_state(sid) is None


# ---------- advance_iter ----------

def test_advance_iter_bumps_count_and_heartbeat():
    from lib.autopilot_state import new_state, advance_iter
    s = new_state("x-aaa", "g")
    earlier = s.last_heartbeat_ts
    time.sleep(0.001)
    s2 = advance_iter(s)
    assert s2.iter == s.iter + 1
    assert s2.last_heartbeat_ts >= earlier
    assert s2.sid == s.sid
    assert s2.goal_hash == s.goal_hash


# ---------- D4 + D3'' can_continue ----------

def test_can_continue_true_for_fresh_state():
    from lib.autopilot_state import new_state
    assert new_state("x-aaa", "g").can_continue() is True


def test_can_continue_false_when_iter_cap_hit():
    from lib.autopilot_state import AutopilotState, MAX_ITERATIONS, hash_goal
    now = time.time()
    s = AutopilotState(
        sid="x-aaa", iter=MAX_ITERATIONS, goal_hash=hash_goal("g"),
        status="in_progress", started_ts=now, last_heartbeat_ts=now,
    )
    assert s.iter_cap_hit() is True
    assert s.can_continue() is False


def test_can_continue_false_when_wallclock_cap_hit():
    from lib.autopilot_state import (
        AutopilotState, MAX_WALLCLOCK_SECONDS, hash_goal,
    )
    now = time.time()
    s = AutopilotState(
        sid="x-aaa", iter=0, goal_hash=hash_goal("g"),
        status="in_progress",
        started_ts=now - MAX_WALLCLOCK_SECONDS - 10,
        last_heartbeat_ts=now,
    )
    assert s.wallclock_cap_hit() is True
    assert s.can_continue() is False


def test_can_continue_false_when_tag_miss_exhausted():
    from lib.autopilot_state import AutopilotState, hash_goal, MAX_TAG_MISS
    now = time.time()
    s = AutopilotState(
        sid="x-aaa", iter=0, goal_hash=hash_goal("g"),
        status="in_progress", started_ts=now, last_heartbeat_ts=now,
        tag_miss_count=MAX_TAG_MISS,
    )
    assert s.tag_miss_exhausted() is True
    assert s.can_continue() is False


def test_can_continue_false_when_json_error_exhausted():
    from lib.autopilot_state import (
        AutopilotState, hash_goal, MAX_JSON_ERROR,
    )
    now = time.time()
    s = AutopilotState(
        sid="x-aaa", iter=0, goal_hash=hash_goal("g"),
        status="in_progress", started_ts=now, last_heartbeat_ts=now,
        json_error_count=MAX_JSON_ERROR,
    )
    assert s.json_error_exhausted() is True
    assert s.can_continue() is False


def test_can_continue_false_when_status_done():
    from lib.autopilot_state import new_state
    s = new_state("x-aaa", "g")
    s.status = "done"  # type: ignore[misc]
    assert s.can_continue() is False


# ---------- is_stale (D2'' resume window) ----------

def test_is_stale_false_for_fresh_heartbeat():
    from lib.autopilot_state import new_state
    assert new_state("x-aaa", "g").is_stale() is False


def test_is_stale_true_after_resume_window():
    from lib.autopilot_state import (
        AutopilotState, hash_goal, RESUME_WINDOW_SECONDS,
    )
    now = time.time()
    s = AutopilotState(
        sid="x-aaa", iter=0, goal_hash=hash_goal("g"),
        status="in_progress", started_ts=now,
        last_heartbeat_ts=now - RESUME_WINDOW_SECONDS - 10,
    )
    assert s.is_stale() is True


# ---------- list_active_sids ----------

def test_list_active_sids_returns_only_in_progress_fresh():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, new_state, write_state, list_active_sids,
            hash_goal, RESUME_WINDOW_SECONDS,
        )

        # Active fresh
        s1 = new_state("orch-active-aaa", "g")
        write_state(s1)

        # done (filtered out)
        s2 = AutopilotState(
            sid="orch-done-bbb", iter=5, goal_hash=hash_goal("g"),
            status="done", started_ts=0, last_heartbeat_ts=time.time(),
        )
        write_state(s2)

        # stale (filtered out)
        s3 = AutopilotState(
            sid="orch-stale-ccc", iter=2, goal_hash=hash_goal("g"),
            status="in_progress", started_ts=0,
            last_heartbeat_ts=time.time() - RESUME_WINDOW_SECONDS - 100,
        )
        write_state(s3)

        sids = list_active_sids()
        assert "orch-active-aaa" in sids
        assert "orch-done-bbb" not in sids
        assert "orch-stale-ccc" not in sids


def test_list_active_sids_cwd_filter_scopes_by_project():
    # D2 (debate-1781937446-1281b5): cwd_filter is now REAL (was a no-op).
    import os
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, new_state, write_state, list_active_sids, hash_goal,
        )
        now = time.time()
        # two v2 sessions bound to different projects
        write_state(new_state("orch-a-aaa", "g", cwd="D:/projA"))
        write_state(new_state("orch-b-bbb", "g", cwd="D:/projB"))
        # one legacy v1 session (cwd is None — simulates a pre-upgrade state file)
        write_state(AutopilotState(
            sid="orch-legacy-ccc", iter=0, goal_hash=hash_goal("g"),
            status="in_progress", started_ts=now, last_heartbeat_ts=now,
        ))
        # cwd-scoped scan returns ONLY the matching project; other project + v1 EXCLUDED
        # (this is the H2 fix: a Stop in cwd B can no longer select a session bound to A)
        assert set(list_active_sids(cwd_filter="D:/projA")) == {"orch-a-aaa"}
        assert set(list_active_sids(cwd_filter="D:/projB")) == {"orch-b-bbb"}
        # unscoped scan (None) returns all three active sessions (back-compat)
        assert set(list_active_sids(None)) == {"orch-a-aaa", "orch-b-bbb", "orch-legacy-ccc"}
        # subtree tolerance: a Stop launched in a subdir of projA still resolves to sA
        assert set(list_active_sids(cwd_filter="D:/projA/scripts")) == {"orch-a-aaa"}
        # Windows case/separator tolerance (_cwd_match casefolds on nt only)
        if os.name == "nt":
            assert "orch-a-aaa" in list_active_sids(cwd_filter="d:\\projA")


def test_advance_iter_carries_cwd_forward():
    # gen-1 Critic blocker: advance_iter re-mints the dataclass; without carrying
    # cwd it would drop to None each iteration and re-open the cross-cwd gap.
    from lib.autopilot_state import new_state, advance_iter
    s = new_state("orch-adv-aaa", "g", cwd="D:/projA")
    assert advance_iter(s).cwd == "D:/projA"


# ---------- cleanup_terminal_sessions ----------

def test_cleanup_removes_done_older_than_window():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, hash_goal, write_state, cleanup_terminal_sessions,
            state_path, RESUME_WINDOW_SECONDS,
        )
        now = time.time()
        old_done = AutopilotState(
            sid="orch-old-done", iter=3, goal_hash=hash_goal("g"),
            status="done", started_ts=now - RESUME_WINDOW_SECONDS - 1000,
            last_heartbeat_ts=now - RESUME_WINDOW_SECONDS - 100,
        )
        write_state(old_done)
        assert state_path("orch-old-done").exists()

        removed = cleanup_terminal_sessions(now=now)
        assert removed == 1
        assert not state_path("orch-old-done").exists()


def test_cleanup_keeps_fresh_done_and_in_progress():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, hash_goal, new_state, write_state,
            cleanup_terminal_sessions, state_path,
        )
        now = time.time()
        # Fresh done — must be kept (heartbeat within window)
        fresh_done = AutopilotState(
            sid="orch-fresh-done", iter=2, goal_hash=hash_goal("g"),
            status="done", started_ts=now - 100, last_heartbeat_ts=now - 50,
        )
        write_state(fresh_done)
        # Active in_progress — must be kept regardless of heartbeat age
        write_state(new_state("orch-active", "g"))

        removed = cleanup_terminal_sessions(now=now)
        assert removed == 0
        assert state_path("orch-fresh-done").exists()
        assert state_path("orch-active").exists()


def test_session_init_cleanup_terminal_helper_removes_old_done():
    """SessionStart hook wiring: _autopilot_cleanup_terminal() prunes
    terminal records during session init (cron substitute)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, hash_goal, write_state, state_path,
            RESUME_WINDOW_SECONDS,
        )
        from handlers.session.init import _autopilot_cleanup_terminal

        now = time.time()
        old_done = AutopilotState(
            sid="orch-prune-aaa", iter=3, goal_hash=hash_goal("g"),
            status="done", started_ts=now - RESUME_WINDOW_SECONDS - 2000,
            last_heartbeat_ts=now - RESUME_WINDOW_SECONDS - 200,
        )
        write_state(old_done)
        assert state_path("orch-prune-aaa").exists()

        _autopilot_cleanup_terminal()

        assert not state_path("orch-prune-aaa").exists()


def test_cleanup_skips_in_progress_even_when_stale():
    """Stale in_progress is operator's call, not auto-prune surface."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, hash_goal, write_state, cleanup_terminal_sessions,
            state_path, RESUME_WINDOW_SECONDS,
        )
        now = time.time()
        stale_active = AutopilotState(
            sid="orch-stale-active", iter=4, goal_hash=hash_goal("g"),
            status="in_progress", started_ts=now - RESUME_WINDOW_SECONDS - 5000,
            last_heartbeat_ts=now - RESUME_WINDOW_SECONDS - 1000,
        )
        write_state(stale_active)

        removed = cleanup_terminal_sessions(now=now)
        assert removed == 0
        assert state_path("orch-stale-active").exists()


# ---------- SessionStart resume line helper (handlers/session/init.py) ----------

def test_session_init_resume_line_none_when_no_active():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from handlers.session.init import _autopilot_resume_line
        assert _autopilot_resume_line(td) is None


def test_session_init_resume_line_emits_advisory_for_active_session():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import new_state, write_state
        from handlers.session.init import _autopilot_resume_line

        # D2: the session must be bound to the cwd we resume from (a session is
        # created in project P and resumed in project P). cwd=td matches the
        # _autopilot_resume_line(td) query.
        write_state(new_state("orch-resume-aaa", "ship feature X", cwd=td))
        line = _autopilot_resume_line(td)
        assert line is not None
        assert "autopilot-resume" in line
        assert "orch-resume-aaa" in line
        assert "/harness-autopilot --resume" in line
        # Single-line invariant — joined into harness-status block directly
        assert "\n" not in line


def test_session_init_resume_line_picks_most_recent_when_multiple():
    """Determinism: when multiple active sessions exist, pick the one with
    the latest heartbeat (predictable surface, not first-listdir-order)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.autopilot_state import (
            AutopilotState, hash_goal, write_state,
        )
        from handlers.session.init import _autopilot_resume_line

        old = AutopilotState(
            sid="orch-old-aaa", iter=1, goal_hash=hash_goal("g"),
            status="in_progress",
            started_ts=time.time() - 100, last_heartbeat_ts=time.time() - 100,
            cwd=td,  # D2: bound to the resume cwd
        )
        new = AutopilotState(
            sid="orch-new-bbb", iter=2, goal_hash=hash_goal("g"),
            status="in_progress",
            started_ts=time.time() - 50, last_heartbeat_ts=time.time() - 1,
            cwd=td,  # D2: bound to the resume cwd
        )
        write_state(old)
        write_state(new)

        line = _autopilot_resume_line(td)
        assert line is not None
        # Newer sid surfaced
        assert "orch-new-bbb" in line
        # Hint about additional sessions
        assert "추가 세션" in line


TESTS = [
    test_post_init_rejects_empty_sid,
    test_post_init_rejects_iter_out_of_range,
    test_post_init_rejects_bad_goal_hash,
    test_post_init_rejects_invalid_status,
    test_post_init_rejects_negative_counters,
    test_hash_goal_returns_40_char_sha1,
    test_hash_goal_is_deterministic,
    test_new_state_starts_at_iter_0_in_progress,
    test_write_read_roundtrip,
    test_read_state_returns_none_for_missing_sid,
    test_read_state_returns_none_on_corrupt_json,
    test_advance_iter_bumps_count_and_heartbeat,
    test_can_continue_true_for_fresh_state,
    test_can_continue_false_when_iter_cap_hit,
    test_can_continue_false_when_wallclock_cap_hit,
    test_can_continue_false_when_tag_miss_exhausted,
    test_can_continue_false_when_json_error_exhausted,
    test_can_continue_false_when_status_done,
    test_is_stale_false_for_fresh_heartbeat,
    test_is_stale_true_after_resume_window,
    test_list_active_sids_returns_only_in_progress_fresh,
    test_cleanup_removes_done_older_than_window,
    test_cleanup_keeps_fresh_done_and_in_progress,
    test_session_init_cleanup_terminal_helper_removes_old_done,
    test_cleanup_skips_in_progress_even_when_stale,
    test_session_init_resume_line_none_when_no_active,
    test_session_init_resume_line_emits_advisory_for_active_session,
    test_session_init_resume_line_picks_most_recent_when_multiple,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
