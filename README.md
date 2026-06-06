# StructAgent (drawioDemo)

Agentic AI for closed UIs — domain-portable framework with a persistent symbolic UI graph. **draw.io is a PoC**; the framework is designed to swap to any interface where APIs are not exposed.

## Architecture

```
Perception Pipeline:
  Screenshot → OpenCV detect → VLM label → state/ui_graph.json
  + per-shape handle detection (resize / extend / rotate) → scene_graph/scene_graph.json

Operation Pipeline:
  User Task → Executor agent (picks tool from catalog)
            → dispatch()
            → L2 compound  → sequences L1 calls via JSON step list
            → L1 operand   → resolves names + calls L0 atoms
            → L0 atom      → atom_* helper → pyautogui
                               ↑
               state/ui_graph.json   (calibrated coordinates)
               scene_graph/scene_graph.json (live canvas objects + edges, gitignored)
```

The Executor agent **never sees pixel coordinates** — it picks named tools and references canvas objects by id (`obj_001`, `edge_001`). The framework resolves names to coordinates deterministically. The Executor can also run in a **text-only mode** with the screenshot dropped from the user message (the SCENE GRAPH alone drives planning) — see [Executor inference modes](#executor-inference-modes--screenshot--sg-vs-text-only) below.

## Tool tree — three abstraction layers

Each tool is a **ToolNode** with an execution function and (optional) children. A node's level is auto-computed:

- **L0** — leaf with no children (native atom).
- **L1+** — `max(child.level) + 1`.

All tools above L0 are defined as **JSON files** in `state/tools/`. Python files contain only the function implementations; registration is handled by the JSON loader at startup.

### L0 — native computer operations (`core/tools/primitives.py`)

Raw pyautogui wrappers. No draw.io knowledge. Registered as ToolNodes directly in Python (the only layer that is).

```
L0  mouse_move(x, y)
L0  mouse_click(x, y, clicks)
L0  mouse_drag(sx, sy, tx, ty)
L0  key_press(key)
L0  key_combo(keys)
L0  keyboard_type(text)
```

### L1 — semantic operands

Single-step actions with draw.io or UI-graph awareness. Python implementations live in `core/tools/actions.py` (generic) and `domains/drawio/operations.py` (draw.io-specific). Each has a JSON definition in `state/tools/` that declares its params and links to the Python function via `"python_fn": "module:fn_name"`.

```
Generic actions (core/tools/actions.py):
  click_empty_canvas()
  click_node(node_ref, clicks)      double_click_node(node_ref)
  drag_node(node_ref, target_x, target_y)
  drag_node_near(node_ref, reference_node, offset_x, offset_y)
  resize_node(node_ref, new_width, new_height)
  hotkey(keys)    undo()    press_enter()    press_delete()    select_all()

draw.io operands (domains/drawio/operations.py):
  place_shape(tool_name)            type_label(text)
  press_escape()                    scan_handles()
  resize_shape(direction, amount)   extend_shape(direction)
  rotate_shape(angle_degrees)       move_shape(direction, amount)
  hover_object(object_id)
  connect_shapes(source_id, target_id, source_anchor)
```

### L2 — compound multi-step flows

Pure JSON compositions — no custom Python needed. Each step calls another registered tool by name with `$param` substitution. Level auto-computes to L2.

```json
// state/tools/place_and_label.json
{
  "name": "place_and_label",
  "params": ["tool_name", "label"],
  "steps": [
    {"tool": "place_shape",      "params": {"tool_name": "$tool_name"}},
    {"tool": "type_label",       "params": {"text": "$label"}},
    {"tool": "press_escape",     "params": {}},
    {"tool": "click_empty_canvas","params": {}}
  ]
}
```

Current L2 tools: `place_and_label`, `edit_label`, `delete_node`, `move_and_deselect`.

## Saving task traces as tools

After a successful task execution, you can persist the trace as a reusable tool:

```python
from core.tools.save_tool import save_trace_as_tool, check_trace_success

results = [...]  # list of step result dicts from dispatch()
if check_trace_success(results):
    save_trace_as_tool(
        name="my_new_tool",
        steps=[
            {"tool": "place_shape",  "params": {"tool_name": "$shape"}},
            {"tool": "type_label",   "params": {"text": "$label"}},
            {"tool": "press_escape", "params": {}},
        ],
        params=["shape", "label"],
        description="Place a shape and label it.",
    )
```

This writes `state/tools/my_new_tool.json` and immediately registers the tool in the live catalog. The LLM executor can also call `save_trace_as_tool` directly.

## Executor inference modes — screenshot + SG vs text-only

`core.agents.executor.infer()` takes `screenshot_path` as an optional argument. The caller decides per turn whether the LLM sees a screenshot; the system prompt's `# INPUTS YOU RECEIVE` block adapts to match.

```python
from core.agents.executor import infer

# 1) screenshot + SG (default — used by scene_graph_demo and complex_tasks_demo).
decision = infer(task, ui_graph, screenshot_path=img_path, history=history)

# 2) text-only — used by text_only_executor_test.ipynb.
decision = infer(task, ui_graph, screenshot_path=None, history=history)
```

| Mode | LLM-visible inputs | When to use |
|---|---|---|
| `screenshot_path=<path>` | Screenshot **+** SCENE GRAPH | Default. The SCENE GRAPH is authoritative; the screenshot catches visual issues the symbolic state misses. |
| `screenshot_path=None` | SCENE GRAPH only | Low-cost planning when symbolic state is known to be complete. Forces the LLM to reason over the deterministic graph rather than pattern-match pixels. |

Both modes share the same catalog, decision procedure, scene-graph block, and active-selection block — only the `INPUTS YOU RECEIVE` paragraph and the user-message image attachment vary. See `text_only_executor_test.ipynb` for a run-through of the same source/target task in both modes and a step-count comparison.

The framework still takes its **own** screenshots internally for handle detection (`_scan_and_reconcile` after geometry-changing ops). That's about keeping the SCENE GRAPH accurate; it is independent of what the LLM sees.

## Planner — text prompt → full plan in ONE call

The **Executor** picks one tool per turn (N LLM calls per task). The **Planner** (`core/agents/planner.py`) is the orchestrator-style alternative: it reads the task + SCENE GRAPH and emits the **whole ordered sequence of parameterized tool calls in a single LLM call**, which the framework then runs deterministically with zero further inference. This is the "prompt → draft graph" step from [ORCHESTRATOR.md](ORCHESTRATOR.md), scoped to a linear plan for Phase 1.

```python
from core import config
from core.state import scene_graph as sg
from core.orchestrator import plan_and_run, run_plan, plan_succeeded, trace_to_steps
from core.agents.planner import plan

g = config.ui_graph(); g["scene_graph"] = sg.load()

# One-shot: plan with the LLM, then execute deterministically.
out = plan_and_run("Place two rectangles Source and Target and connect them", g)
print(out["ok"], [s["tool"] for s in out["plan"]["steps"]])

# Or split the two halves (inspect / edit the plan before running):
p = plan("Draw a 3-node flowchart A→B→C", g)        # text-only by default
trace = run_plan(p["steps"], g, dry_run=True)        # dry_run = no mouse
if plan_succeeded(trace):
    # the trace is save-ready — persist it as a reusable compound tool
    from core.tools.save_tool import save_trace_as_tool
    save_trace_as_tool("flow_abc", steps=trace_to_steps(trace), trace=trace,
                       description="A→B→C flow", overwrite=True)
```

### Typed, parameterizable tools

So the Planner can fill the param space from the SCENE GRAPH, every tool param now carries a **type + description** (`core/tools/param_specs.py`):

| type | how the Planner fills it |
|---|---|
| `tool_name` | one of the listed **sidebar shapes** |
| `scene_object` | an existing `obj_NNN` id, or the **label** of an object the plan creates earlier (resolved → id at run time) |
| `scene_edge` | an `edge_NNN` id (edges numbered in creation order) |
| `direction` / `anchor` | fixed enum (`n/s/e/w[/…]`, `auto`) |
| `int` / `string` / `keys` | literal value |

Specs come from a central map keyed by canonical param name (so consistently-named params are typed everywhere for free); a tool's JSON may add an optional `"param_specs"` override. The Planner renders the catalog as `tool(name:type∈{enum}, …)`.

### Plan == compound tool

A plan's `steps` use the same `{tool, params}` schema as an L2 compound, so a successful plan saves straight back into `state/tools/` via `save_trace_as_tool` and becomes a first-class catalog tool.

### Checkpoints — verify from the screenshot, pause until it passes

Any step may carry a **checkpoint**: the run **pauses** there, captures a screenshot, and waits for **verification** before continuing. Only a PASS resumes the plan. Verification is done one of two ways:

- **Manual** (default) — you eyeball the screenshot in the Studio and click *Looks right — continue* or *Wrong — stop*.
- **AI** (tick "Let AI verify checkpoints") — a **vision critic** (`core/agents/critic.py`, an image-capable model) judges the screenshot against the checkpoint's natural-language `description` and returns `{passed, reasoning}`.

```jsonc
{ "tool": "place_and_label",
  "params": { "tool_name": "Rectangle_Tool", "label": "Source" },
  "checkpoint": {
    "description": "A rectangle labelled 'Source' is on the canvas",
    "assert": [ { "check": "object_exists", "label": "Source" } ]  // optional, secondary
  } }
```

**Why not gate on the scene graph?** The scene graph only reflects mutations the framework itself performed — the moment the live UI drifts from it (a drag that didn't land, a dialog that stole focus, a hand-edit) it silently lies. So the **screenshot is authoritative**. The structural `assert` kinds (`objects_count` / `edges_count` with `op` ∈ `== != >= <= > <`, `object_exists`, `edge_exists`, `selected`, `last_op`) are still evaluated by `core/checkpoint.py` and shown under each checkpoint as **secondary "structural hints (may be stale)"**, but they no longer decide pass/fail.

Execution is **segmented**: the orchestrator runs `steps[start:]` up to and including the next checkpointed step, then returns so the caller can verify it (`orchestrator.run_segment` → `POST /api/run-plan/segment`; the critic is `POST /api/critic`). The older whole-plan `run_plan` / `POST /api/run-plan` (scene-graph-gated, `stop_on_checkpoint_fail`) is kept for notebooks/tests.

### Repair (Phase 3) — fix a plan that drifted

When a checkpoint fails (or the result just looks wrong), you fix it two ways:

- **Manually** — edit the plan in place: change a step's tool, edit its params, reorder, add/remove steps, drop a checkpoint, then re-run.
- **Ask the agent** — flag the wrong step(s), add a free-text note, and `planner.repair(task, ui_graph, failed_steps, user_note)` produces a **corrective plan from the CURRENT scene graph** (the real, post-execution state — so it continues from where things actually are rather than re-doing finished work). It reuses the full planner prompt (catalog, quirks, checkpoints) plus a failure-context message. Exposed as `POST /api/repair`; the returned plan is reviewed and run like any other.

### Scene-graph lifecycle

Live scene-graph state lives in its own gitignored folder, `scene_graph/scene_graph.json`, resolved against the project root so notebooks, CLI, and API all share one graph. It is **not** auto-reset: the Studio asks before a run whether to **clear or keep** an existing scene graph, and `POST /api/scene-graph/reset` / `sg.reset()` clear it on demand.

### Studio — the Plan tab

The frontend ([frontend/](frontend/)) has a **Plan** tab wrapping all of the above as a **persistent planning chat**:

- **Chat** a task, then keep chatting to refine it ("make the boxes bigger", "add a third node and connect it"). The model re-emits the full plan each turn (`POST /api/plan/chat`); its reasoning is the reply. The thread is long-lived — any later message modifies the current plan.
- **Edit** the draft plan by hand — change a step's tool, edit params, reorder, add/remove, drop a checkpoint.
- **Run** it (with a clear-or-keep scene-graph prompt; *Clear* wipes the draw.io canvas too). The run **pauses at each checkpoint** with the captured screenshot and a verdict gate — approve/reject by hand, or tick **Let AI verify checkpoints** to have the vision critic decide. A rejected (or failed) step is flagged and feeds the repair loop.
- **Fix**: flag wrong steps + a note → **Ask agent to fix** re-plans from the current canvas (and threads the fix back into the chat).
- **Save** the current plan as a reusable compound tool, straight into the catalog.

The **left panel** also lists the **captured sidebar icons** — the shapes perception detected in draw.io, grouped by category, each name usable as a `place_shape` `tool_name` (`GET /api/ui-graph`).

Backed by `POST /api/plan/chat`, `POST /api/run-plan/segment`, `POST /api/critic`, `POST /api/repair`, `POST /api/tools`, and `GET /api/screenshot/{name}` in [core/api.py](core/api.py).

```bash
# Offline (no LLM, no GUI):
python tests/test_planner.py --prompt-only     # render the Planner system prompt
python tests/test_planner.py --parse-demo       # parse a sample model reply → plan
python tests/test_planner.py --dry-run          # walk a sample plan, no mouse
python tests/test_checkpoint.py                 # checkpoint DSL + run_plan integration

# Live (needs ollama + draw.io focused; 5s countdown to switch):
python tests/test_planner.py --live "Place two rectangles Source and Target and connect them"
python tests/test_planner.py --live "..." --screenshot   # screenshot+SG instead of text-only
```

## Project structure

```
config.json                  ← Domain, paths, models, executor + perception params
main.py                      ← CLI entry point

core/                        ← Framework — domain-agnostic
  capture.py                 ← Screenshot capture
  config.py                  ← Loads config.json + state/ui_graph.json
  pipeline.py                ← Agentic control loop (perceive → reason → act)
  orchestrator.py            ← Plan runner: run_plan + run_segment (verification-gated)
  checkpoint.py              ← Structural assertions over scene_graph (secondary hints)
  agents/
    _common.py               ← Shared coordinate-free state rendering + JSON parsing
    executor.py              ← LLM tool selection, one per turn (no coords)
    planner.py               ← LLM emits a FULL parameterized plan in one call
    critic.py                ← Vision critic: verify a checkpoint from its screenshot
  perception/
    detect.py                ← OpenCV element detection + annotation
    label.py                 ← VLM crop labeling
    handles.py               ← Detect selection chrome (resize/extend/rotate)
  state/
    ui_graph.py              ← UI graph persistence helpers
    scene_graph.py           ← Live canvas objects + edges (deterministic)
  tools/
    registry.py              ← ToolNode dataclass, register(), dispatch()
    param_specs.py           ← Typed param specs (type/description/enum) for the Planner
    primitives.py            ← L0 atom ToolNodes + raw atom_* helpers (pyautogui)
    actions.py               ← L1 generic action implementations (no registration)
    loader.py                ← JSON tool loader + compound executor builder
    save_tool.py             ← save_trace_as_tool() + check_trace_success()
    __init__.py              ← Loads L0 atoms, then domain plugin (JSON tools)

domains/                     ← Interface-specific plugins (swap to port)
  drawio/
    operations.py            ← draw.io L1 operand implementations (no registration)
    tools.py                 ← Calls load_tools_from_dir(state/tools/) on import

state/
  ui_graph.json              ← Calibrated sidebar UI graph (perception)
  tools/                     ← JSON tool definitions (all L1 and L2 tools)
    click_empty_canvas.json  ← ... 25 files total
    place_and_label.json
    ...

scene_graph/                 ← Live canvas state (gitignored, per-session)
  scene_graph.json           ← Current objects + edges; cleared on demand

notebooks/
  scene_graph_demo.ipynb         ← End-to-end demo: deterministic + LLM-driven
  complex_tasks_demo.ipynb       ← Multi-shape layouts (CCW ring + server-client star)
  text_only_executor_test.ipynb  ← Same source/target task with NO screenshot input
  visualize.ipynb                ← Tool tree visualizer (NetworkX graph + summary)

frontend/                     ← Browser UI (Vite + React) wrapping the catalog
core/api.py                   ← FastAPI sidecar serving the frontend
ORCHESTRATOR.md               ← Design doc for the next-step visual orchestrator
```

## Plugin loading

The active domain is set in `config.json`:
```json
{ "domain": "drawio" }
```
`core/tools/__init__.py` imports `domains.<domain>.tools` on load, which calls `load_tools_from_dir(state/tools/)`. The loader does a two-pass load (python_fn tools first, then compound steps tools) so children resolve correctly.

---

## Quick start

```bash
pip install -r requirements.txt
```

> **macOS note**: Screen capture requires *Screen Recording* permission for Terminal/iTerm in  
> System Preferences → Privacy & Security → Screen Recording.

---

## Running tests

Tests are ordered by dependency. Start from T1 and work down.

### T1 — No dependencies (import + schema)

```bash
# Verify tool registry assembles correctly (6 L0 + 21 L1 + 4 L2 = 31 tools)
python -c "import core.tools; from core.tools.registry import TOOL_CATALOG, print_tree; print(len(TOOL_CATALOG), 'tools'); core.tools.print_tree()"

# Verify config + ui_graph.json load
python -c "from core import config; g = config.ui_graph(); print(len(g['UI_Elements']), 'elements')"
```

### T2 — No LLM, no GUI

```bash
# Render the executor's system prompt (checks executor + catalog)
python tests/test_auto.py --prompt-only

# Show tool tree + loaded sidebar shapes
python tests/demo_integration.py --tree

# Dry-run leaf + compound sequences (no mouse movement)
python tests/demo_integration.py --mode both --dry-run
python tests/test_manual.py --run single --dry-run
```

### T3 — Perception (screenshot + OpenCV, no GUI focus needed)

```bash
# Detect icons from saved screenshot
python tests/test_collect_icons.py --detect --image screenshots/explore.png

# Live capture + detect (no mouse movement, screen focus not needed)
python tests/test_collect_icons.py --detect

# Detect + VLM label + write to state/ui_graph.json (requires ollama)
python tests/test_collect_icons.py --detect --label --write
```

### T4 — Live GUI (draw.io must be focused, requires ollama)

Switch to draw.io when prompted (5-second countdown).

```bash
# Level 1: LLM picks and executes one tool (place a rectangle)
python tests/test_auto.py --level 1

# Level 2: two-step sequence (place + label)
python tests/test_auto.py --level 2

# Level 3: full multi-step workflow (place, label, escape, deselect)
python tests/test_auto.py --level 3

# Manual hardcoded sequences (no LLM)
python tests/test_manual.py --run single --label "Cache"
python tests/test_manual.py --run double

# Leaf + compound live demo
python tests/demo_integration.py --mode both
```

### T5 — Full pipeline

```bash
# Capture state + print ui_graph (no actions)
python main.py --screenshot

# Run the full perceive → reason → act loop
python main.py --task "Draw a rectangle labelled Cache"
python main.py --task "Draw a rectangle labelled Cache" --dry-run
```

---

## Data files

| File | Owner | Content |
|------|-------|---------|
| `config.json` | Manual | Domain selection, paths, models, executor + perception params |
| `state/ui_graph.json` | Perception | Auto-detected sidebar element positions and labels |
| `scene_graph/scene_graph.json` | Framework | Live canvas objects + edges (gitignored, per-session); cleared on demand from the Studio or `sg.reset()` |
| `state/tools/*.json` | Framework / LLM | Registered L1 and L2 tool definitions |

---

## Where to put new tools

| Need | Layer | Where | How |
|------|-------|--------|-----|
| New mouse/keyboard primitive | L0 atom | `core/tools/primitives.py` | Add `atom_*` helper + `_fn_*` ToolNode + `register()`. |
| Single semantic step with UI-graph awareness (generic) | L1 | `core/tools/actions.py` + `state/tools/<name>.json` | Add `_fn_*` impl; add JSON with `"python_fn": "core.tools.actions:_fn_<name>"`. |
| Single semantic step specific to draw.io | L1 | `domains/drawio/operations.py` + `state/tools/<name>.json` | Add `_fn_*` impl; add JSON with `"python_fn": "domains.drawio.operations:_fn_<name>"`. |
| Multi-step workflow | L2+ | `state/tools/<name>.json` | JSON with `"steps": [...]` only — no Python needed. Or call `save_trace_as_tool()`. |

## Adding a new domain

1. Create `domains/<name>/__init__.py` and `domains/<name>/tools.py`.
2. In `tools.py`, call `load_tools_from_dir(Path(config.state_dir()) / "tools")`.
3. Add domain-specific L1 implementations to `domains/<name>/operations.py`.
4. Create JSON definitions in `state/tools/` for each tool.
5. Set `"domain": "<name>"` in `config.json`.

## Example: adding an L2 compound via JSON

```json
// state/tools/my_compound.json
{
  "name": "my_compound",
  "description": "Place a shape and label it.",
  "params": ["shape", "label"],
  "needs_ui_graph": true,
  "steps": [
    {"tool": "place_shape", "params": {"tool_name": "$shape"}},
    {"tool": "type_label",  "params": {"text": "$label"}},
    {"tool": "press_escape","params": {}}
  ]
}
```

Or programmatically (e.g. from a notebook or the LLM executor):

```python
from core.tools.save_tool import save_trace_as_tool

save_trace_as_tool(
    name="my_compound",
    description="Place a shape and label it.",
    params=["shape", "label"],
    steps=[
        {"tool": "place_shape", "params": {"tool_name": "$shape"}},
        {"tool": "type_label",  "params": {"text": "$label"}},
        {"tool": "press_escape","params": {}},
    ],
)
```

---

## Known issues (Phase 1 targets)

| Issue | Root cause | Fix |
|---|---|---|
| Uppercase letters drop during `type_label` | `pyautogui.typewrite` doesn't handle Shift; "Database" types as "atabase" | Replace with `pyautogui.write()` |
| ~~`edit_label` / `delete_node` / `move_and_deselect` always fail~~ **(fixed)** | They resolved node refs via the empty `Canvas_Nodes` | Node refs now resolve by **id or label via the scene graph** (`_resolve_node_geom` in [actions.py](core/tools/actions.py)) |
| Sidebar label ambiguity (`Rectangle_Tool_1..6`) | VLM labels small crops without group context | Group-aware detection (Phase 3) |
