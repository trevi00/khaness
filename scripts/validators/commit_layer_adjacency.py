#!/usr/bin/env python3
"""Commit layer-adjacency validator — enforces 5-tier 단방향 의존.

## Spec (inline)

### Purpose (F2 binding condition, fixplan-meta debate Gen4; cli tier added
### harness-full-review rank 2 — cli is the already-doctrinal top tier, was
### previously unmodeled so reverse edges INTO cli were invisible)
- lib imports nothing project-internal except lib (intra-lib OK).
- validators import lib only (+intra-validators OK).
- handlers import lib + validators only (+intra-handlers OK).
- engine imports lib + validators + handlers (+intra-engine OK).
- cli (top) imports lib + validators + handlers + engine (+intra-cli OK).
- All reverse imports forbidden:
  * lib → validators / handlers / engine / cli
  * validators → handlers / engine / cli
  * handlers → engine / cli
  * engine → cli

### Modes
1. Pre-commit (default if `git` available):
   - `git diff --cached --name-only` — check staged Python files only.
   - Fallback to `git diff HEAD~1 HEAD --name-only` if no staged.
2. Full-tree scan (no git or `--all` arg):
   - Walk scripts/{lib,validators,handlers,engine,cli}/**/*.py.

### Output (caller contract)
- main() -> None, prints `[PASS]` / `[FAIL]` lines to stdout.
- `[FAIL]` lines: `[FAIL] <file>: <importing_layer> -> <imported_layer> (line N)`
- exit code via stdout convention only (never raises, always returns).

### Whitelist (no enforcement)
- tests/, state/, telemetry/, .git/ — out of layer model.
- __pycache__/ — ignored.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

# Layer order (low→high). A file in layer i may import from layers 0..i.
# cli is the top tier (orchestration entry points): may import any lower layer;
# a lower-layer file importing `from cli` is the most severe reverse edge.
_LAYERS = ("lib", "validators", "handlers", "engine", "cli")
_LAYER_INDEX = {name: i for i, name in enumerate(_LAYERS)}


def _classify(path: Path) -> str | None:
    """Return layer name for a path, or None if outside the layer model."""
    try:
        rel = path.resolve().relative_to(_SCRIPTS)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    head = parts[0]
    return head if head in _LAYER_INDEX else None


def _imported_layer(module: str) -> str | None:
    """Map import path 'lib.foo.bar' or 'engine.x' to its layer head, else None."""
    if not module:
        return None
    head = module.split(".", 1)[0]
    return head if head in _LAYER_INDEX else None


def _check_file(path: Path) -> list[str]:
    """Return list of [FAIL] lines for one .py file. Empty list if clean."""
    layer = _classify(path)
    if layer is None:
        return []
    self_idx = _LAYER_INDEX[layer]
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # let other validators flag syntax errors

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Relative imports (level >= 1) are intra-layer by construction.
            if node.level >= 1:
                continue
            target = _imported_layer(module)
        elif isinstance(node, ast.Import):
            target = None
            for alias in node.names:
                t = _imported_layer(alias.name)
                if t is not None:
                    target = t
                    break
        else:
            continue

        if target is None:
            continue
        if _LAYER_INDEX[target] > self_idx:
            findings.append(
                f"[FAIL] {path.relative_to(_SCRIPTS).as_posix()}: "
                f"{layer} -> {target} (line {node.lineno})"
            )
    return findings


def _git_changed_files() -> list[Path] | None:
    """Return list of staged or last-commit .py paths under scripts/, or None if no git."""
    cwd = str(_SCRIPTS.parent)
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    raw = r.stdout.strip().splitlines()
    if not raw:
        try:
            r2 = subprocess.run(
                ["git", "diff", "HEAD~1", "HEAD", "--name-only"],
                cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=5,
            )
        except subprocess.SubprocessError:
            return []
        if r2.returncode != 0:
            return []
        raw = r2.stdout.strip().splitlines()
    out: list[Path] = []
    for line in raw:
        p = (Path(cwd) / line).resolve()
        if p.suffix == ".py" and p.is_file() and _classify(p) is not None:
            out.append(p)
    return out


def _full_tree_files() -> list[Path]:
    out: list[Path] = []
    for layer in _LAYERS:
        layer_dir = _SCRIPTS / layer
        if not layer_dir.is_dir():
            continue
        for p in layer_dir.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def main() -> None:
    # Defensive — StringIO/captured streams in tests don't have reconfigure().
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    use_full = "--all" in sys.argv
    if use_full:
        targets = _full_tree_files()
        mode = "full-tree"
    else:
        targets = _git_changed_files()
        if targets is None:
            targets = _full_tree_files()
            mode = "full-tree (git unavailable)"
        elif not targets:
            print("[PASS] commit_layer_adjacency: no staged Python files under scripts/")
            return
        else:
            mode = "git-staged"

    all_findings: list[str] = []
    for path in targets:
        all_findings.extend(_check_file(path))

    if all_findings:
        for line in all_findings:
            print(line)
        print(f"[FAIL] commit_layer_adjacency: {len(all_findings)} reverse-edge violation(s) "
              f"({mode}, {len(targets)} files)")
    else:
        print(f"[PASS] commit_layer_adjacency: {len(targets)} file(s) clean ({mode})")


if __name__ == "__main__":
    main()
