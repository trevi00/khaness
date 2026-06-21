"""Global pytest fixtures — D3 LOCK (debate-1780268884-1di5gw gen 4 sha1
78f09503a8894f02cff45ed53a3ea07d26a5fddf).

Promotes the ad-hoc `_isolate(td)` helper at tests/test_insight_index.py:26-33
to an autouse function-scope fixture so every test gets:

  1. CLAUDE_HOME redirected to a per-test tmp_path (prevents prod L1 store
     pollution — root cause of the 40+ orchestrator-event incident handled by
     the bulk retract in debate-1780268884-1di5gw).
  2. lib.insight_index._ID_LRU cleared (collision-retry guard reset).
  3. lib.insight_index._PARSE_CACHE cleared (mtime+size cache invalidation).

D2 (writer whitelist) is module-load-time constant. Production keeps the
3-writer frozenset (handlers.stop.learner, engine.orchestrator,
lib.skill_candidate_detector). Tests widen the whitelist via
monkeypatch.setattr to include test-source_module strings — auto-reverted on
teardown.

The fixture does NOT clear any rate-window dict — D2 has no per-test state.
No @pytest.mark.no_isolate carve-out is required.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_LIB = _HERE.parent / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


@pytest.fixture(autouse=True)
def _isolate_claude_home(tmp_path, monkeypatch):
    from lib import insight_index

    monkeypatch.setenv("CLAUDE_HOME", str(tmp_path))
    # Widen D2 whitelist for the test process (auto-reverts on teardown).
    monkeypatch.setattr(
        insight_index,
        "_ALLOWED_WRITER_SOURCES",
        insight_index._ALLOWED_WRITER_SOURCES | frozenset({
            "tests.test_insight_index",
            "tests.test_insight_index_query",
            "tests.test_insight_index_retract",
            "tests",
        }),
    )
    insight_index._ID_LRU.clear()
    insight_index._PARSE_CACHE.clear()
    yield
    # tmp_path auto-cleans; monkeypatch auto-reverts CLAUDE_HOME + whitelist.
