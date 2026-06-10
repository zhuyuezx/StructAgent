# Plan: Screenshot+SG vs. Text-Only Ablation

## Goal

Conduct a controlled ablation for the report subsection:

> Screenshot+SG vs. Text-Only

The central claim to validate is:

1. When the scene graph is complete, text-only planning/execution reaches the same final diagram structure as screenshot-grounded execution.
2. Removing the screenshot from each LLM turn reduces wall-clock time because no image is encoded or sent per turn.
3. The screenshot should be reserved for verification/checkpoints, not used as the default planning signal.

The ablation should produce a small, defensible table and one figure for the report, not just anecdotal demo notes.

## Existing Code Paths

Primary path for the subsection:

- `core.agents.executor.infer(task, ui_graph, screenshot_path=...)`
  - `screenshot_path=<png>`: screenshot + scene graph.
  - `screenshot_path=None`: text-only, scene graph only.
- `core.pipeline.run(...)` currently always captures and passes a screenshot. For a clean executor ablation, add or use a small harness that can toggle whether the screenshot is attached to the executor while still allowing internal framework screenshots for perception/reconciliation.

Supporting path:

- `core.agents.planner.plan(task, ui_graph, screenshot_path=...)`
  - Default is already text-only.
  - `tests/test_planner.py --live "..." --screenshot` runs the screenshot+SG planner condition.
  - This is useful as secondary evidence for the planner default, but the report text is about the executor's optional screenshot input, so executor-mode should be the main study.

Do not count framework-internal screenshots used for capture, handle detection, checkpoint screenshots, or reconciliation as "screenshot input" to the LLM. The ablation variable is only whether the model receives an image attachment.

## Hypotheses

H1: Text-only reaches the same final scene graph as screenshot+SG for the tested draw.io tasks when the scene graph starts clean and remains complete.

H2: Text-only uses the same or fewer executor turns. The expected range from the current source-target demo is 6-7 turns.

H3: Text-only has lower wall-clock latency per LLM turn and lower total wall-clock time, with an expected speedup of roughly 2-3x for screenshot-heavy local/hosted models.

H4: Failures in text-only, if any, should expose missing symbolic state in `scene_graph.summary_for_prompt`, not a fundamental need for screenshots during planning.

## Experimental Conditions

Run each task under two conditions:

| Condition | Executor prompt | Image attached to LLM | Internal framework screenshots |
|---|---|---:|---:|
| `sg_only` | Text-only input block | No | Yes, only as needed by tools/reconciliation/checkpoints |
| `screenshot_sg` | Screenshot+SG input block | Yes, one per executor turn | Yes |

Use the same:

- Git branch: `screenshot_ablation`
- Model config in `config.json`
- Draw.io browser/session setup
- Tool catalog under `state/tools/`
- Initial scene graph reset policy
- Task wording
- Max steps and cooldown
- Hardware and network environment

If possible, set temperature to 0 in the configured model backend. If the backend does not expose temperature in this repo, document the default and run more repetitions.

## Task Suite

Use tasks that match the demos already run and scale the number of objects.

Task A, source-target baseline:

```text
Place two rectangles labelled Source and Target and connect Source to Target.
```

Task B, 3 rectangles:

```text
Place three rectangles labelled Rect1, Rect2, and Rect3. Connect Rect1 to Rect2 and Rect2 to Rect3.
```

Task C, 5 rectangles:

```text
Place five rectangles labelled Rect1, Rect2, Rect3, Rect4, and Rect5. Connect them in order from Rect1 to Rect2 to Rect3 to Rect4 to Rect5.
```

Task D, 6 rectangles:

```text
Place six rectangles labelled Rect1, Rect2, Rect3, Rect4, Rect5, and Rect6. Connect them in order from Rect1 to Rect2 to Rect3 to Rect4 to Rect5 to Rect6.
```

The report paragraph can focus on the source-target task if space is tight, but the 3/5/6 rectangle tasks provide stronger scaling evidence for the demo.

## Repetitions

Minimum:

- 3 repetitions per `(task, condition)` pair.
- Total: `4 tasks x 2 conditions x 3 reps = 24` live runs.

Preferred if time allows:

- 5 repetitions per pair.
- Total: `4 x 2 x 5 = 40` live runs.

Use paired ordering to reduce drift:

1. Reset canvas and scene graph.
2. Run Task A `sg_only`, rep 1.
3. Reset.
4. Run Task A `screenshot_sg`, rep 1.
5. Continue alternating conditions for the same task before moving to the next task.

If a run fails due to external UI focus, browser crash, model server outage, or operator interruption, mark it as `invalid_external` and rerun it. If it fails because the model chose wrong tools or the symbolic state was insufficient, keep it as a real failure.

## Required Harness

Add a lightweight script rather than editing `main.py` behavior. Suggested path:

```text
tests/run_screenshot_ablation.py
```

The script should:

1. Accept:
   - `--task-id source_target|rect3|rect5|rect6`
   - `--condition sg_only|screenshot_sg`
   - `--rep N`
   - `--max-steps N`
   - `--out logs/ablation`
   - `--dry-run` for prompt/logging checks only
2. Reset or require reset of the draw.io canvas and `scene_graph/scene_graph.json` before each live run.
3. Execute the normal executor loop.
4. In `screenshot_sg`, capture and pass a screenshot path to `infer`.
5. In `sg_only`, either:
   - do not call `screenshot` before `infer`, if no tool needs it at that point, or
   - capture internally only when needed for framework state, but pass `screenshot_path=None` to `infer`.
6. Time each LLM call separately from tool dispatch.
7. Save a structured JSON record for every run.

Suggested output:

```text
logs/ablation/
  2026-06-09_source_target_sg_only_rep01.json
  2026-06-09_source_target_screenshot_sg_rep01.json
  ...
  screenshots/
    source_target_sg_only_rep01_final.png
    source_target_screenshot_sg_rep01_final.png
```

## Per-Run Log Schema

Each run JSON should include:

```json
{
  "task_id": "rect5",
  "task": "Place five rectangles ...",
  "condition": "sg_only",
  "rep": 1,
  "branch": "screenshot_ablation",
  "commit": "<git sha>",
  "model": {
    "planner": "...",
    "executor": "...",
    "provider": "..."
  },
  "started_at": "...",
  "ended_at": "...",
  "total_wall_s": 0.0,
  "success": true,
  "failure_type": null,
  "turns": 0,
  "llm_wall_s": 0.0,
  "tool_wall_s": 0.0,
  "screenshot_input_count": 0,
  "final_scene_graph": {},
  "final_summary": "...",
  "trace": [
    {
      "step": 1,
      "tool": "place_shape",
      "params": {},
      "llm_wall_s": 0.0,
      "tool_wall_s": 0.0,
      "used_screenshot_input": false,
      "result_status": "ok"
    }
  ],
  "final_checks": {
    "expected_objects": 5,
    "expected_edges": 4,
    "labels_present": ["Rect1", "Rect2", "Rect3", "Rect4", "Rect5"],
    "edges_present": [
      ["Rect1", "Rect2"],
      ["Rect2", "Rect3"],
      ["Rect3", "Rect4"],
      ["Rect4", "Rect5"]
    ],
    "no_obvious_overlap": true
  }
}
```

## Success Criteria

A run is successful only if all of these pass:

1. Execution terminates with `task_complete` or reaches an equivalent final state before `max_steps`.
2. The final scene graph has exactly the expected labels, or at minimum contains all expected labels with no extra semantically conflicting labels.
3. The final scene graph has the expected edges.
4. The final screenshot does not show severe overlap, off-canvas placement, missing shapes, or visibly wrong labels.

Use scene graph checks as the primary structural metric and the final screenshot as verification evidence. This aligns with the report claim: screenshot is valuable as verification, not as the default planning signal.

## Final-State Equivalence

For each paired run, compare the final scene graph against a task-specific expected graph rather than requiring pixel-identical layouts.

For `rect5`, expected structure:

```text
objects:
  Rect1, Rect2, Rect3, Rect4, Rect5
edges:
  Rect1 -> Rect2
  Rect2 -> Rect3
  Rect3 -> Rect4
  Rect4 -> Rect5
```

Equivalent layouts may differ in coordinates, direction choices, or exact edge routing. They are equivalent if the graph topology and labels match and the diagram is visually legible.

## Metrics

Record and report:

- Success rate: successful runs / valid runs.
- Executor turns: number of LLM decisions until completion.
- Total wall-clock time.
- LLM wall-clock time.
- Tool dispatch wall-clock time.
- Screenshot input count.
- Mean time per LLM turn.
- Final-state equivalence: yes/no.
- Repair/rescan count, if any.
- Failure category:
  - `model_wrong_tool`
  - `model_stopped_early`
  - `scene_graph_incomplete`
  - `tool_dispatch_error`
  - `ui_focus_or_browser_error`
  - `timeout_or_max_steps`

For the report figure, the most important values are:

| Task | Condition | Success | Turns | Total wall-clock | Speedup vs screenshot+SG | Equivalent final state |
|---|---:|---:|---:|---:|---:|---:|

## Concrete Run Procedure

Before live runs:

```powershell
git branch --show-current
python tests/test_planner.py --dry-run
python tests/test_planner.py --parse-demo
python tests/test_checkpoint.py
```

Start services as needed:

```powershell
python -m uvicorn core.api:app --port 8000
```

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Start Chrome with remote debugging if using the target-aware browser path:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="D:\tmp\drawio-chrome-profile"
```

Verify target status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/target/status
```

For each run:

1. Reset draw.io canvas.
2. Reset `scene_graph/scene_graph.json`.
3. Capture or verify a clean starting scene graph.
4. Run the selected `(task, condition, rep)`.
5. Save the run JSON and final screenshot.
6. Inspect the final screenshot and mark visual equivalence.
7. Move to the paired condition.

Suggested commands once the harness exists:

```powershell
python tests/run_screenshot_ablation.py --task-id source_target --condition sg_only --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id source_target --condition screenshot_sg --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect3 --condition sg_only --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect3 --condition screenshot_sg --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect5 --condition sg_only --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect5 --condition screenshot_sg --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect6 --condition sg_only --rep 1 --out logs/ablation
python tests/run_screenshot_ablation.py --task-id rect6 --condition screenshot_sg --rep 1 --out logs/ablation
```

## Analysis Script

Add a small summarizer:

```text
tests/summarize_screenshot_ablation.py
```

It should read `logs/ablation/*.json` and emit:

1. Markdown table for the report.
2. CSV for plotting.
3. Optional JSON aggregate.

Suggested outputs:

```text
logs/ablation/summary.md
logs/ablation/summary.csv
logs/ablation/summary.json
```

Aggregate by `(task_id, condition)`:

- `n`
- `success_rate`
- `turns_mean`
- `turns_std`
- `total_wall_s_mean`
- `total_wall_s_std`
- `llm_wall_s_mean`
- `llm_wall_s_std`
- `screenshot_input_count_mean`
- `equivalent_final_state_rate`

Compute speedup as:

```text
speedup = mean_total_wall_s(screenshot_sg) / mean_total_wall_s(sg_only)
```

Use paired speedup where both reps are valid:

```text
paired_speedup_rep_i =
  total_wall_s(task, screenshot_sg, rep_i) /
  total_wall_s(task, sg_only, rep_i)
```

Report paired mean if the paired protocol was followed.

## Figure Plan

Create `Figure textonly` as a compact grouped bar chart:

- X axis: task (`2`, `3`, `5`, `6` rectangles/nodes).
- Y axis: mean wall-clock seconds.
- Bars: `sg_only` and `screenshot_sg`.
- Annotate each bar with mean turn count.
- Add a checkmark or text marker for final-state equivalence rate, e.g. `3/3 equiv`.

Caption direction:

```text
Scene-graph-only planning matches the screenshot-grounded result while avoiding per-turn image encoding. Bars show mean wall-clock time; labels show executor turns and final-state equivalence over repeated runs.
```

If space is limited in the paper, use only source-target in the figure and mention 3/5/6 rectangle runs in the text or appendix.

## Reporting Template

Use cautious wording unless every run succeeds:

```text
Across the source-target and 3/5/6-rectangle tasks, text-only execution reached a structurally equivalent final scene graph in X/Y valid runs. It required A turns on average, compared with B turns for screenshot+SG, and reduced total wall-clock time from C s to D s on average. The failures, when present, were attributable to <category>, indicating <interpretation>.
```

For the current subsection, the strongest version is:

```text
The ablation supports the planner's text-only default: when the scene graph is complete, the symbolic state carries the planning-relevant information. Screenshots remain useful as verification/checkpoint evidence, where they catch visual drift that the symbolic state may miss.
```

## Risks and Controls

- UI focus can contaminate live results. Use the target-aware Chrome setup when possible and log target status.
- Scene graph reset must be consistent. A stale graph invalidates the comparison.
- Model nondeterminism can blur small differences. Use paired runs and multiple reps.
- Screenshot+SG may sometimes produce different layouts. Treat topology and legibility as equivalence, not exact coordinates.
- Internal perception screenshots are not the ablation variable. Be explicit in the methodology.
- If text-only fails on larger tasks, inspect whether the prompt lacks enough symbolic layout information or whether the model made a generic planning error.

## Deliverables

1. `logs/ablation/*.json` run records.
2. `logs/ablation/summary.md`.
3. `logs/ablation/summary.csv`.
4. Final screenshots for each valid run.
5. One report-ready chart for Figure `textonly`.
6. A short paragraph updating the LaTeX subsection with actual numbers.

## Recommended Order

1. Implement or verify the executor ablation harness.
2. Run one dry/logging pass for `source_target` in both conditions.
3. Run one live paired pilot for `source_target`.
4. Inspect logs and final screenshots; fix only harness/logging issues.
5. Run the full paired suite for 3 reps.
6. Generate summaries and the figure.
7. Update the report text with measured numbers.
