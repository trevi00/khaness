#!/usr/bin/env python3
"""Tests for engine/trigger_summary.py — structured (JSON) summary seam."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _write_telemetry(tdp: Path, records: list[dict]) -> None:
    (tdp / "debate-triggers.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


_RECORDS = [
    {"ts": "2026-06-18T01:00:00Z", "strict_design": True, "phases": ["implement"],
     "cwd": "/a", "prompt_preview": "design the thing"},
    {"ts": "2026-06-18T02:00:00Z", "strict_design": True, "phases": ["implement", "plan"], "cwd": "/a"},
    {"ts": "2026-06-18T03:00:00Z", "strict_design": False, "phases": ["implement"], "cwd": "/b"},
]


def test_summarize_data_schema_and_counts():
    import engine.trigger_summary as ts
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_telemetry(tdp, _RECORDS)
        with mock.patch.object(ts, "TELEMETRY_DIR", tdp), \
             mock.patch.object(ts, "load_acknowledged", lambda: set()):
            d = ts.summarize_data()
        assert d["schema_version"] == "1"
        assert d["total_prompts"] == 3
        assert d["strict_design_matched"] == 2
        assert d["pending"] == 2 and d["acknowledged"] == 0
        assert d["last_strict_ts"] == "2026-06-18T02:00:00Z"
        # phase aggregation: implement in all 3, plan in 1
        phases = {p["phase"]: p["count"] for p in d["top_phases"]}
        assert phases["implement"] == 3 and phases["plan"] == 1
        cwds = {c["cwd"]: c["count"] for c in d["top_cwds"]}
        assert cwds["/a"] == 2 and cwds["/b"] == 1
        assert d["recent_strict"][0]["preview"] == "design the thing"


def test_acknowledged_reduces_pending():
    import engine.trigger_summary as ts
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_telemetry(tdp, _RECORDS)
        with mock.patch.object(ts, "TELEMETRY_DIR", tdp), \
             mock.patch.object(ts, "load_acknowledged", lambda: {"2026-06-18T01:00:00Z"}):
            d = ts.summarize_data()
        assert d["pending"] == 1 and d["acknowledged"] == 1
        assert d["recent_strict"][0]["seen"] is True


def test_empty_telemetry_zeroes():
    import engine.trigger_summary as ts
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(ts, "TELEMETRY_DIR", Path(td)), \
             mock.patch.object(ts, "load_acknowledged", lambda: set()):
            d = ts.summarize_data()
        assert d["total_prompts"] == 0 and d["strict_design_matched"] == 0
        assert d["top_phases"] == [] and d["last_ts"] == ""


def test_json_cli_emits_valid_json():
    import engine.trigger_summary as ts
    import io
    import contextlib
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_telemetry(tdp, _RECORDS)
        buf = io.StringIO()
        with mock.patch.object(ts, "TELEMETRY_DIR", tdp), \
             mock.patch.object(ts, "load_acknowledged", lambda: set()), \
             contextlib.redirect_stdout(buf):
            rc = ts.main(["--json"])
        assert rc == 0
        parsed = json.loads(buf.getvalue())
        assert parsed["total_prompts"] == 3


def main() -> int:
    tests = [
        test_summarize_data_schema_and_counts,
        test_acknowledged_reduces_pending,
        test_empty_telemetry_zeroes,
        test_json_cli_emits_valid_json,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
