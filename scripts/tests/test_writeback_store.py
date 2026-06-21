#!/usr/bin/env python3
"""Unit tests for lib/writeback_store.py — D2 stdlib-only atomic store."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


# ---- ProposalRecord + append_proposal ----

def test_append_proposal_writes_jsonl_line():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, append_proposal, _proposals_path,
        )
        rec = ProposalRecord(
            id="p1", fingerprint="abc", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        )
        assert append_proposal(rec) is True
        text = _proposals_path().read_text(encoding="utf-8")
        line = text.strip()
        decoded = json.loads(line)
        assert decoded["id"] == "p1"
        assert decoded["fingerprint"] == "abc"
        assert decoded["status"] == "pending"


def test_append_proposal_rejects_oversize_line():
    """PIPE_BUF cap (Architect addendum 1): >4096 bytes per line → reject."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, append_proposal, telemetry_snapshot,
        )
        # Force oversized via huge sha1 substitute (real records won't hit this)
        big = ProposalRecord(
            id="big", fingerprint="x" * 5000, target_skill_path="x.md",
            sha1_of_diff="0" * 40,
        )
        assert append_proposal(big) is False
        tele = telemetry_snapshot()
        assert tele.get("writeback_split_rejected_total", 0) >= 1


def test_append_proposal_rejects_non_record():
    from lib.writeback_store import append_proposal
    assert append_proposal({"not": "a record"}) is False  # type: ignore[arg-type]
    assert append_proposal(None) is False  # type: ignore[arg-type]


# ---- read_index / update_index ----

def test_read_index_empty_when_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import read_index
        assert read_index() == {}


def test_update_index_atomic_rewrite():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import update_index, read_index

        def add_x(idx):
            idx["x"] = {"status": "pending"}
            return idx

        assert update_index(add_x) is True
        assert read_index() == {"x": {"status": "pending"}}


def test_update_index_rejects_non_dict_return():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import update_index
        assert update_index(lambda idx: "not a dict") is False  # type: ignore[arg-type,return-value]


# ---- mark_status ----

def test_mark_status_updates_existing_entry():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_status, read_index,
        )
        rec = ProposalRecord(
            id="p1", fingerprint="abc", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        )
        assert register_proposal(rec) is True
        assert mark_status("p1", "acked") is True
        idx = read_index()
        assert idx["p1"]["status"] == "acked"
        assert "resolved_ts" in idx["p1"]


def test_mark_status_rejects_invalid_status():
    from lib.writeback_store import mark_status
    assert mark_status("p1", "weird") is False  # type: ignore[arg-type]
    assert mark_status("", "acked") is False


# ---- register_proposal + list_pending ----

def test_register_proposal_adds_to_jsonl_and_index():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, list_pending, _proposals_path,
        )
        rec = ProposalRecord(
            id="p1", fingerprint="abc", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        )
        assert register_proposal(rec) is True
        # jsonl has line
        assert _proposals_path().read_text(encoding="utf-8").strip() != ""
        # list_pending returns it
        pending = list_pending()
        assert any(p["id"] == "p1" for p in pending)


def test_list_pending_excludes_resolved():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_status, list_pending,
        )
        for pid in ("p1", "p2"):
            register_proposal(ProposalRecord(
                id=pid, fingerprint="abc", target_skill_path="skills/_common/x.md",
                sha1_of_diff="0" * 40,
            ))
        mark_status("p1", "acked")
        pending = list_pending()
        ids = [p["id"] for p in pending]
        assert "p1" not in ids
        assert "p2" in ids


# ---- mark_applied + list_applied (D3 audit, debate-1778236168-53dedd) ----

def _minimal_apply_record(pid="p1"):
    return {
        "apply_id": "abc123def4567890",
        "target_path": "skills/_common/x.md",
        "pre_image_sha1": "a" * 40,
        "post_image_sha1": "b" * 40,
        "applied_ts": 1.0,
        "operator_context": {"pid": 1234, "sid": "x", "cwd": "/tmp"},
        "hunk_count": 1,
    }


def test_mark_applied_appends_jsonl_and_updates_index():
    import time as _time
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_applied, read_index,
            _writeback_dir,
        )
        register_proposal(ProposalRecord(
            id="p1", fingerprint="f", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        ))
        rec = _minimal_apply_record("p1")
        rec["applied_ts"] = _time.time()
        assert mark_applied("p1", rec) is True

        # applied.jsonl line written
        applied_path = _writeback_dir() / "applied.jsonl"
        assert applied_path.exists()
        line = applied_path.read_text(encoding="utf-8").strip()
        decoded = json.loads(line)
        assert decoded["proposal_id"] == "p1"
        assert decoded["target_path"] == "skills/_common/x.md"

        # Index updated
        idx = read_index()
        assert idx["p1"]["status"] == "applied"
        assert idx["p1"]["apply_id"] == "abc123def4567890"


def test_mark_applied_rejects_missing_required_fields():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import mark_applied
        # Missing required keys
        assert mark_applied("p1", {}) is False
        assert mark_applied("p1", {"apply_id": "x"}) is False
        # Non-string proposal_id / non-dict record
        assert mark_applied("", _minimal_apply_record()) is False
        assert mark_applied("p1", "not-a-dict") is False  # type: ignore[arg-type]


def test_mark_applied_drops_hunk_headers_when_oversize():
    """A record with huge hunk_headers should retry-without-hunk_headers,
    succeeding when the slim form fits under PIPE_BUF_CAP_BYTES."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_applied, _writeback_dir,
        )
        register_proposal(ProposalRecord(
            id="p1", fingerprint="f", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        ))
        rec = _minimal_apply_record()
        # Pad hunk_headers to push over 4096B but slim form will fit
        rec["hunk_headers"] = ["@@ -1,1 +1,1 @@ " + "x" * 200] * 30
        ok = mark_applied("p1", rec)
        # Should succeed via slim retry
        assert ok is True
        line = (_writeback_dir() / "applied.jsonl").read_text(encoding="utf-8").strip()
        decoded = json.loads(line)
        assert decoded.get("hunk_headers_dropped_for_size") is True
        assert "hunk_headers" not in decoded


def test_list_applied_returns_records_in_order():
    import time as _time
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_applied, list_applied,
        )
        for pid in ("p1", "p2"):
            register_proposal(ProposalRecord(
                id=pid, fingerprint="f", target_skill_path="skills/_common/x.md",
                sha1_of_diff="0" * 40,
            ))
            rec = _minimal_apply_record(pid)
            rec["apply_id"] = pid + "_apply_id_padded"  # >=16 chars
            rec["applied_ts"] = _time.time()
            mark_applied(pid, rec)

        records = list_applied()
        ids = [r["proposal_id"] for r in records]
        assert ids == ["p1", "p2"]


def test_list_applied_returns_empty_when_no_file():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import list_applied
        assert list_applied() == []


def test_gc_old_sidecars_removes_files_past_retention():
    import os as _os
    import time as _time
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import gc_old_sidecars, _writeback_dir
        d = _writeback_dir() / "preimages"
        d.mkdir(parents=True, exist_ok=True)
        old = d / "old.bin"
        old.write_bytes(b"x")
        # Backdate mtime to 31 days ago
        past = _time.time() - 31 * 86400
        _os.utime(old, (past, past))
        removed = gc_old_sidecars(retention_days=30)
        assert removed == 1
        assert not old.exists()


def test_gc_old_sidecars_keeps_fresh_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import gc_old_sidecars, _writeback_dir
        d = _writeback_dir() / "preimages"
        d.mkdir(parents=True, exist_ok=True)
        fresh = d / "fresh.bin"
        fresh.write_bytes(b"y")
        removed = gc_old_sidecars(retention_days=30)
        assert removed == 0
        assert fresh.exists()


def test_gc_old_sidecars_returns_zero_when_dir_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import gc_old_sidecars
        # No preimages dir exists yet — must return 0 without raising
        assert gc_old_sidecars() == 0


def test_list_applied_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.writeback_store import (
            ProposalRecord, register_proposal, mark_applied, list_applied,
            _writeback_dir,
        )
        register_proposal(ProposalRecord(
            id="p1", fingerprint="f", target_skill_path="skills/_common/x.md",
            sha1_of_diff="0" * 40,
        ))
        mark_applied("p1", _minimal_apply_record())

        # Append a corrupt line manually
        applied_path = _writeback_dir() / "applied.jsonl"
        with open(applied_path, "a", encoding="utf-8") as f:
            f.write("not_json {{{\n")
            f.write('{"valid": "json", "but": "not_a_record"}\n')

        records = list_applied()
        # The corrupt line is skipped; the dict-but-not-record line is kept
        # (list_applied just returns whatever parsable dicts exist).
        # At minimum the original p1 record must be present.
        assert any(r.get("proposal_id") == "p1" for r in records)


TESTS = [
    test_append_proposal_writes_jsonl_line,
    test_append_proposal_rejects_oversize_line,
    test_append_proposal_rejects_non_record,
    test_read_index_empty_when_missing,
    test_update_index_atomic_rewrite,
    test_update_index_rejects_non_dict_return,
    test_mark_status_updates_existing_entry,
    test_mark_status_rejects_invalid_status,
    test_register_proposal_adds_to_jsonl_and_index,
    test_list_pending_excludes_resolved,
    test_mark_applied_appends_jsonl_and_updates_index,
    test_mark_applied_rejects_missing_required_fields,
    test_mark_applied_drops_hunk_headers_when_oversize,
    test_list_applied_returns_records_in_order,
    test_list_applied_returns_empty_when_no_file,
    test_list_applied_skips_malformed_lines,
    test_gc_old_sidecars_removes_files_past_retention,
    test_gc_old_sidecars_keeps_fresh_files,
    test_gc_old_sidecars_returns_zero_when_dir_missing,
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
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
