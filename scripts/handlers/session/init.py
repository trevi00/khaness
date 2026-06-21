#!/usr/bin/env python3
"""init.py - SessionStart hook

Registers watchPaths for FileChanged hooks and performs session initialization.

SessionStart hook input schema:
{
  "hook_event_name": "SessionStart",
  "session_id": str,
  "cwd": str
}

Output: {"hookSpecificOutput": {"hookEventName":"SessionStart", "watchPaths": [...]}}
"""

import sys
import json
import os

# Fix Windows encoding
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# Files/dirs to watch for changes
WATCH_PATTERNS = [
    # CLAUDE.md in cwd and parents
    "CLAUDE.md",
    # Project context docs (including HANDOFF for session continuity)
    "HANDOFF.md",
    ".claude/plan.md",
    ".claude/context.md",
    ".claude/checklist.md",
    ".claude/tech-stack.yaml",
    # GSD compatibility
    ".planning/STATE.md",
    ".planning/.continue-here.md",
    ".claude/STATE.md",
    # Dependency files
    "package.json",
    "build.gradle",
    "pom.xml",
    "pubspec.yaml",
    "requirements.txt",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    # MyBatis & Spring config
    "application.yml",
    "mybatis-config.xml",
    "src/main/resources/mapper",
]

# HANDOFF.md auto-load settings.
# 40_000→16_000 (token-efficiency, wave effort-2; operator-approved 2026-06-01).
# HANDOFF auto-load fires once per session; the load-bearing orientation (one-line
# summary, resume command, Current Phase Block / progress table) lives in the top
# ~2-3KB, so a 16KB head preserves resume-orientation (incl. the most-recent 1-2
# wave entries) while dropping ~24KB of historical detail per HANDOFF-present
# session (real files here are 55-308KB, hitting the old 40K cap). load_handoff_content
# already head-reads + emits a "truncated to N bytes" note so the agent Reads the
# full file when it needs deeper history — that machinery is unchanged.
HANDOFF_MAX_BYTES = 16_000

# Always watch user-level skills
USER_WATCH_DIRS = [
    ".claude/skills",
]

MAX_PARENT_LEVELS = 3


def build_watch_paths(cwd):
    """Build list of absolute paths to watch.

    Only watches files/dirs that ACTUALLY EXIST to avoid flooding
    with broad parent directories (e.g., C:/ or C:/Users).
    """
    watch_paths = []

    # User-level paths (always watch if they exist)
    home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    for watch_dir in USER_WATCH_DIRS:
        abs_dir = os.path.join(home, watch_dir)
        if os.path.isdir(abs_dir):
            watch_paths.append(abs_dir.replace("\\", "/"))

    # CWD-relative paths (check current dir and parents)
    current = os.path.normpath(cwd)
    for _ in range(MAX_PARENT_LEVELS + 1):
        for pattern in WATCH_PATTERNS:
            abs_path = os.path.join(current, pattern)
            normalized = abs_path.replace("\\", "/")
            # Only watch files/dirs that actually exist
            if os.path.exists(abs_path):
                watch_paths.append(normalized)

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    return list(set(watch_paths))


def load_handoff_content(cwd):
    """If cwd contains HANDOFF.md, return its content (trimmed) for injection.

    Only reads the project-root HANDOFF.md (no parent traversal) to prevent
    a stale HANDOFF in an ancestor dir from hijacking a new project's session.
    """
    path = os.path.join(cwd, "HANDOFF.md")
    if not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(HANDOFF_MAX_BYTES + 1)
        truncated = size > HANDOFF_MAX_BYTES or len(content) > HANDOFF_MAX_BYTES
        if truncated:
            content = content[:HANDOFF_MAX_BYTES]
        header = (
            "# HANDOFF.md (auto-loaded by session-init hook)\n"
            f"# source: {path.replace(chr(92), '/')}\n"
        )
        if truncated:
            header += f"# NOTE: truncated to {HANDOFF_MAX_BYTES} bytes\n"
        return header + "\n" + content
    except Exception:
        return None


def _ensure_scripts_on_path():
    """Helper: lazily add ~/.claude/scripts to sys.path for cli/lib imports."""
    from pathlib import Path as _Path
    _scripts = _Path(__file__).resolve().parent.parent.parent
    if str(_scripts) not in sys.path:
        sys.path.insert(0, str(_scripts))


def _skill_lint_line():
    """Returns single status line or None on clean state."""
    try:
        _ensure_scripts_on_path()
        from lib.skill_lint_report import (  # handler->lib (was cli/, layer inversion fixed 2026-06-21)
            load_records, latest_per_path, lint,
            evaluate_r003_trigger, file_size_stats, R002_DEFAULT_BYTES,
        )
        records = load_records()
        if not records:
            return None
        latest = latest_per_path(records)
        if not latest:
            return None
        violations = lint(latest, threshold_bytes=R002_DEFAULT_BYTES)
        trigger = evaluate_r003_trigger(
            {"file_size_stats": file_size_stats(latest),
             "r002_violations_count": len(violations)},
            latest=latest,
        )
        if not violations and not trigger["fired"]:
            return None
        parts = []
        if violations:
            parts.append(f"{len(violations)} R002 violation(s)")
        if trigger["fired"]:
            fired = [c for c, hit in trigger["clauses"].items() if hit]
            parts.append(f"R003 fired ({', '.join(fired)})")
        return f"[skill-lint] {' · '.join(parts)} — `python -m cli.skill_lint_report --lint`"
    except Exception:
        return None


def _debate_doubts_line():
    """Returns single status line or None on clean state."""
    try:
        _ensure_scripts_on_path()
        from lib.debate_doubts import count_pending  # handler->lib (was cli/, layer inversion fixed 2026-06-21)
        n = count_pending()
        if n <= 0:
            return None
        return f"[debate-doubts] {n} pending — `python -m cli.debate_doubts` (ack with --acknowledge <sid>)"
    except Exception:
        return None


def _aborted_kha_plan_line():
    """Returns single status line or None on clean state.

    STEP 6 consumer (operator decision 2026-06-04, hybrid): surface
    autopilot/kha-bridge plan-edit aborts — an action signal that was
    previously silent. The producer (lib/autopilot_kha_bridge.py) appends one
    key per abort to the advisory store via .ack(); we surface the count so the
    operator sees aborts at session boot. Silent (None) on zero — preserves the
    all-silent invariant. Fail-open per hook discipline.

    (The l2/skill/atlas _promotion_completed stores are deliberately NOT
    surfaced here — they are completed-event audit logs, forensic-grep only;
    see lib/advisory_ack.py REGISTRY docs.)
    """
    try:
        _ensure_scripts_on_path()
        from lib.advisory_ack import resolve
        n = len(resolve("aborted_kha_plan_validator_fail").load())
        if n <= 0:
            return None
        return (
            f"[aborted-kha-plan] {n} — autopilot/kha-bridge plan-edit abort(s); "
            f"review `state/aborted_kha_plan_validator_fail.txt` (clear after triage)"
        )
    except Exception:
        return None


def _trigger_line():
    """Returns single status line or None on clean state."""
    try:
        _ensure_scripts_on_path()
        from lib.telemetry_read import count_unreviewed_triggers
        n = count_unreviewed_triggers()
        if n <= 0:
            return None
        return f"[strict-design] {n} unreviewed — `/harness-trigger-summary`"
    except Exception:
        return None


def _phase_tree_drift_line(cwd):
    """Returns single status line if HANDOFF.md anchored block drifts from yaml.

    Fail-open: any exception (no HANDOFF, parse error, missing anchors) -> None.
    """
    try:
        _ensure_scripts_on_path()
        from lib.handoff_drift import status_line_for_session
        return status_line_for_session(cwd)
    except Exception:
        return None


def _autopilot_cleanup_terminal():
    """Best-effort prune of terminal autopilot state files (status in
    {done, failed}, heartbeat older than RESUME_WINDOW_SECONDS). Side-effect
    only — count is not surfaced. Fail-soft per hook discipline.

    Wired here (SessionStart) instead of cron because the harness has no
    scheduler — every new session amortizes accumulated terminal records.
    """
    try:
        _ensure_scripts_on_path()
        from lib.autopilot_state import cleanup_terminal_sessions
        cleanup_terminal_sessions()
    except Exception:
        pass


def _writeback_sidecar_gc():
    """Best-effort prune of preimage sidecars older than 30 days. Side-effect
    only — count is not surfaced. Fail-soft.

    Same SessionStart-amortized pattern as _autopilot_cleanup_terminal:
    no harness scheduler exists, so each new session bears a small share
    of housekeeping. Sidecars enable writeback_inspect --rollback; past
    30 days the rollback path expires and disk is reclaimable.
    """
    try:
        _ensure_scripts_on_path()
        from lib.writeback_store import gc_old_sidecars
        gc_old_sidecars()
    except Exception:
        pass


def _evaluator_axis_log_gc():
    """Best-effort prune of state/evaluator/<sid>/ dirs whose
    axis_scores.jsonl mtime is older than 30 days. Side-effect only.

    Per debate-1778248254-0b7092 D6 condition C6: 30-day cleanup convention
    WIRED INTO existing retention path (not separate cron). Same
    SessionStart-amortized pattern as cleanup_terminal_sessions +
    gc_old_sidecars.

    Fail-soft.
    """
    try:
        _ensure_scripts_on_path()
        from lib.axis_scores_log import gc_old_axis_scores
        gc_old_axis_scores()
    except Exception:
        pass


def _subagent_invocations_gc():
    """Best-effort prune of state/subagent_invocations/<sid>.jsonl files
    older than 30 days. Side-effect only.

    Per A2 wiring (commit 7aff8b7, 2026-05-10): every debate / autopilot /
    team / evaluate / ralph dispatch records one JSONL line under
    state/subagent_invocations/<sid>.jsonl. A long-running harness install
    accumulates one file per session; without GC the directory grows
    unbounded. 30 days matches the writeback / evaluator retention windows.

    Fail-soft.
    """
    try:
        _ensure_scripts_on_path()
        from lib.subagent_invocation_log import gc_old_logs
        gc_old_logs()
    except Exception:
        pass


def _work_unit_gc():
    """Best-effort prune of state/work_unit/*.json breadcrumbs + watermark
    sidecars older than 30 days. Side-effect only. Fail-soft.

    Per debate-1781431026-af5f83 (ontology 32808a52c893) C3: the resume-surface
    breadcrumbs (state/work_unit/<sid>.json) and the C1 throttle watermarks
    accumulate one file per session; 30-day mtime GC matches the
    writeback/evaluator/subagent retention family. Same SessionStart-amortized
    pattern (the harness has no scheduler)."""
    try:
        _ensure_scripts_on_path()
        from lib.work_unit_store import gc_old_work_units
        gc_old_work_units()
    except Exception:
        pass


def _graduation_streak_tick():
    """SessionStart-amortized validator-graduation streak tick (Track 1
    debate-1780722434-e5h19n D1a). Runs each TRACKED advisory validator's
    scan() in-process — the COUNTED EVENT is the fresh zero-drift scan RESULT,
    NOT this SessionStart firing — and advances/resets the consecutive-clean
    streak in state/graduation-state.json. Per-validator 12h dedup + a cheap
    mtime-watermark stat-gate bound the interactive-path cost; a slow/raising
    scan leaves that validator's counter UNTOUCHED. Wired here (not cron)
    because the harness has no scheduler — this is the sole amortized
    maintenance site. Side-effect only (ready-line surfaces it). Fail-soft."""
    try:
        _ensure_scripts_on_path()
        from lib.graduation import run_tracked_scans_and_tick
        from validators import graduation_scan_drift
        run_tracked_scans_and_tick(scan_fn=graduation_scan_drift)
    except Exception:
        pass


def _graduation_ready_line():
    """Single <harness-status> line when a tracked validator's streak has
    reached N (ready to graduate advisory→blocking). Ready-signal only — no
    completed counts (STEP-6 token-diet). Silent otherwise. The flip itself is
    token-gated (cli/graduate_validator.py). Fail-soft."""
    try:
        _ensure_scripts_on_path()
        from lib.graduation import ready_validators, TOKEN_GRADUATE
        ready = ready_validators()
        if not ready:
            return None
        return (
            f"[graduation] {len(ready)} ready: {', '.join(ready)} — "
            f"`HARNESS_MUTATION_TOKEN={TOKEN_GRADUATE} "
            f"python -m cli.graduate_validator graduate <name>`"
        )
    except Exception:
        return None


def _mirror_drift_line(cwd):
    """Single <harness-status> line when the project's mirror context brain is
    STALE (debate-1781435805-qb14p7 M4). Marker-gated + git-only via
    lib.mirror_drift.scan — returns None for any non-mirrored project (no
    <cwd>/atlas/mirror/manifest.json), preserving the all-silent invariant. The
    hot path shells only git (fail-soft); cargo/AST runs only at `cli.mirror
    regenerate`, never here. Fail-open per hook discipline."""
    try:
        _ensure_scripts_on_path()
        from lib.mirror_drift import status_line
        return status_line(cwd)
    except Exception:
        return None


def _autopilot_resume_line(cwd):
    """Returns single status line if any active autopilot session exists.

    Per debate-1778224899-c24de4 D2'' (sessionstart resume scan): scan
    state/autopilot/*.json via lib.autopilot_state.list_active_sids,
    filter to in_progress + non-stale (heartbeat < 24h), and emit a
    single advisory line so the new conversation knows there's a session
    that can be resumed.

    Fail-open per hook discipline: any exception returns None silently.
    """
    try:
        _ensure_scripts_on_path()
        from lib.autopilot_state import list_active_sids, read_state
        sids = list_active_sids(cwd_filter=cwd)
        if sids:
            # If multiple, pick most recent heartbeat (deterministic surface)
            states = [(read_state(s), s) for s in sids]
            states_filt = [(st, sid) for st, sid in states if st is not None]
            if states_filt:
                states_filt.sort(key=lambda pair: pair[0].last_heartbeat_ts, reverse=True)
                st, sid = states_filt[0]
                extra = ""
                if len(states_filt) > 1:
                    extra = f" (+{len(states_filt) - 1} 추가 세션 — 최신 heartbeat 기준 선택)"
                return (
                    f"[autopilot-resume] sid={sid} iter={st.iter}/30 — "
                    f"`/harness-autopilot --resume {sid}`로 재개 가능{extra}"
                )
        # C3 (debate-1781431026-af5f83): no active autopilot session — fall back
        # to the harness-owned work_unit breadcrumb so NON-autopilot work also
        # survives a session break. Read-only; never auto-writes HANDOFF.md.
        from lib.work_unit_store import latest_work_unit
        wu = latest_work_unit(cwd=cwd)
        if wu and wu.get("status") not in ("done", "failed"):
            # collapse whitespace/newlines so the resume line stays ONE clean line
            _summ = " ".join(str(wu.get("summary", "")).split())
            if len(_summ) > 100:
                _summ = _summ[:100] + "…"
            _next = " ".join(str(wu.get("next_steps", "")).split())
            _next_part = ""
            if _next:
                if len(_next) > 140:
                    _next = _next[:140] + "…"
                _next_part = f" | 다음: {_next}"
            # W7 (debate-1781493074-c16jtw): fold the work-tree current node into THIS
            # line (no 4th status line). Read-only (W8) — never writes a phase block.
            _cur = _current_node_suffix(cwd)
            _cur_part = f" | {_cur}" if _cur else ""
            # kha SDLC resume hint (debate-1781871696-sdoggn D5 consumer): surface the
            # mirrored .planning/STATE.md phase/plan/status so a non-autopilot resume
            # shows where the kha project stands. This is the seam's named consumer —
            # without it the breadcrumb extra.kha would be write-only. None-safe.
            _kha = (wu.get("extra") or {}).get("kha") or {}
            _kha_part = ""
            if _kha:
                _bits = []
                # cap + collapse whitespace/newlines: STATE.md frontmatter is
                # parsed raw (no normalization), so bound length AND strip control
                # chars before this reaches SessionStart additionalContext — keeps
                # the resume line one-clean-line and denies injection via a
                # hand-crafted .planning/STATE.md (sibling _summ/_next do the same).
                _ph = " ".join(str(_kha.get("current_phase", "")).split())[:24]
                _pl = " ".join(str(_kha.get("current_plan", "")).split())[:24]
                _st = " ".join(str(_kha.get("status", "")).split())[:24]
                if _ph:
                    _bits.append(f"phase {_ph}")
                if _pl:
                    _bits.append(f"plan {_pl}")
                if _st:
                    _bits.append(_st)
                if _bits:
                    _kha_part = f" | kha: {', '.join(_bits)}"
            return (
                f"[work-resume] 직전 작업: {_summ}{_next_part}{_cur_part}{_kha_part} — 이어서 진행하려면 "
                f"이 컨텍스트에서 계속하세요 (state/work_unit/{wu.get('sid')}.json)"
            )
        return None
    except Exception:
        return None


def _current_node_suffix(cwd):
    """W6 (debate-1781493074-c16jtw): resolve the work-tree current-node suffix for
    `cwd`, precedence: (1) per-project <project>/atlas/mirror/PHASES.md (when a mirror
    exists), (2) global ~/.claude/HANDOFF.md (cwd under CLAUDE_HOME), (3) ''. READ-ONLY
    (W8). Returns the '현재: …' string for folding into the work-resume line, or '' on
    any miss/error (fail-soft — never raises into the hook)."""
    try:
        _ensure_scripts_on_path()
        from pathlib import Path
        from lib import handoff_drift
        text = None
        # (1) per-project mirror PHASES.md
        try:
            from lib.mirror_drift import find_mirror_root
            root = find_mirror_root(cwd)
            if root:
                p = Path(root) / "atlas" / "mirror" / "PHASES.md"
                if p.is_file():
                    text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        # (2) global harness HANDOFF.md (cwd resolves under CLAUDE_HOME)
        if text is None:
            try:
                from lib.paths import CLAUDE_HOME
                home = Path(CLAUDE_HOME).resolve()
                here = Path(cwd).resolve()
                if here == home or home in here.parents:
                    hp = home / "HANDOFF.md"
                    if hp.is_file():
                        text = hp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        if not text:
            return ""
        return handoff_drift.current_node_suffix(text)
    except Exception:
        return ""


def _expired_action_line(cwd):
    """Returns single status line if HANDOFF.md has a `due: YYYY-MM-DD`
    next_action that has expired (today >= due_date).

    Per debate-1779159195-6630f7 LOCK target D8: time-bounded next_action
    expiration advisory at SessionStart. Read-only — no cron, no
    settings.json mutation, no debate auto-spawn. Operator sees the
    advisory and decides (escalate vs retire). Fail-open per hook
    discipline: any exception returns None silently.

    Pattern scanned: `due[: =] YYYY-MM-DD` (case-insensitive, optional
    quote/whitespace). First match's date is reported; total count
    suffix appended if more than one expired.
    """
    try:
        import re
        from datetime import date
        if not cwd:
            return None
        handoff_path = os.path.join(cwd, "HANDOFF.md")
        if not os.path.isfile(handoff_path):
            return None
        with open(handoff_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(HANDOFF_MAX_BYTES + 1)
        pattern = re.compile(
            r"due[\s:=]+['\"]?(\d{4}-\d{2}-\d{2})['\"]?",
            re.IGNORECASE,
        )
        today = date.today()
        expired = []
        for m in pattern.finditer(content):
            try:
                due = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if today >= due and m.group(1) not in expired:
                expired.append(m.group(1))
        if not expired:
            return None
        extra = f" (+{len(expired) - 1} more)" if len(expired) > 1 else ""
        return (
            f"[expired-action] HANDOFF.md next_action due={expired[0]} "
            f"(today={today.isoformat()}) — escalate or retire{extra}"
        )
    except Exception:
        return None


def _skill_candidate_line():
    """S1 PR-C operator surface — debate-1779255461-3fd149 LOCK D4.

    Counts files under ~/.claude/skill-candidates/ (both repeat-tool
    detector AND wonder-derived candidates land here per gen-3 D3 LOCK).
    Returns single status line or None when count==0 (silent on clean
    state — preserves all-silent invariant of every other line helper).

    Fail-open per hook discipline: any exception → None silently.

    This is a NEW line (gen-3 critic B1 + architect adjudication: prior
    Planner claim of 'reuse existing _skill_candidate_line' was rejected
    as fabrication — no such function existed before this commit).
    """
    try:
        import os as _os
        home = _os.environ.get("USERPROFILE") or _os.path.expanduser("~")
        cdir = _os.path.join(home, ".claude", "skill-candidates")
        if not _os.path.isdir(cdir):
            return None
        # Count .json manifests (sidecar .md / .blocked.json files are
        # not separate candidates — they belong to a paired .json).
        n = 0
        for entry in _os.listdir(cdir):
            if entry.endswith(".json") and not entry.endswith(".blocked.json"):
                n += 1
        if n <= 0:
            return None
        return (
            f"[skill-candidate] {n} pending — review files under "
            f"~/.claude/skill-candidates/ then activate via `enable-skill` token"
        )
    except Exception:
        return None


def _insight_index_line():
    """S2 R1 reader (debate-1779267594-edb2a2 LOCK D6_reader_count=3).

    Counts unretracted entries in ~/.claude/memory/insight-index.jsonl
    and surfaces a one-line summary so the new session sees the L1
    insight inventory at boot. Returns None when count==0 (preserves
    all-silent invariant on clean state). Fail-open per hook discipline.
    """
    try:
        _ensure_scripts_on_path()
        from lib import insight_index
        entries = insight_index.query(limit=1024)
        n = len(entries)
        if n <= 0:
            return None
        # Distinct event types in the recent window for quick orientation.
        types = sorted({e.get("event_type", "?") for e in entries[-50:]})
        types_summary = ", ".join(types[:4]) + ("..." if len(types) > 4 else "")
        return (
            f"[insight-index] {n} entry — types: {types_summary} — "
            f"`python -m cli.insight_index_cli list --tail 10`"
        )
    except Exception:
        return None


def _brain_divergence_line():
    """M23 (debate-1781653780-m23a01, LOCK 8b1f22b8) read-only brain-divergence advisory.

    Surfaces live L1/L2 learned-state NOT yet snapshotted to brain/ so the operator can
    run a brain push before machine handoff — brain/ is the SINGLE durable copy, so an
    un-snapshotted record is lost on machine death (the gap a non-autopilot session can
    leave when it ends inside the Stop-hook throttle window). This closes the M23
    detection-to-operator gap: M29's check_brain_push detector wrote a flag no SessionStart
    surface read; this is that missing read-only wire.

    DIVERGENCE is the SOLE source of truth (brain_store.status().live_not_in_brain) — the
    cron brain-push-ready.flag is NOT consulted because it goes stale (the throttled
    Stop-hook auto-save clears divergence without consuming the flag, which only the
    token-gated run_brain_push removes). status() is PURE-READ, so this does NOT enter the
    INV-save-locked write window (INV-save forbids a SessionStart SAVE/tick that races the
    live appenders, not a READ). Returns None on zero divergence (all-silent invariant).
    Fail-soft per hook discipline.
    """
    try:
        _ensure_scripts_on_path()
        from lib import brain_store
        status = brain_store.status()
        total = 0
        for layer in ("l1", "l2"):
            ls = status.get(layer) or {}
            if not isinstance(ls, dict):
                continue
            for entry in ls.values():
                if isinstance(entry, dict):
                    v = entry.get("live_not_in_brain")
                    if isinstance(v, int) and v > 0:
                        total += v
        if total <= 0:
            return None
        return (
            f"[brain-divergence] {total} live insight(s) not yet in brain/ — "
            f"`python -m cli.brain_snapshot save` before machine handoff"
        )
    except Exception:
        return None


def _cron_liveness_line():
    """D4 (M-cron) read-only cron liveness/health advisory. Surfaces a STALE scheduler
    (no pass in > _LIVENESS_MAX_H — down OR the machine was off that long) and jobs stuck
    failing (consecutive_failures >= 3). 'never_run' (no heartbeat — scheduler not set up
    yet) stays SILENT so it never nags before the operator registers it; only a scheduler
    that WAS running and stopped warns. Pure-read, fail-soft, None when healthy."""
    try:
        _ensure_scripts_on_path()
        from cron.scheduler_driver import cron_health
        h = cron_health()
        lv = h["liveness"]
        parts = []
        if lv["state"] == "stale":
            parts.append(f"no scheduler pass in {lv['hours_since']}h (down or machine off)")
        if h["failing"]:
            parts.append(f"{len(h['failing'])} job(s) stuck failing: {', '.join(h['failing'])}")
        if not parts:
            return None
        return "[cron] " + "; ".join(parts) + " — `python -m cron.scheduler_driver --status`"
    except Exception:
        return None


def _brain_unpushed_line():
    """E1 (M-brain-handoff) read-only advisory for the brain/ FILE→GIT→REMOTE hop.

    Closes the 'false silence' gap: _brain_divergence_line watches live→file (which the
    throttled Stop-hook auto-save routinely zeroes by writing the file), so the most
    dangerous durability state — brain/ saved-to-file but UNCOMMITTED, or committed but
    UNPUSHED — produced a SILENT SessionStart even though that state is only on the
    local disk and dies with the machine. This surfaces the real push-before-handoff
    nudge. Pure-read (git status/log on the CLAUDE_HOME repo), fail-soft, None when
    brain/ is fully pushed (all-silent invariant)."""
    try:
        _ensure_scripts_on_path()
        from lib.brain_git_status import brain_durability
        d = brain_durability()
        if not d["at_risk"]:
            return None
        if d["mode"] == "branch":
            # D1 auto-push exists but the live brain/ isn't on origin/brain-snapshots yet
            # (cron hasn't run, or a non-ff needs reconcile).
            return (f"[brain-handoff] {d['detail']} (local disk only) — "
                    "`HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.run_brain_push` to push")
        return (f"[brain-handoff] {d['detail']} on local disk only — "
                "`git add brain/ && git commit && git push` before machine handoff")
    except Exception:
        return None


def _compose_harness_status(cwd=""):
    """Unified <harness-status> block. Returns None when all lines silent."""
    lines = [ln for ln in (
        _trigger_line(),
        _skill_lint_line(),
        _debate_doubts_line(),
        _aborted_kha_plan_line(),
        _phase_tree_drift_line(cwd),
        _mirror_drift_line(cwd),
        _autopilot_resume_line(cwd),
        _expired_action_line(cwd),
        _skill_candidate_line(),
        _insight_index_line(),
        _graduation_ready_line(),
        _brain_divergence_line(),
        _brain_unpushed_line(),
        _cron_liveness_line(),
    ) if ln]
    if not lines:
        return None
    body = "\n".join(lines)
    return f"<harness-status>\n{body}\n</harness-status>"


def main():
    try:
        input_data = json.load(sys.stdin)
        cwd = input_data.get("cwd", "")

        if not cwd:
            sys.exit(0)

        watch_paths = build_watch_paths(cwd)
        handoff = load_handoff_content(cwd)
        # Side-effect maintenance — must run before status compose so
        # _autopilot_resume_line sees the post-cleanup directory state.
        _autopilot_cleanup_terminal()
        _writeback_sidecar_gc()
        _evaluator_axis_log_gc()
        _subagent_invocations_gc()
        _work_unit_gc()
        _graduation_streak_tick()
        # Unified status block (consolidated from 3 separate advisories
        # 2026-05-05 — cognitive load reduction; W21+ adds phase-tree drift).
        status = _compose_harness_status(cwd)

        hook_output = {"hookEventName": "SessionStart"}
        if watch_paths:
            hook_output["watchPaths"] = watch_paths
        ctx_parts = [p for p in (handoff, status) if p]
        if ctx_parts:
            hook_output["additionalContext"] = "\n\n".join(ctx_parts)

        if len(hook_output) == 1:
            sys.exit(0)

        print(json.dumps({"hookSpecificOutput": hook_output}, ensure_ascii=False))

    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
