"""jsonl_cache — canonical mtime+size-cached JSONL reader.

Extracted 2026-06-21 (hygiene Tier-2) from the byte-identical
`insight_index._load_jsonl` (L1) and its self-labeled "Mirror of L1"
`l2_facts._load_jsonl` (L2). Both layers re-parse JSONL on every query and
cache the parsed list keyed by (mtime_ns, size) to hold the L1 SLO
(p99 query < 50ms @ 5k entries on Windows). The two copies were a drift
hazard — a bugfix in one silently diverged from the other.

`load_jsonl_cached` takes the caller's cache dict EXPLICITLY (rather than a
shared module global) so each layer keeps its own isolated cache — no
cross-layer contamination, identical behavior to the two originals.

Invariants preserved verbatim from the originals:
  - missing file -> []
  - stat() OSError -> []  (never the cache)
  - cache hit iff (mtime_ns, size) unchanged -> O(1) return of the SAME list
  - blank lines skipped; torn/invalid JSON lines skipped (atomic append-only
    writes guarantee mtime/size change <=> content change, so a torn final
    line from a concurrent appender is dropped, not mis-parsed)
  - non-dict records skipped (only dict rows retained)
  - read OSError mid-stream -> return what parsed so far, do NOT cache
"""
from __future__ import annotations

import json
from pathlib import Path

# Cache value shape: {path: ((mtime_ns, size), parsed_rows)}
CacheT = dict[Path, tuple[tuple[int, int], list[dict]]]


def load_jsonl_cached(path: Path, cache: CacheT) -> list[dict]:
    """Parse a JSONL file into list[dict] with (mtime_ns, size) cache invalidation.

    `cache` is the caller-owned dict (one per memory layer) — mutated in place
    on a cache miss. Returns only dict rows; fail-soft on every IO/JSON error.
    """
    if not path.exists():
        return []
    try:
        st = path.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    cached = cache.get(path)
    if cached is not None and cached[0] == key:
        return cached[1]
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        return out
    cache[path] = (key, out)
    return out
