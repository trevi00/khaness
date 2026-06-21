#!/usr/bin/env python3
"""insight_index_importer_whitelist — D6_forbidden_set / D7_enforcement validator.

Source: debate-1779267594-edb2a2 converged gen 4 (sha1 ac40cc972219d3374d8f08893719e7a89b495465).

Enforces the D6_forbidden_set LOCK: no module under
  engine/debate/*
  lib/evaluator_dispatcher.py
may import lib.insight_index (judge-generator isolation per
debate-1778248254-0b7092). Whitelist captures the 3 writers + 3 readers
ratified by Architect gen-4:
  WRITERS:
    - handlers/stop/learner.py            (W1 guarded by terminal_convergence_predicate)
    - engine/orchestrator.py              (W3 — evaluate_completion site)
    - lib/skill_candidate_detector.py     (W2 — _build_candidate_from_reflection adapter)
  READERS:
    - handlers/session/init.py            (R1 — _compose_harness_status tuple entry)
    - handlers/prompt/context_load.py     (R2 — last-5-by-correlation_id render)
    - cli/insight_index_cli.py            (R3 — operator surface)

Detection (AST):
  - ImportFrom(module='lib.insight_index' OR relative-resolved to lib/insight_index)
  - Import(alias.name == 'lib.insight_index')
  - Attribute access flagging bound names of insight_index from non-whitelisted callers

Documented out-of-scope (D7_enforcement value, architect self_doubt):
  - importlib.import_module('lib.insight_index')
  - __import__('lib.insight_index')
  A determined caller can bypass. Runtime ModuleSpec assert in
  lib/insight_index.py adds a 2nd line of defense (also fails open for
  REPL / frozen / eval'd cases — see _assert_caller_allowed).

Caller contract (validators/__init__.py):
  - main() -> None, no args
  - reads os.getcwd() (informational; actual scan is over SCRIPTS_DIR tree)
  - prints [PASS]/[FAIL] lines to stdout; never raises
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

for _stream in (sys.stdin, sys.stdout):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        try:
            _reconfigure(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# D6_forbidden_set LOCK (debate-1779267594-edb2a2 sha1 ac40cc972219d3).
# Forbidden module *prefixes* — match exact or descendant.
_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "engine.debate",          # engine/debate/* per ontology field
    "lib.evaluator_dispatcher",
)

# Whitelist of allowed importer modules (writers + readers + tests + the
# index module itself + validators that introspect the module). Listed as
# fully-qualified dotted paths matching the AST module-name space.
_ALLOWED_IMPORTERS: frozenset[str] = frozenset({
    "lib.insight_index",                      # self
    "handlers.stop.learner",                  # W1
    "engine.orchestrator",                    # W3 — evaluate_completion site
    "lib.skill_candidate_detector",           # W2
    "handlers.session.init",                  # R1
    "handlers.prompt.context_load",           # R2
    "cli.insight_index_cli",                  # R3 operator surface
    # housekeeping — tests + this validator must be able to introspect
    "validators.insight_index_importer_whitelist",
    "tests.test_insight_index",
    "tests.test_insight_index_importer_whitelist",
    "tests.test_work_unit_store",             # C6 control-arm introspection (debate-1781431026-af5f83 sha1 32808a52c893) — asserts lib.work_unit_store is NOT an L1 writer; test-housekeeping, not a production reader/writer (reader-count=3 lock preserved)
    "tests.conftest",                         # global autouse isolation fixture (debate-1780268884-1di5gw gen 4 sha1 78f09503) — same housekeeping class as the tests.* entries above

    "cron.check_l2_promotion",                # PR-cron emitter reads index
    "cron.run_l2_promotion",                  # PR-cron L2 consumer reads L1 for projection (W16 debate-1779328283-9076f2 D17)
    "lib.l2_promoter",                        # L1->L2 projection (W16 D5+D17 — uses insight_index.query)
    "tests.test_l2_promoter",                 # W16 cascade tests inject L1 fixtures via insight_index.append/retract

    # Pollution-retraction consumer (wave 27 follow-up #1, a79b2d7). Operator-
    # approved 2026-06-04 (self-verifying-harness STEP 2 follow-up): an
    # operator-invoked index-HYGIENE tool that retracts burst-polluted entries —
    # neither judge nor generator, so it does not breach D6_forbidden_set
    # isolation; aligned with the index's controlled-mutation design (same class
    # as W16 lib.l2_promoter D17, ratified there via debate). Operator nod
    # substitutes for the full debate per the clear-cut/already-shipped case.
    "cli.insight_index_pollution_detector",
    "tests.test_insight_index_pollution_detector",
})

_TARGET_MODULE = "lib.insight_index"


def _path_to_module(path: Path) -> str | None:
    """Map an absolute .py path to its dotted module name (relative to SCRIPTS)."""
    try:
        rel = path.resolve().relative_to(_SCRIPTS)
    except ValueError:
        return None
    parts = list(rel.parts)
    if not parts:
        return None
    if parts[-1].endswith(".py"):
        stem = parts[-1][:-3]
        if stem == "__init__":
            parts = parts[:-1]
        else:
            parts[-1] = stem
    return ".".join(parts) if parts else None


def _is_forbidden(module_name: str) -> bool:
    for prefix in _FORBIDDEN_PREFIXES:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return True
    return False


def _references_target(module: str | None) -> bool:
    """True iff `module` (from ImportFrom.module or Import.alias.name)
    references lib.insight_index either exactly or by attribute access path.
    """
    if not module:
        return False
    return module == _TARGET_MODULE or module.startswith(_TARGET_MODULE + ".")


def _resolve_relative(level: int, module: str | None, importer_pkg: list[str]) -> str | None:
    """Resolve `from .x import y` style ImportFrom to an absolute dotted name.

    `level` = number of leading dots (1 = current package, 2 = parent, etc.).
    `importer_pkg` = the path parts up to (but not including) the importer module.
    """
    if level <= 0:
        return module
    if level > len(importer_pkg):
        return None
    base = importer_pkg[: len(importer_pkg) - (level - 1)]
    if module:
        return ".".join(base + module.split("."))
    return ".".join(base) if base else None


class _InsightIndexUseVisitor(ast.NodeVisitor):
    """Detects (1) import statements pulling lib.insight_index and (2) bound-name
    attribute access of imported `insight_index` symbols. Records all findings
    for the caller's importer-policy decision.
    """

    def __init__(self, importer_module: str) -> None:
        self.importer = importer_module
        self.importer_pkg = importer_module.split(".")[:-1]
        self.hits: list[tuple[int, str]] = []  # (lineno, descriptor)
        self._bound_to_target: set[str] = set()  # local names bound to the module

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if _references_target(alias.name):
                self.hits.append((node.lineno, f"import {alias.name}"))
                bound = alias.asname or alias.name.split(".")[0]
                self._bound_to_target.add(bound)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        resolved = _resolve_relative(node.level, node.module, self.importer_pkg)
        if _references_target(resolved):
            for alias in node.names:
                bound = alias.asname or alias.name
                self._bound_to_target.add(bound)
            self.hits.append((
                node.lineno,
                f"from {resolved} import {', '.join(a.name for a in node.names)}",
            ))
        elif resolved == "lib":
            # Catch `from lib import insight_index [as X]` — the dotted-path
            # target is reached through the parent package.
            for alias in node.names:
                if alias.name == "insight_index":
                    bound = alias.asname or alias.name
                    self._bound_to_target.add(bound)
                    self.hits.append((
                        node.lineno,
                        f"from lib import insight_index"
                        f"{' as ' + alias.asname if alias.asname else ''}",
                    ))
        elif resolved is None and node.module and _references_target(node.module):
            # Defensive: relative resolution failed but absolute module matches.
            self.hits.append((node.lineno, f"from {node.module} import ..."))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Flag attribute access of bound names — e.g. `insight_index.append(...)`
        # after `import lib.insight_index as insight_index`. Already covered by
        # ImportFrom/Import collection but we record here for completeness so
        # the architect's "Attribute NodeVisitor" requirement is honored.
        if isinstance(node.value, ast.Name) and node.value.id in self._bound_to_target:
            self.hits.append((node.lineno, f"{node.value.id}.{node.attr}"))
        self.generic_visit(node)


def _scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    module = _path_to_module(path)
    if module is None:
        return []
    v = _InsightIndexUseVisitor(module)
    v.visit(tree)
    return v.hits


def _walk_harness_tree() -> list[Path]:
    """Yield .py files under the layered subtrees we enforce."""
    out: list[Path] = []
    for sub in ("lib", "validators", "handlers", "engine", "cli", "cron", "tests"):
        root = _SCRIPTS / sub
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def main() -> None:
    failures: list[str] = []
    scanned = 0
    for path in _walk_harness_tree():
        module = _path_to_module(path)
        if module is None:
            continue
        scanned += 1
        hits = _scan_file(path)
        if not hits:
            continue
        if module in _ALLOWED_IMPORTERS:
            # Allowed importer — references are policy-conforming, even if
            # the path is "engine.orchestrator" (allowed despite engine. prefix).
            continue
        if _is_forbidden(module):
            for lineno, desc in hits:
                failures.append(
                    f"[FAIL] insight_index_importer_whitelist: "
                    f"{module} uses lib.insight_index "
                    f"({path.relative_to(_SCRIPTS).as_posix()}:{lineno} `{desc}`) "
                    f"— forbidden by D6_forbidden_set (judge-generator isolation)"
                )
        else:
            # Not whitelisted, not in forbidden prefix — still flag as policy
            # drift so additions go through Architect verdict.
            for lineno, desc in hits:
                failures.append(
                    f"[FAIL] insight_index_importer_whitelist: "
                    f"{module} imports lib.insight_index "
                    f"({path.relative_to(_SCRIPTS).as_posix()}:{lineno} `{desc}`) "
                    f"— not in whitelist; update _ALLOWED_IMPORTERS via debate"
                )
    if failures:
        for line in failures:
            print(line)
        return
    print(f"[PASS] insight_index_importer_whitelist: {scanned} files scanned, no violations")


if __name__ == "__main__":
    main()
