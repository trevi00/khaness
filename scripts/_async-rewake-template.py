#!/usr/bin/env python3
"""_async-rewake-template.py - Async Rewake hook template

NOT active by default (prefixed with _). Copy and customize for your use case.

How asyncRewake works:
1. Hook config: {"type":"command", "command":"python ...", "asyncRewake": true}
2. Hook runs in BACKGROUND (non-blocking, model continues working)
3. When done: exit code 0 = silent, exit code 2 = WAKE MODEL with notification
4. On exit code 2, stdout/stderr becomes a task-notification that wakes the model

Use cases:
- CI/CD pipeline completion monitoring
- Long-running build/test result waiting
- External API/service health checks
- Background security scan completion

Example settings.json entry:
{
  "hooks": {
    "PostToolUse": [{
      "hooks": [{
        "type": "command",
        "command": "python /home/user/.claude/scripts/my-async-hook.py",
        "asyncRewake": true
      }]
    }]
  }
}
"""

import sys
import json
import time
import subprocess

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def main():
    input_data = json.load(sys.stdin)

    # Example: wait for a build to complete
    # Customize this section for your use case

    # Option 1: Poll a process/file
    # max_wait = 120  # seconds
    # for _ in range(max_wait):
    #     if check_build_complete():
    #         result = get_build_result()
    #         if result["failed"]:
    #             print(json.dumps({"reason": f"Build failed: {result['error']}"}))
    #             sys.exit(2)  # Exit 2 = wake model
    #         sys.exit(0)  # Exit 0 = silent success
    #     time.sleep(1)

    # Option 2: Run a command and check result
    # result = subprocess.run(["npm", "test"], capture_output=True, text=True)
    # if result.returncode != 0:
    #     print(f"Tests failed:\n{result.stderr[:500]}")
    #     sys.exit(2)  # Wake model to fix

    # Default: do nothing (template)
    sys.exit(0)


if __name__ == "__main__":
    main()
