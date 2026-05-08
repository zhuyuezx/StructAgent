"""
Primitives — L0 atomic tools.

Domain-agnostic mouse/keyboard primitives. Each function wraps a single
``pyautogui`` call and returns a status dict. ToolNodes are self-registered
at import time.
"""

from __future__ import annotations

import time
from typing import Any, Dict

import pyautogui

from core import config
from core.tools.registry import (
    ToolNode, register, resolve_tool, resolve_node,
)


# ===========================================================================
# Leaf tool functions (level 0 — single atomic operations)
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    x, y = resolve_tool(ui_graph, tool_name)
    print(f"  [L0] place_shape('{tool_name}') → click ({x}, {y})")
    pyautogui.click(x, y)
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name,
            "x": x, "y": y}


def _fn_type_label(text: str) -> dict:
    print(f"  [L0] type_label('{text}')")
    pyautogui.typewrite(text, interval=config.type_interval())
    return {"status": "ok", "tool": "type_label", "text": text}


def _fn_press_escape() -> dict:
    print("  [L0] press_escape")
    pyautogui.hotkey("Escape")
    return {"status": "ok", "tool": "press_escape"}


def _fn_press_enter() -> dict:
    print("  [L0] press_enter")
    pyautogui.hotkey("Return")
    return {"status": "ok", "tool": "press_enter"}


def _fn_press_delete() -> dict:
    print("  [L0] press_delete")
    pyautogui.hotkey("BackSpace")
    return {"status": "ok", "tool": "press_delete"}


def _fn_select_all() -> dict:
    print("  [L0] select_all (Cmd+A)")
    pyautogui.hotkey("command", "a")
    return {"status": "ok", "tool": "select_all"}


def _fn_click_empty_canvas() -> dict:
    x, y = config.empty_canvas_point()
    print(f"  [L0] click_empty_canvas → ({x}, {y})")
    pyautogui.click(x, y)
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def _fn_click_node(ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1) -> dict:
    node = resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    print(f"  [L0] click_node('{node_ref}', clicks={clicks}) → ({x}, {y})")
    pyautogui.click(x, y, clicks=clicks)
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref,
            "x": x, "y": y}


def _fn_double_click_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    return _fn_click_node(ui_graph, node_ref, clicks=2)


def _fn_drag_node(
    ui_graph: Dict[str, Any], node_ref: str, target_x: int, target_y: int,
) -> dict:
    node = resolve_node(ui_graph, node_ref)
    sx, sy = node["x"], node["y"]
    dur = config.drag_duration()
    print(f"  [L0] drag_node('{node_ref}') → ({sx},{sy}) → ({target_x},{target_y})")
    pyautogui.moveTo(sx, sy)
    pyautogui.mouseDown()
    pyautogui.moveTo(target_x, target_y, duration=dur)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "drag_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def _fn_drag_node_near(
    ui_graph: Dict[str, Any], node_ref: str, reference_node: str,
    offset_x: int = 200, offset_y: int = 0,
) -> dict:
    ref = resolve_node(ui_graph, reference_node)
    return _fn_drag_node(ui_graph, node_ref, ref["x"] + offset_x, ref["y"] + offset_y)


def _fn_resize_node(
    ui_graph: Dict[str, Any], node_ref: str, new_width: int, new_height: int,
) -> dict:
    node = resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    w, h = node.get("w", 120), node.get("h", 60)
    handle_x, handle_y = x + w // 2, y + h // 2
    new_hx, new_hy = x + new_width // 2, y + new_height // 2
    print(f"  [L0] resize_node('{node_ref}', {new_width}×{new_height})")
    pyautogui.click(x, y)
    time.sleep(0.2)
    pyautogui.moveTo(handle_x, handle_y)
    pyautogui.mouseDown()
    pyautogui.moveTo(new_hx, new_hy, duration=0.3)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "resize_node", "node_ref": node_ref,
            "new_size": [new_width, new_height]}


def _fn_hotkey(*keys: str) -> dict:
    combo = " + ".join(keys)
    print(f"  [L0] hotkey({combo})")
    pyautogui.hotkey(*keys)
    return {"status": "ok", "tool": "hotkey", "keys": list(keys)}


def _fn_undo() -> dict:
    print("  [L0] undo (Cmd+Z)")
    pyautogui.hotkey("command", "z")
    return {"status": "ok", "tool": "undo"}


# ===========================================================================
# Leaf ToolNodes (level 0)
# ===========================================================================

N_PLACE_SHAPE = ToolNode(
    name="place_shape", fn=_fn_place_shape,
    params=["tool_name"], needs_ui_graph=True,
    description="Click a sidebar shape to place it on the canvas.",
)

N_TYPE_LABEL = ToolNode(
    name="type_label", fn=_fn_type_label,
    params=["text"], needs_ui_graph=False,
    description="Type a text label into the active shape.",
)

N_PRESS_ESCAPE = ToolNode(
    name="press_escape", fn=_fn_press_escape,
    params=[], needs_ui_graph=False,
    description="Press Escape to exit text editing or deselect.",
)

N_PRESS_ENTER = ToolNode(
    name="press_enter", fn=_fn_press_enter,
    params=[], needs_ui_graph=False,
    description="Press Enter to confirm input.",
)

N_PRESS_DELETE = ToolNode(
    name="press_delete", fn=_fn_press_delete,
    params=[], needs_ui_graph=False,
    description="Press Delete to remove the selected element.",
)

N_SELECT_ALL = ToolNode(
    name="select_all", fn=_fn_select_all,
    params=[], needs_ui_graph=False,
    description="Select all text in active field (Cmd+A).",
)

N_CLICK_EMPTY = ToolNode(
    name="click_empty_canvas", fn=_fn_click_empty_canvas,
    params=[], needs_ui_graph=False,
    description="Click empty canvas area to deselect.",
)

N_CLICK_NODE = ToolNode(
    name="click_node", fn=_fn_click_node,
    params=["node_ref", "clicks"], needs_ui_graph=True,
    description="Click on an existing canvas node.",
)

N_DOUBLE_CLICK_NODE = ToolNode(
    name="double_click_node", fn=_fn_double_click_node,
    params=["node_ref"], needs_ui_graph=True,
    description="Double-click a node to enter text-edit mode.",
)

N_DRAG_NODE = ToolNode(
    name="drag_node", fn=_fn_drag_node,
    params=["node_ref", "target_x", "target_y"], needs_ui_graph=True,
    description="Drag a node to a new position.",
)

N_DRAG_NODE_NEAR = ToolNode(
    name="drag_node_near", fn=_fn_drag_node_near,
    params=["node_ref", "reference_node", "offset_x", "offset_y"],
    needs_ui_graph=True,
    description="Move a node to a position relative to another node.",
)

N_RESIZE_NODE = ToolNode(
    name="resize_node", fn=_fn_resize_node,
    params=["node_ref", "new_width", "new_height"], needs_ui_graph=True,
    description="Resize a node by dragging its handle.",
)

N_HOTKEY = ToolNode(
    name="hotkey", fn=_fn_hotkey,
    params=["keys"], needs_ui_graph=False,
    description="Press a keyboard shortcut.",
)

N_UNDO = ToolNode(
    name="undo", fn=_fn_undo,
    params=[], needs_ui_graph=False,
    description="Undo last action (Cmd+Z).",
)


# ===========================================================================
# Self-register all primitives
# ===========================================================================

for _n in (
    N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE, N_PRESS_ENTER,
    N_PRESS_DELETE, N_SELECT_ALL, N_CLICK_EMPTY, N_CLICK_NODE,
    N_DOUBLE_CLICK_NODE, N_DRAG_NODE, N_DRAG_NODE_NEAR,
    N_RESIZE_NODE, N_HOTKEY, N_UNDO,
):
    register(_n)


# ===========================================================================
# Public function aliases (for direct script use)
# ===========================================================================

place_shape = _fn_place_shape
type_label = _fn_type_label
press_escape = _fn_press_escape
press_enter = _fn_press_enter
press_delete = _fn_press_delete
select_all_text = _fn_select_all
click_empty_canvas = _fn_click_empty_canvas
click_node = _fn_click_node
double_click_node = _fn_double_click_node
drag_node = _fn_drag_node
drag_node_near = _fn_drag_node_near
resize_node = _fn_resize_node
hotkey = _fn_hotkey
undo = _fn_undo
