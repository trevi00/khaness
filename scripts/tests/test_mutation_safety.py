#!/usr/bin/env python3
"""Unit tests for validators/mutation_safety.py."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import mutation_safety as ms  # noqa: E402


def _wrap(*lines: str) -> list[str]:
    return list(lines)


def test_rm_rf_detected():
    lines = _wrap("# title", "```bash", "rm -rf /tmp/build", "```")
    assert ms._has_safety_nearby(lines, 2) is False
    # The destructive line is index 2; would-be finding requires no safety nearby.


def test_rm_single_f_not_detected():
    """`rm -f file.txt` (no recursive flag) is NOT flagged."""
    import re
    pattern = ms.DESTRUCTIVE_PATTERNS[0][0]
    assert re.search(pattern, "rm -f file.txt") is None
    assert re.search(pattern, "rm -rf dir/") is not None
    assert re.search(pattern, "rm -fr dir/") is not None


def test_safety_token_within_radius_defuses():
    lines = [
        "# safe section",
        "주의: 사용자 확인 후에만 실행:",
        "",
        "rm -rf /tmp/build",
        "",
    ]
    # safety token "사용자 확인" is 2 lines above destructive
    assert ms._has_safety_nearby(lines, 3) is True


def test_safety_token_outside_radius_not_defuses():
    lines = ["사용자 확인 위에"] + [""] * 12 + ["rm -rf /tmp/build"]
    # destructive at index 13, safety at index 0 → distance 13 > radius 10
    assert ms._has_safety_nearby(lines, 13) is False


def test_anti_pattern_token_defuses():
    lines = ["### anti-pattern: bad cmd", "rm -rf /"]
    assert ms._has_safety_nearby(lines, 1) is True


def test_drop_table_detected():
    import re
    pat = next(p for p, label in ms.DESTRUCTIVE_PATTERNS if label == "DROP TABLE")
    assert re.search(pat, "DROP TABLE users", re.IGNORECASE)
    assert re.search(pat, "drop table cart", re.IGNORECASE)


def test_force_with_lease_not_detected():
    """git push --force-with-lease는 안전한 형태 → 매칭 안 됨."""
    import re
    pat = next(p for p, label in ms.DESTRUCTIVE_PATTERNS if label == "git push --force")
    assert re.search(pat, "git push --force") is not None
    assert re.search(pat, "git push --force-with-lease=foo") is None


def test_docker_compose_down_v_detected():
    import re
    pats = [p for p, label in ms.DESTRUCTIVE_PATTERNS
            if "docker" in label.lower()]
    assert any(re.search(p, "docker compose down -v") for p in pats)
    assert any(re.search(p, "docker-compose down -v") for p in pats)


def test_scan_file_finds_unprotected_op(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("# unrelated\n```\nrm -rf /tmp/build\n```\n", encoding="utf-8")
    findings = ms.scan_file(f)
    assert len(findings) == 1
    assert findings[0][1] == "rm -rf"


def test_scan_file_skips_when_safety_nearby(tmp_path):
    f = tmp_path / "test.md"
    f.write_text(
        "주의: dev 로컬 환경에서만 사용.\n"
        "```\nrm -rf /tmp/build\n```\n",
        encoding="utf-8",
    )
    findings = ms.scan_file(f)
    assert findings == []


def main() -> int:
    import inspect
    import tempfile
    failures = []
    test_count = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        test_count += 1
        sig = inspect.signature(obj)
        try:
            if "tmp_path" in sig.parameters:
                with tempfile.TemporaryDirectory() as td:
                    obj(Path(td))
            else:
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
