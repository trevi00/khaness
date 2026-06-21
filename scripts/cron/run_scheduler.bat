@echo off
REM ============================================================================
REM Harness cron scheduler driver launcher (Windows Task Scheduler).
REM Self-locating + portable: resolves the scripts dir from this file's own
REM location (%~dp0..) and the state dir from CLAUDE_HOME (falls back to
REM %USERPROFILE%\.claude). Uses a discoverable `python` on PATH. Register this
REM .bat (or the hidden .vbs wrapper) in Task Scheduler. Idempotent: each job
REM runs only when its per-job cadence has elapsed, so a 30-min cadence is safe.
REM By DEFAULT only auto-OK jobs run (the check_* probes + GC tasks).
REM
REM OPT-IN: the token-gated run_* mutations (L2 promotion / ledger compaction /
REM pollution cleanup / brain push) are SKIPPED unless you authorize them by
REM UN-commenting the line below (remove `REM `). Scoped to this cron run only —
REM interactive sessions never see it.
REM set HARNESS_MUTATION_TOKEN=enable-cron-job
REM ============================================================================
setlocal
set "STATE=%CLAUDE_HOME%"
if not defined STATE set "STATE=%USERPROFILE%\.claude"
if not exist "%STATE%\state" mkdir "%STATE%\state"
cd /d "%~dp0.."
python -m cron.scheduler_driver >> "%STATE%\state\scheduler-driver.log" 2>&1
