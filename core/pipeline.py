"""
Pipeline — Agentic control loop.

    Capture → Executor decides → Tool dispatches → (repeat)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List

from core import config
from core.capture import screenshot
from core.agents.executor import build_prompt, infer
from core.perception.canvas import (
    annotate_canvas, observe_canvas_detailed, summarize_graph, tool_families,
)
from core.perception.tracker import CanvasTracker
from core.tools import dispatch
from core.verification import verify_action


def run(
    task: str,
    *,
    ui_graph: Dict[str, Any] | None = None,
    dry_run: bool = False,
    trace: bool = False,
) -> List[Dict[str, Any]]:
    """Execute the perceive → reason → act loop."""
    max_steps = config.llm_max_steps()
    cooldown = config.step_cooldown()
    base_graph = ui_graph or config.ui_graph()
    trace_dir = _make_trace_dir() if trace else None

    print("=" * 60)
    print(f"  PIPELINE — {task}")
    if trace_dir:
        print(f"  TRACE   — {trace_dir}")
    print("=" * 60)

    log: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []
    tracker = CanvasTracker()

    for step in range(1, max_steps + 1):
        print(f"\n{'─' * 50}  Step {step}/{max_steps}")

        img_path = screenshot(f"step_{step:02d}.png")
        graph = _runtime_graph(img_path, base_graph, tracker, step)
        graph_before = graph
        canvas_annotation = _write_canvas_annotation(
            trace_dir, step, img_path, graph_before, suffix="canvas",
        )
        decision = infer(task, graph, img_path, history or None)
        tool_name = decision.get("tool", "")
        params = decision.get("params", {})

        history.append({"role": "assistant", "content": json.dumps(decision)})

        if tool_name == "request_rescan":
            print("[PIPELINE] Rescan requested")
            entry = {
                **decision,
                "task": task,
                "step": step,
                "screenshot": img_path,
                "canvas_annotation": canvas_annotation,
                "ui_graph_before": summarize_graph(graph_before),
                "canvas_tracking": graph_before.get("_canvas_tracking", {}),
                "canvas_detection": _detection_trace(graph_before),
                "accepted_candidates": graph_before.get("_canvas_detection", {}).get("accepted_candidates", []),
                "rejected_candidates": graph_before.get("_canvas_detection", {}).get("rejected_candidates", []),
                "tool_families": graph_before.get("Tool_Families", {}),
                "prompt": build_prompt(graph_before),
                "result": {"status": "rescanned"},
                "dispatch_result": {"status": "rescanned"},
            }
            log.append(entry)
            _write_trace(trace_dir, step, entry, history)
            continue
        if tool_name == "task_complete":
            print("[PIPELINE] Task complete ✓")
            entry = {
                **decision,
                "task": task,
                "step": step,
                "screenshot": img_path,
                "canvas_annotation": canvas_annotation,
                "ui_graph_before": summarize_graph(graph_before),
                "canvas_tracking": graph_before.get("_canvas_tracking", {}),
                "canvas_detection": _detection_trace(graph_before),
                "accepted_candidates": graph_before.get("_canvas_detection", {}).get("accepted_candidates", []),
                "rejected_candidates": graph_before.get("_canvas_detection", {}).get("rejected_candidates", []),
                "tool_families": graph_before.get("Tool_Families", {}),
                "prompt": build_prompt(graph_before),
                "dispatch_result": None,
            }
            log.append(entry)
            _write_trace(trace_dir, step, entry, history)
            break

        if dry_run:
            print(f"[PIPELINE] DRY RUN: {tool_name}({params})")
            result = {"status": "dry_run"}
            after_img = img_path
            graph_after = graph_before
            post_canvas_annotation = canvas_annotation
            verification = {
                "passed": True,
                "confidence": "skipped",
                "reason": "dry_run",
                "before_node_count": len(graph_before.get("Canvas_Nodes", [])),
                "after_node_count": len(graph_after.get("Canvas_Nodes", [])),
                "canvas_changed": False,
            }
        else:
            result = dispatch(tool_name, params, ui_graph=graph)
            time.sleep(cooldown)
            after_img = screenshot(f"step_{step:02d}_after.png")
            graph_after = _runtime_graph(after_img, base_graph, tracker, step)
            post_canvas_annotation = _write_canvas_annotation(
                trace_dir, step, after_img, graph_after, suffix="after_canvas",
            )
            verification = verify_action(
                tool_name, params, graph_before, graph_after,
                img_path, after_img, result,
            )

        entry = {
            **decision,
            "task": task,
            "result": result,
            "dispatch_result": result,
            "verification": verification,
            "step": step,
            "screenshot": img_path,
            "post_action_screenshot": after_img,
            "canvas_annotation": canvas_annotation,
            "post_action_canvas_annotation": post_canvas_annotation,
            "ui_graph_before": summarize_graph(graph_before),
            "ui_graph_after": summarize_graph(graph_after),
            "canvas_tracking": {
                "before": graph_before.get("_canvas_tracking", {}),
                "after": graph_after.get("_canvas_tracking", {}),
            },
            "canvas_detection": {
                "before": _detection_trace(graph_before),
                "after": _detection_trace(graph_after),
            },
            "accepted_candidates": {
                "before": graph_before.get("_canvas_detection", {}).get("accepted_candidates", []),
                "after": graph_after.get("_canvas_detection", {}).get("accepted_candidates", []),
            },
            "rejected_candidates": {
                "before": graph_before.get("_canvas_detection", {}).get("rejected_candidates", []),
                "after": graph_after.get("_canvas_detection", {}).get("rejected_candidates", []),
            },
            "tool_families": graph_before.get("Tool_Families", {}),
            "prompt": build_prompt(graph_before),
        }
        log.append(entry)
        history.append({
            "role": "user",
            "content": (
                f"Tool '{tool_name}' executed with status "
                f"'{result.get('status')}'. Verification: "
                f"{verification.get('reason')} "
                f"(passed={verification.get('passed')}, "
                f"observed nodes={verification.get('after_node_count')}). "
                "Continue or signal 'task_complete'."
            ),
        })
        _write_trace(trace_dir, step, entry, history)
        if dry_run:
            time.sleep(cooldown)
    else:
        print(f"\n[PIPELINE] Max steps ({max_steps}) reached.")

    print("\n" + "=" * 60)
    for e in log:
        print(f"  Step {e.get('step', '?'):>2}: {e.get('tool')}  {e.get('params', {})}")
    print("=" * 60)
    return log


def _runtime_graph(
    screenshot_path: str,
    base_graph: Dict[str, Any],
    tracker: CanvasTracker | None = None,
    step: int = 0,
) -> Dict[str, Any]:
    detail = observe_canvas_detailed(screenshot_path)
    nodes = detail.get("nodes", [])
    tracking = {}
    if tracker is not None:
        nodes = tracker.update(nodes, step)
        tracking = tracker.last_diagnostics
    return {
        "UI_Elements": base_graph.get("UI_Elements", {}),
        "Canvas_Nodes": nodes,
        "Canvas_Edges": base_graph.get("Canvas_Edges", []),
        "Tool_Families": tool_families(base_graph.get("UI_Elements", {})),
        "_canvas_detection": detail,
        "_canvas_tracking": tracking,
    }


def _make_trace_dir() -> str:
    root = os.path.join(config.test_output_dir(), "runs")
    os.makedirs(root, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = os.path.join(root, stamp)
    os.makedirs(path, exist_ok=False)
    return path


def _write_trace(
    trace_dir: str | None,
    step: int,
    entry: Dict[str, Any],
    history: List[Dict[str, Any]],
) -> None:
    if not trace_dir:
        return
    path = os.path.join(trace_dir, f"step_{step:02d}.json")
    payload = {
        "task": entry.get("task"),
        "step": step,
        "history": history,
        **entry,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def _write_canvas_annotation(
    trace_dir: str | None,
    step: int,
    screenshot_path: str,
    graph: Dict[str, Any],
    *,
    suffix: str,
) -> str | None:
    if not trace_dir:
        return None
    path = os.path.join(trace_dir, f"step_{step:02d}_{suffix}.png")
    return annotate_canvas(
        screenshot_path,
        graph.get("Canvas_Nodes", []),
        path,
        detection=graph.get("_canvas_detection"),
    )


def _detection_trace(graph: Dict[str, Any]) -> Dict[str, Any]:
    detail = graph.get("_canvas_detection", {})
    return {
        "crop_region": detail.get("crop_region"),
        "theme": detail.get("theme"),
        "polarity": detail.get("polarity"),
        "accepted_count": len(detail.get("accepted_candidates", [])),
        "rejected_count": len(detail.get("rejected_candidates", [])),
    }
