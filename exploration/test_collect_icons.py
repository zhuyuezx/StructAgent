#!/usr/bin/env python3
"""
Test icon collection — verify the explorer pipeline can detect sidebar icons.

Usage:
    python exploration/test_collect_icons.py --detect
    python exploration/test_collect_icons.py --detect --label
    python exploration/test_collect_icons.py --detect --label --write
    python exploration/test_collect_icons.py --detect --image screenshots/explore.png
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import config
from shared.capture import screenshot
from exploration.explorer import detect_icons, annotate, label_icons, write_icons


def _countdown(seconds: int | None = None) -> None:
    secs = seconds or config.countdown_seconds()
    for i in range(secs, 0, -1):
        print(f"  {i}s …")
        time.sleep(1)
    print("  GO!\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Test draw.io icon detection")
    p.add_argument("--detect", action="store_true", help="Run icon detection.")
    p.add_argument("--label", action="store_true", help="Label icons with LLM.")
    p.add_argument("--write", action="store_true", help="Write results to icons.json.")
    p.add_argument("--image", type=str, default=None,
                   help="Use existing screenshot instead of capturing.")
    args = p.parse_args()

    if not args.detect:
        p.print_help()
        return

    # 1. Get screenshot
    if args.image:
        img_path = args.image
        print(f"Using existing screenshot: {img_path}")
    else:
        print("  Switch to draw.io NOW.\n")
        _countdown()
        img_path = screenshot("explore.png")

    # 2. Detect icons
    print(f"\n[DETECT] Sidebar region (physical px): {config.sidebar_region()}")
    print(f"[DETECT] Screen scale: {config.screen_scale()}x")
    print(f"[DETECT] Icon size range: {config.icon_size_range()}")

    icons = detect_icons(img_path)
    print(f"\n✅ Detected {len(icons)} icons\n")

    for i, ic in enumerate(icons):
        print(f"  #{i:<3} logical=({ic['x']:>4}, {ic['y']:>4})  "
              f"size={ic['w']}×{ic['h']}")

    # 3. Save annotated screenshot
    out_dir = config.test_output_dir()
    ann_path = os.path.join(out_dir, "detected_icons.png")
    annotate(img_path, icons, ann_path)

    # 4. Label with LLM (optional)
    if args.label:
        print(f"\n[LABEL] Labeling {len(icons)} icons with {config.explorer_model()} …\n")
        icons = label_icons(img_path, icons)
        ann_labeled = os.path.join(out_dir, "labeled_icons.png")
        annotate(img_path, icons, ann_labeled)

    # 5. Write to icons.json (optional)
    if args.write:
        if not args.label:
            print("\n⚠️  --write requires --label (icons need labels first)")
            return
        print()
        write_icons(icons)
        print(f"   Verify: cat exploration/icons.json | python3 -m json.tool")

    # Summary
    print(f"\n{'=' * 50}")
    print(f"  {len(icons)} icons detected")
    if args.label:
        labels = [ic.get("label", "?") for ic in icons]
        print(f"  Labels: {labels}")
    print(f"  Annotated screenshot: {ann_path}")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
