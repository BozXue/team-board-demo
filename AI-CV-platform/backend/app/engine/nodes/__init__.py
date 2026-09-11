"""Node library. Importing a module registers its nodes."""

from __future__ import annotations

import importlib

_MODULES = (
    "input",
    "roi",
    "enhance",
    "filters",
    "segmentation",
    "morphology",
    "feature",
    "measure",
    "judge",
    "ai",
    "domain_ipsc",
    "domain_grain",
    "output",
)

_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    for name in _MODULES:
        importlib.import_module(f"{__name__}.{name}")
    _loaded = True
