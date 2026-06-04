"""
Orchestrator — run a Planner-produced plan deterministically.

This is the Phase-1 ``run_graph`` driver from ORCHESTRATOR.md, scoped to a
linear plan: walk an ordered list of ``{tool, params}`` steps, dispatch each
through the existing :func:`core.tools.dispatch` path, and thread one shared
``ui_graph`` through every call so selection / handles / scene-graph state
carry across steps (the same way the notebooks do).

It is the deterministic counterpart to the per-turn :func:`core.pipeline.run`:
the LLM is consulted ONCE (by :mod:`core.agents.planner`) to produce the plan;
the orchestrator then executes it with zero further inference.

The trace it returns — a list of ``{step, tool, params, result}`` dicts — is
exactly the shape that :func:`core.tools.save_tool.save_trace_as_tool` consumes
(via its ``trace=`` argument), so a successful plan can be persisted as a
reusable compound tool in one call. See :func:`trace_to_steps`.

**Checkpoints (Phase 2).** Any step may carry a ``"checkpoint"`` dict (see
:mod:`core.checkpoint`). After such a step runs, :func:`run_plan` captures a
screenshot and evaluates the checkpoint's structural assertions against the
live ``ui_graph['scene_graph']``, recording the pass/fail result and the
screenshot path on the trace entry under ``"checkpoint"``. This is the cheap,
deterministic verification the orchestrator is built around — no per-step LLM.
The ``on_step`` callback fires once per step (after the checkpoint is
evaluated) — the seam the repair loop (Phase 3) and the live UI hang off of.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from core import config
from core import checkpoint as _ckpt
from core.tools import TOOL_CATALOG, dispatch

logger = logging.getLogger(__name__)

# Type alias: a per-step observer, called with each trace entry as it lands.
StepCallback = Callable[[Dict[str, Any]], None]
# Type alias: a screenshot capturer (filename -> saved path). Injectable so
# tests can avoid touching the screen.
ScreenshotFn = Callable[[str], str]


def _capture_checkpoint_screenshot(
    step_index: int, screenshot_fn: Optional[ScreenshotFn],
) -> Dict[str, Optional[str]]:
    """Take a screenshot for a checkpoint; never raise (capture is best-effort).

    Returns ``{"path": <abs path or None>, "error": <str or None>}``.
    """
    fn = screenshot_fn
    if fn is None:
        from core.capture import screenshot as fn  # lazy: avoids GUI deps offline
    try:
        path = fn(f"_checkpoint_step{step_index:02d}.png")
        return {"path": path, "error": None}
    except Exception as e:  # pragma: no cover - depends on display/permissions
        logger.warning("checkpoint screenshot failed at step %d: %s", step_index, e)
        return {"path": None, "error": str(e)}


def run_plan(
    steps: List[Dict[str, Any]],
    ui_graph: Optional[Dict[str, Any]] = None,
    *,
    dry_run: bool = False,
    stop_on_error: bool = True,
    stop_on_checkpoint_fail: bool = False,
    capture_checkpoints: bool = True,
    screenshot_fn: Optional[ScreenshotFn] = None,
    step_cooldown: Optional[float] = None,
    on_step: Optional[StepCallback] = None,
) -> List[Dict[str, Any]]:
    """Execute *steps* in order, returning a per-step trace.

    Parameters
    ----------
    steps:
        Ordered list of ``{"tool": str, "params": dict, "checkpoint"?: dict}``
        (the planner's ``steps``). A step may carry an optional ``checkpoint``
        (see :mod:`core.checkpoint`); other extra keys are ignored.
    ui_graph:
        Shared UI graph threaded through every dispatch. Defaults to
        :func:`core.config.ui_graph`. Pass the same dict the rest of your
        session uses so selection / scene-graph state is shared.
    dry_run:
        If True, no tool is dispatched; each step records ``status='dry_run'``
        and any checkpoint is marked skipped (the scene graph is not advanced).
    stop_on_error:
        If True (default), stop at the first step whose dispatch errors.
    stop_on_checkpoint_fail:
        If True, also stop when a step's checkpoint assertions fail (the seam
        the repair loop will use). Default False — record and keep going so the
        user sees every checkpoint outcome.
    capture_checkpoints:
        If True (default), take a screenshot at each checkpointed step (unless
        the checkpoint sets ``"screenshot": false``). Set False to evaluate
        assertions without touching the screen.
    screenshot_fn:
        Override the screenshot capturer (``filename -> path``). Defaults to
        :func:`core.capture.screenshot`. Injectable for tests.
    step_cooldown:
        Seconds to sleep between live steps. Defaults to
        :func:`core.config.step_cooldown`. Skipped on dry runs.
    on_step:
        Optional callback invoked with each trace entry right after it is
        produced (and after its checkpoint is evaluated).

    Returns
    -------
    list of ``{"step", "tool", "params", "result", "checkpoint"?}`` dicts — one
    per attempted step. ``checkpoint`` (when present) is the :func:`evaluate`
    result extended with ``"screenshot"`` (path or None). Use
    :func:`plan_succeeded` to check it and :func:`trace_to_steps` to save it.
    """
    graph = ui_graph if ui_graph is not None else config.ui_graph()
    cooldown = config.step_cooldown() if step_cooldown is None else step_cooldown

    trace: List[Dict[str, Any]] = []
    logger.info("run_plan: %d step(s)%s", len(steps), " (dry run)" if dry_run else "")

    for i, step in enumerate(steps, 1):
        tool = step.get("tool")
        params = dict(step.get("params") or {})

        if not tool:
            result = {"status": "error", "error": "step missing 'tool'"}
        elif tool not in TOOL_CATALOG:
            result = {"status": "error", "tool": tool,
                      "error": f"unknown tool '{tool}'"}
        elif dry_run:
            result = {"status": "dry_run", "tool": tool,
                      "level": TOOL_CATALOG[tool].level}
        else:
            result = dispatch(tool, params, ui_graph=graph)

        entry: Dict[str, Any] = {"step": i, "tool": tool,
                                 "params": params, "result": result}
        logger.info("  step %d/%d  %s  → %s",
                    i, len(steps), tool, result.get("status"))

        # ── Checkpoint: screenshot + structural assertion eval ──────────
        ckpt = step.get("checkpoint")
        if ckpt:
            if dry_run:
                entry["checkpoint"] = {"skipped": True, "reason": "dry_run",
                                       "passed": None,
                                       "description": ckpt.get("description", "")}
            else:
                cp_result = _ckpt.evaluate(ckpt, graph.get("scene_graph") or {})
                shot: Optional[str] = None
                shot_err: Optional[str] = None
                if capture_checkpoints and ckpt.get("screenshot", True):
                    cap = _capture_checkpoint_screenshot(i, screenshot_fn)
                    shot, shot_err = cap["path"], cap["error"]
                cp_result["screenshot"] = shot
                if shot_err:
                    cp_result["screenshot_error"] = shot_err
                entry["checkpoint"] = cp_result
                logger.info("    checkpoint: %s", _ckpt.summarize(cp_result))

        trace.append(entry)
        if on_step is not None:
            on_step(entry)

        if result.get("status") == "error" and stop_on_error:
            logger.warning("run_plan: stopping at step %d (%s): %s",
                           i, tool, result.get("error"))
            break

        cp = entry.get("checkpoint")
        if (stop_on_checkpoint_fail and cp is not None
                and cp.get("passed") is False):
            logger.warning("run_plan: stopping at step %d — checkpoint failed", i)
            break

        if not dry_run and cooldown:
            time.sleep(cooldown)

    return trace


def plan_succeeded(trace: List[Dict[str, Any]]) -> bool:
    """True if every step in *trace* dispatched cleanly (``ok`` or ``dry_run``).

    This is *execution* success only — it does not consider checkpoints. Use
    :func:`checkpoints_passed` to verify the structural assertions.
    """
    return bool(trace) and all(
        e["result"].get("status") in ("ok", "dry_run") for e in trace
    )


def checkpoints_passed(trace: List[Dict[str, Any]]) -> bool:
    """True if no checkpoint in *trace* failed.

    A step with no checkpoint, or a checkpoint skipped on a dry run
    (``passed is None``), does not count against the result.
    """
    return all(
        e["checkpoint"].get("passed") is not False
        for e in trace if e.get("checkpoint") is not None
    )


def trace_to_steps(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce a run_plan trace to ``[{tool, params}]`` for saving as a tool.

    Pair with :func:`core.tools.save_tool.save_trace_as_tool`, passing the full
    trace as ``trace=`` so id→label sanitization can run::

        steps = trace_to_steps(tr)
        save_trace_as_tool("my_tool", steps=steps, trace=tr, description="…")
    """
    return [{"tool": e["tool"], "params": e["params"]} for e in trace]


def plan_and_run(
    task: str,
    ui_graph: Optional[Dict[str, Any]] = None,
    *,
    screenshot_path: Optional[str] = None,
    dry_run: bool = False,
    stop_on_error: bool = True,
    on_step: Optional[StepCallback] = None,
) -> Dict[str, Any]:
    """Plan *task* with the LLM, then run the plan. One-call convenience.

    Returns ``{"plan": <planner output>, "trace": <run_plan trace>,
    "ok": bool}``. Imports the planner lazily so importing the orchestrator
    does not require ``ollama`` (e.g. for dry-run / offline use).
    """
    from core.agents.planner import plan as _plan

    graph = ui_graph if ui_graph is not None else config.ui_graph()
    plan_out = _plan(task, graph, screenshot_path=screenshot_path)
    trace = run_plan(
        plan_out["steps"], graph,
        dry_run=dry_run, stop_on_error=stop_on_error, on_step=on_step,
    )
    return {"plan": plan_out, "trace": trace, "ok": plan_succeeded(trace)}
