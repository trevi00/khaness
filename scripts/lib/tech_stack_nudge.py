"""tech_stack_nudge — one-per-project-per-day warning when .claude/tech-stack.yaml is missing.

Extracted from handlers/prompt/context_load.py so the cache TTL, cache path, and
warning string are testable in isolation. The handler imports
`maybe_emit_tech_stack_warning` and forwards its return value (or None) to the
hook output.

Behavior:
- Returns a `<harness-warning>` XML-style block exactly once per project per day.
- Uses a temp-dir JSON cache keyed by the project root path.
- Returns None when the project already has tech-stack.yaml, or when cwd is not
  under a project root that the discovery walk-up can resolve.
"""

import os
import time

from lib.atomic_json import read_json, write_json_atomic
from lib.project_paths import find_project_root

TECH_STACK_WARN_TTL_SEC = 24 * 3600  # one nudge per project per day
TECH_STACK_WARN_CACHE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_tech_stack_warned.json",
)


def maybe_emit_tech_stack_warning(cwd, *, max_levels=5):
    """Emit a one-per-day nudge when cwd is a code project but has no
    .claude/tech-stack.yaml — so new projects don't silently fall back to
    loading every skill in the tree.

    `max_levels` mirrors find_project_root's parameter; tests creating a
    tempdir under USERPROFILE (Windows default) pass max_levels=1 to keep
    the walk inside the tempdir rather than reaching the real user home.

    Returns the warning string, or None if no warning should be emitted.
    """
    project_root = find_project_root(cwd, max_levels=max_levels)
    if not project_root:
        return None
    tech_stack_path = os.path.join(project_root, ".claude", "tech-stack.yaml")
    if os.path.isfile(tech_stack_path):
        return None

    now = time.time()
    cache = read_json(TECH_STACK_WARN_CACHE, default={})
    # Age cleanup
    for k in list(cache.keys()):
        try:
            if now - float(cache[k]) > TECH_STACK_WARN_TTL_SEC:
                del cache[k]
        except Exception:
            del cache[k]

    key = project_root.replace("\\", "/")
    if key in cache:
        return None

    cache[key] = now
    write_json_atomic(TECH_STACK_WARN_CACHE, cache)

    return (
        "<harness-warning type=\"tech-stack-missing\">\n"
        f"프로젝트 루트 `{key}` 에 `.claude/tech-stack.yaml`이 없습니다.\n"
        "스킬 트리 필터링이 적용되지 않아 모든 스택의 스킬이 후보에 오릅니다 (정확도 저하).\n"
        "다음 중 하나를 선택하세요:\n"
        "  1) `.claude/tech-stack.yaml` 생성 (권장). 예:\n"
        "       stack:\n"
        "         language: flutter\n"
        "       extensions:\n"
        "         - flutter/example_app-agent   # 프로젝트 전용 서브트리가 있을 때만\n"
        "  2) 언어만 감지해도 충분하면 `stack.language`만 선언.\n"
        "CLAUDE.md 규칙: '새 프로젝트 시작 시 반드시 tech-stack.yaml 먼저 생성'.\n"
        "</harness-warning>"
    )
