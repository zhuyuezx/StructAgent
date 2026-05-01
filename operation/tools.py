"""
Tools — Tree-structured hierarchical tool system for draw.io automation.

Each tool is a **ToolNode** with:
    - ``fn``        its own execution logic
    - ``children``  list of sub-tool nodes (empty = leaf)
    - ``level``     auto-computed from tree depth (leaf = 0)

Leaf nodes (level 0) wrap single atomic operations.
Compound nodes compose children and auto-derive their level.

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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pyautogui

from shared import config

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

    Leaf nodes (no children) are level 0.
    Compound nodes auto-compute level = max(child.level) + 1.
    """
    name: str
    fn: Callable[..., dict]
    params: List[str]
    needs_ui_graph: bool
    description: str
    children: List[ToolNode] = field(default_factory=list)

    @property
    def level(self) -> int:
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
# Internal coordinate resolution
# ===========================================================================

def _resolve_tool(ui_graph: Dict[str, Any], name: str) -> Tuple[int, int]:
    """Look up a sidebar tool's (x, y) from the UI graph."""
    elements = ui_graph.get("UI_Elements", {})
    if name not in elements:
        raise KeyError(f"Tool '{name}' not found. Available: {list(elements.keys())}")
    e = elements[name]
    return e["x"], e["y"]


def _resolve_node(ui_graph: Dict[str, Any], ref: str) -> Dict[str, Any]:
    """Find a canvas node by id or text label."""
    for node in ui_graph.get("Canvas_Nodes", []):
        if node.get("id") == ref or node.get("text") == ref:
            return node
    available = [(n.get("id"), n.get("text")) for n in ui_graph.get("Canvas_Nodes", [])]
    raise KeyError(f"Node '{ref}' not found. Available: {available}")


# Configurable pause between compound sub-steps
_STEP_PAUSE = 0.3


# ===========================================================================
# Leaf tool functions (level 0 — single atomic operations)
# ===========================================================================

def _fn_place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    x, y = _resolve_tool(ui_graph, tool_name)
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
    node = _resolve_node(ui_graph, node_ref)
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
    node = _resolve_node(ui_graph, node_ref)
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
    ref = _resolve_node(ui_graph, reference_node)
    return _fn_drag_node(ui_graph, node_ref, ref["x"] + offset_x, ref["y"] + offset_y)


def _fn_resize_node(
    ui_graph: Dict[str, Any], node_ref: str, new_width: int, new_height: int,
) -> dict:
    node = _resolve_node(ui_graph, node_ref)
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
# Registry — flat dict for dispatch, built from the node tree
# ===========================================================================

ALL_NODES: List[ToolNode] = [
    # Leaves (L0)
    N_PLACE_SHAPE, N_TYPE_LABEL, N_PRESS_ESCAPE, N_PRESS_ENTER,
    N_PRESS_DELETE, N_SELECT_ALL, N_CLICK_EMPTY, N_CLICK_NODE,
    N_DOUBLE_CLICK_NODE, N_DRAG_NODE, N_DRAG_NODE_NEAR,
    N_RESIZE_NODE, N_HOTKEY, N_UNDO,
    # Compound (auto-level)
    N_PLACE_AND_LABEL, N_EDIT_LABEL, N_DELETE_NODE, N_MOVE_AND_DESELECT,
]

TOOL_CATALOG: Dict[str, ToolNode] = {n.name: n for n in ALL_NODES}


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

    required = node.params
    missing = [p for p in required if p not in kw]
    if missing:
        return {
            "status": "error", "tool": tool_name,
            "error": f"Missing required params: {missing}. Expected: {required}",
        }

    try:
        result = node.execute(**kw)
        result["level"] = node.level
        return result
    except Exception as e:
        return {"status": "error", "tool": tool_name, "error": str(e)}


# ===========================================================================
# Public aliases for direct use in scripts
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
place_and_label = _fn_place_and_label
edit_label = _fn_edit_label
delete_node = _fn_delete_node
move_and_deselect = _fn_move_and_deselect
