#!/usr/bin/env python3
"""Unit tests for the per-project mirror context brain (debate-1781435805-qb14p7,
ontology c4ad11f4d9a2). Agent-free, deterministic (M6). Pins:

  M2 scope-glob content-hash catches a service-LAYER body edit (the user's trigger).
  M3/BIND-1 non-lying: comment-only + reformat edits do NOT flip STALE; a string
    literal containing '//' that CHANGES flips STALE (proves full-line-only normalize
    never false-cleans an in-string comment token).
  M4 marker-gating: no manifest.json => inert, zero git.
  M6 success-test: set-equality of manifest-claimed hashes vs freshly recomputed.
  BIND-5: SKIP (not fail) when git is unavailable.

Run: python tests/test_mirror_drift.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_PASS = 0
_FAIL = 0


def _ok(m: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [OK]   {m}")


def _fail(m: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {m}")


def _check(c: bool, m: str) -> None:
    _ok(m) if c else _fail(m)


def _git(cwd: Path, *args: str) -> int:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=30).returncode


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _fixture() -> Path:
    d = Path(tempfile.mkdtemp(prefix="mirror-test-"))
    _write(d / "Cargo.toml", "[package]\nname = \"demo\"\nversion = \"0.1.0\"\n")
    _write(d / "src" / "lib.rs", "pub mod services;\n")
    _write(d / "src" / "services" / "foo.rs",
           "// service entry\n"
           "pub fn price(qty: u32) -> u32 {\n"
           "    let base = 10;          // base price\n"
           "    let url = \"http://x//y\";\n"
           "    qty * base\n"
           "}\n")
    _git(d, "init")
    _git(d, "add", ".")
    return d


def main() -> int:
    if shutil.which("git") is None:
        print("  [SKIP] git not available — mirror_drift set-equality test skipped (BIND-5)")
        print("\n0 passed, 0 failed (skipped)")
        return 0

    from lib import mirror_drift
    from lib.mirror_extractors import compute_fingerprint, get_extractor

    # ── regenerate + set-equality (M6) ──
    print("test_regenerate_and_set_equality (M6)")
    d = _fixture()
    res = mirror_drift.regenerate(str(d))
    _check(res.get("ok") is True, "regenerate ok on a git repo")
    manifest = mirror_drift.read_manifest(str(d))
    _check(manifest is not None and manifest.get("extractor") == "rust", "rust extractor detected (Cargo.toml)")
    # set-equality: claimed manifest hashes vs freshly recomputed
    line_comment = get_extractor(manifest["extractor"]).comment_syntax()[0]
    fresh_fp, fresh = compute_fingerprint(str(d), manifest["scopes"], line_comment)
    claimed = {sc["name"]: sc["hash"] for sc in manifest["scopes"]}
    _check(claimed == fresh, "manifest-claimed hashes == freshly recomputed (set-equality)")
    _check(fresh_fp == manifest["fingerprint"], "fingerprint matches")
    r = mirror_drift.scan(str(d))
    _check(r["marker"] and r["fingerprint_match"] and not r["stale_scopes"], "clean tree -> scan not stale")

    # ── M3/BIND-1: comment-only edit does NOT flip STALE ──
    print("test_comment_only_no_stale (M3/BIND-1 non-lying)")
    foo = d / "src" / "services" / "foo.rs"
    txt = foo.read_text(encoding="utf-8")
    _write(foo, txt.replace("// service entry\n", "// service entry — totally rewritten comment\n"))
    r = mirror_drift.scan(str(d))
    _check(r["fingerprint_match"] and not r["stale_scopes"], "full-line comment edit -> NOT stale")

    # reformat (indent/whitespace) does NOT flip STALE
    print("test_reformat_no_stale (M3)")
    txt = foo.read_text(encoding="utf-8")
    _write(foo, txt.replace("    let base = 10;", "        let base = 10;"))  # reindent
    r = mirror_drift.scan(str(d))
    _check(r["fingerprint_match"] and not r["stale_scopes"], "reindent -> NOT stale")

    # ── M2: a real service-body edit DOES flip the services scope STALE ──
    print("test_service_body_edit_stale (M2 — the user's trigger)")
    txt = foo.read_text(encoding="utf-8")
    _write(foo, txt.replace("qty * base", "qty * base + 1"))  # logic change
    r = mirror_drift.scan(str(d))
    _check(not r["fingerprint_match"], "service-body logic edit -> fingerprint mismatch")
    _check("services" in r["stale_scopes"], "the 'services' scope is marked STALE")

    # ── FALSE-CLEAN defense: in-string '//' change MUST flip STALE ──
    print("test_false_clean_defense (BIND-1 — never strip in-string //)")
    mirror_drift.regenerate(str(d))  # re-baseline
    r0 = mirror_drift.scan(str(d))
    _check(r0["fingerprint_match"], "re-baseline clean")
    txt = foo.read_text(encoding="utf-8")
    _write(foo, txt.replace('"http://x//y"', '"http://x//z"'))  # change inside a string literal
    r = mirror_drift.scan(str(d))
    _check(not r["fingerprint_match"], "in-string '//y'->'//z' change -> STALE (NOT false-clean)")

    # ── M4 marker-gating: no manifest => inert ──
    print("test_inert_without_marker (M4)")
    empty = Path(tempfile.mkdtemp(prefix="mirror-empty-"))
    r = mirror_drift.scan(str(empty))
    _check(r["marker"] is False and r["fingerprint_match"] and r["scopes_checked"] == 0, "no manifest -> inert")
    _check(mirror_drift.status_line(str(empty)) is None, "inert project -> no status line")

    # ── M8/BIND-3: NARRATIVE.md from git commit log (work record) ──
    print("test_narrative_from_commit (M8/BIND-3 — how work was done)")
    nd = Path(tempfile.mkdtemp(prefix="mirror-narr-"))
    _write(nd / "Cargo.toml", "[package]\nname = \"n\"\nversion = \"0.1.0\"\n")
    _write(nd / "src" / "services" / "a.rs", "pub fn f() -> u32 { 1 }\n")
    _git(nd, "init")
    _git(nd, "config", "user.email", "t@t")
    _git(nd, "config", "user.name", "t")
    _git(nd, "add", ".")
    # non-ASCII commit subject (em-dash + Korean) guards the cp949 subprocess-decode
    # bug: subprocess.run(text=True) decodes git output with the locale codec, which
    # crashes on UTF-8 on a Korean (cp949) console — the mirror's git calls pin
    # encoding='utf-8' so this must round-trip on any locale.
    _git(nd, "commit", "-m", "feat(svc): add total() — 서비스 계층\n\nimplements service-layer total")
    res = mirror_drift.regenerate(str(nd))
    narr = nd / "atlas" / "mirror" / "NARRATIVE.md"
    ntxt = narr.read_text(encoding="utf-8") if narr.is_file() else ""
    _check(res.get("narrative_appended") is True, "narrative appended on regenerate (commit present)")
    _check("feat(svc): add total() — 서비스 계층" in ntxt, "NARRATIVE carries non-ASCII commit subject (cp949 decode guard)")
    _check("NOT hashed into the" in ntxt and "drift fingerprint" in ntxt, "NARRATIVE header declares it is not part of the fingerprint (M8)")
    # NARRATIVE.md must NOT be inside any drift scope (prose != machine extract)
    r = mirror_drift.scan(str(nd))
    _check(r["fingerprint_match"], "after regenerate (with NARRATIVE) -> scan clean (NARRATIVE not hashed)")

    # ── 확장성: OCP-clean pluggable detection ──
    print("test_detect_extractor_ocp (확장성)")
    from lib.mirror_extractors import detect_extractor
    rd = Path(tempfile.mkdtemp(prefix="mirror-det-"))
    _write(rd / "rust" / "Cargo.toml", "[workspace]\n")  # workspace in a SUBDIR
    _check(detect_extractor(str(rd)) == "rust", "Cargo.toml in a subdir -> rust (subdir workspace)")
    pg = Path(tempfile.mkdtemp(prefix="mirror-pg-"))
    _write(pg / "app.py", "print(1)\n")
    _check(detect_extractor(str(pg)) == "pathglob", "non-cargo project -> pathglob fallback")

    # ── 안정성/성능: HEAD + clean-tree fast-path (no file reads) ──
    print("test_fast_path (안정성/성능)")
    fp = _fixture()
    _git(fp, "config", "user.email", "t@t"); _git(fp, "config", "user.name", "t")
    _git(fp, "commit", "-m", "init")
    mirror_drift.regenerate(str(fp))
    r = mirror_drift.scan(str(fp))
    _check(r.get("fast_path") is True and r["fingerprint_match"], "clean tree @ same commit -> fast_path (no file reads)")
    # untracked file is IGNORED (not in any scope) -> still fast_path
    _write(fp / "untracked_note.txt", "scratch\n")
    r = mirror_drift.scan(str(fp))
    _check(r.get("fast_path") is True, "untracked file -> still fast_path (only tracked files hashed)")
    # a tracked dirty change disables the fast-path and IS detected
    fpfoo = fp / "src" / "services" / "foo.rs"
    _write(fpfoo, fpfoo.read_text(encoding="utf-8").replace("qty * base", "qty * base + 7"))
    r = mirror_drift.scan(str(fp))
    _check(not r.get("fast_path") and not r["fingerprint_match"], "tracked dirty edit -> full recompute -> STALE")

    # ── 사용성: walk-up discovery from a subdir ──
    print("test_walk_up_discovery (사용성)")
    mirror_drift.regenerate(str(fp))  # re-baseline (commit-less dirty now clean vs manifest)
    sub = fp / "src" / "services"
    r = mirror_drift.scan(str(sub))  # scan from a SUBDIR
    _check(r.get("root") == str(fp.resolve()), "scan from subdir walks up to the project mirror root")
    _check(r.get("marker") is True, "mirror is discoverable from a subdir (not just project root)")

    # ── 결합도/안정성: manifest validation surfaces a broken manifest ──
    print("test_manifest_validation (결합도/안정성)")
    bad = Path(tempfile.mkdtemp(prefix="mirror-bad-"))
    badman = bad / "atlas" / "mirror" / "manifest.json"
    badman.parent.mkdir(parents=True)
    # coarse scope with no coarse_reason (BIND-4 violation) + missing fingerprint
    badman.write_text(json.dumps({"schema_version": 1, "scopes": [
        {"name": "x", "globs": ["**/*.rs"], "mode": "coarse"}]}), encoding="utf-8")
    r = mirror_drift.scan(str(bad))
    _check(bool(r.get("invalid")), "broken manifest (coarse w/o reason, no fingerprint) -> invalid surfaced (not silent)")
    line = mirror_drift.status_line(str(bad))
    _check(line is not None and "invalid" in line, "invalid manifest -> SessionStart surfaces it")

    # cleanup best-effort
    for p in (d, empty, nd, rd, pg, fp, bad):
        shutil.rmtree(p, ignore_errors=True)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
