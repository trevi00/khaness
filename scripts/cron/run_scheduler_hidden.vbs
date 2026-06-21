' Hidden launcher for the harness cron scheduler (Windows Task Scheduler).
' Task Scheduler runs a .bat via cmd.exe, which flashes a console window every
' cadence. Pointing the task action at THIS .vbs instead runs run_scheduler.bat
' with WindowStyle 0 (fully hidden) and waits for it (True), propagating the exit
' code so Task Scheduler's "Last Result" stays accurate. No stored password needed.
' Self-locating: resolves run_scheduler.bat next to this script, so it works from
' any install location (clone or plugin) without a hardcoded path.
Set fso = CreateObject("Scripting.FileSystemObject")
batPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "run_scheduler.bat")
Set sh = CreateObject("WScript.Shell")
rc = sh.Run("""" & batPath & """", 0, True)
WScript.Quit rc
