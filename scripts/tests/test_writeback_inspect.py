#!/usr/bin/env python3
"""Unit tests for cli/writeback_inspect.py — operator-facing CLI surface
for harness writeback proposals.
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


def _seed_proposal(pid: str, fp: str = "f" * 40, target: str = "skills/_common/x.md"):
    from lib.writeback_store import ProposalRecord, register_proposal
    register_proposal(ProposalRecord(
        id=pid, fingerprint=fp, target_skill_path=target, sha1_of_diff="0" * 40,
    ))


# ---- render_list ----

def test_render_list_empty():
    from cli.writeback_inspect import render_list
    out = render_list([])
    assert "No pending" in out


def test_render_list_with_entries():
    from cli.writeback_inspect import render_list
    pending = [
        {"id": "p1", "fingerprint": "abc12345xx" * 4,
         "target_skill_path": "skills/_common/foo.md", "created_ts": 0},
        {"id": "p2", "fingerprint": "def67890yy" * 4,
         "target_skill_path": "skills/_common/bar.md", "created_ts": 0},
    ]
    out = render_list(pending, now=100.0)
    assert "p1" in out
    assert "p2" in out
    assert "skills/_common/foo.md" in out
    assert "abc12345" in out  # 8-char fingerprint truncation
    assert "writeback_inspect --show" in out


def test_format_age_branches():
    from cli.writeback_inspect import _format_age
    assert _format_age(100, 100) == "0s"
    assert _format_age(160, 100) == "1m"
    assert _format_age(7300, 100) == "2h"
    assert _format_age(86500, 100) == "1d"


# ---- cmd_list ----

def test_main_default_lists_empty_when_no_proposals():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main([])
        assert rc == 0
        assert "No pending" in buf.getvalue()


def test_main_list_renders_seeded_proposals():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        _seed_proposal("p1")
        _seed_proposal("p2", target="skills/_common/y.md")
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--list"])
        assert rc == 0
        text = buf.getvalue()
        assert "p1" in text and "p2" in text


def test_main_list_json_emits_array():
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        _seed_proposal("p1")
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json", "--list"])
        assert rc == 0
        data = _json.loads(buf.getvalue())
        assert isinstance(data, list)
        assert any(d.get("id") == "p1" for d in data)


# ---- cmd_show ----

def test_main_show_returns_1_for_unknown_id():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from cli.writeback_inspect import main
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--show", "nonexistent-id"])
        assert rc == 1
        assert "unknown id" in err.getvalue()


def test_main_show_known_id_prints_entry():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        _seed_proposal("p1", target="skills/_common/z.md")
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--show", "p1"])
        assert rc == 0
        text = buf.getvalue()
        assert "p1" in text
        assert "skills/_common/z.md" in text


# ---- cmd_dismiss ----

def test_main_dismiss_marks_status_rejected():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        _seed_proposal("p1")
        from lib.writeback_store import read_index, list_pending
        from cli.writeback_inspect import main

        # Pre-state: pending
        assert any(p["id"] == "p1" for p in list_pending())

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--dismiss", "p1"])
        assert rc == 0

        # Post-state: rejected, no longer pending
        idx = read_index()
        assert idx["p1"]["status"] == "rejected"
        assert not any(p["id"] == "p1" for p in list_pending())


def test_main_dismiss_unknown_id_returns_1():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from cli.writeback_inspect import main
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--dismiss", "nope"])
        assert rc == 1


# ---- telemetry ----

def test_main_telemetry_handles_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--telemetry"])
        assert rc == 0
        assert "no telemetry" in buf.getvalue().lower()


# ---- cmd_preview ----

_VALID_DIFF_TEMPLATE = """## Proposed permanent change

```diff
--- a/sandbox/.claude/skills/_common/x.md
+++ b/sandbox/.claude/skills/_common/x.md
@@ -1,3 +1,5 @@
 ## Gotchas
+
+### New rule
+- avoid X when Y
 (existing line)
```
"""


def _seed_strike_artifact(fingerprint: str, content: str = _VALID_DIFF_TEMPLATE):
    from lib.paths import STATE_DIR
    d = STATE_DIR / "research" / "strikes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{fingerprint}.md").write_text(content, encoding="utf-8")


def test_main_preview_unknown_id_returns_1():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from cli.writeback_inspect import main
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--preview", "nope"])
        assert rc == 1
        assert "unknown id" in err.getvalue()


def test_main_preview_missing_artifact_returns_1():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        _seed_proposal("p1", fp="abc" * 20)
        from cli.writeback_inspect import main
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--preview", "p1"])
        assert rc == 1
        assert "strike artifact missing" in err.getvalue()


def test_main_preview_renders_parsed_proposal():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        fp = "deadbeef" * 5  # 40 chars
        _seed_proposal("p1", fp=fp, target="skills/_common/x.md")
        _seed_strike_artifact(fp)
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--preview", "p1"])
        assert rc == 0
        text = buf.getvalue()
        assert "PARSED OK" in text
        assert "skills/_common/x.md" in text
        assert "hunk count" in text
        assert "+/-" in text


def test_main_preview_renders_reject_reason():
    """A strike artifact with no diff fence → UNSUPPORTED_GRAMMAR."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        fp = "cafe" * 10  # 40 chars
        _seed_proposal("p1", fp=fp)
        _seed_strike_artifact(fp, content=(
            "## Proposed permanent change\n\nReplace line 5 with foo.\n"
        ))
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--preview", "p1"])
        assert rc == 0
        text = buf.getvalue()
        assert "REJECTED" in text
        assert "unsupported_grammar" in text


def test_main_preview_json_emits_structured_output():
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        fp = "feed" * 10
        _seed_proposal("p1", fp=fp, target="skills/_common/x.md")
        _seed_strike_artifact(fp)
        from cli.writeback_inspect import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json", "--preview", "p1"])
        assert rc == 0
        data = _json.loads(buf.getvalue())
        assert data["status"] == "parsed"
        assert data["fingerprint"] == fp
        assert isinstance(data["edits"], list)
        assert len(data["edits"]) >= 1


# ---- cmd_arm + cmd_apply + cmd_rollback (D1+D3+D4+D5 E2E) ----

def _seed_concrete_target_for_apply(td: Path, fp: str, pid: str = "p1"):
    """Seed a proposal + strike artifact targeting a real file under td/.claude/.
    The diff modifies a `## Gotchas` section per parser contract.
    Returns the target absolute path after content is written.
    """
    target_dir = td / ".claude" / "skills" / "_common"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "x.md"
    # Write bytes directly to enforce LF (matches harness-researcher output;
    # write_text on Windows would translate \n → \r\n).
    target_file.write_bytes(
        b"# Skill\n\n## Gotchas\n\n- existing rule\n"
    )

    # Diff inserts a new bullet under '## Gotchas' (line 3)
    diff_target = str(target_file).replace("\\", "/")
    artifact = f"""## Proposed permanent change

```diff
--- a/{diff_target}
+++ b/{diff_target}
@@ -3,3 +3,4 @@
 ## Gotchas

 - existing rule
+- new rule from researcher
```
"""
    _seed_proposal(pid, fp=fp, target=str(target_file))
    _seed_strike_artifact(fp, content=artifact)
    return target_file


def _patch_resolve_to_absolute():
    """Patch _resolve_target_abs to return Path(target_path) directly so the
    test's absolute paths flow through unchanged (default impl prefixes
    ~/.claude for relative paths, but our tests use absolute already)."""
    # No-op: the default impl already returns Path(target_path) when absolute.
    pass


def test_main_arm_then_apply_e2e():
    """Full E2E: arm → apply → file modified → audit appended → index updated."""
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        _redirect_state_dir(td_path)
        fp = "f" * 40
        target_file = _seed_concrete_target_for_apply(td_path, fp, pid="p1")

        from cli.writeback_inspect import main

        # ARM
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json", "--arm", "p1"])
        assert rc == 0, buf.getvalue()
        arm_data = _json.loads(buf.getvalue())
        token = arm_data["token"]

        # APPLY
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = main(["--json", "--apply", "p1", "--token", token])
        assert rc2 == 0, buf2.getvalue()
        apply_data = _json.loads(buf2.getvalue())
        assert apply_data["status"] == "applied"
        assert apply_data["targets_modified"] == 1

        # Target file actually modified
        new_text = target_file.read_text(encoding="utf-8")
        assert "new rule from researcher" in new_text
        assert "existing rule" in new_text  # context preserved

        # applied.jsonl has the record
        from lib.writeback_store import list_applied, read_index
        applied = list_applied()
        assert any(r.get("apply_id") == apply_data["apply_id"] for r in applied)

        # Index status now 'applied'
        idx = read_index()
        assert idx["p1"]["status"] == "applied"


def test_main_apply_without_arm_returns_token_invalid():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        _redirect_state_dir(td_path)
        fp = "g" * 40
        _seed_concrete_target_for_apply(td_path, fp, pid="p1")
        from cli.writeback_inspect import main
        err = io.StringIO()
        with redirect_stderr(err):
            rc = main(["--apply", "p1", "--token", "fake-token-no-arm"])
        # Token never armed → TOKEN_INVALID, exit 2
        assert rc == 2
        assert "TOKEN_INVALID" in err.getvalue()


def test_main_apply_then_rollback_e2e():
    """Apply, then arm-rollback + rollback → file restored."""
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td).resolve()
        _redirect_state_dir(td_path)
        fp = "h" * 40
        target_file = _seed_concrete_target_for_apply(td_path, fp, pid="p1")
        original_text = target_file.read_text(encoding="utf-8")

        from cli.writeback_inspect import main

        # arm + apply
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--json", "--arm", "p1"])
        token = _json.loads(buf.getvalue())["token"]
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main(["--json", "--apply", "p1", "--token", token])
        apply_id = _json.loads(buf2.getvalue())["apply_id"]
        # Target modified
        assert target_file.read_text(encoding="utf-8") != original_text

        # arm-rollback + rollback
        buf3 = io.StringIO()
        with redirect_stdout(buf3):
            rc3 = main(["--json", "--arm-rollback", apply_id])
        assert rc3 == 0
        rb_token = _json.loads(buf3.getvalue())["token"]
        buf4 = io.StringIO()
        with redirect_stdout(buf4):
            rc4 = main(["--json", "--rollback", apply_id, "--token", rb_token])
        assert rc4 == 0

        # Target restored to original bytes
        assert target_file.read_text(encoding="utf-8") == original_text


TESTS = [
    test_render_list_empty,
    test_render_list_with_entries,
    test_format_age_branches,
    test_main_default_lists_empty_when_no_proposals,
    test_main_list_renders_seeded_proposals,
    test_main_list_json_emits_array,
    test_main_show_returns_1_for_unknown_id,
    test_main_show_known_id_prints_entry,
    test_main_dismiss_marks_status_rejected,
    test_main_dismiss_unknown_id_returns_1,
    test_main_telemetry_handles_missing,
    test_main_preview_unknown_id_returns_1,
    test_main_preview_missing_artifact_returns_1,
    test_main_preview_renders_parsed_proposal,
    test_main_preview_renders_reject_reason,
    test_main_preview_json_emits_structured_output,
    test_main_arm_then_apply_e2e,
    test_main_apply_without_arm_returns_token_invalid,
    test_main_apply_then_rollback_e2e,
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
