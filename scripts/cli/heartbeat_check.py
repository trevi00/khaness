#!/usr/bin/env python3
"""heartbeat_check — stale heartbeat 검출 + emit (v15.24 Q).

운영자가 주기적으로 실행 (cron 또는 manual). state/heartbeats/ 모든 file을
스캔, max_age_sec 초과 (stale) sid에 대해 'heartbeat.stale' event emit.

Usage:
    cd ~/.claude/scripts
    python -m cli.heartbeat_check                       # default 300s
    python -m cli.heartbeat_check --max-age-sec 600     # 10분
    python -m cli.heartbeat_check --json                # 기계 가독
    python -m cli.heartbeat_check --prune-after 7200    # 2시간 초과 file 삭제

cron 예시 (Linux):
    */5 * * * * cd ~/.claude/scripts && python -m cli.heartbeat_check >> ~/.claude/state/heartbeat-check.log

Exit code: 0 (stale 있어도 정상 종료 — observability 도구).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _raw_event_emit(event_type: str, payload: dict) -> None:
    """Low-level emit (event_store). fail-open."""
    try:
        from lib.event_store import append as event_append
        event_append({"event_type": event_type, **payload})
    except Exception:
        pass


def _event_emit_validated(event_type: str, payload: dict) -> None:
    try:
        from lib.event_taxonomy import emit_with_validation
        emit_with_validation(event_type, payload, _raw_event_emit)
    except Exception:
        _raw_event_emit(event_type, payload)


def find_stale(max_age_sec: int, *, base_dir: Path | None = None) -> list[tuple[str, str, str]]:
    """state/heartbeats/ 모든 file 중 stale인 (sid, agent_type, last_ts) 반환."""
    from lib.heartbeat import _heartbeat_dir, _ts_to_epoch, _now_epoch
    from lib.atomic_json import read_json
    base = _heartbeat_dir(base_dir)
    if not base.exists():
        return []
    now_e = _now_epoch()
    out: list[tuple[str, str, str]] = []
    for p in sorted(base.glob("*.json")):
        rec = read_json(p, default={})
        if not isinstance(rec, dict):
            continue
        ts = rec.get("last_ts")
        if not isinstance(ts, str):
            continue
        epoch = _ts_to_epoch(ts)
        if epoch is None:
            continue
        if now_e - epoch > max_age_sec:
            out.append((p.stem, str(rec.get("agent_type", "")), ts))
    return out


def main(argv: list[str] | None = None) -> int:
    from lib.heartbeat import DEFAULT_STALE_SEC, prune as heartbeat_prune
    parser = argparse.ArgumentParser(
        prog="heartbeat-check",
        description="v15.24 Q — stale heartbeat 검출 + heartbeat.stale event emit",
    )
    parser.add_argument("--max-age-sec", type=int, default=DEFAULT_STALE_SEC,
                        help=f"stale 기준 (기본 {DEFAULT_STALE_SEC}s)")
    parser.add_argument("--json", action="store_true", help="기계 가독 출력")
    parser.add_argument("--prune-after", type=int, default=None,
                        help="초 단위 (제공 시 그 이상 오래된 file 삭제)")
    args = parser.parse_args(argv)

    stale = find_stale(args.max_age_sec)

    for sid, agent_type, ts in stale:
        _event_emit_validated("heartbeat.stale", {
            "session_id": sid,
            "agent_type": agent_type,
            "last_ts": ts,
            "max_age_sec": args.max_age_sec,
        })

    pruned = 0
    if args.prune_after is not None:
        pruned = heartbeat_prune(older_than_sec=args.prune_after)

    if args.json:
        out = {
            "max_age_sec": args.max_age_sec,
            "stale_count": len(stale),
            "pruned_count": pruned,
            "stale": [
                {"session_id": s, "agent_type": a, "last_ts": t}
                for s, a, t in stale
            ],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"=== heartbeat check — max_age={args.max_age_sec}s ===")
        print(f"stale: {len(stale)}  pruned: {pruned}")
        for sid, agent_type, ts in stale:
            print(f"  - sid={sid}  agent_type={agent_type}  last_ts={ts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
