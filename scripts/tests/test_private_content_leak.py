#!/usr/bin/env python3
"""Unit tests for validators/private_content_leak.py."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import private_content_leak as pcl  # noqa: E402


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for path, content in files.items():
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


def test_scan_file_detects_example_app():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("ACME_INTERNAL Skeleton 프로젝트", encoding="utf-8")
        findings = pcl.scan_file(f)
        assert len(findings) == 1
        assert findings[0][1] == "ACME_INTERNAL"


def test_scan_file_detects_example_cloud():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("example_cloud package contains common code", encoding="utf-8")
        findings = pcl.scan_file(f)
        assert len(findings) == 1
        assert "example_cloud" in findings[0][1].lower()


def test_scan_file_detects_gp_auth_headers():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("GP-AUTH-ID is required", encoding="utf-8")
        findings = pcl.scan_file(f)
        assert len(findings) >= 1


def test_scan_file_detects_korean_ecommerce():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("이커머스 도메인 예시", encoding="utf-8")
        findings = pcl.scan_file(f)
        assert len(findings) >= 1
        assert findings[0][1] == "이커머스"


def test_scan_file_pointer_ok_skips_example_app():
    """Lines containing pointer markers like flutter/example_app/ are exempt."""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        # Mention of ACME_INTERNAL in same line as flutter/example_app/ → exempt
        f.write_text(
            "회사별 ACME_INTERNAL 컨벤션은 flutter/example_app/git-flow-company.md 참조",
            encoding="utf-8",
        )
        findings = pcl.scan_file(f)
        assert findings == []


def test_scan_file_pointer_ok_skips_java_example_app():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("ACME_INTERNAL-specific files are in java/example_app/", encoding="utf-8")
        findings = pcl.scan_file(f)
        assert findings == []


def test_scan_file_no_leak_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "test.md"
        f.write_text("Generic Spring Boot guide. No company-specific terms.",
                     encoding="utf-8")
        findings = pcl.scan_file(f)
        assert findings == []


def test_is_private_subtree():
    assert pcl._is_private_subtree(Path("skills/flutter/example_app/git.md"))
    assert pcl._is_private_subtree(Path("skills/flutter/example_app-agent/foo.md"))
    assert pcl._is_private_subtree(Path("skills/java/example_app/backend.md"))
    assert pcl._is_private_subtree(Path("skills/java/ecommerce/phase.md"))
    assert not pcl._is_private_subtree(Path("skills/_common/security.md"))
    assert not pcl._is_private_subtree(Path("skills/java/lang/jvm.md"))


def test_is_in_shared_subtree():
    assert pcl._is_in_shared_subtree(Path("skills/_common/security.md"))
    assert pcl._is_in_shared_subtree(Path("skills/java/lang/jvm.md"))
    assert pcl._is_in_shared_subtree(Path("skills/java/springboot-3.2/db.md"))
    assert pcl._is_in_shared_subtree(Path("skills/typescript/react/fsd.md"))
    assert not pcl._is_in_shared_subtree(Path("skills/flutter/example_app/foo.md"))
    assert not pcl._is_in_shared_subtree(Path("agents/kha-planner.md"))


def test_main_pass_on_clean_tree():
    """Integration: main() exits cleanly when shared trees have no leaks."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "skills/_common").mkdir(parents=True)
        (root / "skills/_common/clean.md").write_text(
            "Generic content. No private tokens.", encoding="utf-8"
        )
        cwd = os.getcwd()
        os.chdir(root)
        try:
            import io
            buf = io.StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                pcl.main()
            finally:
                sys.stdout = old
            out = buf.getvalue()
            assert "[PASS]" in out, out
        finally:
            os.chdir(cwd)


def main() -> int:
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failures.append((name, str(e)))
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            failures.append((name, repr(e)))
            print(f"  [ERR]  {name}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        return 1
    print(f"\n[OK] {test_count} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
