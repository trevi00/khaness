"""agent_depth — recursion cap enforcement (v15.20 B / v15.9 P0 #2).

v15.9 P0 #2 — Anthropic "15x token multiplier" + Cognition write-heavy
telephone-game 손실 회피를 위한 agent recursion depth 강제 cap.

Hard cap: MAX_AGENT_DEPTH=3. depth 초과 시 pre_tool hook이 `deny` 반환.

Depth tracking: ORCH_DEPTH env var (current depth count).
  - root caller (Claude Code session start): depth=0
  - Agent tool dispatch: depth=N → spawned subagent runs with ORCH_DEPTH=N+1
  - subagent가 Agent tool 호출: pre_tool hook이 ORCH_DEPTH 검사 후 +1 시도

본 lib는 inspection helper만 제공. 실제 deny는 handlers/pre_tool/agent_depth_guard.py.

env-based tracking의 한계 (정직):
- ORCH_DEPTH 전파는 spawn pipeline에 의존 (Claude Code Agent tool이 env
  inherit). subagent가 의도적으로 unset할 수도 있음.
- 안전 default: env unset → depth=0 (root) 가정. 이는 root에서 +1 = 1, 정상.

Public API:
- MAX_AGENT_DEPTH: int (3)
- current_depth() -> int
- next_depth() -> int
- would_exceed_cap() -> bool
"""
from __future__ import annotations

import os


MAX_AGENT_DEPTH: int = 3


def current_depth() -> int:
    """현재 spawn chain의 depth. env 없으면 0 (root)."""
    raw = os.environ.get("ORCH_DEPTH", "0")
    try:
        d = int(raw)
        return max(0, d)
    except (TypeError, ValueError):
        return 0


def next_depth() -> int:
    """이 spawn이 진행되면 새 subagent의 depth."""
    return current_depth() + 1


def would_exceed_cap(cap: int = MAX_AGENT_DEPTH) -> bool:
    """다음 spawn이 cap을 초과하는지."""
    return next_depth() > cap


__all__ = [
    "MAX_AGENT_DEPTH",
    "current_depth",
    "next_depth",
    "would_exceed_cap",
]
