#!/usr/bin/env python3
"""Trigger summary — aggregates telemetry/debate-triggers.jsonl per topic.

- Reads ~/.claude/telemetry/debate-triggers.jsonl (append-only, every prompt).
- Groups by strict_design / phases / cwd; reports per-topic counts + last-seen.
- /harness-trigger-summary slash command renders summarize().
- SessionStart 1-line advisory uses lib.telemetry_read.count_unreviewed_triggers
  directly (no longer routes through this module — see fixplan-meta debate Gen4).
- Wave 18 (2026-05-05): adds --acknowledge-all / --acknowledge-up-to / --ack-ts
  to mark strict-design records seen so SessionStart advisory stops growing.

Output format: human-readable markdown to stdout (no telemetry side-effect).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import TELEMETRY_DIR  # noqa: E402
from lib.advisory_ack import REGISTRY  # noqa: E402

_strict_design = REGISTRY["strict_design"]
acknowledge_many = _strict_design.ack_many
load_acknowledged = _strict_design.load


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _strict_records() -> list[dict]:
    path = TELEMETRY_DIR / "debate-triggers.jsonl"
    return [r for r in _read_jsonl(path) if r.get("strict_design") is True]


def summarize_data() -> dict:
    """Structured (schema-stable) trigger telemetry for scripting / chaining — the
    deterministic counterpart of summarize()'s markdown (closes the trigger-summary
    'output format opaque, no JSON schema' gap). Pure read.

    schema: {schema_version, total_prompts, strict_design_matched, pending,
    acknowledged, last_ts, last_strict_ts, top_phases:[{phase,count}],
    top_cwds:[{cwd,count}], recent_strict:[{ts,seen,preview}]}"""
    path = TELEMETRY_DIR / "debate-triggers.jsonl"
    records = _read_jsonl(path)
    ack = load_acknowledged()
    strict = [r for r in records if r.get("strict_design") is True]
    pending = [r for r in strict if r.get("ts") not in ack]
    phase_counter: Counter[str] = Counter()
    for r in records:
        for ph in r.get("phases", []) or []:
            phase_counter[ph] += 1
    cwd_counter: Counter[str] = Counter(r.get("cwd", "") for r in records if r.get("cwd"))
    return {
        "schema_version": "1",
        "total_prompts": len(records),
        "strict_design_matched": len(strict),
        "pending": len(pending),
        "acknowledged": len(strict) - len(pending),
        "last_ts": max((r.get("ts", "") for r in records), default=""),
        "last_strict_ts": max((r.get("ts", "") for r in strict), default=""),
        "top_phases": [{"phase": ph, "count": c} for ph, c in phase_counter.most_common(8)],
        "top_cwds": [{"cwd": cwd, "count": c} for cwd, c in cwd_counter.most_common(5)],
        "recent_strict": [
            {"ts": r.get("ts", ""), "seen": r.get("ts") in ack,
             "preview": (r.get("prompt_preview") or "")[:120].replace("\n", " ")}
            for r in strict[-5:]
        ],
    }


def summarize() -> str:
    """Return a markdown report of trigger telemetry. Used by /harness-trigger-summary."""
    path = TELEMETRY_DIR / "debate-triggers.jsonl"
    records = _read_jsonl(path)
    if not records:
        return "## Trigger Summary\n\n_No debate-trigger telemetry yet._\n"

    ack = load_acknowledged()
    total = len(records)
    strict = [r for r in records if r.get("strict_design") is True]
    pending = [r for r in strict if r.get("ts") not in ack]
    last_ts = max((r.get("ts", "") for r in records), default="")
    last_strict_ts = max((r.get("ts", "") for r in strict), default="—")

    phase_counter: Counter[str] = Counter()
    for r in records:
        for ph in r.get("phases", []) or []:
            phase_counter[ph] += 1

    cwd_counter: Counter[str] = Counter(r.get("cwd", "") for r in records if r.get("cwd"))

    lines: list[str] = [
        "## Trigger Summary",
        "",
        f"- Total prompts logged: **{total}**",
        f"- Strict-design intent matched: **{len(strict)}** "
        f"(pending={len(pending)}, ack={len(strict) - len(pending)}, last: {last_strict_ts})",
        f"- Last entry: `{last_ts}`",
        "",
        "### Top phases",
    ]
    for ph, cnt in phase_counter.most_common(8):
        lines.append(f"  - `{ph}`: {cnt}")

    lines.extend(["", "### Top working directories"])
    for cwd, cnt in cwd_counter.most_common(5):
        lines.append(f"  - `{cwd}`: {cnt}")

    lines.extend([
        "",
        "### Recent strict-design samples (up to 5)",
    ])
    for r in strict[-5:]:
        ts = r.get("ts", "—")
        mark = "[seen]" if ts in ack else "[NEW]"
        prev = (r.get("prompt_preview") or "")[:120].replace("\n", " ")
        lines.append(f"  - {mark} `{ts}` — {prev}")

    if pending:
        lines.extend([
            "",
            "_To clear pending:_ "
            "`python -m engine.trigger_summary --acknowledge-all` "
            "or `--acknowledge-up-to <ts>`.",
        ])

    return "\n".join(lines) + "\n"


def _ack_all() -> int:
    return acknowledge_many(r["ts"] for r in _strict_records() if r.get("ts"))


def _ack_up_to(threshold_ts: str) -> int:
    return acknowledge_many(
        r["ts"] for r in _strict_records()
        if r.get("ts") and r["ts"] <= threshold_ts
    )


def main(argv: list[str] | None = None) -> int:
    _rec = getattr(sys.stdout, "reconfigure", None)
    if _rec:                       # guard: stdout may be a StringIO (redirect) without it
        try:
            _rec(encoding="utf-8")
        except Exception:          # noqa: BLE001
            pass

    parser = argparse.ArgumentParser(prog="trigger_summary")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--acknowledge-all",
        action="store_true",
        help="Mark ALL strict-design records as reviewed",
    )
    group.add_argument(
        "--acknowledge-up-to",
        metavar="TS",
        help="Mark strict-design records with ts <= TS as reviewed (ISO8601)",
    )
    group.add_argument(
        "--ack-ts",
        metavar="TS",
        help="Mark a single strict-design record (exact ts) as reviewed",
    )
    parser.add_argument("--json", action="store_true",
                        help="emit the structured summary (schema-stable) instead of markdown")
    args = parser.parse_args(argv)

    if args.json:
        print(json.dumps(summarize_data(), ensure_ascii=False, indent=2))
        return 0
    if args.acknowledge_all:
        n = _ack_all()
        print(f"acknowledged {n} new strict-design record(s)")
        return 0
    if args.acknowledge_up_to:
        n = _ack_up_to(args.acknowledge_up_to)
        print(f"acknowledged {n} record(s) up to {args.acknowledge_up_to}")
        return 0
    if args.ack_ts:
        added = _strict_design.ack(args.ack_ts)
        print(f"{'acknowledged' if added else 'already-acked'}: {args.ack_ts}")
        return 0

    print(summarize())
    return 0


if __name__ == "__main__":
    sys.exit(main())
