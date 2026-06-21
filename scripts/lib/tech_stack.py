"""tech-stack.yaml loader — minimal YAML parser (no PyYAML dependency).

Returns the list of active skill-tree paths (e.g. ['_common', 'java/springboot-3.2']).
Shared by skill matching and pipeline-stage detection.

Two schemas are recognized:

1. **Flat** (CLAUDE.md spec — single-stack project):

   ```yaml
   stack:
     language: java
     framework: springboot
     version: "3.2"
   extensions:
     - flutter/example_app-agent
   ```

2. **Nested** (multi-stack monorepo — e.g. Spring Boot backend + React frontend):

   ```yaml
   backend:
     language: java
     framework: springboot
     version: "3.2"
   frontend:
     language: typescript
     framework: react
     version: "18"
   mobile:
     language: kotlin
     framework: android
   ```

For each block with a `language` field, the parser emits candidate skill
paths (most-specific to least-specific). The consumer (`collect_skill_files`
in `handlers/prompt/skill_match.py`) does `os.path.isdir` on each candidate,
so non-existent paths (e.g. `typescript/react-18` when only `typescript/react`
exists) are filtered out naturally.
"""
from __future__ import annotations

from pathlib import Path

# Top-level blocks scanned for {language, framework, version}. Order is
# preserved in the returned list so backend skills appear before frontend
# in the matcher's candidate set.
_LANG_BLOCKS = ("stack", "backend", "frontend", "mobile")


def _candidate_paths(language: str, framework: str, version: str) -> list[str]:
    """Emit candidate skill-subtree paths from a (lang, framework, version) triple.

    Most-specific first. Consumer filters by directory existence.
    """
    out: list[str] = []
    if language and framework and version:
        out.append(f"{language}/{framework}-{version}")
    if language and framework:
        out.append(f"{language}/{framework}")
    if language and version:
        out.append(f"{language}/{version}")
        # major-only version (e.g. "5", "18") often has a "{N}.x" subtree
        # in our tree (typescript/5.x, kotlin/1.9.x). Add that variant too.
        if version.isdigit():
            out.append(f"{language}/{version}.x")
    if language:
        out.append(f"{language}/lang")
        out.append(language)
    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    return deduped


def _parse_yaml(content: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Tiny indent-based YAML parser. Returns (nested, lists).

    nested: dotted-key map ('block.field' → value)
    lists: top-level list keys ('extensions' → ['flutter/example_app-agent', ...])
    """
    nested: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    current_block = ""
    in_list_for: str | None = None

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        if stripped.startswith("- ") and in_list_for and indent > 0:
            item = stripped[2:].strip().strip('"').strip("'")
            if item:
                lists.setdefault(in_list_for, []).append(item)
            continue

        if ":" not in stripped:
            in_list_for = None
            continue

        key, val = stripped.split(":", 1)
        key = key.strip()
        val_stripped = val.strip()
        val_clean = val_stripped.strip('"').strip("'")

        if indent == 0:
            current_block = key
            if val_stripped.startswith("[") and val_stripped.endswith("]"):
                items = [
                    v.strip().strip('"').strip("'")
                    for v in val_stripped[1:-1].split(",")
                ]
                lists[key] = [v for v in items if v]
                in_list_for = None
            elif val_stripped == "":
                in_list_for = key
            else:
                nested[key] = val_clean
                in_list_for = None
        else:
            if val_clean:
                nested[f"{current_block}.{key}"] = val_clean

    return nested, lists


def load_tech_stack(cwd: str | Path | None) -> list[str] | None:
    """Read `{cwd}/.claude/tech-stack.yaml` and return active skill paths.

    Returns None when the file is missing or resolves nothing, so the caller
    falls back to scanning every skill subtree (legacy behavior).

    Multi-stack projects (backend + frontend + mobile blocks) get all of their
    candidates merged. `extensions:` list is appended last for project-specific
    subtree opt-in.
    """
    if not cwd:
        return None
    path = Path(cwd) / ".claude" / "tech-stack.yaml"
    if not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    nested, lists = _parse_yaml(content)

    active: list[str] = ["_common"]
    for block in _LANG_BLOCKS:
        language = nested.get(f"{block}.language", "")
        framework = nested.get(f"{block}.framework", "")
        version = nested.get(f"{block}.version", "")
        if not language:
            continue
        for cand in _candidate_paths(language, framework, version):
            if cand not in active:
                active.append(cand)

    for ext in lists.get("extensions", []):
        if ext and ext not in active:
            active.append(ext)

    return active if len(active) > 1 else None


def read_language(cwd: str | Path | None) -> str | None:
    """Convenience accessor — returns the **first** language found across blocks.

    Used by pipeline-stage detection to pick a language-specific stages.yaml
    variant (currently only `flutter` exists). Multi-stack projects get the
    backend language by `_LANG_BLOCKS` order (`stack` > `backend` > `frontend` > `mobile`).
    """
    if not cwd:
        return None
    path = Path(cwd) / ".claude" / "tech-stack.yaml"
    if not path.is_file():
        return None
    try:
        nested, _ = _parse_yaml(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    for block in _LANG_BLOCKS:
        v = nested.get(f"{block}.language")
        if v:
            return v
    return None
