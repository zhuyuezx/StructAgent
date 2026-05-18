"""
Tools — registry, primitives, and domain plugin loader.

Importing this module:
    1. Loads ``core.tools.registry`` (empty registry + dispatch).
    2. Imports ``core.tools.primitives`` (registers L0 nodes).
    3. Imports ``domains.<config.domain()>.tools`` (registers L1+ nodes).

After import, the registry is fully populated and ``dispatch()`` can
execute any registered tool by name.
"""

from __future__ import annotations

import importlib

from core import config as _config
from core.tools.registry import (
    ToolNode, register, dispatch, print_tree,
    ALL_NODES, TOOL_CATALOG, resolve_tool, resolve_node,
)

# Side-effect import: registers L0 primitives
from core.tools import primitives  # noqa: F401

# Re-export common L0 aliases for direct script use
from core.tools.primitives import (
    place_shape, type_label, press_escape, press_enter, press_delete,
    select_all_text, click_empty_canvas, click_node, double_click_node,
    drag_node, drag_node_near, drag_node_to_zone, resize_node, hotkey, undo,
)

# Load active domain plugin (registers compounds via side effects)
_domain_module = importlib.import_module(f"domains.{_config.domain()}.tools")

# Re-export domain compound aliases if the plugin defines them
for _alias in (
    "place_and_label", "place_shape_then_edit_label",
    "edit_label", "delete_node", "move_and_deselect",
    "move_node_to_zone_and_deselect",
):
    if hasattr(_domain_module, _alias):
        globals()[_alias] = getattr(_domain_module, _alias)


__all__ = [
    "ToolNode", "register", "dispatch", "print_tree",
    "ALL_NODES", "TOOL_CATALOG", "resolve_tool", "resolve_node",
    "place_shape", "type_label", "press_escape", "press_enter", "press_delete",
    "select_all_text", "click_empty_canvas", "click_node", "double_click_node",
    "drag_node", "drag_node_near", "drag_node_to_zone",
    "resize_node", "hotkey", "undo",
    "place_and_label", "place_shape_then_edit_label",
    "edit_label", "delete_node", "move_and_deselect",
    "move_node_to_zone_and_deselect",
]
