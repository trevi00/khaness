"""breakers.config — runtime threshold override (v15.16, F closure).

v15.14 cycle (breaker_proposer)가 만든 제안을 운영자가 적용할 수 있도록
yaml runtime override + asymmetric 토큰 게이트 제공. composite.py module-level
상수는 default로 유지되어 yaml이 없으면 기존 동작 그대로.

Asymmetric token gate (critic_policy.py D4 패턴 재사용):

  임계 *상향* (더 관대 — false-positive 감소, 자원 절약 방향):
    - TRIP_PER_MODE 3→4
    - BACKOFF_BASE_SEC 60→120
    → configure-critic-policy 토큰 (강한 방향)

  임계 *하향* (더 민감 — 검출 강화, 안전 방향):
    - TRIP_PER_MODE 3→2
    - BACKOFF_BASE_SEC 60→30
    → apply-user-preference 토큰 (안전 방향)

  WINDOW / ANY_MODE / ANY_WINDOW (양방향 의미 모호):
    → apply-user-preference (보수적 기본)

Persistence: ~/.claude/config/breaker-thresholds.yaml

```yaml
version: 1
overrides:
  trip_per_mode: 4
  backoff_base_sec: 120
```

Public surface:
- BreakerThresholds (frozen dataclass): default values lock
- resolve_thresholds() -> BreakerThresholds: yaml merge + default fallback
- apply_override(key, value, *, token) -> bool: gated mutation
- TOKEN_STRONG / TOKEN_SAFE constants
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from ..paths import CLAUDE_HOME


# --- Default values (mirror composite.py module-level constants) -----------------
DEFAULT_TRIP_PER_MODE: int = 3
DEFAULT_TRIP_WINDOW: int = 10
DEFAULT_TRIP_ANY_MODE: int = 5
DEFAULT_TRIP_ANY_WINDOW: int = 20
DEFAULT_BACKOFF_BASE_SEC: int = 60
DEFAULT_BACKOFF_CAP_SEC: int = 3600


# --- Token constants -------------------------------------------------------------
TOKEN_STRONG: str = "configure-critic-policy"
TOKEN_SAFE: str = "apply-user-preference"


# Direction policy per key.
# "stronger_via" = 임계가 그 방향으로 갈 때 더 관대 (false-positive 감소,
# breaker가 덜 trip) → strong token 필요.
# 반대 방향(검출 강화)은 safe token만으로 충분.
_KEY_DIRECTION_POLICY: dict[str, str] = {
    "trip_per_mode": "increase_is_lenient",    # 3→4 더 관대
    "trip_any_mode": "increase_is_lenient",
    "backoff_base_sec": "increase_is_lenient",  # 120s → 240s 더 관대 (잠금 더 오래)
    "backoff_cap_sec": "increase_is_lenient",
    "trip_window": "ambiguous",                 # 큰 window는 더 많은 sample 필요
    "trip_any_window": "ambiguous",
}


_VALID_KEYS: frozenset[str] = frozenset(_KEY_DIRECTION_POLICY.keys())


@dataclass(frozen=True)
class BreakerThresholds:
    """Lock된 threshold tuple — default가 module-level 상수와 일치."""

    trip_per_mode: int = DEFAULT_TRIP_PER_MODE
    trip_window: int = DEFAULT_TRIP_WINDOW
    trip_any_mode: int = DEFAULT_TRIP_ANY_MODE
    trip_any_window: int = DEFAULT_TRIP_ANY_WINDOW
    backoff_base_sec: int = DEFAULT_BACKOFF_BASE_SEC
    backoff_cap_sec: int = DEFAULT_BACKOFF_CAP_SEC


CONFIG_PATH: Path = CLAUDE_HOME / "config" / "breaker-thresholds.yaml"


# --- YAML subset parser (NO PyYAML dep — critic_policy.py와 동일 패턴) -----------

def _safe_yaml_load(text: str) -> dict:
    """Parse minimal YAML subset:
        version: <int>
        overrides:
          <key>: <int>
    """
    out: dict = {"version": 1, "overrides": {}}
    in_overrides = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "overrides:":
            in_overrides = True
            continue
        if line.startswith("version:"):
            in_overrides = False
            try:
                out["version"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if in_overrides and line.startswith((" ", "\t")):
            stripped = line.strip()
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                try:
                    val = int(v.strip())
                except ValueError:
                    continue
                if key in _VALID_KEYS:
                    out["overrides"][key] = val
    return out


def _safe_yaml_dump(policy: dict) -> str:
    lines: list[str] = []
    lines.append(f"version: {int(policy.get('version', 1))}")
    lines.append("overrides:")
    overrides = policy.get("overrides", {}) or {}
    for k in sorted(overrides):
        v = overrides[k]
        if k in _VALID_KEYS and isinstance(v, int):
            lines.append(f"  {k}: {v}")
    return "\n".join(lines) + "\n"


def _load_policy() -> dict:
    if not CONFIG_PATH.exists():
        return {"version": 1, "overrides": {}}
    try:
        return _safe_yaml_load(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {"version": 1, "overrides": {}}


def _save_policy(policy: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_safe_yaml_dump(policy), encoding="utf-8")


def resolve_thresholds() -> BreakerThresholds:
    """yaml overrides + default fallback. 호출 비용 ~밀리초 (cache 없음 —
    매 record_failure 호출마다 fresh read로 hot-reload 가능)."""
    policy = _load_policy()
    overrides = policy.get("overrides", {}) or {}
    base = BreakerThresholds()
    kwargs = {k: int(v) for k, v in overrides.items() if k in _VALID_KEYS and isinstance(v, int)}
    return replace(base, **kwargs) if kwargs else base


def apply_override(key: str, value: int, *, token: str | None) -> bool:
    """yaml override 적용 — asymmetric token gate.

    Returns True iff persisted change; False on no-op (이미 같은 값).

    Raises:
      ValueError      : 알 수 없는 key / 음수 value
      PermissionError : token이 direction 정책의 required tier와 불일치
    """
    if key not in _VALID_KEYS:
        raise ValueError(
            f"unknown key {key!r}; valid: {sorted(_VALID_KEYS)}"
        )
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"value must be positive int, got {value!r}")

    current = getattr(resolve_thresholds(), key)
    if current == value:
        return False

    direction = _KEY_DIRECTION_POLICY[key]
    if direction == "increase_is_lenient":
        # increase → 더 관대 → strong 필요. decrease → 검출 강화 → safe.
        required = TOKEN_STRONG if value > current else TOKEN_SAFE
    else:
        # ambiguous 키 (window) — safe 토큰
        required = TOKEN_SAFE

    if token != required:
        raise PermissionError(
            f"changing {key} {current} → {value} requires {required!r}, "
            f"got {token!r}"
        )

    policy = _load_policy()
    overrides = dict(policy.get("overrides", {}) or {})
    overrides[key] = value
    policy["overrides"] = overrides
    _save_policy(policy)
    return True


__all__ = [
    "BreakerThresholds",
    "CONFIG_PATH",
    "TOKEN_SAFE",
    "TOKEN_STRONG",
    "apply_override",
    "resolve_thresholds",
]
