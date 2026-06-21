#!/usr/bin/env python3
"""output_schema bootstrap audit (v15.10 A7, implementation note 2).

Per debate-1778946602-jj7vxk implementation note 2:

    Run output_schema bootstrap audit (every agent_type must have declared
    output_schema) BEFORE D2 validator activation. Otherwise the validator
    would treat every legacy agent as 'no schema' and silently skip its
    layer-1 check, defeating the point.

This CLI walks every `~/.claude/agents/*.md` file and reports one of three
classifications per agent:

    PRESENT_FRONTMATTER   — agent has `output_schema:` YAML key in frontmatter
                            (machine-readable, JSON-Schema subset expected)
    PRESENT_XML           — agent has `<output_schema>...</output_schema>` block
                            in body (human prose, NOT machine-readable;
                            counted as "documented but not enforceable" — D2
                            will skip layer-1 for these until promoted)
    MISSING               — neither form present

Exit code is 0 iff every agent has at least one form of declaration
(PRESENT_FRONTMATTER or PRESENT_XML). Exit 1 means the bootstrap audit
caller (handler / CI gate) should block D2 activation until coverage is
complete.

Usage:
    cd ~/.claude/scripts
    python -m cli.output_schema_audit              # plaintext summary
    python -m cli.output_schema_audit --json       # machine-readable
    python -m cli.output_schema_audit --strict     # treat XML as MISSING
                                                   #   (block until fully
                                                   #    machine-readable)

The default classification is "either form counts" — pragmatic for the
initial bootstrap. `--strict` is the eventual target state once every
agent has been migrated to YAML frontmatter form.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import AGENTS_DIR  # noqa: E402


Classification = Literal[
    "PRESENT_FRONTMATTER",
    "PRESENT_XML",
    "MISSING",
]


_XML_RE = re.compile(r"<\s*output_schema\b", re.IGNORECASE)


def classify_agent(path: Path) -> Classification:
    """One agent file → one classification."""
    parsed = parse_frontmatter(path)
    if parsed is not None:
        meta, body = parsed
        if "output_schema" in meta and str(meta.get("output_schema", "")).strip():
            return "PRESENT_FRONTMATTER"
    else:
        # No frontmatter at all → read raw body.
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            return "MISSING"

    if _XML_RE.search(body):
        return "PRESENT_XML"
    return "MISSING"


def audit(agents_dir: Path | None = None, *, strict: bool = False) -> dict:
    """Return {agent_name: classification, ..., '__summary__': {...}}."""
    base = agents_dir or AGENTS_DIR
    results: dict[str, Classification] = {}
    if base.exists():
        for p in sorted(base.glob("*.md")):
            results[p.stem] = classify_agent(p)
    counts: dict[str, int] = {
        "PRESENT_FRONTMATTER": 0,
        "PRESENT_XML": 0,
        "MISSING": 0,
    }
    for v in results.values():
        counts[v] += 1
    missing_keys = [k for k, v in results.items() if v == "MISSING"]
    if strict:
        # XML doesn't count toward coverage in strict mode.
        missing_keys.extend(k for k, v in results.items() if v == "PRESENT_XML")
        missing_keys.sort()
    summary = {
        "total": len(results),
        "counts": counts,
        "missing": sorted(set(missing_keys)),
        "all_covered": len(missing_keys) == 0,
        "strict": strict,
    }
    return {"agents": results, "__summary__": summary}


def _format_plain(report: dict) -> str:
    summary = report["__summary__"]
    lines = [
        f"output_schema bootstrap audit (strict={summary['strict']})",
        f"  total agents : {summary['total']}",
        f"  PRESENT_FRONTMATTER : {summary['counts']['PRESENT_FRONTMATTER']}",
        f"  PRESENT_XML         : {summary['counts']['PRESENT_XML']}",
        f"  MISSING             : {summary['counts']['MISSING']}",
        "",
    ]
    if summary["missing"]:
        lines.append("Agents needing output_schema:")
        for name in summary["missing"]:
            lines.append(f"  - {name}")
        lines.append("")
    if summary["all_covered"]:
        lines.append("[OK] coverage complete — D2 validator activation unblocked")
    else:
        lines.append("[BLOCK] coverage incomplete — D2 validator activation blocked")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="output-schema-audit",
        description="v15.10 A7 bootstrap audit for agent output_schema coverage",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat XML-only declarations as MISSING (eventual target)",
    )
    parser.add_argument(
        "--agents-dir",
        default=None,
        help="override agents directory (default: ~/.claude/agents)",
    )
    args = parser.parse_args(argv)

    agents_dir = Path(args.agents_dir) if args.agents_dir else None
    report = audit(agents_dir, strict=args.strict)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(_format_plain(report))
    return 0 if report["__summary__"]["all_covered"] else 1


if __name__ == "__main__":
    sys.exit(main())
