"""dispatch_retry — bounded retry with full-jitter backoff for external dispatch (M15 D1).

Converged design: debate-1781607404-695af5 gen 2 (snapshot sha1
063a8944db41f71093ce0a84fcb3fc971ea175dc), decision D1.

Domain-agnostic: a caller supplies `fn` (the call to retry) and `classify` (exc → 'transient'
| 'permanent'). Permanent failures re-raise IMMEDIATELY (retry is futile — a config/code bug).
Transient failures retry up to `max_attempts` with FULL-JITTER exponential backoff (default ON,
per AWS backoff-and-jitter guidance — random sleep in [0, min(base*2**k, cap)] de-correlates
retry storms). `sleep_fn` is injected so tests never touch wall-clock. Imports NOTHING from
lib.breakers or engine.providers — pure, unit-testable with a scripted fake `fn`.

The breaker integration (engine.external_jury) wraps this: try_acquire gates BEFORE the retry
loop, and exactly ONE record_success/record_failure resolves the dispatch AFTER it — so N
transient retries that ultimately fail count as ONE breaker failure, not N.
"""
from __future__ import annotations

import random
import time
from typing import Callable, Literal, TypeVar

T = TypeVar("T")
Classification = Literal["transient", "permanent"]


def full_jitter(cap_for_attempt: float) -> float:
    """Default jitter: a uniform random draw in [0, cap_for_attempt] (AWS 'full jitter')."""
    if cap_for_attempt <= 0:
        return 0.0
    return random.uniform(0.0, cap_for_attempt)


def call_with_retry(
    fn: Callable[[], T],
    *,
    classify: Callable[[BaseException], Classification],
    max_attempts: int = 3,
    backoff_base_sec: float = 0.5,
    backoff_cap_sec: float = 8.0,
    jitter: Callable[[float], float] = full_jitter,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Call `fn()`, retrying transient failures with full-jitter backoff.

    - On success: return the value.
    - classify(exc) == 'permanent': re-raise immediately (no sleep, no further attempts).
    - classify(exc) == 'transient': sleep `jitter(min(backoff_base_sec*2**k, backoff_cap_sec))`
      then retry; after `max_attempts` total attempts re-raise the last exception.

    `max_attempts` is TOTAL attempts (1 initial + up to max_attempts-1 retries). `sleep_fn`/
    `jitter` are injected for deterministic tests. Pure — no breaker/provider coupling.
    """
    attempts = max(1, int(max_attempts))
    last_exc: BaseException | None = None
    for k in range(attempts):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 — classify decides retry vs re-raise
            if classify(exc) == "permanent":
                raise
            last_exc = exc
            if k >= attempts - 1:
                raise  # transient but exhausted
            cap = min(backoff_base_sec * (2 ** k), backoff_cap_sec)
            sleep_fn(jitter(cap))
    # Unreachable (the loop either returns or raises), but keep the type-checker happy.
    if last_exc is not None:  # pragma: no cover
        raise last_exc
    raise RuntimeError("call_with_retry: no attempts made")  # pragma: no cover
