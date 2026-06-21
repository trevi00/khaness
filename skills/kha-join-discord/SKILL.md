---
name: kha-join-discord
description: "Join the GSD Discord community"
category: meta
mutates: no
long-running: no
---
<objective>
Display the Discord invite link for the GSD community server.
</objective>

<output>
# Join the GSD Discord

Connect with other GSD users, get help, share what you're building, and stay updated.

**Invite link:** https://discord.gg/mYgfVNfA2r

Click the link or paste it into your browser to join.
</output>

## Output


- artifacts: inline GSD Discord invite message with the static invite URL; no file writes.
- status: `invite_emitted`.

## Failure behavior


- preflight: none beyond the static skill body being available.
- execution: none; this is a fixed informational response.
- partial: not applicable.

## Gate summary


- preflight: skill body is readable.
- success: the invite block is shown exactly once with no side effects.
