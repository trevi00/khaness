#!/usr/bin/env python3
"""context_load.py - UserPromptSubmit hook

Loads project context documents into the conversation as memory.
Even when conversation context is lost (context window overflow),
these documents let the agent immediately understand the current situation.

Context documents (in <project>/.claude/):
- plan.md       (계획서/설계도) - What needs to be done
- context.md    (맥락노트/시방서) - Current context, decisions, constraints
- checklist.md  (체크리스트/공정표) - Progress tracking, what's done/pending

Searches cwd and parent directories up to 5 levels for .claude/ directory.
"""

import sys
import json
import os
from pathlib import Path

# Fix Windows encoding (stdin/stdout default to cp949 on Korean Windows)
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# When invoked as a hook (`python <abs_path>`), sys.path[0] is this script's
# own directory. Add scripts/ so `from lib.X` resolves.
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# --- Per-turn Read:Edit ratio reset ---
# Shared file paths and reset semantics live in lib/ratio_tracker.py
# (M3 dedup, fixplan-meta debate Gen4).
from lib.ratio_tracker import reset_counts as reset_ratio_counters  # noqa: E402,F401
from lib.project_paths import find_claude_dir, find_project_root  # noqa: E402
from lib.tech_stack_nudge import maybe_emit_tech_stack_warning  # noqa: E402

CONTEXT_FILES = [
    ("plan.md", "계획서/설계도"),
    ("context.md", "맥락노트/시방서"),
    ("checklist.md", "체크리스트/공정표"),
    ("pipeline.md", "파이프라인 진행상황"),
    ("STATE.md", "프로젝트 상태 다이제스트 (GSD 호환)"),
]

# Per-doc injection cap (token-efficiency, wave effort-2): these context docs are
# injected on EVERY UserPromptSubmit. A large plan.md/context.md re-injected each
# prompt is the biggest per-prompt waste in this hook. Cap each doc to a head+tail
# slice — head keeps the goal/overview, tail keeps the current status (often at the
# bottom of plan/checklist docs); the middle is elided with a pointer to the file.
# Small docs (<= cap) are injected whole. Full content is always on disk.
CONTEXT_DOC_CAP = 3000      # chars; docs larger than this are head+tail sliced
_CONTEXT_DOC_HEAD = 1800
_CONTEXT_DOC_TAIL = 1000


def _cap_doc(content: str, filename: str) -> str:
    """Head+tail slice a context doc that exceeds CONTEXT_DOC_CAP. Returns the
    content unchanged when within budget."""
    if len(content) <= CONTEXT_DOC_CAP:
        return content
    head = content[:_CONTEXT_DOC_HEAD].rstrip()
    tail = content[-_CONTEXT_DOC_TAIL:].lstrip()
    elided = len(content) - len(head) - len(tail)
    return (
        f"{head}\n\n"
        f"…(중간 {elided}자 생략 — 토큰 절약; 전체는 `{filename}` 직접 읽기)…\n\n"
        f"{tail}"
    )


def find_project_claude_dir(cwd):
    """Find nearest .claude/ holding context files or tech-stack.yaml.

    Wraps lib.project_paths.find_claude_dir with the context-load specific
    content predicate (any CONTEXT_FILES entry OR tech-stack.yaml).
    """
    content_files = [name for name, _ in CONTEXT_FILES] + ["tech-stack.yaml"]
    return find_claude_dir(cwd, content_files=content_files)


# GSD uses .planning/ directory; also search there for STATE.md
GSD_EXTRA_FILES = [
    (".planning/STATE.md", "프로젝트 상태 다이제스트 (GSD .planning)"),
]


# lib absorption (worker-1 R2 HIGH, W22):
# - tech-stack.yaml language reading → lib.tech_stack.read_language
# - stages.yaml resolution + parsing → lib.pipeline_yaml.{resolve_stages_path,
#   parse_stages, parse_output_list}
# Local YAML helpers below are kept only when no lib equivalent exists.
from lib.tech_stack import read_language as _read_tech_stack_language  # noqa: E402
from lib.pipeline_yaml import parse_stages, resolve_stages_path  # noqa: E402
from lib.pipeline_status import render_pipeline_summary  # noqa: E402


def detect_pipeline_stage(project_root):
    """Detect current pipeline stage by checking output file existence.

    Stages.yaml resolution → lib.pipeline_yaml.
    Stage progression check + render → lib.pipeline_status.
    """
    lang = _read_tech_stack_language(project_root)
    stages_path = resolve_stages_path(project_root, lang)
    if not stages_path:
        return None
    stages = parse_stages(stages_path)
    if not stages:
        return None
    return render_pipeline_summary(stages, project_root)


def main():
    try:
        input_data = json.load(sys.stdin)
        cwd = input_data.get("cwd", "")

        # Reset Read:Edit ratio counters at start of every user turn.
        # This is the R4 refactor: counters scope = one turn, not whole session.
        reset_ratio_counters()

        if not cwd:
            sys.exit(0)

        warning = maybe_emit_tech_stack_warning(cwd)

        claude_dir = find_project_claude_dir(cwd)
        if not claude_dir:
            if warning:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": warning,
                    }
                }, ensure_ascii=False))
            sys.exit(0)

        loaded = []
        if warning:
            loaded.append(warning)
        project_root = os.path.dirname(claude_dir)

        # Pipeline stage detection
        pipeline_summary = detect_pipeline_stage(project_root)
        if pipeline_summary:
            loaded.append(
                '<pipeline-status>\n'
                f"{pipeline_summary}\n"
                '</pipeline-status>'
            )

        # S2 R2 reader (debate-1779267594-edb2a2 D6_reader_count=3):
        # Surface the 5 most recent insights, grouped by correlation_id so
        # the agent picks up the convergent state from prior sessions.
        try:
            from lib import insight_index
            entries = insight_index.query(limit=200)
            if entries:
                # Last 3 distinct SESSION keys (most recent first by appearance).
                # C2 (debate-1781431026-af5f83, ontology 32808a52c893): a
                # work_unit_digest carries correlation_id '<sid>-wu'; collapse it
                # onto its base session '<sid>' so the digest and the learner row
                # it subsumes occupy ONE slot, not two (cap=3). The digest is
                # appended later, so in reversed() order it wins the session slot.
                seen_keys: list[str] = []
                latest_by_key: dict[str, dict] = {}
                for rec in reversed(entries):
                    corr = rec.get("correlation_id", "?")
                    if rec.get("event_type") == "work_unit_digest" and corr.endswith("-wu"):
                        session_key = corr[:-3]
                    else:
                        session_key = corr
                    if session_key in latest_by_key:
                        continue
                    latest_by_key[session_key] = rec
                    seen_keys.append(session_key)
                    # window 5→3 (token-efficiency, wave effort-2): this block is
                    # injected on EVERY prompt; 3 most-recent distinct sessions
                    # is enough orientation. Pointer to full list is in SessionStart.
                    if len(seen_keys) >= 3:
                        break
                if seen_keys:
                    body_lines = []
                    for key in seen_keys:
                        rec = latest_by_key[key]
                        corr = rec.get("correlation_id", "?")
                        # hard-cap the per-line summary (was full up-to-280 chars).
                        # Bounds the always-on block + immune to summary growth.
                        _summ = str(rec.get("summary", ""))
                        if len(_summ) > 100:
                            _summ = _summ[:100] + "…"
                        body_lines.append(
                            f"- [{rec.get('event_type', '?')}] "
                            f"corr={corr[:16]} "
                            f"axis={rec.get('axis') or '-'}: "
                            f"{_summ}"
                        )
                    loaded.append(
                        "<insight-index-recent count=\""
                        + str(len(seen_keys)) + "\">\n"
                        + "\n".join(body_lines)
                        + "\n</insight-index-recent>"
                    )
        except Exception:
            pass

        for filename, label in CONTEXT_FILES:
            filepath = os.path.join(claude_dir, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        loaded.append(
                            f'<context-doc type="{label}" file="{filename}">\n'
                            f"{_cap_doc(content, filename)}\n"
                            f"</context-doc>"
                        )
                except Exception:
                    pass

        # Also load GSD .planning/ files relative to project root
        for rel_path, label in GSD_EXTRA_FILES:
            filepath = os.path.join(project_root, rel_path)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if content:
                        loaded.append(
                            f'<context-doc type="{label}" file="{rel_path}">\n'
                            f"{_cap_doc(content, rel_path)}\n"
                            f"</context-doc>"
                        )
                except Exception:
                    pass

        if not loaded:
            sys.exit(0)

        context = "\n\n".join(loaded)
        project_path = project_root

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": (
                    f"<project-context path=\"{project_path}\">\n"
                    "프로젝트 컨텍스트 문서가 로드되었습니다.\n"
                    "이 문서들을 참고하여 현재 작업 상황을 파악하세요.\n"
                    "중요한 작업 진행 시 관련 문서를 업데이트해주세요.\n\n"
                    f"{context}\n"
                    "</project-context>"
                ),
            }
        }

        print(json.dumps(output, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
