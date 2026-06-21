---
description: 같은 작업을 4-8명에게 병렬로 검토시키고 싶을 때. N명의 외부 AI(claude/codex/gemini)에게 파일/모듈을 잘라 분배 → 자동 2x2 psmux 화면 + 워커별 JSONL heartbeat로 진행상황 실시간 가시화. 단일 답이 아닌 다관점 검토 결과가 필요할 때 선택.
user-invocable: true
argument-hint: "<N>:<provider> <task description>"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate
category: external-ai
mutates: yes
long-running: yes
external-deps: claude-cli, codex-cli, psmux
---

You are orchestrating the **harness-team** skill — N parallel worker CLIs working on a partitioned review task.

## Inputs
Argument format: `<N>:<provider> <task>` (e.g. `3:codex review auth module`).
- `N`: 1–8 (enforced). Over 8 requires explicit user confirmation.
- `provider`: `claude` | `codex` | `gemini` (what CLI each worker runs).
- `task`: the shared goal.

## Protocol (W21 — fixplan-meta R2 visibility upgrade)

1. **Decompose** into subtasks (file-scoped or module-scoped). Call `TaskCreate`
   per subtask; pre-assign `owner` to avoid races.

2. **Pick multiplexer**:
   ```python
   from lib.workers import detect_best
   mpx = detect_best()  # psmux_adapter > subprocess_fallback
   ```
   Log the chosen backend to the user.

3. **Spawn N workers** under `~/.omc/team/team-<unix_ts>/`:
   - `worker-<i>.md` — instruction prompt (read-only, written by orchestrator)
   - `worker-<i>.out` — full transcript: provider CLI stdout+stderr (append)
   - `worker-<i>.heartbeat.jsonl` — structured progress, one JSON object per
     event: `{"ts","event","worker","out_bytes","note"}` where event ∈
     `{start, heartbeat, end}`. Heartbeat fires every 30s with the current
     `wc -c` of `worker-<i>.out`.
   - Wrapper script `run-worker.sh` invokes the provider CLI with
     `--skip-git-repo-check` (codex) / equivalent and emits the heartbeat
     JSONL alongside the transcript.
   - Detached launch via `nohup bash run-worker.sh <i> &; disown`.
   - **Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: immediately after each worker's detached launch returns control, the orchestrator calls `lib.subagent_invocation_log.record_invocation(<team_sid_or_orch_sid>, agent_name=f"team-worker-{i}-{provider}", tools=["external-cli"], generation=0, role="team-worker", extra={"provider": provider, "subtask": "<area or file scope>", "session_dir": "<absolute path>", "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. Use `orch_sid` when invoked from an autopilot super-session (`ORCH_SID` env present); otherwise fall back to the team session id (`team-<unix_ts>`). The cross-session grep target lets operators answer "who invoked codex on the auth-module review last week?" without scanning every team-session dir.

4. **Mount view session** (two complementary options — surface BOTH to the user):

   **(a) psmux 4-pane** (legacy, requires psmux):
   - Create `view-setup.sh` that builds psmux session `team-<sid>-view` with
     a tiled 4-pane layout, each pane running `tail -f worker-<i>.out`.
   - Print `psmux attach -t team-<sid>-view`.

   **(b) integrated TUI** (preferred, single window, ASCII-safe):
   - `python -m cli.team_watch <sid>` opens a live rich TUI dashboard with
     per-worker status badges (DONE / RUNNING / IDLE / FAILED), color-coded
     log tail (12 lines), and aggregate elapsed/counts header. Auto-detects
     the latest session if `<sid>` is omitted.
   - `--once` mode renders one frame and exits (CI / snapshot).
   - `--exit-on-done` exits when all workers reach a terminal state.
   - Print the command **prominently**: `cd ~/.claude/scripts && python -m cli.team_watch <sid>`.

   Best-effort hint: if `$WT_SESSION` (Windows Terminal) is set, suggest
   opening a new tab; otherwise direct the user to a fresh terminal.

5. **Monitor** (M28 — deterministic policy consumer, prose→deterministic):
   - Watcher script polls `worker-<i>.out` tail for `^DONE$` marker every 30s.
   - Background task notifies the orchestrator via task-notification on
     completion. Hard cap 40 min (override via `--deadline` arg).
   - **Stall + kill decision is NOT eyeballed** — every monitor tick invokes the
     deterministic consumer ONCE (mirrors harness-debate.md step-4's
     `debate_converge_check` wiring):

     ```bash
     cd ~/.claude/scripts && python -m cli.team_policy_check \
       --session-id "<team_sid_or_ORCH_SID>" \
       --team-dir "<absolute path to ~/.omc/team/<sid>>" \
       --stall-seconds 120
     ```

     The CLI owns the loop-control mutation (terminate + the single
     `state/team/<sid>/events.jsonl` append) so this markdown step cannot silently
     skip it. Branch mechanically on the exit code:

     | exit | meaning | orchestrator action |
     |------|---------|---------------------|
     | 0 | no-op (all progressing/terminal) | continue monitoring |
     | 3 | acted — killed ≥1 stalled worker, quorum still reachable | continue; note killed worker(s) in aggregation |
     | 4 | skipped-for-safety (fail-CLOSED: unknown/unreadable worker) | retry next tick; do NOT kill |
     | 5 | escalate-HALT — a stalled worker is load-bearing for quorum | **stop**, surface to user (do NOT kill below quorum) |

   - **Decision rules** (deterministic, in `lib.team_policy`):
     - **D1 stall**: PRIMARY = growth in `worker-<i>.out` bytes OR
       `worker-<i>.heartbeat.jsonl` `out_bytes`; mailbox depth supplementary (OR,
       never sole); pane-hash corroboration (may VETO a stall, never trigger one).
       Stalled ⇔ alive AND every live signal flat AND ≥ `--stall-seconds`.
       Watermark sidecar freezes `last_progress_ts` on flat cycles; read fault →
       never kill. (Replaces the bare "flat heartbeat ≥120s = flag" heuristic.)
     - **D2 kill guard**: kill ⇔ `responded_count + survivors_after_kill ≥
       frozen_quorum_threshold` (denominator FROZEN at the initial N). A kill that
       would drop the team below quorum is refused → exit 5 escalate. The kill
       stays inside the quorum the operator authorized at launch — **no operator
       gate** (loop-control only).
     - **D3 aggregate** (§6 Completion): `lib.team_policy.aggregate_quorum(results,
       frozen_denominator=N)` — split/unreachable → escalate.

6. **Completion**:
   - All `worker-<i>.out` end with `DONE` marker → aggregate.
   - Read each worker's final `# worker-N <area> 결과` section (the LAST
     occurrence; earlier ones are echoed prompt).
   - Synthesize cross-worker findings.

## Output schema (mandatory — orchestrator must follow)

The wrapper script `run-worker.sh` MUST be:

```bash
#!/usr/bin/env bash
set -u
N="${1:?worker number required}"
DIR="<absolute path to ~/.omc/team/<sid>>"
PROMPT="$DIR/worker-$N.md"
OUT="$DIR/worker-$N.out"
HB="$DIR/worker-$N.heartbeat.jsonl"

emit_hb() {
  printf '{"ts":"%s","event":"%s","worker":%s,"out_bytes":%s,"note":"%s"}\n' \
    "$(date -Iseconds)" "$1" "$N" "$(stat -c%s "$OUT" 2>/dev/null || echo 0)" "$2" >> "$HB"
}

emit_hb start ""
echo "[start] worker-$N $(date -Iseconds)" > "$OUT"

# Background heartbeat loop (kills itself when main worker exits)
(
  while kill -0 $$ 2>/dev/null; do
    sleep 30
    emit_hb heartbeat ""
  done
) &
HB_PID=$!

# W19.1.1+ Mailbox inbox poll loop (active only when orchestrator passes ORCH_SID)
# When standalone /harness-team (no ORCH_SID set), this block no-ops.
INBOX_PID=""
if [ -n "${ORCH_SID:-}" ]; then
  (
    while kill -0 $$ 2>/dev/null; do
      sleep 5
      python -m lib.team_mailbox tail "$ORCH_SID" "worker-$N" inbox 2>/dev/null \
        | while IFS= read -r MSG; do
            # Append inbox messages to a per-worker .inbox-tail.log so the
            # provider CLI prompt can include the latest queries/tasks via
            # `cat worker-$N.inbox-tail.log` injection on next prompt iter.
            printf '%s\n' "$MSG" >> "$DIR/worker-$N.inbox-tail.log"
          done
    done
  ) &
  INBOX_PID=$!
fi

<provider CLI command> < "$PROMPT" >> "$OUT" 2>&1
RC=$?

kill "$HB_PID" 2>/dev/null
[ -n "$INBOX_PID" ] && kill "$INBOX_PID" 2>/dev/null
echo "[end] worker-$N rc=$RC $(date -Iseconds)" >> "$OUT"
echo "DONE" >> "$OUT"
emit_hb end "rc=$RC"
```

When `ORCH_SID` env var is set (autopilot super-session passes it), the
worker tails `state/team/<ORCH_SID>/mailbox/worker-<i>.inbox.jsonl` every
5s and accumulates new envelopes to `worker-<i>.inbox-tail.log` (one JSON
per line). Provider CLI prompts can include `cat worker-<i>.inbox-tail.log`
in their next iteration to pick up routed queries.

Worker outbox writes (worker → orchestrator) go through
`python -m lib.team_mailbox send <orch_sid> worker-<i> outbox <type> <json_payload>`
invoked from the provider's tool surface (worker is a CLI agent — it
runs Bash, so it can call the harness lib directly).

This contract makes the heartbeat JSONL a **first-class artifact** that the
orchestrator and user can both consume. Plain stdout transcript is preserved
for human reading (tailed by the view).

## Mailbox protocol (W19.1.1+, Phase 3 of autonomous orchestrator)

When the team is invoked by `/harness-autopilot` super-session (NOT
standalone), each worker gets a JSON message bus alongside its transcript:

- `state/team/<sid>/mailbox/worker-<i>.inbox.jsonl` — orchestrator → worker
- `state/team/<sid>/mailbox/worker-<i>.outbox.jsonl` — worker → orchestrator

Schema (envelope per line, `lib/team_mailbox.envelope()` builder enforces):
```json
{"ts": "...", "from": "orch|worker-N", "to": "...", "type": "task|query|answer|done|error", "payload": {...}}
```

Worker prompt template (when mailbox active) MUST include:
1. **Poll inbox**: `python -m lib.team_mailbox tail <sid> worker-<i> inbox`
   yields new envelopes since last cursor read, advances cursor. Implement
   as 5s sleep loop in worker wrapper.
2. **Emit outbox**: when worker needs cross-worker info OR completes a
   sub-task, write a `query` or `done` envelope to its outbox.
3. **Routing**: orchestrator tails all `worker-<i>.outbox.jsonl`; on
   `query` envelope, finds the addressed worker and forwards to that
   worker's inbox.

Standalone `/harness-team` (no autopilot super-session) does NOT use
mailbox — workers run autonomous from prompt file as before. Mailbox
activation is signaled by `--sid <orch-sid>` argument from autopilot.

## Git-flow merge (W19.1.1+, Phase 3 deferred — design locked)

When workers each work on their own branch (`team-<sid>/worker-<i>`), the
orchestrator finalizes via `harness-git-master`:

- F4 = `cherry_pick_sequential` (debate-1778161608-713bdc gen 4 lock).
- All workers DONE → orchestrator: spawns
  `Agent(subagent_type="harness-git-master", prompt="<integration spec>")`.
- git-master creates integration branch, sequentially `git cherry-pick
  <worker_head>` in deterministic worker_id order (1, 2, 3, ...), halting
  on first conflict for user resolution.
- Linear history preserved (no merge commits, no rebase rewrite of worker
  branches). Worker branches stay intact for post-hoc inspection.
- Phase 3 revisit clause: this default is locked for MVP only.
  `/harness-debate "git-flow merge strategy"` MUST re-open this decision
  before squash-merge or rebase-merge can be adopted.

## Non-Goals
- No TeamCreate/TeamDelete API (OMC-specific). File-based state only.
- No persistent workers across sessions — one team per invocation.
- No LLM orchestration layer between lead and workers — workers are
  autonomous from their prompt file.

## Error handling
- `WorkerUnavailableError` at spawn → report which multiplexer failed,
  suggest `winget install psmux` if Windows + psmux absent.
- N > 8 without confirmation → abort and prompt the user.
- Heartbeat flat ≥120s on a worker → `cli.team_policy_check` (§5 D1) classifies
  it `stalled` only when ALSO alive AND every live signal flat (codex exec on
  xhigh reasoning legitimately spends minutes silent — the AND-combiner + pane
  veto avoid false positives). A stalled worker is killed ONLY if the D2 quorum
  guard holds; otherwise the worker is kept and the pass escalates (exit 5).
- All workers dead mid-session → `kill_session` + report last known state.

## Visibility checklist (worker-4 R2 HIGH)
- ✓ JSONL heartbeat per worker (structured, machine-readable)
- ✓ 2×2 view session auto-built at launch
- ✓ Attach command surfaced prominently in user response
- ✓ Hardcap deadline visible to user
- ✓ Final aggregation always reports artifact paths

## Output

- session dir: `~/.omc/team/team-<unix_ts>/` (created at launch).
- per-worker artifacts:
  - `worker-<i>.md` — instruction prompt (read-only after spawn).
  - `worker-<i>.out` — full stdout+stderr transcript (append-only).
  - `worker-<i>.heartbeat.jsonl` — `{ts, event, worker, out_bytes, note}` per line; events ∈ `{start, heartbeat, end}`.
- session scripts: `run-worker.sh`, `launch-all.sh`, `view-setup.sh` (psmux 4-pane).
- aggregate: orchestrator final response includes per-worker last-section synthesis + artifact paths.
- status: `all_done` (all DONE markers present) | `partial` (some FAIL/missing) | `stalled` (heartbeat flat ≥120s + alive + all signals flat — `cli.team_policy_check` D1; quorum-guarded auto-kill via D2, else escalate exit 5) | `hard_cap` (deadline reached).

## Failure behavior

- **provider CLI missing** (codex/claude/gemini binary not on PATH): preflight `command -v <cli>` fails → abort BEFORE creating session dir, surface install hint (`gemini` is reserved alias but unimplemented in `lib.providers` REGISTRY — recommend `claude` or `codex`).
- **psmux missing** (Windows): fall back to `subprocess_fallback` adapter via `lib.workers.detect_best`. Surface `winget install psmux` hint as advisory.
- **N > 8 without explicit user confirmation**: abort and prompt.
- **worker dies mid-run** (process exits before DONE marker): leave artifact in place, mark worker as `failed`, continue monitoring siblings. Final aggregation marks the session `partial` and lists dead worker(s).
- **all workers dead simultaneously**: `mpx.kill_session(session)`, report last known JSONL state per worker.
- **heartbeat flat ≥120s** on one worker: `cli.team_policy_check` (§5) decides deterministically — `stalled` requires alive AND all live signals flat (codex/claude on high reasoning effort legitimately spends minutes silent, so the AND-combiner + pane-hash veto guard against false positives). Auto-kill is QUORUM-GUARDED (D2): a kill that would break quorum is refused and escalated (exit 5) instead.
- **hard cap (40 min default)**: monitor stops, sends user the partial aggregation. Workers continue in background; user can recheck via `cli.team_watch <sid>`.

## Gate summary

- preflight: provider CLI on PATH (`command -v claude/codex`); N within `1..8` (or explicit user override); session dir creatable; multiplexer detected (`psmux_adapter` ≻ `subprocess_fallback`).
- success criteria: all `worker-<i>.out` files end with literal `DONE` line; aggregator can extract each worker's final `# worker-N <area> 결과` section.
- abort triggers: provider CLI absent at preflight; N > 8 without confirmation; user interrupt; all workers dead with no partial output.

## Retry / Resume

- checkpoint: per-worker `worker-<i>.heartbeat.jsonl` (start/heartbeat/end events) + `worker-<i>.out` byte count → can derive completion state without re-running.
- resume command: `cd ~/.claude/scripts && python -m cli.team_watch <sid>` re-attaches the live dashboard against an in-flight or finished session. Re-running the orchestrator on the same `<sid>` is NOT idempotent — workers are spawned per invocation; instead use `team_watch` to inspect state.
- idempotent: NO — each `harness-team` invocation creates a new `team-<ts>/` dir. To re-attempt with same prompt, manually copy `worker-<i>.md` files into a new session.
- stall detection: heartbeat JSONL `event=heartbeat` fires every 30s with current `out_bytes`. `cli.team_policy_check` (§5, `lib.team_policy.evaluate_stall`) consumes it deterministically — a flat heartbeat + flat `.out` bytes for ≥`--stall-seconds` while alive ⇒ `stalled`. Kill is quorum-guarded (D2), not advisory-only; a kill that would break the frozen-N quorum escalates (exit 5) instead.

## Boundary with other commands

- vs `harness-ask`: this is `N=2..8` parallel workers on partitioned subtasks; ask is `N=1` single-shot Q&A.
- vs `harness-debate`: this fans out the SAME task to multiple AI providers/perspectives; debate runs Planner/Critic/Architect roles for convergence on a single decision.
- vs `harness-ultrawork`: this runs N **external AI CLI** workers (claude/codex), each autonomous from a prompt file; ultrawork runs internal `Agent` tool subagents in parallel waves with dependency graph.
- vs `harness-ralph`: this is one-shot fan-out, no validator loop; ralph is verify→fix→re-verify persistence loop on local code.
