"""Generate a report-ready SVG for the screenshot ablation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


TASK_ORDER = ["source_target", "rect3", "rect5", "rect6"]
TASK_LABELS = {
    "source_target": "2 rects",
    "rect3": "3 rects",
    "rect5": "5 rects",
    "rect6": "6 rects",
}
CONDITIONS = ["sg_only", "screenshot_sg"]
CONDITION_LABELS = {
    "sg_only": "Scene graph only",
    "screenshot_sg": "Screenshot + SG",
}
COLORS = {
    "sg_only": "#2563eb",
    "screenshot_sg": "#dc2626",
}


def _load_records(path: Path, agent: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for file in sorted(path.glob("*.json")):
        if file.name.startswith("summary"):
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("agent", "executor")
        if agent and data.get("agent") != agent:
            continue
        if data.get("plan_only"):
            continue
        if "task_id" not in data or "condition" not in data:
            continue
        rows.append(data)
    return rows


def _equiv(row: Dict[str, Any]) -> bool:
    checks = row.get("final_checks", {}) or {}
    return bool(
        checks.get("labels_ok")
        and checks.get("edges_ok")
        and checks.get("no_obvious_overlap")
    )


def _aggregate(records: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in records:
        groups[(row["task_id"], row["condition"])].append(row)

    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, rows in groups.items():
        wall = [float(r["total_wall_s"]) for r in rows if isinstance(r.get("total_wall_s"), (int, float))]
        turns = [float(r["turns"]) for r in rows if isinstance(r.get("turns"), (int, float))]
        equiv_count = sum(1 for r in rows if _equiv(r))
        success_count = sum(1 for r in rows if r.get("success") is True)
        out[key] = {
            "n": len(rows),
            "wall_mean": mean(wall) if wall else 0.0,
            "turns_mean": mean(turns) if turns else 0.0,
            "equiv_count": equiv_count,
            "success_count": success_count,
        }
    return out


def _svg_text(x: float, y: float, text: str, *, size: int = 12, anchor: str = "middle",
              weight: str = "400", fill: str = "#111827") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{escape(text)}</text>'
    )


def render_svg(records: List[Dict[str, Any]], out_path: Path) -> None:
    agg = _aggregate(records)
    tasks = [t for t in TASK_ORDER if any((t, c) in agg for c in CONDITIONS)]
    extras = sorted({task for task, _ in agg if task not in tasks})
    tasks.extend(extras)
    if not tasks:
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="220">'
            '<text x="30" y="50" font-family="Arial" font-size="18">'
            'No live records found.</text></svg>\n',
            encoding="utf-8",
        )
        return

    width = max(760, 170 * len(tasks) + 160)
    height = 460
    margin_left = 78
    margin_right = 28
    margin_top = 64
    margin_bottom = 88
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    baseline = margin_top + plot_h
    max_wall = max((v["wall_mean"] for v in agg.values()), default=1.0)
    y_max = max(1.0, max_wall * 1.18)

    def y(value: float) -> float:
        return baseline - (value / y_max) * plot_h

    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(width / 2, 28, "Screenshot Ablation: Wall-Clock Time", size=18, weight="700"),
        _svg_text(width / 2, 48, "Bars show mean live run time; labels show mean plan steps and final-state equivalence.", size=12, fill="#4b5563"),
    ]

    # Axes and grid.
    parts.append(f'<line x1="{margin_left}" y1="{baseline:.1f}" x2="{width - margin_right}" y2="{baseline:.1f}" stroke="#111827" stroke-width="1"/>')
    parts.append(f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{baseline:.1f}" stroke="#111827" stroke-width="1"/>')
    ticks = 5
    for i in range(ticks + 1):
        value = y_max * i / ticks
        yy = y(value)
        parts.append(f'<line x1="{margin_left}" y1="{yy:.1f}" x2="{width - margin_right}" y2="{yy:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
        parts.append(_svg_text(margin_left - 10, yy + 4, f"{value:.0f}", anchor="end", size=11, fill="#374151"))
    parts.append(_svg_text(18, margin_top + plot_h / 2, "seconds", anchor="middle", size=12, fill="#374151") +
                 f'<g transform="rotate(-90 18 {margin_top + plot_h / 2:.1f})"></g>')

    group_w = plot_w / len(tasks)
    bar_w = min(42, group_w / 4)
    gap = 10
    for ti, task in enumerate(tasks):
        cx = margin_left + group_w * ti + group_w / 2
        for ci, condition in enumerate(CONDITIONS):
            data = agg.get((task, condition))
            offset = (ci - 0.5) * (bar_w + gap)
            x = cx + offset - bar_w / 2
            if data is None:
                continue
            h = baseline - y(data["wall_mean"])
            parts.append(
                f'<rect x="{x:.1f}" y="{baseline - h:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
                f'fill="{COLORS[condition]}" rx="2"/>'
            )
            label = f'{data["turns_mean"]:.1f} steps'
            equiv = f'{data["equiv_count"]}/{data["n"]} equiv'
            parts.append(_svg_text(x + bar_w / 2, baseline - h - 20, label, size=10, fill="#111827"))
            parts.append(_svg_text(x + bar_w / 2, baseline - h - 7, equiv, size=10, fill="#374151"))
            parts.append(_svg_text(x + bar_w / 2, baseline + 18 + ci * 14, CONDITION_LABELS[condition], size=9, fill="#374151"))
        parts.append(_svg_text(cx, baseline + 54, TASK_LABELS.get(task, task), size=12, weight="700"))

    # Legend.
    legend_x = width - margin_right - 260
    legend_y = margin_top - 20
    for i, condition in enumerate(CONDITIONS):
        x = legend_x + i * 138
        parts.append(f'<rect x="{x}" y="{legend_y}" width="14" height="14" fill="{COLORS[condition]}" rx="2"/>')
        parts.append(_svg_text(x + 20, legend_y + 11, CONDITION_LABELS[condition], anchor="start", size=11, fill="#374151"))

    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("logs", "ablation_live"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--agent", choices=["planner", "executor"], default="planner")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    in_dir = Path(args.input)
    out = Path(args.output) if args.output else in_dir / "textonly_ablation.svg"
    records = _load_records(in_dir, args.agent)
    render_svg(records, out)
    print(f"Loaded {len(records)} live record(s)")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
