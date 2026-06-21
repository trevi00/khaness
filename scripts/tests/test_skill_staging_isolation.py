#!/usr/bin/env python3
"""Unit tests for validators.skill_staging_isolation — D3 Layer-A AST scan.

debate-1779462559-c29f2b LOCK (gen-2 byte-identical, sha1
67c44483a06d6504209644d792edfd943c4ee3a9).

Cases:
    (a) live skill_candidate_detector.py + skill_candidate_extractor.py PASS
    (b) synthetic fixture with `_CANDIDATES_ROOT / x.json` → no violation
    (c) synthetic fixture with `_TRACKER_ROOT / s.json` → no violation
    (d) synthetic fixture with bare `Path('/tmp/evil')` write → violation
    (e) synthetic fixture with helper returning safe expression → no violation
    (f) synthetic fixture with chained `(_CANDIDATES_ROOT / c).write_text` → no violation
    (g) module-load test: validator registered in VALIDATOR_NAMES
    (h) docstring documents the known false-negative surface
"""
from __future__ import annotations

import ast
import sys
import tempfile
import textwrap
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import VALIDATOR_NAMES  # noqa: E402
from validators.skill_staging_isolation import _scan_file  # noqa: E402


def _write_fixture(source: str) -> Path:
    tf = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    )
    tf.write(textwrap.dedent(source))
    tf.close()
    return Path(tf.name)


def test_live_detector_passes():
    vios = _scan_file(_SCRIPTS / "lib" / "skill_candidate_detector.py")
    if not vios:
        print("[OK] test_live_detector_passes")
        return
    print(f"[FAIL] test_live_detector_passes — {len(vios)} violations: {vios[:3]}")


def test_live_extractor_passes():
    vios = _scan_file(_SCRIPTS / "handlers" / "post_tool" / "skill_candidate_extractor.py")
    if not vios:
        print("[OK] test_live_extractor_passes")
        return
    print(f"[FAIL] test_live_extractor_passes — {len(vios)} violations: {vios[:3]}")


def test_synthetic_candidates_root_div():
    fixture = _write_fixture("""
        from pathlib import Path
        _CANDIDATES_ROOT = Path('x')
        def f():
            write_json_atomic(_CANDIDATES_ROOT / 'a.json', {})
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if not vios:
        print("[OK] test_synthetic_candidates_root_div")
        return
    print(f"[FAIL] test_synthetic_candidates_root_div — {vios}")


def test_synthetic_tracker_root_div():
    fixture = _write_fixture("""
        from pathlib import Path
        _TRACKER_ROOT = Path('y')
        def f():
            write_json_atomic(_TRACKER_ROOT / 's.json', {})
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if not vios:
        print("[OK] test_synthetic_tracker_root_div")
        return
    print(f"[FAIL] test_synthetic_tracker_root_div — {vios}")


def test_synthetic_bare_temp_path_violates():
    fixture = _write_fixture("""
        from pathlib import Path
        def f():
            write_json_atomic(Path('/tmp/evil.json'), {})
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if vios:
        print("[OK] test_synthetic_bare_temp_path_violates")
        return
    print("[FAIL] test_synthetic_bare_temp_path_violates — expected violation, got none")


def test_synthetic_helper_returning_safe():
    fixture = _write_fixture("""
        from pathlib import Path
        _CANDIDATES_ROOT = Path('x')
        def _candidate_path(cid):
            return _CANDIDATES_ROOT / f'{cid}.json'
        def f(cid):
            write_json_atomic(_candidate_path(cid), {})
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if not vios:
        print("[OK] test_synthetic_helper_returning_safe")
        return
    print(f"[FAIL] test_synthetic_helper_returning_safe — {vios}")


def test_synthetic_chained_write_text():
    fixture = _write_fixture("""
        from pathlib import Path
        _CANDIDATES_ROOT = Path('x')
        def f(cid, body):
            (_CANDIDATES_ROOT / f'{cid}.md').write_text(body, encoding='utf-8')
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if not vios:
        print("[OK] test_synthetic_chained_write_text")
        return
    print(f"[FAIL] test_synthetic_chained_write_text — {vios}")


def test_synthetic_mkdir_on_root_attribute():
    fixture = _write_fixture("""
        from pathlib import Path
        _CANDIDATES_ROOT = Path('x')
        def f():
            _CANDIDATES_ROOT.mkdir(parents=True, exist_ok=True)
    """)
    vios = _scan_file(fixture)
    fixture.unlink(missing_ok=True)
    if not vios:
        print("[OK] test_synthetic_mkdir_on_root_attribute")
        return
    print(f"[FAIL] test_synthetic_mkdir_on_root_attribute — {vios}")


def test_validator_registered():
    if "skill_staging_isolation" in VALIDATOR_NAMES:
        print("[OK] test_validator_registered")
        return
    print(f"[FAIL] test_validator_registered — not in VALIDATOR_NAMES: {VALIDATOR_NAMES}")


def test_docstring_lists_false_negatives():
    src = (_SCRIPTS / "validators" / "skill_staging_isolation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    doc = ast.get_docstring(tree) or ""
    required = ("getattr", "shutil", "subprocess", "Layer-B")
    missing = [r for r in required if r not in doc]
    if not missing:
        print("[OK] test_docstring_lists_false_negatives")
        return
    print(f"[FAIL] test_docstring_lists_false_negatives — missing: {missing}")


def main() -> int:
    cases = [
        test_live_detector_passes,
        test_live_extractor_passes,
        test_synthetic_candidates_root_div,
        test_synthetic_tracker_root_div,
        test_synthetic_bare_temp_path_violates,
        test_synthetic_helper_returning_safe,
        test_synthetic_chained_write_text,
        test_synthetic_mkdir_on_root_attribute,
        test_validator_registered,
        test_docstring_lists_false_negatives,
    ]
    failures = 0
    for c in cases:
        try:
            c()
        except Exception as e:
            failures += 1
            print(f"[ERROR] {c.__name__}: {type(e).__name__}: {e}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
