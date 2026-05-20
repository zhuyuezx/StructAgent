"""
Tools — registry, primitives, and domain plugin loader.

Importing this module:
    1. Loads ``core.tools.registry`` (empty registry + dispatch).
    2. Imports ``core.tools.primitives`` (atom helpers + shared utilities).
    3. Imports ``core.tools.actions`` (registers generic L1 nodes).
    4. Imports ``domains.<config.domain()>.tools`` (registers domain L0 + L1+).

After import, the registry is fully populated and ``dispatch()`` can
execute any registered tool by name.

Layer ownership:
    L0 drawio operands  → domains/drawio/operations.py
    L1 generic actions  → core/tools/actions.py
    L1+ drawio compounds → domains/drawio/tools.py
"""

from __future__ import annotations

import importlib

from core import config as _config
from core.tools.registry import (
    ToolNode, register, dispatch, print_tree,
    ALL_NODES, TOOL_CATALOG, resolve_tool, resolve_node,
)

# Side-effect imports: register shared atoms/helpers, then generic L1 actions.
from core.tools import primitives  # noqa: F401
from core.tools import actions     # noqa: F401

# Generic L1 aliases for direct script use
from core.tools.actions import (
    _fn_click_empty_canvas as click_empty_canvas,
    _fn_press_enter as press_enter,
    _fn_press_delete as press_delete,
    _fn_select_all as select_all_text,
    _fn_click_node as click_node,
    _fn_double_click_node as double_click_node,
    _fn_drag_node as drag_node,
    _fn_drag_node_near as drag_node_near,
    _fn_resize_node as resize_node,
    _fn_hotkey as hotkey,
    _fn_undo as undo,
)

# Load active domain plugin (side-effect: registers L0 drawio ops + compounds)
_domain_module = importlib.import_module(f"domains.{_config.domain()}.tools")

# Extract both compound and operand aliases from the domain module
for _alias in (
    "place_and_label", "edit_label", "delete_node", "move_and_deselect",
    "place_shape", "type_label", "press_escape", "click_empty_canvas",
):
    if hasattr(_domain_module, _alias):
        globals()[_alias] = getattr(_domain_module, _alias)


__all__ = [
    # Registry
    "ToolNode", "register", "dispatch", "print_tree",
    "ALL_NODES", "TOOL_CATALOG", "resolve_tool", "resolve_node",
    # Generic L1 actions
    "click_empty_canvas", "press_enter", "press_delete", "select_all_text",
    "click_node", "double_click_node", "drag_node", "drag_node_near",
    "resize_node", "hotkey", "undo",
    # drawio operands (set dynamically from domain module)
    "place_shape", "type_label", "press_escape",
    # drawio compounds (set dynamically from domain module)
    "place_and_label", "edit_label", "delete_node", "move_and_deselect",
]
