#!/usr/bin/env python3
"""Unit tests for the tree-structured work-record surface (debate-1781493074-c16jtw,
ontology sha1 0b1368fac840). Agent-free, deterministic. Pins W3/W6/W7/W9:

  W3 deepest-in_progress selection (ancestors propagate in_progress -> descend to
     deepest leaf; sibling tie -> first; none -> None).
  current_node_suffix: '현재: <id> ▸ <step> (<n>/<m>)' (parseable steps) / '현재: <id>'
     (free-text steps) / '' (malformed) — READ-ONLY.
  W6 resolution precedence: <project>/atlas/mirror/PHASES.md > global ~/.claude/
     HANDOFF.md > '' (fail-soft).
  W7 fold: the current-node folds INTO the single [work-resume] line (never a 4th
     status line).

Run: python tests/test_work_tree.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_PASS = 0
_FAIL = 0


def _ok(m: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [OK]   {m}")


def _fail(m: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {m}")


def _check(c: bool, m: str) -> None:
    _ok(m) if c else _fail(m)


_BLOCK = """# X

## Current Phase Block (machine-readable)

```yaml
phase_id: root
status: in_progress
sub_phases:
  - id: a
    status: done
  - id: b
    status: in_progress
    sub_phases:
      - id: grandchild
        status: in_progress
        step_1: done
        step_2: in_progress
        step_3: pending
```
"""

_FLAT = """## Current Phase Block (machine-readable)

```yaml
phase_id: solo
status: in_progress
step_1: done
step_2: in_progress
```
"""


def _fresh_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="wt-home-")).resolve()
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "state").mkdir(parents=True, exist_ok=True)
    os.environ["CLAUDE_HOME"] = str(home)
    for m in [k for k in list(sys.modules) if k == "lib" or k.startswith("lib.")]:
        del sys.modules[m]
    return home


def test_phase_tree_selection() -> None:
    print("test_phase_tree_selection (W3)")
    from lib import phase_tree
    from lib.phase_tree import Phase, Status
    root = Phase(id="root", status=Status.IN_PROGRESS, sub_phases=[
        Phase(id="a", status=Status.DONE),
        Phase(id="b", status=Status.IN_PROGRESS, sub_phases=[
            Phase(id="grandchild", status=Status.IN_PROGRESS)]),
    ])
    _check(phase_tree.deepest_in_progress(root).id == "grandchild", "(a) descends to deepest leaf, not root")
    _check(phase_tree.deepest_in_progress(Phase(id="r", status=Status.PENDING)) is None, "(b) no in_progress -> None")
    tie = Phase(id="r", status=Status.IN_PROGRESS, sub_phases=[
        Phase(id="first", status=Status.IN_PROGRESS), Phase(id="second", status=Status.IN_PROGRESS)])
    _check(phase_tree.deepest_in_progress(tie).id == "first", "(c) sibling tie -> first in list order")


def test_current_node_suffix() -> None:
    print("test_current_node_suffix (W7 format)")
    from lib import handoff_drift
    s = handoff_drift.current_node_suffix(_BLOCK)
    _check(s == "현재: grandchild ▸ step_2 (1/3)", f"(d) parseable steps -> n/m + current step (got {s!r})")
    ft = _BLOCK.replace("step_1: done", "step_1: 'wrote parser'").replace(
        "step_2: in_progress", "step_2: 'wiring'").replace("step_3: pending", "step_3: 'tests'")
    _check(handoff_drift.current_node_suffix(ft) == "현재: grandchild", "free-text steps -> just '현재: <id>'")
    _check(handoff_drift.current_node_suffix("no yaml here") == "", "(f) malformed -> '' fail-soft")
    _check(handoff_drift.current_node_suffix(_FLAT) == "현재: solo ▸ step_2 (1/2)", "flat steps-only tree -> root node")
    # REAL convention format: descriptive step values 'DONE (...)' / 'PENDING (...)' -> n/m
    conv = _BLOCK.replace("step_1: done", "step_1: DONE (shipped the parser)").replace(
        "step_2: in_progress", "step_2: PENDING (wiring it up)").replace("step_3: pending", "step_3: PENDING (tests)")
    _check(handoff_drift.current_node_suffix(conv) == "현재: grandchild ▸ step_2 (1/3)",
           "convention 'DONE (...)/PENDING (...)' steps -> n/m via leading-token inference")


def test_resolution_precedence() -> None:
    print("test_resolution_precedence (W6)")
    home = _fresh_home()
    from handlers.session import init
    # global: cwd under CLAUDE_HOME, HANDOFF.md present
    (home / "HANDOFF.md").write_text(_FLAT, encoding="utf-8")
    _check(init._current_node_suffix(str(home)) == "현재: solo ▸ step_2 (1/2)", "global HANDOFF.md read when cwd under CLAUDE_HOME")
    # per-project: a mirror project with PHASES.md takes precedence (different tree)
    proj = Path(tempfile.mkdtemp(prefix="wt-proj-")).resolve()
    (proj / "atlas" / "mirror").mkdir(parents=True)
    (proj / "atlas" / "mirror" / "manifest.json").write_text('{"scopes":[]}', encoding="utf-8")  # marker for find_mirror_root
    (proj / "atlas" / "mirror" / "PHASES.md").write_text(_BLOCK, encoding="utf-8")
    _check(init._current_node_suffix(str(proj)) == "현재: grandchild ▸ step_2 (1/3)", "(e) per-project PHASES.md beats global")
    # no marker, not under home -> silent
    bare = Path(tempfile.mkdtemp(prefix="wt-bare-")).resolve()
    _check(init._current_node_suffix(str(bare)) == "", "(f) no PHASES, not under home -> '' silent")
    import shutil
    for p in (home, proj, bare):
        shutil.rmtree(p, ignore_errors=True)


def test_fold_into_work_resume() -> None:
    print("test_fold_into_work_resume (W7)")
    home = _fresh_home()
    from handlers.session import init
    from lib import work_unit_store
    proj = Path(tempfile.mkdtemp(prefix="wt-fold-")).resolve()
    (proj / "atlas" / "mirror").mkdir(parents=True)
    (proj / "atlas" / "mirror" / "manifest.json").write_text('{"scopes":[]}', encoding="utf-8")
    (proj / "atlas" / "mirror" / "PHASES.md").write_text(_BLOCK, encoding="utf-8")
    # seed a work breadcrumb so the work-resume branch fires
    work_unit_store.record_work_unit("wt-sess", str(proj), "did the parser", next_steps="다음: 테스트")
    line = init._autopilot_resume_line(str(proj))
    _check(line is not None and "[work-resume]" in line, "work-resume line fires")
    _check(line is not None and "현재: grandchild" in line, "(g) current node FOLDED into the work-resume line")
    _check(line is not None and line.count("[work-resume]") == 1 and "\n" not in line, "ONE line — not a separate 4th line")
    import shutil
    for p in (home, proj):
        shutil.rmtree(p, ignore_errors=True)


def main() -> int:
    for t in (test_phase_tree_selection, test_current_node_suffix,
              test_resolution_precedence, test_fold_into_work_resume):
        try:
            t()
        except Exception as e:  # noqa: BLE001
            _fail(f"{t.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
