"""Cron-eligible periodic checkers (executed by external scheduler).

Per CLAUDE.md Mutation table: cron job *registration* is auto-OK; cron job
*execution / flag consumption* requires the `enable-cron-job` token gate.
Each module here emits a state-flag file (read-only side effect from the
harness POV) — the operator decides whether to act on it.

Registered jobs (check_* = auto-OK flag emitter, run_* = enable-cron-job gated):
  l2_promotion        — check_l2_promotion / run_l2_promotion (W14/W16)
  ledger_compaction   — check_ledger_compaction / run_ledger_compaction (M29;
                        closes lib/operator_ledger.py:54-56 deferred follow-up)
  pollution           — check_pollution / run_pollution_cleanup (M29; schedules the
                        ad-hoc burst-pollution detector + token-gates the retract)
  brain_push          — check_brain_push / run_brain_push (M29; divergence safety-net
                        for a missed Stop-hook save + deliberate force-snapshot. The
                        git commit+push of brain/ stays the operator's hard-gated flow.)

Activation (operator): `python -m cron.check_<job>` needs no token; the gated run is
`HARNESS_MUTATION_TOKEN=enable-cron-job python -m cron.run_<job>`.

Cadence + reliability: `cron.scheduler_driver` is the single entrypoint an external OS
scheduler calls periodically (failure backoff, overlap lock, run-history, liveness
heartbeat). `python -m cron.scheduler_driver --status` shows per-job health + liveness.
Adding a harness job = ONE `CronJob(...)` row in `scheduler_driver.CRON_JOBS`.

Boundary (D5): the platform `Cron*` tools (CronCreate/CronList/CronDelete) are a
SEPARATE, platform-managed cron system. This `cron/` package is the harness-INTERNAL
scheduler for harness maintenance jobs; the two do not share state. Use the platform
Cron tools for user-facing scheduled tasks; use this package for harness upkeep.
"""
