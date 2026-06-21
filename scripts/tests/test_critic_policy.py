#!/usr/bin/env python3
"""Tests for lib.critic_policy (v15.10 D4).

Coverage map (every D4 contract clause hit):
  - Default resolution: invoke-list, skip-list, unknown (conservative invoke).
  - YAML override beats default.
  - apply_override invoke→skip with WRONG token → PermissionError.
  - apply_override invoke→skip with configure-critic-policy → persists.
  - apply_override skip→invoke under apply-user-preference → persists.
  - apply_override skip→invoke with WRONG token (e.g. configure-critic-policy
    used on the safe direction) → PermissionError because token must match
    the required tier exactly (defensive).
  - Round-trip: persisted override re-resolves through load_policy.
  - Idempotency: setting current decision returns False, no error.
  - Input validation: empty agent_type / invalid target_decision raises.
  - YAML parser tolerance: comments / blank lines preserved roundtrip.
  - REGISTRY entry exists for 'critic_policy'.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import critic_policy as CP  # noqa: E402


def _redirect_policy_path(tmp: Path) -> Path:
    """Point POLICY_PATH at a clean tmp file for the duration of a test."""
    new_path = tmp / "critic-policy.yaml"
    CP.POLICY_PATH = new_path
    return new_path


def test_defaults_invoke_list():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        for agent in CP.DEFAULT_INVOKE:
            assert CP.resolve(agent) == "invoke"


def test_defaults_skip_list():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        for agent in CP.DEFAULT_SKIP:
            assert CP.resolve(agent) == "skip"


def test_unknown_agent_defaults_to_invoke_conservative():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        assert CP.resolve("some-unknown-agent-xyz") == "invoke"


def test_invoke_to_skip_requires_configure_critic_policy_token():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        # Use harness-planner (invoke default)
        try:
            CP.apply_override("harness-planner", "skip", token="apply-user-preference")
        except PermissionError as e:
            assert "configure-critic-policy" in str(e)
        else:
            raise AssertionError("invoke→skip without configure-critic-policy must raise")


def test_invoke_to_skip_with_correct_token_persists():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        assert CP.apply_override(
            "harness-planner", "skip", token="configure-critic-policy"
        ) is True
        assert CP.resolve("harness-planner") == "skip"


def test_skip_to_invoke_under_apply_user_preference():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        assert CP.apply_override(
            "Explore", "invoke", token="apply-user-preference"
        ) is True
        assert CP.resolve("Explore") == "invoke"


def test_skip_to_invoke_with_wrong_token_raises():
    """Configure-critic-policy is for the GATED direction only — wrong token
    on the safe direction should also fail to keep the tier strict."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        try:
            CP.apply_override("Explore", "invoke", token="configure-critic-policy")
        except PermissionError as e:
            assert "apply-user-preference" in str(e)
        else:
            raise AssertionError(
                "skip→invoke with configure-critic-policy must raise"
            )


def test_apply_override_idempotent():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        # harness-planner already 'invoke' by default
        assert CP.apply_override(
            "harness-planner", "invoke", token="apply-user-preference"
        ) is False
        # Explore already 'skip' by default
        assert CP.apply_override(
            "Explore", "skip", token="configure-critic-policy"
        ) is False


def test_input_validation():
    with tempfile.TemporaryDirectory() as td:
        _redirect_policy_path(Path(td))
        try:
            CP.apply_override("", "skip", token="configure-critic-policy")
        except ValueError:
            pass
        else:
            raise AssertionError("empty agent_type must raise ValueError")
        try:
            CP.apply_override("X", "bogus", token="configure-critic-policy")  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("invalid target_decision must raise ValueError")


def test_yaml_round_trip():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_policy_path(Path(td))
        CP.apply_override("harness-planner", "skip", token="configure-critic-policy")
        CP.apply_override("Explore", "invoke", token="apply-user-preference")
        text = path.read_text(encoding="utf-8")
        assert "version: 1" in text
        assert "Explore: invoke" in text
        assert "harness-planner: skip" in text
        # Re-load via fresh path
        policy = CP.load_policy()
        assert policy["overrides"]["Explore"] == "invoke"
        assert policy["overrides"]["harness-planner"] == "skip"


def test_yaml_parser_tolerates_comments_and_blanks():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_policy_path(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# leading comment\n"
            "\n"
            "version: 1\n"
            "# overrides section follows\n"
            "overrides:\n"
            "  # this agent overridden by operator on 2026-05-17\n"
            "  Explore: invoke\n"
            "  harness-planner: skip\n",
            encoding="utf-8",
        )
        assert CP.resolve("Explore") == "invoke"
        assert CP.resolve("harness-planner") == "skip"


def test_yaml_parser_drops_bogus_values():
    with tempfile.TemporaryDirectory() as td:
        path = _redirect_policy_path(Path(td))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "version: 1\n"
            "overrides:\n"
            "  Explore: bogus\n"        # dropped
            "  harness-planner: skip\n",
            encoding="utf-8",
        )
        # bogus value dropped → Explore reverts to default (skip)
        assert CP.resolve("Explore") == "skip"
        assert CP.resolve("harness-planner") == "skip"


def test_advisory_registry_entry_exists():
    from lib.advisory_ack import REGISTRY, resolve
    # Loading lib.critic_policy at import time registered the entry.
    assert "critic_policy" in REGISTRY
    inst = resolve("critic_policy")
    assert inst.name == "critic_policy"
    assert inst.doc and "agent_type" in inst.doc


TESTS = [
    test_defaults_invoke_list,
    test_defaults_skip_list,
    test_unknown_agent_defaults_to_invoke_conservative,
    test_invoke_to_skip_requires_configure_critic_policy_token,
    test_invoke_to_skip_with_correct_token_persists,
    test_skip_to_invoke_under_apply_user_preference,
    test_skip_to_invoke_with_wrong_token_raises,
    test_apply_override_idempotent,
    test_input_validation,
    test_yaml_round_trip,
    test_yaml_parser_tolerates_comments_and_blanks,
    test_yaml_parser_drops_bogus_values,
    test_advisory_registry_entry_exists,
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
