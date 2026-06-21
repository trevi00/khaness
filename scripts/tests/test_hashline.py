#!/usr/bin/env python3
"""Unit tests for validators/hashline.py.

Tests both the regex anchor scanner and the main() driver. Uses tempfile
to construct synthetic projects without touching real harness state.

Run:
    cd ~/.claude/scripts && python -m tests.test_hashline
    cd ~/.claude/scripts && python tests/test_hashline.py
Both produce: "[OK] N tests passed" or first failure with traceback.

Pattern (이 파일이 다른 validator 테스트의 모범):
- 테스트 함수: test_<case>() 시그니처, 실패 시 AssertionError로 즉시 중단
- main()에 모든 테스트 등록 + 카운트 + 일괄 실행
- 외부 의존: tempfile + subprocess (실제 main() 호출은 cwd 변경 필요)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import hashline  # noqa: E402


# === Anchor regex tests ===

def test_anchor_markdown_form():
    text = "# ! my-id My description here"
    matches = list(hashline.ANCHOR_RE.finditer(text))
    assert len(matches) == 1, f"expected 1 match, got {len(matches)}"
    assert matches[0].group(1) == "my-id"


def test_anchor_html_comment_form():
    text = "<!-- ! comment-id Some doc -->"
    matches = list(hashline.ANCHOR_RE.finditer(text))
    assert len(matches) == 1, f"expected 1 match, got {len(matches)}"
    assert matches[0].group(3) == "comment-id"


def test_anchor_rejects_shebang():
    # `#!/usr/bin/env python` must NOT match (no space after !, slash not in [A-Za-z0-9-])
    text = "#!/usr/bin/env python"
    matches = list(hashline.ANCHOR_RE.finditer(text))
    assert len(matches) == 0, f"shebang should not match, got {len(matches)}"


def test_anchor_rejects_id_too_long():
    long_id = "x" * 33  # 33 chars > 32 max
    text = f"# ! {long_id} desc"
    matches = list(hashline.ANCHOR_RE.finditer(text))
    assert len(matches) == 0, "ID > 32 chars must reject"


def test_anchor_rejects_invalid_chars_in_id():
    text = "# ! has_underscore description"  # underscore not in [A-Za-z0-9-]
    matches = list(hashline.ANCHOR_RE.finditer(text))
    assert len(matches) == 0, "underscore in ID must reject"


# === _scan_file tests ===

def test_scan_no_anchors():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "plain.md"
        p.write_text("# Heading\n\nNo anchors here.\n", encoding="utf-8")
        errors, warnings = hashline._scan_file(p)
        assert errors == [], f"expected no errors, got {errors}"
        assert warnings == [], f"expected no warnings, got {warnings}"


def test_scan_duplicate_id():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dup.md"
        p.write_text(
            "# ! foo first occurrence\n"
            "Some content.\n"
            "# ! foo second occurrence\n",
            encoding="utf-8",
        )
        errors, warnings = hashline._scan_file(p)
        assert len(errors) == 1, f"expected 1 duplicate error, got {len(errors)}"
        kind, line_no, msg = errors[0]
        assert kind == "duplicate-id"
        assert line_no == 3
        assert "'foo'" in msg


def test_scan_unique_ids_pass():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ok.md"
        p.write_text(
            "# ! one first\n"
            "# ! two second\n"
            "# ! three third\n",
            encoding="utf-8",
        )
        errors, warnings = hashline._scan_file(p)
        assert errors == [], f"expected no errors, got {errors}"


def test_scan_read_error():
    # Pass a path that doesn't exist — should produce a read-error warning.
    p = Path(tempfile.gettempdir()) / "definitely-does-not-exist-12345.md"
    if p.exists():
        p.unlink()
    errors, warnings = hashline._scan_file(p)
    assert errors == []
    assert len(warnings) == 1
    assert warnings[0][0] == "read-error"


# === Whitelist tests ===

def test_whitelist_skips_node_modules():
    p = Path("project") / "node_modules" / "pkg" / "CLAUDE.md"
    assert hashline._is_whitelisted(p), "node_modules path must be whitelisted"


def test_whitelist_skips_omc_reference():
    p = Path("state") / "omc-reference" / "CLAUDE.md"
    assert hashline._is_whitelisted(p), "omc-reference path must be whitelisted"


def test_whitelist_does_not_skip_normal_skill():
    p = Path("project") / ".claude" / "skills" / "_common" / "convention.md"
    assert not hashline._is_whitelisted(p), "normal skill path must NOT be whitelisted"


# === main() driver tests ===

def _run_main_in(cwd: Path) -> str:
    """Run hashline.main() with cwd swapped, capture stdout, return text."""
    saved_cwd = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            hashline.main()
    finally:
        os.chdir(saved_cwd)
    return buf.getvalue()


def test_main_no_targets():
    with tempfile.TemporaryDirectory() as td:
        out = _run_main_in(Path(td))
        assert "[PASS]" in out
        assert "anchor 파일 없음" in out


def test_main_pass_with_unique_ids():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "CLAUDE.md").write_text("# ! alpha first\n", encoding="utf-8")
        out = _run_main_in(root)
        assert "[PASS]" in out
        assert "[FAIL]" not in out


def test_main_fail_on_duplicate():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "CLAUDE.md").write_text(
            "# ! same first\n"
            "# ! same second\n",
            encoding="utf-8",
        )
        out = _run_main_in(root)
        assert "[FAIL]" in out
        assert "duplicate-id" in out
        assert "'same'" in out


# === Test driver ===

TESTS = [
    test_anchor_markdown_form,
    test_anchor_html_comment_form,
    test_anchor_rejects_shebang,
    test_anchor_rejects_id_too_long,
    test_anchor_rejects_invalid_chars_in_id,
    test_scan_no_anchors,
    test_scan_duplicate_id,
    test_scan_unique_ids_pass,
    test_scan_read_error,
    test_whitelist_skips_node_modules,
    test_whitelist_skips_omc_reference,
    test_whitelist_does_not_skip_normal_skill,
    test_main_no_targets,
    test_main_pass_with_unique_ids,
    test_main_fail_on_duplicate,
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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
