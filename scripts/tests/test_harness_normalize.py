#!/usr/bin/env python3
"""Unit tests for cli/harness_normalize.py."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import harness_normalize as hn  # noqa: E402


def test_classification_has_16_entries():
    assert len(hn.HARNESS_COMMANDS) == 16, f"expected 16, got {len(hn.HARNESS_COMMANDS)}"


def test_every_entry_has_4_fields():
    required = {"category", "mutates", "long-running", "external-deps"}
    for name, meta in hn.HARNESS_COMMANDS.items():
        missing = required - set(meta.keys())
        assert not missing, f"{name}: missing fields {missing}"


def test_external_deps_field_present():
    """external-deps differentiates harness commands from kha skills."""
    for name, meta in hn.HARNESS_COMMANDS.items():
        assert "external-deps" in meta, f"{name}: external-deps missing"


def test_team_has_correct_external_deps():
    """harness-team needs claude-cli, codex-cli, psmux."""
    deps = hn.HARNESS_COMMANDS["harness-team"]["external-deps"]
    for d in ("claude-cli", "codex-cli", "psmux"):
        assert d in deps, f"harness-team missing {d}"


def test_normalize_frontmatter_adds_4_fields():
    content = "---\nname: harness-debate\ndescription: x\n---\nbody\n"
    out = hn.normalize_frontmatter(content, "harness-debate")
    for key, val in hn.HARNESS_COMMANDS["harness-debate"].items():
        assert f"{key}: {val}" in out, f"missing {key}: {val}"
    assert "name: harness-debate" in out  # preserved


def test_normalize_frontmatter_preserves_other_fields():
    content = (
        "---\n"
        "name: harness-debate\n"
        "argument-hint: <topic>\n"
        "allowed-tools: Read, Write\n"
        "---\n"
        "body\n"
    )
    out = hn.normalize_frontmatter(content, "harness-debate")
    assert "argument-hint: <topic>" in out
    assert "allowed-tools: Read, Write" in out


def test_append_sections_adds_5_for_long_running():
    content = "---\nname: harness-debate\n---\n# Body\n"
    out = hn.append_missing_sections(content, "harness-debate")
    for sec in ("Output", "Failure behavior", "Gate summary",
                "Retry / Resume", "Boundary with other commands"):
        assert f"## {sec}" in out, f"missing ## {sec}"


def test_append_sections_no_retry_for_short_running():
    content = "---\nname: harness-help-no-such-cmd\n---\n# Body\n"
    # Use a real short-running entry: harness-trigger-summary
    content2 = "---\nname: harness-trigger-summary\n---\n# Body\n"
    out = hn.append_missing_sections(content2, "harness-trigger-summary")
    assert "## Retry / Resume" not in out
    # but other 4 sections present
    for sec in ("Output", "Failure behavior", "Gate summary",
                "Boundary with other commands"):
        assert f"## {sec}" in out


def test_append_sections_idempotent():
    content = (
        "---\nname: harness-debate\n---\n"
        "# Body\n\n"
        "## Output\nexisting\n\n"
        "## Failure behavior\nexisting\n\n"
        "## Gate summary\nexisting\n\n"
        "## Retry / Resume\nexisting\n\n"
        "## Boundary with other commands\nexisting\n"
    )
    out = hn.append_missing_sections(content, "harness-debate")
    assert out == content


def test_normalize_one_pipeline_idempotent():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "harness-debate.md"
        p.write_text("---\nname: harness-debate\n---\n# Body\n", encoding="utf-8")
        ch1, c1 = hn.normalize_one(p, "harness-debate")
        assert ch1 is True
        p.write_text(c1, encoding="utf-8")
        ch2, c2 = hn.normalize_one(p, "harness-debate")
        assert ch2 is False, "second pass must be idempotent"


def test_check_returns_list_of_issues_when_drift():
    """Synthetic command file with wrong frontmatter -> issues reported."""
    saved = hn.COMMANDS_DIR
    with tempfile.TemporaryDirectory() as td:
        try:
            hn.COMMANDS_DIR = Path(td)
            (Path(td) / "harness-debate.md").write_text(
                "---\nname: harness-debate\ncategory: wrong\n---\nbody\n",
                encoding="utf-8",
            )
            ok, issues = hn.check()
            assert ok is False
            assert any("category=design" in i for i in issues)
        finally:
            hn.COMMANDS_DIR = saved


def main() -> int:
    tests = [
        test_classification_has_16_entries,
        test_every_entry_has_4_fields,
        test_external_deps_field_present,
        test_team_has_correct_external_deps,
        test_normalize_frontmatter_adds_4_fields,
        test_normalize_frontmatter_preserves_other_fields,
        test_append_sections_adds_5_for_long_running,
        test_append_sections_no_retry_for_short_running,
        test_append_sections_idempotent,
        test_normalize_one_pipeline_idempotent,
        test_check_returns_list_of_issues_when_drift,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
