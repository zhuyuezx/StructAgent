"""
test_planner — exercise the Planner + orchestrator (Phase 1).

Offline modes (no LLM, no GUI):
    python tests/test_planner.py --prompt-only      # render the planner prompt
    python tests/test_planner.py --parse-demo       # parse a sample LLM reply
    python tests/test_planner.py --dry-run          # walk a sample plan (no mouse)

Live modes (require ollama + draw.io focused):
    python tests/test_planner.py --live "Place two rectangles Source and Target and connect them"
    python tests/test_planner.py --live "..." --screenshot   # screenshot+SG mode

The live mode plans the whole task in ONE LLM call, then prints the plan and
(after a 5s countdown — switch to draw.io) runs it deterministically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from core.state import scene_graph as sg
from core.tools import TOOL_CATALOG  # noqa: F401  (ensures catalog is loaded)


# A representative model reply — a CCW-ring-ish plan referencing created shapes
# by label. Used by --parse-demo and --dry-run so the harness needs no LLM.
_SAMPLE_REPLY = """\
{
  "reasoning": "Canvas is empty. Place Source, move it out of the drop zone, place Target, then connect Source->Target by label.",
  "steps": [
    {"tool": "place_shape",   "params": {"tool_name": "Rectangle_Tool"}},
    {"tool": "type_label",    "params": {"text": "Source"}},
    {"tool": "press_escape",  "params": {}},
    {"tool": "move_shape",    "params": {"direction": "w", "amount": 180}},
    {"tool": "click_empty_canvas", "params": {}},
    {"tool": "place_shape",   "params": {"tool_name": "Rectangle_Tool"}},
    {"tool": "type_label",    "params": {"text": "Target"}},
    {"tool": "press_escape",  "params": {}},
    {"tool": "connect_shapes","params": {"source_id": "Source",
                                          "target_id": "Target",
                                          "source_anchor": "auto"}}
  ]
}
"""


def _load_graph() -> dict:
    g = config.ui_graph()
    g["scene_graph"] = sg.load()
    g.setdefault("selected_handles", None)
    return g


def cmd_prompt_only(args) -> None:
    from core.agents.planner import build_prompt
    g = _load_graph()
    print(build_prompt(g, use_screenshot=args.screenshot))


def cmd_parse_demo(args) -> None:
    from core.agents.planner import parse_plan_response
    parsed = parse_plan_response(_SAMPLE_REPLY)
    print(f"reasoning: {parsed['reasoning'][:80]}…")
    print(f"steps ({len(parsed['steps'])}):")
    for i, s in enumerate(parsed["steps"], 1):
        print(f"  {i:>2}. {s['tool']}({json.dumps(s['params'])})")
    # Every referenced tool must exist in the catalog.
    unknown = [s["tool"] for s in parsed["steps"] if s["tool"] not in TOOL_CATALOG]
    print(f"\nunknown tools: {unknown or 'none'}")


def cmd_dry_run(args) -> None:
    from core.agents.planner import parse_plan_response
    from core.orchestrator import run_plan, plan_succeeded, trace_to_steps
    steps = parse_plan_response(_SAMPLE_REPLY)["steps"]
    g = _load_graph()
    trace = run_plan(steps, g, dry_run=True)
    for e in trace:
        print(f"  step {e['step']:>2}: {e['tool']:<18} → {e['result']['status']}")
    print(f"\nplan_succeeded: {plan_succeeded(trace)}")
    print(f"saveable steps: {len(trace_to_steps(trace))}")


def cmd_live(args) -> None:
    from core.capture import screenshot
    from core.orchestrator import run_plan, plan_succeeded
    from core.agents.planner import plan
    g = _load_graph()

    shot = None
    if args.screenshot:
        shot = screenshot("_planner_live.png")

    print(f"Planning: {args.live}")
    out = plan(args.live, g, screenshot_path=shot)
    print(f"\nreasoning: {out['reasoning']}")
    print(f"\nplan ({len(out['steps'])} steps):")
    for i, s in enumerate(out["steps"], 1):
        print(f"  {i:>2}. {s['tool']}({json.dumps(s['params'])})")

    if args.plan_only:
        return

    print("\nSwitch to draw.io NOW — running in:")
    for i in range(5, 0, -1):
        print(f"  {i}s …"); time.sleep(1)

    trace = run_plan(out["steps"], g)
    print("\n--- trace ---")
    for e in trace:
        st = e["result"].get("status")
        err = f"  error={e['result'].get('error')}" if st != "ok" else ""
        print(f"  step {e['step']:>2}: {e['tool']:<18} → {st}{err}")
    print(f"\nplan_succeeded: {plan_succeeded(trace)}")
    print("\n--- final scene graph ---")
    print(sg.summary_for_prompt(g["scene_graph"]))


def main() -> None:
    p = argparse.ArgumentParser(description="Planner + orchestrator test harness.")
    p.add_argument("--prompt-only", action="store_true",
                   help="render the planner system prompt and exit")
    p.add_argument("--parse-demo", action="store_true",
                   help="parse a sample LLM reply into a plan")
    p.add_argument("--dry-run", action="store_true",
                   help="walk the sample plan with no mouse movement")
    p.add_argument("--live", metavar="TASK",
                   help="plan + run TASK live (needs ollama + draw.io)")
    p.add_argument("--screenshot", action="store_true",
                   help="screenshot+SG mode (default is text-only)")
    p.add_argument("--plan-only", action="store_true",
                   help="with --live, print the plan but do not execute it")
    args = p.parse_args()

    if args.prompt_only:
        cmd_prompt_only(args)
    elif args.parse_demo:
        cmd_parse_demo(args)
    elif args.dry_run:
        cmd_dry_run(args)
    elif args.live:
        cmd_live(args)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
