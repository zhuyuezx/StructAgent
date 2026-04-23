"""
Config — Centralized configuration loader.

Reads ``config.json`` from the project root and exposes typed accessors
used by every other module.  All hardcoded values (paths, calibration
coordinates, model name, executor tuning) live in that single file.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Locate config.json relative to this file (project_root/config.json)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")


def _load() -> Dict[str, Any]:
    with open(_CONFIG_PATH) as f:
        return json.load(f)


_cfg: Dict[str, Any] = _load()


def reload() -> None:
    """Re-read config.json (e.g. after calibration updates)."""
    global _cfg
    _cfg = _load()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def screenshots_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"]["screenshots_dir"])
    os.makedirs(d, exist_ok=True)
    return d


def test_output_dir() -> str:
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"]["test_output_dir"])
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Calibration data → UI graph
# ---------------------------------------------------------------------------

def ui_graph() -> Dict[str, Any]:
    """
    Return the calibration data formatted as a UI graph dict.

    Schema:
        {
          "UI_Elements": {"name": {"x": int, "y": int, ...}, ...},
          "Canvas_Nodes": [...],
          "Canvas_Edges": [...]
        }
    """
    cal = _cfg["calibration"]
    return {
        "UI_Elements": cal["ui_elements"],
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
# Raw access (for modules that need the full dict)
# ---------------------------------------------------------------------------

def raw() -> Dict[str, Any]:
    """Return the full config dict (read-only copy)."""
    return dict(_cfg)
