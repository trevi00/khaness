#!/usr/bin/env python3
"""Unit tests for validators/skill_source_liveness.py — URL liveness advisory.

Strategy: monkey-patch `_url_opener` for synthetic HTTP responses + tempdir
SKILLS_DIR for isolated skill files. Real network calls are forbidden in tests.
"""
from __future__ import annotations

import io
import sys
import tempfile
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import skill_source_liveness as ssl  # noqa: E402


_FM_ENFORCED = """\
---
name: ssl-sample
description: liveness test sample
keywords: ssl test
intent: smoke
requires: db-design
phase: plan
tech-stack: any
min_score: 1
quality_axes_enforced: true
---

"""

_BODY_WITH_URLS = """\
# Sample
## Source
- https://ok.example.com/spec — quote, 조회 2026-05-10
- https://dead.example.com/404 — quote, 조회 2026-05-10
- https://network.example.com/timeout — quote, 조회 2026-05-10
"""


class _FakeResp:
    def __init__(self, code: int):
        self._code = code

    def getcode(self):
        return self._code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _make_opener(rules: dict[str, object]):
    """Build opener that returns/raises based on URL substring rules."""

    def opener(url: str):
        for needle, action in rules.items():
            if needle in url:
                if isinstance(action, Exception):
                    raise action
                if isinstance(action, int):
                    return _FakeResp(action)
                if callable(action):
                    return action(url)
        return _FakeResp(200)

    return opener


def _run() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        ssl.main()
    return buf.getvalue()


def test_no_skills_dir_passes():
    saved = ssl.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        ssl.SKILLS_DIR = Path(td) / "missing"
        try:
            assert "[PASS]" in _run()
        finally:
            ssl.SKILLS_DIR = saved


def test_no_enforced_nodes_passes():
    saved = ssl.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        ssl.SKILLS_DIR = Path(td)
        legacy = ssl.SKILLS_DIR / "_common" / "legacy.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(_FM_ENFORCED.replace("quality_axes_enforced: true\n", "") + "# x\n",
                          encoding="utf-8")
        try:
            assert "[PASS]" in _run()
        finally:
            ssl.SKILLS_DIR = saved


def test_dead_url_emits_warn():
    saved_dir = ssl.SKILLS_DIR
    saved_opener = ssl._url_opener
    with tempfile.TemporaryDirectory() as td:
        ssl.SKILLS_DIR = Path(td)
        p = ssl.SKILLS_DIR / "data" / "node.md"
        p.parent.mkdir(parents=True)
        p.write_text(_FM_ENFORCED + _BODY_WITH_URLS, encoding="utf-8")
        ssl._url_opener = _make_opener({
            "ok.example.com": 200,
            "dead.example.com": urllib.error.HTTPError(
                url="https://dead.example.com/404", code=404,
                msg="Not Found", hdrs=None, fp=None
            ),
            "network.example.com": ConnectionError("simulated timeout"),
        })
        try:
            out = _run()
            assert "DEAD" in out, out
            assert "404" in out
            assert "NETWORK" in out
            assert "ok=1" in out
            assert "dead=1" in out
            assert "network=1" in out
        finally:
            ssl.SKILLS_DIR = saved_dir
            ssl._url_opener = saved_opener


def test_auth_wall_treated_ok():
    saved_dir = ssl.SKILLS_DIR
    saved_opener = ssl._url_opener
    with tempfile.TemporaryDirectory() as td:
        ssl.SKILLS_DIR = Path(td)
        p = ssl.SKILLS_DIR / "data" / "auth.md"
        p.parent.mkdir(parents=True)
        body = "# x\n## Source\n- https://wall.example.com/private — quote, 조회 2026\n"
        p.write_text(_FM_ENFORCED + body, encoding="utf-8")
        ssl._url_opener = _make_opener({
            "wall.example.com": urllib.error.HTTPError(
                url="https://wall.example.com/private", code=403,
                msg="Forbidden", hdrs=None, fp=None
            ),
        })
        try:
            out = _run()
            assert "ok=1" in out and "dead=0" in out
        finally:
            ssl.SKILLS_DIR = saved_dir
            ssl._url_opener = saved_opener


def test_redirect_treated_ok():
    saved_dir = ssl.SKILLS_DIR
    saved_opener = ssl._url_opener
    with tempfile.TemporaryDirectory() as td:
        ssl.SKILLS_DIR = Path(td)
        p = ssl.SKILLS_DIR / "infra" / "redir.md"
        p.parent.mkdir(parents=True)
        body = "# x\n## Source\n- https://redir.example.com/old — quote\n"
        p.write_text(_FM_ENFORCED + body, encoding="utf-8")
        ssl._url_opener = _make_opener({"redir.example.com": 301})
        try:
            assert "ok=1" in _run()
        finally:
            ssl.SKILLS_DIR = saved_dir
            ssl._url_opener = saved_opener


def main() -> int:
    tests = [
        test_no_skills_dir_passes,
        test_no_enforced_nodes_passes,
        test_dead_url_emits_warn,
        test_auth_wall_treated_ok,
        test_redirect_treated_ok,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
