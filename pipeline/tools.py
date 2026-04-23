"""
Tools — Operational tools for draw.io automation.

Each public function is a self-contained tool that:
    1. Resolves coordinates from the UI graph (via config or argument).
    2. Executes the OS-level action via pyautogui.

## draw.io interaction model

    Click sidebar shape → shape placed at default position (text cursor active)
    Type label → text goes into the shape
    Escape → exit text editing (shape still selected)
    Drag shape → move to desired position
    Drag handle → resize
    Click empty → deselect

There is NO drag-to-draw mode.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

import pyautogui

from . import config

# ── Apply executor settings from config ───────────────────────────────────
pyautogui.FAILSAFE = config.executor_failsafe()
pyautogui.PAUSE = config.executor_pause()


# ---------------------------------------------------------------------------
# Internal coordinate resolution
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Tools — each is a complete operation
# ---------------------------------------------------------------------------

def place_shape(ui_graph: Dict[str, Any], tool_name: str) -> dict:
    """
    Click a sidebar shape to place it on the canvas.

    After this call the shape exists at a default position with its text
    cursor active — call ``type_label()`` next.
    """
    x, y = _resolve_tool(ui_graph, tool_name)
    print(f"[TOOL] place_shape('{tool_name}') → click ({x}, {y})")
    pyautogui.click(x, y)
    return {"status": "ok", "tool": "place_shape", "tool_name": tool_name, "x": x, "y": y}


def type_label(text: str) -> dict:
    """
    Type text into the currently active shape.

    Works immediately after ``place_shape()`` (cursor is auto-active)
    or after ``double_click_node()``.
    """
    interval = config.type_interval()
    print(f"[TOOL] type_label('{text}')")
    pyautogui.typewrite(text, interval=interval)
    return {"status": "ok", "tool": "type_label", "text": text}


def press_escape() -> dict:
    """Press Escape — exits text editing or deselects."""
    print("[TOOL] press_escape")
    pyautogui.hotkey("Escape")
    return {"status": "ok", "tool": "press_escape"}


def press_enter() -> dict:
    """Press Enter — confirms current input."""
    print("[TOOL] press_enter")
    pyautogui.hotkey("Return")
    return {"status": "ok", "tool": "press_enter"}


def click_empty_canvas() -> dict:
    """Click an empty canvas area to deselect everything."""
    x, y = config.empty_canvas_point()
    print(f"[TOOL] click_empty_canvas → ({x}, {y})")
    pyautogui.click(x, y)
    return {"status": "ok", "tool": "click_empty_canvas", "x": x, "y": y}


def click_node(ui_graph: Dict[str, Any], node_ref: str, clicks: int = 1) -> dict:
    """Click (or double-click) an existing canvas node."""
    node = _resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    print(f"[TOOL] click_node('{node_ref}', clicks={clicks}) → ({x}, {y})")
    pyautogui.click(x, y, clicks=clicks)
    return {"status": "ok", "tool": "click_node", "node_ref": node_ref, "x": x, "y": y}


def double_click_node(ui_graph: Dict[str, Any], node_ref: str) -> dict:
    """Double-click a node to enter text-edit mode."""
    return click_node(ui_graph, node_ref, clicks=2)


def move_node(
    ui_graph: Dict[str, Any],
    node_ref: str,
    target_x: int,
    target_y: int,
) -> dict:
    """
    Drag a node from its current (CV-detected) position to a new position.

    The node must not be in text-edit mode — press Escape first.
    """
    node = _resolve_node(ui_graph, node_ref)
    sx, sy = node["x"], node["y"]
    dur = config.drag_duration()
    print(f"[TOOL] move_node('{node_ref}') → drag ({sx},{sy}) → ({target_x},{target_y})")
    pyautogui.moveTo(sx, sy)
    pyautogui.mouseDown()
    pyautogui.moveTo(target_x, target_y, duration=dur)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "move_node", "node_ref": node_ref,
            "from": [sx, sy], "to": [target_x, target_y]}


def move_node_near(
    ui_graph: Dict[str, Any],
    node_ref: str,
    reference_node: str,
    offset_x: int = 200,
    offset_y: int = 0,
) -> dict:
    """Move *node_ref* to a position relative to *reference_node*."""
    ref = _resolve_node(ui_graph, reference_node)
    target_x = ref["x"] + offset_x
    target_y = ref["y"] + offset_y
    return move_node(ui_graph, node_ref, target_x, target_y)


def resize_node(
    ui_graph: Dict[str, Any],
    node_ref: str,
    new_width: int,
    new_height: int,
) -> dict:
    """Resize a node by dragging its bottom-right handle."""
    node = _resolve_node(ui_graph, node_ref)
    x, y = node["x"], node["y"]
    w, h = node.get("w", 120), node.get("h", 60)

    handle_x = x + w // 2
    handle_y = y + h // 2
    new_hx = x + new_width // 2
    new_hy = y + new_height // 2

    print(f"[TOOL] resize_node('{node_ref}', {new_width}×{new_height})")
    pyautogui.click(x, y)
    time.sleep(0.2)
    pyautogui.moveTo(handle_x, handle_y)
    pyautogui.mouseDown()
    pyautogui.moveTo(new_hx, new_hy, duration=0.3)
    pyautogui.mouseUp()
    return {"status": "ok", "tool": "resize_node", "node_ref": node_ref,
            "new_size": [new_width, new_height]}


def hotkey(*keys: str) -> dict:
    """Press a keyboard shortcut (e.g. Ctrl+Z)."""
    combo = " + ".join(keys)
    print(f"[TOOL] hotkey({combo})")
    pyautogui.hotkey(*keys)
    return {"status": "ok", "tool": "hotkey", "keys": list(keys)}


# ---------------------------------------------------------------------------
# Tool catalog — used by the LLM module to present available operations
# ---------------------------------------------------------------------------

TOOL_CATALOG = {
    "place_shape": {
        "fn": place_shape,
        "params": ["tool_name"],
        "needs_ui_graph": True,
        "description": "Click a sidebar shape to place it on the canvas.",
    },
    "type_label": {
        "fn": type_label,
        "params": ["text"],
        "needs_ui_graph": False,
        "description": "Type a text label into the active shape.",
    },
    "press_escape": {
        "fn": press_escape,
        "params": [],
        "needs_ui_graph": False,
        "description": "Press Escape to exit text editing or deselect.",
    },
    "press_enter": {
        "fn": press_enter,
        "params": [],
        "needs_ui_graph": False,
        "description": "Press Enter to confirm input.",
    },
    "click_empty_canvas": {
        "fn": click_empty_canvas,
        "params": [],
        "needs_ui_graph": False,
        "description": "Click empty canvas area to deselect.",
    },
    "click_node": {
        "fn": click_node,
        "params": ["node_ref", "clicks"],
        "needs_ui_graph": True,
        "description": "Click on an existing canvas node.",
    },
    "double_click_node": {
        "fn": double_click_node,
        "params": ["node_ref"],
        "needs_ui_graph": True,
        "description": "Double-click a node to enter text-edit mode.",
    },
    "move_node": {
        "fn": move_node,
        "params": ["node_ref", "target_x", "target_y"],
        "needs_ui_graph": True,
        "description": "Drag a node to a new position.",
    },
    "move_node_near": {
        "fn": move_node_near,
        "params": ["node_ref", "reference_node", "offset_x", "offset_y"],
        "needs_ui_graph": True,
        "description": "Move a node to a position relative to another node.",
    },
    "resize_node": {
        "fn": resize_node,
        "params": ["node_ref", "new_width", "new_height"],
        "needs_ui_graph": True,
        "description": "Resize a node by dragging its handle.",
    },
    "hotkey": {
        "fn": hotkey,
        "params": ["keys"],
        "needs_ui_graph": False,
        "description": "Press a keyboard shortcut.",
    },
}


def dispatch(tool_name: str, params: dict, ui_graph: Optional[Dict[str, Any]] = None) -> dict:
    """
    Execute a tool by name.  Injects ``ui_graph`` for tools that need it.
    """
    entry = TOOL_CATALOG.get(tool_name)
    if entry is None:
        raise ValueError(f"Unknown tool '{tool_name}'. Available: {list(TOOL_CATALOG.keys())}")

    kw = dict(params)
    if entry["needs_ui_graph"]:
        if ui_graph is None:
            ui_graph = config.ui_graph()
        kw["ui_graph"] = ui_graph

    return entry["fn"](**kw)
