#!/usr/bin/env python3
"""
Manual Feasibility Test — No LLM, hardcoded action sequences.

Usage:
    python tests/test_manual.py --calibrate
    python tests/test_manual.py --run single --label "Cache"
    python tests/test_manual.py --run double
    python tests/test_manual.py --run single --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config
from core.capture import screenshot
from core.tools import place_shape, type_label, press_escape, click_empty_canvas


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
# Calibration
# ---------------------------------------------------------------------------

def run_calibrate() -> None:
    print("=" * 50 + "\n  CALIBRATION\n" + "=" * 50)
    print("\n  Switch to draw.io.\n")
    _countdown(3)

    path = screenshot("calibration.png")
    print(f"\n✅ Screenshot → {path}")
    print(f"   Run perception pipeline to auto-detect icons.\n")


# ---------------------------------------------------------------------------
# Step runner
# ---------------------------------------------------------------------------

class Steps:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.n = 0
        self.results: List[dict] = []

    def do(self, desc: str, fn, *args, **kwargs) -> None:
        self.n += 1
        print(f"\n── Step {self.n}: {desc}")
        if self.dry_run:
            print(f"   [DRY RUN] {fn.__name__}({args}, {kwargs})")
            self.results.append({"step": self.n, "action": desc, "status": "dry_run"})
        else:
            r = fn(*args, **kwargs)
            self.results.append({"step": self.n, "action": desc, **(r or {})})
            time.sleep(0.8)

    def summary(self) -> None:
        print("\n" + "=" * 50)
        for r in self.results:
            s = r.get("status", "ok")
            e = "✅" if s == "ok" else "🔶"
            print(f"  {e}  Step {r['step']}: {r['action']}")
        print("=" * 50)


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

def seq_single(ui: Dict, label: str = "Cache", dry_run: bool = False) -> List[dict]:
    """Place one rectangle and label it."""
    s = Steps(dry_run)
    s.do("Place rectangle", place_shape, ui, "Rectangle_Tool")
    s.do(f"Type '{label}'", type_label, label)
    s.do("Escape", press_escape)
    s.do("Deselect", click_empty_canvas)
    s.summary()
    return s.results


def seq_double(ui: Dict, dry_run: bool = False) -> List[dict]:
    """Place two rectangles."""
    s = Steps(dry_run)

    s.do("Place rect #1", place_shape, ui, "Rectangle_Tool")
    s.do("Type 'Service A'", type_label, "Service A")
    s.do("Escape", press_escape)
    s.do("Deselect", click_empty_canvas)

    time.sleep(0.5)

    s.do("Place rect #2", place_shape, ui, "Rectangle_Tool")
    s.do("Type 'Service B'", type_label, "Service B")
    s.do("Escape", press_escape)
    s.do("Deselect", click_empty_canvas)

    s.summary()
    return s.results


# ---------------------------------------------------------------------------
# Runner with before/after screenshots
# ---------------------------------------------------------------------------

def run_with_screenshots(name: str, seq_fn, ui: Dict, dry_run: bool = False) -> None:
    out = config.test_output_dir()
    before = screenshot(f"{name}_before.png")
    import shutil
    dest_before = os.path.join(out, f"{name}_before.png")
    shutil.copy2(before, dest_before)
    print(f"📸 Before → {dest_before}")

    seq_fn(ui, dry_run=dry_run)
    time.sleep(0.5)

    after = screenshot(f"{name}_after.png")
    dest_after = os.path.join(out, f"{name}_after.png")
    shutil.copy2(after, dest_after)
    print(f"📸 After  → {dest_after}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Manual draw.io test")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--calibrate", action="store_true")
    g.add_argument("--run", choices=["single", "double"], nargs="?", const="single")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--label", default="Cache")
    args = p.parse_args()

    if args.calibrate:
        run_calibrate()
        return

    ui = config.ui_graph()
    print("=" * 50)
    print(f"  TEST — {args.run}")
    print("=" * 50)
    print("\n  Switch to draw.io NOW.\n")
    _countdown()

    if args.run == "single":
        run_with_screenshots(
            "single", lambda u, dry_run: seq_single(u, args.label, dry_run),
            ui, args.dry_run,
        )
    elif args.run == "double":
        run_with_screenshots("double", seq_double, ui, args.dry_run)


if __name__ == "__main__":
    main()
