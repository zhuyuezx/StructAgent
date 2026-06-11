# Plan: Pluggable LLM Backends and Targeted draw.io Browser Capture

## Goals

1. Replace direct `ollama` calls with a provider abstraction that supports:
   - Existing local Ollama models.
   - OpenAI-compatible HTTP APIs, including vLLM running Qwen series models.
   - Hosted APIs such as OpenAI.
   - Text-only and vision requests used by planner, executor, critic, and icon labeling.
2. Replace focus-dependent full-screen screenshots with a target-aware capture/control layer that can find the Chrome tab running draw.io and capture only that tab. Prefer backend operation through browser automation when available, while keeping the current PyAutoGUI path as a fallback.

## Current Code Touchpoints

- LLM calls are hardcoded in:
  - `core/agents/planner.py`
  - `core/agents/executor.py`
  - `core/agents/critic.py`
  - `core/perception/label.py`
- Screenshot capture is centralized in `core/capture.py`, but tools and reconciliation depend on it indirectly:
  - `core/pipeline.py`
  - `core/orchestrator.py`
  - `core/tools/reconcile.py`
  - `core/api.py`
- Mouse/keyboard control is currently direct PyAutoGUI in `core/tools/atoms.py`.
- Configuration is loaded from `config.json` through `core/config.py`.

## Phase 1: Add a Model Provider Abstraction

Create a new package, `core/llm/`, with:

- `types.py`: shared request/response types.
- `client.py`: public functions such as `chat_text(...)`, `chat_vision(...)`, and `chat(...)`.
- `providers/ollama.py`: wraps the existing `ollama.chat` behavior.
- `providers/openai_compatible.py`: uses the OpenAI-compatible Chat Completions API for OpenAI, vLLM, and similar servers.

Target interface:

```python
response = llm.chat(
    purpose="planner",
    messages=messages,
    images=[screenshot_path],  # optional
    response_format="json_object",
    timeout=60,
)
raw = response.content
```

The provider layer should normalize image inputs. Existing Ollama calls pass raw image bytes in `images`; OpenAI-compatible APIs usually need base64 `data:image/png;base64,...` content blocks. Keep this conversion in the provider layer, not in agents.

## Phase 2: Extend Configuration

Update `config.json` from single-model fields to purpose-specific model configs while preserving backward compatibility.

Example:

```json
{
  "models": {
    "planner": {
      "provider": "openai_compatible",
      "model": "Qwen3.5-32B-Instruct",
      "base_url": "http://localhost:8001/v1",
      "api_key_env": "VLLM_API_KEY",
      "timeout": 90
    },
    "executor": {
      "provider": "ollama",
      "model": "qwen3.5:35b"
    },
    "critic": {
      "provider": "openai",
      "model": "gpt-4.1-mini",
      "api_key_env": "OPENAI_API_KEY",
      "timeout": 60
    },
    "explorer": {
      "provider": "ollama",
      "model": "qwen3-vl:4b",
      "timeout": 30
    }
  }
}
```

Add helpers in `core/config.py`:

- `model_config(purpose: str)`
- `planner_model_config()`
- `executor_model_config()`
- `critic_model_config()`
- `explorer_model_config()`

Keep `llm_model()`, `critic_model()`, and `explorer_model()` temporarily so existing tests and code continue to run during migration.

## Phase 3: Migrate Agents to the Provider Layer

Replace direct imports of `ollama` in:

- `planner.plan`
- `planner.chat_plan`
- `planner.repair`
- `executor.infer`
- `critic.verify`
- `label.label_icons`

Each call site should pass its purpose name, messages, optional images, and timeout. Parsing should remain local to each agent because planner/executor/critic have different output schemas.

Add tests that monkeypatch the provider instead of requiring a live model:

- Planner sends text-only messages correctly.
- Planner attaches an image when `screenshot_path` is set.
- Critic fails safe on provider errors.
- Icon labeling handles timeout and retry behavior through mocked provider exceptions.

## Phase 4: Add Target-Aware Screenshot Capture

Introduce `core/target/` with:

- `base.py`: abstract `CaptureController` and `InputController`.
- `pyautogui_target.py`: current full-screen screenshot and input behavior.
- `chrome_cdp.py`: Chrome DevTools Protocol implementation.
- `manager.py`: selects the active target from config.

Extend `core/capture.py` so `screenshot(filename)` delegates to the configured target controller. Keep the function signature stable for orchestrator and tests.

Example config:

```json
{
  "target": {
    "backend": "chrome_cdp",
    "browser": "chrome",
    "debug_port": 9222,
    "url_match": ["app.diagrams.net", "draw.io", "drawio"],
    "screenshot_mode": "tab",
    "fallback": "pyautogui"
  }
}
```

The CDP controller should:

1. Query `http://127.0.0.1:9222/json`.
2. Find a page whose URL or title matches draw.io.
3. Connect to its `webSocketDebuggerUrl`.
4. Use `Page.captureScreenshot` for tab-only screenshots.
5. Store the screenshot under `config.screenshots_dir()`.

Important limitation: Chrome must be started with remote debugging enabled, for example:

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir=D:\tmp\drawio-chrome-profile
```

A normal Chrome session cannot always be attached to after launch. Document this clearly and provide fallback behavior.

## Phase 5: Backend Browser Input Control

Move input calls behind the same target abstraction used for screenshots.

Refactor `core/tools/atoms.py` so:

- `atom_move_to`
- `atom_click_at`
- `atom_drag`
- `atom_press`
- `atom_hotkey`
- `atom_write`

delegate to `target.manager.input_controller()`.

Implement two input backends:

- `PyAutoGuiInputController`: current behavior.
- `ChromeCdpInputController`: uses CDP `Input.dispatchMouseEvent` and `Input.dispatchKeyEvent`.

This is what enables “I am still in VS Code, but the backend modifies draw.io.” The CDP path can dispatch events to the draw.io tab without making it the foreground OS window. If CDP is unavailable, retain the current countdown/focus workflow.

## Phase 6: Coordinate Mapping and Calibration

The existing UI graph stores screen-oriented coordinates. CDP input uses browser viewport coordinates. Add a coordinate mapper:

- For PyAutoGUI: identity mapping.
- For CDP: map logical draw.io coordinates into the tab viewport.

Initial implementation can require recalibrating `state/ui_graph.drawio.json` from CDP screenshots. Later, add automatic detection of canvas/sidebar offsets from the tab screenshot.

Update perception assumptions:

- `core/perception/detect.py` and handle detection can work on tab screenshots if coordinates are consistently reported in the same coordinate system.
- `config.screen_scale()` may need to become target-specific because CDP screenshots and OS screenshots can have different device scale factors.

## Phase 7: API and Frontend Support

Add backend endpoints:

- `GET /api/target/status`: selected backend, connected tab title, URL, viewport size.
- `POST /api/target/refresh`: rescan browser tabs.
- `POST /api/target/screenshot`: capture the selected target tab.

Frontend changes:

- Show target status near the run controls.
- Warn when CDP is configured but no draw.io tab is found.
- Keep existing countdown fields for PyAutoGUI fallback.

## Phase 8: Validation Plan

Offline tests:

```powershell
python tests/test_planner.py --dry-run
python tests/test_planner.py --parse-demo
python tests/test_checkpoint.py
```

New unit tests:

- Mock Ollama provider.
- Mock OpenAI-compatible provider.
- Mock CDP tab discovery and screenshot response.
- Verify fallback to PyAutoGUI when CDP target is missing.

Manual integration tests:

1. Start vLLM with an OpenAI-compatible endpoint and configure planner to use it.
2. Start Chrome with `--remote-debugging-port=9222`.
3. Open draw.io in one tab and keep VS Code focused.
4. Call `/api/target/status` and verify the draw.io tab is selected.
5. Capture `/api/target/screenshot` and verify it contains only the draw.io tab.
6. Run a dry plan, then run a simple live action such as placing and labeling one rectangle.
7. Verify checkpoint screenshots come from the target tab, not the active desktop window.

## Risks and Decisions

- Hosted OpenAI vision models and local vLLM vision models use different image message formats; the provider layer must hide this.
- Some Qwen/vLLM deployments expose OpenAI-compatible text chat but not image chat. The config should allow text planner on vLLM and vision critic/explorer on another provider.
- Background modification is realistic with CDP, but only for browser-hosted draw.io. Native desktop draw.io still needs OS-level automation or another backend.
- Existing UI graph coordinates may need a one-time recapture when switching from full-screen screenshots to tab screenshots.

## Recommended Implementation Order

1. Add `core/llm` provider abstraction and migrate planner only.
2. Migrate executor, critic, and icon labeling.
3. Add CDP screenshot capture while leaving PyAutoGUI input unchanged.
4. Add target status API and frontend visibility.
5. Refactor atom input through target controllers.
6. Add CDP input dispatch and coordinate mapping.
7. Recalibrate draw.io UI graph under tab-only screenshot mode.
