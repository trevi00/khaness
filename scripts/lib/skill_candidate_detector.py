"""skill_candidate_detector — H1 detection 본문 (Hermes 흡수, Track 2 H1).

Source:
  /home/user/example_project-analysis/synthesis/HARNESS-APPLY.md (Detector module spec, v15.4)
  /home/user/example_project-analysis/synthesis/EXAMPLE_PROJECT-APPLY.md PR-7 step 5 (cross-track atomic)

Role: extractor hook (`handlers/post_tool/skill_candidate_extractor.py`)이 import.
  PostToolUse payload → per-session tracker 갱신 → repetition threshold 도달 시 candidate 생성.

Phase: 2 — pattern_key 도입 (2026-06-01).
  tracker key = (tool_name, pattern_key) composite — same tool, different patterns
  count independently. Phase 1 (tool_name only, _THRESHOLD=3)은 노이즈 과다로
  대체. _THRESHOLD 3→10 상향, pattern_key per-tool extractor:
    Bash → command 첫 2 토큰 ("git status", "npm test")
    Edit/Write/MultiEdit/Read/NotebookEdit → file_path 확장자 (".py", ".md")
    Grep/Glob → pattern 앞 40자
    WebFetch → URL netloc
    WebSearch/ToolSearch → query 앞 토큰
    Skill → skill name
    Agent → subagent_type
    그 외 / tool_input 없음 → "_" (tool-only count fallback)

Invariant (synthesis/HERMES-DECISIONS.md §1):
  candidate 추출 = 자동 OK. 활성화 = 운영자 `enable-skill` 토큰 (본 module scope 외).
  settings.json / 훅 mutation 0 — module은 tracker file과 candidate file만 write.

Safety: process_payload는 try/except로 모든 exception 흡수.
  caller (extractor)도 silent-on-failure이므로 본 module의 raise도 hook chain 영향 없음.
  Legacy flat tracker shape ({tool: int})는 _bump에서 자동 리셋 (silent migration).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from atomic_json import read_json, write_json_atomic

_TRACKER_ROOT = Path.home() / ".claude" / "state" / "skill-candidate-tracker"
_CANDIDATES_ROOT = Path.home() / ".claude" / "skill-candidates"
_THRESHOLD = 10
_PATTERN_MAX_LEN = 40

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xai-[A-Za-z0-9]{20,}"),
    re.compile(r"dashscope-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{40,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
]
_ALLOWLIST = {"<EXAMPLE_KEY>", "${SECRET}", "<API_KEY>", "<TOKEN>"}

# M18 (debate-1781594208-53fee4 gen 3, D3): co-tenancy clobber-guard. The
# skill-wonder-<fingerprint> cid namespace is SHARED by two producers — the
# wonder reflection path (_build_candidate_from_reflection) and the strike-research
# path (_build_candidate_from_strike). A priority-aware _write_candidate closes the
# asymmetric-dedup clobber in BOTH write orders: a lower-priority producer never
# overwrites a higher-priority candidate already on disk. Priority read from
# manifest.metadata.source; absent/unknown source maps to the LOWEST tier (gen-3
# Critic minor note — .get default, never KeyError).
_SOURCE_PRIORITY: dict[str, int] = {"strike_research": 3, "wonder_reflection": 2}
_DEFAULT_SOURCE_PRIORITY = 1  # auto-detected / unknown / absent source


def _source_priority(source: "str | None") -> int:
    return _SOURCE_PRIORITY.get(source or "", _DEFAULT_SOURCE_PRIORITY)


def _candidate_source_on_disk(cid: str) -> "str | None":
    """Read manifest.metadata.source from an already-written candidate, or None."""
    p = _candidate_json_path(cid)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return ((data.get("manifest") or {}).get("metadata") or {}).get("source")


@dataclass(frozen=True)
class SkillCandidate:
    id: str
    schema: str
    manifest: dict
    trace_md: str
    secret_scan_clean: bool


def process_payload(raw: str) -> None:
    """PostToolUse stdin payload → tracker 갱신 → threshold 도달 시 candidate write.

    Best-effort. Any exception → silent return (AC-DET-E1, AC-DET-E2).
    """
    try:
        payload = _parse_payload(raw)
        if payload is None:
            return
        session_id = str(payload.get("session_id") or "unknown")
        tool_name = str(payload.get("tool_name") or "unknown")
        raw_input = payload.get("tool_input")
        tool_input = raw_input if isinstance(raw_input, dict) else None
        pattern_key = _pattern_key(tool_name, tool_input)

        tracker = _load_tracker(session_id)
        count = _bump(tracker, tool_name, pattern_key)
        _save_tracker(session_id, tracker)

        if count < _THRESHOLD:
            return

        candidate = _build_candidate(session_id, tool_name, pattern_key, count)
        if not _secret_scan_pass(candidate):
            _write_blocked_marker(candidate)
            return
        _write_candidate(candidate)
    except Exception:
        return


def _pattern_key(tool_name: str, tool_input: "dict | None") -> str:
    """Derive a pattern key from tool_input for finer-grained repetition tracking.

    Returns "_" when no useful pattern can be extracted — falls back to
    pure tool-only counting for that (tool, session). Max length is
    `_PATTERN_MAX_LEN`; values are truncated to keep tracker dict bounded.
    """
    if not isinstance(tool_input, dict):
        return "_"
    try:
        if tool_name == "Bash":
            cmd = str(tool_input.get("command", "")).strip()
            tokens = cmd.split()[:2]
            return (" ".join(tokens) or "_")[:_PATTERN_MAX_LEN]
        if tool_name in {"Edit", "Write", "MultiEdit", "Read", "NotebookEdit"}:
            fp = str(tool_input.get("file_path", ""))
            return (Path(fp).suffix or "no_ext")[:_PATTERN_MAX_LEN]
        if tool_name in {"Grep", "Glob"}:
            pat = str(tool_input.get("pattern", ""))
            return (pat or "_")[:_PATTERN_MAX_LEN]
        if tool_name == "WebFetch":
            url = str(tool_input.get("url", ""))
            try:
                host = urlparse(url).netloc or "_"
            except Exception:
                host = "_"
            return host[:_PATTERN_MAX_LEN]
        if tool_name == "WebSearch":
            q = str(tool_input.get("query", ""))
            return (" ".join(q.split()[:2]) or "_")[:_PATTERN_MAX_LEN]
        if tool_name == "Skill":
            return (str(tool_input.get("skill", "")) or "_")[:_PATTERN_MAX_LEN]
        if tool_name == "Agent":
            return (str(tool_input.get("subagent_type", "")) or "_")[:_PATTERN_MAX_LEN]
        if tool_name == "ToolSearch":
            q = str(tool_input.get("query", ""))
            return (q or "_")[:_PATTERN_MAX_LEN]
    except Exception:
        return "_"
    return "_"


def _bump(tracker: dict, tool_name: str, pattern_key: str) -> int:
    """Increment count for (tool, pattern). Resets legacy flat-int shape silently."""
    inner = tracker.get(tool_name)
    if not isinstance(inner, dict):
        inner = {}
        tracker[tool_name] = inner
    inner[pattern_key] = int(inner.get(pattern_key, 0)) + 1
    return inner[pattern_key]


def _parse_payload(raw: str) -> dict | None:
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _safe_session_slug(session_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", session_id)[:64] or "unknown"


def _tracker_path(session_id: str) -> Path:
    return _TRACKER_ROOT / f"{_safe_session_slug(session_id)}.json"


def _load_tracker(session_id: str) -> dict:
    data = read_json(_tracker_path(session_id), default={})
    return data if isinstance(data, dict) else {}


def _save_tracker(session_id: str, tracker: dict) -> None:
    _TRACKER_ROOT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(_tracker_path(session_id), tracker)


def _parse_reflection_frontmatter(text: str) -> dict | None:
    """Parse the YAML subset emitted by lib.wonder.write_reflection (PR-A).

    Returns a dict with top-level scalar keys + 'structured_payload' sub-dict
    when present. Returns None when:
      - text does not start with the `---\\n` opening fence
      - closing `---` fence is absent
      - structure does not match the documented PR-A serializer output

    Parser is a deliberate YAML subset matching lib.wonder._validate
    _structured_payload constraints (single-line scalar values, two-space
    nested indent, `null` literal for None target_skill_hint). Avoids the
    pyyaml dependency the stdlib does not provide.
    """
    if not isinstance(text, str) or not text.startswith("---\n"):
        return None
    body = text[4:]
    end = body.find("\n---\n")
    if end == -1:
        idx = body.find("\n---")
        if idx == -1:
            return None
        end = idx
    frontmatter_text = body[:end]
    result: dict[str, Any] = {}
    structured: dict[str, Any] = {}
    in_structured = False
    for line in frontmatter_text.split("\n"):
        if not line:
            continue
        if in_structured:
            if line.startswith("  ") and ":" in line:
                k, _, v = line[2:].partition(":")
                structured[k.strip()] = v.strip()
                continue
            in_structured = False
        if line == "structured_payload:":
            in_structured = True
            continue
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    if structured:
        if structured.get("target_skill_hint") == "null":
            structured["target_skill_hint"] = None
        result["structured_payload"] = structured
    return result


def _build_candidate_from_reflection(
    reflection_path: "Path | str",
) -> "SkillCandidate | None":
    """S1 PR-B adapter: wonder reflection → agentskills.io/v1 skill candidate.

    debate-1779255461-3fd149 LOCK D1+D2 (converged gen 4, sha1
    90d354d71a73). Reads a reflection markdown file produced by
    lib.wonder.write_reflection with structured_payload set (PR-A path)
    and synthesizes a SkillCandidate the existing _secret_scan_pass +
    _write_candidate pipeline can land into ~/.claude/skill-candidates/.

    Returns None (gen-3 C1 'skill_candidate.skipped' semantic) when:
      - reflection_path does not exist or is unreadable
      - frontmatter parse fails
      - structured_payload block is absent (legacy reflection — silently
        skip without error so legacy callers keep working)

    cid pattern: f'skill-wonder-{fingerprint}' (16-char hex from
    reflection frontmatter, matches lib.wonder._HASH_PREFIX_LEN=16).
    Manifest source provenance lives under manifest.metadata.* to
    preserve agentskills.io/v1 top-level schema compliance (gen-3 D2
    schema_format ontology field).

    Caller is expected to: (1) call _secret_scan_pass(candidate) to
    enforce the secret-scan gate, (2) call _write_candidate(candidate)
    on pass / _write_blocked_marker(candidate) on fail. This adapter
    does NOT write files — separation preserves the gen-3 mutation
    boundary (adapter is pure, write paths are existing).
    """
    p = Path(reflection_path) if not isinstance(reflection_path, Path) else reflection_path
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fm = _parse_reflection_frontmatter(text)
    if not isinstance(fm, dict):
        return None
    structured = fm.get("structured_payload")
    if not isinstance(structured, dict):
        return None  # legacy reflection — gen-3 C1 silent skip
    fingerprint = fm.get("fingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 16:
        return None
    if not all(c in "0123456789abcdef" for c in fingerprint):
        return None
    axis = structured.get("axis")
    gotcha_body = structured.get("gotcha_body")
    target_skill_hint = structured.get("target_skill_hint")
    if not isinstance(axis, str) or not axis:
        return None
    if not isinstance(gotcha_body, str) or not gotcha_body:
        return None
    if target_skill_hint is not None and not isinstance(target_skill_hint, str):
        return None
    try:
        ts = int(fm.get("ts", "0") or "0")
    except (TypeError, ValueError):
        ts = 0
    cid = f"skill-wonder-{fingerprint}"
    manifest = {
        "$schema": "https://agentskills.io/schema/v1.json",
        "name": cid,
        "version": "0.1.0",
        "description": f"Wonder-derived gotcha codification candidate (axis={axis})",
        "category": "wonder-gotcha",
        "allowed_tools": [],
        "mutates": False,
        "long_running": False,
        "secret_scan_required": True,
        "metadata": {
            "source": "wonder_reflection",
            "target_skill_hint": target_skill_hint,
            "axis": axis,
            "gotcha_body": gotcha_body,
            "reflection_fingerprint": fingerprint,
            "reflection_path": str(p),
            "ts": ts,
        },
        "activation": {
            "auto": False,
            "confirm_token": "enable-skill",
            "requires_operator": True,
        },
    }
    target_line = (
        f"- Target skill hint: `{target_skill_hint}`\n"
        if isinstance(target_skill_hint, str)
        else "- Target skill hint: (none — operator decides codification target)\n"
    )
    trace_md = (
        f"# Wonder-derived skill candidate: `{cid}`\n\n"
        f"- Source: `lib.wonder` reflection ({fingerprint})\n"
        f"- Reflection path: `{p}`\n"
        f"- Axis: `{axis}`\n"
        f"{target_line}"
        f"- Status: pending operator review "
        f"(`enable-skill` token required for activation)\n\n"
        f"## Proposed gotcha body\n\n"
        f"{gotcha_body}\n"
    )
    candidate = SkillCandidate(
        id=cid,
        schema="agentskills.io/v1",
        manifest=manifest,
        trace_md=trace_md,
        secret_scan_clean=True,
    )
    # S2 W2 wiring (debate-1779267594-edb2a2 D5_W2_correlation_id_type LOCK):
    # correlation_id = reflection_fingerprint (16-hex from frontmatter).
    try:
        from lib import insight_index as _ii
        import time as _time
        _ii.append({
            "event_type": "skill_candidate",
            "summary": (
                f"Wonder→skill candidate: cid={cid} axis={axis} "
                f"hint={target_skill_hint!r}"
            )[:280],
            "ts_unix_ms": ts * 1000 if ts and ts < 10**12 else int(_time.time() * 1000),
            "correlation_id": fingerprint,
            "source_module": "lib.skill_candidate_detector",
            "axis": axis,
            "tags": ["wonder", "skill_candidate"],
            "body_ref": str(p),
        })
    except Exception:
        # Adapter must remain pure under failure — gen-3 C1 mutation boundary.
        pass
    return candidate


def _build_candidate_from_strike(
    fingerprint: str,
    gotcha_body: str,
    target_skill_hint: "str | None",
    artifact_path: str,
) -> "SkillCandidate | None":
    """M18 D3 adapter: harness-researcher strike artifact -> skill candidate.

    Reuses the EXISTING skill-wonder-<fingerprint> cid namespace (matches
    _build_candidate_from_reflection) so the strike-research and wonder paths land
    ONE candidate per fingerprint at the operator's enable-skill gate — no parallel
    namespace that double-produces. manifest.metadata.source = "strike_research"
    (priority tier 3) so the co-tenancy clobber-guard in _write_candidate lets a
    research-backed candidate win over a wonder_reflection one in both write orders.

    Returns None (skip, no error) when fingerprint is not a 16-hex digest (matches
    lib.repeat_error_tracker.extract_error_fingerprint) or gotcha_body is empty.
    Pure: does NOT write — caller runs _secret_scan_pass + _write_candidate.
    """
    if not isinstance(fingerprint, str) or len(fingerprint) != 16:
        return None
    if not all(c in "0123456789abcdef" for c in fingerprint):
        return None
    if not isinstance(gotcha_body, str) or not gotcha_body.strip():
        return None
    if target_skill_hint is not None and not isinstance(target_skill_hint, str):
        return None
    cid = f"skill-wonder-{fingerprint}"
    manifest = {
        "$schema": "https://agentskills.io/schema/v1.json",
        "name": cid,
        "version": "0.1.0",
        "description": "Strike-research gotcha codification candidate (root-cause backed)",
        "category": "strike-gotcha",
        "allowed_tools": [],
        "mutates": False,
        "long_running": False,
        "secret_scan_required": True,
        "metadata": {
            "source": "strike_research",
            "target_skill_hint": target_skill_hint,
            "reflection_fingerprint": fingerprint,
            "strike_research_artifact": artifact_path,
        },
        "activation": {
            "auto": False,
            "confirm_token": "enable-skill",
            "requires_operator": True,
        },
    }
    target_line = (
        f"- Target skill hint: `{target_skill_hint}`\n"
        if isinstance(target_skill_hint, str) and target_skill_hint
        else "- Target skill hint: (none — operator decides codification target)\n"
    )
    trace_md = (
        f"# Strike-research skill candidate: `{cid}`\n\n"
        f"- Source: harness-researcher strike artifact ({fingerprint})\n"
        f"- Research artifact: `{artifact_path}`\n"
        f"{target_line}"
        f"- Status: pending operator review "
        f"(`enable-skill` token required for activation)\n\n"
        f"## Proposed gotcha body\n\n"
        f"{gotcha_body}\n"
    )
    return SkillCandidate(
        id=cid,
        schema="agentskills.io/v1",
        manifest=manifest,
        trace_md=trace_md,
        secret_scan_clean=True,
    )


def _pattern_slug(pattern_key: str) -> str:
    """Stable short slug for embedding pattern_key in candidate id."""
    if pattern_key == "_":
        return "nop"
    return hashlib.sha1(pattern_key.encode("utf-8", errors="replace")).hexdigest()[:6]


def _build_candidate(
    session_id: str, tool_name: str, pattern_key: str, count: int
) -> SkillCandidate:
    safe_session = re.sub(r"[^a-zA-Z0-9]", "", session_id)[:8] or "anon"
    safe_tool = tool_name.lower().replace("_", "-")
    cid = f"skill-{safe_tool}-{_pattern_slug(pattern_key)}-{safe_session}"
    mutates = tool_name in {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    pattern_display = pattern_key if pattern_key != "_" else "(no pattern)"
    description = (
        f"Auto-detected: {tool_name} pattern '{pattern_display}' used "
        f"{count} times in single session"
        if pattern_key != "_"
        else f"Auto-detected: {tool_name} used {count} times in single session "
             f"(no input pattern available)"
    )
    manifest = {
        "$schema": "https://agentskills.io/schema/v1.json",
        "name": cid,
        "version": "0.1.0",
        "description": description,
        "category": "auto-detected",
        "allowed_tools": [tool_name.lower()],
        "mutates": mutates,
        "long_running": False,
        "secret_scan_required": True,
        "metadata": {
            "tool_name": tool_name,
            "pattern_key": pattern_key,
            "count": count,
            "session_id": session_id,
            "phase": 2,
        },
        "activation": {
            "auto": False,
            "confirm_token": "enable-skill",
            "requires_operator": True,
        },
    }
    trace_md = (
        f"# Auto-detected skill candidate: `{cid}`\n\n"
        f"- Session: `{session_id}`\n"
        f"- Tool: `{tool_name}`\n"
        f"- Pattern: `{pattern_display}`\n"
        f"- Repetition: {count} times (threshold: {_THRESHOLD})\n"
        f"- Detected via: claude harness PostToolUse hook (Phase 2 pattern_key)\n"
        f"- Status: pending operator review "
        f"(`enable-skill` token required for activation)\n"
    )
    return SkillCandidate(
        id=cid,
        schema="agentskills.io/v1",
        manifest=manifest,
        trace_md=trace_md,
        secret_scan_clean=True,
    )


def _secret_scan_pass(c: SkillCandidate) -> bool:
    blob = json.dumps(c.manifest, ensure_ascii=False) + "\n" + c.trace_md
    for tok in _ALLOWLIST:
        blob = blob.replace(tok, "")
    for pat in _SECRET_PATTERNS:
        if pat.search(blob):
            return False
    return True


def _candidate_json_path(cid: str) -> Path:
    return _CANDIDATES_ROOT / f"{cid}.json"


def _candidate_md_path(cid: str) -> Path:
    return _CANDIDATES_ROOT / f"{cid}.md"


def _blocked_marker_path(cid: str) -> Path:
    return _CANDIDATES_ROOT / f"{cid}.blocked.json"


def _write_candidate(c: SkillCandidate, *, collision_policy: str = "priority") -> str:
    """Write a candidate's {json,md}; return "written" | "skipped_lower_priority".

    collision_policy (M18 D3 clobber-guard):
      - "priority" (default): on a cid that already exists, overwrite ONLY if the
        incoming candidate's source priority >= the existing one's. A lower-priority
        producer (e.g. wonder_reflection) is SKIPPED so it cannot clobber a
        higher-priority candidate (e.g. strike_research) already on disk. Equal
        priority overwrites (refresh). Default-on so the pre-existing wonder caller
        inherits the guard without an edit, closing BOTH write orders.
      - "overwrite": legacy unconditional atomic write (cid-distinct callers / tests).

    Return value lets the strike caller surface the research artifact onto whichever
    candidate survived a skip (see consume_artifact). Existing callers ignore it.
    """
    _CANDIDATES_ROOT.mkdir(parents=True, exist_ok=True)
    if collision_policy == "priority" and _candidate_json_path(c.id).exists():
        incoming = _source_priority(((c.manifest or {}).get("metadata") or {}).get("source"))
        existing = _source_priority(_candidate_source_on_disk(c.id))
        if incoming < existing:
            return "skipped_lower_priority"
    write_json_atomic(
        _candidate_json_path(c.id),
        {
            "schema": c.schema,
            "id": c.id,
            "manifest": c.manifest,
            "secret_scan_clean": c.secret_scan_clean,
            "status": "pending_review",
        },
    )
    _candidate_md_path(c.id).write_text(c.trace_md, encoding="utf-8")
    return "written"


def _surface_strike_artifact(cid: str, artifact_path: str) -> bool:
    """M18 D3: in-place add manifest.metadata.strike_research_artifact to an existing
    candidate (single field add, no trace_md body rewrite). Idempotent. Returns True
    iff a write occurred. Used so root cause is visible on whichever candidate the
    operator reviews, regardless of strike-vs-wonder landing order."""
    p = _candidate_json_path(cid)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    meta = data.setdefault("manifest", {}).setdefault("metadata", {})
    if not isinstance(meta, dict):
        return False
    if meta.get("strike_research_artifact") == artifact_path:
        return False  # idempotent — already surfaced
    meta["strike_research_artifact"] = artifact_path
    # NOTE: pass the safe-helper call directly (not the local `p`) so the
    # skill_staging_isolation Layer-A AST validator can statically confirm the
    # write target resolves under _CANDIDATES_ROOT.
    write_json_atomic(_candidate_json_path(cid), data)
    return True


def _write_blocked_marker(c: SkillCandidate) -> None:
    _CANDIDATES_ROOT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        _blocked_marker_path(c.id),
        {
            "schema": c.schema,
            "id": c.id,
            "status": "blocked_by_secret_scanner",
        },
    )
