#!/usr/bin/env python3
"""Unit tests for lib/team_mailbox.py — team-mode JSON message bus.

Per debate-1778161608-713bdc gen 4 (snapshot 7add2646...):
  - F8 team_mailbox_format = jsonl_per_worker

Coverage:
  - envelope: schema + invalid type rejection
  - send_to_inbox / send_to_outbox: append-only, separate files
  - tail_since_cursor: yields only new messages, advances cursor
  - tail_since_cursor with advance_cursor=False: yields but cursor unchanged
  - read_all_messages: reads everything, no cursor effect
  - mailbox_depth: counts correctly
  - malformed json line: tail skips + advances cursor
"""
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


def test_envelope_validates_type():
    from lib.team_mailbox import envelope

    env = envelope(sender="orch", recipient="w1", msg_type="task",
                   payload={"goal": "x"})
    assert env["type"] == "task"
    assert env["from"] == "orch"
    assert env["to"] == "w1"
    assert env["payload"]["goal"] == "x"


def test_envelope_rejects_invalid_type():
    from lib.team_mailbox import envelope
    try:
        envelope(sender="orch", recipient="w1", msg_type="invalid",
                 payload={})
    except ValueError as e:
        assert "msg_type must be" in str(e)
        return
    raise AssertionError("expected ValueError on invalid msg_type")


def test_send_to_inbox_appends_jsonl():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, inbox_path,
        )

        env = envelope(sender="orch", recipient="w1", msg_type="task",
                       payload={"task_id": 1})
        send_to_inbox("team-x", "w1", env)

        text = inbox_path("team-x", "w1").read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        assert len(lines) == 1
        decoded = json.loads(lines[0])
        assert decoded["type"] == "task"
        assert decoded["payload"]["task_id"] == 1


def test_send_inbox_outbox_separate_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, send_to_outbox, inbox_path, outbox_path,
        )

        send_to_inbox("team-x", "w1",
                      envelope(sender="orch", recipient="w1", msg_type="task",
                               payload={}))
        send_to_outbox("team-x", "w1",
                       envelope(sender="w1", recipient="orch", msg_type="done",
                                payload={}))

        assert inbox_path("team-x", "w1").exists()
        assert outbox_path("team-x", "w1").exists()
        # Each file has only its own message
        ib = inbox_path("team-x", "w1").read_text(encoding="utf-8")
        ob = outbox_path("team-x", "w1").read_text(encoding="utf-8")
        assert "task" in ib and "done" not in ib
        assert "done" in ob and "task" not in ob


def test_tail_since_cursor_yields_only_new_and_advances():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, tail_since_cursor,
        )

        for i in range(3):
            send_to_inbox("team-x", "w1",
                          envelope(sender="orch", recipient="w1", msg_type="task",
                                   payload={"i": i}))

        # First tail: 3 messages
        first = list(tail_since_cursor("team-x", "w1", side="inbox"))
        assert len(first) == 3
        assert [m["payload"]["i"] for m in first] == [0, 1, 2]

        # Second tail without new messages: 0
        second = list(tail_since_cursor("team-x", "w1", side="inbox"))
        assert second == []

        # Append more, third tail: 2 new
        for i in range(3, 5):
            send_to_inbox("team-x", "w1",
                          envelope(sender="orch", recipient="w1", msg_type="task",
                                   payload={"i": i}))
        third = list(tail_since_cursor("team-x", "w1", side="inbox"))
        assert [m["payload"]["i"] for m in third] == [3, 4]


def test_tail_since_cursor_no_advance_keeps_position():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, tail_since_cursor,
        )

        send_to_inbox("team-x", "w1",
                      envelope(sender="orch", recipient="w1", msg_type="task",
                               payload={"k": "v"}))

        first = list(tail_since_cursor("team-x", "w1", side="inbox",
                                       advance_cursor=False))
        second = list(tail_since_cursor("team-x", "w1", side="inbox",
                                        advance_cursor=False))
        assert len(first) == 1
        assert len(second) == 1  # cursor not advanced -> same message yielded


def test_tail_since_cursor_invalid_side_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import tail_since_cursor

        try:
            list(tail_since_cursor("team-x", "w1", side="bogus"))
        except ValueError as e:
            assert "inbox" in str(e) or "outbox" in str(e)
            return
        raise AssertionError("expected ValueError on invalid side")


def test_read_all_messages_no_cursor_effect():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_outbox, read_all_messages, tail_since_cursor,
        )

        for i in range(2):
            send_to_outbox("team-x", "w2",
                           envelope(sender="w2", recipient="orch",
                                    msg_type="answer", payload={"i": i}))

        all_msgs = read_all_messages("team-x", "w2", side="outbox")
        assert len(all_msgs) == 2

        # Cursor for tail should still be 0 -> tail yields all 2
        tailed = list(tail_since_cursor("team-x", "w2", side="outbox"))
        assert len(tailed) == 2


def test_mailbox_depth_counts_correctly():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, mailbox_depth,
        )

        assert mailbox_depth("team-x", "w1", side="inbox") == 0

        for _ in range(3):
            send_to_inbox("team-x", "w1",
                          envelope(sender="orch", recipient="w1",
                                   msg_type="task", payload={}))
        assert mailbox_depth("team-x", "w1", side="inbox") == 3


# ---------- runtime stress: round-trip + CLI surface (W21+) ----------

def test_tail_skips_malformed_jsonl_line_and_advances_cursor():
    """Atomic-append usually prevents malformed lines, but defensive — if a
    truncated/garbage line slips in (e.g. another tool's `echo >> file`),
    tail must skip it AND advance the cursor past it (no infinite re-yield).
    """
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, tail_since_cursor, inbox_path,
        )

        send_to_inbox("team-x", "w1",
                      envelope(sender="orch", recipient="w1",
                               msg_type="task", payload={"id": 1}))
        # Manually append a malformed line between two valid messages
        ib = inbox_path("team-x", "w1")
        with ib.open("a", encoding="utf-8") as f:
            f.write("not-valid-json{{{\n")
        send_to_inbox("team-x", "w1",
                      envelope(sender="orch", recipient="w1",
                               msg_type="task", payload={"id": 2}))

        # First tail yields the 2 valid messages (malformed skipped silently)
        msgs = list(tail_since_cursor("team-x", "w1", side="inbox"))
        ids = [m["payload"]["id"] for m in msgs]
        assert ids == [1, 2]

        # Second tail: nothing — cursor must have advanced past the malformed line
        # so we don't re-yield it as garbage on every poll.
        again = list(tail_since_cursor("team-x", "w1", side="inbox"))
        assert again == []


def test_multi_worker_inboxes_isolated():
    """Each worker has its own jsonl files. send_to_inbox(team, worker_id)
    must not leak messages across workers in the same team session.
    """
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, tail_since_cursor, mailbox_depth,
        )

        for w in ("w1", "w2", "w3"):
            send_to_inbox("team-x", w,
                          envelope(sender="orch", recipient=w,
                                   msg_type="task", payload={"who": w}))

        assert mailbox_depth("team-x", "w1", side="inbox") == 1
        assert mailbox_depth("team-x", "w2", side="inbox") == 1
        assert mailbox_depth("team-x", "w3", side="inbox") == 1

        # Each worker's tail yields only its own message
        for w in ("w1", "w2", "w3"):
            msgs = list(tail_since_cursor("team-x", w, side="inbox"))
            assert len(msgs) == 1
            assert msgs[0]["payload"]["who"] == w


def test_orch_worker_round_trip_task_then_done():
    """Real workflow: orch -> worker (task) ; worker -> orch (done).
    Verifies the inbox/outbox pair across both directions, with each side
    advancing its own cursor independently.
    """
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import (
            envelope, send_to_inbox, send_to_outbox, tail_since_cursor,
        )

        # orch sends a task to worker 'w1'
        send_to_inbox("team-x", "w1",
                      envelope(sender="orch", recipient="w1",
                               msg_type="task",
                               payload={"job": "render-tree"}))

        # worker tails its inbox and consumes the task
        worker_inbox = list(tail_since_cursor("team-x", "w1", side="inbox"))
        assert len(worker_inbox) == 1
        assert worker_inbox[0]["payload"]["job"] == "render-tree"

        # worker emits done to its outbox
        send_to_outbox("team-x", "w1",
                       envelope(sender="w1", recipient="orch",
                                msg_type="done",
                                payload={"result_path": "/state/tree.md"}))

        # orch tails worker's outbox and consumes the done
        orch_view = list(tail_since_cursor("team-x", "w1", side="outbox"))
        assert len(orch_view) == 1
        assert orch_view[0]["type"] == "done"
        assert orch_view[0]["payload"]["result_path"] == "/state/tree.md"

        # Re-tail both sides: cursor advanced, yields nothing
        assert list(tail_since_cursor("team-x", "w1", side="inbox")) == []
        assert list(tail_since_cursor("team-x", "w1", side="outbox")) == []


def test_cli_send_dispatches_to_inbox_or_outbox():
    """The `send` CLI subcommand (used by run-worker.sh) writes a single
    envelope to the requested side. Verifies argv parsing + side routing.
    """
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.team_mailbox import _cli, mailbox_depth, read_all_messages

        # orch -> worker inbox
        rc = _cli([
            "send", "team-x", "w1", "inbox", "task",
            json.dumps({"goal": "x"}),
        ])
        assert rc == 0
        assert mailbox_depth("team-x", "w1", side="inbox") == 1
        msgs = read_all_messages("team-x", "w1", side="inbox")
        assert msgs[0]["type"] == "task"
        assert msgs[0]["payload"]["goal"] == "x"

        # worker -> orch outbox
        rc = _cli([
            "send", "team-x", "w1", "outbox", "done",
            json.dumps({"ok": True}),
        ])
        assert rc == 0
        assert mailbox_depth("team-x", "w1", side="outbox") == 1
        msgs = read_all_messages("team-x", "w1", side="outbox")
        assert msgs[0]["type"] == "done"

        # Invalid type -> rc=2, mailbox unchanged
        rc = _cli([
            "send", "team-x", "w1", "inbox", "INVALID_TYPE",
            json.dumps({}),
        ])
        assert rc == 2
        assert mailbox_depth("team-x", "w1", side="inbox") == 1  # unchanged


def test_path_builders_neutralize_traversal():
    # deep-audit pass-2: a crafted sid/worker_id with separators or `..` must not
    # escape STATE_DIR/team/ (defense-in-depth — ids are harness-generated today).
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib import team_mailbox as tm
        from lib import paths as P
        team_root = (P.STATE_DIR / "team").resolve()
        for sid, wid in (("../../evil", "worker-0"),
                         ("sid", "../../../etc/passwd"),
                         ("..", ".."),
                         ("a/b", "c\\d")):
            for p in (tm.inbox_path(sid, wid),
                      tm.outbox_path(sid, wid),
                      tm.cursor_path(sid, wid, side="inbox")):
                # every built path must stay inside STATE_DIR/team/
                assert team_root in p.resolve().parents or p.resolve().parent == team_root \
                    or str(p.resolve()).startswith(str(team_root)), \
                    f"escaped team root: {p.resolve()} (sid={sid!r}, wid={wid!r})"
        # legitimate ids are untouched (no-op for normal tokens)
        assert tm.inbox_path("team-123-abc", "worker-0").name == "worker-0.inbox.jsonl"


TESTS = [
    test_envelope_validates_type,
    test_envelope_rejects_invalid_type,
    test_send_to_inbox_appends_jsonl,
    test_send_inbox_outbox_separate_files,
    test_tail_since_cursor_yields_only_new_and_advances,
    test_tail_since_cursor_no_advance_keeps_position,
    test_tail_since_cursor_invalid_side_raises,
    test_read_all_messages_no_cursor_effect,
    test_mailbox_depth_counts_correctly,
    test_tail_skips_malformed_jsonl_line_and_advances_cursor,
    test_multi_worker_inboxes_isolated,
    test_orch_worker_round_trip_task_then_done,
    test_cli_send_dispatches_to_inbox_or_outbox,
    test_path_builders_neutralize_traversal,
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
