---
name: kha-explore-idea
description: "Socratic ideation and idea routing — think through ideas before committing to plans"
allowed-tools:
  - Read
  - Write
  - Bash
  - Grep
  - Glob
  - Task
  - AskUserQuestion
category: plan
mutates: yes
long-running: no
---
<objective>
Open-ended Socratic ideation session. Guides the developer through exploring an idea via
probing questions, optionally spawns research, then routes outputs to the appropriate GSD
artifacts (notes, todos, seeds, research questions, requirements, or new phases).

Accepts an optional topic argument: `/kha-explore-idea authentication strategy`
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/explore.md
</execution_context>

<process>
Execute the explore workflow from @$HOME/.claude/get-shit-done/workflows/explore.md end-to-end.
</process>

## Output


- artifact: only the outputs explicitly selected by the user are written, drawn from `.planning/notes/{slug}.md`, `.planning/todos/pending/{slug}.md`, `.planning/seeds/{slug}.md`, `.planning/research/questions.md`, `.planning/REQUIREMENTS.md`, or a routed new-phase command.
- status: `exploration_only` | `outputs_created` | `cancelled`

## Failure behavior


- preflight failure: none beyond obtaining a topic or opening question; no artifact is written until the user selects outputs.
- execution failure: optional research failure is non-fatal and exploration can continue; if some selected outputs are written before a later failure, preserve the created files and report exactly which destinations succeeded.

## Gate summary


- preflight: the Socratic session opens with a topic or a user prompt, and any optional research offer is contextual rather than forced.
- success criteria: the conversation reaches explicit capture suggestions, the user chooses which outputs to create, and only those selected artifacts are written and optionally committed.

