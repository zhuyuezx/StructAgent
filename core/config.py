"""
Config — Centralized configuration loader.

Reads ``config.json`` (architectural settings) and ``state/ui_graph.json``
(persistent UI graph) from the project root.

Configuration values are available in two equivalent ways:

  1. **Namespace objects** (preferred for new code)::

         config.llm.model
         config.executor.pause
         config.explorer.screen_scale

  2. **Standalone accessor functions** (backward-compatible)::

         config.llm_model()
         config.executor_pause()
         config.screen_scale()
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Tuple

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
    """Re-read config.json and rebuild namespace objects."""
    global _cfg, llm, executor, explorer
    _cfg = _load(_CONFIG_PATH)
    llm = _build_llm(_cfg)
    executor = _build_executor(_cfg)
    explorer = _build_explorer(_cfg)


# ===========================================================================
# Structured namespace dataclasses
# ===========================================================================

@dataclass(frozen=True)
class LLMConfig:
    """LLM planner settings."""
    model: str
    max_steps: int


@dataclass(frozen=True)
class ExecutorConfig:
    """pyautogui / step timing settings."""
    failsafe: bool
    pause: float
    drag_duration: float
    type_interval: float
    step_cooldown: float
    countdown_seconds: int


@dataclass(frozen=True)
class ExplorerConfig:
    """Sidebar perception / icon-labeling settings."""
    screen_scale: int
    sidebar_region: Tuple[int, int, int, int]
    icon_size_range: Tuple[int, int]
    nms_distance: int
    model: str
    label_timeout: float
    label_max_retries: int


def _build_llm(cfg: Dict[str, Any]) -> LLMConfig:
    return LLMConfig(
        model=cfg["llm"]["model"],
        max_steps=cfg["llm"]["max_steps"],
    )


def _build_executor(cfg: Dict[str, Any]) -> ExecutorConfig:
    e = cfg["executor"]
    return ExecutorConfig(
        failsafe=e["failsafe"],
        pause=e["pause"],
        drag_duration=e["drag_duration"],
        type_interval=e["type_interval"],
        step_cooldown=e["step_cooldown"],
        countdown_seconds=e["countdown_seconds"],
    )


def _build_explorer(cfg: Dict[str, Any]) -> ExplorerConfig:
    e = cfg.get("explorer", {})
    r = e.get("sidebar_region", [0, 480, 380, 1120])
    isz = e.get("icon_size_range", [20, 70])
    return ExplorerConfig(
        screen_scale=e.get("screen_scale", 2),
        sidebar_region=(r[0], r[1], r[2], r[3]),
        icon_size_range=(isz[0], isz[1]),
        nms_distance=e.get("nms_distance", 20),
        model=e.get("model", "qwen3-vl:4b"),
        label_timeout=e.get("label_timeout", 30),
        label_max_retries=e.get("label_max_retries", 2),
    )


# Build once at import time
llm = _build_llm(_cfg)
executor = _build_executor(_cfg)
explorer = _build_explorer(_cfg)


# ===========================================================================
# Path helpers
# ===========================================================================

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


def scene_graph_dir() -> str:
    """Dedicated, gitignored folder for live scene-graph state.

    Always resolved against the project root (not the cwd), so notebooks,
    the CLI, and the API all read/write the *same* scene graph instead of
    each spawning a cwd-relative ``state/scene_graph.json``.
    """
    d = os.path.join(_PROJECT_ROOT, _cfg["paths"].get("scene_graph_dir", "scene_graph"))
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


def ui_graph() -> Dict[str, Any]:
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
    return {
        "UI_Elements": state.get("ui_elements", {}),
        "Canvas_Nodes": cal.get("canvas_nodes", []),
        "Canvas_Edges": cal.get("canvas_edges", []),
    }


def empty_canvas_point() -> Tuple[int, int]:
    pt = _cfg["calibration"]["empty_canvas_point"]
    return (pt[0], pt[1])


# ===========================================================================
# Backward-compatible accessor functions (thin aliases)
#
# These delegate to the namespace objects above.  New code should prefer
# ``config.llm.model`` over ``config.llm_model()``, etc.
# ===========================================================================

# LLM
def llm_model() -> str:
    return llm.model

def llm_max_steps() -> int:
    return llm.max_steps

# Executor
def executor_failsafe() -> bool:
    return executor.failsafe

def executor_pause() -> float:
    return executor.pause

def drag_duration() -> float:
    return executor.drag_duration

def type_interval() -> float:
    return executor.type_interval

def step_cooldown() -> float:
    return executor.step_cooldown

def countdown_seconds() -> int:
    return executor.countdown_seconds

# Explorer
def screen_scale() -> int:
    return explorer.screen_scale

def sidebar_region() -> Tuple[int, int, int, int]:
    return explorer.sidebar_region

def icon_size_range() -> Tuple[int, int]:
    return explorer.icon_size_range

def nms_distance() -> int:
    return explorer.nms_distance

def explorer_model() -> str:
    """Model for icon labeling (separate from planner model)."""
    return explorer.model

def label_timeout() -> float:
    return explorer.label_timeout

def label_max_retries() -> int:
    return explorer.label_max_retries


# ---------------------------------------------------------------------------
# Raw access
# ---------------------------------------------------------------------------

def config_path() -> str:
    return _CONFIG_PATH


def raw() -> Dict[str, Any]:
    """Return the full config dict (read-only copy)."""
    return dict(_cfg)
