"""extractor_baseline — operator helper for SKILL_CANDIDATE_EXTRACTOR_ENABLED activation.

Implements ADV-2 (debate-1779468030-0e0a82 gen-3 approved): records the T0
baseline count, computes 24h delta against ~/.claude/skill-candidates/, and
provides a synthetic warm-up probe for AFK delta=0 disambiguation.

Operator-discipline tool. NOT a harness component, NOT spawned by hooks.
Invoked manually per the runbook at ~/.claude/docs/runbooks/skill-extractor-activation.md.

Subcommands:
  record   — capture T0 count + verify SKILL_CANDIDATE_EXTRACTOR_ENABLED env
  delta    — compute current count - T0 count; report against evidence-of-activity
  warmup   — synthetic PostToolUse stdin probe (>= _THRESHOLD); re-read delta
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CANDIDATES_ROOT = Path.home() / ".claude" / "skill-candidates"
BASELINE_PATH = Path.home() / ".claude" / "state" / "skill-extractor-baseline.txt"
ENV_GATE = "SKILL_CANDIDATE_EXTRACTOR_ENABLED"


def _count_non_blocked() -> int:
    if not CANDIDATES_ROOT.exists():
        return 0
    return sum(
        1 for p in CANDIDATES_ROOT.iterdir()
        if p.is_file() and p.suffix == ".json" and not p.name.endswith(".blocked.json")
    )


def _detect_shell() -> str:
    if os.environ.get("MSYSTEM") or "bash" in os.environ.get("SHELL", "").lower():
        return "git-bash"
    if os.environ.get("PSModulePath"):
        return "powershell"
    return os.environ.get("SHELL") or "unknown"


def cmd_record() -> int:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    verified = os.environ.get(ENV_GATE) == "1"
    snapshot = {
        "t0_iso": datetime.now(timezone.utc).isoformat(),
        "t0_unix": int(time.time()),
        "t0_count": _count_non_blocked(),
        "shell": _detect_shell(),
        "env_gate_verified": verified,
        "candidates_root": str(CANDIDATES_ROOT),
    }
    BASELINE_PATH.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"baseline recorded: {BASELINE_PATH}")
    print(json.dumps(snapshot, indent=2))
    if not verified:
        print(
            f"\nWARNING: {ENV_GATE} is not '1' in this shell. "
            "Run the verification one-liner from step 4 of the runbook BEFORE launching claude.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_delta() -> int:
    if not BASELINE_PATH.exists():
        print(f"baseline missing: {BASELINE_PATH}", file=sys.stderr)
        print("re-run runbook steps 2-5 with `record` subcommand first.", file=sys.stderr)
        return 2
    snapshot = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    t0_count = int(snapshot.get("t0_count", 0))
    now_count = _count_non_blocked()
    delta = now_count - t0_count
    elapsed_s = int(time.time()) - int(snapshot.get("t0_unix", 0))
    report = {
        "t0_iso": snapshot.get("t0_iso"),
        "t0_count": t0_count,
        "now_count": now_count,
        "delta": delta,
        "elapsed_hours": round(elapsed_s / 3600, 2),
        "verdict": _delta_verdict(delta, elapsed_s),
    }
    print(json.dumps(report, indent=2))
    return 0 if delta > 0 else 3


def _delta_verdict(delta: int, elapsed_s: int) -> str:
    if delta > 0:
        return "extractor confirmed live"
    if elapsed_s < 3600:
        return "window too short (<1h); wait and re-check"
    if elapsed_s < 24 * 3600:
        return "delta=0 within sub-24h window; normal if low tool-use volume"
    return "delta=0 across full 24h window; run `warmup` to disambiguate broken vs AFK"


def cmd_warmup() -> int:
    """Synthetic PostToolUse stdin probe.

    Calls the detector's `process_payload` directly with a synthetic payload
    that pushes a same-tool counter to >= _THRESHOLD (3). Bypasses the
    PostToolUse hook chain entirely — this is operator-side diagnostic only.
    If extractor + detector are wired correctly, this MUST produce at least
    one new <cid>.json under ~/.claude/skill-candidates/ regardless of the
    PostToolUse env gate (the env gate guards the hook, not the detector
    module).
    """
    detector_dir = Path.home() / ".claude" / "scripts" / "lib"
    if str(detector_dir) not in sys.path:
        sys.path.insert(0, str(detector_dir))
    try:
        from skill_candidate_detector import process_payload  # type: ignore
    except ImportError as exc:
        print(f"detector import failed: {exc}", file=sys.stderr)
        return 4

    before = _count_non_blocked()
    fake_sid = f"warmup-{uuid.uuid4().hex[:8]}"
    fake_tool = "Edit"
    for _ in range(5):
        payload = json.dumps({"session_id": fake_sid, "tool_name": fake_tool})
        process_payload(payload)
    after = _count_non_blocked()
    new_files = after - before
    report = {
        "warmup_sid": fake_sid,
        "tool_name": fake_tool,
        "invocations": 5,
        "before_count": before,
        "after_count": after,
        "new_non_blocked": new_files,
        "verdict": "detector reachable + writes" if new_files > 0
                   else "detector unreachable or secret-scan blocked",
    }
    print(json.dumps(report, indent=2))
    return 0 if new_files > 0 else 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor_baseline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("record", help="capture T0 baseline + env verification")
    sub.add_parser("delta", help="compute 24h delta against baseline")
    sub.add_parser("warmup", help="synthetic detector probe (AFK disambiguation)")
    args = parser.parse_args(argv)
    if args.cmd == "record":
        return cmd_record()
    if args.cmd == "delta":
        return cmd_delta()
    if args.cmd == "warmup":
        return cmd_warmup()
    parser.print_help(sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
