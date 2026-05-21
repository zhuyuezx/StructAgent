# StructAgent Studio (frontend, v1)

Browser UI that wraps the existing tool registry: browse the catalog, inspect
each tool, run any tool with params, and author new compound tools as a
form-based step list.

> v1 is intentionally the **form-based composer** — pick a tool from a dropdown,
> fill its params, reorder, save. The ComfyUI-style node graph from
> [`ORCHESTRATOR.md`](../ORCHESTRATOR.md) is v2; everything underneath
> (typed I/O, repair loop, planner) lives on the same backend so v2 is
> a drop-in upgrade.

## Stack

- **React 18 + Vite + TypeScript** — frontend.
- **FastAPI** (in [`core/api.py`](../core/api.py)) — HTTP wrapper over
  `TOOL_CATALOG`, `dispatch`, `save_trace_as_tool`, and `state/scene_graph.json`.
- Dev: Vite at `:5173`, uvicorn at `:8000`. `/api/*` is proxied through Vite,
  so the frontend just calls relative URLs.

## Quick start

```bash
# 1. Backend (from repo root) — installs fastapi + uvicorn the first time.
pip install -r requirements.txt
uvicorn core.api:app --reload --port 8000

# 2. Frontend (in a second terminal)
cd frontend
npm install
npm run dev
# → open http://localhost:5173
```

On macOS the existing **Screen Recording** permission still applies — every
`Run` / `Test draft` button dispatches the tool through pyautogui against
whichever window has focus when the countdown expires. Set the countdown to
5s and switch to draw.io during it.

## What's in here

```
frontend/
├── index.html
├── package.json
├── vite.config.ts            ← proxies /api/* to localhost:8000
├── tsconfig.json
└── src/
    ├── main.tsx              ← React entry
    ├── App.tsx               ← three-pane layout + tabs
    ├── styles.css            ← all styling, no framework
    ├── api.ts                ← typed fetch client
    ├── types.ts              ← mirrors core/api.py Pydantic models
    └── components/
        ├── ToolTree.tsx      ← left sidebar: catalog by level + filter
        ├── ToolDetail.tsx    ← Inspect tab: tool metadata + steps + raw JSON
        ├── ExecutePanel.tsx  ← Execute tab: run selected tool with params
        ├── ComposerForm.tsx  ← Compose tab: form-based compound builder
        └── SceneGraphView.tsx← right sidebar: live scene graph
```

## How the three tabs map to the framework

| Tab | What it shows | Backend |
|---|---|---|
| **Inspect** | Selected tool's level, params, children, full step list, raw JSON | `GET /api/tools/{name}` |
| **Execute** | Param form + countdown → dispatches the tool against the live app | `POST /api/tools/{name}/run` |
| **Compose** | Pick steps, fill params, reorder, "Test draft" or "Save" | `POST /api/run-steps` / `POST /api/tools` |

The right sidebar (Scene graph) reads `state/scene_graph.json` and refreshes
after every run, so you can see object IDs and edges appear live.

## Composer tips

- **Top-level params** are the `$`-references your saved tool will accept.
  Example: enter `shape, label` here, then in a `place_shape` step write
  `tool_name=$shape` and in a `type_label` step write `text=$label`.
- **Literal vs. `$`-reference** — anything starting with `$` is treated as a
  parameter reference; everything else is JSON-parsed (so `120` becomes a
  number, `"n"` stays a string, `true` becomes a boolean). Strings without
  quotes are stored as raw strings — matching the existing JSON tool format.
- **Test draft** runs the current step list once via `POST /api/run-steps`
  without writing anything to disk. Failures stop at the failing step and
  return the partial result.
- **Edit in composer** on the Inspect tab pre-fills the form from any saved
  compound tool — useful for branching a successful trace into a variant.

## Backend endpoints (full)

| Method | Path | Body / Query | Purpose |
|---|---|---|---|
| GET | `/api/health` | — | liveness + tool count |
| GET | `/api/tools` | — | catalog summary |
| GET | `/api/tools/{name}` | — | full detail incl. raw JSON |
| POST | `/api/tools` | `SaveToolBody` | save new compound (calls `save_trace_as_tool`) |
| DELETE | `/api/tools/{name}` | — | remove JSON file + drop from catalog |
| POST | `/api/tools/{name}/run` | `{params, countdown}` | dispatch tool |
| POST | `/api/run-steps` | `{steps, params, countdown}` | ad-hoc dispatch w/o save |
| GET | `/api/scene-graph` | — | current scene graph |
| POST | `/api/scene-graph/reset` | — | wipe scene graph |
| GET | `/api/ui-graph` | — | calibrated sidebar shapes (names only) |

## Known limitations (v1)

- No typed params yet — everything is JSON-coerced. The orchestrator vision
  needs typed I/O (`scene_object`, `position`, etc.); that lands with v2.
- No node-graph composition view yet. The composer is a flat list editor.
- Top-level `$`-params can't be supplied for the **Test draft** button —
  the draft runs with `params={}` because the runtime values would have to
  come from somewhere. Use literal step params for testing, or save first
  and run via the Execute tab.
- Mouse moves go to whatever window has focus — the countdown is the only
  guard. Keep the runner terminal in mind.

## Next (v2 outline)

See [`ORCHESTRATOR.md`](../ORCHESTRATOR.md) for the full plan. The
shortest path from this v1 to the node-graph editor:

1. Add a `steps_graph` field alongside `steps` in saved tool JSON (back-compat).
2. Swap `ComposerForm` for a `react-flow`-based canvas, reading/writing the
   same `SaveToolBody.steps` plus the new edge wiring.
3. Add per-step checkpoint blocks and the repair-on-fail loop on the
   backend.
