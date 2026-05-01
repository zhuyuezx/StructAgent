"""
Config — Centralized configuration loader.

Reads ``config.json`` (architectural settings) and ``icons.json``
(auto-detected UI elements) from the project root.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Locate files relative to this file (project_root/<shared>/config.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")
_ICONS_PATH = os.path.join(_PROJECT_ROOT, "exploration", "icons.json")


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


# ---------------------------------------------------------------------------
# Icons data (from exploration/icons.json)
# ---------------------------------------------------------------------------

def icons_path() -> str:
    return _ICONS_PATH


def load_icons() -> Dict[str, Any]:
    """Load UI elements from icons.json.  Returns {} if file missing."""
    if not os.path.exists(_ICONS_PATH):
        return {}
    return _load(_ICONS_PATH)


def ui_graph() -> Dict[str, Any]:
    """
    Return the UI graph dict merging icons.json elements with
    config.json calibration data.

    Schema:
        {
          "UI_Elements": {"name": {"x": int, "y": int, ...}, ...},
          "Canvas_Nodes": [...],
          "Canvas_Edges": [...]
        }
    """
    icons = load_icons()
    cal = _cfg.get("calibration", {})
    return {
        "UI_Elements": icons.get("ui_elements", {}),
        "Canvas_Nodes": cal.get("canvas_nodes", []),
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
# Raw access
# ---------------------------------------------------------------------------

def config_path() -> str:
    return _CONFIG_PATH


def raw() -> Dict[str, Any]:
    """Return the full config dict (read-only copy)."""
    return dict(_cfg)
