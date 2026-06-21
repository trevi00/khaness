'use strict';

/**
 * Multi-scenario test harness for the `gsd-tools quick-merge-back` subcommand.
 *
 * HARD PREREQUISITE (worktree-merge-back-REDESIGN-SPEC.md): built BEFORE the
 * implementation. Each scenario constructs a REAL temp git repo + `git worktree
 * add`, drives the subcommand end-to-end via subprocess, and asserts on the
 * final `main` tree + the returned JSON. The sim approximations missed the
 * failing edge cell four times; these are real git assertions.
 *
 * Design contract locked by debate-1781268351-d1cd78 (gen-2 approved, ontology
 * sha f16bbec2…). Run: node --test bin/lib/__tests__/merge-back.test.cjs
 *
 * Each scenario gets its OWN temp root (no shared worktree-list contamination).
 * Teardown runs `git worktree remove --force` BEFORE rmSync (releases git's
 * handles) then a retried rmSync of the whole root — a persistent Windows lock
 * surfaces as a test error rather than silently leaking into the next scenario.
 */

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

// bin/lib/__tests__/ -> bin/gsd-tools.cjs
const GSD_TOOLS = path.resolve(__dirname, '..', '..', 'gsd-tools.cjs');

// ─── git + fs helpers ─────────────────────────────────────────────────────────

function git(cwd, args, { check = false } = {}) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf-8' });
  const out = (r.stdout || '').replace(/\s+$/, '');
  const err = (r.stderr || '').replace(/\s+$/, '');
  if (check && r.status !== 0) {
    throw new Error(`git ${args.join(' ')} failed (${r.status}): ${err || out}`);
  }
  return { code: r.status, stdout: out, stderr: err };
}

function rmRetry(p) {
  for (let i = 0; i < 6; i++) {
    try {
      fs.rmSync(p, { recursive: true, force: true });
      return;
    } catch (e) {
      // Final attempt: a persistent lock is a real problem — surface it.
      if (i === 5) throw e;
      // Backoff without a wall-clock dependency (Windows AV/fsmonitor handle race).
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 150);
    }
  }
}

function writeFile(root, rel, content) {
  const fp = path.join(root, rel);
  fs.mkdirSync(path.dirname(fp), { recursive: true });
  fs.writeFileSync(fp, content);
  return fp;
}

function commit(cwd, rel, content, msg) {
  writeFile(cwd, rel, content);
  git(cwd, ['add', '--', rel], { check: true });
  git(cwd, ['commit', '-q', '-m', msg], { check: true });
  return git(cwd, ['rev-parse', 'HEAD'], { check: true }).stdout;
}

function head(cwd) {
  return git(cwd, ['rev-parse', 'HEAD'], { check: true }).stdout;
}

function existsAtHead(repo, rel) {
  return git(repo, ['cat-file', '-e', `HEAD:${rel}`]).code === 0;
}

function showAtHead(repo, rel) {
  // raw (no trailing-whitespace strip) so byte-exact content assertions hold
  const r = spawnSync('git', ['show', `HEAD:${rel}`], { cwd: repo, encoding: 'utf-8' });
  return r.stdout || '';
}

function worktreeCount(repo) {
  return git(repo, ['worktree', 'list', '--porcelain']).stdout
    .split('\n').filter((l) => l.startsWith('worktree ')).length;
}

function branchExists(repo, branch) {
  return git(repo, ['rev-parse', '--verify', '--quiet', `refs/heads/${branch}`]).code === 0;
}

// ─── scenario scaffold ────────────────────────────────────────────────────────

const QID = '260612-a3f';     // YYMMDD-xxx, mirrors init.cjs
const SLUG = 'demo';
const QDIR = `.planning/quick/${QID}-${SLUG}`;
const BRANCH = `gsd/quick-${QID}`;

/**
 * Build a base repo (main): STATE/ROADMAP committed, then PLAN committed
 * (Fix E — PLAN reachable before the worktree spawn). Returns paths + the
 * EXPECTED_BASE sha (HEAD after the PLAN commit).
 */
function makeBase({ autocrlf = false, extraBaseFiles = {} } = {}) {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), 'gsd-mb-'));
  const repo = path.join(rootDir, 'repo');
  fs.mkdirSync(repo);
  git(repo, ['init', '-q'], { check: true });
  git(repo, ['config', 'user.email', 'mb@test.local'], { check: true });
  git(repo, ['config', 'user.name', 'mb-test'], { check: true });
  git(repo, ['config', 'commit.gpgsign', 'false']);
  git(repo, ['config', 'core.autocrlf', String(autocrlf)]);

  writeFile(repo, '.planning/STATE.md', '# STATE\nmain-state-v1\n');
  writeFile(repo, '.planning/ROADMAP.md', '# ROADMAP\nmain-roadmap-v1\n');
  for (const [rel, content] of Object.entries(extraBaseFiles)) writeFile(repo, rel, content);
  git(repo, ['add', '-A'], { check: true });
  git(repo, ['commit', '-q', '-m', 'base: planning + seed'], { check: true });

  const planRel = `${QDIR}/${QID}-PLAN.md`;
  const expectedBase = commit(repo, planRel, '# PLAN\nthe plan\n', `docs(quick-${QID}): plan`);

  return { rootDir, repo, expectedBase };
}

/**
 * Add an executor worktree branched from EXPECTED_BASE and run `build(wt)`
 * to author its commits. Returns wt path. The worktree dir lives INSIDE the
 * scenario root so a single rmRetry cleans everything.
 */
function addWorktree(ctx, build, { detach = false, name = 'wt', branch = BRANCH } = {}) {
  const wt = path.join(ctx.rootDir, name);
  if (detach) {
    git(ctx.repo, ['worktree', 'add', '-q', '--detach', wt, 'HEAD'], { check: true });
  } else {
    git(ctx.repo, ['worktree', 'add', '-q', '-b', branch, wt, 'HEAD'], { check: true });
  }
  build(wt);
  return wt;
}

function runMergeBack(repo, { quickId = QID, quickDir = QDIR, expectedBase } = {}) {
  const args = [GSD_TOOLS, 'quick-merge-back', '--cwd', repo, '--quick-id', quickId, '--quick-dir', quickDir];
  if (expectedBase) args.push('--expected-base', expectedBase);
  const r = spawnSync('node', args, { encoding: 'utf-8' });
  let out = (r.stdout || '').trim();
  if (out.startsWith('@file:')) out = fs.readFileSync(out.slice(6), 'utf-8');
  let json;
  try {
    json = JSON.parse(out);
  } catch (e) {
    throw new Error(`quick-merge-back did not emit JSON (exit ${r.status}).\nSTDOUT: ${out}\nSTDERR: ${r.stderr}`);
  }
  return { code: r.status, json, stderr: r.stderr || '' };
}

function teardown(ctx) {
  try {
    if (ctx.repo && fs.existsSync(ctx.repo)) {
      const wl = git(ctx.repo, ['worktree', 'list', '--porcelain']).stdout;
      for (const line of wl.split('\n')) {
        if (!line.startsWith('worktree ')) continue;
        const wt = line.slice('worktree '.length).trim();
        if (path.resolve(wt) !== path.resolve(ctx.repo)) {
          git(ctx.repo, ['worktree', 'remove', '--force', wt]);
        }
      }
      git(ctx.repo, ['worktree', 'prune']);
    }
  } catch { /* fall through to rmRetry */ }
  rmRetry(ctx.rootDir);
}

/** Run a scenario body with guaranteed teardown. */
function scenario(t, ctx, body) {
  t.after(() => teardown(ctx));
  body();
}

// ─── Scenarios ────────────────────────────────────────────────────────────────

test('1. fast-forward clean: FF merge, no drift -> no reconcile commit', (t) => {
  const ctx = makeBase();
  let codeCommit;
  addWorktree(ctx, (wt) => {
    codeCommit = commit(wt, 'src/foo.js', 'console.log(1)\n', 'feat: foo');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, '# Summary\ndone\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { code, json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(code, 0, 'exit 0');
    assert.equal(json.merged, true);
    assert.equal(json.worktrees.length, 1);
    const w = json.worktrees[0];
    assert.equal(w.merge_type, 'fast-forward');
    assert.equal(w.reconcile_commit_hash, null, 'clean FF -> NO reconcile commit (D6)');
    assert.equal(w.summary_present, true);
    assert.equal(w.plan_present, true);
    assert.equal(w.removed, true);
    assert.equal(w.branch_deleted, true);
    assert.deepEqual(w.resurrected_removed, []);
    // commit_hash = executor CODE commit, NOT the SUMMARY tip (D2 resolved_condition)
    assert.equal(w.executor_commit_hash, codeCommit, 'executor_commit_hash = code commit');
    assert.equal(json.commit_hash, codeCommit, 'top-level commit_hash = code commit');
    // final main tree
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'SUMMARY committed on main');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-PLAN.md`), 'PLAN present');
    assert.ok(existsAtHead(ctx.repo, 'src/foo.js'), 'code present');
    assert.equal(showAtHead(ctx.repo, '.planning/STATE.md'), '# STATE\nmain-state-v1\n', 'STATE = main version');
    assert.equal(worktreeCount(ctx.repo), 1, 'only main worktree remains');
    assert.equal(branchExists(ctx.repo, BRANCH), false, 'branch cleaned up');
  });
});

test('2. non-fast-forward: main advanced -> real merge commit, code+summary preserved', (t) => {
  const ctx = makeBase();
  let codeCommit;
  addWorktree(ctx, (wt) => {
    codeCommit = commit(wt, 'src/foo.js', 'A\n', 'feat: foo');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, '# Summary\n', `docs(quick-${QID}): summary`);
  });
  // advance main AFTER the worktree spawned
  commit(ctx.repo, 'src/main_only.js', 'B\n', 'chore: main advance');
  scenario(t, ctx, () => {
    const { code, json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(code, 0);
    assert.equal(json.merged, true);
    const w = json.worktrees[0];
    assert.equal(w.merge_type, 'merge', 'non-FF -> merge commit');
    assert.equal(w.reconcile_commit_hash, null, 'no STATE/ROADMAP drift, no resurrection -> no reconcile');
    assert.ok(existsAtHead(ctx.repo, 'src/foo.js'), 'worktree code present');
    assert.ok(existsAtHead(ctx.repo, 'src/main_only.js'), 'main advance preserved');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'SUMMARY present');
    assert.equal(w.executor_commit_hash, codeCommit);
    assert.equal(worktreeCount(ctx.repo), 1);
  });
});

test('3. multi-commit worktree: 2 code commits + SUMMARY -> code_hash = last code commit', (t) => {
  const ctx = makeBase();
  let lastCode;
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/a.js', '1\n', 'feat: a');
    lastCode = commit(wt, 'src/b.js', '2\n', 'feat: b');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, '# Summary\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    const w = json.worktrees[0];
    assert.ok(existsAtHead(ctx.repo, 'src/a.js') && existsAtHead(ctx.repo, 'src/b.js'), 'all code present');
    assert.equal(w.executor_commit_hash, lastCode, 'code_hash = SUMMARY parent = last code commit');
    assert.equal(json.commit_hash, lastCode);
  });
});

test('4. --full artifacts: CONTEXT/RESEARCH/VERIFICATION/REVIEW under QUICK_DIR are KEPT', (t) => {
  const ctx = makeBase();
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    // worktree authors the full artifact set under its dir (the Critic blocker:
    // the KEEP predicate must not be limited to PLAN|SUMMARY|REVIEW)
    writeFile(wt, `${QDIR}/${QID}-CONTEXT.md`, 'ctx\n');
    writeFile(wt, `${QDIR}/${QID}-RESEARCH.md`, 'res\n');
    writeFile(wt, `${QDIR}/${QID}-VERIFICATION.md`, 'ver\n');
    writeFile(wt, `${QDIR}/${QID}-REVIEW.md`, 'rev\n');
    writeFile(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n');
    git(wt, ['add', '-A'], { check: true });
    git(wt, ['commit', '-q', '-m', `docs(quick-${QID}): artifacts`], { check: true });
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    for (const kind of ['CONTEXT', 'RESEARCH', 'VERIFICATION', 'REVIEW', 'SUMMARY']) {
      assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-${kind}.md`), `${kind}.md kept under QUICK_DIR`);
    }
    assert.deepEqual(json.worktrees[0].resurrected_removed, [], 'no artifact swept');
  });
});

test('4b. --full without REVIEW.md: absence is fine, no spurious removal', (t) => {
  const ctx = makeBase();
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    assert.equal(existsAtHead(ctx.repo, `${QDIR}/${QID}-REVIEW.md`), false, 'no REVIEW.md (not produced)');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'SUMMARY still present');
  });
});

test('5a. resurrection (outside QUICK_DIR): foreign .planning add is swept + reconciled', (t) => {
  const ctx = makeBase();
  const foreign = '.planning/quick/991231-zzz-old/991231-zzz-SUMMARY.md';
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    // worktree re-introduces a foreign artifact main does not track
    commit(wt, foreign, 'stale\n', 'oops: resurrect foreign');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    const w = json.worktrees[0];
    assert.equal(existsAtHead(ctx.repo, foreign), false, 'resurrected foreign file removed from main');
    assert.ok(w.resurrected_removed.includes(foreign), 'reported in resurrected_removed');
    assert.notEqual(w.reconcile_commit_hash, null, 'resurrection -> reconcile commit exists');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'legit SUMMARY kept');
  });
});

test('5b. same-quick-id junk: non-artifact file UNDER QUICK_DIR is swept; artifacts kept', (t) => {
  const ctx = makeBase();
  const junk = `${QDIR}/scratch-junk.txt`;          // under dir, NOT ${id}-<MODE>.md
  const lowerName = `${QDIR}/${QID}-notes.md`;        // lowercase mode -> NOT matched by ^${id}-[A-Z]+\.md$
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    writeFile(wt, junk, 'junk\n');
    writeFile(wt, lowerName, 'notes\n');
    writeFile(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n');
    git(wt, ['add', '-A'], { check: true });
    git(wt, ['commit', '-q', '-m', 'mix'], { check: true });
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    const w = json.worktrees[0];
    assert.equal(existsAtHead(ctx.repo, junk), false, 'non-artifact junk swept (D4 hole closed)');
    assert.equal(existsAtHead(ctx.repo, lowerName), false, 'lowercase non-artifact swept');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'SUMMARY artifact kept');
    assert.ok(w.resurrected_removed.includes(junk));
  });
});

test('6. detached-HEAD worktree: merged by sha, not skipped (D8)', (t) => {
  const ctx = makeBase();
  let codeCommit;
  addWorktree(ctx, (wt) => {
    codeCommit = commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  }, { detach: true });
  scenario(t, ctx, () => {
    const { code, json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(code, 0);
    assert.equal(json.merged, true);
    const w = json.worktrees[0];
    assert.equal(w.detached, true, 'detected detached HEAD');
    assert.ok(existsAtHead(ctx.repo, 'src/foo.js'), 'detached worktree code merged (not stranded)');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'detached SUMMARY merged');
    assert.equal(w.executor_commit_hash, codeCommit);
    assert.equal(w.removed, true);
    assert.equal(worktreeCount(ctx.repo), 1, 'detached worktree cleaned up');
  });
});

test('7. merge conflict: merged=false, worktree LEFT, main tree intact, exit 0', (t) => {
  const ctx = makeBase({ extraBaseFiles: { 'src/conflict.js': 'base\n' } });
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/conflict.js', 'worktree-version\n', 'feat: edit');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  });
  // main edits the SAME file differently after the spawn -> conflicting merge
  commit(ctx.repo, 'src/conflict.js', 'main-version\n', 'chore: main edits');
  const mainHeadBefore = head(ctx.repo);
  scenario(t, ctx, () => {
    const { code, json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(code, 0, 'conflict is reported via JSON, exit still 0');
    assert.equal(json.merged, false, 'merged=false on conflict');
    assert.ok(json.conflicts.length >= 1, 'conflicts[] populated');
    assert.equal(head(ctx.repo), mainHeadBefore, 'main HEAD unchanged (merge aborted)');
    assert.equal(showAtHead(ctx.repo, 'src/conflict.js'), 'main-version\n', 'main file intact');
    assert.equal(worktreeCount(ctx.repo), 2, 'conflicting worktree LEFT in place for manual resolve');
    assert.equal(git(ctx.repo, ['status', '--porcelain']).stdout, '', 'working tree clean (no dangling merge state)');
  });
});

test('8. multi-worktree: per-worktree PRE_MERGE_HEAD; both merged; commit_hash=primary code', (t) => {
  const ctx = makeBase();
  let code1;
  addWorktree(ctx, (wt) => {
    code1 = commit(wt, 'src/one.js', '1\n', 'feat: one');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum1\n', `docs(quick-${QID}): summary`);
  }, { name: 'wt1', branch: `gsd/quick-${QID}` });
  // second worktree, different branch + different quick dir id-suffixed file
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/two.js', '2\n', 'feat: two');
  }, { name: 'wt2', branch: `gsd/quick-${QID}-b` });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true, 'all worktrees merged');
    assert.equal(json.worktrees.length, 2, 'both worktrees processed');
    assert.ok(existsAtHead(ctx.repo, 'src/one.js') && existsAtHead(ctx.repo, 'src/two.js'), 'both merges landed');
    assert.equal(json.commit_hash, code1, 'top-level commit_hash = primary (first) worktree code commit');
    assert.equal(worktreeCount(ctx.repo), 1, 'all worktrees cleaned');
  });
});

test('9. STATE drift main-wins: worktree STATE edit discarded, reconcile restores main blob', (t) => {
  const ctx = makeBase();
  addWorktree(ctx, (wt) => {
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    commit(wt, '.planning/STATE.md', '# STATE\nWORKTREE-EDIT\n', 'oops: touch state');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    const w = json.worktrees[0];
    assert.equal(showAtHead(ctx.repo, '.planning/STATE.md'), '# STATE\nmain-state-v1\n', 'main STATE wins (#1756)');
    assert.notEqual(w.reconcile_commit_hash, null, 'drift -> reconcile commit created');
    assert.ok(existsAtHead(ctx.repo, `${QDIR}/${QID}-SUMMARY.md`), 'SUMMARY still kept');
  });
});

test('10. CRLF immunity: autocrlf checkout does NOT trigger a spurious reconcile (D6)', (t) => {
  const ctx = makeBase({ autocrlf: true });   // working-tree CRLF, blob LF
  addWorktree(ctx, (wt) => {
    git(wt, ['config', 'core.autocrlf', 'true']);
    commit(wt, 'src/foo.js', 'x\n', 'feat: foo');
    commit(wt, `${QDIR}/${QID}-SUMMARY.md`, 'sum\n', `docs(quick-${QID}): summary`);
  });
  scenario(t, ctx, () => {
    const { json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(json.merged, true);
    assert.equal(json.worktrees[0].reconcile_commit_hash, null,
      'blob-compare drift detection ignores CRLF working-tree -> NO spurious reconcile');
  });
});

test('11. no worktrees: graceful no-op', (t) => {
  const ctx = makeBase();
  scenario(t, ctx, () => {
    const { code, json } = runMergeBack(ctx.repo, { expectedBase: ctx.expectedBase });
    assert.equal(code, 0);
    assert.equal(json.merged, false);
    assert.equal(json.worktrees.length, 0);
    assert.equal(json.commit_hash, null);
    assert.equal(json.reason, 'no_worktrees');
  });
});
