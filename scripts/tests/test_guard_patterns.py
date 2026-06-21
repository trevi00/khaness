#!/usr/bin/env python3
"""Unit tests for lib/guard_patterns.py — extracted from guard.py W2 P1."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import guard_patterns as gp  # noqa: E402


def _matches(rules, cmd):
    """Helper: return list of matching rule indices."""
    return [i for i, r in enumerate(rules) if r["regex"].search(cmd)]


def test_deny_count():
    assert len(gp.DENY_PATTERNS) == 10


def test_warn_count():
    assert len(gp.WARN_PATTERNS) == 9


def test_autocorrect_count():
    assert len(gp.BASH_AUTOCORRECT) == 2


def test_sensitive_deny_count():
    assert len(gp.SENSITIVE_FILE_DENY) >= 7


def test_deny_rm_rf_root():
    matched = _matches(gp.DENY_PATTERNS, 'rm -rf /')
    assert len(matched) >= 1


def test_deny_rm_rf_home():
    matched = _matches(gp.DENY_PATTERNS, 'rm -rf ~')
    assert len(matched) >= 1


def test_deny_force_push_main_anywhere():
    """Round 6 W2: --force flag may appear AFTER branch name."""
    matched = _matches(gp.DENY_PATTERNS, 'git push origin main --force')
    assert len(matched) >= 1


def test_deny_drop_database():
    matched = _matches(gp.DENY_PATTERNS, 'mysql -e "DROP DATABASE test"')
    assert len(matched) >= 1


def test_deny_fork_bomb():
    matched = _matches(gp.DENY_PATTERNS, ':(){ :|: & };:')
    assert len(matched) >= 1


def test_deny_chmod_777_root():
    matched = _matches(gp.DENY_PATTERNS, 'chmod -R 777 /')
    assert len(matched) >= 1


def test_warn_reset_hard():
    matched = _matches(gp.WARN_PATTERNS, 'git reset --hard HEAD~1')
    assert len(matched) >= 1


def test_warn_delete_no_where():
    matched = _matches(gp.WARN_PATTERNS, 'DELETE FROM users')
    assert len(matched) >= 1


def test_warn_delete_with_where_no_match():
    matched = _matches(gp.WARN_PATTERNS, 'DELETE FROM users WHERE id=1')
    # Should NOT match the no-WHERE rule, may match nothing
    rule_idx = [i for i, r in enumerate(gp.WARN_PATTERNS)
                if "WHERE 절" in r.get("message", "")]
    assert all(i not in matched for i in rule_idx)


def test_warn_drop_table():
    matched = _matches(gp.WARN_PATTERNS, 'DROP TABLE old_data')
    assert len(matched) >= 1


def test_warn_commit_without_prefix():
    """Conventional commit prefix 없으면 WARN."""
    matched = _matches(gp.WARN_PATTERNS, 'git commit -m "random change"')
    assert len(matched) >= 1


def test_warn_commit_with_feat_prefix_passes():
    matched = _matches(gp.WARN_PATTERNS, 'git commit -m "feat: add login"')
    # The git-flow prefix WARN should NOT trigger
    prefix_rule_idx = [i for i, r in enumerate(gp.WARN_PATTERNS)
                       if "접두사" in r.get("message", "")]
    assert all(i not in matched for i in prefix_rule_idx)


def test_warn_commit_with_company_prefix_passes():
    matched = _matches(gp.WARN_PATTERNS, 'git commit -m "[f/d] 로그인 기능 개발"')
    prefix_rule_idx = [i for i, r in enumerate(gp.WARN_PATTERNS)
                       if "접두사" in r.get("message", "")]
    assert all(i not in matched for i in prefix_rule_idx)


def test_autocorrect_strips_no_verify():
    cmd = "git commit --no-verify -m feat"
    rule = gp.BASH_AUTOCORRECT[0]
    assert rule["regex"].search(cmd)
    fixed = rule["fix"](cmd)
    assert "--no-verify" not in fixed
    assert "git commit" in fixed


def test_sensitive_deny_env_file():
    paths = [".env", ".env.local", ".env.production"]
    for p in paths:
        assert any(r.search(p) for r in gp.SENSITIVE_FILE_DENY), p


def test_sensitive_deny_private_key():
    paths = ["id_rsa", "client.pem", "server.key"]
    for p in paths:
        assert any(r.search(p) for r in gp.SENSITIVE_FILE_DENY), p


def test_sensitive_warn_settings_local():
    matched = [m for r, m in gp.SENSITIVE_FILE_WARN if r.search("settings.local.json")]
    assert len(matched) >= 1


def test_sensitive_warn_dockerfile():
    matched = [m for r, m in gp.SENSITIVE_FILE_WARN if r.search("Dockerfile")]
    assert len(matched) >= 1
    matched2 = [m for r, m in gp.SENSITIVE_FILE_WARN if r.search("docker-compose.yml")]
    assert len(matched2) >= 1


def test_sensitive_path_deny_matches_claude_settings():
    # deep-audit pass-3: direct Write/Edit to the runtime-policy file must be denied.
    for p in ["/home/user/.claude/settings.json",
              "/home/u/.claude/settings.json",
              "D:/proj/.claude/settings.json",
              "C:\\Users\\user\\.claude\\settings.json".replace("\\", "/")]:
        assert any(r.search(p) for r, _ in gp.SENSITIVE_PATH_DENY), p


def test_sensitive_path_deny_excludes_vscode_and_bare():
    # path-scoped: must NOT false-deny editor/app config or a bare settings.json
    for p in ["D:/proj/.vscode/settings.json", "settings.json",
              "C:/app/config/settings.json", "my-settings.json",
              "/home/user/.claude/settings.local.json"]:
        assert not any(r.search(p) for r, _ in gp.SENSITIVE_PATH_DENY), p


def test_check_sensitive_file_denies_runtime_policy():
    # behavioral contract through the guard handler's check_sensitive_file
    from handlers.pre_tool.guard import check_sensitive_file
    deny, _ = check_sensitive_file("/home/user/.claude/settings.json")
    assert deny, "runtime-policy settings.json must be denied"
    deny2, _ = check_sensitive_file("D:/proj/.vscode/settings.json")
    assert not deny2, ".vscode/settings.json must NOT be denied"
    deny3, _ = check_sensitive_file("D:/example_project/src/foo.rs")
    assert not deny3, "ordinary source file must NOT be denied"


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
