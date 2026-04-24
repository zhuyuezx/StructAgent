#!/usr/bin/env python3
"""
LLM Integration Test — Verify the LLM can pick correct tools.

Levels:
    1. single-step  — "Place a rectangle"  (just place_shape)
    2. two-step     — "Place a rectangle labelled Cache"  (place_shape + type_label)
    3. multi-step   — Full sequence with escape + deselect
    4. multi-shape  — Place multiple shapes

Usage:
    # Level 1 — simplest possible, just checks LLM returns a valid tool
    python test_drawio_auto.py --level 1

    # Level 2 — place + label
    python test_drawio_auto.py --level 2

    # Level 3 — full sequence
    python test_drawio_auto.py --level 3

    # Dry-run any level (LLM decides but no execution)
    python test_drawio_auto.py --level 1 --dry-run

    # Prompt-only (just print the prompt, no LLM call)
    python test_drawio_auto.py --prompt-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import config
from pipeline.capture import screenshot
from pipeline.llm import infer, build_prompt
from pipeline.tools import dispatch, TOOL_CATALOG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _countdown(seconds: int | None = None) -> None:
    secs = seconds or config.countdown_seconds()
    for i in range(secs, 0, -1):
        print(f"  {i}s …")
        time.sleep(1)
    print("  GO!\n")


def _validate_decision(decision: dict) -> dict:
    """Validate that the LLM's decision references a known tool."""
    tool = decision.get("tool", "")
    params = decision.get("params", {})
    reasoning = decision.get("reasoning", "")

    is_special = tool in ("request_rescan", "task_complete")
    is_known = tool in TOOL_CATALOG

    return {
        "tool": tool,
        "params": params,
        "reasoning": reasoning,
        "valid": is_known or is_special,
        "is_special": is_special,
    }


# ---------------------------------------------------------------------------
# Single-step LLM call
# ---------------------------------------------------------------------------

def llm_step(
    task: str,
    ui_graph: Dict[str, Any],
    img_path: str,
    history: list | None = None,
    step_num: int = 1,
    dry_run: bool = False,
) -> dict:
    """
    One perceive → reason → (optionally execute) cycle.

    Returns the validated decision dict with an added 'executed' key.
    """
    print(f"\n{'━' * 55}")
    print(f"  LLM Step {step_num}")
    print(f"{'━' * 55}")

    # Ask the LLM
    decision = infer(task, ui_graph, img_path, history)
    info = _validate_decision(decision)

    print(f"\n  📋 Reasoning: {info['reasoning']}")
    print(f"  🔧 Tool:      {info['tool']}")
    print(f"  📦 Params:    {info['params']}")
    print(f"  ✅ Valid:      {info['valid']}")

    if not info["valid"]:
        print(f"  ❌ INVALID TOOL — '{info['tool']}' not in catalog!")
        info["executed"] = False
        return info

    if info["is_special"]:
        print(f"  ⚡ Special signal: {info['tool']}")
        info["executed"] = False
        return info

    # Execute
    if dry_run:
        print(f"  🔶 DRY RUN — would execute: {info['tool']}({info['params']})")
        info["executed"] = False
    else:
        print(f"  ▶ Executing: {info['tool']}({info['params']})")
        result = dispatch(info["tool"], info["params"], ui_graph=ui_graph)
        info["result"] = result
        info["executed"] = True
        time.sleep(0.8)  # let draw.io catch up

    return info


# ---------------------------------------------------------------------------
# Level 1: Single-step — "Place a rectangle"
# ---------------------------------------------------------------------------

LEVEL_1_TASK = "Place a rectangle on the canvas."

def run_level_1(ui_graph: Dict, dry_run: bool = False) -> bool:
    """
    Simplest test: give the LLM a trivial task and verify it picks
    `place_shape` with `tool_name: Rectangle_Tool`.
    """
    print("\n" + "=" * 55)
    print("  LEVEL 1 — Single-step: Place a rectangle")
    print("=" * 55)

    img = screenshot("auto_level1.png")
    info = llm_step(LEVEL_1_TASK, ui_graph, img, step_num=1, dry_run=dry_run)

    ok = info["valid"] and info["tool"] == "place_shape"
    _print_verdict("Level 1", ok, info)
    return ok


# ---------------------------------------------------------------------------
# Level 2: Two-step — "Place a rectangle labelled 'Cache'"
# ---------------------------------------------------------------------------

LEVEL_2_TASK = "Place a rectangle and label it 'Cache'. Do one step at a time."

def run_level_2(ui_graph: Dict, dry_run: bool = False) -> bool:
    """
    Two-step: LLM should first pick place_shape, then type_label.
    We feed the result of step 1 back as history for step 2.
    """
    print("\n" + "=" * 55)
    print("  LEVEL 2 — Two-step: Place + label")
    print("=" * 55)

    history: List[Dict[str, Any]] = []
    results: List[dict] = []

    for step in range(1, 3):
        img = screenshot(f"auto_level2_step{step}.png")

        info = llm_step(
            LEVEL_2_TASK, ui_graph, img,
            history=history if history else None,
            step_num=step, dry_run=dry_run,
        )
        results.append(info)

        # Build history for next turn
        history.append({"role": "assistant", "content": json.dumps({
            "tool": info["tool"], "params": info["params"],
            "reasoning": info["reasoning"],
        })})
        if info["executed"] or dry_run:
            history.append({"role": "user", "content":
                f"Tool '{info['tool']}' executed. What's the next step? "
                f"If done, use 'task_complete'."
            })

        if info["is_special"] and info["tool"] == "task_complete":
            break

    # Validate: step 1 should be place_shape, step 2 should be type_label
    ok = (
        len(results) >= 2
        and results[0]["tool"] == "place_shape"
        and results[1]["tool"] == "type_label"
    )
    _print_verdict("Level 2", ok, results)
    return ok


# ---------------------------------------------------------------------------
# Level 3: Multi-step — Full workflow
# ---------------------------------------------------------------------------

LEVEL_3_TASK = (
    "Place a rectangle labelled 'Database', then press Escape to exit "
    "text editing, then click empty canvas to deselect. Do one step at a time."
)

def run_level_3(ui_graph: Dict, dry_run: bool = False) -> bool:
    """
    Multi-step: place → type → escape → deselect → task_complete.
    """
    print("\n" + "=" * 55)
    print("  LEVEL 3 — Multi-step: Full workflow")
    print("=" * 55)

    history: List[Dict[str, Any]] = []
    results: List[dict] = []
    max_turns = 8  # safety cap

    for step in range(1, max_turns + 1):
        img = screenshot(f"auto_level3_step{step}.png")

        info = llm_step(
            LEVEL_3_TASK, ui_graph, img,
            history=history if history else None,
            step_num=step, dry_run=dry_run,
        )
        results.append(info)

        history.append({"role": "assistant", "content": json.dumps({
            "tool": info["tool"], "params": info["params"],
            "reasoning": info["reasoning"],
        })})

        if info["is_special"] and info["tool"] == "task_complete":
            print("\n  🏁 LLM signalled task_complete")
            break

        if info["valid"] and not info["is_special"]:
            history.append({"role": "user", "content":
                f"Tool '{info['tool']}' executed successfully. "
                f"What's the next step? Use 'task_complete' if done."
            })

    # Validate: at minimum place_shape and type_label should appear
    tools_used = [r["tool"] for r in results]
    ok = "place_shape" in tools_used and "type_label" in tools_used
    _print_verdict("Level 3", ok, results)
    return ok


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------

def _print_verdict(level: str, ok: bool, data: Any) -> None:
    print(f"\n{'=' * 55}")
    if ok:
        print(f"  ✅ {level} PASSED")
    else:
        print(f"  ❌ {level} FAILED")
    if isinstance(data, list):
        print(f"  Tools chosen: {[r['tool'] for r in data]}")
    elif isinstance(data, dict):
        print(f"  Tool chosen: {data.get('tool')}")
    print("=" * 55)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="LLM Integration Test for draw.io")
    parser.add_argument("--level", type=int, choices=[1, 2, 3], default=1,
                        help="Test level: 1=single-step, 2=two-step, 3=multi-step")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM decides but tools are not executed.")
    parser.add_argument("--prompt-only", action="store_true",
                        help="Just print the LLM prompt and exit (no inference).")
    args = parser.parse_args()

    ui_graph = config.ui_graph()

    if args.prompt_only:
        print(build_prompt(ui_graph))
        return

    print("  Switch to draw.io NOW.\n")
    _countdown()

    runners = {1: run_level_1, 2: run_level_2, 3: run_level_3}
    ok = runners[args.level](ui_graph, dry_run=args.dry_run)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
