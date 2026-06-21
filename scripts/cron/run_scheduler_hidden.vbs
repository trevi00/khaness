' Hidden launcher for the harness cron scheduler (M20).
' Task Scheduler runs a .bat via cmd.exe, which flashes a console window every
' cadence. Pointing the task action at THIS .vbs instead runs run_scheduler.bat
' with WindowStyle 0 (fully hidden) and waits for it (True), propagating the exit
' code so Task Scheduler's "Last Result" stays accurate. No stored password needed.
Set sh = CreateObject("WScript.Shell")
rc = sh.Run("""C:\Users\user\.claude\scripts\cron\run_scheduler.bat""", 0, True)
WScript.Quit rc
