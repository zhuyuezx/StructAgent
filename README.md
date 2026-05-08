# StructAgent (drawioDemo)

Agentic AI for closed UIs — domain-portable framework with a persistent symbolic UI graph. **draw.io is a PoC**; the framework is designed to swap to any interface where APIs are not exposed.

## Architecture

```
Perception Pipeline:
  Screenshot → OpenCV detect → VLM label → state/ui_graph.json

Operation Pipeline:
  User Task → Executor agent (picks tool from tree) → dispatch() → pyautogui
                                                          ↑
                                              ui_graph.json (coordinates)
```

The executor agent **never sees pixel coordinates** — it picks named tools. The tool tree handles coordinate resolution.

## Hierarchical tool tree

Each tool is a **ToolNode** with its own execution logic and children.
Level is auto-computed: leaf = L0, compound = max(child.level) + 1.

Generic L0 primitives live in `core/tools/primitives.py`. Domain-specific L1 compounds live in `domains/<name>/tools.py`.

```
L1 place_and_label(tool_name, label)              ← domains/drawio
  L0 place_shape(tool_name)                       ← core
  L0 type_label(text)                             ← core
  L0 press_escape()                               ← core
  L0 click_empty_canvas()                         ← core

L1 edit_label(node_ref, new_label)                ← domains/drawio
  L0 double_click_node(node_ref)
  L0 select_all()
  L0 type_label(text)
  L0 press_escape()
  L0 click_empty_canvas()

L1 delete_node(node_ref)                          ← domains/drawio
  L0 click_node(node_ref, clicks)
  L0 press_delete()
  L0 click_empty_canvas()

L1 move_and_deselect(node_ref, target_x, target_y) ← domains/drawio
  L0 drag_node(node_ref, target_x, target_y)
  L0 click_empty_canvas()
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
  state/
    ui_graph.py              ← UI graph persistence helpers
  tools/
    registry.py              ← ToolNode dataclass, register(), dispatch()
    primitives.py            ← L0 generic primitives (self-register on import)
    __init__.py              ← Loads primitives then domain plugin

domains/                     ← Interface-specific plugins (swap to port)
  drawio/
    tools.py                 ← draw.io L1 compounds (self-register on import)

state/
  ui_graph.json              ← Persistent UI graph (perception output)

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
| `state/ui_graph.json` | Perception | Auto-detected element positions and labels |

---

## Adding a new domain

1. Create `domains/<name>/__init__.py` and `domains/<name>/tools.py`.
2. In `tools.py`, define compound ToolNodes composed of `core.tools.primitives` leaves; call `register(node)` on each.
3. Set `"domain": "<name>"` in `config.json`.
4. The framework loads the plugin automatically — no other changes needed.

## Adding tools within a domain

```python
# domains/drawio/tools.py
from core.tools.registry import ToolNode, register
from core.tools.primitives import (
    _fn_place_shape, _fn_type_label,
    N_PLACE_SHAPE, N_TYPE_LABEL,
)

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
    children=[N_PLACE_SHAPE, N_TYPE_LABEL],  # level auto-computed
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
