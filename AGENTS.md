# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

**drawioDemo** is an agentic AI system that automates Draw.io diagram creation via a perceive → reason → act loop:
1. Captures a screenshot of the current Draw.io state
2. Observes the dynamic canvas with OpenCV and merges it with persistent sidebar tool memory
3. Queries a local LLM (Qwen via Ollama) to select a tool based on the task
4. Executes the tool using `pyautogui` to interact with Draw.io
5. Captures a post-action screenshot and verifies whether the action changed the canvas as expected
6. Repeats until the task is complete

**Key design principle**: The LLM reasons only about abstract named elements (e.g., `Rectangle_Tool`, `Observed_Node_1`) — never pixel coordinates. Stable sidebar coordinates live in `state/ui_graph.json`; dynamic canvas nodes are observed from the latest screenshot at runtime. Coordinate resolution still happens in the tools layer.

## Setup

```bash
pip install -r requirements.txt
pip install opencv-python httpx  # required by perception pipeline, not in requirements.txt
```

Requires Draw.io running locally and Ollama running with the appropriate models:
```bash
ollama pull qwen3.5:35b      # planner LLM (executor agent)
ollama pull qwen3-vl:4b      # vision LLM (perception pipeline, icon labeling)
```

## Commands

### Run the main pipeline
```bash
python main.py --task "Add a rectangle labelled Cache"
python main.py --task "Add a rectangle labelled Cache" --dry-run  # LLM decides, no execution
python main.py --task "Add a rectangle labelled Cache" --trace    # write step diagnostics to test_output/runs/
python main.py --screenshot                                         # capture only
```

### Perception pipeline (auto-detect sidebar icons)

```bash
python tests/test_collect_icons.py --detect                          # detect icons via OpenCV
python tests/test_collect_icons.py --detect --label                  # detect + label with VLM
python tests/test_collect_icons.py --detect --label --write          # detect + label + save to state/ui_graph.json
python tests/test_collect_icons.py --detect --image path/to/img.png  # use existing screenshot
```

### Show integration demo
```bash
python tests/demo_integration.py --mode leaf       # run leaf tools step-by-step
python tests/demo_integration.py --mode compound   # run compound tool (place_and_label)
python tests/demo_integration.py --mode both
python tests/demo_integration.py --dry-run
python tests/demo_integration.py --tree            # print tool tree and exit
```

### Manual testing (no LLM)
```bash
python tests/test_manual.py --calibrate            # capture screenshot for calibration
python tests/test_manual.py --run single --label "Cache"
python tests/test_manual.py --run double
python tests/test_manual.py --run single --dry-run
```

### LLM integration tests
```bash
python tests/test_auto.py --level 1                # single-step: place_shape only
python tests/test_auto.py --level 2                # two-step: place + label
python tests/test_auto.py --level 3                # multi-step: full workflow
python tests/test_auto.py --level 3 --dry-run
python tests/test_auto.py --prompt-only            # print LLM prompt without executing
python -m unittest tests.test_canvas tests.test_canvas_tracker tests.test_tool_families tests.test_verification tests.test_pipeline_rescan
```

## Architecture

```
main.py (CLI entry point)
    └── core/pipeline.py       (agentic loop — perceive/reason/act/verify, up to max_steps)
            ├── core/capture.py            (screenshot to disk)
            ├── core/agents/executor.py    (Ollama query → JSON tool decision)
            ├── core/perception/canvas.py  (runtime canvas observation + overlays)
            ├── core/perception/tracker.py (stable in-run canvas node IDs)
            ├── core/verification.py       (post-action verification)
            └── core/tools/__init__.py     (loads registry + primitives + domain plugin)
                    ├── core/tools/registry.py      (ToolNode, register, dispatch)
                    ├── core/tools/primitives.py    (14 L0 leaf tools, self-register)
                    └── domains/drawio/tools.py     (4 L1 compound tools, self-register)

core/config.py        (typed accessors for config.json + state/ui_graph.json)
config.json           (domain, paths, calibration coords, LLM settings, executor timing, explorer settings)

core/perception/
    canvas.py             (OpenCV canvas node observation + graph summaries + debug overlays)
    tracker.py            (stable in-run canvas node IDs)
    detect.py             (OpenCV icon detection)
    label.py              (VLM labeling via Ollama)

core/state/
    ui_graph.py           (save/load state/ui_graph.json)

state/
    ui_graph.json         (OUTPUT: auto-detected sidebar icon names and coordinates)

tests/
    test_canvas.py        (non-LLM canvas observer tests with synthetic screenshots)
    test_canvas_tracker.py (stable canvas ID tests)
    test_tool_families.py (manual/default family tests)
    test_verification.py  (action-level verification tests)
    test_pipeline_rescan.py (rescan refresh regression test)
    test_collect_icons.py (perception pipeline test — detect + label + write)
    test_manual.py        (no-LLM manual action test)
    test_auto.py          (LLM integration test, levels 1–3)
    demo_integration.py   (end-to-end demo: leaf and compound tools)
```

### config.json structure

- **`domain`** — active domain plugin name (e.g. `"drawio"`); controls which `domains/<name>/tools.py` is loaded
- **`paths`** — `screenshots_dir`, `test_output_dir`, `state_dir`, `ui_graph_file` (relative paths)
- **`calibration.canvas_nodes/edges`** — legacy/static canvas calibration; runtime pipeline now observes `Canvas_Nodes` from screenshots
- **`calibration.empty_canvas_point`** — pixel coord to click to deselect everything
- **`llm.model`** — Ollama model name for the planner; `llm.max_steps` — loop iteration limit
- **`executor`** — pyautogui timing: `pause`, `drag_duration`, `type_interval`, `step_cooldown`, `countdown_seconds`
- **`explorer`** — perception pipeline: `model` (VLM for labeling), `screen_scale` (retina factor), `sidebar_region`, `canvas_region`, `icon_size_range`, `nms_distance`, `label_timeout`, `label_max_retries`

### core/config.py: key accessors

- `ui_graph(screenshot_path=...)` — merges `state/ui_graph.json` UI elements with runtime canvas observations; returns `{"UI_Elements": {...}, "Canvas_Nodes": [...], "Canvas_Edges": [...]}`
- `load_ui_state()` — reads `state/ui_graph.json` directly (returns `{}` if missing)
- `canvas_region()` — returns the physical-pixel crop used by the runtime canvas observer
- `domain()` — returns active domain plugin name
- All `explorer_*()` and `executor_*()` helpers for typed access to config sections

### Tool system: hierarchical ToolNode tree

Tools are split across three files and self-register at import time:

**`core/tools/primitives.py` — Leaf tools (Level 0)**, 15 atomic GUI operations:
`place_shape`, `type_label`, `press_escape`, `press_enter`, `press_delete`, `select_all`, `click_empty_canvas`, `click_node`, `double_click_node`, `drag_node`, `drag_node_near`, `drag_node_to_zone`, `resize_node`, `hotkey`, `undo`

**`domains/drawio/tools.py` — Compound tools (Level 1)**, multi-step workflows:
`place_and_label`, `place_shape_then_edit_label`, `edit_label`, `delete_node`, `move_and_deselect`, `move_node_to_zone_and_deselect`

**`core/tools/registry.py`** — `ToolNode` dataclass, `register()`, `dispatch()`, coordinate resolution helpers (`resolve_tool`, `resolve_node`).

**`core/tools/__init__.py`** — imports primitives (self-registers L0), then dynamically imports `domains.<config.domain()>.tools` (self-registers L1+). After import, `dispatch(tool_name, params, ui_graph)` works for any level.

### core/perception/: icon detection pipeline

**`detect.py`** — `detect_icons(screenshot_path)`:
1. Crop screenshot to sidebar region (physical pixels from config)
2. OpenCV Canny edge detection + contour finding
3. Filter by size/aspect ratio
4. NMS to remove duplicates
5. Return coordinates in logical pixels (physical ÷ screen_scale)

**`label.py`** — `label_icons(screenshot_path, icons)`:
- Sends each icon crop to VLM (Qwen-VL via Ollama) with httpx timeout
- Returns label like "Rectangle", "Diamond", "Ellipse"
- Handles timeouts and retries per config

**`canvas.py`** — `observe_canvas(screenshot_path)`:
- Crops screenshot to `explorer.canvas_region`
- Uses theme-aware OpenCV contours so light/dark grid lines are suppressed
- Returns approximate runtime nodes like `Observed_Node_1` with logical center/size, confidence, stroke density, rectangularity, and source metadata
- `observe_canvas_detailed()` returns accepted candidates, rejected candidates, crop metadata, and theme/polarity for traces
- `annotate_canvas()` writes visual debug images showing crop bounds, accepted boxes, rejected boxes, and tracked motion arrows
- Also provides graph summaries and configured/default sidebar tool family grouping for traces/prompts

**`tracker.py`** — `CanvasTracker`:
- Keeps `Observed_Node_N` stable within a single pipeline run by matching raw detections using center distance, size similarity, and bounding-box IoU
- Records matched, new, and deleted tracks in trace diagnostics

**`core/state/ui_graph.py`** — `save_ui_state(icons)` formats labeled icons as `{name}_Tool` entries and writes to `state/ui_graph.json`.

### core/agents/executor.py: LLM prompt structure

Prompt includes: available tools (as markdown table), named sidebar tools, ambiguous tool families, observed canvas nodes (no coordinates), draw.io workflow rules, verification-aware action history, current task, and current screenshot. Model returns JSON: `{ "reasoning": "...", "tool": "place_shape", "params": {...} }`. Special tool names `task_complete` and `request_rescan` control loop termination and force a fresh screenshot-backed graph.

### core/verification.py: post-action checks

`verify_action()` compares pre-action and post-action screenshots/observed graphs. Placement tools strongly pass when a new tracked node appears. Drag tools strongly pass when the same tracked node moves in the expected direction. `delete_node` strongly passes when the target tracked node disappears or node count decreases. For `type_label`, image change is a weak pass because OCR is not implemented yet. `text_placement` is currently recorded as `"unknown"`. Selection-only actions such as `press_escape` and `click_empty_canvas` are non-blocking in v1.

### Trace diagnostics

`python main.py --task "Add a rectangle labelled Cache" --trace` writes one JSON file per step under `test_output/runs/<timestamp>/`. Each step includes screenshot paths, canvas annotation image paths, accepted/rejected canvas candidates, tracking diagnostics, tool-family defaults, prompt text, UI graph summaries, decision, dispatch result, verification result, and history.
