#!/usr/bin/env python3
"""reviewer.py - PostToolUse hook

Features:
1. Change Log: Records every code modification to <project>/.claude/changelog.md
2. Quality Review: Periodically injects review checklist reminders
3. Error Guidance: Instructs Claude to auto-fix small issues or recommend specialists
4. Tool Routing Feedback: Detects suboptimal tool usage in Bash and suggests dedicated tools
5. Error Recovery Hint: Provides recovery guidance when tool execution fails
6. Stop-Phrase Guard: Detects lazy code patterns in Edit/Write content (merged from stop-phrase-guard.py)
7. Read:Edit Ratio: Tracks research vs modification tool usage balance
8. Spec Verification Sensor: Auto-runs verification scripts when spec files are modified

Non-blocking: reminds, does not block. Only triggers for code files (except Bash sensors).
"""

import sys
import json
import os
import re
import time
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path

# Fix Windows encoding (stdin/stdout default to cp949 on Korean Windows)
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# When invoked directly via `python <abs_path>` (PostToolUse hook), sys.path[0]
# is the script's own directory (handlers/post_tool/), not scripts/. Add
# scripts/ so `from lib.X import ...` resolves.
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# File-path matchers extracted to lib/file_matchers.py (Round 6 W2 P1 — bloat
# reduction, was 18 _match_* helpers in this module).
from lib.file_matchers import (  # noqa: E402
    is_openapi, is_flow, is_er, is_logical, is_ddl, is_class, is_skeleton,
    is_prd_domain, is_prd_root, is_convention, is_code_file, is_fe_contract,
    is_be_dto, is_test_file, is_ci_config, is_collab_config, is_pipeline_md,
    is_impl_code_edit,
)

# --- Configuration ---
REVIEW_COOLDOWN_SECONDS = 120  # Review reminder cooldown
TOOL_ROUTING_COOLDOWN_SECONDS = 60  # Tool routing feedback cooldown
ERROR_RECOVERY_COOLDOWN_SECONDS = 30  # Error recovery hint cooldown
RATIO_WARN_COOLDOWN_SECONDS = 300  # Read:Edit ratio warning cooldown (5 min)

COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_review_cooldown",
)
TOOL_ROUTING_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_tool_routing_cooldown",
)
ERROR_RECOVERY_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_error_recovery_cooldown",
)
RATIO_WARN_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_ratio_warn_cooldown",
)

# Change log: max recent entries to include in review
# CHANGELOG_MAX_RECENT/LINES constants moved to lib/changelog_io.py (W2 P1).

# Read:Edit ratio tracking — counter file/threshold/reset live in lib.ratio_tracker
# (M3 dedup, fixplan-meta debate Gen4). Cooldown surfacing stays here.
from lib.ratio_tracker import (  # noqa: E402
    MODIFY_TOOLS,
    RESEARCH_TOOLS,
    WARN_THRESHOLD as RATIO_WARN_THRESHOLD,
    record_tool_use,
    check_ratio_warning,
)

STOP_PHRASE_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_stop_phrase_cooldown",
)
STOP_PHRASE_COOLDOWN_SECONDS = 60

SPEC_VERIFY_COOLDOWN_SECONDS = 120  # Spec file verification cooldown
CASCADE_COOLDOWN_SECONDS = 300  # Downstream cascade cooldown (5 min)
HARNESS_RETRO_COOLDOWN_SECONDS = 1800  # Harness retrospective prompt (30 min)
HARNESS_GAP_COOLDOWN_SECONDS = 3600  # Manual fix gap-check prompt (60 min)

# Per-script cooldown overrides (seconds)
SCRIPT_COOLDOWN_OVERRIDES = {
    "verify-codegen.py": 600,  # 10min — bulk codegen 시 노이즈 방지
    "verify-contract.py": 300,  # 5min — FE/BE 수정 시 빈번 트리거 방지
    "verify-convention.py": 300,  # 5min — 컨벤션 체크 빈번 트리거 방지
    "verify-test.py": 600,  # 10min — 테스트 파일 수정 시 빈번 트리거 방지
    "verify-collab.py": 600,  # 10min — 협업 인프라 파일은 변경 빈도 낮음
}

# Harness retrospective cooldown files
HARNESS_RETRO_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_harness_retro_cooldown",
)
HARNESS_GAP_COOLDOWN_FILE = os.path.join(
    os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp")),
    ".claude_harness_gap_cooldown",
)

# Directory where this script and other global scripts live
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Verification Dependency DAG ---
# Graph: file change → primary script + downstream cascade scripts
#
#   openapi.yaml ──┬─→ verify-openapi.py (primary)
#                  ├─→ verify-er.py (cascade)
#                  ├─→ verify-logical.py (cascade)
#                  └─→ verify-skeleton.py (cascade) ← DTO SSOT
#
#   conceptual-er.md ──┬─→ verify-er.py (primary)
#                      ├─→ verify-logical.py (cascade)
#                      └─→ verify-ddl.py (cascade)
#
#   logical-design.md ──┬─→ verify-logical.py (primary)
#                       └─→ verify-ddl.py (cascade)
#
#   init/*.sql ──→ verify-ddl.py (leaf)
#   flows/*.md ──┬─→ mermaid-validate.py
#               ├─→ verify-flow.py (cascade) ← 3단계 크로스검증
#               └─→ verify-er.py (cascade)
#   class/*.md ──→ mermaid-validate.py (leaf)
#   requirements/domain/*.md ──┬─→ verify-flow.py (primary) ← PRD↔Flow US 크로스
#                              └─→ verify-prd.py (cascade) ← PRD 내부 정합
#   requirements/*.md (root) ──→ verify-prd.py (leaf) ← index↔domain 정합
#   convention.md ──→ verify-er.py (cascade) ← Convention↔ER D섹션
#
#   skeleton-design.md ──┬─→ verify-skeleton.py (primary)
#                        └─→ verify-codegen.py (cascade, 600s cooldown)
#
#   backend/**/*.java ──→ verify-codegen.py (leaf, 600s cooldown)
#   frontend/src/**/*.{tsx,ts,css} ──→ verify-codegen.py (leaf, 600s cooldown)
#
#   frontend/src/**/api.ts ──→ verify-contract.py (FE contract)
#   frontend/src/**/model.ts ──→ verify-contract.py (FE contract)
#   backend/**/*{Request,Response}.java ──→ verify-contract.py (BE contract)
#   backend/**/domain/**/*.java ──→ verify-contract.py (BE enum contract)
#   openapi.yaml ──(cascade)──→ verify-contract.py
#
#   backend/**/*.java ──→ verify-convention.py (BE convention, 300s cooldown)
#   frontend/src/**/*.{tsx,ts} ──→ verify-convention.py (FE convention, 300s cooldown)
#
#   backend/src/test/**/*.java ──→ verify-test.py (leaf, 600s cooldown)
#
# Harness retrospective sensors (outside DAG, in main()):
#   pipeline.md ──→ 하네스 회고 프롬프트 주입 (30min cooldown)
#   backend/src/main/**/*.java (Edit only) ──→ 갭 체크 프롬프트 (60min cooldown)
#   frontend/src/**/*.{ts,tsx} (Edit only) ──→ 갭 체크 프롬프트 (60min cooldown)
#
# Each node: (match_func, primary_tuple, downstream_list)
#   primary_tuple: (script, label, project_script, pass_file_arg)
#   downstream:    (script, label, project_script)

VERIFICATION_DAG = [
    (is_openapi,  ("verify-openapi.py", "OpenAPI", True, False), [
        ("verify-er.py", "ER", True),
        ("verify-logical.py", "Logical", True),
        ("verify-skeleton.py", "Skeleton", True),
        ("verify-contract.py", "Contract", True),
    ]),
    (is_flow,     ("mermaid-validate.py", "Mermaid", False, True), [
        ("verify-flow.py", "Flow", True),
        ("verify-er.py", "ER", True),
    ]),
    (is_er,       ("verify-er.py", "Conceptual ER", True, False), [
        ("verify-logical.py", "Logical", True),
        ("verify-ddl.py", "DDL", True),
    ]),
    (is_logical,  ("verify-logical.py", "Logical Design", True, False), [
        ("verify-ddl.py", "DDL", True),
    ]),
    (is_ddl,      ("verify-ddl.py", "DDL", True, False), []),
    (is_class,    ("mermaid-validate.py", "Mermaid (Class)", False, True), []),
    (is_prd_domain, ("verify-flow.py", "Flow (PRD cross)", True, False), [
        ("verify-prd.py", "PRD", True),
    ]),
    (is_prd_root,   ("verify-prd.py", "PRD", True, False), []),
    (is_convention, ("verify-er.py", "ER (Convention cross)", True, False), []),
    (is_skeleton, ("verify-skeleton.py", "Skeleton", True, False), [
        ("verify-codegen.py", "Codegen", True),  # skeleton 변경 → 코드 정합 재검증
    ]),
    (is_code_file, ("verify-codegen.py", "Codegen", True, False), [
        ("verify-convention.py", "Convention", True),
    ]),
    (is_fe_contract, ("verify-contract.py", "Contract (FE)", True, False), []),
    (is_be_dto, ("verify-contract.py", "Contract (BE)", True, False), [
        ("verify-convention.py", "Convention", True),
    ]),
    (is_test_file, ("verify-test.py", "Test", True, False), []),
    (is_ci_config, ("verify-ci.py", "CI Config", True, False), []),
    (is_collab_config, ("verify-collab.py", "Collab Infra", True, False), []),
]

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".gd", ".rs", ".go",
    ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".swift",
    ".kt", ".vue", ".svelte", ".sh", ".bash", ".ps1",
}

REVIEW_TOOLS = {"Write", "Edit", "MultiEdit"}

SKIP_PATTERNS = {
    "settings.json", "settings.local.json", ".claude.json",
    "package.json", "package-lock.json", "tsconfig.json",
    ".gitignore", "LICENSE", "changelog.md",
}

SKIP_DIRS = {".claude", "node_modules", ".git", "__pycache__"}

from lib.project_paths import find_claude_dir as _lib_find_claude_dir  # noqa: E402
from lib.cooldown import check_cooldown as _lib_check_cooldown  # noqa: E402

# BASH_TOOL_ROUTING_RULES extracted to lib/bash_tool_routing.py (W2 P1).
# Re-imported below alongside detect_tool_routing_feedback.

# Error-indicator regex pre-filter extracted to lib/repeat_error_tracker.py
# (W22 cohesion fix — worker-1 R2 MED). reviewer + tracker now share the
# same "is this an error output?" semantic.
from lib.repeat_error_tracker import has_error_indicator as detect_error_in_output  # noqa: E402,F401


def track_and_warn_ratio(tool_name):
    """Track tool usage and return warning if Read:Edit ratio is low.

    Counting + threshold via lib.ratio_tracker (M3 dedup); cooldown surfacing
    stays local to reviewer (per-handler concern).
    """
    data = record_tool_use(tool_name)
    if tool_name not in MODIFY_TOOLS:
        return None
    ratio = check_ratio_warning(data)
    if ratio is None:
        return None
    if not check_cooldown(RATIO_WARN_COOLDOWN_FILE, RATIO_WARN_COOLDOWN_SECONDS):
        return None
    return (
        f"<read-edit-ratio-warning>\n"
        f"[Read:Edit 비율 경고] 현재 {ratio:.1f} (권장: ≥{RATIO_WARN_THRESHOLD:.0f})\n"
        f"  리서치(Read/Grep/Glob): {data['research']}회 / "
        f"수정(Edit/Write): {data['modify']}회\n"
        f"  파일을 충분히 읽고 이해한 후 수정하세요.\n"
        f"</read-edit-ratio-warning>"
    )


# Stop-phrase patterns extracted to lib/stop_phrases.py (W15 — M6 partial split,
# fixplan-meta debate Gen4 follow-through). Imported via the alias below to
# preserve any handler-internal callers that referenced check_stop_phrases.
from lib.stop_phrases import check_stop_phrases  # noqa: E402,F401


def spec_cooldown_file(script_name):
    """Get per-script cooldown file path."""
    tmp = os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))
    safe_name = script_name.replace(".", "_").replace("-", "_")
    return os.path.join(tmp, f".claude_spec_verify_{safe_name}")


def file_content_changed(file_path, *, namespace: str = "fhash"):
    """Check if file content changed since last verification (MD5 hash).

    Returns True if content changed or unknown; False if identical.
    Stores hash in temp directory for cross-session persistence.

    namespace isolates hash stores between callers. Default 'fhash' preserves
    the legacy filename '.claude_fhash_<key>' byte-for-byte for existing
    callers; new callers (e.g. skill_lint) pass their own namespace.
    """
    try:
        with open(file_path, "rb") as f:
            current_hash = hashlib.md5(f.read()).hexdigest()
    except Exception:
        return True  # assume changed if unreadable

    tmp = os.environ.get("TEMP", os.environ.get("TMPDIR", "/tmp"))
    cache_key = hashlib.md5(file_path.encode()).hexdigest()[:16]
    hash_file = os.path.join(tmp, f".claude_{namespace}_{cache_key}")

    if os.path.exists(hash_file):
        try:
            with open(hash_file) as f:
                if f.read().strip() == current_hash:
                    return False  # content identical
        except Exception:
            pass

    try:
        with open(hash_file, "w") as f:
            f.write(current_hash)
    except Exception:
        pass

    return True


def resolve_dag_verifications(file_path, cwd):
    """Resolve verification scripts to run using dependency DAG.

    Walks the DAG to find matching nodes, collects primary + downstream scripts.
    Deduplicates by script name. Applies cooldown + hash checks.

    Returns list of result messages (strings) for context injection.
    """
    if not file_path or not cwd:
        return []

    normalized = file_path.replace("\\", "/")
    results = []
    seen_scripts = set()

    for match_fn, primary, downstream in VERIFICATION_DAG:
        if not match_fn(normalized):
            continue

        script, label, project, pass_file = primary

        # --- Primary check: cooldown + hash ---
        if script not in seen_scripts:
            cd_file = spec_cooldown_file(script)
            cooldown = SCRIPT_COOLDOWN_OVERRIDES.get(script, SPEC_VERIFY_COOLDOWN_SECONDS)
            if check_cooldown(cd_file, cooldown):
                if file_content_changed(file_path):
                    extra = [file_path] if pass_file else None
                    result = run_spec_verification(
                        cwd, script, label,
                        project_script=project, extra_args=extra,
                    )
                    if result:
                        results.append(result)
            seen_scripts.add(script)

        # --- Downstream cascade: same cooldown key as primary (no duplication) ---
        for ds_script, ds_label, ds_project in downstream:
            if ds_script in seen_scripts:
                continue
            cd_file = spec_cooldown_file(ds_script)
            if check_cooldown(cd_file, CASCADE_COOLDOWN_SECONDS):
                result = run_spec_verification(
                    cwd, ds_script, f"{ds_label} (cascade)",
                    project_script=ds_project,
                )
                if result:
                    results.append(result)
            seen_scripts.add(ds_script)

    return results


def run_spec_verification(cwd, script_name, label, project_script=True, extra_args=None):
    """Run a verification script and return result message.

    Args:
        cwd: Current working directory (project root)
        script_name: Name of the verification script
        label: Human-readable label for the verification type
        project_script: If True, look in <project>/.claude/scripts/; otherwise global SCRIPTS_DIR
        extra_args: Additional arguments to pass to the script
    """
    if project_script:
        # Try project-level first, fall back to global
        script_path = os.path.join(cwd, ".claude", "scripts", script_name)
        if not os.path.isfile(script_path):
            script_path = os.path.join(SCRIPTS_DIR, script_name)
    else:
        script_path = os.path.join(SCRIPTS_DIR, script_name)

    if not os.path.isfile(script_path):
        return None

    try:
        cmd = [sys.executable, script_path]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
            encoding="utf-8",
        )

        output = result.stdout.strip()
        if not output:
            return None

        if "[FAIL]" in output:
            return (
                f"<spec-verify-fail>\n"
                f"[{label} 검증 실패] 자동 검증에서 문제 발견:\n"
                f"{output}\n"
                f"→ 수정 후 재검증하세요.\n"
                f"</spec-verify-fail>"
            )
        else:
            return (
                f"<spec-verify-pass>\n"
                f"[{label} 검증 통과] {output}\n"
                f"</spec-verify-pass>"
            )

    except subprocess.TimeoutExpired:
        return (
            f"<spec-verify-fail>\n"
            f"[{label} 검증 타임아웃] 30초 초과 — 스크립트를 확인하세요.\n"
            f"</spec-verify-fail>"
        )
    except Exception:
        return None


def find_project_claude_dir(cwd):
    """Find nearest .claude/ directory (any state). Delegated to lib."""
    return _lib_find_claude_dir(cwd)


def should_review():
    """Check the review cooldown. Delegates to lib.cooldown.check_cooldown."""
    return _lib_check_cooldown(COOLDOWN_FILE, REVIEW_COOLDOWN_SECONDS)


def check_cooldown(cooldown_file, cooldown_seconds):
    """Backward-compatible alias for lib.cooldown.check_cooldown.

    Kept so existing reviewer-internal callers (track_and_warn_ratio,
    detect_tool_routing_feedback usage) don't need import rewrites.
    """
    return _lib_check_cooldown(cooldown_file, cooldown_seconds)


def is_code_file(path):
    """Check if file is a code file worth reviewing."""
    if not path:
        return False
    basename = os.path.basename(path)
    if basename in SKIP_PATTERNS:
        return False
    normalized = path.replace("\\", "/")
    for skip_dir in SKIP_DIRS:
        if f"/{skip_dir}/" in normalized:
            return False
    ext = os.path.splitext(path)[1].lower()
    return ext in CODE_EXTENSIONS


# changelog tracking extracted to lib/changelog_io.py (Round 6 W2 P1).
from lib.changelog_io import log_change, get_recent_changes  # noqa: E402,F401


# review reminder + error recovery extracted to lib/review_reminder.py (W2 P1).
from lib.review_reminder import get_review_context  # noqa: E402,F401


# BASH_TOOL_ROUTING_RULES + detect_tool_routing_feedback extracted to
# lib/bash_tool_routing.py (Round 6 W2 P1).
from lib.bash_tool_routing import (  # noqa: E402,F401
    BASH_TOOL_ROUTING_RULES,
    detect_tool_routing_feedback,
)


# detect_error_in_output is now imported from lib.repeat_error_tracker as
# `has_error_indicator` (W22 cohesion). The alias at the top of this file
# preserves all existing call sites in reviewer.py without rewiring.


from lib.review_reminder import get_error_recovery_hint  # noqa: E402,F401


# 2-Strike repeat-error detector extracted to lib/repeat_error_tracker.py (W17).
from lib.repeat_error_tracker import track_repeat_error  # noqa: E402,F401


def main():
    try:
        input_data = json.load(sys.stdin)
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_output = input_data.get("tool_output", "")
        cwd = input_data.get("cwd", "")

        # Collect all additional context pieces
        context_parts = []

        # --- Read:Edit Ratio Tracking (all tools) ---
        ratio_warning = track_and_warn_ratio(tool_name)
        if ratio_warning:
            context_parts.append(ratio_warning)

        # --- 2-Strike repeat-error detector (all tools, no cooldown) ---
        if isinstance(tool_output, str) and detect_error_in_output(tool_output):
            strike = track_repeat_error(tool_name, tool_input, tool_output)
            if strike:
                context_parts.append(strike)

                # --- N-strike research dispatch advisory (Phase 2, W19.1.1+) ---
                # Per debate-1778161608-713bdc gen 4 (snapshot 7add2646...): when
                # the same fingerprint reaches RESEARCH_DISPATCH_THRESHOLD inside
                # an active orchestrator super-session, surface an advisory
                # suggesting `harness-researcher` dispatch via the orchestrator.
                # This handler does NOT spawn the agent itself (locked invariant
                # p0_scope = telemetry_only_no_advisory: PostToolUse channel may
                # surface text but never auto-dispatch). The autopilot or user
                # decides whether to invoke the researcher.
                try:
                    from lib.repeat_error_tracker import extract_error_fingerprint
                    from lib.strike_dispatcher import (
                        RESEARCH_DISPATCH_THRESHOLD, remaining_quota,
                    )
                    fp_pair = extract_error_fingerprint(tool_name, tool_input, tool_output)
                    if fp_pair:
                        fp_digest, _ = fp_pair
                        # The strike message already implies count >= STRIKE_THRESHOLD.
                        # Advisory only; super-session sid (if any) is owned by autopilot.
                        context_parts.append(
                            f"<research-dispatch-advisory>\n"
                            f"  fingerprint={fp_digest} reached RESEARCH_DISPATCH_THRESHOLD="
                            f"{RESEARCH_DISPATCH_THRESHOLD}.\n"
                            f"  If running inside /harness-autopilot, the orchestrator may\n"
                            f"  invoke harness-researcher (tools: WebSearch/WebFetch/Edit\n"
                            f"  on state/research/strikes/) to extract a permanent rule.\n"
                            f"</research-dispatch-advisory>"
                        )
                        # remaining_quota intentionally not displayed here — it
                        # depends on a sid we do not have at handler context.
                        _ = remaining_quota  # quiet unused-import lint
                except Exception:
                    # Fail-open per CLAUDE.md hook discipline: handler failures
                    # never block tool output. The advisory is best-effort.
                    pass

        # --- Bash-specific sensors (tool routing + error recovery) ---
        if tool_name == "Bash":
            command = tool_input.get("command", "")

            # 1. Tool routing feedback (60s cooldown)
            routing_feedback = detect_tool_routing_feedback(command)
            if routing_feedback:
                if check_cooldown(TOOL_ROUTING_COOLDOWN_FILE, TOOL_ROUTING_COOLDOWN_SECONDS):
                    context_parts.append(routing_feedback)

            # 2. Error recovery hint (30s cooldown) - applies to Bash output
            if isinstance(tool_output, str) and detect_error_in_output(tool_output):
                if check_cooldown(ERROR_RECOVERY_COOLDOWN_FILE, ERROR_RECOVERY_COOLDOWN_SECONDS):
                    context_parts.append(get_error_recovery_hint())

            # Bash does NOT trigger changelog or code review
            if context_parts:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "\n\n".join(context_parts),
                    }
                }
                print(json.dumps(output, ensure_ascii=False))

            sys.exit(0)

        # --- Stop-phrase guard (Edit/Write/MultiEdit) ---
        if tool_name in {"Edit", "MultiEdit", "Write"}:
            stop_findings = check_stop_phrases(tool_name, tool_input)
            if stop_findings:
                if check_cooldown(STOP_PHRASE_COOLDOWN_FILE, STOP_PHRASE_COOLDOWN_SECONDS):
                    finding_text = "\n".join(f"  - {f}" for f in stop_findings[:5])
                    context_parts.append(
                        "<stop-phrase-warning>\n"
                        "[품질 경고] 코드에서 지연/회피 패턴 감지:\n"
                        f"{finding_text}\n"
                        "→ 작업을 미루지 말고 지금 완료하세요.\n"
                        "</stop-phrase-warning>"
                    )

        # --- Code editing tools (Write, Edit, MultiEdit) ---
        if tool_name not in REVIEW_TOOLS:
            # For non-Bash, non-REVIEW_TOOLS: check error recovery only
            if isinstance(tool_output, str) and detect_error_in_output(tool_output):
                if check_cooldown(ERROR_RECOVERY_COOLDOWN_FILE, ERROR_RECOVERY_COOLDOWN_SECONDS):
                    context_parts.append(get_error_recovery_hint())
            if context_parts:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "\n\n".join(context_parts),
                    }
                }
                print(json.dumps(output, ensure_ascii=False))
            sys.exit(0)

        file_path = tool_input.get("file_path", "")

        # --- Spec verification sensor (DAG-based resolution) ---
        dag_results = resolve_dag_verifications(file_path, cwd)
        context_parts.extend(dag_results)

        # --- Harness retrospective sensors ---
        normalized_fp = file_path.replace("\\", "/")

        # --- Skill .md frontmatter shape telemetry (P0: telemetry-only, no advisory) ---
        # debate-1777963974-4e8915 ontology_snapshot 833f75770125.
        # Lazy import + try/except gates the silent-fail invariant against ImportError.
        if (tool_name in ("Write", "Edit", "MultiEdit")
                and normalized_fp.endswith(".md")):
            try:
                from lib.skill_lint import is_skill_file, lint_skill_file
                if (is_skill_file(normalized_fp)
                        and file_content_changed(file_path, namespace="skill_lint")):
                    lint_skill_file(file_path, session_id=input_data.get("session_id"))
            except Exception:
                pass

        # --- HANDOFF.md drift advisory (W21+, lib/handoff_drift) ---
        # When the user edits HANDOFF.md, surface a non-blocking advisory if
        # the anchored phase-tree visualization no longer matches the yaml
        # source-of-truth. Fail-open: any error returns None (advisory is
        # best-effort, never blocks the hook output stream).
        if (tool_name in ("Write", "Edit", "MultiEdit")
                and os.path.basename(normalized_fp).lower() == "handoff.md"):
            try:
                from lib.handoff_drift import emit_drift_advisory
                advisory = emit_drift_advisory(file_path)
                if advisory:
                    context_parts.append(advisory)
            except Exception:
                pass

        # 1. Pipeline.md step-complete detection → retrospective prompt
        if is_pipeline_md(normalized_fp):
            if check_cooldown(HARNESS_RETRO_COOLDOWN_FILE, HARNESS_RETRO_COOLDOWN_SECONDS):
                context_parts.append(
                    "<harness-retro>\n"
                    "[하네스 회고 리마인더] pipeline.md가 수정되었습니다.\n"
                    "단계가 완료되었다면 다음을 확인하세요:\n"
                    "1. 이 단계에서 수동으로 발견·수정한 버그가 evaluator로 자동 검출 가능했는지\n"
                    "2. 새로운 evaluator 체크나 센티넬 업데이트가 필요한지\n"
                    "3. DAG에 새 파일 패턴 등록이 필요한지\n"
                    "→ 개선 사항이 있으면 사용자에게 제안하세요.\n"
                    "</harness-retro>"
                )

        # 2. Implementation code Edit (not Write) → gap-check prompt
        if (tool_name == "Edit" and
                is_impl_code_edit(normalized_fp) and
                not dag_results):  # No evaluator already triggered
            if check_cooldown(HARNESS_GAP_COOLDOWN_FILE, HARNESS_GAP_COOLDOWN_SECONDS):
                context_parts.append(
                    "<harness-gap-check>\n"
                    "[하네스 갭 체크] 구현 코드 수동 수정 감지.\n"
                    "이 수정이 버그 수정이라면:\n"
                    "- 기존 evaluator가 검출할 수 있었는지 확인\n"
                    "- 검출 불가했다면 evaluator 보강을 사용자에게 제안\n"
                    "일반 개발이라면 무시하세요.\n"
                    "</harness-gap-check>"
                )

        if not is_code_file(file_path):
            # Non-code files may still have spec verification results
            if context_parts:
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": "\n\n".join(context_parts),
                    }
                }
                print(json.dumps(output, ensure_ascii=False))
            sys.exit(0)

        # Always log the change (no cooldown for logging)
        claude_dir = find_project_claude_dir(cwd) if cwd else None
        log_change(claude_dir, tool_name, file_path)

        # Error recovery for editing tools
        if isinstance(tool_output, str) and detect_error_in_output(tool_output):
            if check_cooldown(ERROR_RECOVERY_COOLDOWN_FILE, ERROR_RECOVERY_COOLDOWN_SECONDS):
                context_parts.append(get_error_recovery_hint())

        # Review reminder with cooldown
        if should_review():
            recent_changes = get_recent_changes(claude_dir)
            review = get_review_context(tool_name, file_path, recent_changes)
            context_parts.append(review)

        if context_parts:
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "\n\n".join(context_parts),
                }
            }
            print(json.dumps(output, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
