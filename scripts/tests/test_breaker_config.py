#!/usr/bin/env python3
"""Tests for lib.breakers.config + cli.breaker_override + composite 통합 (v15.16).

Coverage:
  - BreakerThresholds: default == module-level constants
  - resolve_thresholds: yaml 없으면 default, 있으면 merge
  - yaml parser: comment / blank / bogus value tolerant
  - apply_override:
      * 상향 increase_is_lenient → configure-critic-policy 필요
      * 하향 → apply-user-preference 필요
      * window (ambiguous) → apply-user-preference (양방향)
      * 잘못된 토큰 → PermissionError
      * 같은 값 → False (no-op)
      * unknown key / 음수 → ValueError
  - composite 통합:
      * yaml override 적용 후 record_failure가 새 임계로 동작
      * default 동작 회귀 (yaml 없을 때 = 기존 test_composite_breaker와 동일)
  - CLI: happy path / wrong token / unknown key
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

from lib.breakers import config as CFG  # noqa: E402
from lib.breakers.config import (  # noqa: E402
    DEFAULT_BACKOFF_BASE_SEC,
    DEFAULT_TRIP_PER_MODE,
    DEFAULT_TRIP_WINDOW,
    TOKEN_SAFE,
    TOKEN_STRONG,
    BreakerThresholds,
    apply_override,
    resolve_thresholds,
)
from lib.breakers import composite as comp  # noqa: E402
from cli.breaker_override import main as cli_main  # noqa: E402


def _redirect_config(tmp: Path) -> Path:
    new_path = tmp / "breaker-thresholds.yaml"
    CFG.CONFIG_PATH = new_path
    return new_path


# ---- BreakerThresholds defaults ----

def test_default_values_match_module_constants():
    th = BreakerThresholds()
    assert th.trip_per_mode == comp.TRIP_PER_MODE
    assert th.trip_window == comp.TRIP_WINDOW
    assert th.trip_any_mode == comp.TRIP_ANY_MODE
    assert th.trip_any_window == comp.TRIP_ANY_WINDOW
    assert th.backoff_base_sec == comp.BACKOFF_BASE_SEC
    assert th.backoff_cap_sec == comp.BACKOFF_CAP_SEC


def test_resolve_no_yaml_returns_default():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        th = resolve_thresholds()
        assert th.trip_per_mode == DEFAULT_TRIP_PER_MODE


def test_resolve_merges_yaml_override():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_config(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "version: 1\n"
            "overrides:\n"
            "  trip_per_mode: 5\n"
            "  backoff_base_sec: 120\n",
            encoding="utf-8",
        )
        th = resolve_thresholds()
        assert th.trip_per_mode == 5
        assert th.backoff_base_sec == 120
        assert th.trip_window == DEFAULT_TRIP_WINDOW  # not overridden


# ---- yaml parser tolerance ----

def test_yaml_tolerates_comments_and_blanks():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_config(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# header comment\n\n"
            "version: 1\n"
            "overrides:\n"
            "  # comment inside\n"
            "  trip_per_mode: 4\n",
            encoding="utf-8",
        )
        assert resolve_thresholds().trip_per_mode == 4


def test_yaml_drops_bogus_keys_and_nonint_values():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_config(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "version: 1\n"
            "overrides:\n"
            "  bogus_key: 99\n"          # unknown key → dropped
            "  trip_per_mode: abc\n"     # non-int → dropped
            "  backoff_base_sec: 200\n",
            encoding="utf-8",
        )
        th = resolve_thresholds()
        assert th.trip_per_mode == DEFAULT_TRIP_PER_MODE  # bogus_key, abc 무시
        assert th.backoff_base_sec == 200


# ---- apply_override token gating ----

def test_increase_requires_strong_token():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        # default=3, 3→4 (increase) → strong 필요
        try:
            apply_override("trip_per_mode", 4, token=TOKEN_SAFE)
        except PermissionError as e:
            assert TOKEN_STRONG in str(e)
        else:
            raise AssertionError("increase without strong token must raise")
        # with strong token → persists
        assert apply_override("trip_per_mode", 4, token=TOKEN_STRONG) is True
        assert resolve_thresholds().trip_per_mode == 4


def test_decrease_requires_safe_token():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        # default=3, 3→2 (decrease) → safe 필요
        assert apply_override("trip_per_mode", 2, token=TOKEN_SAFE) is True
        assert resolve_thresholds().trip_per_mode == 2


def test_decrease_with_strong_token_also_raises():
    """엄격성: 잘못된 tier 토큰은 양방향 모두 reject (critic_policy 패턴)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        try:
            apply_override("trip_per_mode", 2, token=TOKEN_STRONG)
        except PermissionError as e:
            assert TOKEN_SAFE in str(e)
        else:
            raise AssertionError("decrease with strong token must raise")


def test_window_key_uses_safe_token_both_directions():
    """trip_window는 ambiguous → safe token 양방향 모두 통과."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        # default=10, 10→12 (increase ambiguous)
        assert apply_override("trip_window", 12, token=TOKEN_SAFE) is True
        # 12→8 (decrease)
        assert apply_override("trip_window", 8, token=TOKEN_SAFE) is True


def test_apply_idempotent():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        # default already 3 → no change
        assert apply_override("trip_per_mode", DEFAULT_TRIP_PER_MODE, token=TOKEN_SAFE) is False


def test_unknown_key_and_invalid_value_raise():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        try:
            apply_override("nonexistent_key", 5, token=TOKEN_SAFE)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown key must raise")
        try:
            apply_override("trip_per_mode", -1, token=TOKEN_SAFE)
        except ValueError:
            pass
        else:
            raise AssertionError("negative value must raise")


# ---- composite 통합 ----

def test_composite_uses_yaml_override_for_trip_per_mode():
    """yaml override가 record_failure trip 결정에 반영."""
    with tempfile.TemporaryDirectory() as td:
        # config + breakers root 둘 다 격리
        path = _redirect_config(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "version: 1\n"
            "overrides:\n"
            "  trip_per_mode: 5\n",   # 더 관대 — 3대신 5
            encoding="utf-8",
        )
        from lib.breakers.composite import CompositeBreaker, State
        breakers_root = Path(td) / "breakers"
        br = CompositeBreaker(
            agent_type="researcher",
            failure_mode="evidence_fabrication",
            project_id="test",
            base_dir=str(breakers_root),
        )
        # 3번 fail → default였으면 trip, 5로 상향 후 trip 안 함
        for _ in range(3):
            assert br.record_failure() == State.CLOSED
        # 5번째 fail에 trip
        assert br.record_failure() == State.CLOSED
        assert br.record_failure() == State.OPEN


def test_composite_default_behavior_when_no_yaml():
    """yaml 없으면 기존 default 동작 보존 (test_composite_breaker 회귀 0 보장)."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))  # exists but empty path → file doesn't exist
        from lib.breakers.composite import CompositeBreaker, State
        breakers_root = Path(td) / "breakers"
        br = CompositeBreaker(
            agent_type="researcher",
            failure_mode="evidence_fabrication",
            project_id="test",
            base_dir=str(breakers_root),
        )
        # 3번 fail에 trip (default TRIP_PER_MODE=3)
        for _ in range(2):
            assert br.record_failure() == State.CLOSED
        assert br.record_failure() == State.OPEN


# ---- CLI ----

def test_cli_happy_path():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        out = StringIO()
        with redirect_stdout(out):
            rc = cli_main([
                "--key", "trip_per_mode", "--value", "4",
                "--token", TOKEN_STRONG,
            ])
        assert rc == 0
        assert "persisted" in out.getvalue()
        assert resolve_thresholds().trip_per_mode == 4


def test_cli_wrong_token_returns_3():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        err = StringIO()
        with redirect_stderr(err):
            rc = cli_main([
                "--key", "trip_per_mode", "--value", "4",
                "--token", "wrong",
            ])
        assert rc == 3


def test_cli_unknown_key_returns_2_from_argparse():
    with tempfile.TemporaryDirectory() as td:
        _redirect_config(Path(td))
        err = StringIO()
        # argparse choices 검증이 먼저 발화 → SystemExit(2)
        try:
            with redirect_stderr(err):
                cli_main([
                    "--key", "totally_invalid", "--value", "4",
                    "--token", TOKEN_SAFE,
                ])
        except SystemExit as e:
            assert e.code == 2


TESTS = [
    test_default_values_match_module_constants,
    test_resolve_no_yaml_returns_default,
    test_resolve_merges_yaml_override,
    test_yaml_tolerates_comments_and_blanks,
    test_yaml_drops_bogus_keys_and_nonint_values,
    test_increase_requires_strong_token,
    test_decrease_requires_safe_token,
    test_decrease_with_strong_token_also_raises,
    test_window_key_uses_safe_token_both_directions,
    test_apply_idempotent,
    test_unknown_key_and_invalid_value_raise,
    test_composite_uses_yaml_override_for_trip_per_mode,
    test_composite_default_behavior_when_no_yaml,
    test_cli_happy_path,
    test_cli_wrong_token_returns_3,
    test_cli_unknown_key_returns_2_from_argparse,
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
