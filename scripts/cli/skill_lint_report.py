#!/usr/bin/env python3
"""Thin CLI wrapper — logic lives in lib.skill_lint_report.

Moved to lib/ on 2026-06-21 to fix a layer inversion: handlers/ (init.py) was
importing UP into cli/ (the top consumer tier). The analysis/query logic only
ever depended on lib.paths, so it belongs in lib; init.py now imports
lib.skill_lint_report directly (handlers->lib, legal).

This wrapper re-exports the FULL module namespace so the existing surface keeps
working: `python -m cli.skill_lint_report ...` (skills/_common/skill-lint-workflow.md),
`cli/skill_lint_report.py::GRANDFATHERED_PATHS` doc refs, and
`from cli import skill_lint_report as SLR` (tests/test_skill_lint.py — incl.
private access like SLR._is_conv_tree_shape).
"""
from __future__ import annotations

import sys as _sys

from lib import skill_lint_report as _impl

# Rebind every public + private name onto this module so existing
# `import cli.skill_lint_report as SLR; SLR.<anything>` patterns resolve.
_self = _sys.modules[__name__]
for _name in dir(_impl):
    if not _name.startswith("__"):
        setattr(_self, _name, getattr(_impl, _name))

if __name__ == "__main__":
    _sys.exit(_impl.main())
