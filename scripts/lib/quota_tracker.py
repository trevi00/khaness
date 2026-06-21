"""quota_tracker — shared per-(sid, key) JSON-sidecar dispatch counter (M10).

`lib/strike_dispatcher.py` and `lib/evaluator_dispatcher.py` each reimplemented
the SAME atomic JSON-sidecar counter — load → increment → atomic write at
`state/<subsystem>/<sid>/dispatch_counter.json` — with copy-pasted cold-start,
corruption, and value-coercion handling. This extracts that primitive ONCE so
both consumers (and any future quota-bounded dispatcher) share one tested core.

The one thing that must NOT be flattened is a deliberate **corruption-policy
asymmetry** between the two original call sites:

  - strike_dispatcher fails CLOSED on a corrupt counter (raises) — its quota
    bounds N-strike researcher recursion, so silently zeroing the counter would
    re-enable infinite recursion. Quota loss = safety risk → never silent.
  - evaluator_dispatcher fails SOFT ({}) — it re-evaluates a phase at most
    `limit` times regardless, so a lost counter costs at most a few redundant
    evaluations, never a runaway. Empty-on-corrupt is the cheaper choice.

`on_corrupt` ('raise' | 'empty') carries that policy per instance, and
`value_mode` ('coerce' | 'filter') preserves each site's value handling
(strike coerced `int(v)`; evaluator filtered to non-negative non-bool ints).
The primitive is the generalization the two call sites were special cases of —
parameterized, not flattened.

Read-only-safe, atomic writes (lib.atomic_json), lazy STATE_DIR (honors the
run_units junction isolation and test redirects). lib→lib only (no validators
import — layering clean).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from .atomic_json import write_json_atomic

OnCorrupt = Literal["raise", "empty"]
ValueMode = Literal["coerce", "filter"]


class QuotaCounter:
    """A per-(sid, key) integer counter persisted to one JSON sidecar per sid.

    Args:
      subsystem:  the `state/<subsystem>/<sid>/` path segment (e.g. 'orchestrator',
                  'evaluator').
      on_corrupt: 'raise' → fail-closed RuntimeError on a malformed/non-object
                  counter (quota loss = safety risk); 'empty' → fail-soft {}.
      value_mode: 'coerce' → `int(v)` every value (legacy strike behavior);
                  'filter' → keep only non-negative non-bool ints (legacy
                  evaluator behavior).
      filename:   sidecar basename (default 'dispatch_counter.json').
      label:      name used in error messages (default = subsystem).
    """

    def __init__(self, subsystem: str, *, on_corrupt: OnCorrupt = "empty",
                 value_mode: ValueMode = "filter",
                 filename: str = "dispatch_counter.json",
                 label: str | None = None) -> None:
        if not isinstance(subsystem, str) or not subsystem:
            raise ValueError(f"subsystem must be a non-empty str, got {subsystem!r}")
        if on_corrupt not in ("raise", "empty"):
            raise ValueError(f"on_corrupt must be 'raise'|'empty', got {on_corrupt!r}")
        if value_mode not in ("coerce", "filter"):
            raise ValueError(f"value_mode must be 'coerce'|'filter', got {value_mode!r}")
        self.subsystem = subsystem
        self.on_corrupt = on_corrupt
        self.value_mode = value_mode
        self.filename = filename
        self.label = label or subsystem

    def path(self, sid: str) -> Path:
        """state/<subsystem>/<sid>/<filename>. Creates the dir. Lazy STATE_DIR so
        test fixtures redirecting lib.paths.STATE_DIR after import take effect."""
        if not isinstance(sid, str) or not sid:
            raise ValueError(f"sid must be non-empty str, got {sid!r}")
        from .paths import STATE_DIR, ensure_dir
        d = ensure_dir(STATE_DIR / self.subsystem / sid)
        return d / self.filename

    def _corrupt(self, msg: str, exc: Exception | None) -> dict[str, int]:
        """Apply the corruption policy: raise (fail-closed) or return {} (fail-soft)."""
        if self.on_corrupt == "raise":
            if exc is not None:
                raise RuntimeError(msg) from exc
            raise RuntimeError(msg)
        return {}

    def load(self, sid: str) -> dict[str, int]:
        """Read the {key: count} counter for `sid`.

        Cold start (no file / empty file) → {}. A transient read error → {}
        (no corruption signal). A malformed-JSON or non-object file applies the
        `on_corrupt` policy. Values are handled per `value_mode`.
        """
        path = self.path(sid)
        if not path.exists():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not text.strip():
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return self._corrupt(
                f"{self.label} counter corrupt for sid={sid}: {e}. "
                f"Manual inspection required (DO NOT delete — quota loss = "
                f"recursion risk). Inspect {path}", e)
        if not isinstance(data, dict):
            return self._corrupt(
                f"{self.label} counter must be a JSON object, got "
                f"{type(data).__name__} for sid={sid}", None)
        out: dict[str, int] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if self.value_mode == "coerce":
                try:
                    out[str(k)] = int(v)   # int(True)==1, matches legacy strike int(v)
                except (TypeError, ValueError):
                    return self._corrupt(
                        f"{self.label} counter has non-numeric value {v!r} for "
                        f"key {k!r}, sid={sid}", None)
            else:  # filter
                if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                    out[k] = v
        return out

    def record(self, sid: str, key: str) -> int:
        """Increment the counter for (sid, key) by 1, atomically. Returns new count.

        `key` must be a non-empty str (recording an empty key is meaningless —
        both legacy call sites gate emptiness, evaluator at record-time and strike
        at should_dispatch-time; centralizing the guard here is strictly safer)."""
        if not isinstance(key, str) or not key:
            raise ValueError(f"key must be non-empty str, got {key!r}")
        counter = self.load(sid)
        counter[key] = counter.get(key, 0) + 1
        write_json_atomic(self.path(sid), counter)
        return counter[key]

    def get(self, sid: str, key: str) -> int:
        """Current count for (sid, key), 0 if absent."""
        return self.load(sid).get(key, 0)

    def remaining(self, sid: str, key: str, limit: int) -> int:
        """How many more increments (sid, key) is allowed under `limit` (>=0)."""
        return max(0, limit - self.get(sid, key))

    def reset(self, sid: str) -> None:
        """Remove the sidecar (test/admin only — a production reset under a
        fail-closed quota would defeat the recursion safeguard)."""
        path = self.path(sid)
        if path.exists():
            path.unlink()
