@echo off
REM ============================================================================
REM Harness cron scheduler driver launcher (M20).
REM Register this .bat in Windows Task Scheduler (see instructions). Idempotent:
REM each job runs only when its per-job cadence has elapsed, so calling this every
REM 30 min is safe. By DEFAULT only auto-OK jobs run: the 4 check_* probes + 6 GC
REM tasks. The 4 token-gated run_* mutations (L2 promotion / ledger compaction /
REM pollution cleanup / brain push) are SKIPPED unless you opt in below.
REM
REM Token-gated mutations OPTED IN (operator decision 2026-06-18): the line below
REM authorizes the 4 run_* jobs (L2 promotion / ledger compaction / pollution cleanup /
REM brain push). Scoped to this cron run only — interactive sessions never see it.
REM Re-comment (prefix `REM `) to opt back out.
set HARNESS_MUTATION_TOKEN=enable-cron-job
REM ============================================================================
cd /d "C:\Users\user\.claude\scripts"
"C:\Python313\python.exe" -m cron.scheduler_driver >> "C:\Users\user\.claude\state\scheduler-driver.log" 2>&1
