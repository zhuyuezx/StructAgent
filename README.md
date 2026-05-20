# StructAgent (drawioDemo)

Agentic AI for closed UIs — domain-portable framework with a persistent symbolic UI graph. **draw.io is a PoC**; the framework is designed to swap to any interface where APIs are not exposed.

## Architecture

```
Perception Pipeline:
  Screenshot → OpenCV detect → VLM label → state/ui_graph.json
  + per-shape handle detection (resize / extend / rotate) → state/scene_graph.json

Operation Pipeline:
  User Task → Executor agent (picks operand from tree)
            → dispatch()
            → L1/L2 operand → resolves names + composes
            → L0 atomic primitives → atom_* helpers → pyautogui
                                       ↑
                       state/ui_graph.json   (calibrated coordinates)
                       state/scene_graph.json (live canvas objects + edges)
```

The Executor agent **never sees pixel coordinates** — it picks named operands and references canvas objects by id (`obj_001`, `edge_001`). The framework resolves names to coordinates deterministically.

## Tool tree — three abstraction layers

Each tool is a **ToolNode** with its own execution logic and (optional) children. A node's level is computed from its tree:

- A leaf with no children → **L0** (atom).
- A node with children → **max(child.level) + 1**.
- Composers that call bare helper functions (not registered ToolNodes) declare their level explicitly via `level_override=1` so the hierarchy stays meaningful.

### L0 — drawio-aware atomic primitives (`core/tools/primitives.py`)
Single-step actions. Each is a thin wrapper around one `atom_*` helper plus minimal scene-graph bookkeeping. No name resolution beyond the tool catalog.

```
L0  place_shape(tool_name)         ← click sidebar icon + Enter
L0  type_label(text)               ← atom_write
L0  press_escape() / press_enter() / press_delete()
L0  select_all()                   ← Cmd+A
L0  scan_handles()                 ← re-detect selection chrome
L0  resize_shape(direction, amount)
L0  extend_shape(direction)
L0  rotate_shape(angle_degrees)
L0  move_shape(direction, amount)
L0  hover_object(object_id)
L0  connect_shapes(source_id, target_id, source_anchor)
```

`primitives.py` also defines (but does NOT register as ToolNodes) the raw atoms — `atom_click_at`, `atom_drag`, `atom_press`, `atom_hotkey`, `atom_write`, `atom_move_to`. These are the only places where `pyautogui` is called directly.

### L1 — generic node-aware actions (`core/tools/actions.py`)
Resolve a node/object reference to coordinates, then call one or more L0 atoms. Domain-agnostic.

```
L1  click_empty_canvas()                       ← atom_click_at + clear-selection
L1  click_node(node_ref, clicks=1)             ← resolve + atom_click_at
L1  double_click_node(node_ref)                ← click_node(clicks=2)
L1  drag_node(node_ref, target_x, target_y)    ← resolve + atom_drag
L1  drag_node_near(node_ref, reference_node)   ← resolve + drag_node
L1  resize_node(node_ref, new_width, new_height)
L1  hotkey(*keys)                              ← atom_hotkey wrapper
L1  undo()                                     ← Cmd+Z via atom_hotkey
```

### L2 — domain compound flows (`domains/drawio/tools.py`)
Multi-step drawio-specific workflows. Compose L0 + L1 children — auto-computed level = 2.

```
L2 place_and_label(tool_name, label)
  L0 place_shape(tool_name)
  L0 type_label(text)
  L0 press_escape()
  L1 click_empty_canvas()

L2 edit_label(node_ref, new_label)
  L1 double_click_node(node_ref)
  L0 select_all()
  L0 type_label(text)
  L0 press_escape()
  L1 click_empty_canvas()

L2 delete_node(node_ref)
  L1 click_node(node_ref)
  L0 press_delete()
  L1 click_empty_canvas()

L2 move_and_deselect(node_ref, target_x, target_y)
  L1 drag_node(node_ref, target_x, target_y)
  L1 click_empty_canvas()
```

To visualize: `python tests/demo_integration.py --tree`

## Project structure

```
config.json                  ← Domain, paths, models, executor + perception params
main.py                      ← CLI entry point

core/                        ← Framework — domain-agnostic
  capture.py                 ← Screenshot capture
  config.py                  ← Loads config.json + state/ui_graph.json
  pipeline.py                ← Agentic control loop (perceive → reason → act)
  agents/
    executor.py              ← LLM tool selection (no coords)
  perception/
    detect.py                ← OpenCV element detection + annotation
    label.py                 ← VLM crop labeling
    handles.py               ← Detect selection chrome (resize/extend/rotate)
  state/
    ui_graph.py              ← UI graph persistence helpers
    scene_graph.py           ← Live canvas objects + edges (deterministic)
  tools/
    registry.py              ← ToolNode dataclass, register(), dispatch()
    primitives.py            ← L0 drawio-aware atoms + raw atom_* helpers
    actions.py               ← L1 generic node-aware actions
    __init__.py              ← Loads primitives, actions, then domain plugin

domains/                     ← Interface-specific plugins (swap to port)
  drawio/
    tools.py                 ← draw.io L2 compounds (self-register on import)

state/
  ui_graph.json              ← Calibrated sidebar UI graph (perception)
  scene_graph.json           ← Live canvas state (objects + edges)
  
notebooks/
  scene_graph_demo.ipynb     ← End-to-end demo: deterministic + LLM-driven

tests/                       ← Integration test scripts
  test_collect_icons.py      ← Perception pipeline test
  test_manual.py             ← No-LLM hardcoded sequences
  test_auto.py               ← Full LLM integration tests (Levels 1–3)
  demo_integration.py        ← Leaf + compound demo
```

## Plugin loading

The active domain is set in `config.json`:
```json
{ "domain": "drawio" }
```
`core/tools/__init__.py` auto-imports `domains.<domain>.tools` on load, which self-registers its ToolNodes into the catalog via `register()`.

---

## Quick start

```bash
pip install -r requirements.txt
```

> **macOS note**: Screen capture requires *Screen Recording* permission for Terminal/iTerm in  
> System Preferences → Privacy & Security → Screen Recording.

---

## Running tests

Tests are ordered by dependency. Start from T1 and work down — each level requires the previous to pass.

### T1 — No dependencies (import + schema)

```bash
# Verify tool registry assembles (14 L0 + 4 L1 = 18 tools)
python -c "from core.tools import TOOL_CATALOG, print_tree; print(len(TOOL_CATALOG), 'tools'); print_tree()"

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
| `state/scene_graph.json` | Framework (deterministic) | Live canvas objects + edges, updated by operands after each geometry-changing op |

---

## Where to put new tools — picking a layer

| Need | Layer | File | How |
|------|-------|------|-----|
| Wrap a single new key/click/drag/keystroke | L0 atom | `core/tools/primitives.py` | Add an `atom_*` helper. Don't register as a ToolNode — atoms are internal. |
| Single semantic step that maps to one atom + minimal state update (drawio-aware) | L0 primitive | `core/tools/primitives.py` | Add `_fn_*` + `N_*` ToolNode, register it. |
| Resolve a name/id, OR compose multiple atoms | L1 action | `core/tools/actions.py` | Add `_fn_*` + `N_*` with `level_override=1`, register it. |
| Multi-step workflow specific to a domain (e.g. drawio's place + label + escape + deselect) | L2 compound | `domains/<name>/tools.py` | Add ToolNode with `children=[…]`; level auto-computes to L2. |

## Adding a new domain

1. Create `domains/<name>/__init__.py` and `domains/<name>/tools.py`.
2. In `tools.py`, define compound ToolNodes composed of `core.tools.primitives` and `core.tools.actions` ToolNodes; call `register(node)` on each.
3. Set `"domain": "<name>"` in `config.json`.
4. The framework loads the plugin automatically — no other changes needed.

## Example: adding an L2 compound

```python
# domains/drawio/tools.py
from core.tools.registry import ToolNode, register
from core.tools.primitives import (
    _fn_place_shape, _fn_type_label,
    N_PLACE_SHAPE, N_TYPE_LABEL,
)
from core.tools.actions import N_CLICK_EMPTY  # L1 generic action

def _fn_my_compound(ui_graph, tool_name: str, label: str) -> dict:
    steps = [
        _fn_place_shape(ui_graph, tool_name),
        _fn_type_label(label),
    ]
    return {"status": "ok", "tool": "my_compound", "steps": steps}

N_MY_COMPOUND = ToolNode(
    name="my_compound", fn=_fn_my_compound,
    params=["tool_name", "label"], needs_ui_graph=True,
    description="Place a shape and label it.",
    children=[N_PLACE_SHAPE, N_TYPE_LABEL, N_CLICK_EMPTY],  # level auto = L2
)
register(N_MY_COMPOUND)
```

---

## Known issues (Phase 1 targets)

| Issue | Root cause | Fix |
|---|---|---|
| Uppercase letters drop during `type_label` | `pyautogui.typewrite` doesn't handle Shift; "Database" types as "atabase" | Replace with `pyautogui.write()` |
| `edit_label` / `delete_node` / `move_and_deselect` always fail | `Canvas_Nodes` is never populated — no canvas perception | Implement Perceiver agent (Phase 1) |
| Sidebar label ambiguity (`Rectangle_Tool_1..6`) | VLM labels small crops without group context | Group-aware detection (Phase 3) |
