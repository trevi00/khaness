#!/usr/bin/env python3
"""graduate_validator — operator CLI for validator advisory→blocking graduation.

Track 1 (harness-debate debate-1780722434-e5h19n gen-2). This is the ONLY entry
point that flips a validator's blocking semantics. Per CLAUDE.md §Mutation:
  - graduate (advisory→blocking, RISKY direction): requires
    HARNESS_MUTATION_TOKEN=graduate-validator AND the ready-flag (streak>=N).
  - demote   (blocking→advisory, SAFE direction): requires only
    HARNESS_MUTATION_TOKEN=apply-user-preference (no ready-flag — fast incident
    response), resets the streak to 0 (anti-flap).
  - status / tick: no token (read-only / streak accounting only).

NO cron may invoke graduate/demote — the operator runs this and commits the
resulting source diff (GRADUATED_NAMES concat is auditable). `tick` runs the
same SessionStart-amortized scan-and-tick on demand (12h dedup is enforced
identically, so the CLI cannot inflate the streak faster than real run-events).

Usage:
    python -m cli.graduate_validator status
    python -m cli.graduate_validator tick
    python -m cli.graduate_validator history            # M13: read-only audit trail
    python -m cli.graduate_validator history doc_code_drift [N]
    HARNESS_MUTATION_TOKEN=graduate-validator   python -m cli.graduate_validator graduate doc_code_drift
    HARNESS_MUTATION_TOKEN=apply-user-preference python -m cli.graduate_validator demote   doc_code_drift

Exit codes: 0 ok; 2 usage error; 3 token/ready gate refused.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows cp949 console can't encode the em-dash / arrow glyphs this CLI prints
# (status '→', history '—'); reconfigure to utf-8 (codebase pattern, fail-soft).
for _s in (sys.stdout, sys.stderr):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import graduation as g  # noqa: E402

TOKEN_ENV = "HARNESS_MUTATION_TOKEN"


def _token() -> str:
    return os.environ.get(TOKEN_ENV, "").strip()


def _cmd_status() -> int:
    rows = g.status_report()
    print(f"graduation status (threshold N={g.GRADUATION_THRESHOLD}, "
          f"dedup window={g.DEDUP_WINDOW_SECONDS}s):")
    for r in rows:
        state = "BLOCKING" if r["graduated"] else ("READY" if r["ready"] else "advisory")
        print(
            f"  {r['validator']:18} [{state:8}] streak={r['consecutive_clean']}/{r['threshold']}"
            f" remaining={r['remaining']} last_drift={r['last_total_drift']}"
        )
    ready = g.ready_validators()
    if ready:
        print(f"\n  {len(ready)} ready to graduate: {', '.join(ready)}")
        print(f"  → HARNESS_MUTATION_TOKEN={g.TOKEN_GRADUATE} "
              f"python -m cli.graduate_validator graduate <name>")
    return 0


def _cmd_tick() -> int:
    from validators import graduation_scan_drift
    actions = g.run_tracked_scans_and_tick(scan_fn=graduation_scan_drift)
    print("scan-and-tick actions:")
    for name, action in actions.items():
        print(f"  {name:18} {action}")
    return _cmd_status() if actions else 0


def _cmd_history(rest: list[str]) -> int:
    """Read-only audit-trail view (M13). No token — pure forensic read.

    `history`              → summary (by_action + per-validator last flip) + tail.
    `history <validator>`  → that validator's records.
    Optional trailing integer caps the tail (default 20).
    """
    from lib import graduation_audit as ga

    name: str | None = None
    limit = 20
    for arg in rest:
        if arg.isdigit():
            limit = int(arg)
        elif name is None:
            name = arg
        else:
            print(f"usage: history [validator] [N]; unexpected {arg!r}", file=sys.stderr)
            return 2

    summary = ga.summary_report()
    if name is None:
        print(f"graduation audit trail ({summary['total_records']} record(s)):")
        ba = summary["by_action"]
        print("  by action: " + (", ".join(f"{a}={c}" for a, c in ba.items()) or "(none)"))
        if summary["validators"]:
            for vname, v in summary["validators"].items():
                print(f"  {vname:18} total={v['total']} last={v['last_action']} "
                      f"@ {v['last_ts']} (token={v['last_token']})")
        else:
            print("  (no flips recorded yet — trail populates on graduate/demote/circuit-breaker)")
        recs = ga.read_history(limit=limit)
    else:
        recs = ga.history_for_validator(name, limit=limit)
        print(f"graduation audit trail for {name!r} ({len(recs)} of "
              f"{summary['validators'].get(name, {}).get('total', 0)} record(s)):")

    if recs:
        print(f"  --- last {min(limit, len(recs))} record(s) ---")
        for r in recs:
            print(f"  {r.get('ts','?'):26} {str(r.get('action','?')):22} "
                  f"{str(r.get('validator','?')):18} token={r.get('token_used')}")
    return 0


def _cmd_graduate(name: str) -> int:
    try:
        g.graduate(name, token=_token())
    except g.TokenError as e:
        print(f"[REFUSED] {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    print(f"[OK] graduated {name} → blocking. VALIDATOR_NAMES now includes it; "
          f"commit the source/state diff. (demote with apply-user-preference if it regresses.)")
    return 0


def _cmd_demote(name: str) -> int:
    try:
        g.demote(name, token=_token())
    except g.TokenError as e:
        print(f"[REFUSED] {e}", file=sys.stderr)
        return 3
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    print(f"[OK] demoted {name} → advisory; streak reset to 0.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "status":
        return _cmd_status()
    if cmd == "tick":
        return _cmd_tick()
    if cmd == "history":
        return _cmd_history(rest)
    if cmd in ("graduate", "demote"):
        if len(rest) != 1:
            print(f"usage: {cmd} <validator-name>  (one of {', '.join(g.TRACKED)})",
                  file=sys.stderr)
            return 2
        return _cmd_graduate(rest[0]) if cmd == "graduate" else _cmd_demote(rest[0])
    print(f"unknown command {cmd!r}; expected status|tick|history|graduate|demote", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
