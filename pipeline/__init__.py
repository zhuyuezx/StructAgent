"""
draw.io Hybrid Automation Pipeline.

Modules:
    config   — Centralized configuration (reads config.json)
    capture  — Screenshot capture
    tools    — Operational tools (place, move, type, etc.)
    llm      — LLM inference (tool selection)
    pipeline — Agentic control loop
"""

from .capture import screenshot
from .tools import (
    place_shape, type_label, press_escape, press_enter,
    click_empty_canvas, click_node, double_click_node,
    move_node, move_node_near, resize_node, hotkey, dispatch,
    TOOL_CATALOG,
)
from .llm import infer, build_prompt, parse_response
from .pipeline import run
from . import config
