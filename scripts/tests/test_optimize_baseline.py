#!/usr/bin/env python3
"""Tests for lib/optimize_baseline.py — cost-driver baseline snapshots + delta."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _make_home(td: Path, *, commands=2) -> Path:
    h = td / "home"
    (h / "commands").mkdir(parents=True)
    for i in range(commands):
        (h / "commands" / f"c{i}.md").write_text("x", encoding="utf-8")
    (h / "skills").mkdir()
    (h / "skills" / "s.md").write_text("x", encoding="utf-8")
    (h / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"a": 1}]}}), encoding="utf-8")
    (h / ".claude.json").write_text(json.dumps({"mcpServers": {"a": {}, "b": {}}}), encoding="utf-8")
    (h.parent / "CLAUDE.md").write_text("# L0\n" * 100, encoding="utf-8")   # live L0 at parent
    return h


def _state(td: Path):
    import lib.paths as P
    return mock.patch.object(P, "STATE_DIR", td / "state")


def test_current_metrics_measures_drivers():
    from lib.optimize_baseline import current_metrics
    with tempfile.TemporaryDirectory() as td:
        h = _make_home(Path(td))
        m = current_metrics(home=h)
        assert m["commands_count"] == 2 and m["skills_count"] >= 1
        assert m["mcp_server_count"] == 2
        assert m["hook_event_count"] == 1
        assert m["claude_md_bytes"] > 0 and m["settings_bytes"] > 0


def test_first_snapshot_no_baseline():
    from lib.optimize_baseline import delta_from_last
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        h = _make_home(Path(td))
        d = delta_from_last(home=h)
        assert d["previous_ts"] is None and d["deltas"] == {}


def test_delta_detects_growth():
    from lib.optimize_baseline import record_snapshot, delta_from_last
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        h = _make_home(Path(td), commands=2)
        record_snapshot(home=h, ts_ms=1)
        # add a command -> commands_count grows by 1
        (h / "commands" / "new.md").write_text("x", encoding="utf-8")
        d = delta_from_last(home=h)
        assert d["previous_ts"] == 1
        assert d["deltas"]["commands_count"] == 1
        assert "commands_count" in d["grew"]


def test_render_delta_strings():
    from lib.optimize_baseline import record_snapshot, render_delta
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        h = _make_home(Path(td))
        assert "first snapshot" in render_delta(home=h)
        record_snapshot(home=h, ts_ms=1)
        out = render_delta(home=h)
        assert "drivers vs last snapshot" in out


def main() -> int:
    tests = [
        test_current_metrics_measures_drivers,
        test_first_snapshot_no_baseline,
        test_delta_detects_growth,
        test_render_delta_strings,
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
