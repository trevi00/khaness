#!/usr/bin/env bash
# Install pre-commit hook that runs commit_layer_adjacency validator.
# Idempotent: safe to re-run. Honors $CLAUDE_HOME if set, else ~/.claude.
#
# F4 binding condition (fixplan-meta debate Gen4): hook scope is python
# orphan detection only via subprocess.run timeout in tests/run_all.py;
# non-python (git/node) child processes are out of scope.
set -e

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
SCRIPTS="$CLAUDE_HOME/scripts"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"

if [[ -z "$REPO_ROOT" ]]; then
  echo "ERROR: not inside a git repository — run from a clone of the harness repo." >&2
  exit 1
fi

HOOK_DIR="$REPO_ROOT/.git/hooks"
HOOK_PATH="$HOOK_DIR/pre-commit"
mkdir -p "$HOOK_DIR"

cat > "$HOOK_PATH" <<'EOF'
#!/usr/bin/env bash
# Auto-installed by scripts/install_pre_commit.sh — DO NOT EDIT.
# Runs commit_layer_adjacency validator on staged Python files.
# git runs this hook with CWD=repo root; the `validators` package lives under
# scripts/, so add it to PYTHONPATH (git context still resolves from repo root).
ROOT="$(git rev-parse --show-toplevel)"
# Skip on trees without scripts/ (e.g. the brain-snapshots orphan worktree that
# brain_autopush commits into) — nothing to validate and validators/ isn't there.
[ -d "$ROOT/scripts" ] || exit 0
exec env PYTHONPATH="$ROOT/scripts" PYTHONIOENCODING=utf-8 python -m validators.commit_layer_adjacency
EOF

chmod +x "$HOOK_PATH" 2>/dev/null || true

echo "[OK] pre-commit hook installed at $HOOK_PATH"
echo "     wraps: python -m validators.commit_layer_adjacency"
echo "     (Note on Windows Git Bash: chmod is a no-op; Git for Windows honors hook by extension.)"
