"""Extractors — reverse-engineer harness pipeline documents from existing project code.

Lazy-loaded registry pattern. Canonical with `lib.providers` / `lib.workers`:
each module exposes a single uppercase capability constant (`EXTRACTOR =
<Class>`), and `__init__` only loads concrete modules on demand.

Public API:
- `list_extractors()`: canonical names in registry order.
- `get_extractor(name)`: instantiate by canonical name.
- `iter_extractors()`: yield instances in registry order.

Backward-compat:
- `REGISTRY`: module attribute that returns a list of extractor *classes* (in
  registry order). Resolved lazily via `__getattr__`. Existing callers
  (cli.project_analyze, cli.reverse_engineer, tests.test_extractors) keep
  working without changes; new code should prefer `iter_extractors()`.

Extension (OCP):
- Create `lib/extractors/<name>.py` exposing `EXTRACTOR = YourClass`.
- Add `(canonical_name, "module_name")` to `_REGISTRY_ORDER` below.
- No other file changes required.
"""
from __future__ import annotations

from importlib import import_module
from typing import Iterator

from .base import Extractor, ExtractionResult


# Order matters — CLI tries extractors in this sequence.
# (canonical extractor name, module under this package)
_REGISTRY_ORDER: tuple[tuple[str, str], ...] = (
    ("convention", "convention"),
    ("er", "er"),
    ("logical", "logical"),
    ("doc_classifier", "doc_classifier"),
)


def list_extractors() -> list[str]:
    """Canonical extractor names in registry order."""
    return [name for name, _ in _REGISTRY_ORDER]


def _load_class(module_name: str) -> type[Extractor]:
    mod = import_module(f"{__name__}.{module_name}")
    cls = getattr(mod, "EXTRACTOR", None)
    if cls is None:
        raise RuntimeError(
            f"Extractor module {module_name!r} does not export EXTRACTOR"
        )
    return cls


def get_extractor(name: str) -> Extractor:
    """Instantiate an extractor by canonical name. Raises KeyError on unknown."""
    n = name.lower()
    for canonical, module_name in _REGISTRY_ORDER:
        if canonical == n:
            return _load_class(module_name)()
    raise KeyError(
        f"Unknown extractor {name!r}. Known: {list_extractors()}"
    )


def iter_extractors() -> Iterator[Extractor]:
    """Yield extractor instances in registry order (lazy import per module)."""
    for canonical, module_name in _REGISTRY_ORDER:
        yield _load_class(module_name)()


# Backward-compat module attribute. Resolves to a list of class objects on
# first access; raises AttributeError otherwise so typos still fail loudly.
def __getattr__(name: str):
    if name == "REGISTRY":
        return [_load_class(module_name) for _, module_name in _REGISTRY_ORDER]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Extractor",
    "ExtractionResult",
    "get_extractor",
    "iter_extractors",
    "list_extractors",
]
