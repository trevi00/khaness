---
description: Manage skills in ~/.claude/skills/ — list, search, add, edit, remove. Respects tech-stack.yaml filtering and our skill-tree structure.
user-invocable: true
argument-hint: "<list|search|add|edit|remove> [args]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, AskUserQuestion
category: meta
mutates: yes
long-running: no
external-deps: git
---

You are executing **harness-skill** — a CLI-like manager for our skill tree.

## Skill tree layout (from CLAUDE.md, see `state/inventory.md` for live counts)
```
~/.claude/skills/
├── _common/                   # always active (37 skills, locked schema)
├── _pipeline/                 # stages.yaml + variants
├── gsd-*/                     # 68 GSD workflow skills (skills/gsd-*/ + skills/_gsd/* union, D6)
├── java/springboot-3.2/
├── kotlin/android/
├── typescript/react/
└── flutter/example_app-agent/      # project-specific subtree
```

New skills added by `add` go under `_common/` by default, or into a tech-stack subtree if `--stack <path>` is given.

## Subcommands

### list [--stack <path>]
- Use `Glob` for `skills/_common/*.md` + specified stack subtree.
- For each file, parse frontmatter via `lib.frontmatter.parse_frontmatter`.
- Display: name, description, keywords, intent, score/min_score, file path.
- Group by category (_common vs stack).

### search <keyword>
- Grep case-insensitively across `~/.claude/skills/**/*.md` frontmatter AND body.
- Rank by: (frontmatter match = 2 points, body match = 1 point, path match = 1 point).
- Show top 10 with path + 1-line description.

### add <name> [--stack <path>]
- If `name` missing, `AskUserQuestion` for it (validate: lowercase, hyphens, no spaces).
- Ask for: description (one line), keywords (space-separated), intent verbs, phase (`plan|implement|review|debug|deploy`), tech-stack (`any` or `<lang>` or `<lang>,<lang>`).
- Write `<skills_dir>/<name>.md` with a minimal SKILL template (locked schema per
  `skills/_common/_template.md`, fixplan-meta debate Gen4 W13):
  - Frontmatter (name, description, keywords, intent, paths, patterns, requires, phase, tech-stack, min_score=2)
  - `## 의사결정 트리`
  - `## Gotchas`
- Verify with `lib.frontmatter.parse_frontmatter` — abort if the written file does not parse.
- Verify name == file stem and `description` is non-empty.

### edit <name>
- Resolve `<name>` to a single file via Glob. If multiple matches, `AskUserQuestion` to pick.
- Open via `Read` then `Edit` for the section the user specifies.

### remove <name>
- Confirm with `AskUserQuestion` (destructive).
- Only allow within `~/.claude/skills/_common/` and user-writable stack trees.
- `git mv` to `skills/_archive/<name>-<unix_ts>.md` instead of hard-deleting (recoverable).

## Non-Goals
- No skill quality scoring (OMC's usage/quality stats) — we don't track usage yet.
- No auto-learning (that's `handlers/stop/learner.py`'s sensor role; promotion is manual via `add`).
- No project-level `.claude/skills/` scope — our design is user-level trees only.

## Error handling
- Frontmatter parse failure on `add` → delete the file and abort with the parser error.
- `remove` on built-in helper files (`_template.md`, `convention.md` core list) → refuse.
- Conflicting name with existing skill in a different stack → list both and require `--stack` to disambiguate.

## Output

- per-action artifacts:
  - `list` / `search`: markdown table of matched skills (no file write).
  - `add`: new `~/.claude/skills/<subtree>/<name>/SKILL.md` (or `<name>.md` for flat) with valid frontmatter.
  - `edit`: in-place modification of existing `SKILL.md`.
  - `remove`: deletion of skill dir/file (with confirmation).
- status: `listed` | `added` | `edited` | `removed` | `aborted_invalid_subtree` | `aborted_namespace_violation` | `aborted_path_conflict`.

## Failure behavior

- **invalid subtree** (e.g., not a real prefix): abort `aborted_invalid_subtree` + list valid subtrees from `state/inventory.md`.
- **namespace violation** (`skills/harness-*` blocked by `validators/skill_frontmatter.py`): abort `aborted_namespace_violation` — that prefix is reserved for `commands/`.
- **path conflict** (add/edit but path already exists with different content): refuse — surface diff, require explicit `--overwrite` flag.
- **frontmatter validation fail post-write** (W13 schema mismatch): rollback the file write; surface the validator error so user can fix and retry.
- **remove without confirm**: refuse — destructive action requires `--yes` flag.

## Gate summary

- preflight: action argument resolves to one of {list, search, add, edit, remove}; for add/edit/remove: target subtree + name resolve to a canonical path under `skills/`.
- success criteria: action completed AND `validators.skill_frontmatter --check` (full subtree) passes after.
- abort triggers: invalid action; namespace violation; path conflict without overwrite; remove without explicit confirm.

## Boundary with other commands

- vs `cli.kha_alias`: skill manages individual files (one at a time); kha_alias performs bulk gsd→kha rename mapping (one-shot bulk).
- vs `cli.kha_normalize`: skill creates/edits one skill; kha_normalize enforces frontmatter+sections across all 68 kha skills.
- vs `harness-extend`: extend designs new mechanisms (hook/MCP/lib); skill manages skill files specifically.
- vs `harness-pinit`: pinit suggests which subtrees activate for a project; skill is the CRUD surface for editing the actual skill files.
