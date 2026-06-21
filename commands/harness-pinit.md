---
description: 신규 프로젝트를 하네스 스킬 파이프라인을 통해 역추적해 분석하고 .claude/ 초기 설정을 제안한다. 빌드 파일 → 기술 스택 → 활성 스킬 → 검증 커버리지 → 누락 자산 순으로 보고서 생성.
user-invocable: true
argument-hint: "<프로젝트 경로 또는 . (현재 디렉토리)>"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
category: project
mutates: yes
long-running: no
external-deps: python-cli
---

You are running the **harness-pinit** workflow — reverse-engineering a target
project through the harness skill pipeline to bootstrap or audit its
`.claude/` setup.

## Inputs

Argument: project path. Examples:
- `.` — current working directory
- `/home/user/some-project`
- relative paths resolve against the parent shell cwd

If the argument is empty, ask the user for the path and stop.

## Protocol

1. **Run the analyzer** (read-only):
   ```bash
   cd ~/.claude/scripts && python -m cli.project_analyze --root <PATH>
   ```
   Capture stdout — it's a markdown report with 6 sections:
   1. Tech stack detection
   2. tech-stack.yaml (existing or suggested)
   3. Skill activations
   4. Validator coverage
   5. Missing harness assets
   6. Next steps

2. **Surface the report to the user** — render it directly. Do not summarize
   or compress it; the user should see the full table output.

3. **Offer follow-up actions** based on findings (do NOT execute without
   confirmation):
   - If `.claude/tech-stack.yaml` is missing → offer to write the suggested
     content to `<PATH>/.claude/tech-stack.yaml`.
   - If `convention.md`, `requirements/`, `changelog.md` are missing → offer
     to copy templates from `~/.claude/templates/` (or scaffold minimal
     placeholders).
   - If validator FAILs are real bugs (not "missing target") → list each
     `validator@subroot → tail` separately and ask which to fix.
   - If detected_stacks is empty → ask the user to confirm the language
     manually (analyzer may have missed an unusual build system).

4. **Skill graph cross-reference** (optional):
   If the user wants to know which skills are most relevant for this project:
   ```bash
   python -m cli.skill_graph --json | jq '.nodes[] | select(.subtree | startswith("typescript/"))'
   ```
   Filter the JSON graph by the active subtrees from step 1.

5. **Confirm + commit** (only if the user asks to apply changes):
   - Write requested files in the target project (NOT in `~/.claude/`).
   - Run `cli.validate_project --root <PATH>` again to confirm coverage
     improved.
   - Do NOT commit on the user's behalf — they handle their own VCS.

## Output schema (mandatory — print as the FIRST visible message)

The orchestrator must surface the analyzer's full markdown output before
adding any commentary. Do not paraphrase the tables.

After the report, append exactly this section:

```
## Suggested actions

[ ] Write .claude/tech-stack.yaml (if missing)
[ ] Author .claude/convention.md (if missing)
[ ] Scaffold .claude/requirements/ (if missing)
[ ] Resolve N validator FAILs (if any)
[ ] Re-run `python -m cli.project_analyze --root <PATH>` to confirm

Tell me which to apply and I'll proceed.
```

## Non-Goals

- Do NOT modify the target project without explicit user approval.
- Do NOT push to the user's project repo.
- Do NOT alter `~/.claude/` skills based on a single project's findings —
  that's `harness-trigger-summary` / `harness-audit` territory.
- Do NOT run pip install / npm install / etc. inside the target project.

## Error handling

- Path doesn't exist → prompt user for a valid path.
- Permission denied on read → report which file, suggest manual workaround.
- Analyzer crash → re-raise with traceback; do not silently produce empty
  report.

## Output

- analysis report (markdown, surfaced inline to user — 6 sections):
  1. Tech stack detection (per subroot, confidence + source files)
  2. tech-stack.yaml (existing or suggested)
  3. Skill activations (filtered to existing subtrees)
  4. Validator coverage (via cli.validate_project)
  5. Reverse-engineered drafts (P1 extractor previews — convention/er/logical)
  6. Missing harness assets + Next steps
- artifact: NONE by default (read-only analysis). `cli.project_analyze` writes nothing.
- status: `analysis_complete` (6 sections rendered) | `aborted_path_invalid` | `aborted_unsupported_stack` (no detector matched).

## Failure behavior

- **path doesn't exist OR not a directory**: abort with `aborted_path_invalid` + sample valid paths. No writes attempted.
- **permission denied on read**: report exact file/dir + suggest manual workaround. Skip that path; continue analysis on the rest.
- **no detector matches** (no build.gradle / package.json / pubspec.yaml / etc.): abort with `aborted_unsupported_stack` + list of recognized build files.
- **analyzer crash**: re-raise with traceback (no silent empty report). User can re-run after fix.
- **mutation contract** (Round-3 P0 #7 fix): pinit ITSELF is read-only — `cli.project_analyze` never writes. The command markdown's "Confirm + commit" section refers to follow-up actions the user explicitly approves; bootstrap writes (creating `<root>/.claude/tech-stack.yaml`) require explicit `--write` confirmation per asset, not pinit's default.

## Gate summary

- preflight: target path exists + readable; CLAUDE_HOME/skills/ exists (for activation matching); python lib.tech_stack importable.
- success criteria: 6 analysis sections rendered to user.
- abort triggers: path invalid; analyzer crashes; user interrupt.

## Boundary with other commands

- vs `harness-reverse-prd`: pinit is read-only analysis of EXISTING `.claude/` setup (분석); reverse-prd creates a NEW sibling repo with PRD + study folders (역설계 산출).
- vs `harness-skill`: pinit suggests which skill subtrees activate; harness-skill manages the skill files themselves.
- vs `harness-audit`: pinit targets a project directory; audit targets the harness itself (`~/.claude/`).
- vs `kha-new-project`: pinit analyzes existing project; kha-new-project bootstraps a fresh `.planning/` from scratch.
