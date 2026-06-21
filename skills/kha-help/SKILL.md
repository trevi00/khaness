---
name: kha-help
description: "Show available GSD commands and usage guide"
allowed-tools:
  - Read
category: meta
mutates: no
long-running: no
---
<objective>
Display the complete GSD command reference.

Output ONLY the reference content below. Do NOT add:
- Project-specific analysis
- Git status or file context
- Next-step suggestions
- Any commentary beyond the reference
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/help.md
</execution_context>

<process>
Output the complete GSD command reference from @$HOME/.claude/get-shit-done/workflows/help.md.
Display the reference content directly — no additions or modifications.
</process>

## Output


- artifacts: inline emission of the GSD command reference from `workflows/help.md`; no file writes and no project-specific commentary.
- status: `reference_emitted`.

## Failure behavior


- preflight: if the help reference file is unreadable, abort without substitution text.
- execution: none; this command should be pure reference output.
- partial: not applicable.

## Gate summary


- preflight: help workflow file is readable.
- success: the reference body is emitted verbatim and nothing extra is appended.
