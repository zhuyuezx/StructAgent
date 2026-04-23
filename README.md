# drawioDemo

Agentic AI for Draw.io Automation

## Structure

```
config.json              ← All configuration (paths, calibration, LLM, executor)
main.py                  ← CLI entry point
test_drawio_manual.py    ← Manual test (no LLM)
pipeline/
  config.py              ← Config loader
  capture.py             ← Screenshot capture
  tools.py               ← Operational tools (place, move, type, etc.)
  llm.py                 ← LLM inference (tool selection)
  pipeline.py            ← Agentic control loop
```

## Quick Start

```bash
pip install -r requirements.txt

# Calibrate — capture screenshot, measure sidebar coordinates
python test_drawio_manual.py --calibrate

# Edit config.json → calibration.ui_elements with measured coords

# Manual test — place + label a rectangle
python test_drawio_manual.py --run single --label "Cache"

# Full LLM pipeline (requires Ollama running)
python main.py --task "Add a rectangle labelled Cache"
```
