"""
drawio compound tools (level 1+).

Domain-specific tool compositions for draw.io. Composes drawio operands
from ``domains.drawio.operations`` and generic actions from
``core.tools.actions`` into multi-step actions matching draw.io's
interaction model.

## draw.io interaction model

    Click sidebar shape → shape placed at default position (text cursor active)
    Type label → text goes into the shape
    Escape → exit text editing (shape still selected)
    Drag shape → move to desired position
    Drag handle → resize
    Click empty → deselect
"""

from __future__ import annotations

import time
from typing import Any, Dict

from core.tools.registry import ToolNode, register
# drawio L0 operands
from domains.drawio.operations import (  # noqa: F401 (side-effect: registers L0)
    _fn_place_shape, _fn_type_label, _fn_press_escape,
    N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE,
)
# generic L1 actions
from core.tools.actions import (
    _fn_click_empty_canvas, _fn_double_click_node, _fn_select_all,
    _fn_click_node, _fn_press_delete, _fn_drag_node,
    N_CLICK_EMPTY, N_DOUBLE_CLICK_NODE, N_SELECT_ALL,
    N_CLICK_NODE, N_PRESS_DELETE, N_DRAG_NODE,
)


# Configurable pause between compound sub-steps
_STEP_PAUSE = 0.3


# ===========================================================================
# Compound tool functions (auto-level from children)
# ===========================================================================

def _fn_place_and_label(
    ui_graph: Dict[str, Any], tool_name: str, label: str,
) -> dict:
    """Place a shape, label it, then deselect."""
    steps = []
    print(f"\n  [L{N_PLACE_AND_LABEL.level}] place_and_label('{tool_name}', '{label}')")
    steps.append(_fn_place_shape(ui_graph, tool_name))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_type_label(label))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_press_escape())
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_click_empty_canvas())
    ok = all(s.get("status") == "ok" for s in steps)
    return {"status": "ok" if ok else "partial", "tool": "place_and_label",
            "steps": steps}


def _fn_edit_label(
    ui_graph: Dict[str, Any], node_ref: str, new_label: str,
) -> dict:
    """Re-label an existing canvas node."""
    steps = []
    print(f"\n  [L{N_EDIT_LABEL.level}] edit_label('{node_ref}', '{new_label}')")
    steps.append(_fn_double_click_node(ui_graph, node_ref))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_select_all())
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_type_label(new_label))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_press_escape())
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_click_empty_canvas())
    ok = all(s.get("status") == "ok" for s in steps)
    return {"status": "ok" if ok else "partial", "tool": "edit_label",
            "steps": steps}


def _fn_delete_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    """Select and delete a canvas node."""
    steps = []
    print(f"\n  [L{N_DELETE_NODE.level}] delete_node('{node_ref}')")
    steps.append(_fn_click_node(ui_graph, node_ref))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_press_delete())
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_click_empty_canvas())
    ok = all(s.get("status") == "ok" for s in steps)
    return {"status": "ok" if ok else "partial", "tool": "delete_node",
            "steps": steps}


def _fn_move_and_deselect(
    ui_graph: Dict[str, Any], node_ref: str, target_x: int, target_y: int,
) -> dict:
    """Drag a node to a position and deselect."""
    steps = []
    print(f"\n  [L{N_MOVE_AND_DESELECT.level}] move_and_deselect('{node_ref}')")
    steps.append(_fn_drag_node(ui_graph, node_ref, target_x, target_y))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_click_empty_canvas())
    ok = all(s.get("status") == "ok" for s in steps)
    return {"status": "ok" if ok else "partial", "tool": "move_and_deselect",
            "steps": steps}


# ===========================================================================
# Compound ToolNodes (level auto-derived from children)
# ===========================================================================

N_PLACE_AND_LABEL = ToolNode(
    name="place_and_label", fn=_fn_place_and_label,
    params=["tool_name", "label"], needs_ui_graph=True,
    description="Place a shape, label it, then deselect.",
    children=[N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE, N_CLICK_EMPTY],
)

N_EDIT_LABEL = ToolNode(
    name="edit_label", fn=_fn_edit_label,
    params=["node_ref", "new_label"], needs_ui_graph=True,
    description="Re-label an existing canvas node.",
    children=[N_DOUBLE_CLICK_NODE, N_SELECT_ALL, N_TYPE_LABEL,
              N_PRESS_ESCAPE, N_CLICK_EMPTY],
)

N_DELETE_NODE = ToolNode(
    name="delete_node", fn=_fn_delete_node,
    params=["node_ref"], needs_ui_graph=True,
    description="Select and delete a canvas node.",
    children=[N_CLICK_NODE, N_PRESS_DELETE, N_CLICK_EMPTY],
)

N_MOVE_AND_DESELECT = ToolNode(
    name="move_and_deselect", fn=_fn_move_and_deselect,
    params=["node_ref", "target_x", "target_y"], needs_ui_graph=True,
    description="Drag a node and deselect.",
    children=[N_DRAG_NODE, N_CLICK_EMPTY],
)


# ===========================================================================
# Self-register compound tools with the framework registry
# ===========================================================================

for _n in (N_PLACE_AND_LABEL, N_EDIT_LABEL, N_DELETE_NODE, N_MOVE_AND_DESELECT):
    register(_n)


# ===========================================================================
# Public function aliases (for direct script use)
# ===========================================================================

place_and_label = _fn_place_and_label
edit_label = _fn_edit_label
delete_node = _fn_delete_node
move_and_deselect = _fn_move_and_deselect

# Operand aliases re-exported so core/tools/__init__.py can pick them up
# via the domain module handle (avoids core → domains import direction).
place_shape = _fn_place_shape
type_label = _fn_type_label
press_escape = _fn_press_escape
click_empty_canvas = _fn_click_empty_canvas
