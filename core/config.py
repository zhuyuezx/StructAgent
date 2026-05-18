"""
Config — Centralized configuration loader.

Reads ``config.json`` (architectural settings) and ``state/ui_graph.json``
(persistent UI graph) from the project root.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Locate files relative to this file (project_root/core/config.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")


def _load(path: str) -> Dict[str, Any]:
    with open(path) as f:
        return json.load(f)


_cfg: Dict[str, Any] = _load(_CONFIG_PATH)


def reload() -> None:
    """Re-read config.json."""
    global _cfg
    _cfg = _load(_CONFIG_PATH)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def project_root() -> str:
    return _PROJECT_ROOT


def screenshots_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"]["screenshots_dir"])
    os.makedirs(d, exist_ok=True)
    return d


def test_output_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"]["test_output_dir"])
    os.makedirs(d, exist_ok=True)
    return d


def state_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"].get("state_dir", "state"))
    os.makedirs(d, exist_ok=True)
    return d


def ui_graph_path() -> str:
    return os.path.join(state_dir(), _cfg["paths"].get("ui_graph_file", "ui_graph.json"))


# ---------------------------------------------------------------------------
# Domain plugin
# ---------------------------------------------------------------------------

def domain() -> str:
    """Active domain plugin name (e.g. 'drawio')."""
    return _cfg.get("domain", "drawio")


# ---------------------------------------------------------------------------
# UI graph (from state/ui_graph.json)
# ---------------------------------------------------------------------------

def load_ui_state() -> Dict[str, Any]:
    """Load the persisted UI graph file. Returns {} if missing."""
    path = ui_graph_path()
    if not os.path.exists(path):
        return {}
    return _load(path)


def ui_graph(
    *,
    screenshot_path: str | None = None,
    canvas_nodes: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    Return the runtime UI graph dict, merging persisted UI state with
    config.json calibration data.

    Schema (Phase 0 — preserved from prior layout):
        {
          "UI_Elements": {"name": {"x": int, "y": int, ...}, ...},
          "Canvas_Nodes": [...],
          "Canvas_Edges": [...]
        }
    """
    state = load_ui_state()
    cal = _cfg.get("calibration", {})
    if canvas_nodes is None:
        canvas_nodes = cal.get("canvas_nodes", [])
        if screenshot_path is not None:
            from core.perception.canvas import observe_canvas
            canvas_nodes = observe_canvas(screenshot_path)
    return {
        "UI_Elements": state.get("ui_elements", {}),
        "Canvas_Nodes": canvas_nodes,
        "Canvas_Edges": cal.get("canvas_edges", []),
    }


def empty_canvas_point() -> Tuple[int, int]:
    pt = _cfg["calibration"]["empty_canvas_point"]
    return (pt[0], pt[1])


# ---------------------------------------------------------------------------
# LLM settings
# ---------------------------------------------------------------------------

def llm_model() -> str:
    return _cfg["llm"]["model"]


def llm_max_steps() -> int:
    return _cfg["llm"]["max_steps"]


# ---------------------------------------------------------------------------
# Executor settings
# ---------------------------------------------------------------------------

def executor_failsafe() -> bool:
    return _cfg["executor"]["failsafe"]


def executor_pause() -> float:
    return _cfg["executor"]["pause"]


def drag_duration() -> float:
    return _cfg["executor"]["drag_duration"]


def type_interval() -> float:
    return _cfg["executor"]["type_interval"]


def step_cooldown() -> float:
    return _cfg["executor"]["step_cooldown"]


def countdown_seconds() -> int:
    return _cfg["executor"]["countdown_seconds"]


# ---------------------------------------------------------------------------
# Explorer settings
# ---------------------------------------------------------------------------

def screen_scale() -> int:
    return _cfg.get("explorer", {}).get("screen_scale", 2)


def sidebar_region() -> Tuple[int, int, int, int]:
    r = _cfg.get("explorer", {}).get("sidebar_region", [0, 480, 380, 1120])
    return tuple(r)


def canvas_region() -> Tuple[int, int, int, int] | None:
    r = _cfg.get("explorer", {}).get("canvas_region")
    if r is None:
        return None
    return tuple(r)


def icon_size_range() -> Tuple[int, int]:
    r = _cfg.get("explorer", {}).get("icon_size_range", [20, 70])
    return (r[0], r[1])


def nms_distance() -> int:
    return _cfg.get("explorer", {}).get("nms_distance", 20)


def explorer_model() -> str:
    """Model for icon labeling (separate from planner model)."""
    return _cfg.get("explorer", {}).get("model", "qwen3-vl:4b")


def label_timeout() -> float:
    return _cfg.get("explorer", {}).get("label_timeout", 30)


def label_max_retries() -> int:
    return _cfg.get("explorer", {}).get("label_max_retries", 2)


# ---------------------------------------------------------------------------
# Tool families
# ---------------------------------------------------------------------------

def tool_families() -> Dict[str, Dict[str, Any]]:
    """Configured sidebar tool families and defaults."""
    families = _cfg.get("tool_families", {})
    return dict(families)


# ---------------------------------------------------------------------------
# Raw access
# ---------------------------------------------------------------------------

def config_path() -> str:
    return _CONFIG_PATH


def raw() -> Dict[str, Any]:
    """Return the full config dict (read-only copy)."""
    return dict(_cfg)
