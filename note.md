# drawioDemo — Codebase Guide

A full reference for understanding what this repo does, how every piece works, and how to run it.

**Current architecture note (updated 2026-05-17):** the agent now keeps sidebar tools as stable memory in `state/ui_graph.json`, but observes canvas nodes dynamically from each screenshot. The main loop is now capture → observe canvas → reason → act → capture again → verify.

---

## Table of Contents

1. [Running the Project (Mac + DSMLP)](#0-running-the-project-mac--dsmlp)
2. [What This Project Does](#1-what-this-project-does)
3. [Core Concepts](#2-core-concepts)
4. [System Requirements](#3-system-requirements)
5. [How to Run — Step by Step](#4-how-to-run--step-by-step)
6. [File-by-File Breakdown](#5-file-by-file-breakdown)
7. [Data Flow — End to End](#6-data-flow--end-to-end)
8. [Configuration Reference](#7-configuration-reference)
9. [Tool Reference](#8-tool-reference)
10. [Common Issues and Tips](#9-common-issues-and-tips)

---

## 0. Running the Project (Mac + DSMLP)

This is the **operator's manual** — captures the exact flow verified working on 2026-05-16. Follow §0.1–§0.4 once; for daily use, jump to **§0.5**.

### 0.1 The Split — What Runs Where, and Why

The agent needs a real, visible screen (screenshots + mouse clicks). Your Mac has that. DSMLP has the GPU but no GUI. So we split:

```
┌──────────────────────────────────────┐         ┌──────────────────────────────────────┐
│  YOUR MAC                            │         │   DSMLP POD (GPU, A30 24 GB)         │
│                                      │         │                                      │
│  - Draw.io desktop (FOREGROUND)      │         │  - ollama serve  (listens on 11434) │
│  - Cloned drawioDemo repo            │  HTTP   │     ├─ qwen3.5:35b  (planner)       │
│  - python main.py                    │ ◄────► │     └─ qwen3-vl:4b  (icon labeler)  │
│      • pyautogui screenshot+click   │  via    │  - Model weights at                  │
│      • OpenCV icon detection        │  SSH    │    /home/yay025/public/scratch/yay/  │
│      • talks to localhost:11434     │  -L     │      ollama_models   (~26 GB)        │
│                                      │ tunnel  │                                      │
└──────────────────────────────────────┘         └──────────────────────────────────────┘
```

The Mac → DSMLP connection is **one SSH command** that simultaneously:
1. Spawns a fresh GPU pod via `launch-sp26-cuda128.sh -H` (the `-H` flag launches `sshd` inside the pod for ProxyCommand transport).
2. Tunnels Mac port 11434 → pod port 11434 (`-L`).
3. Drops you into a pod shell where you start `ollama serve`.

**What persists between sessions on DSMLP:**

- `/home/yay025/public/scratch/yay/ollama_models/` — model weights (3 TB scratch, persistent ✅).
- `/home/yay025/.local/bin/ollama` — the binary. **Usually persists but sometimes doesn't** ($HOME mount has been observed empty in new pods; §0.5 has a one-line check).
- The pod itself does **NOT** persist. Every session = new pod with new hostname like `yay025-1928303`.

---

### 0.2 First-Time Setup — DSMLP Side (model server)

Do this once. After this, model weights live in shared scratch forever.

**Step A.** From Mac, open the tunnel + pod in one command (this is also your daily command — see §0.5):

```bash
ssh -L 11434:localhost:11434 \
  -o ProxyCommand="ssh yay025@dsmlp-login.ucsd.edu '/opt/launch-sh/bin/launch-sp26-cuda128.sh -W CSE252D_SP26_A00 -c 4 -m 16 -g 1 -l gpu-class=medium -H'" \
  yay025@dsmlp-pod
```

> ⚠ **Use the absolute path** `/opt/launch-sh/bin/launch-sp26-cuda128.sh` — the ProxyCommand runs in a non-interactive SSH shell where PATH does NOT include `/opt/launch-sh/bin`. The bare `launch-sp26-cuda128.sh` will give you `command not found`.

Duo-auth once (login-node leg). A new pod spawns. You'll see warnings like `cp: preserving permissions for ...authorized_keys: Operation not supported` — ignore them. First time you'll also get an SSH host key prompt — type `yes`.

You land at `yay025@yay025-XXXXXXX:~$`. Note the hostname — you'll need it if you want a second shell (see Step D).

**Step B.** Inside the pod, install Ollama. **Use `.tar.zst`, NOT `.tgz`** — the common stale-guide trap:

```bash
mkdir -p /home/yay025/.local
curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst \
  | tar -x --zstd -C /home/yay025/.local
/home/yay025/.local/bin/ollama -v   # should print "0.x.x"
```

> If `tar --zstd` errors (old tar), do it in two steps:
> ```bash
> curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst -o /tmp/o.tar.zst
> zstd -d /tmp/o.tar.zst -o /tmp/o.tar
> tar -xf /tmp/o.tar -C /home/yay025/.local
> ```
> **Do NOT use Ollama's official `curl … | sh` script** — it tries `sudo` which DSMLP blocks (`sudo: you do not exist in passwd db`).

**Step C.** Set up models directory and start serve:

```bash
export PATH=/home/yay025/.local/bin:$PATH
mkdir -p /home/yay025/public/scratch/yay/ollama_models
export OLLAMA_MODELS=/home/yay025/public/scratch/yay/ollama_models
ollama serve   # holds the terminal — that's correct
```

Look for these lines in the output (confirms GPU):
```
Listening on 127.0.0.1:11434
inference compute ... library=CUDA ... name=CUDA0 description="NVIDIA A30" ... total="24.0 GiB"
```

If you see `compute=cpu` and `total_vram="0 B"` instead, the pod didn't get a GPU — exit and re-launch with the full course flags above.

**Step D.** Open a **second shell into the same pod** to pull models. Don't open another `ssh -L ...` ProxyCommand — that spawns a *different* pod and you'll hit the 1-GPU quota. Instead, in a new Mac terminal:

```bash
ssh yay025@dsmlp-login.ucsd.edu
kubesh yay025-XXXXXXX     # ← the hostname from Step A
```

You're now in a second shell inside the same pod. Pull both models (in parallel for speed):

```bash
export PATH=/home/yay025/.local/bin:$PATH
ollama pull qwen3-vl:4b &
ollama pull qwen3.5:35b
wait
ollama list
```

Expected output:
```
NAME           ID              SIZE      MODIFIED
qwen3.5:35b    3460ffeede54    23 GB     ...
qwen3-vl:4b    1343d82ebee3    3.3 GB    ...
```

The 35B pull is ~20 GB — 5–15 min on DSMLP's network.

**Optional:** make weights world-readable for teammates: `chmod -R og+rX /home/yay025/public/scratch/yay`.

You can `exit` both shells now — pod will be destroyed, models stay in scratch.

---

### 0.3 First-Time Setup — Mac Side (controller)

```bash
cd ~/Desktop/26SP/252D/project/drawioDemo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install opencv-python httpx
```

> Every new terminal: `source ~/Desktop/26SP/252D/project/drawioDemo/.venv/bin/activate` first.

**Install Draw.io desktop** from [https://www.drawio.com/](https://www.drawio.com/) — use the *desktop app*, not browser (pyautogui can't reliably interact with browser tabs).

**Grant macOS permissions.** Open *System Settings → Privacy & Security*:

- **Accessibility** → enable Terminal (or iTerm). If not listed, click **+**, navigate to `/Applications/Utilities/Terminal.app`, click *Open*, toggle ON.
- **Screen Recording** → same flow.

**Fully quit Terminal (⌘Q, not just close window)**, reopen, re-activate venv. Verify with:

```bash
python -c "import pyautogui; print(pyautogui.position()); pyautogui.screenshot('/tmp/_perm.png'); print('OK')"
```

Should print coords and `OK`. "Not authorized" = permission didn't actually save; redo Settings.

---

### 0.4 First-Time Setup — Draw.io Window Layout

Calibration is sensitive to where Draw.io sits on screen. **Pick one window position and never move it.**

1. Open Draw.io desktop. Create a blank diagram.
2. Make sure the **left shape sidebar** is visible (View menu → *Shapes* if hidden).
3. Expand the **Basic / General** category so rectangle, ellipse, diamond thumbnails are visible.
4. Maximize Draw.io or place in a consistent spot.

> ⚠️ **Most common mistake** (we hit this once): when `test_collect_icons.py` runs its 5-second countdown, Draw.io must be the **frontmost window** — not Cursor, not Terminal, not Finder. Otherwise the screenshot captures whatever else is in front. Symptom: your `state/ui_graph.json` fills with labels like `Python_Tool`, `Snake_Tool`, `Text_Tool` (those are your IDE's file-tree icons being labeled by the VLM). Fix: bring Draw.io to front, re-run §0.6.

---

### 0.5 Every-Session Workflow

You need **2 or 3 Mac terminals**. After the first time it's muscle memory.

#### Terminal 1 — One command: pod + tunnel + shell (leave open)

```bash
ssh -L 11434:localhost:11434 \
  -o ProxyCommand="ssh yay025@dsmlp-login.ucsd.edu '/opt/launch-sh/bin/launch-sp26-cuda128.sh -W CSE252D_SP26_A00 -c 4 -m 16 -g 1 -l gpu-class=medium -H'" \
  yay025@dsmlp-pod
```

**What this does:**
- `ssh ... yay025@dsmlp-pod` opens an SSH session to a pod, with `-L 11434:...` forwarding Mac:11434 → pod:11434.
- `ProxyCommand` — instead of TCP-connecting directly to `dsmlp-pod`, run a command on `dsmlp-login` whose stdin/stdout is the SSH transport. That command (`launch-sp26-cuda128.sh -H`) launches a fresh pod with `sshd` inside.
- `-W CSE252D_SP26_A00 -c 4 -m 16 -g 1 -l gpu-class=medium` = course code, 4 CPU, 16 GB RAM, 1 GPU, 24 GB GPU class. The 24 GB GPU is the only size that fits `qwen3.5:35b`.

Duo-auth once. **Host key changes per pod hostname**, so if you ever see `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED`, run `ssh-keygen -R dsmlp-pod` and retry.

You'll land at `yay025@yay025-XXXXXXX:~$`. **Note the hostname** — needed for Terminal 2 below.

**Inside the pod:**

```bash
ls /home/yay025/.local/bin/ollama 2>&1     # if "No such file or directory", reinstall per §0.2 Step B
export OLLAMA_MODELS=/home/yay025/public/scratch/yay/ollama_models
/home/yay025/.local/bin/ollama serve
```

Confirm `total_vram="24.0 GiB"` and `NVIDIA A30` in the logs. Leave this terminal alone.

#### Terminal 2 (Mac) — Verify tunnel

```bash
curl http://localhost:11434/api/tags
```

Should return JSON listing both models. If `connection refused`, ollama serve isn't ready yet (wait a few seconds) or the tunnel didn't establish (check Terminal 1 for errors).

#### Terminal 3 (Mac) — Run the agent

```bash
cd ~/Desktop/26SP/252D/project/drawioDemo
source .venv/bin/activate

# First time / after Draw.io window moves: scan the sidebar (REMEMBER: Draw.io FRONTMOST)
python tests/test_collect_icons.py --detect --label --write

# Verify shapes — should list Rectangle_Tool, Ellipse_Tool, Diamond_Tool, etc.
python tests/demo_integration.py --tree

# Smoke-test without LLM
python tests/test_manual.py --run single --label "Cache"

# Smoke-test with LLM
python tests/test_auto.py --level 1

# Full agent run
python main.py --task "Add a rectangle labelled Cache"
python main.py --task "Add a rectangle labelled Cache" --trace

# Non-GUI regression tests for the reliability layer
python -m unittest tests.test_canvas tests.test_pipeline_rescan
```

> Every script has a 5-second countdown. During it, **click Draw.io to bring it foreground**, then DON'T touch anything until the script finishes.

---

### 0.6 When to re-run perception

Re-run `python tests/test_collect_icons.py --detect --label --write` if:

- You moved or resized the Draw.io window.
- You changed Mac display resolution / plugged in an external monitor.
- `state/ui_graph.json` got deleted or has garbage labels (`Python_Tool`, `Text_Tool`, etc. — meaning calibration captured the wrong window).

Otherwise `ui_graph.json` persists and you can skip perception on subsequent sessions.

---

### 0.7 Shutting Down

1. **Terminal 3** — just stop the script (Ctrl-C if mid-run).
2. **Terminal 2** — close the window.
3. **Terminal 1** — Ctrl-C `ollama serve`, then `exit`. **The pod is destroyed** when you exit the SSH session, freeing the GPU. Models in scratch persist.

If you forget to exit cleanly and the pod is still running next session, you'll hit `GPU quota exceeded`. Clean up from the login node:

```bash
ssh yay025@dsmlp-login.ucsd.edu
kubectl get pods                    # see what's still running
kubectl delete pod yay025-XXXXXXX   # delete the stale pod(s)
```

---

### 0.8 Troubleshooting — Gotchas We Actually Hit

| Symptom                                                                                  | Cause                                                                                  | Fix                                                                                                                                  |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `GPU quota exceeded. Wanted 1 but … 1 already in use`                                    | Old pod from a previous session still alive, holding the GPU                           | `ssh yay025@dsmlp-login.ucsd.edu`, then `kubectl get pods` + `kubectl delete pod yay025-XXXXXXX`                                     |
| `launch-sp26-cuda128.sh: command not found` (inside ProxyCommand)                        | Non-interactive SSH doesn't load PATH                                                  | Use the absolute path `/opt/launch-sh/bin/launch-sp26-cuda128.sh` in the ProxyCommand                                                |
| `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`                                       | Host key for `dsmlp-pod` rotates per pod; old key in `~/.ssh/known_hosts` no longer matches | `ssh-keygen -R dsmlp-pod` and retry                                                                                                  |
| Ollama install fails with `sudo: you do not exist in passwd db`                          | You ran `curl … \| sh` — uses sudo, blocked on DSMLP                                  | Use the `.tar.zst` extraction in §0.2 Step B                                                                                         |
| `404` on `ollama-linux-amd64.tgz`                                                        | Wrong extension; Ollama's Linux binary is `.tar.zst`                                  | Use `https://ollama.com/download/ollama-linux-amd64.tar.zst`                                                                         |
| `compute=cpu`, `total_vram="0 B"` in ollama startup                                      | Pod launched without GPU flags                                                         | Make sure launch command has `-W CSE252D_SP26_A00 -c 4 -m 16 -g 1 -l gpu-class=medium`                                              |
| `bind: address already in use` on port 11434 when running `ollama serve` on Mac          | You ran ollama on the wrong machine — it belongs in the pod. An old SSH tunnel may also be holding the port | `lsof -i :11434` to find the process; the tunnel from a previous Terminal 1 is what we want. Don't run `ollama serve` on the Mac. |
| `KeyError: 'Rectangle_Tool' not found. Available: [unknown_Tool, Python_Tool, Snake_Tool, Text_Tool, …]` | Calibration screenshot captured Cursor/IDE, not Draw.io                                 | Bring Draw.io fully foreground; during countdown click it once, don't touch anything else; re-run `test_collect_icons.py --detect --label --write` |
| `/home/yay025/.local/` empty in a fresh pod                                              | $HOME mount didn't persist (rare but seen)                                             | Reinstall ollama per §0.2 Step B; scratch (`/home/yay025/public/scratch/yay/`) and models stay intact                                |
| `Connection refused` on `curl localhost:11434` from Mac                                  | Tunnel down, or ollama serve hasn't started                                            | Check Terminal 1: is the pod prompt there? Is `ollama serve` printing logs? Are there `Listening on 127.0.0.1:11434` lines?         |
| `pyautogui.FailSafeException`                                                            | Mouse hit a screen corner during run                                                   | Don't touch the mouse during a live run                                                                                              |
| Mouse moves but Draw.io ignores clicks                                                   | Draw.io not focused, or Accessibility permission not actually saved                    | Quit Terminal (⌘Q), reopen, retest with the `pyautogui` snippet in §0.3                                                              |
| Icons detected but all labelled `unknown`                                                | VLM timeouts (model loading on first call, or tunnel hiccup)                           | Increase `explorer.label_timeout` in `config.json`; check Terminal 1 — is qwen3-vl:4b loading?                                       |
| First LLM call takes 30+ seconds                                                         | Model loading into VRAM on cold start — normal                                         | Subsequent calls should be 2–5s. If consistently slow, swap planner to `qwen2.5:7b` in `config.json` → `llm.model`                  |

---

## 1. What This Project Does

This is an **AI agent that controls Draw.io by moving the mouse and typing**, exactly as a human would. You give it a task in plain English like `"Add a rectangle labelled Cache"`, and it:

1. Takes a screenshot of your screen
2. Asks a local LLM (running via Ollama) "what should I click next?"
3. Executes that click/keystroke using `pyautogui`
4. Repeats until the task is done

It never hardcodes pixel positions. Instead, it uses a **name-based abstraction** — the LLM says "click `Rectangle_Tool`", and the system looks up where that icon currently lives on your screen.

There are **three perception/control layers**:

- **Sidebar perception** — runs when the Draw.io layout changes; scans the sidebar and saves tool coordinates to `state/ui_graph.json`
- **Canvas observation** — runs every pipeline step; detects approximate visible canvas nodes from the current screenshot
- **Operation pipeline** — runs repeatedly to plan, execute, verify, and update history from the observed screen state

---

## 2. Core Concepts

### Perceive → Reason → Act Loop

The agent works in a loop (max 10 iterations by default):

```
Screenshot → observe canvas → LLM decides next tool → execute tool → screenshot → verify → repeat
```

Each iteration:

- **Perceive**: capture a screenshot of the screen
- **Observe**: extract approximate canvas nodes from the screenshot
- **Reason**: send screenshot + task + history to the LLM, get back `{ "tool": "...", "params": {...}, "reasoning": "..." }`
- **Act**: execute that tool (move mouse, click, type)
- **Verify**: compare pre/post screenshots and observed canvas state

The loop terminates when the LLM returns `task_complete` or when max steps is reached.

### Coordinate Abstraction

The LLM never sees pixel coordinates. It only sees **names**:

- Sidebar shapes: `Rectangle_Tool`, `Diamond_Tool`, `Ellipse_Tool`, ...
- Canvas nodes: `Observed_Node_1`, `Observed_Node_2`, or text labels when text perception is available

The system maps names → coordinates at the last moment, inside the tool execution functions. This means:

- The LLM prompt is the same regardless of screen resolution or window position
- Recalibrating only requires re-running the perception pipeline — no LLM prompt changes needed

### The UI Graph

A dict that represents the current state of the UI. Passed to tools and the LLM at every step:

```python
{
  "UI_Elements": {                    # sidebar shapes with coordinates
    "Rectangle_Tool": {"x": 33, "y": 299, "w": 32, "h": 17},
    ...
  },
  "Canvas_Nodes": [                   # shapes already on the canvas
    {"id": "Observed_Node_1", "text": "", "x": 600, "y": 400, "confidence": 0.82},
    ...
  ],
  "Canvas_Edges": []                  # connections between canvas nodes
}
```

The LLM only sees the names (never x/y). The tools use the full dict to resolve coordinates.

`UI_Elements` comes from `state/ui_graph.json` (written by the perception pipeline).
`Canvas_Nodes` comes from `core/perception/canvas.py` at runtime when the pipeline has a screenshot. `Canvas_Edges` remains empty/static for this phase.

### Hierarchical Tool Tree

Tools are organized in a two-level tree across multiple files:

- **L0 (leaf)** — one atomic GUI action (click a point, press a key, type text) — defined in `core/tools/primitives.py`
- **L1 (compound)** — a sequence of L0 actions packaged as a single call — defined in `domains/drawio/tools.py`

For example, `place_shape_then_edit_label` (L1) internally calls `place_shape` → `press_escape` → `press_enter` → `select_all` → `type_label` → `press_escape` → `click_empty_canvas`. The LLM should prefer it for labelled-shape tasks because it explicitly enters label edit mode before typing.

Level is auto-computed: a compound node's level = `max(child.level) + 1`. You never set it manually.

All tools self-register into a global `TOOL_CATALOG` at import time via `register()`.

### Domain Plugin System

The tool system is domain-agnostic. The active domain is set in `config.json` as `"domain": "drawio"`. When `core/tools/__init__.py` is imported, it dynamically loads `domains.drawio.tools`, which registers the Draw.io-specific compound tools. To support a different application, you'd create `domains/<name>/tools.py` and change the config.

### How Draw.io Interaction Works

Draw.io's behavior when you click a sidebar shape:

1. Click sidebar icon → shape appears on canvas at a default position, text cursor is already active inside
2. While cursor is active: type text → it becomes the shape's label
3. Press Escape → exits text editing, shape stays selected
4. Click empty canvas → deselects the shape

`place_shape_then_edit_label` is the preferred workflow for new labelled shapes because it explicitly enters label edit mode. `place_and_label` is still available as the older direct workflow.

---

## 3. System Requirements

**Python packages:**

```bash
pip install -r requirements.txt       # pyautogui, ollama, Pillow
pip install opencv-python httpx       # for perception pipeline (NOT in requirements.txt)
```

**External:**

- **Draw.io desktop app** running and visible on screen
- **Ollama** running locally with two models pulled:

```bash
ollama pull qwen3.5:35b       # planner — decides which tool to use (text-only)
ollama pull qwen3-vl:4b       # vision — labels sidebar icons (multimodal)
```

**macOS note:** `pyautogui` requires Accessibility permissions. Go to System Settings → Privacy & Security → Accessibility → allow Terminal (or your IDE).

**Retina display note:** If on a Retina Mac, physical pixels = 2× logical pixels. `config.json` has `"screen_scale": 2` to handle this. Change to `1` on non-Retina.

---

## 4. How to Run — Step by Step

### Step 0: One-time setup

```bash
cd drawioDemo
pip install -r requirements.txt
pip install opencv-python httpx
```

### Step 1: Explore — detect sidebar icons

This maps Draw.io's sidebar icons to pixel coordinates. Only needed once per screen setup.

```bash
# Open Draw.io, make sure the sidebar is visible
python tests/test_collect_icons.py --detect --label --write
# You have 5 seconds to switch to Draw.io after running this
```

What happens:

- Takes a screenshot
- Uses OpenCV to find all icon-sized rectangles in the sidebar region (`core/perception/detect.py`)
- Sends each icon crop to the VLM (`qwen3-vl:4b`) to get a name like "Rectangle", "Diamond" (`core/perception/label.py`)
- Writes results to `state/ui_graph.json` (`core/state/ui_graph.py`)

Verify it worked:

```bash
python tests/demo_integration.py --tree   # shows detected icons and tool tree
```

If icons look wrong, adjust `sidebar_region` in `config.json` (see §7).

### Step 2: Test without LLM (optional)

Verifies pyautogui can click the right places without any LLM overhead:

```bash
python tests/test_manual.py --calibrate    # just takes a screenshot
python tests/test_manual.py --run single --dry-run   # preview steps
python tests/test_manual.py --run single --label "Cache"  # live run
```

### Step 3: Test with LLM (optional)

Verifies the LLM picks the right tools:

```bash
python tests/test_auto.py --level 1 --dry-run   # safe, no mouse movement
python tests/test_auto.py --level 1              # live: place a shape
python tests/test_auto.py --level 2              # live: place + label
python tests/test_auto.py --level 3              # live: full workflow
```

### Step 4: Run the full agent

```bash
python main.py --task "Add a rectangle labelled Cache"
python main.py --task "Add a rectangle labelled Cache" --dry-run   # LLM decides, no execution
python main.py --task "Add a rectangle labelled Cache" --trace     # writes diagnostics to test_output/runs/
```

The agent runs the perceive→observe→reason→act→verify loop up to `max_steps` times.

---

## 5. File-by-File Breakdown

### `main.py` — Entry point

The CLI. Parses arguments and calls either:

- `screenshot()` to capture and print the UI graph (for debugging)
- `core/pipeline.run(task, trace=...)` to start the agent loop

### `config.json` — Master configuration

The single source of truth for all settings. Human-editable. No code changes needed to recalibrate.

Key sections:

- `domain` — which domain plugin to load (`"drawio"`)
- `paths` — where screenshots, test output, and state files are saved; `state_dir` + `ui_graph_file` point to `state/ui_graph.json`
- `calibration` — pixel coordinates of known points (canvas nodes, empty space)
- `explorer.canvas_region` — physical-pixel crop used by runtime canvas observation
- `llm` — which Ollama model to use and how many steps to allow
- `executor` — timing: how fast to type, how long drags take, pauses between steps
- `explorer` — settings for the perception pipeline (region to scan, icon size range, VLM model)

### `core/config.py` — Config accessor layer

Reads `config.json` and `state/ui_graph.json` and exposes typed getter functions. No code elsewhere reads JSON directly — everything goes through this module.

Key functions:

- `ui_graph(screenshot_path=...)` — merges `state/ui_graph.json` UI elements with observed canvas nodes when a screenshot is provided
- `load_ui_state()` — loads `state/ui_graph.json` directly (returns `{}` if missing)
- `domain()` — returns active domain plugin name from config
- `ui_graph_path()` — returns full path to `state/ui_graph.json`
- `canvas_region()` — returns the canvas crop in physical pixels

Config is loaded at import time and cached. Call `config.reload()` if you change `config.json` at runtime.

### `core/capture.py` — Screenshot capture

One function: `screenshot(filename)`. Takes a full screenshot using `pyautogui.screenshot()` and saves it to `screenshots/`. Returns the absolute path.

### `core/pipeline.py` — Agentic control loop

The core of the agent. `run(task, dry_run, trace)` executes the perceive→observe→reason→act→verify loop:

```
for step in range(max_steps):
    img_path = screenshot(...)             # perceive
    graph = observe_canvas + sidebar state # observe
    decision = infer(task, graph, img)     # reason
    if decision.tool == "task_complete": break
    if decision.tool == "request_rescan": continue
    result = dispatch(decision.tool, decision.params)  # act
    after_img = screenshot(...)
    verification = verify_action(...)
```

Maintains a `history` list of prior decisions plus verification summaries, passed to the LLM on each turn so it knows what it already did and whether the screen changed. With `--trace`, it writes one JSON file per step under `test_output/runs/<timestamp>/`.

### `core/agents/executor.py` — LLM interface (the "executor agent")

Builds the system prompt and calls Ollama. This was previously `operation/llm.py`.

**Prompt structure (sent to LLM every step):**

1. System instructions: rules, Draw.io workflow, available tools as markdown table
2. Detected elements: sidebar shape names, ambiguous tool families, observed canvas node names (NO coordinates)
3. History: prior tool calls (if any)
4. User message: the task + current screenshot as image bytes

**Output format the LLM must follow:**

```json
{
  "reasoning": "explain step by step what to do",
  "tool": "place_shape",
  "params": {"tool_name": "Rectangle_Tool"}
}
```

`parse_response()` is tolerant: tries raw JSON, then fenced code blocks, then substring extraction. Also accepts `"action"` as an alias for `"tool"`.

### `core/tools/__init__.py` — Tool loader

Imports `core.tools.primitives` (self-registers all L0 tools), then dynamically imports `domains.<domain>.tools` (self-registers L1+ tools). After this import, `dispatch()` can execute any tool by name. Re-exports all public aliases for direct script use.

### `core/tools/registry.py` — ToolNode and dispatch

Defines the `ToolNode` dataclass and the global `TOOL_CATALOG`. Key parts:

- `ToolNode` — wraps a function with metadata: name, params, description, children. `level` is auto-computed.
- `register(node)` — adds a node to `ALL_NODES` and `TOOL_CATALOG`
- `dispatch(tool_name, params, ui_graph)` — looks up the tool, injects `ui_graph` if needed, validates params, calls `node.execute()`
- `resolve_tool(ui_graph, name)` — looks up a sidebar icon's (x, y) by name
- `resolve_node(ui_graph, ref)` — finds a canvas node by id or text label

### `core/tools/primitives.py` — Leaf tools (L0)

14 atomic GUI operations, each wrapping a single `pyautogui` call. All self-register at the bottom of the file. Public function aliases are exported for direct use in test scripts.

### `domains/drawio/tools.py` — Compound tools (L1)

Draw.io-specific multi-step workflows. Composes primitives from `core/tools/primitives.py`. Self-registers at the bottom of the file.

### `core/perception/detect.py` — OpenCV icon detection

`detect_icons(screenshot_path)`:

1. Crops screenshot to sidebar region (physical pixels)
2. Canny edge detection + contour finding
3. Filters by size range and aspect ratio
4. NMS (non-maximum suppression) to deduplicate nearby detections
5. Returns coordinates in **logical pixels** (physical ÷ screen_scale)

`annotate(screenshot_path, icons, output_path)` draws bounding boxes for visual verification.

### `core/perception/label.py` — VLM icon labeling

`label_icons(screenshot_path, icons)`:

- Crops each detected icon from the screenshot
- Sends to Qwen-VL via Ollama with a real HTTP timeout (uses `httpx.Client`)
- Returns label like "Rectangle", "Diamond", "Ellipse"
- Handles timeouts and retries (configurable in `config.json`)

### `core/perception/canvas.py` — Runtime canvas observation

`observe_canvas(screenshot_path)`:

- Crops the current screenshot to `explorer.canvas_region`
- Uses OpenCV contours to detect visible closed shapes on the canvas
- Returns approximate runtime nodes like `Observed_Node_1` with logical center/size, confidence, stroke density, rectangularity, and source metadata
- `annotate_canvas()` writes visual debug images showing detected canvas boxes during traced runs
- Provides graph summaries and ambiguous sidebar tool families for traces and prompts

This is intentionally approximate. For v1, it is mainly used to answer "did a shape appear?" and to provide the planner with current visible canvas state.

### `core/verification.py` — Post-action checks

`verify_action(...)` compares before/after screenshots and observed graphs:

- `place_shape` / `place_and_label` / `place_shape_then_edit_label`: node-count increase is a strong pass
- `type_label` / `edit_label`: canvas image change is a weak pass because OCR is not implemented yet
- `press_escape`, `press_enter`, and `click_empty_canvas`: non-blocking weak pass unless dispatch failed
`text_placement` is currently recorded as `unknown`.

### `core/state/ui_graph.py` — State persistence

`save_ui_state(icons)` — formats labeled icons as `{label}_Tool` entries and writes to `state/ui_graph.json`. Handles duplicate labels by appending `_1`, `_2`, etc.

### `state/ui_graph.json` — Detected icon coordinates (OUTPUT)

Auto-generated by the perception pipeline. Not hand-edited.

Schema:

```json
{
  "ui_elements": {
    "Rectangle_Tool": {"x": 33, "y": 299, "w": 32, "h": 17},
    ...
  }
}
```

`x, y` are the center of the icon in logical pixels.

### `tests/test_collect_icons.py` — Perception pipeline test

Runs the full perception pipeline: screenshot → detect → (optionally label) → (optionally write). Saves annotated screenshots to `test_output/` for visual verification.

### `tests/test_manual.py` — Manual test (no LLM)

Runs hardcoded action sequences directly via the tool functions. Used to verify pyautogui is clicking the right places before adding LLM complexity.

- `--calibrate` just takes a screenshot
- `--run single` executes: place Rectangle_Tool → type label → escape → deselect
- `--run double` places two rectangles

### `tests/test_auto.py` — LLM integration test

Tests that the LLM picks the right tools for progressively harder tasks:

- Level 1: single step (place shape)
- Level 2: two steps (place + label)
- Level 3: multi-step (full workflow including escape and deselect)

`--prompt-only` prints the full system prompt without running anything.

### `tests/test_canvas.py` — Canvas observer regression test

Uses synthetic screenshots to verify that an empty canvas returns zero nodes and a simple rectangle returns one observed node. Does not require Draw.io, Ollama, or pyautogui.

### `tests/test_pipeline_rescan.py` — Rescan regression test

Mocks screenshots and LLM decisions to verify that `request_rescan` uses a fresh screenshot-backed canvas observation instead of reusing stale state.

### `tests/demo_integration.py` — Integration demo

Loads `state/ui_graph.json` and demonstrates the full perception→operation flow:

- `--mode leaf`: calls L0 tools one by one
- `--mode compound`: calls L1 `place_and_label` as a single call
- `--tree`: prints the full tool hierarchy + available icon names

---

## 6. Data Flow — End to End

```
User: "Add a rectangle labelled Cache"
          │
          ▼
     main.py
          │
          ▼
  core/pipeline.run(task)
    │
    ├── [Step 1] ─────────────────────────────────────────────────
    │   core/capture.py → screenshot("step_01.png")
    │           │
    │           ▼
    │   core/perception/canvas.py → observe_canvas("step_01.png")
    │     │  Builds runtime Canvas_Nodes like Observed_Node_1
    │           │
    │           ▼
    │   core/agents/executor.py → infer(task, ui_graph, img_path)
    │     │  Builds prompt with:
    │     │    - Tool catalog (from TOOL_CATALOG)
    │     │    - Sidebar tool names (from state/ui_graph.json)
    │     │    - Observed canvas nodes (from current screenshot)
    │     │    - Ambiguous tool families (e.g. Rectangle_Family)
    │     │    - Screenshot bytes
    │     │  Sends to Ollama (qwen3.5:35b)
    │     │  Gets back: {"tool": "place_shape_then_edit_label",
    │     │              "params": {"tool_name": "Rectangle_Tool", "label": "Cache"}}
    │           │
    │           ▼
    │   core/tools → dispatch("place_shape_then_edit_label", params, ui_graph)
    │     │  Looks up ToolNode in TOOL_CATALOG
    │     │  Calls domains/drawio/tools._fn_place_shape_then_edit_label(ui_graph, "Rectangle_Tool", "Cache")
    │     │    ├── place_shape → resolve "Rectangle_Tool" → (33, 299) → pyautogui.click(33, 299)
    │     │    ├── press_escape → normalize selection/edit state
    │     │    ├── press_enter → enter label edit mode
    │     │    ├── select_all
    │     │    ├── type_label → pyautogui.typewrite("Cache")
    │     │    ├── press_escape → exit text editing
    │     │    └── click_empty_canvas → pyautogui.click(600, 400)
    │           │
    │           ▼
    │   core/capture.py → screenshot("step_01_after.png")
    │           │
    │           ▼
    │   core/verification.py → verify_action(...)
    │     │  Compares before/after screenshots and observed node counts
    │           │
    │           ▼
    │         History records dispatch status + verification result
    │
    ├── [Step 2] LLM returns task_complete
    │
    └── pipeline returns log
```

**Where coordinates come from:**

- Sidebar icon positions (`Rectangle_Tool` → (33, 299)) come from `state/ui_graph.json`
- Runtime canvas node positions come from `core/perception/canvas.py` observations
- Empty canvas click position comes from `config.json` → `calibration.empty_canvas_point`

---

## 7. Configuration Reference

### `config.json` full schema

```json
{
  "domain": "drawio",               // active domain plugin — loads domains/drawio/tools.py

  "paths": {
    "screenshots_dir": "screenshots",   // where step_XX.png files go
    "test_output_dir": "test_output",   // where test output files go
    "state_dir": "state",               // where ui_graph.json lives
    "ui_graph_file": "ui_graph.json"    // filename inside state_dir
  },

  "calibration": {
    "canvas_nodes": [],                 // legacy/static fallback; runtime nodes come from screenshots
    "canvas_edges": [],                 // connections: currently static/empty in v1
    "empty_canvas_point": [600, 400]    // logical pixel coord of blank canvas area
  },

  "llm": {
    "model": "qwen3.5:35b",            // Ollama model for the planner
    "max_steps": 10                     // max perceive/reason/act iterations
  },

  "executor": {
    "failsafe": true,                   // move mouse to corner to abort (pyautogui failsafe)
    "pause": 0.15,                      // seconds between pyautogui calls
    "drag_duration": 0.5,               // seconds for drag operations
    "type_interval": 0.03,             // seconds between keystrokes when typing
    "step_cooldown": 0.5,              // seconds to wait after each pipeline step
    "countdown_seconds": 5             // countdown before live tests start
  },

  "explorer": {
    "model": "qwen3-vl:4b",           // VLM for icon labeling
    "screen_scale": 2,                 // 2 for Retina, 1 for non-Retina
    "sidebar_region": [0, 480, 380, 1120], // [x1, y1, x2, y2] in PHYSICAL pixels
    "canvas_region": [630, 260, 2350, 1720], // canvas crop in PHYSICAL pixels
    "icon_size_range": [20, 70],       // min/max icon size in physical pixels
    "nms_distance": 20,                // deduplicate icons within this many logical px
    "label_timeout": 30,               // seconds before VLM request times out
    "label_max_retries": 2             // retries before marking icon as "unknown"
  }
}
```

### Recalibrating `sidebar_region`

If Draw.io moves or you change screen resolution:

1. Take a screenshot: `python main.py --screenshot`
2. Open `screenshots/manual_capture.png` in any image viewer
3. Find the pixel bounds of the shape sidebar (in **physical** pixels on Retina)
4. Update `"sidebar_region": [x1, y1, x2, y2]` in `config.json`
5. Re-run perception: `python tests/test_collect_icons.py --detect --label --write`

### Recalibrating `canvas_region`

`canvas_region` is the screenshot crop used by `core/perception/canvas.py`. If the observer misses shapes or detects sidebar/UI noise as canvas nodes:

1. Take a screenshot: `python main.py --screenshot`
2. Open `screenshots/manual_capture.png`
3. Find the physical-pixel bounds of the draw.io canvas area, excluding the sidebar and top toolbar as much as practical
4. Update `"canvas_region": [x1, y1, x2, y2]` in `config.json`
5. Run `python -m unittest tests.test_canvas tests.test_pipeline_rescan`
6. Try a live traced run: `python main.py --task "Add a rectangle labelled Cache" --trace`

### Runtime `Canvas_Nodes`

`canvas_nodes` in `config.json` is now a legacy/static fallback. During the main pipeline, `Canvas_Nodes` is rebuilt from the current screenshot and looks like:

```json
[
  {
    "id": "Observed_Node_1",
    "text": "",
    "x": 600,
    "y": 400,
    "w": 120,
    "h": 60,
    "confidence": 0.82,
    "source": "opencv_canvas_contour"
  }
]
```

Text recognition and edge detection are not implemented in this phase, so labels may remain empty and `Canvas_Edges` may remain empty.

---

## 8. Tool Reference

### Leaf tools (L0) — atomic operations (`core/tools/primitives.py`)


| Tool                 | Params                                               | What it does                                     |
| -------------------- | ---------------------------------------------------- | ------------------------------------------------ |
| `place_shape`        | `tool_name`                                          | Click a sidebar icon to place that shape         |
| `type_label`         | `text`                                               | Type text into the active shape's text field     |
| `press_escape`       | —                                                    | Exit text editing mode                           |
| `press_enter`        | —                                                    | Press Enter to confirm                           |
| `press_delete`       | —                                                    | Delete selected element (Backspace)              |
| `select_all`         | —                                                    | Cmd+A to select all text                         |
| `click_empty_canvas` | —                                                    | Click blank canvas to deselect                   |
| `click_node`         | `node_ref`, `clicks`                                 | Click a canvas node by id or label               |
| `double_click_node`  | `node_ref`                                           | Double-click to enter text edit on existing node |
| `drag_node`          | `node_ref`, `target_x`, `target_y`                   | Drag node to absolute position                   |
| `drag_node_near`     | `node_ref`, `reference_node`, `offset_x`, `offset_y` | Drag node relative to another                    |
| `resize_node`        | `node_ref`, `new_width`, `new_height`                | Resize a node                                    |
| `hotkey`             | `keys`                                               | Press a keyboard shortcut                        |
| `undo`               | —                                                    | Cmd+Z                                            |


### Compound tools (L1) — multi-step workflows (`domains/drawio/tools.py`)


| Tool                | Params                             | Steps inside                                                                    |
| ------------------- | ---------------------------------- | ------------------------------------------------------------------------------- |
| `place_and_label`   | `tool_name`, `label`               | place_shape → type_label → press_escape → click_empty_canvas                    |
| `place_shape_then_edit_label` | `tool_name`, `label` | place_shape → press_escape → press_enter → select_all → type_label → press_escape → click_empty_canvas |
| `edit_label`        | `node_ref`, `new_label`            | double_click_node → select_all → type_label → press_escape → click_empty_canvas |
| `delete_node`       | `node_ref`                         | click_node → press_delete → click_empty_canvas                                  |
| `move_and_deselect` | `node_ref`, `target_x`, `target_y` | drag_node → click_empty_canvas                                                  |


### Special signals (not tools, no params)


| Signal           | Meaning                                                       |
| ---------------- | ------------------------------------------------------------- |
| `task_complete`  | LLM signals the task is finished — loop exits                 |
| `request_rescan` | LLM wants a fresh screenshot-backed UI graph before deciding  |


### Adding a new compound tool

In `domains/drawio/tools.py` (or a new domain file):

```python
def _fn_my_tool(ui_graph, param1, param2):
    steps = []
    steps.append(_fn_place_shape(ui_graph, param1))
    time.sleep(_STEP_PAUSE)
    steps.append(_fn_type_label(param2))
    ok = all(s.get("status") == "ok" for s in steps)
    return {"status": "ok" if ok else "partial", "tool": "my_tool", "steps": steps}

N_MY_TOOL = ToolNode(
    name="my_tool", fn=_fn_my_tool,
    params=["param1", "param2"], needs_ui_graph=True,
    description="One sentence describing what this does.",
    children=[N_PLACE_SHAPE, N_TYPE_LABEL],   # level auto-computed
)

register(N_MY_TOOL)  # self-registers at import time
```

---

## 9. Common Issues and Tips

**Mouse moves but nothing happens in Draw.io**

- Make sure Draw.io is focused/in the foreground when the countdown ends
- Increase the countdown delay: `countdown_seconds` in `config.json`

**Wrong shapes detected (ui_graph.json has bad labels)**

- The VLM (`qwen3-vl:4b`) can misidentify icons. Check `test_output/labeled_icons.png`
- You can manually edit `state/ui_graph.json` to fix labels
- Or re-run with a better model: change `explorer.model` in `config.json`

**LLM picks wrong tools or invents non-existent tools**

- Run `python tests/test_auto.py --prompt-only` to see what the LLM sees
- If `state/ui_graph.json` is empty or missing, re-run the perception pipeline
- For ambiguous repeated icons like `Rectangle_Tool_1`, check the prompt's `Ambiguous Sidebar Families` section
- Increase `max_steps` if the task needs more iterations

**Agent cannot tell whether the canvas changed**

- Run with `--trace` and inspect `test_output/runs/<timestamp>/step_XX.json`
- Check `ui_graph_before`, `ui_graph_after`, and `verification`
- If observed node count is wrong, recalibrate `explorer.canvas_region`
- Current text verification is image-change based, not OCR-based

**Mouse flies to corner and aborts**

- `pyautogui.FAILSAFE = True` is intentional — moving mouse to any corner stops execution
- To disable: set `"failsafe": false` in `config.json`

**Retina display issues (coordinates off by 2x)**

- Verify `"screen_scale": 2` in `config.json`
- The `sidebar_region` uses **physical** pixels; everything returned by `detect_icons` is **logical** (÷ screen_scale)

`**httpx` or `cv2` import errors**

- These packages are not in `requirements.txt`:
  ```bash
  pip install opencv-python httpx
  ```

`**state/ui_graph.json` missing**

- Run the perception pipeline first: `python tests/test_collect_icons.py --detect --label --write`
- `core/config.load_ui_state()` returns `{}` if the file doesn't exist, so `UI_Elements` will be empty

**LLM calls `double_click_node` after `place_shape`**

- This is wrong. After `place_shape`, the text cursor is already active — use `type_label` directly.
- The system prompt in `core/agents/executor.py` explicitly states this rule. If the LLM keeps doing this, the rules section may need strengthening.
