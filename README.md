# drawioDemo

Agentic AI for Draw.io Automation

## Project Structure

```
config.json                  ← Architectural config (paths, models, executor, explorer)
main.py                      ← CLI entry point for the operation pipeline

shared/                      ← Shared utilities (used by both pipelines)
  config.py                  ← Config loader (reads config.json + icons.json)
  capture.py                 ← Screenshot capture

exploration/                 ← Pipeline 2: UI exploration & auto-calibration
  explorer.py                ← OpenCV icon detection + VLM labeling
  test_collect_icons.py      ← Test script for exploration pipeline
  icons.json                 ← OUTPUT: auto-detected icon coordinates

operation/                   ← Pipeline 1: LLM-driven draw.io operations
  tools.py                   ← Operational tools (place, move, type, etc.)
  llm.py                     ← LLM inference (tool selection via Ollama)
  pipeline.py                ← Agentic control loop
  test_manual.py             ← Manual test (no LLM)
  test_auto.py               ← LLM integration test (escalating difficulty)
```

## Two Pipelines

| Pipeline | Folder | Purpose |
|----------|--------|---------|
| **Exploration** | `exploration/` | Auto-detects UI elements → labels with VLM → writes `icons.json` |
| **Operation** | `operation/` | Uses configured tools to operate draw.io via LLM |

Exploration feeds Operation: it discovers what's clickable and writes coordinates to `icons.json`, which Operation reads at runtime.

## Data Files

| File | Owner | Content |
|------|-------|---------|
| `config.json` | Manual | Architectural settings (paths, models, executor tuning, explorer params) |
| `exploration/icons.json` | Exploration pipeline | Auto-detected icon positions (`{ui_elements: {...}}`) |

## Quick Start

```bash
pip install -r requirements.txt
```

### Step 1: Auto-detect sidebar icons (Exploration)

```bash
# Detect icons from a live screenshot
python exploration/test_collect_icons.py --detect

# Use an existing screenshot
python exploration/test_collect_icons.py --detect --image screenshots/explore.png

# Detect + label with VLM
python exploration/test_collect_icons.py --detect --label

# Detect + label + write to icons.json
python exploration/test_collect_icons.py --detect --label --write
```

### Step 2: Manual test (Operation, no LLM)

```bash
python operation/test_manual.py --run single --label "Cache"
python operation/test_manual.py --run double
```

### Step 3: LLM integration test (Operation)

```bash
python operation/test_auto.py --level 1      # single-step
python operation/test_auto.py --level 2      # two-step
python operation/test_auto.py --level 3      # multi-step
python operation/test_auto.py --prompt-only  # inspect prompt
```

### Step 4: Full pipeline

```bash
python main.py --task "Draw a rectangle labelled Cache"
```

## Configuration

### config.json (architectural)

| Section | Purpose |
|---------|---------|
| `paths` | Screenshot and test output directories |
| `calibration` | Canvas nodes/edges, empty canvas click point |
| `llm` | Ollama model name and step limit for the planner |
| `executor` | pyautogui tuning (pause, drag speed, etc.) |
| `explorer` | Detection params, VLM model for icon labeling |

### exploration/icons.json (auto-generated)

Written by the exploration pipeline. Contains `ui_elements` — a map of tool names to `{x, y, w, h}` in logical pixels:

```json
{
  "ui_elements": {
    "Rectangle_Tool": {"x": 20, "y": 290, "w": 30, "h": 30},
    "Ellipse_Tool": {"x": 165, "y": 290, "w": 30, "h": 30}
  }
}
```

## Architecture

```
Exploration Pipeline:
  Screenshot → OpenCV detect → VLM label → icons.json

Operation Pipeline:
  User Task → LLM (picks tool) → dispatch() → pyautogui
                                      ↑
                                  icons.json
```

The LLM **never sees pixel coordinates** — it only picks named tools.
