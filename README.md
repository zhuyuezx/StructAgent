# drawioDemo

Agentic AI for Draw.io Automation

## Structure

```
config.json              ← All configuration (paths, calibration, LLM, executor)
main.py                  ← CLI entry point
test_drawio_manual.py    ← Manual test (no LLM)
test_drawio_auto.py      ← LLM integration test (escalating difficulty)
pipeline/
  config.py              ← Config loader (reads config.json)
  capture.py             ← Screenshot capture
  tools.py               ← Operational tools (place, move, type, etc.)
  llm.py                 ← LLM inference (tool selection via Ollama)
  pipeline.py            ← Agentic control loop
```

## Quick Start

```bash
pip install -r requirements.txt
```

### 1. Calibrate

Capture a screenshot and measure the (x, y) centres of draw.io's sidebar shapes:

```bash
python test_drawio_manual.py --calibrate
```

Then edit `config.json` → `calibration.ui_elements` with the measured coordinates.

### 2. Manual Test (no LLM)

Verify the tools work by running a hardcoded sequence:

```bash
python test_drawio_manual.py --run single --label "Cache"
python test_drawio_manual.py --run double
```

### 3. LLM Integration Test

Verify the LLM picks correct tools, with escalating difficulty:

```bash
# Level 1 — single step (place a rectangle)
python test_drawio_auto.py --level 1 --dry-run   # LLM decides, no execution
python test_drawio_auto.py --level 1              # LLM decides + executes

# Level 2 — two steps (place + label)
python test_drawio_auto.py --level 2

# Level 3 — multi-step (place + label + escape + deselect)
python test_drawio_auto.py --level 3

# Just inspect the prompt (no LLM call)
python test_drawio_auto.py --prompt-only
```

### 4. Full Pipeline

Run the agentic loop with a natural language task:

```bash
python main.py --task "Draw a rectangle labelled Cache"
python main.py --task "Draw a rectangle labelled Cache" --dry-run
```

## Configuration

All settings live in `config.json`:

| Section | Keys | Purpose |
|---------|------|---------|
| `paths` | `screenshots_dir`, `test_output_dir` | Where to save screenshots |
| `calibration` | `ui_elements`, `empty_canvas_point` | Sidebar shape coordinates |
| `llm` | `model`, `max_steps` | Ollama model name, step limit |
| `executor` | `pause`, `drag_duration`, `type_interval`, etc. | pyautogui tuning |

## Architecture

```
User Task → LLM (picks tool by name) → dispatch() → pyautogui (pixel coords from config)
                                           ↑
                              config.json calibration data
```

The LLM **never sees pixel coordinates** — it only picks named tools and references elements by name.
