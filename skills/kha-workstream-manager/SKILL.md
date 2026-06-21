---
name: kha-workstream-manager
description: "Manage parallel workstreams — list, create, switch, status, progress, complete, and resume"
allowed-tools:
  - Read
  - Bash
category: meta
mutates: yes
long-running: no
---
# /kha-workstream-manager

Manage parallel workstreams for concurrent milestone work.

## Usage

`/kha-workstream-manager [subcommand] [args]`

### Subcommands

| Command | Description |
|---------|-------------|
| `list` | List all workstreams with status |
| `create <name>` | Create a new workstream |
| `status <name>` | Detailed status for one workstream |
| `switch <name>` | Set active workstream |
| `progress` | Progress summary across all workstreams |
| `complete <name>` | Archive a completed workstream |
| `resume <name>` | Resume work in a workstream |

## Step 1: Parse Subcommand

Parse the user's input to determine which workstream operation to perform.
If no subcommand given, default to `list`.

## Step 2: Execute Operation

### list
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream list --raw --cwd "$CWD"`
Display the workstreams in a table format showing name, status, current phase, and progress.

### create
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream create <name> --raw --cwd "$CWD"`
After creation, display the new workstream path and suggest next steps:
- `/kha-new-milestone --ws <name>` to set up the milestone

### status
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream status <name> --raw --cwd "$CWD"`
Display detailed phase breakdown and state information.

### switch
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream set <name> --raw --cwd "$CWD"`
Also set `GSD_WORKSTREAM` for the current session when the runtime supports it.
If the runtime exposes a session identifier, GSD also stores the active workstream
session-locally so concurrent sessions do not overwrite each other.

### progress
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream progress --raw --cwd "$CWD"`
Display a progress overview across all workstreams.

### complete
Run: `node "$HOME/.claude/get-shit-done/bin/gsd-tools.cjs" workstream complete <name> --raw --cwd "$CWD"`
Archive the workstream to milestones/.

### resume
Set the workstream as active and suggest `/kha-resume-work --ws <name>`.

## Step 3: Display Results

Format the JSON output from gsd-tools into a human-readable display.
Include the `${GSD_WS}` flag in any routing suggestions.

## Output


- artifacts: inline list/status/progress views; on mutation, creation of `.planning/workstreams/<name>/` with `STATE.md` and `phases/`, active-workstream pointer changes, or archival under `.planning/milestones/ws-<name>-<date>/`.
- status: `workstreams_listed` | `workstream_created` | `workstream_switched` | `workstream_completed` | `active_workstream_cleared`.

## Failure behavior


- preflight: reject unknown subcommands, invalid names, or missing required workstream names before mutation.
- execution: creation can fail on migration, switching can fail on `not_found`, and completion can fail on archive errors; keep current workstream state intact when those failures happen.
- partial: if archive fails during completion, restore moved files when possible and report the remaining active/archive state explicitly.

## Gate summary


- preflight: `.planning/` exists; current mode (`flat` vs `workstream`) and active pointer are known before mutating subcommands.
- success: dry-run preview must show current active workstream plus target lifecycle action; snapshot is current `workstream list/status/get` state; explicit confirmation is required before `create`, `switch/clear`, or `complete`.
- boundary: own parallel workstream lifecycle inside one project repo; `kha-milestone-manager` orchestrates phases inside the active workstream/milestone; `kha-list-workspaces` lists external multi-repo workspace folders and does not touch `.planning/workstreams/`.

=== worker-4 meta/infra/docs 완료 ===

## 3쌍 boundary 정리
- `kha-settings` vs `kha-set-model-profile` vs `kha-user-profile`: `kha-settings`는 전체 workflow toggle과 defaults 저장을 다루는 interactive config surface다. `kha-set-model-profile`는 quality/balanced/budget/inherit 계열의 agent routing profile fast-path다. `kha-user-profile`는 세션 분석으로 `USER-PROFILE.md`와 개인화 artifact를 만드는 behavioral profile surface다.
- `kha-intel-index` vs `kha-scan-codebase` vs `kha-map-codebase`: `kha-intel-index`는 `.planning/intel/`의 증분형 machine-readable store를 다루고, `kha-scan-codebase`는 한 focus에 대한 짧고 얕은 targeted scan이며, `kha-map-codebase`는 7문서 세트의 길고 깊은 narrative map이다.
- `kha-milestone-manager` vs `kha-list-workspaces` vs `kha-workstream-manager`: `kha-milestone-manager`는 milestone 안의 여러 phase를 interactive하게 orchestration하는 command center다. `kha-list-workspaces`는 `~/gsd-workspaces/`를 읽기 전용으로 나열한다. `kha-workstream-manager`는 `.planning/workstreams/`의 create/switch/status/progress/complete lifecycle을 관리한다.

## destructive 스킬 stability 규약 적용 결과
- `kha-self-update`: dry-run은 installed/latest/changelog/install-scope preview, snapshot은 runtime target과 `gsd-local-patches/` backup, confirm은 explicit proceed gate로 정의했다.
- `kha-sync-docs`: dry-run은 queue/mode/path preview, snapshot은 `.planning/tmp/docs-work-manifest.json` 및 `verify-*.json`, confirm은 generation proceed와 secret-scan commit gate로 정의했다.
- `kha-milestone-manager`: dry-run은 dashboard와 compound action preview, snapshot은 현재 disk state로 재구성한 phase table, confirm은 action selection before dispatch로 정의했다.
- `kha-remove-workspace`: dry-run은 workspace path/strategy/repo/dirty-state preview, snapshot은 init remove-workspace result, confirm은 typed-name confirmation으로 정의했다.
- `kha-workstream-manager`: dry-run은 current active/mode/target preview, snapshot은 `workstream list/status/get` 상태, confirm은 create/switch/complete 전 gate로 정의했다.
- `kha-intel-index`: dry-run은 `status`/`diff` 기반 rebuild preview, snapshot은 refresh 전 intel freshness/diff state, confirm은 explicit refresh approval로 정의했다.

## 협의 필요
- frontmatter `mutates` 불일치가 보인다: `kha-map-codebase`, `kha-scan-codebase`, `kha-milestone-summary`, `kha-session-report`는 현재 `mutates: no`인데 workflow는 파일 쓰기까지 수행한다.
- frontmatter `long-running` 불일치가 보인다: 요청 기준 long-running 대상인 `kha-self-update`, `kha-sync-docs`는 현재 `long-running: no`다.
- `kha-intel-index`는 prompt 내부 산출물 이름과 실제 `bin/lib/intel.cjs` 구현이 다르다. prompt는 `api-map.json`/`dependency-graph.json`/`file-roles.json`/`arch-decisions.json`을 말하지만 실제 구현은 `files.json`/`apis.json`/`deps.json`/`stack.json`/`arch.md`다.
- `kha-intel-index`의 “machine-readable `.json` only” 경계와 실제 `arch.md` 구현도 충돌한다.
- model profile 범위도 한 번 정리해야 한다: `kha-set-model-profile` argument-hint는 `quality|balanced|budget|inherit`인데, `model-profiles.md`와 `settings.md` 내부 schema는 `adaptive`까지 언급한다.
[end] worker-4 rc=0 2026-04-30T10:11:02+09:00
DONE
