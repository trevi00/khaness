"""brain_git_status — read-only durability check for the brain/ FILE→REMOTE hop
(M-brain-handoff E1, made coherent with the D1 auto-push).

The brain auto-save writes brain/ FILES, but the git push that makes them survive
machine death is automated only via D1 (lib.brain_autopush pushes brain/ to the orphan
`brain-snapshots` branch). This computes whether the LIVE brain/ is durably on the
remote, so a SessionStart advisory gives a TRUE 'not yet pushed' nudge — closing the
'false silence' where the old live→file divergence metric went quiet the instant the
auto-save wrote the file.

TWO modes (the D1 gen-2 Critic showed a master-relative metric is incoherent with a
side-branch push — so this measures CONTENT against the actual push target):
  - branch mode (origin/brain-snapshots EXISTS): at_risk ⟺ the live brain/ tree differs
    from origin/brain-snapshots (`git diff origin/brain-snapshots -- brain/`). A
    successful autopush makes them equal → silent; a non-ff leaves them different →
    nudges. This is the same ref D1 pushes to, so the two features are coherent.
  - fallback mode (no brain-snapshots yet — pre-first-autopush): at_risk ⟺ brain/ has
    uncommitted changes OR commits ahead of the branch upstream. Preserves the original
    pre-D1 warning so a never-pushed brain still nudges.

Pure-read (git diff/status/log), fail-soft (any git error → not at risk, never a false
alarm). The git tree is CLAUDE_HOME (the ~/.claude repo that tracks brain/).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

_SNAPSHOT_REF = "origin/brain-snapshots"


def _parse_jsonl_text(text: str) -> list[dict]:
    """Lenient JSONL parse — skip blank/torn lines, never raise (advisory must not
    crash). Deliberately NOT brain_store._read_jsonl_pinned (that hard-fails on schema
    drift); a SessionStart read should degrade, not abort."""
    out: list[dict] = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _ids(recs: list[dict], key: str) -> set[str]:
    """The durable identity set for a layer. '__line__' (evidence, no id) → whole-record
    set; else the layer's id-key. Format-insensitive (compares identities, not bytes),
    so JSON re-serialization differences never produce a false 'at risk'."""
    if key == "__line__":
        return {json.dumps(r, sort_keys=True) for r in recs}
    return {str(r.get(key)) for r in recs if r.get(key) is not None}


def _git(home: Path, args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", str(home), *args],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
    except Exception:  # noqa: BLE001 — git absent / timeout / OS error → fail-soft
        return None


def _ref_exists(home: Path, ref: str) -> bool:
    cp = _git(home, ["rev-parse", "--verify", "-q", ref])
    return cp is not None and cp.returncode == 0


def _resolve_home(home: str | Path | None) -> Path:
    if home is None:
        from .paths import CLAUDE_HOME
        return Path(CLAUDE_HOME)
    return Path(home)


def brain_durability(home: str | Path | None = None) -> dict:
    """Return {at_risk: bool, detail: str, mode: 'branch'|'fallback'}.

    branch mode: at_risk ⟺ live brain/ differs from origin/brain-snapshots (the
    auto-push target). fallback: at_risk ⟺ uncommitted brain/ OR brain commits ahead of
    @{upstream}. Pure-read, fail-soft → not at risk on any git error."""
    home = _resolve_home(home)

    if _ref_exists(home, _SNAPSHOT_REF):
        # at_risk ⟺ some live brain record id is NOT yet on origin/brain-snapshots.
        # Id-set comparison (not `git diff`) so brain_store's JSON re-serialization +
        # all-layer-file writes never produce a false positive — durability is about
        # which IDENTITIES are on the remote, not byte-identical files.
        try:
            from lib import brain_store as bs
            brain_dir = bs._brain_dir()
            for _live, brain_path, key in bs._jsonl_layers():
                rel = brain_path.relative_to(brain_dir).as_posix()
                live_file = home / "brain" / rel
                live_recs = _parse_jsonl_text(live_file.read_text(encoding="utf-8")) if live_file.is_file() else []
                cp = _git(home, ["show", f"{_SNAPSHOT_REF}:brain/{rel}"])
                remote_recs = _parse_jsonl_text(cp.stdout) if (cp is not None and cp.returncode == 0) else []
                if _ids(live_recs, key) - _ids(remote_recs, key):   # live ids missing on remote
                    return {"at_risk": True, "mode": "branch",
                            "detail": "live brain/ not yet auto-pushed to brain-snapshots"}
        except Exception:  # noqa: BLE001 — fail-soft → not at risk
            return {"at_risk": False, "detail": "", "mode": "branch"}
        return {"at_risk": False, "detail": "", "mode": "branch"}

    # fallback — no snapshot branch yet
    uncommitted = 0
    cp = _git(home, ["status", "--porcelain", "--", "brain/"])
    if cp is not None and cp.returncode == 0:
        uncommitted = sum(1 for ln in cp.stdout.splitlines() if ln.strip())
    unpushed = 0
    cp = _git(home, ["log", "@{upstream}..HEAD", "--oneline", "--", "brain/"])
    if cp is not None and cp.returncode == 0:
        unpushed = sum(1 for ln in cp.stdout.splitlines() if ln.strip())
    parts = []
    if uncommitted:
        parts.append(f"{uncommitted} uncommitted brain file(s)")
    if unpushed:
        parts.append(f"{unpushed} unpushed brain commit(s)")
    return {"at_risk": bool(parts), "mode": "fallback", "detail": " + ".join(parts)}


def at_risk(home: str | Path | None = None) -> bool:
    """True iff the live brain/ is not yet durably on the remote."""
    return bool(brain_durability(home)["at_risk"])
