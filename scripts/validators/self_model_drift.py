#!/usr/bin/env python3
"""self_model_drift — ADVISORY validator: 3 self-model-drift surfaces.

Sibling of doc_code_drift (which covers atlas card↔code drift). Extends the
self-verifying-harness thesis to doc↔doc governance + agent-capability drift.
Design: debate-1780540387-7a5009 converged gen-3 sha1
d5aa3c5b9d53d42521cf5eaa97ce72b8ca5ff4b4 (harness-advancement #4).

F-TOOLS (security): agents/*.md `tools:` frontmatter privilege-creep. A
  name-keyed allowlist of ISOLATION-class agents (seed: harness-evaluator, whose
  Read/Grep/WebSearch/WebFetch isolation is runtime-enforced in
  lib/evaluator_dispatcher.py). WARN if such an agent's frontmatter declares a
  tool NOT in its allowlist (one-way subset / privilege-creep only). Seed-of-one:
  only harness-evaluator is asserted — the debate trio (planner/critic/architect)
  is a looser isolation class, intentionally UNASSERTED; and the subset check is
  BLIND to a DELETED required tool (out of the privilege-creep scope).

F-SCRIPTREF: commands/*.md + skills/**/*.md backtick script-path refs must
  resolve on disk. Triple guard: backtick-wrapped + known-dir-prefix
  {lib,validators,handlers,engine,cli,cron} (tests/ DROPPED — tests/test_<name>.py
  is a documented TEMPLATE, not an always-resident path) + (`.py` | `python -m
  <dotted>`). Existence-only: catches non-resolving refs; a moved-but-lingering
  target → false PASS (semantic currency unchecked).

F-MUTMIRROR: the §Mutation classification table's 5 gate tokens must be present
  in every canonical mirror. Canonical = CLAUDE.md table. EXPLICIT hardcoded
  3-path allowlist of TABLE mirrors {CLAUDE.md, HARNESS-GUIDE.md, atlas
  mutation-classification-table-is-single-source-of-truth.md}; NO glob/density
  discovery → any OTHER table (incl. the L0-L4 memory-autonomy-gradient note)
  excluded BY IDENTITY. Prose/code summaries (meta_rules.py, critic_policy.py)
  are deliberately NOT policed: they hold only 2 token literals each by design
  (completeness-diffing paraphrasing prose is structurally unsound), and being
  plain .py (no globs:) they are never agent-context-injected.

Default ADVISORY tier; GRADUATES advisory->blocking via the graduate-validator
  token. Graduation state is DYNAMIC (do not hardcode it — it drifts; check
  is_graduated() / VALIDATOR_NAMES membership at runtime). When graduated,
  main()->1 on drift>0; ungraduated it is WARN-only (main()->0). AST/text-only,
  hermetic (shares lib.doc_drift_common._read_source / ._module_reader hook).
  Residual risks (non-blocking, recorded in the debate self_doubt): prose/code
  summaries can silently drift (low-risk reviewed-code class); _meta/
  promotion-policy.md is activation:always with a self-subordinating 2-row
  partial excerpt, not policed here.

Invocation:
    python -m validators.self_model_drift
    python -m validators.self_model_drift --self-check
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # cp949 console safety (Windows)

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.frontmatter import parse_frontmatter  # noqa: E402
from lib.paths import SCRIPTS_DIR  # noqa: E402
from lib.doc_drift_common import _read_source  # noqa: E402 (shared hermetic reader)

_HOME = _SCRIPTS.parent  # ~/.claude


# ────────────────────────────── F-TOOLS ──────────────────────────────
# Single source of truth for isolation-class agents' minimal tool sets.
_ISOLATION_TOOL_ALLOWLIST: dict[str, frozenset[str]] = {
    "harness-evaluator": frozenset({"Read", "Grep", "WebSearch", "WebFetch"}),
}


def _parse_tools_field(raw) -> set[str]:
    """Frontmatter `tools:` may be a comma-string or a YAML list. Normalize to set."""
    if isinstance(raw, str):
        return {t.strip() for t in raw.split(",") if t.strip()}
    if isinstance(raw, (list, tuple)):
        return {str(t).strip() for t in raw if str(t).strip()}
    return set()


def _extra_tools(actual: set[str], allowed: frozenset[str]) -> set[str]:
    """One-way subset: tools present beyond the allowlist (= privilege creep)."""
    return actual - allowed


def check_agent_tools() -> list[str]:
    warns: list[str] = []
    agents_dir = _HOME / "agents"
    for name in sorted(_ISOLATION_TOOL_ALLOWLIST):
        allowed = _ISOLATION_TOOL_ALLOWLIST[name]
        path = agents_dir / f"{name}.md"
        parsed = parse_frontmatter(path)
        if parsed is None:
            warns.append(
                f"[WARN] agents/{name}.md: isolation-class agent missing/unreadable "
                f"— cannot verify tools allowlist"
            )
            continue
        fm, _ = parsed
        actual = _parse_tools_field(fm.get("tools", ""))
        extra = _extra_tools(actual, allowed)
        if extra:
            warns.append(
                f"[WARN] agents/{name}.md: tools-isolation: frontmatter declares "
                f"{sorted(extra)} not in expected-minimal allowlist {sorted(allowed)} "
                f"(privilege creep)"
            )
    return warns


# ───────────────────────────── F-SCRIPTREF ─────────────────────────────
# .py refs: backtick + known dir-prefix (tests/ DROPPED per debate) + .py.
_SCRIPTREF_PY_RE = re.compile(
    r"`(?:~/\.claude/)?(?:scripts/)?"
    r"((?:lib|validators|handlers|engine|cli|cron)/[A-Za-z0-9_./-]+\.py)`"
)
# module refs: `python -m <dotted>` where the head is a known package.
_MODULE_REF_RE = re.compile(
    r"`python -m ((?:lib|validators|handlers|engine|cli|cron)\.[A-Za-z0-9_.]+)`"
)


def _extract_script_refs(text: str) -> list[tuple[str, str]]:
    """Return [('py', rel), ('mod', dotted), ...] — the triple-guarded refs.
    Pure: backtick + dir-prefix + (.py | python -m) already encoded in the regexes."""
    out: list[tuple[str, str]] = []
    for rel in _SCRIPTREF_PY_RE.findall(text):
        out.append(("py", rel))
    for dotted in _MODULE_REF_RE.findall(text):
        out.append(("mod", dotted))
    return out


def _ref_resolves(kind: str, ref: str) -> bool:
    """Existence-only resolution under SCRIPTS_DIR. (Currency NOT checked: a
    moved-but-lingering target file → True = false PASS.)"""
    if kind == "py":
        return (SCRIPTS_DIR / ref).exists()
    # module form: dotted -> path.py OR package/__main__.py
    rel = ref.replace(".", "/")
    return (SCRIPTS_DIR / (rel + ".py")).exists() or (SCRIPTS_DIR / rel / "__main__.py").exists()


def check_script_refs() -> list[str]:
    warns: list[str] = []
    for sub in ("commands", "skills"):
        root = _HOME / sub
        if not root.is_dir():
            continue
        for md in sorted(root.rglob("*.md")):
            text = _read_source(md)
            if text is None:
                continue
            seen: set[str] = set()
            for kind, ref in _extract_script_refs(text):
                key = f"{kind}:{ref}"
                if key in seen:
                    continue
                seen.add(key)
                if not _ref_resolves(kind, ref):
                    shown = ref if kind == "py" else f"python -m {ref}"
                    warns.append(
                        f"[WARN] {sub}/{md.name}: script ref `{shown}` does not resolve under scripts/"
                    )
    return warns


# ───────────────────────────── F-MUTMIRROR ─────────────────────────────
_CANONICAL_TOKENS: frozenset[str] = frozenset({
    "enable-skill",
    "apply-user-preference",
    "enable-cron-job",
    "configure-critic-policy",
    "promote-to-core",
    "graduate-validator",
})
_BACKTICK_TOKEN_RE = re.compile(r"`([a-z][a-z0-9-]+)`")


def _canonical_tokens_in(text: str) -> set[str]:
    """Backtick literals intersected with the canonical gate-token vocabulary.
    Intersecting with the closed vocabulary makes paraphrased row labels and
    stray backticks (e.g. `<project>/atlas/`) structurally unable to pollute the
    set — only the 5 known gate tokens can match."""
    return set(_BACKTICK_TOKEN_RE.findall(text)) & _CANONICAL_TOKENS


def _mirror_paths() -> list[tuple[str, Path]]:
    """EXPLICIT hardcoded allowlist of the 3 table mirrors. No glob/density
    discovery — any other table is excluded BY IDENTITY (not in this list)."""
    # Canonical = the shipped operating contract at CLAUDE_HOME/CLAUDE.md. HARNESS-GUIDE.md
    # and the atlas note are OPTIONAL secondary mirrors — only cross-checked when present
    # (check_mut_mirror skips an unreadable mirror silently, so a minimal install shipping
    # only CLAUDE.md produces no spurious "mirror unreadable" warnings).
    return [
        ("CLAUDE.md", _HOME / "CLAUDE.md"),
        ("HARNESS-GUIDE.md", _HOME / "HARNESS-GUIDE.md"),
        ("atlas/mutation-tokens/concepts/mutation-classification-table-is-single-source-of-truth.md",
         _HOME / "atlas" / "mutation-tokens" / "concepts"
         / "mutation-classification-table-is-single-source-of-truth.md"),
    ]


def check_mut_mirror() -> list[str]:
    warns: list[str] = []
    mirrors = _mirror_paths()
    # Canonical = CLAUDE.md (first entry). Sanity: it must carry all 5 itself.
    canon_label, canon_path = mirrors[0]
    canon_text = _read_source(canon_path)
    if canon_text is None:
        return [f"[WARN] {canon_label}: canonical §Mutation table source unreadable ({canon_path})"]
    canon_tokens = _canonical_tokens_in(canon_text)
    missing_canon = _CANONICAL_TOKENS - canon_tokens
    if missing_canon:
        warns.append(
            f"[WARN] {canon_label}: canonical §Mutation table missing expected gate tokens "
            f"{sorted(missing_canon)} (canonical itself drifted)"
        )
    for label, path in mirrors[1:]:
        text = _read_source(path)
        if text is None:
            continue  # optional mirror not shipped in this install — silent, not drift
        missing = _CANONICAL_TOKENS - _canonical_tokens_in(text)
        if missing:
            warns.append(
                f"[WARN] {label}: §Mutation mirror missing gate tokens {sorted(missing)} "
                f"present in canonical CLAUDE.md table"
            )
    return warns


# ─────────────────────────────── scan / main ───────────────────────────────
def scan() -> dict:
    return {
        "tools_warns": check_agent_tools(),
        "scriptref_warns": check_script_refs(),
        "mutmirror_warns": check_mut_mirror(),
    }


def _is_graduated() -> bool:
    """True iff this validator graduated advisory→blocking (Track 1
    debate-1780722434-e5h19n). Guarded + fail-soft (missing/garbled state keeps
    us advisory). Lazy import keeps scan() and the module hermetic."""
    try:
        from lib.graduation import is_graduated
        return is_graduated("self_model_drift")
    except Exception:
        return False


def main() -> int:
    r = scan()
    for key in ("tools_warns", "scriptref_warns", "mutmirror_warns"):
        for w in r[key]:
            print(w)
    total = sum(len(r[k]) for k in r)
    tier = "blocking" if _is_graduated() else "advisory"
    summary = (
        f"self_model_drift — {len(r['tools_warns'])} tools + "
        f"{len(r['scriptref_warns'])} scriptref + {len(r['mutmirror_warns'])} mutmirror drift "
        f"({total} total, {tier})"
    )
    # C8 part-2: graduated (blocking) mode FAILs on drift; advisory stays exit-0.
    if tier == "blocking" and total > 0:
        print(f"[FAIL] {summary}")
        return 1
    print(f"[PASS] {summary}")
    return 0


def _self_check() -> int:
    """Hermetic assertions on the pure extractors (synthetic fixtures)."""
    n = 0

    def _a(cond: bool, msg: str) -> None:
        nonlocal n
        n += 1
        if not cond:
            raise AssertionError(f"self_model_drift self-check FAIL: {msg}")

    # F-TOOLS
    _a(_parse_tools_field("Read, Grep, Bash") == {"Read", "Grep", "Bash"}, "tools comma-parse")
    _a(_parse_tools_field(["Read", "Grep"]) == {"Read", "Grep"}, "tools list-parse")
    _a(_extra_tools({"Read", "Grep", "Bash"}, frozenset({"Read", "Grep"})) == {"Bash"}, "creep detect")
    _a(_extra_tools({"Read"}, frozenset({"Read", "Grep", "WebSearch"})) == set(), "subset clean (missing tool NOT warned)")

    # F-SCRIPTREF
    refs = _extract_script_refs(
        "use `lib/foo.py` and `python -m cli.bar` and `tests/test_x.py` "
        "and prose lib mention and `enable-skill`"
    )
    _a(("py", "lib/foo.py") in refs, "py ref extracted")
    _a(("mod", "cli.bar") in refs, "module ref extracted")
    _a(all(r != ("py", "tests/test_x.py") for r in refs), "tests/ DROPPED from prefix")
    _a(all("enable-skill" not in r[1] for r in refs), "non-path backtick token ignored")
    _a(_ref_resolves("py", "validators/self_model_drift.py"), "real py ref resolves")
    _a(not _ref_resolves("py", "lib/__nonexistent__.py"), "phantom py ref unresolved")

    # F-MUTMIRROR
    full = "| x | `enable-skill` | `apply-user-preference` | `enable-cron-job` | `configure-critic-policy` | `promote-to-core` | `graduate-validator` |"
    _a(_canonical_tokens_in(full) == _CANONICAL_TOKENS, "full table → all 6 tokens")
    _a(_canonical_tokens_in("only `enable-skill` here") == {"enable-skill"}, "partial → subset")
    _a(_canonical_tokens_in("paraphrase: critic policy 변경, `<project>/atlas/`") == set(), "paraphrase/stray backtick → none")

    print(f"[OK] self_model_drift self-check: {n} assertions passed")
    return 0


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        sys.exit(_self_check())
    sys.exit(main())
