"""Bar chart: token usage per task, sg_only vs screenshot_sg (ReAct runs).

Stacked bars (prompt + completion tokens, completion on top) grouped by task,
with std error bars over total tokens. No success-rate panel.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CONDITIONS = ["sg_only", "screenshot_sg"]
CONDITION_LABELS = {"sg_only": "SG only (initial screenshot)",
                    "screenshot_sg": "Screenshot + SG (every step)"}
CONDITION_COLORS = {"sg_only": "#4C72B0", "screenshot_sg": "#DD8452"}
TASK_ORDER = ["source_target", "rect3", "rect5", "rect6"]


def load_records(in_dir: Path) -> List[Dict[str, Any]]:
    records = []
    for path in sorted(in_dir.glob("*.json")):
        if path.name.startswith("summary"):
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("agent") == "react" \
                and isinstance(data.get("total_tokens"), (int, float)):
            records.append(data)
    return records


def plot(records: List[Dict[str, Any]], out_base: Path, title: str) -> None:
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        groups[(r["task_id"], r["condition"])].append(r)

    tasks = [t for t in TASK_ORDER if any(k[0] == t for k in groups)]
    tasks += sorted({k[0] for k in groups} - set(tasks))

    x = np.arange(len(tasks))
    width = 0.36
    fig, ax = plt.subplots(figsize=(9, 5.2))

    for i, cond in enumerate(CONDITIONS):
        offsets = x + (i - 0.5) * width
        prompt_means, completion_means, total_stds, ns = [], [], [], []
        for task in tasks:
            rows = groups.get((task, cond), [])
            p = [r.get("prompt_tokens") or 0 for r in rows]
            c = [r.get("completion_tokens") or 0 for r in rows]
            t = [r.get("total_tokens") or 0 for r in rows]
            prompt_means.append(mean(p) if p else 0.0)
            completion_means.append(mean(c) if c else 0.0)
            total_stds.append(stdev(t) if len(t) > 1 else 0.0)
            ns.append(len(rows))

        color = CONDITION_COLORS[cond]
        ax.bar(offsets, prompt_means, width, color=color,
               label=CONDITION_LABELS[cond])
        ax.bar(offsets, completion_means, width, bottom=prompt_means,
               color=color, alpha=0.45,
               label=f"{CONDITION_LABELS[cond]} — completion")
        totals = [p + c for p, c in zip(prompt_means, completion_means)]
        ax.errorbar(offsets, totals, yerr=total_stds, fmt="none",
                    ecolor="#333333", elinewidth=1.2, capsize=4)
        for xo, total, n in zip(offsets, totals, ns):
            if total > 0:
                ax.annotate(f"{total:,.0f}\n(n={n})", (xo, total),
                            textcoords="offset points", xytext=(0, 10),
                            ha="center", fontsize=8.5)

    ax.set_xticks(x)
    ax.set_xticklabels(tasks)
    ax.set_ylabel("Tokens per run (mean over reps)")
    ax.set_title(title)
    ax.margins(y=0.18)
    ax.legend(fontsize=9, loc="upper right")
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()
    for ext in ("png", "svg"):
        path = out_base.with_suffix(f".{ext}")
        fig.savefig(path, dpi=200)
        print(f"Wrote {path}")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("logs", "react_final"))
    parser.add_argument("--out", default=None,
                        help="Output basename (default: <input>/react_token_comparison)")
    parser.add_argument("--title",
                        default="ReAct token usage: scene-graph-only vs screenshot+SG")
    args = parser.parse_args()

    in_dir = Path(args.input)
    records = load_records(in_dir)
    if not records:
        raise SystemExit(f"No react records with token usage in {in_dir}")
    out_base = Path(args.out) if args.out else in_dir / "react_token_comparison"
    print(f"Loaded {len(records)} record(s)")
    plot(records, out_base, args.title)


if __name__ == "__main__":
    main()
