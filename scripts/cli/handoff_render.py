#!/usr/bin/env python3
"""Render Phase Tree from HANDOFF.md yaml block (W19.1.1+ auto-tree visualization).

Thin CLI wrapper. The pure parsing / rendering / drift logic lives in
`lib/handoff_drift.py` so handlers + cli + engine can all reuse it
without crossing layer boundaries (W21+ refactor).

Usage:
  python -m cli.handoff_render                               # default ~/.claude/HANDOFF.md, print
  python -m cli.handoff_render <path/to/HANDOFF.md>          # print
  python -m cli.handoff_render <path> --in-place             # rewrite anchored block
  python -m cli.handoff_render <path> --check                # drift exit 0/1

Exit codes:
  0  success (or no drift on --check)
  1  drift detected (--check)
  2  bad input (yaml block missing, parse error, anchors missing on --in-place)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yaml  # noqa: E402

from lib.handoff_drift import (  # noqa: E402,F401
    ANCHOR_BEGIN,
    ANCHOR_END,
    YAML_FENCE_RE,
    _build_anchored_block,
    _coalesce_step_keys,
    check_drift,
    detect_promotable_sub_phases,
    emit_drift_advisory,
    extract_yaml_block,
    promote_sub_phase,
    render_from_handoff,
    replace_anchored,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render the Phase Tree visualization from HANDOFF.md yaml block."
    )
    parser.add_argument(
        "handoff_path", nargs="?",
        default=str(Path.home() / ".claude" / "HANDOFF.md"),
        help="Path to HANDOFF.md (default: ~/.claude/HANDOFF.md)",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--in-place", action="store_true",
                   help="Rewrite anchored block in HANDOFF.md")
    g.add_argument("--check", action="store_true",
                   help="Drift detection: exit 1 if anchored block differs")
    g.add_argument(
        "--promote", metavar="SUB_PHASE_ID",
        help=("Promote a sub_phase's flat step_* keys to a nested sub_phases "
              "array (yaml flat→nested transform, vision item #4). Writes "
              "transformed HANDOFF in-place. Use --list-promotable to see "
              "which sub_phases qualify."),
    )
    g.add_argument("--list-promotable", action="store_true",
                   help="List sub_phase ids that satisfy phase_tree.should_promote")
    args = parser.parse_args(argv)

    path = Path(args.handoff_path)
    if not path.is_file():
        print(f"[ERROR] HANDOFF.md not found: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    try:
        tree = render_from_handoff(text)
    except (ValueError, yaml.YAMLError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    if args.check:
        if check_drift(text, tree):
            print(
                "[DRIFT] anchored phase tree differs from yaml-rendered tree",
                file=sys.stderr,
            )
            return 1
        print("[OK] anchored phase tree matches yaml-rendered tree")
        return 0

    if args.list_promotable:
        candidates = detect_promotable_sub_phases(text)
        if not candidates:
            print("[OK] no sub_phases meet promotion threshold")
            return 0
        print(f"[INFO] {len(candidates)} sub_phase(s) eligible for promotion:")
        for cid in candidates:
            print(f"  - {cid}")
        print(
            f"\nApply with: python -m cli.handoff_render {path} --promote <id>"
        )
        return 0

    if args.promote:
        try:
            promoted_text = promote_sub_phase(text, args.promote)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 2
        if promoted_text == text:
            print(f"[OK] no changes needed for {args.promote}")
            return 0
        path.write_text(promoted_text, encoding="utf-8")
        print(
            f"[OK] promoted sub_phase {args.promote!r} (flat step_* → nested sub_phases) "
            f"in {path}. Run --in-place next to refresh anchored block."
        )
        return 0

    if args.in_place:
        try:
            new_text = replace_anchored(text, tree)
        except ValueError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 2
        if new_text == text:
            print("[OK] no changes needed")
            return 0
        path.write_text(new_text, encoding="utf-8")
        print(f"[OK] rewrote anchored phase-tree block in {path}")
        return 0

    print(tree)
    return 0


if __name__ == "__main__":
    sys.exit(main())
