"""reverse_prd_checkpoint — per-release checkpoint + source-drift detection for
/harness-reverse-prd.

Closes the harness-reverse-prd gap: it reverse-engineers a codebase into a PRD across
4 release stages where "earlier artifacts feed later, never overwritten", BUT a source
code change (the pinned commit moving) BETWEEN stages silently invalidates the prior
releases' artifacts — "no invalidation detection". This records, per release, the
SOURCE commit it was built against, so before continuing the next stage the command can
detect drift (current source commit != the commit a completed release was built on) and
prompt a re-baseline instead of layering new artifacts on stale ones.

Read-only on the source (only reads its git HEAD); writes only the checkpoint under the
OUTPUT root. Fail-soft (a non-git source / write error degrades, never raises).
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

RELEASES = ("1-A", "1-B", "1-C", "2")
_STATUSES = ("pending", "partial", "complete")


def source_commit(src: str | Path) -> str | None:
    """The source tree's current git HEAD (the 'pinned commit'). None if not a repo."""
    try:
        cp = subprocess.run(
            ["git", "-C", str(src), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    return cp.stdout.strip() if cp.returncode == 0 and cp.stdout.strip() else None


def _ckpt_path(out_root: str | Path) -> Path:
    return Path(out_root) / ".claude" / "reverse-prd-checkpoint.json"


def load_checkpoint(out_root: str | Path) -> dict:
    p = _ckpt_path(out_root)
    if not p.is_file():
        return {"releases": {}}
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) and isinstance(v.get("releases"), dict) else {"releases": {}}
    except Exception:  # noqa: BLE001
        return {"releases": {}}


def record_release(out_root: str | Path, release: str, *, src_commit: str | None,
                   status: str, ts_ms: int | None = None) -> bool:
    """Record that `release` reached `status`, built against `src_commit`. Returns True
    on write. Fail-soft."""
    if release not in RELEASES or status not in _STATUSES:
        return False
    ck = load_checkpoint(out_root)
    ck["releases"][release] = {
        "src_commit": src_commit, "status": status,
        "ts_ms": int(ts_ms if ts_ms is not None else time.time() * 1000)}
    try:
        p = _ckpt_path(out_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(ck, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def check_drift(out_root: str | Path, src: str | Path) -> dict:
    """Compare the source's CURRENT commit to the commit each recorded release was built
    on. {current_commit, drifted_releases: [release...], drift: bool}. A drifted release's
    artifacts predate the current source → re-baseline before layering new stages on it."""
    current = source_commit(src)
    ck = load_checkpoint(out_root)
    drifted = []
    for rel, info in (ck.get("releases") or {}).items():
        built_on = info.get("src_commit")
        # only flag releases that recorded a commit AND it differs from the current one
        if built_on and current and built_on != current:
            drifted.append(rel)
    return {"current_commit": current, "drifted_releases": sorted(drifted),
            "drift": bool(drifted)}


def render_status(out_root: str | Path, src: str | Path) -> str:
    ck = load_checkpoint(out_root)
    d = check_drift(out_root, src)
    rels = ck.get("releases") or {}
    if not rels:
        return "[reverse-prd] no checkpoint yet (forward-looking)"
    lines = [f"[reverse-prd] source@{(d['current_commit'] or '?')[:8]}; releases:"]
    for rel in RELEASES:
        if rel in rels:
            info = rels[rel]
            flag = "  ⚠ DRIFT — re-baseline" if rel in d["drifted_releases"] else ""
            lines.append(f"  {rel}: {info.get('status')} (built@{(info.get('src_commit') or '?')[:8]}){flag}")
    return "\n".join(lines)
