"""skill_candidate_extractor — PostToolUse hook (Hermes 흡수 — Track 2 H1)

Source: /home/user/example_project-analysis/synthesis/HARNESS-APPLY.md H1
Spec adaptation (2026-05-16 v15.2):
  HARNESS-APPLY: Node.js `~/.claude/scripts/skill-candidate-extractor.js`
  Applied: Python `scripts/handlers/post_tool/skill_candidate_extractor.py`
  Reason: 본 하네스 모든 hook가 Python + `handlers/<lifecycle>/<name>.py` 컨벤션

Role: dispatch layer.
  Activation gate: env `SKILL_CANDIDATE_EXTRACTOR_ENABLED=1`.
  Detector binding: separate module `skill_candidate_detector` (out of this hook's scope).

Output target: `~/.claude/skill-candidates/<id>.{json,md}` (detector writes; hook only dispatches).

Safety (HARNESS-APPLY H1 AC-H1-E1):
  silent-on-failure — 모든 exception 흡수, hook chain 중단 안 함. exit 0 강제.

Invariant (synthesis/HERMES-DECISIONS.md §1):
  candidate 추출 = 자동 OK.
  활성화 (skill을 invocation 가능 상태로) = 운영자 명시 `enable-skill` 토큰 (본 hook scope 외).
"""

import os
import sys
from pathlib import Path


def main() -> int:
    """Dispatch entry for PostToolUse.

    Disabled state: return 0 immediately.
    Enabled state: ensure scripts/lib on sys.path, import detector, hand off stdin.
    ImportError or any exception → silent return 0 (AC-H1-E1).
    """
    try:
        if os.environ.get("SKILL_CANDIDATE_EXTRACTOR_ENABLED") != "1":
            return 0
        lib_dir = Path(__file__).resolve().parents[2] / "lib"
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))
        try:
            from skill_candidate_detector import process_payload
        except ImportError:
            return 0
        process_payload(sys.stdin.read())
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
