"""
Registry — ToolNode dataclass, registration, and dispatch.

Domain-agnostic tool catalog. Primitives (level 0) self-register on
import of ``core.tools.primitives``. Domain compounds (level 1+)
self-register on import of ``domains.<name>.tools``.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pyautogui

from core import config

# ── Apply executor settings from config ───────────────────────────────────
pyautogui.FAILSAFE = config.executor_failsafe()
pyautogui.PAUSE = config.executor_pause()


# ===========================================================================
# ToolNode — the core abstraction
# ===========================================================================

@dataclass
class ToolNode:
    """
    A tool in the hierarchical tree.

    Leaf nodes (no children, no override) are level 0.
    Compound nodes auto-compute level = max(child.level) + 1.
    Actions that compose raw helper functions (not registered ToolNodes)
    set ``level_override`` to declare their level explicitly.
    """
    name: str
    fn: Callable[..., dict]
    params: List[str]
    needs_ui_graph: bool
    description: str
    children: List["ToolNode"] = field(default_factory=list)
    level_override: Optional[int] = None
    # Optional per-param type/description overrides. Keyed by param name; each
    # value is a ParamSpec dict (see core.tools.param_specs). When absent, the
    # central PARAM_SPECS map supplies a spec by param name. Used by the Planner
    # to fill the param space — see core/agents/planner.py.
    param_specs: Dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> int:
        if self.level_override is not None:
            return self.level_override
        if not self.children:
            return 0
        return max(c.level for c in self.children) + 1

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def tree_str(self, indent: int = 0) -> str:
        """Pretty-print the tool tree."""
        prefix = "  " * indent
        params_str = ", ".join(self.params) if self.params else ""
        s = f"{prefix}L{self.level} {self.name}({params_str})"
        for c in self.children:
            s += "\n" + c.tree_str(indent + 1)
        return s

    def execute(self, **kwargs) -> dict:
        """Execute this tool with the given parameters."""
        return self.fn(**kwargs)


# ===========================================================================
# Coordinate resolution helpers (used by primitives + compounds)
# ===========================================================================

def resolve_tool(ui_graph: Dict[str, Any], name: str) -> Tuple[int, int]:
    """Look up a sidebar tool's (x, y) from the UI graph."""
    elements = ui_graph.get("UI_Elements", {})
    if name not in elements:
        raise KeyError(f"Tool '{name}' not found. Available: {list(elements.keys())}")
    e = elements[name]
    return e["x"], e["y"]


def resolve_node(ui_graph: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """Find a canvas node by id or text label."""
    for node in ui_graph.get("Canvas_Nodes", []):
        if node.get("id") == ref or node.get("text") == ref:
            return node
    available = [(n.get("id"), n.get("text")) for n in ui_graph.get("Canvas_Nodes", [])]
    raise KeyError(f"Node '{ref}' not found. Available: {available}")


# ===========================================================================
# Registry — global catalog populated via register()
# ===========================================================================

ALL_NODES: List[ToolNode] = []
TOOL_CATALOG: Dict[str, ToolNode] = {}


def register(node: ToolNode) -> ToolNode:
    """Register a ToolNode in the global catalog. Returns the node."""
    if node.name in TOOL_CATALOG:
        # Replace in place (allows reload-style re-registration)
        idx = next((i for i, n in enumerate(ALL_NODES) if n.name == node.name), None)
        if idx is not None:
            ALL_NODES[idx] = node
    else:
        ALL_NODES.append(node)
    TOOL_CATALOG[node.name] = node
    return node


def print_tree() -> None:
    """Print all compound tool trees."""
    compounds = [n for n in ALL_NODES if not n.is_leaf]
    leaves = [n for n in ALL_NODES if n.is_leaf]
    print(f"\n  Leaf tools (L0): {len(leaves)}")
    for n in leaves:
        print(f"    {n.name}({', '.join(n.params)})")
    print(f"\n  Compound tools:")
    for n in compounds:
        print(f"\n{n.tree_str(indent=2)}")


# ===========================================================================
# Dispatch — unified executor for any level
# ===========================================================================

def _required_params(node: "ToolNode") -> List[str]:
    """Return the subset of ``node.params`` that have NO default value in
    the underlying function — i.e. the ones the caller actually has to
    provide. Params with defaults are treated as optional.
    """
    try:
        sig = inspect.signature(node.fn)
    except (TypeError, ValueError):
        return list(node.params)
    required: List[str] = []
    for p in node.params:
        param = sig.parameters.get(p)
        if param is None:
            required.append(p)
        elif param.default is inspect.Parameter.empty:
            required.append(p)
    return required


def dispatch(
    tool_name: str,
    params: dict,
    ui_graph: Optional[Dict[str, Any]] = None,
) -> dict:
    """Execute a tool by name. Works for any level."""
    node = TOOL_CATALOG.get(tool_name)
    if node is None:
        raise ValueError(f"Unknown tool '{tool_name}'. "
                         f"Available: {list(TOOL_CATALOG.keys())}")

    kw = dict(params)
    if node.needs_ui_graph:
        if ui_graph is None:
            ui_graph = config.ui_graph()
        kw["ui_graph"] = ui_graph

    # Only params without function-level defaults are actually required.
    required = _required_params(node)
    missing = [p for p in required if p not in kw]
    if missing:
        return {
            "status": "error", "tool": tool_name,
            "error": (
                f"Missing required params: {missing}. "
                f"Required: {required}. All accepted: {node.params}."
            ),
        }

    try:
        result = node.execute(**kw)
        result["level"] = node.level
        return result
    except Exception as e:
        return {"status": "error", "tool": tool_name, "error": str(e)}
