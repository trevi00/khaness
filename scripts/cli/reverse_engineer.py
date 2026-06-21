#!/usr/bin/env python3
"""Reverse-engineer harness pipeline documents from existing project code.

Walks lib.extractors.REGISTRY and runs each extractor against the project
root. Emits a per-extractor report; with --write applies the results to
`<root>/.claude/...` after confidence + round-trip validation.

Usage:
    cd ~/.claude/scripts
    python -m cli.reverse_engineer --root /home/user/some-project           # dry-run
    python -m cli.reverse_engineer --root . --stage convention                  # one stage
    python -m cli.reverse_engineer --root . --write                             # apply all
    python -m cli.reverse_engineer --root . --write --min-confidence 0.7        # stricter
    python -m cli.reverse_engineer --root . --json                              # machine-readable

Round-trip validation (default ON when --write):
After writing each file, run the matching validator. If the validator emits
[FAIL], rollback the write and surface the failure.

Exit code: 0 on success, 1 if any extractor or round-trip validation failed.
"""
from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.extractors import REGISTRY  # noqa: E402


def _instantiate(extractor_cls):
    return extractor_cls()


def _select_extractors(stage: str | None):
    """Select extractor instances for a run.

    Default (no --stage): CODE extractors only — instances whose
    ``code_extractor`` attribute is not False (existing convention/er/logical
    lack the attr and default to True via getattr). This keeps non-code
    extractors (e.g. doc_classifier, which writes .planning/SPEC-seed.md) OUT
    of the default code-reverse walk so a reverse run is never contaminated.
    With --stage, any registered extractor (including non-code) runs by name.
    """
    extractors = [_instantiate(c) for c in REGISTRY]
    if stage:
        return [e for e in extractors if e.name == stage]
    return [e for e in extractors if getattr(e, "code_extractor", True)]


def _validator_for(stage_name: str) -> str | None:
    """Map stage → validator module that should accept the extracted output."""
    return {
        "convention": "convention",
        "er": "er",
        "logical": "logical",
        "openapi": "openapi",
        "prd": "prd",
        "flow": "flow",
        "ddl": "ddl",
    }.get(stage_name)


def _run_validator(name: str, cwd: Path) -> tuple[bool, str]:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        try:
            mod = importlib.import_module(f"validators.{name}")
            with redirect_stdout(buf):
                mod.main()
        except SystemExit as e:
            if e.code and e.code != 0:
                return False, buf.getvalue()
        except Exception as e:
            return False, f"{type(e).__name__}: {e}\n{buf.getvalue()}"
    finally:
        os.chdir(saved)
    out = buf.getvalue()
    return ("[FAIL]" not in out), out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reverse-engineer harness pipeline docs from project code")
    ap.add_argument("--root", default=os.getcwd(), help="project root (default: cwd)")
    ap.add_argument("--stage", help="run a single extractor by name (default: all)")
    ap.add_argument("--write", action="store_true",
                    help="write extracted content to .claude/ paths (default: dry-run)")
    ap.add_argument("--min-confidence", type=float, default=0.5,
                    help="skip extractor results below this confidence (default 0.5)")
    ap.add_argument("--no-roundtrip", action="store_true",
                    help="skip post-write validator round-trip check")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[reverse_engineer] root not a directory: {root}", file=sys.stderr)
        return 2

    extractors = _select_extractors(args.stage)
    if args.stage and not extractors:
        print(f"[reverse_engineer] unknown stage: {args.stage}", file=sys.stderr)
        return 2

    results = []
    any_failed = False

    for ex in extractors:
        if not ex.can_extract(root):
            results.append({
                "extractor": ex.name,
                "target": ex.target,
                "status": "skip",
                "reason": "can_extract=False (no source material)",
            })
            continue

        result = ex.extract(root)
        record = {
            "extractor": result.extractor,
            "target": result.target,
            "confidence": result.confidence,
            "notes": result.notes,
            "sources_count": len(result.sources),
            "content_preview": result.content[:300],
            "content_length": len(result.content),
        }

        if result.confidence < args.min_confidence:
            record["status"] = "skip"
            record["reason"] = f"confidence {result.confidence} < min {args.min_confidence}"
            results.append(record)
            continue

        if not args.write:
            record["status"] = "dry-run"
            results.append(record)
            continue

        # Write phase
        target_path = root / result.target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        existed = target_path.is_file()
        previous = target_path.read_text(encoding="utf-8") if existed else None

        target_path.write_text(result.content, encoding="utf-8")
        record["status"] = "written"
        record["created"] = not existed

        if not args.no_roundtrip:
            v_name = _validator_for(ex.name)
            if v_name:
                ok, out = _run_validator(v_name, root)
                record["roundtrip_validator"] = v_name
                record["roundtrip_pass"] = ok
                record["roundtrip_tail"] = out[-200:] if not ok else ""
                if not ok:
                    # Rollback — leave previous state
                    if previous is not None:
                        target_path.write_text(previous, encoding="utf-8")
                    else:
                        target_path.unlink()
                    record["status"] = "rolled-back"
                    any_failed = True
        results.append(record)

    if args.json:
        print(json.dumps({"root": str(root), "results": results},
                         ensure_ascii=False, indent=2))
    else:
        _print_table(root, results)

    return 1 if any_failed else 0


def _print_table(root: Path, results: list[dict]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    print(f"# Reverse-engineering report -- `{root}`")
    print()
    print(f"{'Extractor':14} {'Target':42} {'Status':12} {'Conf':6} Notes")
    print("-" * 100)
    for r in results:
        name = r.get("extractor", "?")
        target = r.get("target", "?")[:40]
        status = r.get("status", "?")
        conf = f"{r.get('confidence', 0):.2f}" if r.get("confidence") is not None else "-"
        note = ""
        if r.get("status") == "skip":
            note = r.get("reason", "")
        elif r.get("status") == "rolled-back":
            note = f"roundtrip FAIL: {r.get('roundtrip_tail', '')[:60]}"
        elif r.get("status") == "written":
            note = "(roundtrip PASS)" if r.get("roundtrip_pass", True) else ""
        else:
            note = ", ".join(r.get("notes", [])[:1])
        print(f"{name:14} {target:42} {status:12} {conf:6} {note}")


if __name__ == "__main__":
    sys.exit(main())
