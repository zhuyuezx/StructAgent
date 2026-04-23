#!/usr/bin/env python3
"""
draw.io Hybrid Agent — Entry Point.

Usage:
    python main.py --task "Add a Cache rectangle"
    python main.py --task "Add a Cache rectangle" --dry-run
    python main.py --screenshot
"""

import argparse
import json

from pipeline import config, screenshot
from pipeline.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description="draw.io Hybrid Agent")
    parser.add_argument("--task", "-t", type=str,
                        default="Draw a rectangle labelled 'Cache'")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--screenshot", action="store_true",
                        help="Capture a screenshot and exit.")
    args = parser.parse_args()

    if args.screenshot:
        path = screenshot("manual_capture.png")
        graph = config.ui_graph()
        print(json.dumps(graph, indent=2))
        return

    log = run(args.task, dry_run=args.dry_run)
    print(f"\nDone — {len(log)} action(s).")


if __name__ == "__main__":
    main()
