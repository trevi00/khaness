# Contributing

Thanks for considering a contribution. This harness values **small, verified changes** over large unverified ones.

## Setup

```bash
git clone <your-fork> ~/.claude-dev
cd ~/.claude-dev
CLAUDE_HOME="$PWD" bash install.sh   # installs deps + runs the suite
```

You do **not** need a Claude account or API keys to develop or run the test suite — provider calls are mocked in tests.

## The one rule: keep the suite green

```bash
cd scripts
python tests/run_all.py     # validator regression (mechanical gates)
python tests/run_units.py   # harness internals
```

Both must pass before and after your change. CI runs them on every PR.

## Design conventions

- **Open/Closed.** A new provider/worker/validator/engine is a *new file* + *one registry line*. If you find yourself editing many existing files to add one thing, reconsider the seam.
- **Hooks fail open.** Any hook entrypoint must exit cleanly on exception — never let a hook bug block a user's tools. Wrap the top-level path and exit 0 on error.
- **Quantify, don't assert.** In docstrings, commit messages, and reports, state known limitations and coverage rather than absolute claims. A comment that over-promises relative to the code is treated as a defect.
- **Tests live next to what they verify** and self-register (the runners auto-discover `test_*`). Add a regression test with every behavioral change.
- **No personal/private data.** Don't commit absolute home paths, real project/company names, or credentials. Use generic placeholders (`example_project`, `~/.claude`).

## Pull requests

- One focused change per PR. Conventional Commit style (`fix:`, `feat:`, `docs:`, `refactor:`).
- Describe what you changed, why, and how you verified it (paste the green suite summary).
- For changes to enforcement code (hooks, the mutation-gate, validators that block), call it out explicitly — these get extra review because they change runtime behavior for everyone.

## Reporting issues

Especially welcome: any place where a claim (in docs, a docstring, or a report) is **stronger than the code that backs it**. That's the kind of bug this project most wants to hear about.
