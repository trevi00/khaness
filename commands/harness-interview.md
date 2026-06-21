---
description: Socratic deep interview — iterate question-answer with the user until ambiguity is below threshold, then emit a seed spec ready for harness-debate or harness-autopilot.
user-invocable: true
argument-hint: "<topic>"
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, AskUserQuestion
category: clarify
mutates: yes
long-running: yes
external-deps: none
---

You are orchestrating **harness-interview** — ambiguity-gated requirement clarification. Inspired by Ouroboros' Socratic interviewer.

## Inputs
- `topic`: the subject to clarify. If empty, ask once for one sentence, then stop.

## Protocol

### 1. Initial assessment
Spawn `Agent(subagent_type="harness-analyst", prompt=<topic + "list missing questions, undefined guardrails, and unvalidated assumptions">)`.
Collect the gap list. (harness-analyst owns pre-planning gap surfacing per its
agent definition; harness-critic is reserved for attacking an existing
proposal, not for first-pass ambiguity scan.)

**Audit log (A2 wiring, commit 7aff8b7, 2026-05-10; E1 origin tag 2026-05-10)**: immediately after the Agent tool returns, call `lib.subagent_invocation_log.record_invocation(interview_sid, "harness-analyst", tools=lib.agent_tool_audit.expected_tools("harness-analyst"), generation=0, role="interview-analyst", extra={"topic": topic, "origin": lib.subagent_invocation_log.ORIGIN_DIRECTIVE})`. ``interview_sid`` = ``f"interview-{unix_ts}-{rand6}"`` minted at step 0; the same id is used for the answers.jsonl + seed.md filenames. PostToolUse hook (handlers/post_tool/agent_invocation_audit.py) records this dispatch automatically as well — the directive here is the contract; the hook is the safety net.

### 2. Ambiguity scoring (v15.39 — `lib.ambiguity_score` wired)

Initial scoring uses the empty Q&A history (round 1 has no answers yet). Invoke via Bash:

```bash
cd ~/.claude/scripts && python -c "
from lib.ambiguity_score import compute_ambiguity_score
import json, os
threshold = float(os.environ.get('AMBIGUITY_THRESHOLD', '0.2'))
topic = '''<topic argument>'''
score = compute_ambiguity_score(seed=topic, qa_pairs=[], threshold=threshold)
print(json.dumps({
    'aggregate': score.aggregate,
    'passes_gate': score.passes_gate,
    'coverage_gap': score.coverage_gap,
    'lexical_entropy': score.lexical_entropy,
    'unknown_marker_density': score.unknown_marker_density,
    'threshold': score.threshold,
}, indent=2))
"
```

**3-component scoring** (`lib.ambiguity_score`, v15.37 primitive):
- `coverage_gap` (weight 0.85) — 6W (who/what/when/where/why/how) bilingual EN/KO 미답변 비율. Dominant carrier (post-D1 substring-scan + post-D4 KO synonym 으로 accuracy 확보, debate-1779201365-66ff07 LOCK SHA f1ca724ecb06).
- `lexical_entropy` (weight 0.05) — normalized Shannon entropy on tokens. EN token uniqueness saturated noise floor (0.93-0.95 baseline), weight 축소.
- `unknown_marker_density` (weight 0.10) — TBD/?/may/might/어쩌면/추후 density. 50% of original — adversarial mar>0.5 region documented as KNOWN LIMITATION (out-of-scope for D2 design; no explicit downstream filter exists per C-LAND-4 investigation 2026-05-19, only Critic LLM judgment).

`aggregate = 0.85*gap + 0.05*entropy + 0.10*marker`, `passes_gate = aggregate <= threshold`.

**Target**: `passes_gate=True` (default threshold 0.2). Override via `AMBIGUITY_THRESHOLD` env (0.0–1.0 float).

Ad-hoc clarity weights (Goal 40% / Constraint 30% / Success 30%, `ambiguity = 1 - sum(clarity_i * weight_i)`) are kept as **fallback only** — used if `lib.ambiguity_score` import fails (defense-in-depth, should never trigger). Primary path is the Python call above.

If `passes_gate=True` at round 1 (topic is already concrete enough): skip to step 5 (seed) immediately, no Q&A needed.

### 3. Question round
For each unresolved point (up to 4 per round, never more):
- Use `AskUserQuestion` with:
  - A clear one-line question.
  - 2-4 options labeled concisely.
  - "Other" is added automatically by the tool.
- Record answers into `<CLAUDE_HOME>/state/interview/<unix_ts>/answers.jsonl`.

### 4. Re-score (v15.39)

After each question round, append answers to `answers.jsonl`, then re-compute via Python with the accumulated Q&A:

```bash
cd ~/.claude/scripts && python -c "
import json, os
from pathlib import Path
from lib.ambiguity_score import compute_ambiguity_score
from lib.paths import STATE_DIR

sid = '<interview_sid>'  # interview-<unix_ts>-<rand6> from step 1
threshold = float(os.environ.get('AMBIGUITY_THRESHOLD', '0.2'))
topic = '''<topic argument>'''

answers_path = STATE_DIR / 'interview' / sid / 'answers.jsonl'
qa_pairs = []
if answers_path.exists():
    for line in answers_path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        q = ev.get('question', '')
        a = ev.get('answer', '')
        if isinstance(q, str) and isinstance(a, str) and q and a:
            qa_pairs.append((q, a))

score = compute_ambiguity_score(seed=topic, qa_pairs=qa_pairs, threshold=threshold)
from lib.ambiguity_report import render_breakdown, component_breakdown
b = component_breakdown(score)
print(json.dumps({
    'aggregate': score.aggregate,
    'passes_gate': score.passes_gate,
    'qa_pair_count': len(qa_pairs),
    'dominant_axis': b['dominant_axis'],          # which axis drives the ambiguity
    'axes': {ax: a['contribution'] for ax, a in b['axes'].items()},
}, indent=2))
print(render_breakdown(score))                    # human-readable per-axis + focus hint
"
```

- `passes_gate=True` (aggregate <= threshold): go to step 5 (seed).
- Else: another question round (step 3). **Target your NEXT question at `dominant_axis`** — the
  per-component breakdown (`lib.ambiguity_report`) shows which axis (`coverage_gap` = missing
  6W, `lexical_entropy` = vague wording, `unknown_marker_density` = uncertainty tokens) is
  driving the ambiguity, so questioning is directed, not blind. Max 5 rounds total; after 5
  emit current seed with a warning.

**ambiguity_delta tracking**: each round records `(round_n_aggregate - round_{n-1}_aggregate)` into `answers.jsonl` for downstream telemetry. Monotonic decrease expected; non-decrease for 2 consecutive rounds → suggest escalation to `/harness-debate`.

### 5. Emit seed spec
Write `<CLAUDE_HOME>/state/interview/<unix_ts>/seed.md`:
- Goal (one paragraph)
- Constraints (bullet list)
- Success criteria (bullet list with concrete values — no "적절한/빠르게")
- Open questions (explicit, each tied to a re-check trigger)

### 6. Handoff
Suggest the next command:
- If the seed describes a design decision → `/harness-debate <one-line goal>`.
- If it describes buildable work → `/harness-autopilot <one-line goal>`.
- Otherwise let the user decide.

## Non-Goals
- No ontology graph (Ouroboros). We stop at a markdown seed.
- No auto-invocation of the next command — the user chooses.
- No free-text questions — always use `AskUserQuestion` so answers are structured.

## Error handling
- User gives "Other" answers that introduce new ambiguity → count as a new unresolved point for the next round.
- 5 rounds elapsed without convergence → emit seed + warning + recommend `/harness-debate` to settle remaining disputes.

## Output

- session dir: `state/interview/<sid>/` (canonical singular — matches `lib.ambiguity_score` docstring + `test_subagent_isolation_contract`).
- `answers.jsonl` — per-round `{question, answer, ambiguity_delta}` events.
- `seed.md` — final seed spec with frontmatter (`one_line_goal`, `concrete_anchor`, `recommended_next: harness-debate | harness-autopilot`).
- status: `seed_emitted` (ambiguity below threshold + seed.md written) | `aborted_no_topic` | `aborted_max_rounds` (8 rounds without convergence) | `user_quit`.

## Failure behavior

- **empty topic**: ask once for one-sentence topic, abort `aborted_no_topic` on second empty.
- **user quits mid-interview**: persist partial `answers.jsonl` + abort `user_quit`. No seed.md written.
- **max rounds (8) without ambiguity below threshold**: emit `seed.md` with `status=partial` flag + best-effort `one_line_goal` from accumulated answers; `aborted_max_rounds` status. User can refine and re-run or feed partial seed to debate.
- **handoff schema violation** (downstream `harness-debate` / `harness-autopilot` rejects seed): document the missing fields (`one_line_goal`, `concrete_anchor`, `recommended_next` are MANDATORY in seed.md) and re-run interview with focused topic.

## Gate summary

- preflight: topic argument non-empty after trim; `state/interview/` writable (canonical singular path).
- success criteria: `seed.md` written with all 3 mandatory fields populated AND ambiguity score below threshold (recovered from analyst agent's reported delta).
- abort triggers: empty topic; user quits; max round count reached.

## Retry / Resume

- checkpoint: `answers.jsonl` is per-round event log. Re-running interview with same topic mints new sid; manual resume = read prior `answers.jsonl`, supply already-answered context to current session.
- resume command: not first-class. Reuse pattern: `cat <prior>/answers.jsonl` → human edit → start fresh interview with synthesized prefix.
- idempotent: NO — questions are LLM-generated and adapt to prior answers.
- stall detection: round counter monotonic; per-round wall-clock advisory if user takes >5 min to answer (no auto-timeout).

## Boundary with other commands

- vs `harness-debate`: interview gathers context (questions to user); debate makes a decision (Planner/Critic/Architect among themselves).
- vs `harness-autopilot`: interview produces seed BEFORE autopilot consumes it. autopilot's preflight rejects vague goals → routes to interview.
- vs `harness-ask`: ask is single-shot Q&A with external AI; interview is multi-round Socratic with USER + internal harness-analyst agent.
- vs `kha-discuss-phase` (now `kha-clarify-phase`): kha-clarify-phase clarifies a SPECIFIC PRD phase context; interview clarifies an ambiguous TOPIC at any abstraction level.
