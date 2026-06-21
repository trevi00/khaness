#!/usr/bin/env python3
"""atlas_structure validator — Atlas vault structural invariant enforcement.

Per atlas P0 design (allsolution-compressed-phase0, orchestrator session
orch-1779544694-27f7cc), enforces:

  - Depth limits: ≤3 baseline (vault/domain/type/file.md), ≤4 if sub-domain
    pattern detected (vault/domain/sub-domain/type/file.md), ≥5 = FAIL.
  - Capacity limits: per-folder ≤30 soft (WARN), ≤50 hard (FAIL).
    Reflects PKM community ≤30/50 norm (Miller 7±2 + INDEX grooming).
  - Required structure: _meta/ + _common/ + 99-archive/ at root.
  - Domain registry consistency: domain folders at root must be listed in
    _meta/domain-registry.md (heuristic: header "### N. `<name>/`").
  - Per-domain type subdirs: each registered domain must have
    {concepts,decisions,artifacts,journal}/ (warn if missing).

Caller contract (validators/__init__.py L14-19 표준):
  - main() -> None, no args
  - reads ATLAS_DIR (CLAUDE_HOME / 'atlas')
  - prints [PASS]/[FAIL]/[WARN] lines to stdout
  - never raises; failures via stdout
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.paths import ATLAS_DIR  # noqa: E402


SOFT_CAP_PER_FOLDER = 30
HARD_CAP_PER_FOLDER = 50
DEPTH_BASELINE = 3
DEPTH_MAX = 4
ROOT_DOMAINS_SOFT = 10
ROOT_DOMAINS_HARD = 15

REQUIRED_ROOT_DIRS = ("_meta", "_common", "99-archive")
REQUIRED_TYPE_SUBDIRS = ("concepts", "decisions", "artifacts", "journal")

_DOMAIN_REGISTRY_HEADER_RE = re.compile(
    r"^###\s+\d+\.\s+`([a-z][a-z0-9_-]*)/`", re.MULTILINE
)


def _registered_domains() -> set[str]:
    registry = ATLAS_DIR / "_meta" / "domain-registry.md"
    if not registry.is_file():
        return set()
    try:
        text = registry.read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(_DOMAIN_REGISTRY_HEADER_RE.findall(text))


def _is_system_dir(name: str) -> bool:
    return name.startswith("_") or name in ("99-archive",)


def _scan_depth(root: Path, base_depth: int = 0) -> list[tuple[Path, int]]:
    """Walk and return (file_path, depth_from_root) tuples for .md files.

    depth counts directory components below ATLAS_DIR. So:
      ATLAS_DIR/INDEX.md -> depth 0
      ATLAS_DIR/domain/concepts/foo.md -> depth 2
      ATLAS_DIR/domain/sub/concepts/foo.md -> depth 3
    """
    out: list[tuple[Path, int]] = []
    for p in root.rglob("*.md"):
        rel = p.relative_to(root)
        out.append((p, len(rel.parts) - 1))
    return out


def main() -> None:
    if not ATLAS_DIR.is_dir():
        print("[PASS] ATLAS_DIR 없음 (skip)")
        return

    failures: list[str] = []
    warnings: list[str] = []

    # 1. Required root dirs
    for required in REQUIRED_ROOT_DIRS:
        if not (ATLAS_DIR / required).is_dir():
            failures.append(f"missing required root dir: {required}/")

    # 2. Root-level domain count
    root_entries = [p for p in ATLAS_DIR.iterdir() if p.is_dir()]
    domain_dirs = [p for p in root_entries if not _is_system_dir(p.name)]
    if len(domain_dirs) > ROOT_DOMAINS_HARD:
        failures.append(
            f"root domain count {len(domain_dirs)} > hard cap {ROOT_DOMAINS_HARD}"
        )
    elif len(domain_dirs) > ROOT_DOMAINS_SOFT:
        warnings.append(
            f"root domain count {len(domain_dirs)} > soft cap {ROOT_DOMAINS_SOFT}"
        )

    # 3. Domain registry consistency
    registered = _registered_domains()
    if registered:
        on_disk = {p.name for p in domain_dirs}
        unregistered = on_disk - registered
        for name in sorted(unregistered):
            warnings.append(f"unregistered domain on disk: {name}/")
        missing_on_disk = registered - on_disk
        for name in sorted(missing_on_disk):
            warnings.append(f"registered domain missing on disk: {name}/")

    # 4. Per-domain type subdirs
    for d in domain_dirs:
        for sub in REQUIRED_TYPE_SUBDIRS:
            if not (d / sub).is_dir():
                warnings.append(f"{d.name}/ missing type subdir: {sub}/")

    # 5. Depth + capacity check
    files = _scan_depth(ATLAS_DIR)
    for p, depth in files:
        if depth >= 5:
            failures.append(f"depth {depth} >= 5: {p.relative_to(ATLAS_DIR)}")
        elif depth == 4:
            # depth 4 only allowed if there's a sub-domain pattern (heuristic:
            # parent of parent is a registered domain and parent has the 4
            # type subdirs structure)
            rel = p.relative_to(ATLAS_DIR)
            parts = rel.parts
            if len(parts) >= 4 and parts[0] in registered:
                # Looks like domain/sub-domain/type/file.md — OK
                pass
            else:
                warnings.append(
                    f"depth 4 without sub-domain pattern: {rel}"
                )

    # 6. Per-folder capacity
    folders_seen: dict[Path, int] = {}
    for p in ATLAS_DIR.rglob("*.md"):
        folder = p.parent
        folders_seen[folder] = folders_seen.get(folder, 0) + 1
    for folder, count in folders_seen.items():
        rel = folder.relative_to(ATLAS_DIR)
        rel_str = str(rel) if str(rel) != "." else "(root)"
        if count > HARD_CAP_PER_FOLDER:
            failures.append(
                f"{rel_str}: {count} files > hard cap {HARD_CAP_PER_FOLDER} (split required)"
            )
        elif count > SOFT_CAP_PER_FOLDER:
            warnings.append(
                f"{rel_str}: {count} files > soft cap {SOFT_CAP_PER_FOLDER} (INDEX grooming)"
            )

    # Emit
    if not failures and not warnings:
        print(f"[PASS] atlas_structure: {len(domain_dirs)} domains, {len(files)} .md files, no violations")
        return

    for w in warnings:
        print(f"[WARN] atlas_structure: {w}")
    for f in failures:
        print(f"[FAIL] atlas_structure: {f}")
    if not failures:
        print(f"[PASS] atlas_structure: {len(warnings)} warnings, 0 failures")


if __name__ == "__main__":
    main()
