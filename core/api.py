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
    POST   /api/plan                         LLM: text prompt -> parameterized plan
    POST   /api/plan/chat                     LLM: conversational plan refinement
    POST   /api/run-plan                     run a plan with checkpoints + screenshots
    POST   /api/repair                       LLM: corrective plan from current state
    GET    /api/screenshot/{name}            serve a captured screenshot (PNG)
    GET    /api/scene-graph                  current scene graph
    POST   /api/scene-graph/reset            reset scene graph
    GET    /api/ui-graph                     current UI graph (sidebar elements)
    GET    /api/health                       liveness probe
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core import config
from core import orchestrator
from core.state import scene_graph as sg
from core.state import ui_graph as ui_state
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


class PlanBody(BaseModel):
    task: str
    use_screenshot: bool = False  # screenshot+SG planning vs text-only (default)
    countdown: int = 0            # seconds before the screenshot (focus drawio)


class PlanResult(BaseModel):
    reasoning: str = ""
    # steps are {tool, params, checkpoint?, reasoning?} — kept loose on purpose.
    steps: List[Dict[str, Any]] = Field(default_factory=list)


class ChatPlanBody(BaseModel):
    # Full conversation [{role, content}, ...]; must end with a 'user' turn.
    # Assistant turns carry the prior plan JSON so the model keeps context.
    messages: List[Dict[str, str]]
    use_screenshot: bool = False
    countdown: int = 0


class RunPlanBody(BaseModel):
    steps: List[Dict[str, Any]]
    countdown: int = 0
    stop_on_checkpoint_fail: bool = False
    clear_canvas: bool = False  # wipe the draw.io canvas + scene graph first


class RunPlanResult(BaseModel):
    ok: bool                      # every step dispatched cleanly
    checkpoints_ok: bool          # no checkpoint failed
    trace: List[Dict[str, Any]]   # per-step {tool, params, result, checkpoint?}
    scene_graph: Dict[str, Any]


class RepairBody(BaseModel):
    task: str                                  # the original task
    failed_steps: List[Dict[str, Any]] = Field(default_factory=list)
    user_note: str = ""                        # free-text guidance for the fix
    use_screenshot: bool = False
    countdown: int = 0


class CapturedIcon(BaseModel):
    name: str          # dispatch key (place_shape tool_name)
    label: str         # humanized shape family
    category: str      # group header (shape family)
    x: int
    y: int
    w: int
    h: int


class UiGraphResult(BaseModel):
    domain: str
    sidebar_shapes: List[str]          # names only (back-compat)
    icons: List[CapturedIcon]          # full per-icon metadata


class RunPlanSegmentBody(BaseModel):
    # The whole plan + where to resume; the server runs up to and including the
    # next checkpointed step, then returns so the caller can verify it before
    # continuing (manual or AI critic). clear_canvas/countdown apply at start=0.
    steps: List[Dict[str, Any]]
    start: int = 0
    countdown: int = 0
    clear_canvas: bool = False


class SegmentResult(BaseModel):
    trace: List[Dict[str, Any]]        # the steps run in THIS segment
    next_index: int                    # resume here (== len(steps) when done)
    done: bool                         # no more steps to run
    checkpoint_step: Optional[int] = None  # 1-based step# that paused us, if any
    scene_graph: Dict[str, Any]


class CriticBody(BaseModel):
    screenshot: str                    # filename under screenshots_dir
    description: str                   # the checkpoint's expectation


class CriticResult(BaseModel):
    passed: bool
    reasoning: str = ""


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


def _optional_input_screenshot(
    use_screenshot: bool, countdown: int, name: str,
) -> Optional[str]:
    """Countdown + capture an input screenshot when requested, else None.

    Shared by the LLM endpoints (plan / plan-chat / repair) so screenshot+SG
    mode behaves identically across them.
    """
    if not use_screenshot:
        return None
    _countdown(countdown)
    from core.capture import screenshot as _screenshot
    return _screenshot(name)


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
    # Reconcile with disk before answering so a browser refresh reflects
    # tools added or removed out-of-band — e.g. a JSON file deleted directly
    # in state/tools/. Without this, a plain GET returns the in-memory
    # catalog, which can be stale relative to disk (and a deleted file would
    # keep showing up until the server restarts).
    _reload_tools_from_disk()
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
    # Record it as a known JSON tool so the deletion-diff in
    # _reload_tools_from_disk() can later drop it if its file is removed
    # out-of-band. (save_trace_as_tool registers it in the catalog but does
    # not touch this snapshot.)
    _KNOWN_JSON_TOOLS.add(body.name)
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
    # Keep the deletion-diff snapshot consistent with disk.
    _KNOWN_JSON_TOOLS.discard(name)
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
# Planner + orchestrator endpoints
# ===========================================================================

def _clear_canvas() -> Dict[str, Any]:
    """Wipe the draw.io canvas (select-all + delete) AND reset the scene graph.

    Driven through the normal dispatch path so it respects the focused window;
    assumes draw.io is focused (call after the countdown). Unlike an undo loop,
    select-all + delete clears shapes from earlier sessions too.
    """
    logger.info("[api] clearing draw.io canvas (select-all + delete)")
    dispatch("click_empty_canvas", {}, ui_graph=_G)
    time.sleep(0.2)
    dispatch("select_all", {}, ui_graph=_G)       # Cmd+A selects all cells
    time.sleep(0.2)
    dispatch("press_delete", {}, ui_graph=_G)      # delete the selection
    time.sleep(0.3)
    _G["scene_graph"] = sg.reset()
    _G["selected_handles"] = None
    return _G["scene_graph"]


def _basename_screenshots(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rewrite absolute checkpoint screenshot paths to bare filenames.

    The frontend loads them via GET /api/screenshot/{name}; we never expose
    absolute server paths.
    """
    for entry in trace:
        cp = entry.get("checkpoint")
        if cp and cp.get("screenshot"):
            cp["screenshot"] = os.path.basename(cp["screenshot"])
    return trace


@app.post("/api/plan", response_model=PlanResult)
def plan(body: PlanBody) -> PlanResult:
    """Turn a text prompt into a full parameterized plan (one LLM call).

    The plan's steps may carry ``checkpoint`` objects; nothing is executed
    here. Imported lazily so the rest of the API works without ``ollama``.
    """
    from core.agents.planner import plan as _plan

    _refresh_scene_graph()
    shot = _optional_input_screenshot(
        body.use_screenshot, body.countdown, "_plan_input.png")
    try:
        out = _plan(body.task, _G, screenshot_path=shot)
    except Exception as e:
        raise HTTPException(502, f"planner failed: {e}")
    return PlanResult(reasoning=out.get("reasoning", ""),
                      steps=out.get("steps", []))


@app.post("/api/plan/chat", response_model=PlanResult)
def plan_chat(body: ChatPlanBody) -> PlanResult:
    """Conversational planning — refine the plan over a running thread.

    The caller keeps the whole conversation and POSTs it each turn; the model
    re-emits the full updated plan. ``reasoning`` is the assistant's reply.
    """
    from core.agents.planner import chat_plan

    if not body.messages or body.messages[-1].get("role") != "user":
        raise HTTPException(400, "messages must be non-empty and end with a user turn")
    _refresh_scene_graph()
    shot = _optional_input_screenshot(
        body.use_screenshot, body.countdown, "_plan_input.png")
    try:
        out = chat_plan(body.messages, _G, screenshot_path=shot)
    except Exception as e:
        raise HTTPException(502, f"chat planning failed: {e}")
    return PlanResult(reasoning=out.get("reasoning", ""), steps=out.get("steps", []))


@app.post("/api/run-plan", response_model=RunPlanResult)
def run_plan(body: RunPlanBody) -> RunPlanResult:
    """Execute a plan deterministically, with checkpoint screenshots + checks.

    Each step with a ``checkpoint`` is screenshotted and its assertions are
    evaluated against the live scene graph; results land on the trace.
    """
    if not body.steps:
        raise HTTPException(400, "No steps to run.")
    unknown = [s.get("tool") for s in body.steps
               if s.get("tool") not in TOOL_CATALOG]
    if unknown:
        raise HTTPException(400, f"Unknown tool(s) in steps: {unknown}")

    _countdown(body.countdown)
    if body.clear_canvas:
        _clear_canvas()          # draw.io is focused now (post-countdown)
    _refresh_scene_graph()
    trace = orchestrator.run_plan(
        body.steps, _G,
        stop_on_checkpoint_fail=body.stop_on_checkpoint_fail,
    )
    return RunPlanResult(
        ok=orchestrator.plan_succeeded(trace),
        checkpoints_ok=orchestrator.checkpoints_passed(trace),
        trace=_basename_screenshots(trace),
        scene_graph=_G["scene_graph"],
    )


@app.post("/api/run-plan/segment", response_model=SegmentResult)
def run_plan_segment(body: RunPlanSegmentBody) -> SegmentResult:
    """Run one verification-gated segment of a plan.

    Executes ``steps[start:]`` up to and including the next checkpointed step,
    captures that checkpoint's screenshot, and returns — so the caller can
    verify it (manually or via POST /api/critic) before resuming from
    ``next_index``. ``clear_canvas`` / ``countdown`` apply only at ``start==0``.

    Unlike POST /api/run-plan, the scene-graph assertions do NOT gate the run;
    the screenshot is the source of truth (see core/agents/critic.py).
    """
    if not body.steps:
        raise HTTPException(400, "No steps to run.")
    unknown = [s.get("tool") for s in body.steps
               if s.get("tool") not in TOOL_CATALOG]
    if unknown:
        raise HTTPException(400, f"Unknown tool(s) in steps: {unknown}")
    if body.start < 0 or body.start >= len(body.steps):
        raise HTTPException(400, f"start {body.start} out of range "
                                 f"[0, {len(body.steps)})")

    _countdown(body.countdown)
    if body.clear_canvas and body.start == 0:
        _clear_canvas()          # draw.io is focused now (post-countdown)
    _refresh_scene_graph()
    seg = orchestrator.run_segment(body.steps, body.start, _G)
    return SegmentResult(
        trace=_basename_screenshots(seg["trace"]),
        next_index=seg["next_index"],
        done=seg["done"],
        checkpoint_step=seg["checkpoint_step"],
        scene_graph=_G["scene_graph"],
    )


@app.post("/api/critic", response_model=CriticResult)
def critic(body: CriticBody) -> CriticResult:
    """Have the vision critic judge a checkpoint screenshot against its
    expectation. Returns ``{passed, reasoning}``; the caller only continues the
    plan when ``passed`` is true. Imported lazily (needs ``ollama``)."""
    from core.agents import critic as _critic

    safe = os.path.basename(body.screenshot)
    path = os.path.join(config.screenshots_dir(), safe)
    if not os.path.isfile(path):
        raise HTTPException(404, f"No screenshot '{safe}'")
    try:
        out = _critic.verify(path, body.description)
    except Exception as e:
        raise HTTPException(502, f"critic failed: {e}")
    return CriticResult(passed=bool(out.get("passed")),
                        reasoning=out.get("reasoning", ""))


@app.post("/api/repair", response_model=PlanResult)
def repair(body: RepairBody) -> PlanResult:
    """Produce a corrective plan from the current scene graph (Phase 3).

    Reuses the planner against the live scene graph plus the flagged/failed
    steps and the user's note. The returned plan is reviewed + run like any
    other (POST /api/run-plan). Imported lazily (needs ``ollama``).
    """
    from core.agents.planner import repair as _repair

    _refresh_scene_graph()
    shot = _optional_input_screenshot(
        body.use_screenshot, body.countdown, "_repair_input.png")
    try:
        out = _repair(body.task, _G, failed_steps=body.failed_steps,
                      user_note=body.user_note, screenshot_path=shot)
    except Exception as e:
        raise HTTPException(502, f"repair failed: {e}")
    return PlanResult(reasoning=out.get("reasoning", ""),
                      steps=out.get("steps", []))


@app.get("/api/screenshot/{name}")
def get_screenshot(name: str) -> FileResponse:
    """Serve a captured screenshot by filename (no path traversal)."""
    safe = os.path.basename(name)
    path = os.path.join(config.screenshots_dir(), safe)
    if not os.path.isfile(path):
        raise HTTPException(404, f"No screenshot '{safe}'")
    return FileResponse(path, media_type="image/png")


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


_TOOL_SUFFIX_RE = re.compile(r"_Tool(?:_\d+)?$")


def _icon_category(name: str) -> str:
    """Derive a human-readable shape family from a captured icon's name.

    The perception layer names icons ``<Shape>_Tool`` and disambiguates
    duplicates with a numeric suffix (``Rectangle_Tool_1``). We strip both to
    recover the family (``Rectangle``), then humanize underscores. This is the
    only categorization the captured data actually supports — no hardcoded
    taxonomy — so all variants of a shape group together.
    """
    base = _TOOL_SUFFIX_RE.sub("", name) or name
    return base.replace("_", " ").strip() or "Other"


@app.get("/api/ui-graph", response_model=UiGraphResult)
def get_ui_graph() -> UiGraphResult:
    """Return the captured sidebar icons with labels, categories, and geometry.

    These are the shapes the perception layer detected + labeled in draw.io's
    sidebar; each ``name`` is the dispatch key accepted by ``place_shape`` /
    ``place_and_label`` (the ``tool_name`` param). The frontend lists them in
    the left panel grouped by ``category``.
    """
    elements = _G.get("UI_Elements", {})
    icons: List[CapturedIcon] = []
    for name in sorted(elements):
        e = elements[name]
        cat = _icon_category(name)
        icons.append(CapturedIcon(
            name=name,
            label=cat,
            category=cat,
            x=e.get("x", 0), y=e.get("y", 0),
            w=e.get("w", 0), h=e.get("h", 0),
        ))
    return UiGraphResult(
        domain=config.domain(),
        sidebar_shapes=[i.name for i in icons],
        icons=icons,
    )


@app.post("/api/ui-graph/dedupe", response_model=UiGraphResult)
def dedupe_ui_graph() -> UiGraphResult:
    """Collapse the captured icons to one canonical icon per shape.

    The vision labeler sometimes tags several distinct sidebar cells with the
    same shape word (``Rectangle_Tool_1 … _6``). This keeps only the canonical
    (top-left-most) icon of each shape, rewrites state/ui_graph.json, and
    refreshes the live catalog so the change shows without a restart.
    """
    diff = ui_state.dedupe_ui_state()
    logger.info("[api] deduped captured icons: %s", diff)
    _G["UI_Elements"] = config.ui_graph().get("UI_Elements", {})
    return get_ui_graph()


# ===========================================================================
# Explore — interactive sidebar detection + labeling (builds ui_graph.json)
# ===========================================================================
#
# Workflow:
#   1. POST /api/explore/detect  → screenshot + CV → working set of icon boxes
#   2. (frontend) user edits/adds/removes boxes, edits labels
#   3. POST /api/explore/label   → VLM labels requested icons (uses screenshot)
#   4. POST /api/explore/save    → writes the final icon set to ui_graph.json
#
# The frontend is the source of truth for the working icon set after step 1.
# Label and Save both receive the current icon list in the request body so
# manual edits (add/delete/relabel) are preserved across LLM label calls.

# Server-side state: only the screenshot path is kept (for cropping during
# labeling). The icon list lives in the frontend after the initial detect.
_explore_screenshot: Optional[str] = None
_explore_logical_w: int = 0
_explore_logical_h: int = 0


def _get_domain_label_prompt() -> Optional[str]:
    """Load the active domain's VLM label prompt, or None for generic fallback."""
    import importlib
    try:
        mod = importlib.import_module(f"domains.{config.domain()}.perception")
        return getattr(mod, "LABEL_PROMPT", None)
    except ImportError:
        return None


class ExploreIcon(BaseModel):
    x: int                      # logical center-x
    y: int                      # logical center-y
    w: int                      # logical width
    h: int                      # logical height
    label: Optional[str] = None


class DetectResult(BaseModel):
    screenshot: str             # filename, served via GET /api/screenshot/{name}
    logical_width: int
    logical_height: int
    screen_scale: int
    icons: List[ExploreIcon]


class LabelBody(BaseModel):
    icons: List[ExploreIcon]                  # current frontend working set
    indices: Optional[List[int]] = None       # None = label all
    countdown: int = 0


class LabelResult(BaseModel):
    icons: List[ExploreIcon]                  # full updated list


class SaveExploreBody(BaseModel):
    icons: List[ExploreIcon]


class SaveExploreResult(BaseModel):
    saved: int
    path: str


class DetectBody(BaseModel):
    countdown: int = 0


@app.post("/api/explore/detect", response_model=DetectResult)
def explore_detect(body: DetectBody) -> DetectResult:
    """Screenshot + CV detect icon-sized regions.

    Takes a fresh screenshot (countdown lets the user switch to the target
    window), runs OpenCV contour detection over the configured sidebar region,
    and returns the icon boxes in logical pixels together with the screenshot
    dimensions so the frontend can render an accurate SVG overlay.
    """
    global _explore_screenshot, _explore_logical_w, _explore_logical_h

    from core.capture import screenshot as _screenshot
    from core.perception.detect import detect_icons
    import cv2

    _countdown(body.countdown)
    path = _screenshot("_explore_detect.png")
    _explore_screenshot = path

    img = cv2.imread(path)
    if img is None:
        raise HTTPException(500, "Could not read screenshot")
    phys_h, phys_w = img.shape[:2]
    scale = config.screen_scale()
    _explore_logical_w = phys_w // scale
    _explore_logical_h = phys_h // scale

    raw_icons = detect_icons(path)
    icons = [
        ExploreIcon(x=ic["x"], y=ic["y"], w=ic["w"], h=ic["h"])
        for ic in raw_icons
    ]
    logger.info("[explore/detect] %d icons found in %s", len(icons), path)
    return DetectResult(
        screenshot=os.path.basename(path),
        logical_width=_explore_logical_w,
        logical_height=_explore_logical_h,
        screen_scale=scale,
        icons=icons,
    )


@app.post("/api/explore/label", response_model=LabelResult)
def explore_label(body: LabelBody) -> LabelResult:
    """AI-label some or all icons using the VLM.

    The client sends its current working icon set (including any manual edits)
    and optionally a list of indices to label.  The server crops each icon from
    the last-captured explore screenshot and calls the VLM.  Returns the full
    updated icon list.
    """
    global _explore_screenshot

    if not _explore_screenshot or not os.path.isfile(_explore_screenshot):
        raise HTTPException(400, "No screenshot available — run /explore/detect first")

    from core.perception.label import label_icons as _label

    _countdown(body.countdown)

    all_icons = [ic.model_dump() for ic in body.icons]
    indices = body.indices if body.indices is not None else list(range(len(all_icons)))
    valid_indices = [i for i in indices if 0 <= i < len(all_icons)]
    subset = [all_icons[i] for i in valid_indices]

    prompt = _get_domain_label_prompt()
    labeled_subset = _label(_explore_screenshot, subset, label_prompt=prompt)

    result = list(all_icons)
    for orig_idx, labeled in zip(valid_indices, labeled_subset):
        result[orig_idx] = {**result[orig_idx], "label": labeled.get("label")}

    logger.info("[explore/label] labeled %d icon(s)", len(valid_indices))
    return LabelResult(icons=[
        ExploreIcon(x=ic["x"], y=ic["y"], w=ic["w"], h=ic["h"], label=ic.get("label"))
        for ic in result
    ])


@app.post("/api/explore/save", response_model=SaveExploreResult)
def explore_save(body: SaveExploreBody) -> SaveExploreResult:
    """Persist the working icon set to ui_graph.json and reload the live catalog.

    Writes the icons the frontend sends (with whatever labels they have) to
    ``state/ui_graph.json`` via the same :func:`save_ui_state` path used by the
    notebook-based explorer, then reloads ``_G["UI_Elements"]`` so subsequent
    ``place_shape`` dispatches use the updated positions without a server restart.
    """
    from core.state.ui_graph import save_ui_state

    icons_dicts = [ic.model_dump() for ic in body.icons]
    out_path = save_ui_state(icons_dicts)
    _G["UI_Elements"] = config.ui_graph().get("UI_Elements", {})
    logger.info("[explore/save] saved %d icons → %s", len(icons_dicts), out_path)
    return SaveExploreResult(saved=len(icons_dicts), path=os.path.basename(out_path))
