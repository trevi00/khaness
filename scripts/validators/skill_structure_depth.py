#!/usr/bin/env python3
"""skill_structure_depth — structure-DEPTH advisory for STAGED skill candidates (M21).

Flags a staged skill candidate (~/.claude/skill-candidates/<cid>.md) whose body
passes section PRESENCE (skill_quality_axes G4) but is HOLLOW — a bare standard
header with no substance, or a Gotchas section below MIN_GOTCHAS items. The depth
bar complements skill_quality_axes (presence + count) with a min-substance check.

Scope (the M27 lesson): this scans ONLY skill-candidates/ (bodies being promoted),
NEVER the built-in gate-exempt kha-* skills (many intentionally concise dispatch/
status commands). So it raises quality on NEW promotions without false-flagging
legitimately-thin built-ins. ADVISORY ([WARN], does not trip run_all's failure
regex); graduates to blocking via the graduate-validator token (roadmap M21:
advisory->graduate). Currently 0 active candidates -> [PASS] (forward-looking guard,
like M32 exit_contract_coverage). Caller contract: main()->None, prints [PASS]/[WARN].
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.skill_structure_depth import structure_depth_gaps  # noqa: E402


def _candidates_dir() -> Path:
    from lib.paths import CLAUDE_HOME
    return CLAUDE_HOME / "skill-candidates"


def find_hollow_candidates(candidates_dir: Path) -> list[tuple[str, list[str]]]:
    """[(candidate_name, gaps)] for ACTIVE staged .md candidates with depth gaps.

    Skips .dismissed / .promoted / .promoting historical/marker files (only an
    active `<cid>.md` is a live promotion target). Pure (testable)."""
    out: list[tuple[str, list[str]]] = []
    if not candidates_dir.is_dir():
        return out
    for f in sorted(candidates_dir.glob("*.md")):
        # an active candidate is exactly '<cid>.md' — historical have extra suffixes
        # like '.md.dismissed.<ts>' (which glob('*.md') already excludes), but guard
        # against any '<cid>.md' that is itself a marker carrier.
        if any(part in f.name for part in (".dismissed", ".promoted", ".promoting")):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        gaps = structure_depth_gaps(text)
        if gaps:
            out.append((f.name, gaps))
    return out


def main() -> None:
    hollow = find_hollow_candidates(_candidates_dir())
    if not hollow:
        print("[PASS] skill_structure_depth: no staged skill candidate has hollow standard sections")
        return
    for name, gaps in hollow:
        print(f"[WARN] skill_structure_depth: candidate {name} is structurally hollow — "
              f"{'; '.join(gaps[:4])}. Deepen before promotion (skill_quality_axes checks "
              f"presence; this checks substance).")
    try:
        from lib.logging import log_telemetry
        log_telemetry("skill-structure-depth-hollow", {
            "count": len(hollow), "samples": [n for n, _ in hollow[:10]],
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
