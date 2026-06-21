#!/usr/bin/env python3
"""Tests for validators.atlas_frontmatter._check_one (M3 — close the 0-coverage gap).

The atlas_frontmatter validator's main() is run by run_all.py but had NO unit test,
so its per-file frontmatter rules were unverified (the validator skips entirely when
no ATLAS_DIR exists, masking rule regressions). These exercise _check_one directly
with fixtures. Auto-discovered by run_units.py via the top-level main() -> int.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


_VALID = """---
id: my-note
type: concept
activation: always
description: a valid atlas note
created: 2026-06-16
updated: 2026-06-16
last_writer: claude
status: active
---
body text
"""


def _write(td: Path, body: str) -> Path:
    p = td / "note.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_no_frontmatter_fails():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        issues = _check_one(_write(Path(td), "no fences here\njust body\n"))
        assert any(sev == "FAIL" and "no frontmatter" in msg for sev, msg in issues)


def test_valid_frontmatter_no_issues():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        issues = _check_one(_write(Path(td), _VALID))
        assert issues == [], f"expected clean, got {issues}"


def test_missing_required_key_fails():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        body = _VALID.replace("status: active\n", "")  # drop one required key
        issues = _check_one(_write(Path(td), body))
        assert any(
            sev == "FAIL" and "missing required key: status" in msg
            for sev, msg in issues
        )


def test_bad_type_enum_fails():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        body = _VALID.replace("type: concept", "type: bogus")
        issues = _check_one(_write(Path(td), body))
        assert any(sev == "FAIL" and msg.startswith("type=") for sev, msg in issues)


def test_bad_id_warns():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        body = _VALID.replace("id: my-note", "id: Bad_ID")  # uppercase -> not kebab
        issues = _check_one(_write(Path(td), body))
        assert any(sev == "WARN" and msg.startswith("id=") for sev, msg in issues)


def test_glob_activation_requires_globs():
    from validators.atlas_frontmatter import _check_one
    with tempfile.TemporaryDirectory() as td:
        body = _VALID.replace("activation: always", "activation: glob")
        issues = _check_one(_write(Path(td), body))
        assert any(
            sev == "FAIL" and "globs field missing" in msg for sev, msg in issues
        )


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
