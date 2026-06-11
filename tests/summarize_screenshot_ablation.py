"""Summarize screenshot ablation JSON logs into Markdown, CSV, and JSON."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _load_records(
    in_dir: Path,
    agent: Optional[str] = None,
    *,
    include_plan_only: bool = False,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(in_dir.glob("*.json")):
        if path.name.startswith("summary"):
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "task_id" in data and "condition" in data:
            data.setdefault("agent", "executor")
            if agent and data.get("agent") != agent:
                continue
            if data.get("plan_only") and not include_plan_only:
                continue
            data["_path"] = str(path)
            records.append(data)
    return records


def _numbers(rows: Iterable[Dict[str, Any]], key: str) -> List[float]:
    vals: List[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            vals.append(float(value))
    return vals


def _mean(vals: List[float]) -> Optional[float]:
    return mean(vals) if vals else None


def _std(vals: List[float]) -> Optional[float]:
    return stdev(vals) if len(vals) > 1 else 0.0 if vals else None


def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "-"
    if math.isnan(value):
        return "-"
    return f"{value:.{digits}f}"


def _success_rate(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("success") is True) / len(rows)


def _equiv_rate(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    ok = 0
    for r in rows:
        checks = r.get("final_checks", {}) or {}
        if checks.get("labels_ok") and checks.get("edges_ok") and checks.get("no_obvious_overlap"):
            ok += 1
    return ok / len(rows)


def _aggregate(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record.get("agent", "executor"), record["task_id"], record["condition"])].append(record)

    summaries: List[Dict[str, Any]] = []
    for (agent, task_id, condition), rows in sorted(groups.items()):
        total_wall = _numbers(rows, "total_wall_s")
        llm_wall = _numbers(rows, "llm_wall_s")
        tool_wall = _numbers(rows, "tool_wall_s")
        turns = _numbers(rows, "turns")
        screenshots = _numbers(rows, "screenshot_input_count")
        summaries.append({
            "agent": agent,
            "task_id": task_id,
            "condition": condition,
            "n": len(rows),
            "success_rate": _success_rate(rows),
            "equivalent_final_state_rate": _equiv_rate(rows),
            "turns_mean": _mean(turns),
            "turns_std": _std(turns),
            "total_wall_s_mean": _mean(total_wall),
            "total_wall_s_std": _std(total_wall),
            "llm_wall_s_mean": _mean(llm_wall),
            "llm_wall_s_std": _std(llm_wall),
            "tool_wall_s_mean": _mean(tool_wall),
            "tool_wall_s_std": _std(tool_wall),
            "screenshot_input_count_mean": _mean(screenshots),
        })
    return summaries


def _add_speedups(summaries: List[Dict[str, Any]]) -> None:
    by_task: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for summary in summaries:
        by_task[(summary["agent"], summary["task_id"])][summary["condition"]] = summary
    for _, conds in by_task.items():
        sg = conds.get("sg_only")
        shot = conds.get("screenshot_sg")
        if not sg or not shot:
            continue
        sg_time = sg.get("total_wall_s_mean")
        shot_time = shot.get("total_wall_s_mean")
        speedup = None
        if isinstance(sg_time, (int, float)) and sg_time > 0 and isinstance(shot_time, (int, float)):
            speedup = shot_time / sg_time
        sg["speedup_vs_screenshot_sg"] = speedup
        shot["speedup_vs_screenshot_sg"] = 1.0


def _paired_speedups(records: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    by_key: Dict[Tuple[str, str, int], Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for record in records:
        rep = record.get("rep")
        if not isinstance(rep, int):
            continue
        by_key[(record.get("agent", "executor"), record["task_id"], rep)][record["condition"]] = record

    out: Dict[str, List[float]] = defaultdict(list)
    for (agent, task_id, _), conds in by_key.items():
        sg = conds.get("sg_only")
        shot = conds.get("screenshot_sg")
        if not sg or not shot:
            continue
        sg_time = sg.get("total_wall_s")
        shot_time = shot.get("total_wall_s")
        if isinstance(sg_time, (int, float)) and sg_time > 0 and isinstance(shot_time, (int, float)):
            out[f"{agent}:{task_id}"].append(shot_time / sg_time)
    return dict(out)


def _write_csv(path: Path, summaries: List[Dict[str, Any]]) -> None:
    fields = [
        "agent",
        "task_id",
        "condition",
        "n",
        "success_rate",
        "equivalent_final_state_rate",
        "turns_mean",
        "turns_std",
        "total_wall_s_mean",
        "total_wall_s_std",
        "llm_wall_s_mean",
        "llm_wall_s_std",
        "tool_wall_s_mean",
        "tool_wall_s_std",
        "screenshot_input_count_mean",
        "speedup_vs_screenshot_sg",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            writer.writerow({field: row.get(field) for field in fields})


def _write_markdown(
    path: Path,
    summaries: List[Dict[str, Any]],
    paired_speedups: Dict[str, List[float]],
) -> None:
    lines = [
        "# Screenshot Ablation Summary",
        "",
        "| Agent | Task | Condition | n | Success | Equiv. final | Turns | Total wall s | LLM wall s | Screenshot inputs | Speedup |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {agent} | {task_id} | {condition} | {n} | {success:.0%} | {equiv:.0%} | "
            "{turns} | {total} | {llm} | {shots} | {speedup} |".format(
                agent=row["agent"],
                task_id=row["task_id"],
                condition=row["condition"],
                n=row["n"],
                success=row["success_rate"],
                equiv=row["equivalent_final_state_rate"],
                turns=_fmt(row.get("turns_mean")),
                total=_fmt(row.get("total_wall_s_mean")),
                llm=_fmt(row.get("llm_wall_s_mean")),
                shots=_fmt(row.get("screenshot_input_count_mean")),
                speedup=_fmt(row.get("speedup_vs_screenshot_sg")),
            )
        )

    if paired_speedups:
        lines.extend(["", "## Paired Speedups", ""])
        lines.append("| Agent:Task | Pairs | Mean screenshot_sg / sg_only |")
        lines.append("|---|---:|---:|")
        for task_id, values in sorted(paired_speedups.items()):
            lines.append(f"| {task_id} | {len(values)} | {_fmt(_mean(values))} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(args: argparse.Namespace) -> Dict[str, Any]:
    in_dir = Path(args.input)
    in_dir.mkdir(parents=True, exist_ok=True)
    records = _load_records(in_dir, args.agent, include_plan_only=args.include_plan_only)
    summaries = _aggregate(records)
    _add_speedups(summaries)
    paired = _paired_speedups(records)

    out = {
        "input": str(in_dir),
        "agent_filter": args.agent,
        "include_plan_only": args.include_plan_only,
        "records": len(records),
        "summary": summaries,
        "paired_speedups": paired,
    }

    summary_json = in_dir / "summary.json"
    summary_csv = in_dir / "summary.csv"
    summary_md = in_dir / "summary.md"
    summary_json.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(summary_csv, summaries)
    _write_markdown(summary_md, summaries, paired)

    print(f"Loaded {len(records)} record(s)")
    print(f"Wrote {summary_md}")
    print(f"Wrote {summary_csv}")
    print(f"Wrote {summary_json}")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("logs", "ablation"))
    parser.add_argument("--agent", choices=["planner", "executor"], default=None)
    parser.add_argument("--include-plan-only", action="store_true",
                        help="Include plan-only validation records in aggregates.")
    return parser.parse_args()


def main() -> None:
    summarize(parse_args())


if __name__ == "__main__":
    main()
