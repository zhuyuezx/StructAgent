"""
FastAPI server — HTTP wrapper around the tool registry.

Exposes the tool catalog, dispatch, scene-graph state, and save_trace_as_tool
to a browser-based frontend. Run with::

    uvicorn core.api:app --reload --port 8000

Endpoints
─────────
    GET    /api/tools                        list all registered tools
    GET    /api/tools/{name}                 full definition for one tool
    POST   /api/tools                        save a new compound tool
    DELETE /api/tools/{name}                 delete a saved compound tool
    POST   /api/tools/{name}/run             dispatch a tool by name
    POST   /api/run-steps                    run an ad-hoc step list (no save)
    GET    /api/scene-graph                  current scene graph
    POST   /api/scene-graph/reset            reset scene graph
    GET    /api/ui-graph                     current UI graph (sidebar elements)
    GET    /api/health                       liveness probe
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core import config
from core.state import scene_graph as sg
from core.tools import TOOL_CATALOG, dispatch
from core.tools.loader import _make_compound_executor, load_tools_from_dir
from core.tools.registry import ALL_NODES
from core.tools.save_tool import save_trace_as_tool, tools_dir

logger = logging.getLogger(__name__)

app = FastAPI(title="StructAgent API", version="0.1.0")

# Dev: allow the Vite dev server (default 5173) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Shared ui_graph state
# ===========================================================================
# The UI graph (and the scene_graph mounted inside it) is threaded through
# every dispatch so successive calls share selection/handle state, the same
# way the notebooks do.
#
# Scene graph is **reset on startup** so the frontend starts from a clean
# slate, matching the pattern the notebooks use (sg.reset() before every
# run). This avoids showing leftover state from a prior notebook session.

_G: Dict[str, Any] = config.ui_graph()
_G["scene_graph"] = sg.reset()
_G["selected_handles"] = None

# Names of tools that were loaded from JSON on disk. Used by the reload
# endpoint to compute add/remove diffs.
_KNOWN_JSON_TOOLS: set = {p.stem for p in tools_dir().glob("*.json")}


def _refresh_scene_graph() -> Dict[str, Any]:
    """Pick up any out-of-band edits to scene_graph.json."""
    _G["scene_graph"] = sg.load()
    return _G["scene_graph"]


def _reload_tools_from_disk() -> Dict[str, Any]:
    """Rescan ``state/tools/`` and reconcile the live TOOL_CATALOG.

    - JSON files added since last load → register.
    - JSON files removed since last load → drop from catalog.
    - Existing JSON files → re-register (replacing the previous node so
      param changes / step edits take effect without a server restart).
    """
    on_disk_now = {p.stem for p in tools_dir().glob("*.json")}
    deleted = _KNOWN_JSON_TOOLS - on_disk_now

    for name in deleted:
        node = TOOL_CATALOG.pop(name, None)
        if node is not None:
            try:
                ALL_NODES.remove(node)
            except ValueError:
                pass

    # register() in load_tool_definition replaces by name, so this also
    # picks up edits to existing files.
    load_tools_from_dir(tools_dir())

    added = on_disk_now - _KNOWN_JSON_TOOLS
    _KNOWN_JSON_TOOLS.clear()
    _KNOWN_JSON_TOOLS.update(on_disk_now)

    return {
        "added": sorted(added),
        "removed": sorted(deleted),
        "total": len(TOOL_CATALOG),
    }


# ===========================================================================
# Response models
# ===========================================================================

class ToolSummary(BaseModel):
    name: str
    level: int
    params: List[str]
    needs_ui_graph: bool
    description: str
    is_leaf: bool
    children: List[str]
    has_json: bool  # whether a JSON definition exists on disk


class StepDef(BaseModel):
    tool: str
    params: Dict[str, Any] = Field(default_factory=dict)


class ToolDetail(ToolSummary):
    steps: Optional[List[StepDef]] = None       # for compound tools
    python_fn: Optional[str] = None             # for python_fn tools
    raw_definition: Optional[Dict[str, Any]] = None


class SaveToolBody(BaseModel):
    name: str
    description: str = ""
    params: List[str] = Field(default_factory=list)
    needs_ui_graph: bool = True
    steps: List[StepDef]
    overwrite: bool = False


class RunBody(BaseModel):
    params: Dict[str, Any] = Field(default_factory=dict)
    countdown: int = 0  # seconds to wait before dispatching (lets user focus drawio)


class RunStepsBody(BaseModel):
    steps: List[StepDef]
    params: Dict[str, Any] = Field(default_factory=dict)
    countdown: int = 0


class RunResult(BaseModel):
    status: str
    tool: Optional[str] = None
    result: Dict[str, Any]
    scene_graph: Dict[str, Any]


# ===========================================================================
# Helpers
# ===========================================================================

def _json_path_for(name: str) -> Path:
    return tools_dir() / f"{name}.json"


def _load_raw_definition(name: str) -> Optional[Dict[str, Any]]:
    path = _json_path_for(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _tool_to_summary(name: str) -> ToolSummary:
    node = TOOL_CATALOG[name]
    return ToolSummary(
        name=node.name,
        level=node.level,
        params=list(node.params),
        needs_ui_graph=node.needs_ui_graph,
        description=node.description,
        is_leaf=node.is_leaf,
        children=[c.name for c in node.children],
        has_json=_json_path_for(name).exists(),
    )


def _tool_to_detail(name: str) -> ToolDetail:
    summary = _tool_to_summary(name)
    raw = _load_raw_definition(name)
    steps: Optional[List[StepDef]] = None
    python_fn: Optional[str] = None
    if raw:
        if "steps" in raw:
            steps = [StepDef(**s) for s in raw["steps"]]
        if "python_fn" in raw:
            python_fn = raw["python_fn"]
    return ToolDetail(
        **summary.model_dump(),
        steps=steps,
        python_fn=python_fn,
        raw_definition=raw,
    )


def _countdown(seconds: int) -> None:
    """Blocking sleep so the user can switch to the target window."""
    seconds = max(0, min(seconds, 30))
    if seconds <= 0:
        return
    logger.info("[api] countdown: switch to draw.io now …")
    for i in range(seconds, 0, -1):
        logger.info("  %ss", i)
        time.sleep(1)


# ===========================================================================
# Tool catalog endpoints
# ===========================================================================

@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "domain": config.domain(),
        "tool_count": len(TOOL_CATALOG),
    }


@app.get("/api/tools", response_model=List[ToolSummary])
def list_tools() -> List[ToolSummary]:
    return [_tool_to_summary(n) for n in TOOL_CATALOG]


class ReloadResult(BaseModel):
    added: List[str]
    removed: List[str]
    total: int
    tools: List[ToolSummary]


@app.post("/api/reload-tools", response_model=ReloadResult)
def reload_tools() -> ReloadResult:
    """Rescan ``state/tools/`` and refresh the live catalog.

    Pick up new JSON files added on disk, drop ones that were deleted, and
    re-register changed ones. Avoids the need to restart uvicorn after
    hand-editing a tool definition.
    """
    diff = _reload_tools_from_disk()
    return ReloadResult(
        added=diff["added"],
        removed=diff["removed"],
        total=diff["total"],
        tools=[_tool_to_summary(n) for n in TOOL_CATALOG],
    )


@app.get("/api/tools/{name}", response_model=ToolDetail)
def get_tool(name: str) -> ToolDetail:
    if name not in TOOL_CATALOG:
        raise HTTPException(404, f"Unknown tool '{name}'")
    return _tool_to_detail(name)


@app.post("/api/tools", response_model=ToolDetail)
def save_tool(body: SaveToolBody) -> ToolDetail:
    if not body.steps:
        raise HTTPException(400, "Cannot save a tool with zero steps.")
    # Reject step.tool references the registry doesn't know.
    unknown = [s.tool for s in body.steps if s.tool not in TOOL_CATALOG]
    if unknown:
        raise HTTPException(400, f"Unknown sub-tool(s) referenced in steps: {unknown}")
    try:
        save_trace_as_tool(
            name=body.name,
            description=body.description,
            params=body.params,
            needs_ui_graph=body.needs_ui_graph,
            steps=[s.model_dump() for s in body.steps],
            overwrite=body.overwrite,
        )
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(400, f"save_trace_as_tool failed: {e}")
    return _tool_to_detail(body.name)


@app.delete("/api/tools/{name}")
def delete_tool(name: str) -> Dict[str, Any]:
    path = _json_path_for(name)
    if not path.exists():
        raise HTTPException(404, f"No JSON definition on disk for '{name}'.")
    # Only allow deletion of JSON-backed tools; the L0 atoms are Python-only.
    path.unlink()
    # Drop from the live catalog so subsequent GETs don't return a stale entry.
    if name in TOOL_CATALOG:
        node = TOOL_CATALOG.pop(name)
        from core.tools.registry import ALL_NODES
        try:
            ALL_NODES.remove(node)
        except ValueError:
            pass
    return {"status": "ok", "deleted": name}


# ===========================================================================
# Execution endpoints
# ===========================================================================

@app.post("/api/tools/{name}/run", response_model=RunResult)
def run_tool(name: str, body: RunBody) -> RunResult:
    if name not in TOOL_CATALOG:
        raise HTTPException(404, f"Unknown tool '{name}'")
    _countdown(body.countdown)
    _refresh_scene_graph()
    result = dispatch(name, body.params, ui_graph=_G)
    return RunResult(
        status=result.get("status", "unknown"),
        tool=name,
        result=result,
        scene_graph=_G["scene_graph"],
    )


@app.post("/api/run-steps", response_model=RunResult)
def run_steps(body: RunStepsBody) -> RunResult:
    """
    Execute an ad-hoc step list without saving it.

    Used by the composer's "Test draft" button: build a compound on the fly,
    run it, return the final scene graph. If any step fails, execution stops
    and the error is returned along with the scene graph state at the failure
    point.
    """
    if not body.steps:
        raise HTTPException(400, "No steps to run.")
    unknown = [s.tool for s in body.steps if s.tool not in TOOL_CATALOG]
    if unknown:
        raise HTTPException(400, f"Unknown sub-tool(s) in steps: {unknown}")

    _countdown(body.countdown)
    _refresh_scene_graph()

    # Build a one-shot compound executor mirroring the loader.
    fn, _ = _make_compound_executor("__draft__", [s.model_dump() for s in body.steps])
    result = fn(ui_graph=_G, **body.params)
    return RunResult(
        status=result.get("status", "unknown"),
        tool="__draft__",
        result=result,
        scene_graph=_G["scene_graph"],
    )


# ===========================================================================
# Scene-graph + UI-graph endpoints
# ===========================================================================

@app.get("/api/scene-graph")
def get_scene_graph() -> Dict[str, Any]:
    return _refresh_scene_graph()


@app.post("/api/scene-graph/reset")
def reset_scene_graph() -> Dict[str, Any]:
    g = sg.reset()
    _G["scene_graph"] = g
    _G["selected_handles"] = None
    return g


@app.get("/api/ui-graph")
def get_ui_graph() -> Dict[str, Any]:
    """Return the calibrated sidebar elements (names only, coords stripped)."""
    elements = _G.get("UI_Elements", {})
    return {
        "domain": config.domain(),
        "sidebar_shapes": sorted(elements.keys()),
    }
