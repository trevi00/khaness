"""test_skill_candidate_detector — unit tests for H1 detection 본문 (Track 2 H1).

Covers AC from HARNESS-APPLY.md H1 detector module spec (v15.4):
  AC-DET-S1: threshold candidate creation
  AC-DET-S2: idempotent suffix (deferred — phase 2 heuristic)
  AC-DET-S3: secret block, no secret body persisted
  AC-DET-S4: manifest schema fill
  AC-DET-E1: payload parse fail silent
  AC-DET-E2: write failure silent
  AC-DET-INV: no settings.json mutation in module source
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_LIB = _HERE.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import skill_candidate_detector as scd  # noqa: E402


class TestSkillCandidateDetector(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="scd-test-"))
        self._patches = [
            mock.patch.object(scd, "_TRACKER_ROOT", self._tmp / "tracker"),
            mock.patch.object(scd, "_CANDIDATES_ROOT", self._tmp / "candidates"),
            # Phase 2 raised default to 10; keep legacy AC tests using 3.
            mock.patch.object(scd, "_THRESHOLD", 3),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _payload(self, session_id: str = "sess-1", tool: str = "Read") -> str:
        return json.dumps({"session_id": session_id, "tool_name": tool})

    def test_below_threshold_no_candidate(self) -> None:
        for _ in range(2):
            scd.process_payload(self._payload())
        cand_dir = scd._CANDIDATES_ROOT
        self.assertFalse(cand_dir.exists() and list(cand_dir.glob("*.json")))

    def test_at_threshold_creates_candidate(self) -> None:
        for _ in range(3):
            scd.process_payload(self._payload())
        files = sorted(scd._CANDIDATES_ROOT.glob("skill-*.json"))
        self.assertEqual(len(files), 1)
        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["status"], "pending_review")
        self.assertEqual(data["schema"], "agentskills.io/v1")
        # AC-DET-S4: manifest schema fill
        m = data["manifest"]
        self.assertEqual(m["$schema"], "https://agentskills.io/schema/v1.json")
        self.assertEqual(m["activation"]["confirm_token"], "enable-skill")
        self.assertTrue(m["activation"]["requires_operator"])
        self.assertFalse(m["activation"]["auto"])
        # mutates flag: Read 는 false
        self.assertFalse(m["mutates"])

        # markdown trace 함께 존재
        md_files = sorted(scd._CANDIDATES_ROOT.glob("skill-*.md"))
        self.assertEqual(len(md_files), 1)
        self.assertIn("pending operator review", md_files[0].read_text(encoding="utf-8"))

    def test_edit_tool_mutates_flag(self) -> None:
        for _ in range(3):
            scd.process_payload(self._payload(tool="Edit"))
        files = list(scd._CANDIDATES_ROOT.glob("skill-*.json"))
        self.assertEqual(len(files), 1)
        with open(files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["manifest"]["mutates"])

    def test_secret_blocks_candidate_no_body_persisted(self) -> None:
        # AC-DET-S3: secret 포함 → blocked marker only, 실제 secret 본문 ⛔ 저장 안 됨
        real = scd._build_candidate("sess-1", "Read", "_", 3)
        tainted = replace(real, trace_md=real.trace_md + "\nsk-AbCdEfGhIjKlMnOpQrStUvWxYz123")
        with mock.patch.object(scd, "_build_candidate", return_value=tainted):
            for _ in range(3):
                scd.process_payload(self._payload())
        approved = sorted(scd._CANDIDATES_ROOT.glob("skill-*.json"))
        approved_only = [p for p in approved if "blocked" not in p.name]
        blocked = sorted(scd._CANDIDATES_ROOT.glob("*.blocked.json"))
        self.assertEqual(len(approved_only), 0)
        self.assertEqual(len(blocked), 1)
        marker = json.loads(blocked[0].read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "blocked_by_secret_scanner")
        # 실제 secret 본문 ⛔ 저장 안 됨
        self.assertNotIn("sk-AbCdEfGhIjKlMnOpQrStUvWxYz123", blocked[0].read_text(encoding="utf-8"))

    def test_secret_allowlist_passes(self) -> None:
        # AC-DET-S3 inverse: <API_KEY> placeholder는 allowlist → 통과
        real = scd._build_candidate("sess-1", "Read", "_", 3)
        with_placeholder = replace(real, trace_md=real.trace_md + "\n<API_KEY>")
        # placeholder만으로는 차단 안 되어야 함
        self.assertTrue(scd._secret_scan_pass(with_placeholder))

    def test_empty_or_invalid_payload_silent(self) -> None:
        # AC-DET-E1
        for raw in ("", "   ", "not-json", "null", "[]", "12345"):
            scd.process_payload(raw)
        if scd._TRACKER_ROOT.exists():
            self.assertEqual(list(scd._TRACKER_ROOT.glob("*.json")), [])
        if scd._CANDIDATES_ROOT.exists():
            self.assertEqual(list(scd._CANDIDATES_ROOT.glob("*")), [])

    def test_write_failure_silent(self) -> None:
        # AC-DET-E2
        with mock.patch.object(scd, "_write_candidate", side_effect=IOError("disk full")):
            for _ in range(3):
                scd.process_payload(self._payload())
        # 예외 propagate 없으면 통과

    def test_invariant_no_settings_mutation(self) -> None:
        # AC-DET-INV: module source가 settings.json을 write/mutate하지 않음.
        # Docstring/comment 안의 invariant 인용은 허용 — code path 검사만.
        import inspect
        import re
        source = inspect.getsource(scd)
        no_docstrings = re.sub(r'""".*?"""', "", source, flags=re.DOTALL)
        no_docstrings = re.sub(r"'''.*?'''", "", no_docstrings, flags=re.DOTALL)
        no_comments = re.sub(r"#.*", "", no_docstrings)
        self.assertNotIn("settings.json", no_comments)
        self.assertNotIn(".claude/settings", no_comments)

    def test_session_isolation(self) -> None:
        # 다른 세션끼리 tracker 독립
        for _ in range(2):
            scd.process_payload(self._payload(session_id="sess-A"))
        for _ in range(2):
            scd.process_payload(self._payload(session_id="sess-B"))
        # 두 세션 모두 threshold 미달 → candidate 0
        self.assertEqual(list(scd._CANDIDATES_ROOT.glob("skill-*.json")) if scd._CANDIDATES_ROOT.exists() else [], [])
        # 한 세션만 threshold 도달
        scd.process_payload(self._payload(session_id="sess-A"))
        files = list(scd._CANDIDATES_ROOT.glob("skill-*.json"))
        self.assertEqual(len(files), 1)


class TestPhase2PatternKey(unittest.TestCase):
    """Phase 2 (2026-06-01): (tool_name, pattern_key) composite tracking."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="scd-phase2-"))
        self._patches = [
            mock.patch.object(scd, "_TRACKER_ROOT", self._tmp / "tracker"),
            mock.patch.object(scd, "_CANDIDATES_ROOT", self._tmp / "candidates"),
            mock.patch.object(scd, "_THRESHOLD", 3),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _payload(self, tool: str, tool_input: dict, session: str = "sess-x") -> str:
        return json.dumps(
            {"session_id": session, "tool_name": tool, "tool_input": tool_input}
        )

    def test_pattern_key_bash_first_two_tokens(self) -> None:
        self.assertEqual(
            scd._pattern_key("Bash", {"command": "git status --short"}), "git status"
        )
        self.assertEqual(
            scd._pattern_key("Bash", {"command": "npm test"}), "npm test"
        )
        self.assertEqual(scd._pattern_key("Bash", {"command": "ls"}), "ls")
        self.assertEqual(scd._pattern_key("Bash", {"command": ""}), "_")

    def test_pattern_key_file_tools_extension(self) -> None:
        for tool in ("Edit", "Write", "Read", "MultiEdit", "NotebookEdit"):
            self.assertEqual(
                scd._pattern_key(tool, {"file_path": "/x/y/foo.py"}), ".py"
            )
        self.assertEqual(
            scd._pattern_key("Read", {"file_path": "/x/y/README"}), "no_ext"
        )

    def test_pattern_key_grep_glob_truncated(self) -> None:
        long_pat = "x" * 100
        key = scd._pattern_key("Grep", {"pattern": long_pat})
        self.assertEqual(len(key), scd._PATTERN_MAX_LEN)

    def test_pattern_key_webfetch_netloc(self) -> None:
        self.assertEqual(
            scd._pattern_key("WebFetch", {"url": "https://docs.example.com/x"}),
            "docs.example.com",
        )

    def test_pattern_key_websearch_first_two_words(self) -> None:
        self.assertEqual(
            scd._pattern_key("WebSearch", {"query": "spring boot 3.2 tutorial"}),
            "spring boot",
        )

    def test_pattern_key_skill_and_agent(self) -> None:
        self.assertEqual(
            scd._pattern_key("Skill", {"skill": "harness-debate"}), "harness-debate"
        )
        self.assertEqual(
            scd._pattern_key("Agent", {"subagent_type": "Explore"}), "Explore"
        )

    def test_pattern_key_no_input_fallback(self) -> None:
        self.assertEqual(scd._pattern_key("Read", None), "_")
        self.assertEqual(scd._pattern_key("UnknownTool", {"x": 1}), "_")

    def test_distinct_patterns_count_independently(self) -> None:
        # 2 bash commands, each 2x — neither hits threshold=3
        for _ in range(2):
            scd.process_payload(self._payload("Bash", {"command": "git status"}))
        for _ in range(2):
            scd.process_payload(self._payload("Bash", {"command": "npm test"}))
        self.assertEqual(
            list(scd._CANDIDATES_ROOT.glob("skill-*.json"))
            if scd._CANDIDATES_ROOT.exists()
            else [],
            [],
        )

    def test_same_pattern_hits_threshold(self) -> None:
        for _ in range(3):
            scd.process_payload(self._payload("Bash", {"command": "git status"}))
        files = list(scd._CANDIDATES_ROOT.glob("skill-*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["manifest"]["metadata"]["pattern_key"], "git status")
        self.assertEqual(data["manifest"]["metadata"]["tool_name"], "Bash")
        self.assertEqual(data["manifest"]["metadata"]["phase"], 2)
        self.assertIn("git status", data["manifest"]["description"])

    def test_cid_includes_pattern_slug(self) -> None:
        c1 = scd._build_candidate("sess-1", "Bash", "git status", 3)
        c2 = scd._build_candidate("sess-1", "Bash", "npm test", 3)
        self.assertNotEqual(c1.id, c2.id)
        self.assertNotIn("nop", c1.id)  # real pattern → real slug
        c_nop = scd._build_candidate("sess-1", "Bash", "_", 3)
        self.assertIn("nop", c_nop.id)

    def test_legacy_flat_tracker_resets(self) -> None:
        # Pre-load legacy {tool: int} tracker — Phase 2 should reset silently.
        scd._TRACKER_ROOT.mkdir(parents=True, exist_ok=True)
        legacy_path = scd._tracker_path("sess-legacy")
        legacy_path.write_text(json.dumps({"Bash": 99}), encoding="utf-8")
        # Single new payload — should NOT inherit the 99 count.
        scd.process_payload(
            self._payload("Bash", {"command": "git status"}, session="sess-legacy")
        )
        tracker = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(tracker["Bash"]["git status"], 1)
        # No candidate yet — count=1 < threshold=3.
        self.assertEqual(
            list(scd._CANDIDATES_ROOT.glob("skill-*.json"))
            if scd._CANDIDATES_ROOT.exists()
            else [],
            [],
        )


class TestPhase2Constants(unittest.TestCase):
    """No setUp patches — inspects unmodified module-load-time constants."""

    def test_default_threshold_is_10(self) -> None:
        self.assertEqual(scd._THRESHOLD, 10)

    def test_pattern_max_len_is_40(self) -> None:
        self.assertEqual(scd._PATTERN_MAX_LEN, 40)


class TestBuildCandidateFromReflection(unittest.TestCase):
    """S1 PR-B adapter tests — debate-1779255461-3fd149 LOCK D1+D2."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="scd-pr-b-"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_reflection(self, name: str, body: str) -> Path:
        p = self._tmp / name
        p.write_text(body, encoding="utf-8")
        return p

    def _structured_reflection(self, fp: str = "a" * 16, **payload) -> Path:
        defaults = {
            "axis": "completeness",
            "target_skill_hint": "skills/_common/foo.md",
            "gotcha_body": "wonder insight body",
        }
        defaults.update(payload)
        return self._write_reflection(
            f"reflection_001_{fp}.md",
            (
                "---\n"
                "orch_sid: test-orch\n"
                f"fingerprint: {fp}\n"
                "depth: 1\n"
                "ts: 1700000000\n"
                "structured_payload:\n"
                f"  axis: {defaults['axis']}\n"
                f"  target_skill_hint: {defaults['target_skill_hint']}\n"
                f"  gotcha_body: {defaults['gotcha_body']}\n"
                "---\n\n"
                "summary body\n"
            ),
        )

    def test_structured_reflection_yields_candidate(self) -> None:
        refl = self._structured_reflection()
        c = scd._build_candidate_from_reflection(refl)
        self.assertIsNotNone(c)
        self.assertEqual(c.id, f"skill-wonder-{'a' * 16}")
        self.assertEqual(c.manifest["category"], "wonder-gotcha")
        self.assertEqual(c.schema, "agentskills.io/v1")

    def test_manifest_provenance_under_metadata(self) -> None:
        refl = self._structured_reflection()
        c = scd._build_candidate_from_reflection(refl)
        meta = c.manifest.get("metadata")
        self.assertIsInstance(meta, dict)
        self.assertEqual(meta["source"], "wonder_reflection")
        self.assertEqual(meta["axis"], "completeness")
        self.assertEqual(meta["target_skill_hint"], "skills/_common/foo.md")
        self.assertEqual(meta["gotcha_body"], "wonder insight body")
        self.assertEqual(meta["reflection_fingerprint"], "a" * 16)
        self.assertIn("reflection_path", meta)
        self.assertEqual(meta["ts"], 1700000000)
        # gen-3 D2: no top-level kind field; category-based taxonomy
        self.assertNotIn("kind", c.manifest)

    def test_activation_block_enable_skill(self) -> None:
        refl = self._structured_reflection()
        c = scd._build_candidate_from_reflection(refl)
        self.assertEqual(c.manifest["activation"]["confirm_token"], "enable-skill")
        self.assertFalse(c.manifest["activation"]["auto"])
        self.assertTrue(c.manifest["activation"]["requires_operator"])

    def test_target_skill_hint_null_yaml_to_python_none(self) -> None:
        refl = self._write_reflection(
            "reflection_001_" + "b" * 16 + ".md",
            (
                "---\n"
                "orch_sid: test-orch\n"
                f"fingerprint: {'b' * 16}\n"
                "depth: 1\n"
                "ts: 1700000000\n"
                "structured_payload:\n"
                "  axis: stability\n"
                "  target_skill_hint: null\n"
                "  gotcha_body: body without hint\n"
                "---\n\nsummary\n"
            ),
        )
        c = scd._build_candidate_from_reflection(refl)
        self.assertIsNone(c.manifest["metadata"]["target_skill_hint"])

    def test_legacy_reflection_returns_none(self) -> None:
        """gen-3 C1 silent-skip: legacy reflections without structured_payload."""
        refl = self._write_reflection(
            "reflection_001_" + "c" * 16 + ".md",
            (
                "---\n"
                "orch_sid: legacy\n"
                f"fingerprint: {'c' * 16}\n"
                "depth: 1\n"
                "ts: 1700000000\n"
                "---\n\nlegacy body only\n"
            ),
        )
        self.assertIsNone(scd._build_candidate_from_reflection(refl))

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(
            scd._build_candidate_from_reflection(self._tmp / "does-not-exist.md")
        )

    def test_malformed_frontmatter_returns_none(self) -> None:
        refl = self._write_reflection("bad.md", "not-a-frontmatter-document\n")
        self.assertIsNone(scd._build_candidate_from_reflection(refl))

    def test_bad_fingerprint_length_returns_none(self) -> None:
        refl = self._write_reflection(
            "reflection_001_short.md",
            (
                "---\n"
                "orch_sid: test-orch\n"
                "fingerprint: short\n"
                "depth: 1\n"
                "ts: 1700000000\n"
                "structured_payload:\n"
                "  axis: x\n"
                "  target_skill_hint: null\n"
                "  gotcha_body: y\n"
                "---\n\ns\n"
            ),
        )
        self.assertIsNone(scd._build_candidate_from_reflection(refl))

    def test_secret_scan_pass_compatible(self) -> None:
        """Adapter output is consumable by existing _secret_scan_pass."""
        refl = self._structured_reflection()
        c = scd._build_candidate_from_reflection(refl)
        self.assertTrue(scd._secret_scan_pass(c))

    def test_trace_md_contains_axis_and_body(self) -> None:
        refl = self._structured_reflection(
            axis="usability", gotcha_body="trace md body"
        )
        c = scd._build_candidate_from_reflection(refl)
        self.assertIn("usability", c.trace_md)
        self.assertIn("trace md body", c.trace_md)
        self.assertIn("`enable-skill`", c.trace_md)

    def test_idempotent_cid_for_same_fingerprint(self) -> None:
        """cid stable when fingerprint unchanged — D6 fingerprint idempotency."""
        refl1 = self._structured_reflection(fp="d" * 16)
        c1 = scd._build_candidate_from_reflection(refl1)
        # Re-emit same reflection (would happen on re-strike with same fp)
        refl2 = self._write_reflection(
            f"reflection_002_{'d' * 16}.md",  # different depth, same fp
            (
                "---\n"
                "orch_sid: test-orch\n"
                f"fingerprint: {'d' * 16}\n"
                "depth: 2\n"
                "ts: 1700000099\n"
                "structured_payload:\n"
                "  axis: completeness\n"
                "  target_skill_hint: skills/_common/foo.md\n"
                "  gotcha_body: wonder insight body\n"
                "---\n\nsummary\n"
            ),
        )
        c2 = scd._build_candidate_from_reflection(refl2)
        self.assertEqual(c1.id, c2.id)


def main() -> int:
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestSuite()
    suite.addTests(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestSkillCandidateDetector)
    )
    suite.addTests(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestPhase2PatternKey)
    )
    suite.addTests(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestPhase2Constants)
    )
    suite.addTests(
        unittest.defaultTestLoader.loadTestsFromTestCase(TestBuildCandidateFromReflection)
    )
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
