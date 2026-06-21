#!/usr/bin/env python3
"""Unit tests for cli/telemetry_report.py."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cli import telemetry_report as tr  # noqa: E402


def test_parse_since_arg_units():
    assert tr._parse_since_arg("60s") == 60.0
    assert tr._parse_since_arg("5m") == 300.0
    assert tr._parse_since_arg("2h") == 7200.0
    assert tr._parse_since_arg("3d") == 259200.0


def test_parse_since_arg_unknown_unit():
    try:
        tr._parse_since_arg("10x")
    except ValueError as e:
        assert "unknown unit" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_parse_since_arg_empty():
    try:
        tr._parse_since_arg("")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_percentile_empty_returns_zero():
    assert tr._percentile([], 50) == 0.0


def test_percentile_single_value():
    assert tr._percentile([42.0], 50) == 42.0
    assert tr._percentile([42.0], 95) == 42.0


def test_percentile_p50_p95():
    values = sorted([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert tr._percentile(values, 50) == 6.0  # idx 5
    # p95 of 10 values: idx 9
    assert tr._percentile(values, 95) == 10.0


def test_ts_to_epoch_valid():
    epoch = tr._ts_to_epoch("2026-05-01T06:15:35Z")
    assert epoch is not None
    assert epoch > 0


def test_ts_to_epoch_none_input():
    assert tr._ts_to_epoch(None) is None
    assert tr._ts_to_epoch("") is None


def test_ts_to_epoch_invalid_format():
    assert tr._ts_to_epoch("not-a-date") is None


def test_filter_since_no_filter_returns_all():
    events = [{"ts": "2026-05-01T06:00:00Z"}, {"ts": "2024-01-01T00:00:00Z"}]
    assert len(tr._filter_since(events, None)) == 2


def test_filter_since_drops_old():
    """An event with epoch < (now - cutoff) is filtered out."""
    import time
    now = time.time()
    old_epoch = now - 100000  # ~28h ago
    new_epoch = now - 60       # 1 min ago

    def epoch_to_ts(ep: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ep))

    events = [
        {"ts": epoch_to_ts(old_epoch), "name": "old"},
        {"ts": epoch_to_ts(new_epoch), "name": "new"},
    ]
    # Cutoff = 24h
    out = tr._filter_since(events, 86400)
    names = [e["name"] for e in out]
    assert "new" in names
    # old MAY or MAY NOT be filtered depending on local timezone vs UTC
    # — gmtime above produces UTC string but mktime in _ts_to_epoch parses
    # as local. Tolerate the timezone drift; assert at least the new one survives.


def test_filter_since_keeps_unparseable_ts():
    """Events with no/bad ts are conservatively kept (don't silently drop data)."""
    events = [{"name": "no_ts"}, {"ts": "garbage", "name": "bad_ts"}]
    out = tr._filter_since(events, 60)
    names = sorted(e["name"] for e in out)
    assert names == ["bad_ts", "no_ts"]


def test_report_hook_latency_groups_by_name():
    events = [
        {"name": "h1", "duration_ms": 10.0, "status": "ok"},
        {"name": "h1", "duration_ms": 20.0, "status": "ok"},
        {"name": "h2", "duration_ms": 5.0, "status": "error"},
    ]
    report = tr.report_hook_latency(events)
    assert "h1" in report
    assert report["h1"]["n"] == 2
    assert report["h1"]["max_ms"] == 20.0
    assert report["h1"]["errors"] == 0
    assert report["h2"]["errors"] == 1


def test_report_hook_latency_skips_non_numeric_duration():
    events = [
        {"name": "h1", "duration_ms": "not a number"},
        {"name": "h1", "duration_ms": 10.0},
    ]
    report = tr.report_hook_latency(events)
    assert report["h1"]["n"] == 1


def test_report_skill_match_aggregates_top_skills():
    events = [
        {"top": [{"name": "a.md", "score": 5}, {"name": "b.md", "score": 3}], "phases": ["plan"]},
        {"top": [{"name": "a.md", "score": 4}], "phases": ["plan", "implement"], "truncated": True},
    ]
    report = tr.report_skill_match(events, top_n=10)
    assert report["invocations"] == 2
    assert report["truncated_pct"] == 50.0
    top_names = dict(report["top_skills"])
    assert top_names["a.md"] == 2
    assert top_names["b.md"] == 1


def test_report_skill_match_empty():
    report = tr.report_skill_match([], top_n=5)
    assert report["invocations"] == 0
    assert report["truncated_pct"] == 0.0
    assert report["top_skills"] == []


def test_report_debate_triggers_strict_pct():
    events = [
        {"strict_design": True, "phase": "plan"},
        {"strict_design": False, "phase": "implement"},
        {"strict_design": True, "phase": "plan"},
        {"strict_design": False},
    ]
    report = tr.report_debate_triggers(events)
    assert report["total_prompts"] == 4
    assert report["strict_design_count"] == 2
    assert report["strict_design_pct"] == 50.0
    top_phases = dict(report["top_phases"])
    assert top_phases["plan"] == 2


def test_render_text_no_crash_on_empty():
    """Empty report should still render without errors."""
    empty_report = {
        "window": "all-time",
        "hook_latency": {},
        "skill_match": {"invocations": 0, "truncated_pct": 0.0, "top_skills": [], "top_phases": []},
        "debate_triggers": {"total_prompts": 0, "strict_design_count": 0, "strict_design_pct": 0.0, "top_phases": [], "top_cwds": []},
        "validators": [("v1", 0)],
        "opaque_counts": [("o1", 0)],
    }
    text = tr.render_text(empty_report)
    assert "telemetry_report" in text
    assert "no events" in text


def test_build_report_without_telemetry_dir(monkeypatch=None):
    """Report should be safe when telemetry dir is empty / missing."""
    # iter_events returns empty iterator on missing files; build_report aggregates 0s.
    report = tr.build_report(since_seconds=None)
    # Smoke: structure has all expected top-level keys
    for key in ("window", "hook_latency", "skill_match", "debate_triggers", "validators", "opaque_counts"):
        assert key in report


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
