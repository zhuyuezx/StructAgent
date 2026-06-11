"""Generate a paired SVG plot for screenshot-vs-text-only ablations.

The plot is intended for paper figures: each replicate is a point, matched
replicates are connected, and per-condition means are shown as short ticks.
It deliberately avoids plotting dependencies so it works in the project test
environment.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - handled at runtime for PNG output.
    Image = None
    ImageDraw = None
    ImageFont = None


TASK_ORDER = ["source_target", "rect3", "rect5", "rect6"]
TASK_LABELS = {
    "source_target": "Source-target",
    "rect3": "3 rectangles",
    "rect5": "5 rectangles",
    "rect6": "6 rectangles",
}
CONDITIONS = ["sg_only", "screenshot_sg"]
CONDITION_LABELS = {
    "sg_only": "SG only",
    "screenshot_sg": "Screenshot + SG",
}
COLORS = {
    "sg_only": "#2563eb",
    "screenshot_sg": "#dc2626",
}
METRIC_LABELS = {
    "total_wall_s": "Wall-clock time (s)",
    "llm_wall_s": "LLM time (s)",
    "tool_wall_s": "Tool time (s)",
    "turns": "Planner steps",
}


def _load_records(path: Path, agent: Optional[str]) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    skipped = 0
    for file in sorted(path.glob("*.json")):
        if file.name.startswith("summary"):
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped += 1
            continue
        if not isinstance(data, dict):
            skipped += 1
            continue
        data.setdefault("agent", "executor")
        if agent and data.get("agent") != agent:
            continue
        if data.get("plan_only"):
            continue
        if "task_id" not in data or "condition" not in data:
            skipped += 1
            continue
        data["_file"] = file.name
        rows.append(data)
    return rows, skipped


def _equiv(row: Dict[str, Any]) -> bool:
    checks = row.get("final_checks", {}) or {}
    return bool(
        checks.get("labels_ok")
        and checks.get("edges_ok")
        and checks.get("no_obvious_overlap")
    )


def _is_zero_turn_llm_failure(row: Dict[str, Any]) -> bool:
    return row.get("failure_type") == "llm_error" and row.get("turns") == 0


def _metric(row: Dict[str, Any], name: str) -> Optional[float]:
    value = row.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return float(value)
    return None


def _fmt(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _text(
    x: float,
    y: float,
    text: str,
    *,
    size: int = 11,
    anchor: str = "middle",
    weight: str = "400",
    fill: str = "#111827",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{escape(text)}</text>'
    )


def _selected_tasks(records: Sequence[Dict[str, Any]], requested: Sequence[str]) -> List[str]:
    available = {str(row.get("task_id")) for row in records}
    if requested:
        return [task for task in requested if task in available]
    tasks = [task for task in TASK_ORDER if task in available]
    tasks.extend(sorted(available - set(tasks)))
    return tasks


def _values(records: Iterable[Dict[str, Any]], metric: str) -> List[float]:
    out: List[float] = []
    for row in records:
        value = _metric(row, metric)
        if value is not None:
            out.append(value)
    return out


def _latest_by_rep(rows: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Collapse duplicate task/condition/rep records to the lexically latest log."""
    latest: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for row in rows:
        rep = row.get("rep")
        if not isinstance(rep, int):
            continue
        key = (str(row.get("task_id")), str(row.get("condition")), rep)
        prev = latest.get(key)
        if prev is None or str(row.get("_file", "")) > str(prev.get("_file", "")):
            latest[key] = row
    return latest


def _render_marker(x: float, y: float, row: Dict[str, Any], condition: str) -> List[str]:
    color = COLORS[condition]
    equiv = _equiv(row)
    failure = row.get("failure_type")
    fill = color if equiv else "white"
    stroke_width = 1.8 if equiv else 1.5
    parts = [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.8" fill="{fill}" '
        f'stroke="{color}" stroke-width="{stroke_width}"/>'
    ]
    if failure:
        parts.append(
            f'<line x1="{x - 3.0:.1f}" y1="{y - 3.0:.1f}" '
            f'x2="{x + 3.0:.1f}" y2="{y + 3.0:.1f}" '
            f'stroke="#111827" stroke-width="1.1"/>'
        )
        parts.append(
            f'<line x1="{x - 3.0:.1f}" y1="{y + 3.0:.1f}" '
            f'x2="{x + 3.0:.1f}" y2="{y - 3.0:.1f}" '
            f'stroke="#111827" stroke-width="1.1"/>'
        )
    return parts


def render_svg(
    records: List[Dict[str, Any]],
    out_path: Path,
    *,
    tasks: Sequence[str],
    metric: str,
    title: str,
    latest_only: bool,
) -> None:
    if latest_only:
        records = list(_latest_by_rep(records).values())

    tasks_to_plot = _selected_tasks(records, tasks)
    plotted = [
        row
        for row in records
        if row.get("task_id") in tasks_to_plot and row.get("condition") in CONDITIONS
    ]
    vals = _values(plotted, metric)
    if not tasks_to_plot or not vals:
        out_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="220">'
            '<rect width="100%" height="100%" fill="white"/>'
            '<text x="30" y="50" font-family="Arial" font-size="18">'
            'No matching records found.</text></svg>\n',
            encoding="utf-8",
        )
        return

    panel_w = 230
    width = max(720, 118 + panel_w * len(tasks_to_plot))
    height = 430
    margin_left = 76
    margin_right = 30
    margin_top = 70
    margin_bottom = 96
    plot_h = height - margin_top - margin_bottom
    baseline = margin_top + plot_h
    panel_gap = 18
    panel_inner_w = panel_w - panel_gap

    max_value = max(vals)
    y_max = max(1.0, max_value * 1.15)

    def y(value: float) -> float:
        return baseline - (value / y_max) * plot_h

    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _text(width / 2, 28, title, size=17, weight="700"),
        _text(
            width / 2,
            48,
            "Points are live runs; lines connect matched replicates. Filled points pass final-state equivalence; x marks a run failure.",
            size=11,
            fill="#4b5563",
        ),
    ]

    # Shared y-axis.
    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" '
        f'y2="{baseline:.1f}" stroke="#111827" stroke-width="1"/>'
    )
    ticks = 5
    for i in range(ticks + 1):
        value = y_max * i / ticks
        yy = y(value)
        parts.append(
            f'<line x1="{margin_left}" y1="{yy:.1f}" x2="{width - margin_right}" '
            f'y2="{yy:.1f}" stroke="#e5e7eb" stroke-width="1"/>'
        )
        parts.append(_text(margin_left - 8, yy + 4, _fmt(value), anchor="end", fill="#374151"))
    parts.append(
        f'<text x="18" y="{margin_top + plot_h / 2:.1f}" text-anchor="middle" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="12" fill="#374151" '
        f'transform="rotate(-90 18 {margin_top + plot_h / 2:.1f})">'
        f'{escape(METRIC_LABELS.get(metric, metric))}</text>'
    )

    for ti, task in enumerate(tasks_to_plot):
        panel_left = margin_left + ti * panel_w + panel_gap
        x_sg = panel_left + panel_inner_w * 0.30
        x_shot = panel_left + panel_inner_w * 0.70
        x_by_condition = {"sg_only": x_sg, "screenshot_sg": x_shot}

        task_rows = [
            row
            for row in plotted
            if row.get("task_id") == task
        ]
        by_rep: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        unpaired: List[Dict[str, Any]] = []
        for row in task_rows:
            rep = row.get("rep")
            if isinstance(rep, int):
                by_rep[rep][str(row.get("condition"))] = row
            else:
                unpaired.append(row)

        # Panel baseline and condition labels.
        parts.append(
            f'<line x1="{panel_left:.1f}" y1="{baseline:.1f}" '
            f'x2="{panel_left + panel_inner_w:.1f}" y2="{baseline:.1f}" '
            f'stroke="#111827" stroke-width="1"/>'
        )
        parts.append(_text((x_sg + x_shot) / 2, baseline + 56, TASK_LABELS.get(task, task), size=12, weight="700"))
        parts.append(_text(x_sg, baseline + 18, CONDITION_LABELS["sg_only"], size=10, fill="#374151"))
        parts.append(_text(x_shot, baseline + 18, CONDITION_LABELS["screenshot_sg"], size=10, fill="#374151"))

        # Connecting lines are drawn first so points stay readable.
        for rep, conds in sorted(by_rep.items()):
            left = conds.get("sg_only")
            right = conds.get("screenshot_sg")
            if not left or not right:
                continue
            left_value = _metric(left, metric)
            right_value = _metric(right, metric)
            if left_value is None or right_value is None:
                continue
            parts.append(
                f'<line x1="{x_sg:.1f}" y1="{y(left_value):.1f}" '
                f'x2="{x_shot:.1f}" y2="{y(right_value):.1f}" '
                f'stroke="#9ca3af" stroke-width="1.2" opacity="0.75"/>'
            )

        condition_rows: Dict[str, List[Dict[str, Any]]] = {
            condition: [row for row in task_rows if row.get("condition") == condition]
            for condition in CONDITIONS
        }
        for condition, rows in condition_rows.items():
            x0 = x_by_condition[condition]
            rows = sorted(rows, key=lambda row: (row.get("rep", 9999), row.get("_file", "")))
            for idx, row in enumerate(rows):
                value = _metric(row, metric)
                if value is None:
                    continue
                # Deterministic jitter keeps duplicate points from perfectly hiding each other.
                jitter = ((idx % 5) - 2) * 3.0
                parts.extend(_render_marker(x0 + jitter, y(value), row, condition))

            values = _values(rows, metric)
            if values:
                m = mean(values)
                yy = y(m)
                parts.append(
                    f'<line x1="{x0 - 18:.1f}" y1="{yy:.1f}" x2="{x0 + 18:.1f}" '
                    f'y2="{yy:.1f}" stroke="{COLORS[condition]}" stroke-width="3"/>'
                )
                equiv_count = sum(1 for row in rows if _equiv(row))
                parts.append(_text(x0, baseline + 34, f"n={len(rows)}, equiv {equiv_count}/{len(rows)}", size=9, fill="#4b5563"))
                parts.append(_text(x0, yy - 9, _fmt(m), size=9, fill=COLORS[condition], weight="700"))

    # Legend.
    legend_y = height - 24
    legend_x = margin_left
    parts.append(f'<circle cx="{legend_x:.1f}" cy="{legend_y:.1f}" r="4.8" fill="#111827" stroke="#111827"/>')
    parts.append(_text(legend_x + 12, legend_y + 4, "equivalent final state", anchor="start", size=10, fill="#374151"))
    parts.append(f'<circle cx="{legend_x + 150:.1f}" cy="{legend_y:.1f}" r="4.8" fill="white" stroke="#111827" stroke-width="1.5"/>')
    parts.append(_text(legend_x + 162, legend_y + 4, "not equivalent", anchor="start", size=10, fill="#374151"))
    parts.append(
        f'<line x1="{legend_x + 260:.1f}" y1="{legend_y - 3:.1f}" x2="{legend_x + 266:.1f}" y2="{legend_y + 3:.1f}" stroke="#111827" stroke-width="1.1"/>'
    )
    parts.append(
        f'<line x1="{legend_x + 260:.1f}" y1="{legend_y + 3:.1f}" x2="{legend_x + 266:.1f}" y2="{legend_y - 3:.1f}" stroke="#111827" stroke-width="1.1"/>'
    )
    parts.append(_text(legend_x + 274, legend_y + 4, "failure_type set", anchor="start", size=10, fill="#374151"))

    parts.append("</svg>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _rgb(hex_color: str) -> Tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _font(size: int, *, bold: bool = False) -> Any:
    if ImageFont is None:
        return None
    names = ["arialbd.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "Arial.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _draw_text(
    draw: Any,
    x: float,
    y: float,
    text: str,
    *,
    size: int = 22,
    anchor: str = "mm",
    fill: Tuple[int, int, int] = (17, 24, 39),
    bold: bool = False,
) -> None:
    draw.text((x, y), text, font=_font(size, bold=bold), fill=fill, anchor=anchor)


def render_png(
    records: List[Dict[str, Any]],
    out_path: Path,
    *,
    tasks: Sequence[str],
    metric: str,
    title: str,
    latest_only: bool,
    scale: int = 2,
) -> None:
    if Image is None or ImageDraw is None:
        raise RuntimeError("PNG output requires Pillow. Install dependencies with: pip install Pillow")

    if latest_only:
        records = list(_latest_by_rep(records).values())

    tasks_to_plot = _selected_tasks(records, tasks)
    plotted = [
        row
        for row in records
        if row.get("task_id") in tasks_to_plot and row.get("condition") in CONDITIONS
    ]
    vals = _values(plotted, metric)
    if not tasks_to_plot or not vals:
        image = Image.new("RGB", (760 * scale, 220 * scale), "white")
        draw = ImageDraw.Draw(image)
        _draw_text(draw, 30 * scale, 50 * scale, "No matching records found.", size=18 * scale, anchor="la")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)
        return

    panel_w = 230 * scale
    width = max(720 * scale, 118 * scale + panel_w * len(tasks_to_plot))
    height = 430 * scale
    margin_left = 76 * scale
    margin_right = 30 * scale
    margin_top = 70 * scale
    margin_bottom = 96 * scale
    plot_h = height - margin_top - margin_bottom
    baseline = margin_top + plot_h
    panel_gap = 18 * scale
    panel_inner_w = panel_w - panel_gap
    y_max = max(1.0, max(vals) * 1.15)

    def y(value: float) -> float:
        return baseline - (value / y_max) * plot_h

    image = Image.new("RGB", (int(width), int(height)), "white")
    draw = ImageDraw.Draw(image)

    _draw_text(draw, width / 2, 28 * scale, title, size=17 * scale, bold=True)
    _draw_text(
        draw,
        width / 2,
        48 * scale,
        "Points are live runs; lines connect matched replicates. Filled points pass final-state equivalence; x marks a run failure.",
        size=11 * scale,
        fill=(75, 85, 99),
    )

    draw.line((margin_left, margin_top, margin_left, baseline), fill=(17, 24, 39), width=scale)
    for i in range(6):
        value = y_max * i / 5
        yy = y(value)
        draw.line((margin_left, yy, width - margin_right, yy), fill=(229, 231, 235), width=scale)
        _draw_text(draw, margin_left - 8 * scale, yy, _fmt(value), size=11 * scale, anchor="rm", fill=(55, 65, 81))
    _draw_text(
        draw,
        16 * scale,
        margin_top + plot_h / 2,
        METRIC_LABELS.get(metric, metric),
        size=12 * scale,
        anchor="mm",
        fill=(55, 65, 81),
    )

    for ti, task in enumerate(tasks_to_plot):
        panel_left = margin_left + ti * panel_w + panel_gap
        x_sg = panel_left + panel_inner_w * 0.30
        x_shot = panel_left + panel_inner_w * 0.70
        x_by_condition = {"sg_only": x_sg, "screenshot_sg": x_shot}
        task_rows = [row for row in plotted if row.get("task_id") == task]
        by_rep: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        for row in task_rows:
            rep = row.get("rep")
            if isinstance(rep, int):
                by_rep[rep][str(row.get("condition"))] = row

        draw.line((panel_left, baseline, panel_left + panel_inner_w, baseline), fill=(17, 24, 39), width=scale)
        _draw_text(draw, (x_sg + x_shot) / 2, baseline + 56 * scale, TASK_LABELS.get(task, task), size=12 * scale, bold=True)
        _draw_text(draw, x_sg, baseline + 18 * scale, CONDITION_LABELS["sg_only"], size=10 * scale, fill=(55, 65, 81))
        _draw_text(draw, x_shot, baseline + 18 * scale, CONDITION_LABELS["screenshot_sg"], size=10 * scale, fill=(55, 65, 81))

        for _, conds in sorted(by_rep.items()):
            left = conds.get("sg_only")
            right = conds.get("screenshot_sg")
            if not left or not right:
                continue
            left_value = _metric(left, metric)
            right_value = _metric(right, metric)
            if left_value is None or right_value is None:
                continue
            draw.line((x_sg, y(left_value), x_shot, y(right_value)), fill=(156, 163, 175), width=max(1, scale))

        for condition in CONDITIONS:
            rows = sorted(
                [row for row in task_rows if row.get("condition") == condition],
                key=lambda row: (row.get("rep", 9999), row.get("_file", "")),
            )
            x0 = x_by_condition[condition]
            color = _rgb(COLORS[condition])
            for idx, row in enumerate(rows):
                value = _metric(row, metric)
                if value is None:
                    continue
                jitter = ((idx % 5) - 2) * 3.0 * scale
                cx = x0 + jitter
                cy = y(value)
                r = 4.8 * scale
                fill = color if _equiv(row) else (255, 255, 255)
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=color, width=max(2, scale + 1))
                if row.get("failure_type"):
                    draw.line((cx - 3 * scale, cy - 3 * scale, cx + 3 * scale, cy + 3 * scale), fill=(17, 24, 39), width=max(1, scale))
                    draw.line((cx - 3 * scale, cy + 3 * scale, cx + 3 * scale, cy - 3 * scale), fill=(17, 24, 39), width=max(1, scale))

            values = _values(rows, metric)
            if values:
                m = mean(values)
                yy = y(m)
                draw.line((x0 - 18 * scale, yy, x0 + 18 * scale, yy), fill=color, width=3 * scale)
                equiv_count = sum(1 for row in rows if _equiv(row))
                _draw_text(draw, x0, baseline + 34 * scale, f"n={len(rows)}, equiv {equiv_count}/{len(rows)}", size=9 * scale, fill=(75, 85, 99))
                _draw_text(draw, x0, yy - 9 * scale, _fmt(m), size=9 * scale, fill=color, bold=True)

    legend_y = height - 24 * scale
    legend_x = margin_left
    r = 4.8 * scale
    draw.ellipse((legend_x - r, legend_y - r, legend_x + r, legend_y + r), fill=(17, 24, 39), outline=(17, 24, 39))
    _draw_text(draw, legend_x + 12 * scale, legend_y, "equivalent final state", size=10 * scale, anchor="lm", fill=(55, 65, 81))
    cx = legend_x + 150 * scale
    draw.ellipse((cx - r, legend_y - r, cx + r, legend_y + r), fill=(255, 255, 255), outline=(17, 24, 39), width=max(2, scale))
    _draw_text(draw, cx + 12 * scale, legend_y, "not equivalent", size=10 * scale, anchor="lm", fill=(55, 65, 81))
    cx = legend_x + 263 * scale
    draw.line((cx - 3 * scale, legend_y - 3 * scale, cx + 3 * scale, legend_y + 3 * scale), fill=(17, 24, 39), width=max(1, scale))
    draw.line((cx - 3 * scale, legend_y + 3 * scale, cx + 3 * scale, legend_y - 3 * scale), fill=(17, 24, 39), width=max(1, scale))
    _draw_text(draw, cx + 11 * scale, legend_y, "failure_type set", size=10 * scale, anchor="lm", fill=(55, 65, 81))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("logs", "ablation_live"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--agent", choices=["planner", "executor"], default="planner")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Task id to plot. Repeat for multiple tasks. Defaults to all tasks.",
    )
    parser.add_argument(
        "--metric",
        choices=sorted(METRIC_LABELS),
        default="total_wall_s",
        help="Metric to plot on the y-axis.",
    )
    parser.add_argument(
        "--drop-zero-turn-llm-errors",
        action="store_true",
        help="Drop infrastructure-like LLM failures where no planner turn completed.",
    )
    parser.add_argument(
        "--latest-only",
        action="store_true",
        help="If multiple logs share task/condition/rep, keep only the lexically latest file.",
    )
    parser.add_argument(
        "--title",
        default="Screenshot Ablation: Paired Live Runs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    in_dir = Path(args.input)
    out = Path(args.output) if args.output else in_dir / "textonly_paired_ablation.svg"
    records, skipped = _load_records(in_dir, args.agent)
    if args.drop_zero_turn_llm_errors:
        records = [row for row in records if not _is_zero_turn_llm_failure(row)]
    render_svg(
        records,
        out,
        tasks=args.task,
        metric=args.metric,
        title=args.title,
        latest_only=args.latest_only,
    ) if out.suffix.lower() != ".png" else render_png(
        records,
        out,
        tasks=args.task,
        metric=args.metric,
        title=args.title,
        latest_only=args.latest_only,
    )
    print(f"Loaded {len(records)} live record(s)")
    if skipped:
        print(f"Skipped {skipped} unreadable or malformed record(s)")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
