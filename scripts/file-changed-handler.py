#!/usr/bin/env python3
"""file-changed-handler.py - FileChanged hook

Triggers when watched files change (external edits, git operations, etc.).
Notifies the model about relevant file changes so it can adapt.

FileChanged hook input schema:
{
  "hook_event_name": "FileChanged",
  "file_paths": [str],        // Changed file paths
  "session_id": str,
  "transcript_path": str,
  "cwd": str
}

Output: {"hookSpecificOutput": {"hookEventName":"FileChanged", "watchPaths": [...]}}
  - watchPaths: update which paths to monitor
"""

import sys
import json
import os

# Fix Windows encoding
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# File categories and their significance
FILE_CATEGORIES = [
    {
        "patterns": [".claude/skills/", ".claude\\skills\\"],
        "label": "스킬 파일",
        "action": "스킬 매칭이 영향받을 수 있습니다. 변경된 스킬을 확인하세요.",
    },
    {
        "patterns": ["CLAUDE.md"],
        "label": "프로젝트 지침",
        "action": "프로젝트 규칙이 변경되었습니다. 새 규칙을 준수하세요.",
    },
    {
        "patterns": ["package.json", "build.gradle", "pom.xml", "Cargo.toml",
                     "pyproject.toml", "requirements.txt", "go.mod"],
        "label": "의존성 파일",
        "action": "의존성이 변경되었습니다. 빌드/설치가 필요할 수 있습니다.",
    },
    {
        "patterns": [".env", ".env.local", ".env.production"],
        "label": "환경 설정",
        "action": "환경 변수가 변경되었습니다. 서버 재시작이 필요할 수 있습니다.",
    },
    {
        "patterns": [".claude/checklist.md", ".claude/plan.md", ".claude/context.md"],
        "label": "프로젝트 컨텍스트",
        "action": "프로젝트 문서가 업데이트되었습니다. 최신 상태를 반영하세요.",
    },
]


def categorize_file(file_path):
    """Determine the category of a changed file."""
    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(normalized)

    for cat in FILE_CATEGORIES:
        for pattern in cat["patterns"]:
            if pattern in normalized or pattern == basename:
                return cat

    return None


def main():
    try:
        input_data = json.load(sys.stdin)

        file_paths = input_data.get("file_paths", [])
        if not file_paths:
            sys.exit(0)

        # Categorize changed files
        notifications = []
        seen_labels = set()

        for fp in file_paths:
            cat = categorize_file(fp)
            if cat and cat["label"] not in seen_labels:
                seen_labels.add(cat["label"])
                basename = os.path.basename(fp)
                notifications.append(f"  [{cat['label']}] {basename} — {cat['action']}")

        if not notifications:
            sys.exit(0)

        notification_text = "\n".join(notifications)

        output = {
            "systemMessage": (
                f"[파일 변경 감지]\n{notification_text}"
            ),
        }

        print(json.dumps(output, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
