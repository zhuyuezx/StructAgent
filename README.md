# drawioDemo

Agentic AI for Draw.io — Hierarchical Tool Composition

## Architecture

```
Exploration Pipeline:
  Screenshot → OpenCV detect → VLM label → icons.json

Operation Pipeline:
  User Task → LLM (picks tool from tree) → dispatch() → pyautogui
                                                ↑
                                          icons.json (coordinates)
```

The LLM **never sees pixel coordinates** — it picks named tools. The tool tree handles coordinate resolution.

## Hierarchical Tool Tree

Each tool is a **ToolNode** with its own execution logic and children.
Level is auto-computed: leaf = L0, compound = max(child.level) + 1.

```
L1 place_and_label(tool_name, label)
  L0 place_shape(tool_name)
  L0 type_label(text)
  L0 press_escape()
  L0 click_empty_canvas()

L1 edit_label(node_ref, new_label)
  L0 double_click_node(node_ref)
  L0 select_all()
  L0 type_label(text)
  L0 press_escape()
  L0 click_empty_canvas()

L1 delete_node(node_ref)
  L0 click_node(node_ref, clicks)
  L0 press_delete()
  L0 click_empty_canvas()

L1 move_and_deselect(node_ref, target_x, target_y)
  L0 drag_node(node_ref, target_x, target_y)
  L0 click_empty_canvas()
```

To visualize the full tree: `python operation/demo_integration.py --tree`

## Project Structure

```
config.json                  ← Architectural config (paths, models, executor)
main.py                      ← CLI entry point

shared/                      ← Shared utilities
  config.py                  ← Reads config.json + icons.json
  capture.py                 ← Screenshot capture

exploration/                 ← Pipeline 2: UI exploration
  explorer.py                ← OpenCV detection + VLM labeling
  test_collect_icons.py      ← Test script
  icons.json                 ← OUTPUT: detected icon coordinates

operation/                   ← Pipeline 1: LLM-driven operations
  tools.py                   ← ToolNode tree (L0 leaves + compounds)
  llm.py                     ← LLM inference (tool selection)
  pipeline.py                ← Agentic control loop
  demo_integration.py        ← Integration demo (exploration → operation)
  test_manual.py             ← Manual test (no LLM)
  test_auto.py               ← LLM integration test
```

## Quick Start

```bash
pip install -r requirements.txt
```

### 1. Explore: auto-detect sidebar icons

```bash
# Detect + label + write to icons.json
python exploration/test_collect_icons.py --detect --label --write

# Use existing screenshot
python exploration/test_collect_icons.py --detect --image screenshots/explore.png
```

### 2. Demo: prove exploration → operation integration

```bash
# Show the tool tree
python operation/demo_integration.py --tree

# Dry run (no mouse movement)
python operation/demo_integration.py --mode both --dry-run

# Live demo (place shapes using exploration-detected coordinates)
python operation/demo_integration.py --mode both
```

### 3. LLM integration test

```bash
python operation/test_auto.py --level 1      # single-step
python operation/test_auto.py --level 2      # two-step
python operation/test_auto.py --level 3      # multi-step
```

### 4. Full pipeline

```bash
python main.py --task "Draw a rectangle labelled Cache"
```

## Data Files

| File | Owner | Content |
|------|-------|---------|
| `config.json` | Manual | Architectural settings (paths, models, executor, explorer params) |
| `exploration/icons.json` | Exploration | Auto-detected icon positions and labels |

## Adding New Tools

Compound tools are just ToolNodes with children:

```python
# In operation/tools.py

def _fn_my_compound(ui_graph, ...):
    steps = []
    steps.append(_fn_place_shape(ui_graph, "Rectangle_Tool"))
    time.sleep(0.3)
    steps.append(_fn_type_label("Hello"))
    ...
    return {"status": "ok", "tool": "my_compound", "steps": steps}

N_MY_COMPOUND = ToolNode(
    name="my_compound", fn=_fn_my_compound,
    params=["..."], needs_ui_graph=True,
    description="...",
    children=[N_PLACE_SHAPE, N_TYPE_LABEL, ...],  # level auto-computed!
)
```

Add to `ALL_NODES` and it's automatically in the catalog + LLM prompt.
