#!/usr/bin/env python3
"""Unit tests for cli/graduate_validator.py — the token-gated flip CLI
(Track 1 debate-1780722434-e5h19n gen-2). Hermetic: graduation.STATE_DIR → temp,
HARNESS_MUTATION_TOKEN injected/cleared per test.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import graduation as g  # noqa: E402
from cli import graduate_validator as cli  # noqa: E402

NAME = "doc_code_drift"
TOKEN_ENV = "HARNESS_MUTATION_TOKEN"


class _Ctx:
    """Temp STATE_DIR + token-env control."""
    def __init__(self, token=None):
        self.token = token

    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        self._saved_state = g.STATE_DIR
        g.STATE_DIR = Path(self._td.name)
        self._saved_tok = os.environ.get(TOKEN_ENV)
        if self.token is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = self.token
        return self

    def __exit__(self, *exc):
        g.STATE_DIR = self._saved_state
        if self._saved_tok is None:
            os.environ.pop(TOKEN_ENV, None)
        else:
            os.environ[TOKEN_ENV] = self._saved_tok
        self._td.cleanup()

    def make_ready(self):
        st = g.load_state()
        g._entry(st, NAME)["ready"] = True
        g.save_state(st)


def test_status_no_token_ok():
    with _Ctx():
        assert cli.main(["status"]) == 0


def test_usage_error_no_args():
    with _Ctx():
        assert cli.main([]) == 2
        assert cli.main(["bogus"]) == 2
        assert cli.main(["graduate"]) == 2  # missing name


def test_graduate_refused_without_token():
    with _Ctx(token=None):
        c = _Ctx.make_ready  # noqa
        st = g.load_state(); g._entry(st, NAME)["ready"] = True; g.save_state(st)
        assert cli.main(["graduate", NAME]) == 3, "no token → refused (exit 3)"
        assert g.is_graduated(NAME) is False


def test_graduate_refused_wrong_token():
    with _Ctx(token="enable-skill"):
        st = g.load_state(); g._entry(st, NAME)["ready"] = True; g.save_state(st)
        assert cli.main(["graduate", NAME]) == 3
        assert g.is_graduated(NAME) is False


def test_graduate_refused_not_ready():
    with _Ctx(token=g.TOKEN_GRADUATE):
        # ready-flag absent → refused even with the right token
        assert cli.main(["graduate", NAME]) == 3
        assert g.is_graduated(NAME) is False


def test_graduate_success_with_token_and_ready():
    with _Ctx(token=g.TOKEN_GRADUATE) as ctx:
        ctx.make_ready()
        assert cli.main(["graduate", NAME]) == 0
        assert g.is_graduated(NAME) is True


def test_demote_safe_token():
    with _Ctx(token=g.TOKEN_DEMOTE) as ctx:
        st = g.load_state()
        e = g._entry(st, NAME); e["graduated"] = True; e["ready"] = True
        e["consecutive_clean"] = g.GRADUATION_THRESHOLD
        g.save_state(st)
        assert cli.main(["demote", NAME]) == 0
        assert g.is_graduated(NAME) is False


def test_demote_refused_wrong_token():
    with _Ctx(token="enable-cron-job"):
        st = g.load_state(); g._entry(st, NAME)["graduated"] = True; g.save_state(st)
        assert cli.main(["demote", NAME]) == 3
        assert g.is_graduated(NAME) is True, "wrong token must not demote"


def test_graduate_unknown_validator():
    with _Ctx(token=g.TOKEN_GRADUATE):
        assert cli.main(["graduate", "not_a_validator"]) == 2


def test_tick_runs_without_token():
    # tick is read/accounting only — no token, must not raise. Injected nothing;
    # the real scan runs against the (temp, empty) home and is fail-soft.
    with _Ctx():
        assert cli.main(["tick"]) == 0


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            failed += 1
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"[FAIL] {failed}/{len(tests)} failed")
        return 1
    print(f"[OK] {len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
