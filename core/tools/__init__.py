"""
Tools — registry, primitives, and domain plugin loader.

Importing this module:
    1. Loads ``core.tools.registry`` (empty registry + dispatch).
    2. Imports ``core.tools.primitives`` (registers 6 L0 atom ToolNodes).
    3. Imports the active domain plugin (loads all L1/L2 tools from JSON).

After import, the registry is fully populated and ``dispatch()`` can
execute any registered tool by name.

Layer ownership:
    L0 atoms        → core/tools/primitives.py  (registered in Python)
    L1/L2 tools     → state/tools/*.json         (loaded by loader.py)
    Python impls    → core/tools/actions.py, domains/drawio/operations.py
"""

from __future__ import annotations

import importlib

from core import config as _config
from core.tools.registry import (
    ToolNode, register, dispatch, print_tree,
    ALL_NODES, TOOL_CATALOG, resolve_tool, resolve_node,
)
from core.tools.save_tool import save_trace_as_tool, check_trace_success

# Side-effect: register L0 atom ToolNodes
from core.tools import primitives  # noqa: F401

# Load active domain plugin (side-effect: loads all JSON tools from state/tools/)
_domain_module = importlib.import_module(f"domains.{_config.domain()}.tools")


def _tool_fn(name: str):
    """Return the callable for a registered tool (convenience for direct use)."""
    return TOOL_CATALOG[name].fn


# Convenience aliases resolved from the live catalog after all tools are loaded
def __getattr__(name: str):
    if name in TOOL_CATALOG:
        return TOOL_CATALOG[name].fn
    raise AttributeError(f"module 'core.tools' has no attribute {name!r}")


__all__ = [
    # Registry
    "ToolNode", "register", "dispatch", "print_tree",
    "ALL_NODES", "TOOL_CATALOG", "resolve_tool", "resolve_node",
    # Trace saving
    "save_trace_as_tool", "check_trace_success",
]
