# Repository Guidelines

## Project Structure & Module Organization

This repository implements a draw.io automation agent with a Python backend and a React/Vite studio frontend. Core orchestration, API, capture, checkpoint, and agent logic lives in `core/`. Domain-specific draw.io behavior is in `domains/drawio/`. Tool definitions and UI graph fixtures are JSON files under `state/`, especially `state/tools/`. Frontend code is in `frontend/src/`, with component views in `frontend/src/components/`. Offline and live test harnesses are in `tests/`. Notebooks, screenshots, and presentation material live in `notebooks/`, `screenshots/`, and `presentation/`.

## Build, Test, and Development Commands

Install Python dependencies from the repo root:

```powershell
pip install -r requirements.txt
```

Run the backend API for the Studio:

```powershell
uvicorn core.api:app --reload --port 8000
```

Run the frontend from `frontend/`:

```powershell
npm install
npm run dev
npm run build
```

Use `python main.py --task "Draw a rectangle labelled Cache" --dry-run` for a safe pipeline run. Use `python main.py --screenshot` to capture current UI state.

## Coding Style & Naming Conventions

Python uses 4-space indentation, type hints where useful, and snake_case names for modules, functions, and JSON tool files. Tool implementations typically use `_fn_<tool_name>` and are referenced from JSON with `"python_fn": "module:function"`. React/TypeScript uses 2-space indentation, PascalCase components, and camelCase variables. Keep API payload shapes aligned with `frontend/src/types.ts`.

## Testing Guidelines

Run focused offline tests before changing planner, checkpoint, or tool behavior:

```powershell
python tests/test_planner.py --dry-run
python tests/test_planner.py --parse-demo
python tests/test_checkpoint.py
```

Live tests may require Ollama, draw.io, and the target window focused. Prefer dry-run coverage for deterministic changes, then add live verification only when GUI behavior changes.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `add presentation` and `update ppt`. Keep commits focused and describe the user-visible behavior or artifact changed. Pull requests should include a concise summary, test commands run, linked issue or task context, and screenshots for frontend or draw.io interaction changes.

## Agent-Specific Instructions

On Windows, when using bash, call `E:\VSCODE\Git\Git\bin\bash.exe` explicitly instead of relying on `bash` from `PATH`.
