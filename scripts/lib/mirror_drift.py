#!/usr/bin/env python3
"""mirror_drift — per-project mirror context brain: DETECT (hot path) + REGENERATE.

Locked by debate-1781435805-qb14p7 (ontology c4ad11f4d9a2).

scan(cwd)  — the SessionStart HOT PATH (M4): project-marker-gated (inert unless
             <project>/atlas/mirror/manifest.json exists), git-only/file-read-only,
             NO toolchain. Compares the manifest fingerprint to a freshly recomputed
             one; returns the stale scopes. Fail-soft on git absence (BIND-2).
regenerate(cwd) — the on-demand path (M4): runs the per-stack extractor's heavy
             extract_structure (MAY shell cargo/AST), re-stamps manifest hashes +
             fingerprint, writes STRUCTURE.md. Prose NARRATIVE.md is a SEPARATE
             writer (M8/BIND-3), not produced here.

Lives in lib/ (not validators/) because it is PROJECT-scoped, whereas the
validators/ family scans the CLAUDE_HOME harness; keeping it out of
validators._BUILTIN avoids run_all coupling (the run_units test owns its
regression). Writes ONLY under <project>/atlas/mirror/ (M7 sub-Atlas envelope:
project-repo-local, never ~/.claude, never runtime policy).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lib.mirror_extractors import (
    MANIFEST_RELPATH,
    SCHEMA_VERSION,
    compute_fingerprint,
    detect_extractor,
    get_extractor,
    working_tree_clean,
)


def _mirror_dir(cwd: str) -> Path:
    return Path(cwd) / MANIFEST_RELPATH[0] / MANIFEST_RELPATH[1]


def manifest_path(cwd: str) -> Path:
    return Path(cwd, *MANIFEST_RELPATH)


def find_mirror_root(cwd: str) -> str | None:
    """Walk UP from cwd to the nearest dir holding atlas/mirror/manifest.json, so
    the mirror is discoverable from ANY subdir of the project (usability) — not
    only when the session launches exactly at the project root. None if no mirror
    exists anywhere up the tree (=> inert)."""
    try:
        cur = Path(cwd).resolve()
    except OSError:
        return None
    for d in (cur, *cur.parents):
        if (d / MANIFEST_RELPATH[0] / MANIFEST_RELPATH[1] / MANIFEST_RELPATH[2]).is_file():
            return str(d)
    return None


def validate_manifest(m: dict) -> list[str]:
    """Return a list of structural problems (empty = valid). Enforces the manifest
    contract at READ time so a corrupted/hand-broken manifest surfaces loudly
    instead of silently disabling drift detection (stability). Also enforces BIND-4
    (a coarse scope MUST carry a coarse_reason)."""
    problems: list[str] = []
    scopes = m.get("scopes")
    if not isinstance(scopes, list):
        problems.append("scopes missing or not a list")
    else:
        for i, sc in enumerate(scopes):
            if not isinstance(sc, dict) or not {"name", "globs", "mode"} <= set(sc):
                problems.append(f"scope[{i}] missing name/globs/mode")
                continue
            if sc.get("mode") == "coarse" and not sc.get("coarse_reason"):
                problems.append(f"scope '{sc.get('name')}' is coarse without coarse_reason (BIND-4)")
    if not m.get("fingerprint"):
        problems.append("fingerprint missing")
    return problems


def read_manifest(cwd: str) -> dict | None:
    p = manifest_path(cwd)
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _git_head(cwd: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "rev-parse", "HEAD"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15)
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _line_comment_for(manifest: dict):
    try:
        return get_extractor(manifest.get("extractor", "pathglob")).comment_syntax()[0]
    except Exception:  # unknown extractor -> treat as no-comment (coarse)
        return None


# ── DETECT (hot path) ────────────────────────────────────────────────────────

def scan(cwd: str) -> dict:
    """Marker-gated, git-only drift detect. Returns:
      {marker: bool, scopes_checked: int, stale_scopes: [..], fingerprint_match: bool,
       unverifiable: bool}.
    INERT (marker False) when no manifest is found up the tree from cwd — zero git
    calls, no banner. INVALID (marker True + invalid[]) when the manifest is
    structurally broken. UNVERIFIABLE (fail-open) when git is absent (BIND-2). A
    fast-path returns clean WITHOUT reading any scope file when HEAD ==
    generated_at_commit and the tracked tree is clean (the fingerprint is provably
    unchanged). The result carries `root` (the resolved mirror dir). Never raises."""
    inert = {"marker": False, "root": None, "scopes_checked": 0, "stale_scopes": [],
             "fingerprint_match": True, "unverifiable": False, "invalid": []}
    try:
        root = find_mirror_root(cwd)
        if root is None:
            return inert
        manifest = read_manifest(root)
        if not manifest:
            return inert
        problems = validate_manifest(manifest)
        if problems:
            return {"marker": True, "root": root, "scopes_checked": 0, "stale_scopes": [],
                    "fingerprint_match": True, "unverifiable": False, "invalid": problems}
        scopes = manifest["scopes"]
        # ── fast-path (stability/perf): same commit + clean tracked tree + matching
        #    schema => fingerprint provably == manifest; skip ALL file reads. ──
        head = _git_head(root)
        if (head and head == manifest.get("generated_at_commit")
                and str(manifest.get("schema_version")) == str(SCHEMA_VERSION)
                and working_tree_clean(root) is True):
            return {"marker": True, "root": root, "scopes_checked": len(scopes),
                    "stale_scopes": [], "fingerprint_match": True, "unverifiable": False,
                    "invalid": [], "fast_path": True}
        line_comment = _line_comment_for(manifest)
        fp, per_scope = compute_fingerprint(root, scopes, line_comment)
        if fp is None:  # git unavailable -> unverifiable, fail-open inert
            return {"marker": True, "root": root, "scopes_checked": 0, "stale_scopes": [],
                    "fingerprint_match": True, "unverifiable": True, "invalid": []}
        stale = [sc["name"] for sc in scopes if per_scope.get(sc["name"]) != sc.get("hash")]
        return {"marker": True, "root": root, "scopes_checked": len(scopes), "stale_scopes": stale,
                "fingerprint_match": (fp == manifest.get("fingerprint")), "unverifiable": False,
                "invalid": []}
    except Exception:
        return inert  # absolute fail-open: drift detect never breaks the hot path


def status_line(cwd: str) -> str | None:
    """SessionStart surface: a single line ONLY when a mirror exists AND is stale.
    None otherwise (inert / clean / unverifiable) — preserves the all-silent
    invariant of the harness-status block."""
    r = scan(cwd)
    if not r.get("marker"):
        return None
    if r.get("invalid"):
        return (f"[mirror-drift] manifest invalid ({'; '.join(r['invalid'][:2])}) — "
                f"`python -m cli.mirror regenerate`로 재생성")
    if r.get("unverifiable") or r.get("fingerprint_match"):
        return None
    stale = r.get("stale_scopes") or []
    if not stale:
        return None
    return (f"[mirror-drift] {len(stale)} scope(s) STALE: {', '.join(stale)} — "
            f"`python -m cli.mirror regenerate`로 미러 갱신")


# ── REGENERATE (on-demand) ───────────────────────────────────────────────────

def regenerate(cwd: str) -> dict:
    """Rebuild the mirror: pick/keep scopes, recompute per-scope hashes +
    fingerprint, write manifest.json + STRUCTURE.md under <project>/atlas/mirror/.
    Returns a summary. Heavy extraction allowed here (M4). If an existing mirror is
    found up the tree from cwd, it is refreshed in place (re-running from a subdir
    targets the right mirror); otherwise a new mirror is created at cwd."""
    cwd = find_mirror_root(cwd) or cwd
    mdir = _mirror_dir(cwd)
    mdir.mkdir(parents=True, exist_ok=True)
    existing = read_manifest(cwd)
    if existing and existing.get("extractor"):
        ext_key = existing["extractor"]
    else:
        ext_key = detect_extractor(cwd)
    extractor = get_extractor(ext_key)
    scopes = (existing.get("scopes") if existing else None) or extractor.default_scopes(cwd)
    # strip stale hashes before recompute; keep declarations (name/globs/mode/coarse_reason)
    decl = [{k: v for k, v in sc.items() if k != "hash"} for sc in scopes]
    line_comment = extractor.comment_syntax()[0]
    fp, per_scope = compute_fingerprint(cwd, decl, line_comment)
    if fp is None:
        return {"ok": False, "reason": "not a git repo or git unavailable"}
    for sc in decl:
        sc["hash"] = per_scope.get(sc["name"], "")
    # BIND-4: any scope with no semantic extract (coarse extractor) must be coarse
    if line_comment is None:
        for sc in decl:
            if sc.get("mode") != "coarse":
                sc["mode"] = "coarse"
                sc.setdefault("coarse_reason", "no language extractor (toolchain-free fallback); raw content hashed")
    head = _git_head(cwd)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generality_mode": "pluggable" if ext_key != "pathglob" else "fallback",
        "extractor": ext_key,
        "generated_at_commit": head,
        "fingerprint": fp,
        "scopes": decl,
    }
    manifest_path(cwd).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    structure = extractor.extract_structure(cwd)
    _write_structure_md(mdir / "STRUCTURE.md", manifest, structure, head)
    narrated = _append_narrative(mdir / "NARRATIVE.md", cwd, head, [sc["name"] for sc in decl])
    return {"ok": True, "extractor": ext_key, "fingerprint": fp,
            "scopes": [sc["name"] for sc in decl], "structure_keys": list(structure.keys()),
            "narrative_appended": narrated}


def _write_structure_md(path: Path, manifest: dict, structure: dict, head: str) -> None:
    lines = [
        "# Project STRUCTURE (mirror)",
        "",
        "> MACHINE-GENERATED by `cli.mirror regenerate` — do NOT hand-edit (regenerate overwrites).",
        f"> mirror_fingerprint: `{manifest['fingerprint']}`",
        f"> generated_at_commit: `{head or '(no git head)'}`",
        f"> extractor: `{manifest['extractor']}`  generality_mode: `{manifest['generality_mode']}`",
        "",
        "## Tracked drift scopes",
        "",
        "| scope | mode | globs |",
        "|---|---|---|",
    ]
    for sc in manifest["scopes"]:
        lines.append(f"| {sc['name']} | {sc.get('mode')} | {', '.join(sc.get('globs', []))} |")
    lines += ["", "## Structure", "", "```json", json.dumps(structure, ensure_ascii=False, indent=2), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


_NARRATIVE_HEADER = (
    "# Work NARRATIVE (mirror)\n\n"
    "> Append-only work log — newest first. Project-local prose; NOT hashed into the\n"
    "> drift fingerprint (M8 prose/machine split). Each entry = one regenerate, sourced\n"
    "> from the project's git commit log (the commit messages ARE the work record).\n"
)


def _append_narrative(path: Path, cwd: str, head: str, scopes: list[str]) -> bool:
    """Prepend a work-narrative entry from the project's last git commit. Resolves
    BIND-3 by SUBSTITUTING the writer (this project-local function) for the
    `.planning/`-bound kha-codebase-mapper, which cannot write under atlas/mirror/.
    Deterministic, no agent. Dedups when the newest entry is already this commit."""
    try:
        proc = subprocess.run(["git", "-C", str(cwd), "log", "-1", "--format=%h%n%s%n%b"],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0 or not proc.stdout:
        return False
    lines = proc.stdout.splitlines()
    if not lines:
        return False
    short = lines[0].strip()
    subject = lines[1].strip() if len(lines) > 1 else "(no commit subject)"
    body = "\n".join(lines[2:]).strip()
    entry = f"## {short} — {subject}\n\n"
    if body:
        entry += body + "\n\n"
    entry += f"_scopes refreshed: {', '.join(scopes)}_\n\n---\n\n"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    body_part = old[len(_NARRATIVE_HEADER):].lstrip("\n") if old.startswith(_NARRATIVE_HEADER) else ""
    if body_part.startswith(f"## {short} — "):
        return False  # same commit already the newest entry
    path.write_text(_NARRATIVE_HEADER + "\n" + entry + body_part, encoding="utf-8")
    return True
