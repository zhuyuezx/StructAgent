"""
Live ablation harness for screenshot+SG vs. scene-graph-only input.

The experimental switch is narrow:

    screenshot_sg -> pass a screenshot path to the model
    sg_only       -> pass screenshot_path=None

Framework/tool-internal screenshots may still occur during dispatch and
reconciliation. Those are not counted as LLM screenshot inputs.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from core.agents.executor import infer
from core.agents.planner import plan
from core.capture import screenshot
from core.orchestrator import run_plan
from core.state import scene_graph as sg
from core.tools import TOOL_CATALOG, dispatch


TASKS: Dict[str, Dict[str, Any]] = {
    "source_target": {
        "task": (
            "Place two non-overlapping rectangles labelled Source and Target "
            "and connect Source to Target."
        ),
        "labels": ["Source", "Target"],
        "edges": [("Source", "Target")],
    },
    "rect3": {
        "task": (
            "Place three non-overlapping rectangles labelled Rect1, Rect2, and Rect3. "
            "Connect Rect1 to Rect2 and Rect2 to Rect3."
        ),
        "labels": ["Rect1", "Rect2", "Rect3"],
        "edges": [("Rect1", "Rect2"), ("Rect2", "Rect3")],
    },
    "rect5": {
        "task": (
            "Place five non-overlapping rectangles labelled Rect1, Rect2, Rect3, Rect4, and Rect5. "
            "Connect them in order from Rect1 to Rect2 to Rect3 to Rect4 to Rect5."
        ),
        "labels": ["Rect1", "Rect2", "Rect3", "Rect4", "Rect5"],
        "edges": [
            ("Rect1", "Rect2"),
            ("Rect2", "Rect3"),
            ("Rect3", "Rect4"),
            ("Rect4", "Rect5"),
        ],
    },
    "rect6": {
        "task": (
            "Place six non-overlapping rectangles labelled Rect1, Rect2, Rect3, Rect4, Rect5, and Rect6. "
            "Connect them in order from Rect1 to Rect2 to Rect3 to Rect4 to Rect5 to Rect6."
        ),
        "labels": ["Rect1", "Rect2", "Rect3", "Rect4", "Rect5", "Rect6"],
        "edges": [
            ("Rect1", "Rect2"),
            ("Rect2", "Rect3"),
            ("Rect3", "Rect4"),
            ("Rect4", "Rect5"),
            ("Rect5", "Rect6"),
        ],
    },
}


def _git_value(*args: str) -> Optional[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=config.project_root(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    value = proc.stdout.strip()
    return value or None


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in value)


def _countdown(seconds: int, message: str) -> None:
    if seconds <= 0:
        return
    print(message)
    for remaining in range(seconds, 0, -1):
        print(f"  {remaining}s")
        time.sleep(1)


def _clear_canvas(graph: Dict[str, Any], countdown_seconds: int) -> None:
    _countdown(countdown_seconds, "Focus draw.io now; clearing canvas in:")
    dispatch("click_empty_canvas", {}, ui_graph=graph)
    time.sleep(0.2)
    dispatch("select_all", {}, ui_graph=graph)
    time.sleep(0.2)
    dispatch("press_delete", {}, ui_graph=graph)
    time.sleep(0.2)
    graph["scene_graph"] = sg.reset()


def _labels_present(graph: Dict[str, Any], expected: Iterable[str]) -> Dict[str, bool]:
    labels = {str(o.get("label", "")) for o in graph.get("objects", [])}
    return {label: label in labels for label in expected}


def _edge_label_pairs(graph: Dict[str, Any]) -> set[Tuple[str, str]]:
    label_by_id = {
        o.get("id"): str(o.get("label", ""))
        for o in graph.get("objects", [])
    }
    pairs: set[Tuple[str, str]] = set()
    for edge in graph.get("edges", []):
        source = label_by_id.get(edge.get("source"), str(edge.get("source", "")))
        target = label_by_id.get(edge.get("target"), str(edge.get("target", "")))
        pairs.add((source, target))
    return pairs


def _edges_present(graph: Dict[str, Any], expected: Iterable[Tuple[str, str]]) -> Dict[str, bool]:
    actual = _edge_label_pairs(graph)
    return {f"{source}->{target}": (source, target) in actual for source, target in expected}


def _bbox_intersects(a: List[int], b: List[int], min_gap: int = 0) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (
        ax + aw + min_gap <= bx
        or bx + bw + min_gap <= ax
        or ay + ah + min_gap <= by
        or by + bh + min_gap <= ay
    )


def _no_obvious_overlap(graph: Dict[str, Any]) -> bool:
    boxes = [
        (str(o.get("label") or o.get("id")), o.get("bbox"))
        for o in graph.get("objects", [])
        if isinstance(o.get("bbox"), list) and len(o.get("bbox")) == 4
    ]
    for i, (_, box_a) in enumerate(boxes):
        for _, box_b in boxes[i + 1:]:
            if _bbox_intersects(box_a, box_b):
                return False
    return True


def _final_checks(
    graph: Dict[str, Any],
    expected_labels: List[str],
    expected_edges: List[Tuple[str, str]],
) -> Dict[str, Any]:
    label_checks = _labels_present(graph, expected_labels)
    edge_checks = _edges_present(graph, expected_edges)
    actual_labels = [str(o.get("label", "")) for o in graph.get("objects", [])]
    return {
        "expected_objects": len(expected_labels),
        "expected_edges": len(expected_edges),
        "actual_objects": len(graph.get("objects", [])),
        "actual_edges": len(graph.get("edges", [])),
        "labels_present": label_checks,
        "edges_present": edge_checks,
        "actual_labels": actual_labels,
        "actual_edge_label_pairs": [list(pair) for pair in sorted(_edge_label_pairs(graph))],
        "no_obvious_overlap": _no_obvious_overlap(graph),
        "labels_ok": all(label_checks.values()),
        "edges_ok": all(edge_checks.values()),
    }


def _failure_type(
    *,
    terminated_by_task_complete: bool,
    final_checks: Dict[str, Any],
    trace: List[Dict[str, Any]],
    max_steps_reached: bool,
) -> Optional[str]:
    if final_checks["labels_ok"] and final_checks["edges_ok"] and final_checks["no_obvious_overlap"]:
        return None
    if any(e.get("result", {}).get("phase") == "llm" for e in trace):
        return "llm_error"
    if any(e.get("result", {}).get("phase") == "screenshot_capture" for e in trace):
        return "ui_focus_or_browser_error"
    if any(e.get("result", {}).get("status") == "error" for e in trace):
        return "tool_dispatch_error"
    if max_steps_reached and not terminated_by_task_complete:
        return "timeout_or_max_steps"
    if not final_checks["labels_ok"] or not final_checks["edges_ok"]:
        return "model_wrong_tool"
    if not final_checks["no_obvious_overlap"]:
        return "model_layout_overlap"
    return "unknown"


def _required_params_for_tool(tool_name: str) -> List[str]:
    node = TOOL_CATALOG[tool_name]
    try:
        sig = inspect.signature(node.fn)
    except (TypeError, ValueError):
        return list(node.params)

    required: List[str] = []
    for param_name in node.params:
        param = sig.parameters.get(param_name)
        if param is None or param.default is inspect.Parameter.empty:
            required.append(param_name)
    return required


def _validate_plan_steps(steps: Any) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(steps, list):
        return {"valid": False, "errors": ["Planner output 'steps' is not a list."]}
    if not steps:
        return {"valid": False, "errors": ["Planner output contains no steps."]}

    placement_offsets: Dict[Tuple[str, int], List[int]] = {}
    place_and_label_steps: List[int] = []

    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            errors.append(f"Step {index} is not an object.")
            continue

        tool = step.get("tool")
        params = step.get("params") or {}
        if not tool:
            errors.append(f"Step {index} is missing tool.")
            continue
        if tool not in TOOL_CATALOG:
            errors.append(f"Step {index} uses unknown tool {tool!r}.")
            continue
        if not isinstance(params, dict):
            errors.append(f"Step {index} uses {tool} but params is not an object.")
            continue

        required = _required_params_for_tool(tool)
        if tool == "place_label_and_move":
            required = ["tool_name", "label", "direction", "amount"]
        elif tool == "place_and_label":
            place_and_label_steps.append(index)

        missing = [name for name in required if name not in params or params[name] in ("", None)]
        if missing:
            errors.append(
                f"Step {index} uses {tool} but is missing required params: "
                f"{', '.join(missing)}."
            )

        if tool == "place_label_and_move" and not missing:
            direction = str(params.get("direction", "")).lower().strip()
            try:
                amount = int(params.get("amount"))
            except (TypeError, ValueError):
                errors.append(f"Step {index} uses place_label_and_move but amount is not an integer.")
                continue
            placement_offsets.setdefault((direction, amount), []).append(index)

        if tool == "move_shape" and index > 1:
            prev = steps[index - 2] if isinstance(steps[index - 2], dict) else {}
            if prev.get("tool") == "place_and_label":
                errors.append(
                    f"Step {index} moves after step {index - 1} place_and_label. "
                    "Use place_label_and_move instead so the target shape remains known and selected."
                )

    for (direction, amount), indexes in placement_offsets.items():
        if len(indexes) > 1:
            joined = ", ".join(str(i) for i in indexes)
            errors.append(
                f"Steps {joined} all use place_label_and_move with the same offset "
                f"{direction} {amount}, which stacks shapes at the same location."
            )

    if len(place_and_label_steps) > 1:
        joined = ", ".join(str(i) for i in place_and_label_steps)
        errors.append(
            f"Steps {joined} use place_and_label multiple times. For multiple free-standing "
            "rectangles, use place_label_and_move with distinct direction/amount offsets."
        )

    return {"valid": not errors, "errors": errors}


def _validation_retry_history(plan_out: Dict[str, Any], validation: Dict[str, Any]) -> List[Dict[str, Any]]:
    previous = plan_out.get("raw_response")
    if not previous:
        previous = json.dumps(
            {"reasoning": plan_out.get("reasoning", ""), "steps": plan_out.get("steps", [])},
            ensure_ascii=False,
        )
    error_text = "\n".join(f"- {err}" for err in validation.get("errors", []))
    return [
        {"role": "assistant", "content": previous},
        {
            "role": "user",
            "content": (
                "The previous plan is invalid and must not be executed.\n"
                f"{error_text}\n\n"
                "Re-emit the complete plan as one JSON object. Every step must use a known tool "
                "and include all required params. If you use place_label_and_move, include "
                "tool_name, label, direction, and amount. For the source-target task, a valid "
                "pattern is either setup_source_target_connected({}) or "
                "place_label_and_move(Source, direction='w', amount=220), "
                "place_label_and_move(Target, direction='e', amount=220), then connect_shapes. "
                "For three or more rectangles, every place_label_and_move step must use a "
                "distinct direction/amount offset; do not place all shapes at e 220. Do not "
                "use place_and_label multiple times or place_and_label followed by move_shape."
            ),
        },
    ]


def run_ablation(args: argparse.Namespace) -> Dict[str, Any]:
    if args.clear_only:
        graph = config.ui_graph()
        graph["scene_graph"] = sg.load()
        _clear_canvas(graph, args.countdown)
        print("clear_only: done")
        return {"status": "ok", "clear_only": True}
    if args.agent == "planner":
        return run_planner_ablation(args)
    return run_executor_ablation(args)


def run_executor_ablation(args: argparse.Namespace) -> Dict[str, Any]:
    task_def = TASKS[args.task_id]
    condition = args.condition
    use_screenshot_input = condition == "screenshot_sg"
    max_steps = args.max_steps or config.llm_max_steps()
    cooldown = 0.0 if args.dry_run else config.step_cooldown()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    graph = config.ui_graph()
    graph["scene_graph"] = sg.load()

    if args.clear_canvas:
        _clear_canvas(graph, args.countdown)
    elif args.reset_scene_graph:
        graph["scene_graph"] = sg.reset()

    started_at = _now_utc()
    total_start = time.perf_counter()
    history: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    screenshot_input_count = 0
    llm_wall_s = 0.0
    tool_wall_s = 0.0
    terminated_by_task_complete = False
    max_steps_reached = False

    if not args.dry_run and not args.clear_canvas:
        _countdown(args.countdown, "Focus draw.io now; starting run in:")

    print(f"Task: {args.task_id}")
    print(f"Condition: {condition}")

    for step in range(1, max_steps + 1):
        step_record: Dict[str, Any] = {
            "step": step,
            "used_screenshot_input": use_screenshot_input,
        }
        image_path = None
        if use_screenshot_input:
            image_name = f"ablation_{args.task_id}_{condition}_rep{args.rep:02d}_step{step:02d}.png"
            try:
                image_path = screenshot(image_name)
            except Exception as exc:  # live capture depends on browser/display state
                step_record["result"] = {
                    "status": "error",
                    "phase": "screenshot_capture",
                    "error": str(exc),
                }
                step_record["result_status"] = "error"
                trace.append(step_record)
                break
            screenshot_input_count += 1
            step_record["screenshot_input"] = image_path

        llm_start = time.perf_counter()
        try:
            decision = infer(task_def["task"], graph, image_path, history or None)
        except Exception as exc:
            step_llm_s = time.perf_counter() - llm_start
            llm_wall_s += step_llm_s
            step_record.update({
                "llm_wall_s": step_llm_s,
                "result": {"status": "error", "phase": "llm", "error": str(exc)},
                "result_status": "error",
            })
            trace.append(step_record)
            break
        step_llm_s = time.perf_counter() - llm_start
        llm_wall_s += step_llm_s

        tool_name = decision.get("tool", "")
        params = decision.get("params", {}) or {}
        step_record.update({
            "tool": tool_name,
            "params": params,
            "reasoning": decision.get("reasoning", ""),
            "llm_wall_s": step_llm_s,
        })

        history.append({"role": "assistant", "content": json.dumps(decision)})

        if tool_name == "request_rescan":
            step_record["result"] = {"status": "skipped", "reason": "request_rescan"}
            step_record["result_status"] = "skipped"
            trace.append(step_record)
            continue

        if tool_name == "task_complete":
            terminated_by_task_complete = True
            step_record["result"] = {"status": "ok", "tool": "task_complete"}
            step_record["result_status"] = "ok"
            step_record["tool_wall_s"] = 0.0
            trace.append(step_record)
            break

        tool_start = time.perf_counter()
        if args.dry_run:
            result = {"status": "dry_run", "tool": tool_name}
        else:
            try:
                result = dispatch(tool_name, params, ui_graph=graph)
            except Exception as exc:
                result = {
                    "status": "error",
                    "phase": "dispatch",
                    "tool": tool_name,
                    "error": str(exc),
                }
        step_tool_s = time.perf_counter() - tool_start
        tool_wall_s += step_tool_s

        step_record["result"] = result
        step_record["result_status"] = result.get("status")
        step_record["tool_wall_s"] = step_tool_s
        trace.append(step_record)

        history.append({
            "role": "user",
            "content": f"Tool '{tool_name}' executed. Continue or signal 'task_complete'.",
        })

        if result.get("status") == "error":
            break
        if cooldown:
            time.sleep(cooldown)
    else:
        max_steps_reached = True

    final_graph = graph.get("scene_graph") or sg.load()
    checks = _final_checks(final_graph, task_def["labels"], task_def["edges"])
    success = bool(checks["labels_ok"] and checks["edges_ok"] and checks["no_obvious_overlap"])
    failure = _failure_type(
        terminated_by_task_complete=terminated_by_task_complete,
        final_checks=checks,
        trace=trace,
        max_steps_reached=max_steps_reached,
    )

    final_screenshot = None
    final_screenshot_error = None
    if not args.skip_final_screenshot and not args.dry_run:
        final_name = f"ablation_{args.task_id}_{condition}_rep{args.rep:02d}_final.png"
        try:
            final_screenshot = screenshot(final_name)
        except Exception as exc:
            final_screenshot_error = str(exc)

    ended_at = _now_utc()
    total_wall_s = time.perf_counter() - total_start
    model_cfg = config.executor_model_config()

    record: Dict[str, Any] = {
        "task_id": args.task_id,
        "task": task_def["task"],
        "condition": condition,
        "rep": args.rep,
        "branch": _git_value("branch", "--show-current"),
        "commit": _git_value("rev-parse", "HEAD"),
        "model": {
            "executor": model_cfg.model,
            "provider": model_cfg.provider,
            "temperature": model_cfg.temperature,
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "total_wall_s": total_wall_s,
        "success": success,
        "failure_type": failure,
        "terminated_by_task_complete": terminated_by_task_complete,
        "max_steps_reached": max_steps_reached,
        "turns": len(trace),
        "llm_wall_s": llm_wall_s,
        "tool_wall_s": tool_wall_s,
        "screenshot_input_count": screenshot_input_count,
        "final_screenshot": final_screenshot,
        "final_screenshot_error": final_screenshot_error,
        "final_scene_graph": final_graph,
        "final_summary": sg.summary_for_prompt(final_graph),
        "trace": trace,
        "final_checks": checks,
        "notes": args.notes,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = (
        f"{stamp}_{_safe_name(args.task_id)}_{_safe_name(condition)}_"
        f"rep{args.rep:02d}.json"
    )
    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, default=str)

    print(f"Wrote {out_path}")
    print(f"success={success} turns={len(trace)} total_wall_s={total_wall_s:.2f}")
    return record


def run_planner_ablation(args: argparse.Namespace) -> Dict[str, Any]:
    task_def = TASKS[args.task_id]
    condition = args.condition
    use_screenshot_input = condition == "screenshot_sg"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    graph = config.ui_graph()
    graph["scene_graph"] = sg.load()

    if args.clear_canvas:
        _clear_canvas(graph, args.countdown)
    elif args.reset_scene_graph:
        graph["scene_graph"] = sg.reset()

    started_at = _now_utc()
    total_start = time.perf_counter()
    screenshot_input_count = 0
    llm_wall_s = 0.0
    tool_wall_s = 0.0
    trace: List[Dict[str, Any]] = []
    plan_out: Dict[str, Any] = {"reasoning": "", "steps": []}
    plan_error = None
    run_error = None
    validation: Dict[str, Any] = {"valid": False, "errors": ["Planner was not called."]}
    validation_attempts: List[Dict[str, Any]] = []
    retry_used = False
    screenshot_input = None

    print(f"Task: {args.task_id}")
    print(f"Condition: {condition}")
    print("Agent: planner")

    if use_screenshot_input:
        try:
            screenshot_input = screenshot(
                f"ablation_{args.task_id}_{condition}_rep{args.rep:02d}_planner_input.png"
            )
            screenshot_input_count = 1
        except Exception as exc:
            plan_error = {"status": "error", "phase": "screenshot_capture", "error": str(exc)}

    if plan_error is None:
        llm_start = time.perf_counter()
        try:
            plan_out = plan(task_def["task"], graph, screenshot_path=screenshot_input)
        except Exception as exc:
            plan_error = {"status": "error", "phase": "llm", "error": str(exc)}
        llm_wall_s = time.perf_counter() - llm_start

    if plan_error is None:
        validation = _validate_plan_steps(plan_out.get("steps", []))
        validation_attempts.append({
            "attempt": 1,
            "valid": validation["valid"],
            "errors": validation["errors"],
            "steps": plan_out.get("steps", []),
        })

    if plan_error is None and not validation["valid"]:
        retry_used = True
        retry_history = _validation_retry_history(plan_out, validation)
        llm_start = time.perf_counter()
        try:
            plan_out = plan(
                task_def["task"],
                graph,
                screenshot_path=screenshot_input,
                history=retry_history,
            )
        except Exception as exc:
            plan_error = {"status": "error", "phase": "llm_retry", "error": str(exc)}
        llm_wall_s += time.perf_counter() - llm_start
        if plan_error is None:
            validation = _validate_plan_steps(plan_out.get("steps", []))
            validation_attempts.append({
                "attempt": 2,
                "valid": validation["valid"],
                "errors": validation["errors"],
                "steps": plan_out.get("steps", []),
            })

    invalid_plan_error = None
    if plan_error is None and not validation["valid"]:
        invalid_plan_error = {
            "status": "error",
            "phase": "plan_validation",
            "error": "Planner produced an invalid plan after validation retry.",
            "errors": validation["errors"],
        }

    if plan_error is None and invalid_plan_error is None and not args.plan_only:
        if not args.dry_run and not args.clear_canvas:
            _countdown(args.countdown, "Focus draw.io now; running plan in:")
        tool_start = time.perf_counter()
        try:
            trace = run_plan(
                plan_out.get("steps", []),
                graph,
                dry_run=args.dry_run,
                step_cooldown=0.0 if args.dry_run else None,
            )
        except Exception as exc:
            run_error = {"status": "error", "phase": "run_plan", "error": str(exc)}
        tool_wall_s = time.perf_counter() - tool_start

    final_graph = graph.get("scene_graph") or sg.load()
    checks = _final_checks(final_graph, task_def["labels"], task_def["edges"])
    success = bool(
        not args.plan_only
        and plan_error is None
        and invalid_plan_error is None
        and run_error is None
        and checks["labels_ok"]
        and checks["edges_ok"]
        and checks["no_obvious_overlap"]
    )

    trace_for_failure: List[Dict[str, Any]] = list(trace)
    if plan_error is not None:
        trace_for_failure.append({"result": plan_error})
    if invalid_plan_error is not None:
        trace_for_failure.append({"result": invalid_plan_error})
    if run_error is not None:
        trace_for_failure.append({"result": run_error})
    failure = None if success else _failure_type(
        terminated_by_task_complete=True,
        final_checks=checks,
        trace=trace_for_failure,
        max_steps_reached=False,
    )
    if args.plan_only and failure is None:
        failure = "plan_only"
    if invalid_plan_error is not None:
        failure = "model_invalid_plan"

    final_screenshot = None
    final_screenshot_error = None
    if not args.skip_final_screenshot and not args.dry_run and not args.plan_only:
        final_name = f"ablation_{args.task_id}_{condition}_rep{args.rep:02d}_final.png"
        try:
            final_screenshot = screenshot(final_name)
        except Exception as exc:
            final_screenshot_error = str(exc)

    ended_at = _now_utc()
    total_wall_s = time.perf_counter() - total_start
    model_cfg = config.planner_model_config()
    steps = plan_out.get("steps", [])

    record: Dict[str, Any] = {
        "agent": "planner",
        "task_id": args.task_id,
        "task": task_def["task"],
        "condition": condition,
        "rep": args.rep,
        "branch": _git_value("branch", "--show-current"),
        "commit": _git_value("rev-parse", "HEAD"),
        "model": {
            "planner": model_cfg.model,
            "provider": model_cfg.provider,
            "temperature": model_cfg.temperature,
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "total_wall_s": total_wall_s,
        "success": success,
        "failure_type": failure,
        "plan_only": args.plan_only,
        "turns": len(steps),
        "llm_turns": 0 if plan_error and not retry_used else 2 if retry_used else 1,
        "llm_wall_s": llm_wall_s,
        "tool_wall_s": tool_wall_s,
        "screenshot_input_count": screenshot_input_count,
        "screenshot_input": screenshot_input,
        "final_screenshot": final_screenshot,
        "final_screenshot_error": final_screenshot_error,
        "plan": plan_out,
        "plan_error": plan_error,
        "plan_validation": validation,
        "plan_validation_attempts": validation_attempts,
        "plan_retry_used": retry_used,
        "invalid_plan_error": invalid_plan_error,
        "run_error": run_error,
        "final_scene_graph": final_graph,
        "final_summary": sg.summary_for_prompt(final_graph),
        "trace": trace,
        "final_checks": checks,
        "notes": args.notes,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = (
        f"{stamp}_planner_{_safe_name(args.task_id)}_{_safe_name(condition)}_"
        f"rep{args.rep:02d}.json"
    )
    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, default=str)

    print(f"reasoning: {plan_out.get('reasoning', '')}")
    print(f"plan ({len(steps)} steps):")
    for i, step in enumerate(steps, 1):
        print(f"  {i:>2}. {step.get('tool')}({json.dumps(step.get('params', {}))})")
    if validation_attempts:
        status = "valid" if validation.get("valid") else "INVALID"
        print(f"plan_validation: {status}")
        for err in validation.get("errors", []):
            print(f"  - {err}")
        if retry_used:
            print("plan_retry_used: true")
    print(f"Wrote {out_path}")
    print(f"success={success} steps={len(steps)} total_wall_s={total_wall_s:.2f}")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["planner", "executor"], default="planner",
                        help="Planner mode matches the successful Studio/orchestrator demo.")
    parser.add_argument("--task-id", choices=sorted(TASKS), required=True)
    parser.add_argument("--condition", choices=["sg_only", "screenshot_sg"], required=True)
    parser.add_argument("--rep", type=int, required=True)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--out", default=os.path.join("logs", "ablation"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Ask the model but do not dispatch tools.")
    parser.add_argument("--plan-only", action="store_true",
                        help="Planner mode only: save/print the plan without running it.")
    parser.add_argument("--clear-canvas", action="store_true",
                        help="Select all and delete live draw.io content before the run.")
    parser.add_argument("--clear-only", action="store_true",
                        help="Clear the live draw.io canvas and scene graph, then exit.")
    parser.add_argument("--no-reset-scene-graph", dest="reset_scene_graph",
                        action="store_false",
                        help="Keep the existing scene graph when not clearing the canvas.")
    parser.set_defaults(reset_scene_graph=True)
    parser.add_argument("--countdown", type=int, default=config.countdown_seconds())
    parser.add_argument("--skip-final-screenshot", action="store_true")
    parser.add_argument("--notes", default="")
    return parser.parse_args()


def main() -> None:
    run_ablation(parse_args())


if __name__ == "__main__":
    main()
