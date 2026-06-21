#!/usr/bin/env python3
"""Thin CLI wrapper — logic lives in lib.debate_doubts.

Moved to lib/ on 2026-06-21 to fix a layer inversion: handlers/ (init.py) was
importing UP into cli/. count_pending only depended on lib.advisory_ack +
lib.paths, so it belongs in lib; init.py now imports lib.debate_doubts directly.

This wrapper re-exports the full module namespace so the existing surface keeps
working: `python -m cli.debate_doubts ...` (skill-lint-workflow.md),
`python -m cli.advisory_ack debate_doubts <sid>` alias, and
`import cli.debate_doubts as DD` (tests/test_advisory_ack.py — DD.main).
"""
from __future__ import annotations

import sys as _sys

from lib import debate_doubts as _impl

_self = _sys.modules[__name__]
for _name in dir(_impl):
    if not _name.startswith("__"):
        setattr(_self, _name, getattr(_impl, _name))

if __name__ == "__main__":
    _sys.exit(_impl.main())
