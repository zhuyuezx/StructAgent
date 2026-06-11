"""
Config — Centralized configuration loader.

Reads ``config.json`` (architectural settings) and the active interface's
``state/ui_graph.<domain>.json`` (persistent UI graph) from the project root.

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
from typing import Any, Dict, List, Optional, Tuple

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
    global _cfg, llm, executor, explorer, target, _ACTIVE_DOMAIN
    _cfg = _load(_CONFIG_PATH)
    llm = _build_llm(_cfg)
    executor = _build_executor(_cfg)
    explorer = _build_explorer(_cfg)
    target = _build_target(_cfg)
    _ACTIVE_DOMAIN = _cfg.get("domain", "drawio")


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


@dataclass(frozen=True)
class ModelConfig:
    """Per-purpose LLM provider settings."""
    provider: str
    model: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout: Optional[float] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


@dataclass(frozen=True)
class TargetConfig:
    """Screenshot/input target settings."""
    backend: str
    debug_port: int
    url_match: Tuple[str, ...]
    screenshot_mode: str
    fallback: str


def _build_llm(cfg: Dict[str, Any]) -> LLMConfig:
    return LLMConfig(
        model=cfg["llm"]["model"],
        max_steps=cfg["llm"]["max_steps"],
    )


def _legacy_model_config(cfg: Dict[str, Any], purpose: str) -> Dict[str, Any]:
    if purpose in {"planner", "executor"}:
        llm_cfg = cfg.get("llm", {})
        return {
            "provider": llm_cfg.get("provider", "ollama"),
            "model": llm_cfg.get("model", "qwen3.5:35b"),
            "timeout": llm_cfg.get("timeout"),
        }
    if purpose == "critic":
        critic_cfg = cfg.get("critic", {})
        explorer_cfg = cfg.get("explorer", {})
        return {
            "provider": critic_cfg.get("provider", explorer_cfg.get("provider", "ollama")),
            "model": critic_cfg.get("model", explorer_cfg.get("model", "qwen3-vl:4b")),
            "timeout": critic_cfg.get("timeout", 60),
        }
    explorer_cfg = cfg.get("explorer", {})
    return {
        "provider": explorer_cfg.get("provider", "ollama"),
        "model": explorer_cfg.get("model", "qwen3-vl:4b"),
        "timeout": explorer_cfg.get("label_timeout", 30),
    }


def _build_model_config(cfg: Dict[str, Any], purpose: str) -> ModelConfig:
    raw = dict(_legacy_model_config(cfg, purpose))
    raw.update(cfg.get("models", {}).get(purpose, {}))
    if raw.get("provider") == "openai" and not raw.get("api_key_env") and not raw.get("api_key"):
        raw["api_key_env"] = "OPENAI_API_KEY"
    api_key = raw.get("api_key")
    api_key_env = raw.get("api_key_env")
    if not api_key and api_key_env:
        api_key = os.environ.get(api_key_env)
    return ModelConfig(
        provider=raw.get("provider", "ollama"),
        model=raw["model"],
        base_url=raw.get("base_url"),
        api_key=api_key,
        api_key_env=api_key_env,
        timeout=raw.get("timeout"),
        max_tokens=raw.get("max_tokens"),
        temperature=raw.get("temperature"),
    )


def _build_target(cfg: Dict[str, Any]) -> TargetConfig:
    t = cfg.get("target", {})
    matches = t.get("url_match", ["app.diagrams.net", "draw.io", "drawio"])
    backend = os.environ.get("DRAWIO_TARGET_BACKEND") or t.get("backend", "pyautogui")
    fallback = os.environ.get("DRAWIO_TARGET_FALLBACK") or t.get("fallback", "pyautogui")
    return TargetConfig(
        backend=backend,
        debug_port=int(t.get("debug_port", 9222)),
        url_match=tuple(str(m) for m in matches),
        screenshot_mode=t.get("screenshot_mode", "tab"),
        fallback=fallback,
    )


def _build_executor(cfg: Dict[str, Any]) -> ExecutorConfig:
    e = cfg["executor"]
    failsafe_env = os.environ.get("DRAWIO_EXECUTOR_FAILSAFE")
    failsafe = e["failsafe"]
    if failsafe_env is not None:
        failsafe = failsafe_env.strip().lower() not in {"0", "false", "no", "off"}
    return ExecutorConfig(
        failsafe=failsafe,
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
target = _build_target(_cfg)


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


def ui_graph_path(domain: Optional[str] = None) -> str:
    """Path of the captured UI graph for an interface.

    Each interface keeps its OWN icon set in ``state/ui_graph.<domain>.json``
    (e.g. ``ui_graph.drawio.json``, ``ui_graph.imovie.json``). Defaults to the
    active domain. This is what lets the Explore tab + ``place_shape`` target
    different applications without their sidebars colliding.
    """
    d = domain or _ACTIVE_DOMAIN
    return os.path.join(state_dir(), f"ui_graph.{d}.json")


# ---------------------------------------------------------------------------
# Domain plugin (active interface — runtime-switchable)
# ---------------------------------------------------------------------------

# The active domain starts from config.json's "domain" but can be switched at
# runtime via set_domain() (the frontend's Interface dropdown). It governs both
# which ``domains.<name>`` plugin is used AND which ui_graph file is read.
_ACTIVE_DOMAIN: str = _cfg.get("domain", "drawio")


def domain() -> str:
    """Active domain/interface name (e.g. 'drawio'). Runtime-switchable."""
    return _ACTIVE_DOMAIN


def set_domain(name: str) -> None:
    """Switch the active domain/interface at runtime.

    Affects ``ui_graph_path`` / ``ui_graph`` (which icon set is read) and the
    ``domains.<name>`` plugin lookup. The caller is responsible for reloading
    any per-domain state it caches (tools, the live UI graph) — see
    ``core.api._switch_domain``.
    """
    global _ACTIVE_DOMAIN
    _ACTIVE_DOMAIN = name


def available_domains() -> List[str]:
    """Interfaces the user can switch between.

    Read from config.json's ``"interfaces"`` list (user-editable, so an
    in-progress interface like 'imovie' can appear before its plugin exists).
    Falls back to just the active domain when unset.
    """
    listed = _cfg.get("interfaces")
    if listed:
        return list(listed)
    return [_ACTIVE_DOMAIN]


# ---------------------------------------------------------------------------
# UI graph (from state/ui_graph.<domain>.json)
# ---------------------------------------------------------------------------

def load_ui_state(domain: Optional[str] = None) -> Dict[str, Any]:
    """Load an interface's persisted UI graph file. Returns {} if missing.

    Defaults to the active domain; pass ``domain`` to read another interface.
    """
    path = ui_graph_path(domain)
    if not os.path.exists(path):
        return {}
    return _load(path)


def ui_graph(domain: Optional[str] = None) -> Dict[str, Any]:
    """
    Return the runtime UI graph dict for an interface, merging persisted UI
    state with config.json calibration data. Defaults to the active domain.

    Schema (Phase 0 — preserved from prior layout):
        {
          "UI_Elements": {"name": {"x": int, "y": int, ...}, ...},
          "Canvas_Nodes": [...],
          "Canvas_Edges": [...]
        }
    """
    state = load_ui_state(domain)
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

def model_config(purpose: str) -> ModelConfig:
    return _build_model_config(_cfg, purpose)

def planner_model_config() -> ModelConfig:
    return model_config("planner")

def executor_model_config() -> ModelConfig:
    return model_config("executor")

def critic_model_config() -> ModelConfig:
    return model_config("critic")

def explorer_model_config() -> ModelConfig:
    return model_config("explorer")

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

# Critic
def critic_model() -> str:
    """Vision model for the checkpoint critic (Phase 3 verification).

    The critic judges a checkpoint from a *screenshot*, so it must be an
    image-capable model. Defaults to the explorer's icon-labeling vision model
    (which is known to accept images); override with a ``"critic": {"model": …}``
    block in config.json.
    """
    return _cfg.get("critic", {}).get("model", explorer.model)

def critic_timeout() -> float:
    """HTTP timeout (s) for a single critic verification call."""
    return float(_cfg.get("critic", {}).get("timeout", 60))

def label_timeout() -> float:
    return explorer.label_timeout

def label_max_retries() -> int:
    return explorer.label_max_retries

# Target
def target_config() -> TargetConfig:
    return _build_target(_cfg)


# ---------------------------------------------------------------------------
# Raw access
# ---------------------------------------------------------------------------

def config_path() -> str:
    return _CONFIG_PATH


def raw() -> Dict[str, Any]:
    """Return the full config dict (read-only copy)."""
    return dict(_cfg)
