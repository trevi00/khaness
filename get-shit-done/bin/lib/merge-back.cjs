'use strict';

/**
 * merge-back — deterministic quick-task worktree merge-back.
 *
 * Extracted from quick.md Step 6's inline bash-in-LLM-prose (which proved
 * patch-resistant: 4 adversarial passes found non-convergent defects 1→1→3→3).
 * Centralises the git-worktree logic so the edge cases are handled once,
 * correctly, and are unit-testable (bin/lib/__tests__/merge-back.test.cjs).
 *
 * Design locked by debate-1781268351-d1cd78 (gen-2 approved, ontology sha
 * f16bbec2…). Defect map (worktree-merge-back-REDESIGN-SPEC.md):
 *   D1 SUMMARY survives  — executor commits SUMMARY in worktree mode (quick.md),
 *                          so it is reachable via the merge here.
 *   D2 guard vs SUMMARY  — resurrection KEEP predicate is namespace-structural,
 *                          not a string allowlist (keeps every ${id}-<MODE>.md).
 *   D3 HEAD~1 on FF      — PRE_MERGE_HEAD captured per-worktree BEFORE its merge.
 *   D4 --amend on FF     — reconcile is a FRESH non-amend commit, drift-gated.
 *   D6 commit_hash       — executor_commit_hash = executor CODE commit, not tip.
 *   D7 guard over-scope  — KEEP is scoped to the current QUICK_DIR only.
 *   D8 detached skipped  — detached worktrees merge by sha (not skipped).
 *   D9 restore/sweep ord — single ordered transaction below.
 *
 * Only ever runs for non-scratch, commit_docs=true (quick.md Fix B/F).
 */

const path = require('node:path');
const { execGit, output, error } = require('./core.cjs');

/** dirname of a forward-slashed repo-relative path (no Windows backslashes). */
function posixDirname(p) {
  const norm = p.replace(/\\/g, '/');
  const idx = norm.lastIndexOf('/');
  return idx === -1 ? '' : norm.slice(0, idx);
}
function posixBasename(p) {
  const norm = p.replace(/\\/g, '/');
  const idx = norm.lastIndexOf('/');
  return idx === -1 ? norm : norm.slice(idx + 1);
}

/**
 * Resolve the executor's CODE commit on the worktree branch (spec-D6).
 * When the tip is a PURE docs (.planning/) commit — the SUMMARY commit the
 * executor makes last in worktree mode — the code commit is its parent;
 * otherwise the tip itself is the code commit. Returns a full sha.
 */
function resolveCodeCommit(wt, wtHead, normQuickDir, quickId) {
  const summaryPath = `${normQuickDir}/${quickId}-SUMMARY.md`;
  const sc = execGit(wt, ['log', '-1', '--format=%H', '--', summaryPath]);
  const summaryCommit = sc.exitCode === 0 ? sc.stdout.trim() : '';
  if (summaryCommit && summaryCommit === wtHead) {
    const changed = execGit(wt, ['diff-tree', '--no-commit-id', '--name-only', '-r', wtHead]);
    const files = changed.exitCode === 0
      ? changed.stdout.split('\n').map((s) => s.trim()).filter(Boolean)
      : [];
    const pureDocs = files.length > 0 && files.every((f) => f.replace(/\\/g, '/').startsWith('.planning/'));
    if (pureDocs) {
      const parent = execGit(wt, ['rev-parse', `${wtHead}^`]);
      if (parent.exitCode === 0 && parent.stdout.trim()) return parent.stdout.trim();
    }
  }
  return wtHead;
}

/**
 * Process one linked worktree: merge → resurrection sweep → main-wins restore →
 * single fresh reconcile commit (drift-gated) → cleanup. Mutates nothing on the
 * caller; returns a result entry (+ optional `_conflict`).
 */
function mergeOneWorktree(cwd, wt, normQuickDir, quickId, artifactRe) {
  // branch vs detached HEAD (D8)
  const symRef = execGit(wt, ['symbolic-ref', '-q', 'HEAD']);
  const detached = symRef.exitCode !== 0;
  let branch = null;
  if (!detached) {
    const ab = execGit(wt, ['rev-parse', '--abbrev-ref', 'HEAD']);
    branch = ab.exitCode === 0 ? ab.stdout.trim() : null;
  }
  const wtHead = execGit(wt, ['rev-parse', 'HEAD']).stdout.trim();

  const entry = {
    path: wt.replace(/\\/g, '/'),
    branch,
    detached,
    merge_type: null,
    executor_commit_hash: resolveCodeCommit(wt, wtHead, normQuickDir, quickId),
    reconcile_commit_hash: null,
    resurrected_removed: [],
    summary_present: false,
    plan_present: false,
    removed: false,
    branch_deleted: false,
    merged: false,
  };

  // PRE_MERGE_HEAD: main HEAD as it stands BEFORE merging THIS worktree (D3 +
  // per-worktree so a second worktree sees the first's merge, not a stale tip).
  const preMergeHead = execGit(cwd, ['rev-parse', 'HEAD']).stdout.trim();

  const target = detached ? wtHead : branch;
  if (!target) {
    entry._conflict = { path: entry.path, branch: '(unknown)', message: 'cannot resolve merge target' };
    return entry;
  }

  const merge = execGit(cwd, ['merge', target, '--no-edit', '-m', `chore: merge quick task worktree (${branch || wtHead.slice(0, 12)})`]);
  if (merge.exitCode !== 0) {
    execGit(cwd, ['merge', '--abort']); // no-op if no merge in progress
    entry._conflict = {
      path: entry.path,
      branch: branch || '(detached)',
      message: (merge.stdout + ' ' + merge.stderr).replace(/\s+/g, ' ').trim().slice(0, 300),
    };
    return entry;
  }

  // merge_type
  const postMergeHead = execGit(cwd, ['rev-parse', 'HEAD']).stdout.trim();
  if (postMergeHead === preMergeHead) {
    entry.merge_type = 'up-to-date';
  } else {
    const parents = execGit(cwd, ['rev-list', '--parents', '-n', '1', 'HEAD']).stdout.trim().split(/\s+/);
    entry.merge_type = parents.length > 2 ? 'merge' : 'fast-forward';
  }

  // Detached dangle tripwire (D8 — non-load-bearing: a real merge makes sha an
  // ancestor, 'up to date' means it already was; kept as a cheap honest guard).
  if (detached) {
    const anc = execGit(cwd, ['merge-base', '--is-ancestor', wtHead, 'HEAD']);
    if (anc.exitCode !== 0) {
      entry._conflict = { path: entry.path, branch: '(detached)', message: 'merged sha not ancestor of HEAD; refusing to remove (would dangle)' };
      return entry;
    }
  }

  // ── single ordered transaction (D9): sweep → main-wins restore → 1 reconcile ──

  // Resurrection sweep (D2/D7): files ADDED by the merge under .planning/. KEEP
  // iff under the current QUICK_DIR AND named ${id}-<MODE>.md (covers PLAN/
  // SUMMARY/REVIEW/CONTEXT/RESEARCH/VERIFICATION + future modes); else git rm.
  const added = execGit(cwd, ['diff', '--diff-filter=A', '--name-only', `${preMergeHead}..HEAD`, '--', '.planning/']);
  if (added.exitCode === 0 && added.stdout.trim()) {
    for (const rawPath of added.stdout.split('\n')) {
      const p = rawPath.trim();
      if (!p) continue;
      const pNorm = p.replace(/\\/g, '/');
      const keep = posixDirname(pNorm) === normQuickDir && artifactRe.test(posixBasename(pNorm));
      if (!keep) {
        execGit(cwd, ['rm', '-f', '--', p]);
        entry.resurrected_removed.push(pNorm);
      }
    }
  }

  // Drift detection — blob-exact vs PRE_MERGE_HEAD (commit-tree compare, so a
  // CRLF working-tree checkout never reads as drift). #1756: main always wins.
  const stateDrift = execGit(cwd, ['diff', '--quiet', preMergeHead, 'HEAD', '--', '.planning/STATE.md']).exitCode !== 0;
  const roadmapDrift = execGit(cwd, ['diff', '--quiet', preMergeHead, 'HEAD', '--', '.planning/ROADMAP.md']).exitCode !== 0;

  if (stateDrift || roadmapDrift || entry.resurrected_removed.length > 0) {
    if (stateDrift) {
      execGit(cwd, ['checkout', preMergeHead, '--', '.planning/STATE.md']);
      execGit(cwd, ['add', '--', '.planning/STATE.md']);
    }
    if (roadmapDrift) {
      execGit(cwd, ['checkout', preMergeHead, '--', '.planning/ROADMAP.md']);
      execGit(cwd, ['add', '--', '.planning/ROADMAP.md']);
    }
    // FRESH non-amend commit (D4): on FF, HEAD IS the SUMMARY commit — amending
    // would rewrite it. git rm already staged the removals.
    const rc = execGit(cwd, ['commit', '-m', `chore(quick-${quickId}): reconcile orchestrator-owned planning files`, '--no-verify']);
    if (rc.exitCode === 0) {
      entry.reconcile_commit_hash = execGit(cwd, ['rev-parse', 'HEAD']).stdout.trim();
    }
  }

  // presence on final main HEAD
  entry.summary_present = execGit(cwd, ['cat-file', '-e', `HEAD:${normQuickDir}/${quickId}-SUMMARY.md`]).exitCode === 0;
  entry.plan_present = execGit(cwd, ['cat-file', '-e', `HEAD:${normQuickDir}/${quickId}-PLAN.md`]).exitCode === 0;

  // cleanup — remove worktree FIRST (releases the branch checkout), then branch -D
  const rm = execGit(cwd, ['worktree', 'remove', wt, '--force']);
  entry.removed = rm.exitCode === 0;
  if (branch && !detached) {
    entry.branch_deleted = execGit(cwd, ['branch', '-D', branch]).exitCode === 0;
  }

  entry.merged = true;
  return entry;
}

const OUTPUT_FIELDS = [
  'path', 'branch', 'detached', 'merge_type', 'executor_commit_hash',
  'reconcile_commit_hash', 'resurrected_removed', 'summary_present',
  'plan_present', 'removed', 'branch_deleted',
];
function toOutputEntry(e) {
  const o = {};
  for (const k of OUTPUT_FIELDS) o[k] = e[k];
  return o;
}

/**
 * cmdQuickMergeBack — enumerate the executor's linked worktrees, merge each back
 * into main, and clean up. Returns + prints the JSON contract.
 *
 * @param {string} cwd  project root (the main worktree)
 * @param {{quickId:string, quickDir:string, expectedBase?:string}} opts
 * @param {boolean} raw
 */
function cmdQuickMergeBack(cwd, opts, raw) {
  const quickId = opts && opts.quickId;
  const quickDir = opts && opts.quickDir;
  if (!quickId) error('quick-merge-back requires --quick-id');
  if (!quickDir) error('quick-merge-back requires --quick-dir');

  const normQuickDir = quickDir.replace(/\\/g, '/').replace(/\/+$/, '');
  const escId = quickId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const artifactRe = new RegExp(`^${escId}-[A-Z]+\\.md$`);

  // exclude the main worktree (Fix C: --show-toplevel, not $(pwd))
  const top = execGit(cwd, ['rev-parse', '--show-toplevel']);
  const mainRoot = path.resolve(top.exitCode === 0 ? top.stdout.trim() : cwd);

  const wlist = execGit(cwd, ['worktree', 'list', '--porcelain']);
  const worktreePaths = [];
  if (wlist.exitCode === 0) {
    for (const line of wlist.stdout.split('\n')) {
      if (!line.startsWith('worktree ')) continue;
      const p = line.slice('worktree '.length).trim();
      if (path.resolve(p) !== mainRoot) worktreePaths.push(p);
    }
  }
  // `git worktree list` only guarantees the MAIN worktree is first; linked-worktree
  // ordering is unspecified. Sort so `primary` (the commit_hash recorded in STATE.md
  // for the rare multi-worktree quick task) is deterministic across runs.
  worktreePaths.sort();

  if (worktreePaths.length === 0) {
    const result = { merged: false, reason: 'no_worktrees', worktrees: [], commit_hash: null, conflicts: [] };
    output(result, raw, '');
    return result;
  }

  const entries = [];
  const conflicts = [];
  for (const wt of worktreePaths) {
    const e = mergeOneWorktree(cwd, wt, normQuickDir, quickId, artifactRe);
    entries.push(e);
    if (e._conflict) conflicts.push(e._conflict);
  }

  const primary = entries.find((e) => e.merged && e.executor_commit_hash);
  const commitHash = primary ? primary.executor_commit_hash : null;

  const result = {
    merged: entries.every((e) => e.merged),
    worktrees: entries.map(toOutputEntry),
    commit_hash: commitHash,
    conflicts,
  };
  output(result, raw, commitHash || '');
  return result;
}

module.exports = { cmdQuickMergeBack };
