#!/usr/bin/env python3
"""Unit tests for lib/work_unit_store.py — auto-brain-update + session-continuity.

Pins the locked invariants from debate-1781431026-af5f83 (converged gen-3,
ontology SHA-1 32808a52c893) as executable assertions:
  C1  throttle: ≤ once per SAVE_INTERVAL_SECONDS, gated on work-unit-happened
      (brain divergence), for BOTH autopilot AND non-autopilot; force on terminal.
  C3  resume breadcrumb state/work_unit/<sid>.json + 30-day gc_old_work_units().
  C4  INV-save race tolerated (copy2 non-atomic) — asserted via brain_store reuse.
  C6  CONTROL-ARM: lib.work_unit_store is NOT an L1 writer. The test DEFEATS the
      conftest autouse whitelist-widening — 'lib.work_unit_store' is absent from
      BOTH the production frozenset AND the conftest widened set, so a fully-shaped
      append under that source returns None EVEN with the widening applied. This is
      non-tautological: it does not pass merely because isolation dropped the writer.

Each test isolates CLAUDE_HOME to a fresh temp dir (set BEFORE imports). Run:
    python tests/test_work_unit_store.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_PASS = 0
_FAIL = 0


def _ok(msg: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [OK]   {msg}")


def _fail(msg: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {msg}")


def _check(cond: bool, msg: str) -> None:
    _ok(msg) if cond else _fail(msg)


def _fresh_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="wu-test-"))
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_HOME"] = str(home)
    return home


def _import_wu():
    """Fresh import of work_unit_store + brain_store under the current CLAUDE_HOME."""
    for m in [k for k in list(sys.modules) if k == "lib" or k.startswith("lib.")]:
        del sys.modules[m]
    from lib import work_unit_store  # noqa: E402
    return work_unit_store


# ── C1 throttle ──────────────────────────────────────────────────────────────

def test_throttle() -> None:
    print("test_throttle (C1 watermark)")
    _fresh_home()
    wu = _import_wu()
    t0 = 1_000_000.0
    _check(wu.throttle_ok("save", now=t0, interval=900) is True, "no watermark → elapsed")
    wu.mark("save", now=t0)
    _check(wu.throttle_ok("save", now=t0 + 100, interval=900) is False, "within interval → blocked")
    _check(wu.throttle_ok("save", now=t0 + 900, interval=900) is True, "at interval → elapsed")
    _check(wu.throttle_ok("save", now=t0 + 5000, interval=900) is True, "past interval → elapsed")
    # garbage watermark fails open toward saving
    (Path(os.environ["CLAUDE_HOME"]) / "state" / "work_unit" / "save_watermark.json").write_text("{bad", encoding="utf-8")
    _check(wu.throttle_ok("save", now=t0, interval=900) is True, "torn watermark → fail-open elapsed")


# ── C3 breadcrumb + GC ───────────────────────────────────────────────────────

def test_breadcrumb_roundtrip() -> None:
    print("test_breadcrumb_roundtrip (C3)")
    _fresh_home()
    wu = _import_wu()
    p = wu.record_work_unit("sess-A", "D:/proj", "implementing throttle", now=2000.0)
    _check(p is not None and p.is_file(), "record writes <sid>.json")
    rec = wu.read_work_unit("sess-A")
    _check(rec is not None and rec["summary"] == "implementing throttle", "read roundtrip")
    _check(rec["cwd"] == "D:/proj" and rec["status"] == "active", "fields persisted")
    # overwrite REPLACES not ADDS (one row per session)
    wu.record_work_unit("sess-A", "D:/proj", "second update", now=2100.0)
    rec2 = wu.read_work_unit("sess-A")
    _check(rec2["summary"] == "second update" and rec2["last_activity_ts"] == 2100.0, "overwrite replaces")
    files = list((Path(os.environ["CLAUDE_HOME"]) / "state" / "work_unit").glob("sess-A*.json"))
    _check(len(files) == 1, "still one file for the session (replace not add)")


def test_safe_name_traversal() -> None:
    print("test_safe_name_traversal")
    _fresh_home()
    wu = _import_wu()
    wu.record_work_unit("../../etc/passwd", "c", "x", now=1.0)
    d = Path(os.environ["CLAUDE_HOME"]) / "state" / "work_unit"
    escaped = list(d.glob("*.json"))
    _check(all(".." not in p.name and "/" not in p.name for p in escaped), "traversal chars collapsed in filename")
    _check(not (Path(os.environ["CLAUDE_HOME"]).parent / "etc").exists(), "no escape outside CLAUDE_HOME")


def test_latest_work_unit() -> None:
    print("test_latest_work_unit (resume surface)")
    _fresh_home()
    wu = _import_wu()
    wu.record_work_unit("old", "D:/proj", "old work", now=1000.0)
    wu.record_work_unit("new", "D:/proj", "new work", now=5000.0)
    wu.record_work_unit("other", "D:/elsewhere", "other proj", now=9000.0)
    latest = wu.latest_work_unit(cwd="D:/proj", now=5100.0)
    _check(latest is not None and latest["sid"] == "new", "picks most-recent for cwd")
    # staleness: 40 days old is skipped
    stale = wu.latest_work_unit(cwd="D:/proj", now=1000.0 + 41 * 86400)
    _check(stale is None, "stale (>30d) breadcrumb skipped")
    # watermark sidecars never surface as breadcrumbs
    wu.mark("save", now=5000.0)
    latest2 = wu.latest_work_unit(cwd=None, now=9100.0)
    _check(latest2 is not None and latest2["sid"] == "other", "watermark sidecar not surfaced")


def test_gc_old_work_units() -> None:
    print("test_gc_old_work_units (C3 30-day GC)")
    _fresh_home()
    wu = _import_wu()
    d = Path(os.environ["CLAUDE_HOME"]) / "state" / "work_unit"
    wu.record_work_unit("keep", "c", "fresh", now=time.time())
    wu.record_work_unit("drop", "c", "old", now=time.time())
    old_file = d / "drop.json"
    old_mtime = time.time() - (40 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))
    removed = wu.gc_old_work_units(max_age_days=30)
    _check(removed == 1, "one old breadcrumb pruned")
    _check((d / "keep.json").is_file() and not old_file.is_file(), "fresh kept, old removed")


# ── C1 brain divergence + autosave ──────────────────────────────────────────

def _seed_live_l1(home: Path, eid: str) -> None:
    rec = {"id": eid, "schema_version": "1", "ts_unix_ms": 1, "event_type": "wonder",
           "summary": "s", "correlation_id": "c", "source_module": "m",
           "axis": None, "tags": [], "body_ref": None}
    (home / "memory" / "insight-index.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")


def test_brain_divergence_and_autosave() -> None:
    print("test_brain_divergence_and_autosave (C1)")
    home = _fresh_home()
    wu = _import_wu()
    _seed_live_l1(home, "id-1")
    _check(wu.brain_has_unsaved_work() is True, "live L1 absent from empty brain → diverged")
    # throttle blocks even when diverged
    wu.mark("save", now=10_000.0)
    _check(wu.maybe_autosave(now=10_100.0) is None, "throttle blocks autosave within interval")
    # interval elapsed + diverged → saves
    res = wu.maybe_autosave(now=10_000.0 + 901)
    _check(res is not None, "autosave runs after interval when diverged")
    brain_l1 = home / "brain" / "l1" / "insight-index.jsonl"
    _check(brain_l1.is_file(), "brain snapshot written")
    # after save, no divergence → autosave returns None (no spurious save)
    _check(wu.brain_has_unsaved_work() is False, "post-save: live == snapshot")
    _check(wu.maybe_autosave(now=10_000.0 + 5000) is None, "no divergence → autosave no-op")


def test_force_autosave() -> None:
    print("test_force_autosave (C1 terminal)")
    home = _fresh_home()
    wu = _import_wu()
    _seed_live_l1(home, "id-term")
    wu.mark("save", now=20_000.0)  # would block maybe_autosave
    res = wu.force_autosave(now=20_050.0)
    _check(res is not None, "force_autosave bypasses throttle")
    _check((home / "brain" / "l1" / "insight-index.jsonl").is_file(), "terminal save persisted brain")


# ── cwd same-tree matching (resume robustness) ───────────────────────────────

def test_cwd_match_same_tree() -> None:
    print("test_cwd_match_same_tree (resume cwd robustness)")
    _fresh_home()
    wu = _import_wu()
    _check(wu._cwd_match("C:/Users/u/.claude", "C:\\Users\\u\\.claude"), "separator / vs backslash matches")
    _check(wu._cwd_match("C:/Users/u/.claude", "C:/Users/u/.claude/scripts"), "ancestor query -> subdir breadcrumb matches")
    _check(wu._cwd_match("C:/Users/u/.claude/scripts", "C:/Users/u/.claude"), "subdir query -> ancestor breadcrumb matches")
    _check(not wu._cwd_match("C:/Users/u/.claude", "D:/other"), "unrelated path does NOT match")
    _check(not wu._cwd_match("C:/Users/u/.claude", "C:/Users/u/.claudeX"), "segment-safe: .claude != .claudeX")
    _check(not wu._cwd_match("C:/p", ""), "empty stored cwd -> no match")
    # latest_work_unit uses it: a breadcrumb at <proj>/scripts resumes from <proj>
    wu.record_work_unit("s1", "C:/proj/scripts", "work in subdir", now=1000.0)
    got = wu.latest_work_unit(cwd="C:/proj", now=1001.0)
    _check(got is not None and got["sid"] == "s1", "latest_work_unit matches breadcrumb in a subdir of cwd")


# ── forward-plan capture (handoff replacement: "what's NEXT") ────────────────

def test_extract_next_steps_and_breadcrumb() -> None:
    print("test_extract_next_steps_and_breadcrumb (handoff forward-plan)")
    _fresh_home()
    wu = _import_wu()
    msg = ("완료했습니다. 작업 트리 clean.\n\n"
           "남은 건 settings.json 커밋입니다.\n"
           "- 다음: CI 빨강 원인 규명\n"
           "Next: push the brain snapshot\n"
           "그냥 설명 문장 (마커 없음).")
    ns = wu.extract_next_steps(msg)
    _check("settings.json" in ns, "captures '남은 건 …' line")
    _check("CI 빨강" in ns, "captures '다음: …' line")
    _check("push the brain" in ns.lower(), "captures English 'Next:' line")
    _check("그냥 설명 문장" not in ns, "ignores non-forward prose (no marker)")
    _check(wu.extract_next_steps("그냥 끝. 마커 전혀 없음.") == "", "no markers -> empty")
    _check(wu.extract_next_steps("") == "", "empty input -> empty")
    # breadcrumb stores + reads next_steps
    wu.record_work_unit("sess-fp", "D:/p", "did work", now=1.0, next_steps="다음: 배포")
    rec = wu.read_work_unit("sess-fp")
    _check(rec is not None and rec.get("next_steps") == "다음: 배포", "breadcrumb persists next_steps field")


# ── C6 control-arm: work_unit_store is NOT an L1 writer ──────────────────────

def test_c6_control_arm_not_a_writer() -> None:
    print("test_c6_control_arm_not_a_writer (C6, defeats conftest widening)")
    home = _fresh_home()
    for m in [k for k in list(sys.modules) if k == "lib" or k.startswith("lib.")]:
        del sys.modules[m]
    from lib import insight_index

    prod = insight_index._ALLOWED_WRITER_SOURCES
    _check("lib.work_unit_store" not in prod, "absent from PRODUCTION frozenset")
    _check(prod == frozenset({"handlers.stop.learner", "engine.orchestrator",
                              "lib.skill_candidate_detector"}), "production writer set unchanged (3 writers)")

    # Replicate the conftest autouse widening EXACTLY and assert work_unit_store
    # is STILL absent — so the rejection is not an artifact of isolation.
    widened = prod | frozenset({
        "tests.test_insight_index", "tests.test_insight_index_query",
        "tests.test_insight_index_retract", "tests",
    })
    _check("lib.work_unit_store" not in widened, "absent from conftest WIDENED set")

    # Positive control: even WITH the widening monkeypatched in, a fully-shaped
    # entry whose source_module='lib.work_unit_store' is REJECTED (returns None).
    insight_index._ALLOWED_WRITER_SOURCES = widened  # simulate conftest autouse
    try:
        entry = {
            "event_type": "work_unit_digest",
            "summary": "control-arm fully-shaped entry",
            "ts_unix_ms": 123,
            "correlation_id": "sess-A-wu",
            "source_module": "lib.work_unit_store",
            "axis": None,
            "tags": ["work_unit"],
            "body_ref": None,
        }
        result = insight_index.append(entry)
        _check(result is None, "fully-shaped append under work_unit_store source → None (rejected under widening)")
    finally:
        insight_index._ALLOWED_WRITER_SOURCES = prod

    # And the whitelisted learner source on an identical shape WOULD be accepted
    # (proves the rejection is source-driven, not shape-driven — control rigor).
    entry2 = dict(entry, source_module="handlers.stop.learner")
    accepted = insight_index.append(entry2)
    _check(isinstance(accepted, str), "identical shape under whitelisted learner source → accepted (id returned)")


# ── kha SDLC one-way state mirror (debate-1781871696-sdoggn G5 seam) ─────────

def _write_state_md(root: Path, body: str) -> Path:
    pdir = root / ".planning"
    pdir.mkdir(parents=True, exist_ok=True)
    sp = pdir / "STATE.md"
    sp.write_text(body, encoding="utf-8")
    return sp


# Canonical gsd `state-sync` output: snake_case flat keys + a nested progress:
# block (get-shit-done/bin/lib/state.cjs buildStateFrontmatter / reconstructFrontmatter).
_CANON_FM = (
    "---\n"
    "gsd_state_version: 1.0\n"
    "milestone_name: internalized autopilot runtime\n"
    "current_phase: 3\n"
    "current_phase_name: failure-learning prevention\n"
    "current_plan: 2\n"
    "status: executing\n"
    "last_activity: 2026-06-20 — wired the seam\n"
    "progress:\n"
    "  total_phases: 5\n"
    "  completed_phases: 2\n"
    "  percent: 40\n"
    "---\n\n"
    "# Project State\n\n## Current Position\nPhase: 3 of 5\n"
)


def test_kha_planning_state_mirror() -> None:
    print("test_kha_planning_state_mirror (debate-1781871696 G5 seam)")
    _fresh_home()
    wu = _import_wu()
    proj = Path(tempfile.mkdtemp(prefix="kha-proj-"))

    # 1. canonical gsd state-sync frontmatter -> extracted dict (real format)
    _write_state_md(proj, _CANON_FM)
    kha = wu.read_planning_state(str(proj))
    _check(kha is not None, "resolves STATE.md at cwd")
    _check(bool(kha) and kha["current_phase"] == "3", "current_phase extracted (snake_case)")
    _check(bool(kha) and kha["current_plan"] == "2", "current_plan extracted")
    _check(bool(kha) and kha["status"] == "executing", "status extracted")
    _check(bool(kha) and kha["project"] == "internalized autopilot runtime", "project <- milestone_name")

    # 2. parent ascent: cwd a deep subdir, STATE.md up exactly 3 parents -> found
    deep = proj / "rust" / "crates" / "x"
    deep.mkdir(parents=True, exist_ok=True)
    kha2 = wu.read_planning_state(str(deep))
    _check(kha2 is not None and kha2["current_phase"] == "3", "ascends <=3 parents to find .planning/STATE.md")

    # 3. beyond 3 parents -> not found (bounded, no false bind)
    toodeep = proj / "a" / "b" / "c" / "d"
    toodeep.mkdir(parents=True, exist_ok=True)
    _check(wu.read_planning_state(str(toodeep)) is None, "ascent bounded at 3 parents")

    # 4. no .planning/ -> None (counted no-op)
    empty = Path(tempfile.mkdtemp(prefix="kha-empty-"))
    _check(wu.read_planning_state(str(empty)) is None, "no .planning -> None no-op")

    # 5. STATE.md with NO frontmatter (example_project-style) -> None (fail-soft)
    proj2 = Path(tempfile.mkdtemp(prefix="kha-nofm-"))
    _write_state_md(proj2, "# example_project State\n\n## Active Mode\n- Status: active\n")
    _check(wu.read_planning_state(str(proj2)) is None, "no --- frontmatter -> None")

    # 6. frontmatter present but no gsd keys -> None (not a row of empty strings)
    proj3 = Path(tempfile.mkdtemp(prefix="kha-nokeys-"))
    _write_state_md(proj3, "---\nunrelated: yes\n---\n\nbody\n")
    _check(wu.read_planning_state(str(proj3)) is None, "frontmatter without gsd keys -> None")

    # 7. WRITE-side contract: none-safe prior-sha read (LOCK g5_sha_read_guard) +
    #    extra={'kha':..} roundtrip (the init.py consumer's data contract).
    _check((wu.read_work_unit("absent") or {}).get("extra", {}).get("planning_sha") is None,
           "none-safe prior-sha: read_work_unit None -> no crash")
    wu.record_work_unit("kha-sess", str(proj), "did kha work", now=1.0)  # legacy: no extra
    _check((wu.read_work_unit("kha-sess") or {}).get("extra", {}).get("planning_sha") is None,
           "none-safe prior-sha: breadcrumb without 'extra' -> no crash")
    wu.record_work_unit("kha-sess", str(proj), "did kha work", now=2.0,
                        extra={"kha": kha, "planning_sha": "deadbeef"})
    rec = wu.read_work_unit("kha-sess")
    _check(rec is not None and rec.get("extra", {}).get("planning_sha") == "deadbeef",
           "extra.planning_sha roundtrips through breadcrumb")
    _check(bool(rec) and rec.get("extra", {}).get("kha", {}).get("current_phase") == "3",
           "extra.kha.current_phase roundtrips (init.py consumer data contract)")


def main() -> int:
    tests = [
        test_throttle,
        test_breadcrumb_roundtrip,
        test_safe_name_traversal,
        test_latest_work_unit,
        test_gc_old_work_units,
        test_brain_divergence_and_autosave,
        test_force_autosave,
        test_cwd_match_same_tree,
        test_extract_next_steps_and_breadcrumb,
        test_c6_control_arm_not_a_writer,
        test_kha_planning_state_mirror,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            _fail(f"{t.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
