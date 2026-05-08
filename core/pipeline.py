"""
Pipeline — Agentic control loop.

    Capture → Executor decides → Tool dispatches → (repeat)
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from core import config
from core.capture import screenshot
from core.agents.executor import infer
from core.tools import dispatch


def run(
    task: str,
    *,
    ui_graph: Dict[str, Any] | None = None,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    """Execute the perceive → reason → act loop."""
    max_steps = config.llm_max_steps()
    cooldown = config.step_cooldown()
    graph = ui_graph or config.ui_graph()

    print("=" * 60)
    print(f"  PIPELINE — {task}")
    print("=" * 60)

    log: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []

    for step in range(1, max_steps + 1):
        print(f"\n{'─' * 50}  Step {step}/{max_steps}")

        img_path = screenshot(f"step_{step:02d}.png")
        decision = infer(task, graph, img_path, history or None)
        tool_name = decision.get("tool", "")
        params = decision.get("params", {})

        history.append({"role": "assistant", "content": json.dumps(decision)})

        if tool_name == "request_rescan":
            print("[PIPELINE] Rescan requested")
            continue
        if tool_name == "task_complete":
            print("[PIPELINE] Task complete ✓")
            log.append(decision)
            break

        if dry_run:
            print(f"[PIPELINE] DRY RUN: {tool_name}({params})")
            result = {"status": "dry_run"}
        else:
            result = dispatch(tool_name, params, ui_graph=graph)

        log.append({**decision, "result": result, "step": step})
        history.append({
            "role": "user",
            "content": f"Tool '{tool_name}' executed. Continue or signal 'task_complete'.",
        })
        time.sleep(cooldown)
    else:
        print(f"\n[PIPELINE] Max steps ({max_steps}) reached.")

    print("\n" + "=" * 60)
    for e in log:
        print(f"  Step {e.get('step', '?'):>2}: {e.get('tool')}  {e.get('params', {})}")
    print("=" * 60)
    return log
