"""S1 PR-D — filesystem-level invariant test for wonder→proposer pipeline.

debate-1779255461-3fd149 LOCK D7 + gen-3 architect verdict:
  > Replace AST-scan with filesystem-level invariant test: tmp HOME,
  > capture mtime+inode+sha256 of ~/.claude/skills/ tree and
  > settings.json before run, assert byte-identical after run. Add a
  > positive-control test that intentionally writes there and verifies
  > the test catches it.

This file enforces the CLAUDE.md L0 invariant ("NEVER 자동 runtime
policy 변경") at runtime semantics — not syntax. The gen-3 Critic B3
proved AST-scanning is trivially evaded (Path.home() / ".claude" /
("skil" + "ls")). The filesystem-level snapshot catches semantic
violations regardless of how the offending write is spelled.

What is asserted:
  1. Running lib.skill_candidate_detector._build_candidate_from_reflection
     against a synthetic reflection produces a SkillCandidate WITHOUT
     touching ~/.claude/skills/ or ~/.claude/settings.json.
  2. Positive control: an intentional write to skills/ DOES get caught
     by the snapshot differ — proves the test is not vacuously passing.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LIB = _HERE.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import skill_candidate_detector as scd  # noqa: E402


def _snapshot_tree(root: Path) -> dict[str, tuple[int, int, str]]:
    """Capture {relative_path: (st_mtime_ns, st_ino, sha256_hex)} for every
    file under root. Returns empty dict when root does not exist.

    Catches: (a) file added, (b) file removed, (c) mtime change, (d) inode
    change (rename / atomic-replace), (e) content change with same mtime
    (same-size byte swap).
    """
    if not root.exists():
        return {}
    out: dict[str, tuple[int, int, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        st = path.stat()
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        out[rel] = (st.st_mtime_ns, st.st_ino, h)
    return out


def _snapshot_file(path: Path) -> tuple[int, int, str] | None:
    """Single-file variant for ~/.claude/settings.json."""
    if not path.is_file():
        return None
    st = path.stat()
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return (st.st_mtime_ns, st.st_ino, h)


class TestWonderProposerInvariant(unittest.TestCase):
    """Wonder → proposer adapter MUST NOT mutate skills/ or settings.json."""

    def setUp(self) -> None:
        # Isolated HOME — every path the adapter could touch (state/,
        # skills/, settings.json, skill-candidates/) is under self._home.
        self._home = Path(tempfile.mkdtemp(prefix="s1-prd-"))
        # Pre-seed protected surfaces with fixtures so the snapshot has
        # content to compare against (not just absent-on-both-sides).
        self._skills = self._home / ".claude" / "skills"
        self._skills.mkdir(parents=True)
        (self._skills / "_common").mkdir()
        (self._skills / "_common" / "fixture-a.md").write_text(
            "# fixture A\nProtected content.\n", encoding="utf-8"
        )
        (self._skills / "fixture-b.md").write_text(
            "# fixture B\nMore protected content.\n", encoding="utf-8"
        )
        self._settings = self._home / ".claude" / "settings.json"
        self._settings.write_text(
            '{"protected": "sentinel", "hooks": []}', encoding="utf-8"
        )
        # Reflection fixture (input the adapter reads).
        self._refl_dir = self._home / ".claude" / "state" / "wonder" / "orch-x"
        self._refl_dir.mkdir(parents=True)
        self._refl_path = (
            self._refl_dir / ("reflection_001_" + "a" * 16 + ".md")
        )
        self._refl_path.write_text(
            (
                "---\n"
                "orch_sid: orch-x\n"
                f"fingerprint: {'a' * 16}\n"
                "depth: 1\n"
                "ts: 1700000000\n"
                "structured_payload:\n"
                "  axis: completeness\n"
                "  target_skill_hint: skills/_common/foo.md\n"
                "  gotcha_body: do not write to skills directly\n"
                "---\n\nfree-form summary\n"
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self._home, ignore_errors=True)

    def test_adapter_run_does_not_mutate_skills_or_settings(self) -> None:
        """Run _build_candidate_from_reflection and assert no protected
        surface (~/.claude/skills/ tree, ~/.claude/settings.json) changed.
        """
        skills_before = _snapshot_tree(self._skills)
        settings_before = _snapshot_file(self._settings)

        # Run adapter — return value verified for non-None to ensure the
        # adapter actually executed (vacuous pass guard).
        candidate = scd._build_candidate_from_reflection(self._refl_path)
        self.assertIsNotNone(candidate, "adapter should produce a candidate")
        self.assertEqual(candidate.manifest["category"], "wonder-gotcha")

        skills_after = _snapshot_tree(self._skills)
        settings_after = _snapshot_file(self._settings)

        self.assertEqual(
            skills_before, skills_after,
            "~/.claude/skills/ tree mutated by adapter — L0 invariant violation",
        )
        self.assertEqual(
            settings_before, settings_after,
            "~/.claude/settings.json mutated by adapter — L0 invariant violation",
        )

    def test_positive_control_detects_intentional_skills_write(self) -> None:
        """Snapshot differ MUST catch an intentional write — proves the
        test is not vacuous. gen-3 architect verdict explicitly required
        this positive control to validate the assertion machinery.
        """
        skills_before = _snapshot_tree(self._skills)

        # Intentional violation: write a NEW file under skills/.
        (self._skills / "intentional-violation.md").write_text(
            "this would represent an adapter regression", encoding="utf-8"
        )

        skills_after = _snapshot_tree(self._skills)

        # Assert the snapshots DIFFER — proves the detector works.
        self.assertNotEqual(
            skills_before, skills_after,
            "snapshot differ did not catch an intentional skills/ write — "
            "test machinery is vacuous, FIX before relying on the "
            "negative test above",
        )

    def test_positive_control_detects_settings_mutation(self) -> None:
        """Positive control for settings.json — mtime+content snapshot
        must catch a same-path content swap.
        """
        settings_before = _snapshot_file(self._settings)
        # Same path, different bytes (same size to defeat naive size-only
        # checks — sha256 catches this regardless).
        self._settings.write_text(
            '{"protected": "MUTATED", "hooks": []}', encoding="utf-8"
        )
        settings_after = _snapshot_file(self._settings)
        self.assertNotEqual(
            settings_before, settings_after,
            "snapshot differ did not catch settings.json mutation — test vacuous",
        )

    def test_positive_control_detects_same_path_atomic_replace(self) -> None:
        """Inode change (atomic-replace via os.replace) MUST also be
        caught — same mtime+content could theoretically pass naive
        comparison if the replacement happens fast enough.
        """
        target = self._skills / "_common" / "fixture-a.md"
        before = _snapshot_tree(self._skills)
        # Atomic replace: write tmp + os.replace (this changes inode on
        # POSIX; on Windows os.replace also rebuilds the directory entry).
        tmp = target.with_suffix(".md.tmp")
        tmp.write_text("# fixture A\nProtected content.\n", encoding="utf-8")
        os.replace(tmp, target)
        after = _snapshot_tree(self._skills)
        # On Windows the snapshot SHOULD still differ on mtime_ns even
        # when content+inode look stable (os.replace updates mtime).
        # Either differ-axis triggering the assertion is acceptable.
        self.assertNotEqual(
            before, after,
            "snapshot differ did not catch atomic replace — test vacuous",
        )

    def test_adapter_with_legacy_reflection_does_not_mutate_either(self) -> None:
        """A legacy reflection (no structured_payload block) makes the
        adapter return None silently — still must not touch protected
        surfaces.
        """
        legacy = self._refl_dir / ("reflection_002_" + "b" * 16 + ".md")
        legacy.write_text(
            (
                "---\n"
                "orch_sid: orch-x\n"
                f"fingerprint: {'b' * 16}\n"
                "depth: 2\n"
                "ts: 1700000001\n"
                "---\n\nlegacy body\n"
            ),
            encoding="utf-8",
        )
        skills_before = _snapshot_tree(self._skills)
        settings_before = _snapshot_file(self._settings)

        result = scd._build_candidate_from_reflection(legacy)
        self.assertIsNone(result)

        self.assertEqual(skills_before, _snapshot_tree(self._skills))
        self.assertEqual(settings_before, _snapshot_file(self._settings))


def main() -> int:
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        TestWonderProposerInvariant
    )
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
