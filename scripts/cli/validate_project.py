#!/usr/bin/env python3
"""Monorepo-aware validator dispatcher (F2).

Each validator in `validators/` reads `os.getcwd()` and assumes a single-cwd
project layout. For monorepos like:

    project/
    ├── .claude/                ← design docs (convention, prd, flow, ...)
    ├── backend/                ← Java/Spring (skeleton, codegen, test, ddl)
    │   ├── src/main/java/
    │   └── build.gradle
    ├── frontend/               ← TypeScript/React (lint, build)
    │   └── package.json
    └── .github/workflows/      ← CI (ci, collab)

a single `cd ~/project && python -m validators.<x>` skips most checks because
the targets live in subroots. This dispatcher walks the tree, classifies each
subroot by the artifacts present, and runs the matching validator set with the
correct cwd.

Usage (run from project root):
    cd ~/ecommerce-v2 && python -m cli.validate_project
    python -m cli.validate_project --root /home/user/ecommerce-v2
    python -m cli.validate_project --json    # machine-readable summary

Exit code: 0 if every validator exits cleanly (no [FAIL] tokens in output);
1 if any validator emits [FAIL]. Skips ([PASS] 검증 대상 파일 없음) are
treated as success.

Classification:
    root       : has .claude/ at this directory
    java-be    : has src/main/java/  (Spring/Maven/Gradle backend)
    ts-fe      : has package.json    (Node/Vite/Next/etc. frontend)
    flutter    : has pubspec.yaml
    generic    : everything else (skipped — no validators apply)
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# Validator → subroot-type set. A validator runs in every subroot whose type
# is in its set. (Some validators can apply to multiple roots.)
ROUTING = {
    "convention":  {"root"},
    "prd":         {"root"},
    "flow":        {"root"},
    "er":          {"root"},
    "logical":     {"root"},
    "openapi":     {"root"},
    "ci":          {"root"},
    "collab":      {"root"},
    "contract":    {"root", "java-be"},   # cross-cutting; run from both
    "skeleton":    {"java-be"},
    "codegen":     {"java-be"},
    "test":        {"java-be"},
    "ddl":         {"java-be", "root"},
}

# Order matters — subroots scanned in this order; .claude/ at root means
# root takes precedence for design-doc validators.
SUBROOT_ORDER = ("root", "java-be", "ts-fe", "flutter")

FAIL_RE = re.compile(r"\[FAIL\]")
SKIP_RE = re.compile(r"\[PASS\] 검증 대상 파일 없음 \(skip\)")


@dataclass
class SubrootInfo:
    path: Path
    kind: str               # "root" | "java-be" | "ts-fe" | "flutter" | "generic"
    rationale: str          # human-readable why we tagged it this kind


@dataclass
class ValidatorResult:
    validator: str
    subroot: str            # relative path from --root
    kind: str
    status: str             # "PASS" | "SKIP" | "FAIL"
    output_tail: str        # last ~200 chars of stdout


@dataclass
class RunSummary:
    root: Path
    subroots: list[SubrootInfo] = field(default_factory=list)
    results: list[ValidatorResult] = field(default_factory=list)


def _classify_dir(path: Path, is_root: bool) -> SubrootInfo | None:
    """Tag a directory as a known subroot type, or None if not interesting."""
    if is_root and (path / ".claude").is_dir():
        return SubrootInfo(path=path, kind="root", rationale="has .claude/ design docs")
    if (path / "src" / "main" / "java").is_dir():
        return SubrootInfo(path=path, kind="java-be",
                           rationale="has src/main/java (Java backend)")
    if (path / "package.json").is_file():
        return SubrootInfo(path=path, kind="ts-fe",
                           rationale="has package.json (Node/TS frontend)")
    if (path / "pubspec.yaml").is_file():
        return SubrootInfo(path=path, kind="flutter",
                           rationale="has pubspec.yaml (Flutter/Dart)")
    return None


def _discover_subroots(root: Path) -> list[SubrootInfo]:
    """Walk one level deep from root and tag known subroot types.

    Root itself is always classified first (most often as 'root' if .claude/
    exists, otherwise as a content type). Direct children get a single-pass
    classification; we do NOT recurse deeper to keep blast radius bounded.
    """
    out: list[SubrootInfo] = []
    root_info = _classify_dir(root, is_root=True)
    if root_info:
        out.append(root_info)

    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name == "node_modules":
            continue
        info = _classify_dir(child, is_root=False)
        if info:
            out.append(info)

    return out


def _run_validator(name: str, cwd: Path) -> tuple[str, str]:
    """Import validators.<name>, call main() with cwd switched. Returns (status, tail)."""
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        try:
            mod = importlib.import_module(f"validators.{name}")
        except ModuleNotFoundError:
            return "FAIL", f"validator module missing: validators.{name}"
        main = getattr(mod, "main", None)
        if not callable(main):
            return "FAIL", f"validators.{name} has no main()"
        try:
            with redirect_stdout(buf):
                main()
        except SystemExit as e:
            output = buf.getvalue()
            tail = output[-200:].strip()
            if e.code and e.code != 0:
                return "FAIL", tail or f"sys.exit({e.code})"
            # exit(0) is also "clean"
        except Exception as e:
            return "FAIL", f"{type(e).__name__}: {e}"
    finally:
        os.chdir(saved)

    output = buf.getvalue()
    if FAIL_RE.search(output):
        return "FAIL", output[-200:].strip()
    if SKIP_RE.search(output):
        return "SKIP", output[-200:].strip()
    return "PASS", output[-200:].strip()


def run(root: Path) -> RunSummary:
    summary = RunSummary(root=root)
    summary.subroots = _discover_subroots(root)

    if not summary.subroots:
        return summary

    for sub in summary.subroots:
        for validator, applicable_kinds in ROUTING.items():
            if sub.kind not in applicable_kinds:
                continue
            status, tail = _run_validator(validator, sub.path)
            rel = "." if sub.path == root else sub.path.relative_to(root).as_posix()
            summary.results.append(ValidatorResult(
                validator=validator,
                subroot=rel,
                kind=sub.kind,
                status=status,
                output_tail=tail,
            ))
    return summary


def _format_table(summary: RunSummary) -> str:
    if not summary.results:
        return f"(no subroots detected under {summary.root})"

    lines = [
        f"Root: {summary.root}",
        "",
        "Subroots:",
    ]
    for s in summary.subroots:
        rel = "." if s.path == summary.root else s.path.relative_to(summary.root).as_posix()
        lines.append(f"  [{s.kind:8}] {rel:24}  ← {s.rationale}")

    lines.append("")
    lines.append(f"{'Validator':18} {'Subroot':18} {'Kind':10} {'Status':6}")
    lines.append("-" * 60)

    counts = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    for r in summary.results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"{r.validator:18} {r.subroot:18} {r.kind:10} {r.status:6}")
    lines.append("-" * 60)
    lines.append(f"PASS={counts['PASS']}  SKIP={counts['SKIP']}  FAIL={counts['FAIL']}")

    fails = [r for r in summary.results if r.status == "FAIL"]
    if fails:
        lines.append("")
        lines.append("Failures:")
        for r in fails:
            lines.append(f"  {r.validator}@{r.subroot} → {r.output_tail[:160]}")
    return "\n".join(lines)


def _format_json(summary: RunSummary) -> str:
    return json.dumps({
        "root": str(summary.root),
        "subroots": [
            {"path": str(s.path), "kind": s.kind, "rationale": s.rationale}
            for s in summary.subroots
        ],
        "results": [
            {
                "validator": r.validator,
                "subroot": r.subroot,
                "kind": r.kind,
                "status": r.status,
                "output_tail": r.output_tail,
            } for r in summary.results
        ],
        "counts": {
            s: sum(1 for r in summary.results if r.status == s)
            for s in ("PASS", "SKIP", "FAIL")
        },
    }, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Monorepo-aware validator dispatcher")
    ap.add_argument("--root", default=os.getcwd(), help="project root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of table")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[validate_project] root not a directory: {root}", file=sys.stderr)
        return 2

    summary = run(root)

    if args.json:
        print(_format_json(summary))
    else:
        print(_format_table(summary))

    fails = sum(1 for r in summary.results if r.status == "FAIL")
    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
