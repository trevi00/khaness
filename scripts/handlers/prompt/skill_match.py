#!/usr/bin/env python3
"""skill_match.py - UserPromptSubmit hook

Enhanced multi-dimensional skill matching with decision tree:
1. Keywords  - topic detection (score: +1 per match)
2. Intent    - action detection (score: +2 per match)
3. Paths     - file/folder detection (score: +2 per match)
4. Patterns  - code/library detection (score: +1 per match)
+ Phase detection   - work phase context (informational)
+ Project detection - project type context (informational)
+ Cross-skill refs  - requires: field recommendations
+ Token budget      - truncate lower-scored skills when over budget
+ Tool routing      - recommend native tools over Bash equivalents
+ Sensor reminder   - feedback loop hints for implement/review phases

Skill files: ~/.claude/skills/*.md (YAML-like frontmatter)
"""

import sys
import json
import os
import re
from pathlib import Path

# Fix Windows encoding (stdin/stdout default to cp949 on Korean Windows)
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# Ensure scripts/ on sys.path so lib.* resolves (skill_match runs as standalone hook)
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter, extract_section  # noqa: E402
from lib.frontmatter_norm import split_list_field  # noqa: E402
from lib.phase_detector import detect_phase  # noqa: E402
from lib.logging import log_telemetry  # noqa: E402  Round 7 Phase B.1 — skill_match telemetry
from lib.project_paths import find_claude_dir  # noqa: E402  debate-1779110852 D2 — scan_root resolver
from lib.tech_stack import load_tech_stack  # noqa: E402
from lib.prompt_origin import is_system_reinvocation  # noqa: E402

# Token budget: max chars for FULL-BODY activated skill content combined.
# Lowered 8000→4000 (token-efficiency, wave effort-2): full skill bodies are now
# gated to prompt-relevant matches only (base_score >= FULL_BODY_MIN_SCORE, capped
# at FULL_BODY_TOP_K). Weak or pipeline-only matches render as one-line pointers
# instead of full bodies, so the per-prompt injection no longer dumps coincidental
# or stage-forced skill guides. See journal-2026-06-01-skill-injection-token-diet.
MAX_CONTEXT_CHARS = 4000
# base score (EXCLUDING the +3 pipeline-stage boost) required for full-body injection.
# 3 keeps genuine multi-signal matches (e.g. code-quality score 6, handoff score 3)
# while demoting score<=2 coincidental tech-skill noise and pipeline-only forced
# matches to pointers.
# M22 (debate-1781603679-a14912 D4): resolve via the tunable-threshold config override
# (operator-applied, token-gated) with the in-code default 3 as fallback. Guarded so ANY
# resolution/import failure falls back to 3 — a tunable lookup must never break the prompt
# hook (skill_match.py:564 fail-soft contract; the import-resolve is safe here because the
# hook runs as a fresh short-lived process per prompt, process_lifetime='short_hook').
try:
    from lib.threshold_policy import resolve_threshold as _resolve_threshold  # noqa: E402
    FULL_BODY_MIN_SCORE = _resolve_threshold("skill_match.FULL_BODY_MIN_SCORE", 3)
except Exception:  # noqa: BLE001
    FULL_BODY_MIN_SCORE = 3
FULL_BODY_TOP_K = 3        # max full-body skills per prompt; rest become pointers
MAX_POINTERS = 8           # cap on pointer lines (bounded tail)
# Per-body cap: apply_token_budget keeps the top-ranked skill at FULL length
# ignoring max_chars, so a single huge skill (e.g. an 11K-char guide that matched
# on a coincidental keyword) could blow the budget. Cap every full body to its
# decision-tree(+gotchas) sections beyond this size. 3000 ≈ a full decision tree.
PER_BODY_CAP = 3000

# Project type detection from config files
PROJECT_FILE_SIGNALS = {
    "package.json": "node",
    "tsconfig.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "settings.gradle.kts": "kotlin",
    "pubspec.yaml": "flutter",
    "project.godot": "godot",
    "Gemfile": "ruby",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker",
    "docker-compose.yaml": "docker",
}

PROJECT_DIR_SIGNALS = {
    ".github/workflows": "github-actions",
}

# Render helpers (constant + 4 fns) extracted to lib/skill_match_render (Round 6 W2 P1).
from lib.skill_match_render import (  # noqa: E402
    PROMPT_TOOL_ROUTING_HINTS,
    build_cross_references,
    build_phase_guidance,
    build_sensor_reminder,
    detect_tool_routing_hints,
)


# parse_frontmatter is canonical in lib.frontmatter (imported at module top).
# Older inline copy removed (byte-identical logic) to enforce DRY.


def extract_paths_from_prompt(prompt):
    """Extract file/folder paths mentioned in the prompt."""
    patterns = [
        r"[A-Za-z]:[/\\][\w\uAC00-\uD7A3./\\-]+",   # Windows absolute
        r"(?<!\w)\.{0,2}/[\w\uAC00-\uD7A3./\\-]+",    # Relative paths
        r"[\w\uAC00-\uD7A3-]+/[\w\uAC00-\uD7A3./\\-]+",  # folder/file
    ]
    paths = set()
    for p in patterns:
        for match in re.findall(p, prompt):
            cleaned = match.rstrip("/\\.,;:)")
            if len(cleaned) > 3:
                paths.add(cleaned)
    return paths


# Scoring helpers extracted to lib/skill_score.py (Round 6 W2 P1).
# Aliased on import to preserve _underscore-private names already used by
# match_skill below.
from lib.skill_score import (  # noqa: E402
    is_ascii as _is_ascii,
    keyword_in_prompt as _keyword_in_prompt,
    intent_in_prompt as _intent_in_prompt,
    read_file_head,
    score_skill,
)


def _user_home_dir():
    """USERPROFILE > HOME > expanduser('~'). Empty string if unresolvable."""
    return (
        os.environ.get("USERPROFILE")
        or os.environ.get("HOME")
        or os.path.expanduser("~")
        or ""
    )


def _paths_match_home(parent, home):
    """Robust home-equality: samefile (Windows junction / OneDrive-redirect safe)
    with normcase-eq fallback on OSError (nonexistent paths)."""
    if not home or not parent:
        return False
    try:
        return os.path.samefile(parent, home)
    except OSError:
        return os.path.normcase(os.path.realpath(parent)) == os.path.normcase(
            os.path.realpath(home)
        )


def _resolve_project_scan_root(cwd):
    """Resolve the project scan root (debate-1779110852 5-step locked).

    Returns (parent_path, '') on success or (None, reason_enum) on failure.
    reason_enum is one of {'no_cwd', 'no_claude_dir', 'home_dir'}.

    Steps (verbatim per ontology):
      1. validate cwd non-empty else return (None, 'no_cwd')
      2. find_claude_dir(cwd, content_files=('tech-stack.yaml',))
      3. if no claude_dir return (None, 'no_claude_dir')
      4. parent = dirname(claude_dir)
      5. samefile(parent, HOME) → (None, 'home_dir') else (parent, '')

    TODO(promotion): move to lib/project_scan_root.py when LOC > 30 or 2nd caller.
    """
    if not cwd or not os.path.isdir(cwd):
        return (None, "no_cwd")
    claude_dir = find_claude_dir(cwd, content_files=("tech-stack.yaml",))
    if not claude_dir:
        return (None, "no_claude_dir")
    parent = os.path.dirname(claude_dir)
    home = _user_home_dir()
    if _paths_match_home(parent, home):
        return (None, "home_dir")
    return (parent, "")


def detect_project_type(cwd):
    """Detect project type from files in the project scan root. Returns set of
    type strings.

    Uses _resolve_project_scan_root to walk up from cwd to the nearest
    `.claude/` directory containing `tech-stack.yaml` (the canonical project
    marker per CLAUDE.md §프로젝트 기술 스택 선언) and scans THAT directory's
    children — NOT cwd directly. Prevents picking up home-dir junk
    (~/Dockerfile, ~/build.gradle) when claude is invoked outside a project.
    """
    scan_root, reason = _resolve_project_scan_root(cwd)
    if scan_root is None:
        try:
            log_telemetry(
                "skill_match.scan_root_unresolved", {"reason": reason}
            )
        except Exception:
            pass
        return set()

    types = set()
    try:
        entries = set(os.listdir(scan_root))
        for filename, ptype in PROJECT_FILE_SIGNALS.items():
            if filename in entries:
                types.add(ptype)
        for dirname, ptype in PROJECT_DIR_SIGNALS.items():
            if os.path.isdir(os.path.join(scan_root, dirname)):
                types.add(ptype)
    except Exception:
        pass
    return types


def match_skill(meta, prompt_lower, detected_paths, file_contents_cache):
    """Calculate multi-dimensional match score for a skill.

    Wraps lib.skill_score.score_skill — kept here as the handler-side
    public name so existing callers (tests, main()) don't break.
    """
    return score_skill(meta, prompt_lower, detected_paths, file_contents_cache)


# build_cross_references / build_phase_guidance moved to lib/skill_match_render (W2 P1).


# Token budget logic extracted to lib/skill_token_budget.py (Round 6 W2 P1).
from lib.skill_token_budget import (  # noqa: E402
    apply_token_budget as _apply_token_budget_impl,
    truncate_skill_content,
)


def apply_token_budget(matched_skills):
    """Wrap lib impl with module-local MAX_CONTEXT_CHARS."""
    return _apply_token_budget_impl(matched_skills, max_chars=MAX_CONTEXT_CHARS)


# detect_tool_routing_hints / build_sensor_reminder moved to lib/skill_match_render (W2 P1).


# Pipeline stage detection extracted to lib/pipeline_stage_picker (W2 P1).
from lib.pipeline_stage_picker import detect_pipeline_skills  # noqa: E402,F401


def collect_skill_files(skills_dir, active_paths=None):
    """Collect .md skill files from the tree structure.

    Behavior:
    - active_paths is provided → scan only those subdirectories (tree mode).
    - active_paths is None → recursive os.walk fallback.

    D6 (harness-perfection debate): GSD-namespaced skills are scanned via the
    union of `skills/gsd-*/` (current 75 dirs at SKILLS_DIR root) and
    `skills/_gsd/*` (future migration target). On filename collision, the
    first occurrence wins via dict.setdefault semantics — by walk order
    `skills/` direct (gsd-*) is visited before `_gsd/`. The actual migration
    of files into _gsd/ is deferred to a separate decision.

    invariant: skills/harness-* is forbidden (enforced by
    validators/skill_frontmatter.py::_check_naming, not here).
    """
    skill_files: list[tuple[str, str]] = []
    seen: dict[str, str] = {}  # filename → filepath, for setdefault precedence

    def _add(filename: str, filepath: str) -> None:
        # D6 minor: skills/ direct entries win on collision via setdefault
        if seen.setdefault(filename, filepath) == filepath:
            skill_files.append((filename, filepath))

    if active_paths is not None:
        # Tree mode: only scan active paths
        for rel_path in active_paths:
            scan_dir = os.path.join(skills_dir, rel_path.replace("/", os.sep))
            if os.path.isdir(scan_dir):
                for filename in sorted(os.listdir(scan_dir)):
                    if filename.endswith(".md") and not filename.startswith("_"):
                        _add(filename, os.path.join(scan_dir, filename))
    else:
        # Fallback: recursive scan (no tech-stack.yaml). gsd-* directories
        # are NO LONGER pruned — D6 union policy. _gsd/ subtree is also
        # included if present (os.walk recurses naturally).
        for root, dirs, files in os.walk(skills_dir):
            # Stable order: skills/ direct children visited first by sorting,
            # ensures gsd-* root wins over future _gsd/ on collision.
            dirs.sort()
            for filename in sorted(files):
                if filename.endswith(".md") and not filename.startswith("_"):
                    _add(filename, os.path.join(root, filename))

    return skill_files


def main():
    try:
        input_data = json.load(sys.stdin)
        prompt = input_data.get("prompt", "")

        if not prompt:
            sys.exit(0)

        # Harness re-invocations (<task-notification> etc.) are not user intent —
        # skip skill matching entirely. Without this gate a notification's
        # structural noise (e.g. the 'pat::' / 'pat:in' substrings in a
        # tool-routing summary) score-matches advanced-type-patterns and injects
        # its body. Shared gate (lib.prompt_origin, STEP 3); fires before the
        # skills scan so it short-circuits the whole matcher.
        if is_system_reinvocation(prompt):
            sys.exit(0)

        # Locate skills directory
        home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        skills_dir = os.path.join(home, ".claude", "skills")

        if not os.path.isdir(skills_dir):
            sys.exit(0)

        prompt_lower = prompt.lower()
        detected_paths = extract_paths_from_prompt(prompt)
        file_contents_cache = {}

        # Phase and project type detection
        detected_phases = detect_phase(prompt_lower)
        cwd = input_data.get("cwd", "")
        detected_project_types = detect_project_type(cwd)

        # Tech stack based skill filtering
        active_paths = load_tech_stack(cwd)

        # Pipeline stage skill boosting
        pipeline_skills, pipeline_dge, pipeline_stage_name = detect_pipeline_skills(cwd)

        # If pipeline detected a DGE role, add it to detected phases
        dge_to_phase = {
            "designer": "plan",
            "generator": "implement",
            "evaluator": "review",
        }
        if pipeline_dge and pipeline_dge in dge_to_phase:
            detected_phases.add(dge_to_phase[pipeline_dge])

        matched_skills = []
        all_skills_meta = {}  # for cross-skill resolution
        base_scores = {}  # filename -> prompt-relevance score (EXCLUDING pipeline boost)

        for filename, filepath in collect_skill_files(skills_dir, active_paths):
            # D1 None-guard contract: parse_frontmatter returns None for unreadable
            # or malformed files; we skip silently. setdefault below normalizes the
            # 'name' field for downstream consumers (lib.frontmatter docstring).
            meta_body = parse_frontmatter(filepath)
            if meta_body is None:
                continue
            meta, content = meta_body
            meta.setdefault("name", Path(filename).stem)
            all_skills_meta[filename] = meta

            is_match, score, dims = match_skill(
                meta, prompt_lower, detected_paths, file_contents_cache
            )
            base_score = score  # prompt-relevance only (before pipeline boost)

            # Pipeline stage boost: +3 for skills in current stage
            if filename in pipeline_skills:
                score += 3
                dims.append(f"pipeline:{pipeline_stage_name}")
                is_match = True  # Force match if in pipeline stage

            if is_match:
                matched_skills.append((score, filename, dims, content))
                base_scores[filename] = base_score

        if not matched_skills:
            sys.exit(0)

        # Sort by score descending
        matched_skills.sort(key=lambda x: -x[0])

        # Tiered injection (token-efficiency, wave effort-2): only prompt-relevant
        # matches (base_score >= FULL_BODY_MIN_SCORE, capped at FULL_BODY_TOP_K) get
        # full bodies. Weak (score<=2 coincidental) or pipeline-only forced matches
        # render as one-line pointers — the model still sees they exist (and can
        # /invoke them) without paying the multi-KB body cost on every prompt.
        full_skills = []
        pointer_skills = []
        for entry in matched_skills:
            _score, _name = entry[0], entry[1]
            if (base_scores.get(_name, _score) >= FULL_BODY_MIN_SCORE
                    and len(full_skills) < FULL_BODY_TOP_K):
                full_skills.append(entry)
            else:
                pointer_skills.append(entry)

        # Apply token budget to the full-body set only (pointers are cheap).
        full_skills, was_truncated = apply_token_budget(full_skills)

        # Per-body cap: apply_token_budget keeps the top skill at FULL length
        # ignoring max_chars, so cap each body to its decision-tree(+gotchas)
        # sections if it exceeds PER_BODY_CAP. Bounds the worst case where a huge
        # guide matched on a coincidental keyword.
        capped = []
        for _s, _n, _d, _c in full_skills:
            if len(_c) > PER_BODY_CAP:
                t = truncate_skill_content(_c, level=1)
                if not (t and len(t) <= PER_BODY_CAP):
                    t = truncate_skill_content(_c, level=2)
                if t:
                    _c = t
                else:
                    _c = _c[:PER_BODY_CAP] + "\n…(생략 — 토큰 절약)"
                was_truncated = True
            capped.append((_s, _n, _d, _c))
        full_skills = capped

        # Round 7 Phase B.1 — telemetry instrument (best-effort, never raises).
        # Records which skills the matcher emitted so that cli/telemetry_report
        # can surface top-N matched skills + match frequency over a window.
        # Payload kept small: top 5 names + scores, total count, phases, prompt_len.
        try:
            top5 = [
                # M7: include matched dims so the weight/false-positive audit
                # (cli.skill_telemetry_audit) can see WHICH dimension drove each match —
                # a skill repeatedly firing on a single broad keyword is a FP candidate.
                # M22: include body_chars so the threshold gate's guard (non_truncation_rate)
                # can RE-SIMULATE context-budget pressure at a hypothetical FULL_BODY_MIN_SCORE.
                {"name": name, "score": score, "dims": list(_dims or []),
                 "body_chars": len(_content or "")}
                for score, name, _dims, _content in matched_skills[:5]
            ]
            log_telemetry("skill-match", {
                "top": top5,
                "matched_count": len(matched_skills),
                "full_body_count": len(full_skills),
                "pointer_count": len(pointer_skills),
                "phases": sorted(detected_phases),
                "prompt_len": len(prompt),
                "truncated": bool(was_truncated),
                "pipeline_stage": pipeline_stage_name or None,
            })
        except Exception:
            pass  # never block hook output on telemetry failure

        # Build enhanced context
        context_parts = []

        # Project type context (informational)
        if detected_project_types:
            types_str = " ".join(sorted(detected_project_types))
            context_parts.append(
                f'<project-context types="{types_str}" />'
            )

        # Phase context with guidance
        if detected_phases:
            phase_str = " ".join(sorted(detected_phases))
            guidance = build_phase_guidance(detected_phases, matched_skills)
            context_parts.append(
                f'<detected-phase phases="{phase_str}">\n{guidance}\n</detected-phase>'
            )

        # Matched skills (full body — prompt-relevant only)
        for score, name, dims, content in full_skills:
            dim_str = ", ".join(dims)
            # Check if skill has phase-specific relevance
            meta = all_skills_meta.get(name, {})
            skill_phases = set(split_list_field(meta.get("phase", "")))
            phase_match = ""
            if skill_phases and detected_phases:
                overlap = skill_phases & detected_phases
                if overlap:
                    phase_match = f' phase-match="{" ".join(sorted(overlap))}"'

            context_parts.append(
                f'<skill name="{name}" score="{score}" matched="{dim_str}"{phase_match}>\n'
                f"{content}\n"
                f"</skill>"
            )

        # M2a: proactive thin-skill advisory. If any FULL-BODY-injected skill is a
        # historical thin-fire / false-positive candidate (it usually matches on weak
        # signals but spiked high enough this prompt to inject as an authoritative
        # guide — live telemetry: 8/16 FP candidates do reach full-body), surface a
        # one-line caution so the model treats it critically. Fail-soft + bounded
        # telemetry read: a thin-advisory lookup must never break the prompt hook.
        try:
            from lib.thin_skill_advisor import injected_thin_advisory
            from lib.telemetry_read import iter_events as _iter_skill_events
            _injected = [n for _s, n, _d, _c in full_skills]
            _thin_adv = injected_thin_advisory(_injected, _iter_skill_events("skill-match"))
            if _thin_adv:
                context_parts.append(
                    f"<thin-skill-advisory>\n{_thin_adv}\n</thin-skill-advisory>"
                )
        except Exception:
            pass  # never block hook output on the advisory lookup

        # Weak / pipeline-only matches → compact pointers (token-efficiency).
        # One line each: name + score + dims + short description. The full body is
        # intentionally omitted; the model can /invoke the skill if it turns out
        # relevant. This is the main per-prompt token saving.
        if pointer_skills:
            ptr_lines = []
            for score, name, dims, _content in pointer_skills[:MAX_POINTERS]:
                meta = all_skills_meta.get(name, {})
                desc = str(meta.get("description", "")).strip().replace("\n", " ")
                if len(desc) > 120:
                    desc = desc[:117] + "..."
                # Pointer lines drop the verbose internal dims string (intent:/kw:
                # trivia) — on a pointer-only match the load-bearing signal is the
                # name + description (to decide whether to /invoke), not which dims
                # fired. Full-body <skill> headers keep dims. (token-efficiency W-eff-2)
                line = f"- {name} (score {score}, {len(dims)} signals)"
                if desc:
                    line += f" — {desc}"
                ptr_lines.append(line)
            dropped = len(pointer_skills) - len(ptr_lines)
            tail = f"\n(+{dropped}개 더 낮은 관련도 스킬 생략)" if dropped > 0 else ""
            context_parts.append(
                "<related-skills>\n"
                "아래 스킬이 약하게 관련될 수 있습니다 (전문 내용 생략 — 토큰 절약). "
                "실제로 필요하면 해당 스킬을 직접 호출하세요:\n"
                + "\n".join(ptr_lines)
                + tail
                + "\n</related-skills>"
            )

        # Cross-skill recommendations
        recommendations = build_cross_references(matched_skills, all_skills_meta)
        if recommendations:
            rec_lines = []
            for from_skill, to_skill, desc in recommendations:
                rec_lines.append(f"  {from_skill} -> {to_skill} ({desc})")
            context_parts.append(
                "<cross-references>\n"
                "관련 스킬이 추가로 참고될 수 있습니다:\n"
                + "\n".join(rec_lines)
                + "\n</cross-references>"
            )

        # Token budget truncation notice
        if was_truncated:
            context_parts.append(
                "(일부 스킬이 토큰 절약을 위해 축약되었습니다)"
            )

        context = "\n\n".join(context_parts)

        # Build the main output with activated-skills
        additional_sections = []

        additional_sections.append(
            "<activated-skills>\n"
            "아래 스킬 가이드가 현재 요청과 관련이 있습니다. "
            "이 가이드를 참고하여 작업을 진행하세요.\n\n"
            f"{context}\n"
            "</activated-skills>"
        )

        # Tool routing hints
        routing_hints = detect_tool_routing_hints(prompt_lower)
        if routing_hints:
            hints_text = "\n".join(f"- {h}" for h in routing_hints)
            additional_sections.append(
                "<tool-routing>\n"
                f"{hints_text}\n"
                "</tool-routing>"
            )

        # Sensor reminder for implement/review phases
        sensor_reminders = build_sensor_reminder(detected_phases)
        if sensor_reminders:
            reminders_text = "\n".join(sensor_reminders)
            additional_sections.append(
                "<sensor-reminder>\n"
                f"{reminders_text}\n"
                "</sensor-reminder>"
            )

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n\n".join(additional_sections),
            }
        }

        print(json.dumps(output, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
