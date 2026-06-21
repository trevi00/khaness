---
description: Route a prompt to an external AI provider (claude or codex) via lib/providers and persist the answer as an artifact.
user-invocable: true
argument-hint: "<claude|codex> <prompt>"
allowed-tools: Read, Write, Bash, Grep, Glob
category: external-ai
mutates: yes
long-running: no
external-deps: claude-cli, codex-cli
---

You are executing the **harness-ask** skill — a single-shot query to a named external AI provider, no debate, no loop.

## Inputs
Argument format: `<provider> <prompt>`.
- `provider`: one of `claude` or `codex` (or the canonical `anthropic`/`openai`).
  `gemini`/`google` are reserved aliases but the underlying provider is not
  implemented (`lib/providers/__init__.py` REGISTRY comments them out) — pass
  one of these to get an early `ProviderUnavailableError`.
- `prompt`: everything after the provider token.

If the argument is empty or provider is missing, ask the user once and stop.

## Protocol

1. **Resolve provider**:
   ```python
   from lib.providers import get_provider
   p = get_provider(<provider>)
   if not p.is_available():
       # Stop and tell the user how to install (CLI or SDK). Do not fall back silently.
   ```

2. **Ask**:
   ```python
   from lib.providers import AskRequest
   resp = p.ask(AskRequest(prompt="<prompt>"))
   ```

3. **Persist artifact**:
   - Path: `<CLAUDE_HOME>/state/ask/<provider>-<unix_ts>-<slug>.md`
   - Content: YAML frontmatter (provider, model, timestamp, token counts if present) + body = response text.
   - Create parent dir if absent.

4. **Report to user**:
   - Echo the response text.
   - Include artifact path as a footnote.
   - Include tokens_in/out if returned.

## Non-Goals
- No agent spawning (this is Q&A, not orchestration).
- No retry on parse failure — raw text is the deliverable.
- No multi-provider fanout — use `/harness-debate` with external_jury for cross-vendor.

## Error handling
- `ProviderUnavailableError` → surface the error message and abort.
- Unknown provider name → list `lib.providers.list_aliases()` and abort.
- Network/timeout → exactly one retry, then abort with a concrete error.

## Output

- artifact: `$CLAUDE_HOME/state/ask/<provider>-<unix_ts>-<slug>.md` — frontmatter (provider, model, timestamp, token counts) + response text body.
- stdout: response text echoed to user; artifact path printed as footnote; tokens_in/out reported when provider returns them.
- status: `ok` (artifact written) | `provider_unavailable` (CLI/SDK missing) | `unknown_provider` | `network_failed_after_retry`.

## Failure behavior

- `ProviderUnavailableError` (preflight `is_available()` returns False): no artifact written, surface install hint from the provider adapter module (`lib/providers/<name>.py` header comment or its CLI install line) — `ProviderBase` exposes only `is_available()` and `ask()`, NOT `install_url()`. Abort with `provider_unavailable` status.
- Unknown provider name: list `lib.providers.list_aliases()` and abort with `unknown_provider`. No retry.
- Network/timeout during `p.ask()`: exactly one retry, then abort with `network_failed_after_retry`. Partial response (if any) is discarded; no artifact.
- `gemini`/`google` provider requested but commented out in REGISTRY: same as ProviderUnavailableError with hint pointing at `lib/providers/__init__.py:31-32` (the `# "google":` / `# "gemini":` commented entries).

## Gate summary

- preflight: provider name resolves via `lib.providers.get_provider`; `p.is_available()` returns True; prompt is non-empty.
- success criteria: response text echoed to user AND artifact written under `state/ask/`.
- abort triggers: missing provider arg, unknown alias, provider unavailable, two consecutive network failures.

## Boundary with other commands

- vs `harness-debate`: this is one-shot Q&A with a single provider; debate runs Planner/Critic/Architect convergence (3 actors × up to 4 generations) on a design decision.
- vs `harness-team`: this is `N=1`; team is `N=2..8` parallel workers on partitioned subtasks.
- vs `harness-interview`: this returns provider's raw answer once; interview iterates a Socratic Q&A loop until ambiguity is below threshold and emits a seed spec.
- vs `harness-ralph`: this never re-runs validators; ralph is verify→fix→re-verify persistence loop.
