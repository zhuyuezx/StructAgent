#!/usr/bin/env python3
"""
Test icon collection — verify the perception pipeline can detect sidebar icons.

Usage:
    python tests/test_collect_icons.py --detect
    python tests/test_collect_icons.py --detect --label
    python tests/test_collect_icons.py --detect --label --write
    python tests/test_collect_icons.py --detect --image screenshots/explore.png
"""

from __future__ import annotations

import argparse
import os
import sys
import time

# Add project root to path so both `core` and `tests` packages resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import countdown  # noqa: E402

from core import config
from core.capture import screenshot
from core.perception.detect import detect_icons, annotate
from core.perception.label import label_icons
from core.state.ui_graph import save_ui_state





def main() -> None:
    p = argparse.ArgumentParser(description="Test draw.io icon detection")
    p.add_argument("--detect", action="store_true", help="Run icon detection.")
    p.add_argument("--label", action="store_true", help="Label icons with LLM.")
    p.add_argument("--write", action="store_true", help="Write results to ui_graph.json.")
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
        countdown()
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

    # 5. Write to ui_graph.json (optional)
    if args.write:
        if not args.label:
            print("\n⚠️  --write requires --label (icons need labels first)")
            return
        print()
        save_ui_state(icons)
        print(f"   Verify: cat state/ui_graph.json | python3 -m json.tool")

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
