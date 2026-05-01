#!/usr/bin/env python3
"""
Integration Demo — Uses exploration-detected icons with the ToolNode tree.

Demonstrates:
    1. Load icons auto-detected by exploration (icons.json)
    2. Use L0 leaf tools step-by-step
    3. Use compound tools (auto-leveled from children) for single-call ops
    4. Print the full tool tree

Usage:
    python operation/demo_integration.py                   # compound demo
    python operation/demo_integration.py --mode leaf       # leaf step-by-step
    python operation/demo_integration.py --mode compound   # compound
    python operation/demo_integration.py --mode both       # both
    python operation/demo_integration.py --dry-run         # print plan only
    python operation/demo_integration.py --tree            # show tool tree
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import config
from shared.capture import screenshot
from operation.tools import (
    TOOL_CATALOG, print_tree, dispatch,
    place_shape, type_label, press_escape, click_empty_canvas,
    place_and_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _countdown(seconds: int | None = None) -> None:
    secs = seconds or config.countdown_seconds()
    for i in range(secs, 0, -1):
        print(f"  {i}s …  (move mouse to corner to ABORT)")
        time.sleep(1)
    print("  GO!\n")


# ---------------------------------------------------------------------------
# Demo sequences
# ---------------------------------------------------------------------------

def demo_leaf(ui: Dict[str, Any], dry_run: bool = False) -> List[dict]:
    """
    L0 leaf tools: step-by-step place + label.
    This is what the LLM does at runtime — one tool per turn.
    """
    print("\n" + "=" * 55)
    print("  DEMO — Leaf tools (step-by-step)")
    print("=" * 55)

    steps: List[dict] = []

    def do(desc: str, fn, *args, **kwargs):
        print(f"\n── {desc}")
        if dry_run:
            print(f"   [DRY RUN] {fn.__name__}({args}, {kwargs})")
            steps.append({"action": desc, "status": "dry_run"})
        else:
            r = fn(*args, **kwargs)
            steps.append({**r, "action": desc})
            time.sleep(0.5)

    do("Place Rectangle_Tool", place_shape, ui, "Rectangle_Tool")
    do("Type 'Cache'", type_label, "Cache")
    do("Escape", press_escape)
    do("Deselect", click_empty_canvas)

    return steps


def demo_compound(ui: Dict[str, Any], dry_run: bool = False) -> List[dict]:
    """
    Compound tool: single call does place + label + escape + deselect.
    """
    print("\n" + "=" * 55)
    print("  DEMO — Compound tool (single call)")
    print("=" * 55)

    if dry_run:
        node = TOOL_CATALOG["place_and_label"]
        print(f"\n   [DRY RUN] place_and_label('Diamond_Tool', 'Router')")
        print(f"   Level: {node.level}  Children: {[c.name for c in node.children]}")
        return [{"action": "place_and_label", "status": "dry_run"}]

    result = place_and_label(ui, "Diamond_Tool", "Router")
    return [result]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Integration demo: exploration → operation")
    p.add_argument("--mode", choices=["leaf", "compound", "both"], default="compound")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tree", action="store_true", help="Print the tool tree and exit")
    args = p.parse_args()

    # ── Tool tree ─────────────────────────────────────────────────────
    if args.tree:
        print_tree()
        ui = config.ui_graph()
        elements = list(ui["UI_Elements"].keys())
        print(f"\n  Shapes from icons.json: {len(elements)}")
        for e in elements:
            print(f"    - {e}")
        print()
        return

    # ── Validate icons ────────────────────────────────────────────────
    ui = config.ui_graph()
    elements = list(ui["UI_Elements"].keys())
    print(f"  Loaded {len(elements)} shapes from icons.json")

    needed = {"Rectangle_Tool", "Diamond_Tool"}
    missing = needed - set(elements)
    if missing:
        print(f"\n  ❌ Missing required shapes: {missing}")
        print(f"     Run: python exploration/test_collect_icons.py --detect --label --write")
        sys.exit(1)

    # ── Run ───────────────────────────────────────────────────────────
    if not args.dry_run:
        print("\n  Switch to draw.io NOW.\n")
        _countdown()
        screenshot("demo_before.png")

    results: List[dict] = []

    if args.mode in ("leaf", "both"):
        results.extend(demo_leaf(ui, args.dry_run))

    if args.mode == "both" and not args.dry_run:
        time.sleep(1)

    if args.mode in ("compound", "both"):
        results.extend(demo_compound(ui, args.dry_run))

    if not args.dry_run:
        time.sleep(0.5)
        screenshot("demo_after.png")

    # ── Summary ───────────────────────────────────────────────────────
    print(f"\n{'=' * 55}")
    print(f"  RESULTS — {len(results)} action(s)")
    for r in results:
        status = r.get("status", "?")
        tool = r.get("tool", r.get("action", "?"))
        icon = "✅" if status == "ok" else "🔶" if status in ("dry_run", "partial") else "❌"
        sub = f"  ({len(r['steps'])} sub-steps)" if "steps" in r else ""
        print(f"  {icon}  {tool}{sub}")
    print(f"{'=' * 55}\n")


if __name__ == "__main__":
    main()
