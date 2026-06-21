#!/usr/bin/env python3
"""Tests for cli.critic_policy_override (v15.17 H closure).

cli.breaker_override 1:1 mirror — token gate 양방향 + invalid + idempotent + CLI.
lib.critic_policy.apply_override 자체는 test_critic_policy.py (13/13)에서 이미
검증. 본 테스트는 CLI exit code 매핑 + 메시지 + lib 통합 wiring.
"""
from __future__ import annotations

import sys
import tempfile
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import critic_policy as CP  # noqa: E402
from cli.critic_policy_override import main as cli_main  # noqa: E402


def _redirect_policy_path(tmp: Path) -> Path:
    p = tmp / "critic-policy.yaml"
    CP.POLICY_PATH = p
    return p


def test_cli_skip_to_invoke_happy_path():
    """Explore는 DEFAULT_SKIP — skip→invoke는 apply-user-preference."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main([
                "--agent", "Explore",
                "--decision", "invoke",
                "--token", "apply-user-preference",
            ])
        assert rc == 0
        assert "persisted" in out.getvalue()
        assert CP.resolve("Explore") == "invoke"


def test_cli_invoke_to_skip_requires_strong_token():
    """harness-planner는 DEFAULT_INVOKE — invoke→skip는 configure-critic-policy."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        # 안전 토큰으로 시도 → exit 3
        err = StringIO()
        with redirect_stderr(err):
            rc = cli_main([
                "--agent", "harness-planner",
                "--decision", "skip",
                "--token", "apply-user-preference",
            ])
        assert rc == 3
        assert "configure-critic-policy" in err.getvalue()
        # 강한 토큰으로 재시도 → 성공
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main([
                "--agent", "harness-planner",
                "--decision", "skip",
                "--token", "configure-critic-policy",
            ])
        assert rc == 0
        assert "persisted" in out.getvalue()
        assert CP.resolve("harness-planner") == "skip"


def test_cli_idempotent_returns_noop():
    """이미 같은 decision이면 no-op + exit 0."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            # harness-planner는 default invoke — invoke로 적용 = no-op
            rc = cli_main([
                "--agent", "harness-planner",
                "--decision", "invoke",
                "--token", "apply-user-preference",
            ])
        assert rc == 0
        assert "NOOP" in out.getvalue() or "already" in out.getvalue()


def test_cli_invalid_decision_returns_2_from_argparse():
    """argparse choices가 잘못된 decision을 reject (exit 2)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        err = StringIO()
        try:
            with redirect_stderr(err):
                cli_main([
                    "--agent", "x",
                    "--decision", "totally-invalid",
                    "--token", "any",
                ])
        except SystemExit as e:
            assert e.code == 2


def test_cli_unknown_agent_defaults_to_invoke_and_then_skip_requires_strong():
    """모르는 agent → default invoke. skip 적용은 strong 필요."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        # 모르는 agent, skip 적용 시도 with safe → exit 3
        err = StringIO()
        with redirect_stderr(err):
            rc = cli_main([
                "--agent", "totally-unknown-agent-xyz",
                "--decision", "skip",
                "--token", "apply-user-preference",
            ])
        assert rc == 3
        # strong 토큰 → 성공
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main([
                "--agent", "totally-unknown-agent-xyz",
                "--decision", "skip",
                "--token", "configure-critic-policy",
            ])
        assert rc == 0


TESTS = [
    test_cli_skip_to_invoke_happy_path,
    test_cli_invoke_to_skip_requires_strong_token,
    test_cli_idempotent_returns_noop,
    test_cli_invalid_decision_returns_2_from_argparse,
    test_cli_unknown_agent_defaults_to_invoke_and_then_skip_requires_strong,
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
