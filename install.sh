#!/usr/bin/env bash
# Claude Harness installer — interpolates the portable settings template with this
# clone's actual location, installs Python deps, and runs the regression suite.
#
#   git clone <repo> ~/.claude && cd ~/.claude && bash install.sh
#
# Idempotent. Re-run any time to regenerate settings.json from the template.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HERE}"

echo "==> Claude Harness install"
echo "    home: $CLAUDE_HOME"

# 1. settings.json from the portable template (forward-slash absolute path).
TEMPLATE="$HERE/settings.json.template"
TARGET="$HERE/settings.json"
if [ -f "$TEMPLATE" ]; then
  # Claude Code hook commands use forward-slash absolute paths.
  HOME_FWD="$(printf '%s' "$CLAUDE_HOME" | sed 's#\\#/#g')"
  sed "s#__CLAUDE_HOME__#${HOME_FWD}#g" "$TEMPLATE" > "$TARGET"
  python -c "import json,sys; json.load(open(sys.argv[1],encoding='utf-8'))" "$TARGET" \
    && echo "    settings.json generated ($(grep -c '"command"' "$TARGET" 2>/dev/null || echo '?') hook commands)"
else
  echo "    WARN: settings.json.template not found — skipping settings generation"
fi

# 2. Python dependencies.
echo "==> pip install -r requirements.txt"
python -m pip install -q -r "$HERE/requirements.txt" || {
  echo "    pip install failed — install PyYAML>=6.0 manually"; }

# 3. Regression suite (proves the install is sound).
echo "==> running regression suite"
cd "$HERE/scripts"
CLAUDE_HOME="$CLAUDE_HOME" python tests/run_all.py   | tail -1
CLAUDE_HOME="$CLAUDE_HOME" python tests/run_units.py  | tail -1

echo "==> done. Open a new Claude Code session in this directory."
