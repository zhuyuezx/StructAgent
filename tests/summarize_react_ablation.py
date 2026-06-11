"""Summarize ReAct ablation JSON logs (incl. token usage) into MD/CSV/JSON."""

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


def _load_records(in_dir: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(in_dir.glob("*.json")):
        if path.name.startswith("summary"):
            continue
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("agent") == "react" \
                and "task_id" in data and "condition" in data:
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
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "-"
    return f"{value:.{digits}f}"


def _fmt_int(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}"


def _success_rate(rows: List[Dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("success") is True) / len(rows)


def _aggregate(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["task_id"], record["condition"])].append(record)

    summaries: List[Dict[str, Any]] = []
    for (task_id, condition), rows in sorted(groups.items()):
        summaries.append({
            "task_id": task_id,
            "condition": condition,
            "n": len(rows),
            "success_rate": _success_rate(rows),
            "turns_mean": _mean(_numbers(rows, "turns")),
            "turns_std": _std(_numbers(rows, "turns")),
            "llm_calls_mean": _mean(_numbers(rows, "llm_calls")),
            "total_wall_s_mean": _mean(_numbers(rows, "total_wall_s")),
            "total_wall_s_std": _std(_numbers(rows, "total_wall_s")),
            "llm_wall_s_mean": _mean(_numbers(rows, "llm_wall_s")),
            "tool_wall_s_mean": _mean(_numbers(rows, "tool_wall_s")),
            "screenshot_input_count_mean": _mean(
                _numbers(rows, "screenshot_input_count")),
            "prompt_tokens_mean": _mean(_numbers(rows, "prompt_tokens")),
            "prompt_tokens_std": _std(_numbers(rows, "prompt_tokens")),
            "completion_tokens_mean": _mean(_numbers(rows, "completion_tokens")),
            "total_tokens_mean": _mean(_numbers(rows, "total_tokens")),
            "total_tokens_std": _std(_numbers(rows, "total_tokens")),
        })
    return summaries


def _add_ratios(summaries: List[Dict[str, Any]]) -> None:
    """Per task: screenshot_sg cost relative to sg_only (tokens + wall)."""
    by_task: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for summary in summaries:
        by_task[summary["task_id"]][summary["condition"]] = summary
    for conds in by_task.values():
        sg = conds.get("sg_only")
        shot = conds.get("screenshot_sg")
        if not sg or not shot:
            continue
        for src_key, ratio_key in (
            ("total_tokens_mean", "token_ratio_vs_sg_only"),
            ("total_wall_s_mean", "wall_ratio_vs_sg_only"),
        ):
            sg_val = sg.get(src_key)
            shot_val = shot.get(src_key)
            ratio = None
            if isinstance(sg_val, (int, float)) and sg_val > 0 \
                    and isinstance(shot_val, (int, float)):
                ratio = shot_val / sg_val
            shot[ratio_key] = ratio
            sg[ratio_key] = 1.0 if ratio is not None else None


def _paired_token_ratios(records: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    by_key: Dict[Tuple[str, int], Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for record in records:
        rep = record.get("rep")
        if isinstance(rep, int):
            by_key[(record["task_id"], rep)][record["condition"]] = record

    out: Dict[str, List[float]] = defaultdict(list)
    for (task_id, _), conds in by_key.items():
        sg = conds.get("sg_only")
        shot = conds.get("screenshot_sg")
        if not sg or not shot:
            continue
        sg_tok = sg.get("total_tokens")
        shot_tok = shot.get("total_tokens")
        if isinstance(sg_tok, (int, float)) and sg_tok > 0 \
                and isinstance(shot_tok, (int, float)):
            out[task_id].append(shot_tok / sg_tok)
    return dict(out)


_CSV_FIELDS = [
    "task_id", "condition", "n", "success_rate",
    "turns_mean", "turns_std", "llm_calls_mean",
    "total_wall_s_mean", "total_wall_s_std",
    "llm_wall_s_mean", "tool_wall_s_mean",
    "screenshot_input_count_mean",
    "prompt_tokens_mean", "prompt_tokens_std",
    "completion_tokens_mean",
    "total_tokens_mean", "total_tokens_std",
    "token_ratio_vs_sg_only", "wall_ratio_vs_sg_only",
]


def _write_csv(path: Path, summaries: List[Dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for row in summaries:
            writer.writerow({field: row.get(field) for field in _CSV_FIELDS})


def _write_markdown(
    path: Path,
    summaries: List[Dict[str, Any]],
    paired_ratios: Dict[str, List[float]],
) -> None:
    lines = [
        "# ReAct Ablation Summary",
        "",
        "| Task | Condition | n | Success | Turns | LLM calls | "
        "Prompt tok | Compl. tok | Total tok | Tok ratio | "
        "Total wall s | LLM wall s | Screenshots |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {task} | {cond} | {n} | {success:.0%} | {turns} | {calls} | "
            "{ptok} | {ctok} | {ttok} | {ratio} | {total} | {llm} | {shots} |".format(
                task=row["task_id"],
                cond=row["condition"],
                n=row["n"],
                success=row["success_rate"],
                turns=_fmt(row.get("turns_mean"), 1),
                calls=_fmt(row.get("llm_calls_mean"), 1),
                ptok=_fmt_int(row.get("prompt_tokens_mean")),
                ctok=_fmt_int(row.get("completion_tokens_mean")),
                ttok=_fmt_int(row.get("total_tokens_mean")),
                ratio=_fmt(row.get("token_ratio_vs_sg_only")),
                total=_fmt(row.get("total_wall_s_mean")),
                llm=_fmt(row.get("llm_wall_s_mean")),
                shots=_fmt(row.get("screenshot_input_count_mean"), 1),
            )
        )

    if paired_ratios:
        lines.extend(["", "## Paired Token Ratios (screenshot_sg / sg_only)", ""])
        lines.append("| Task | Pairs | Mean ratio |")
        lines.append("|---|---:|---:|")
        for task_id, values in sorted(paired_ratios.items()):
            lines.append(f"| {task_id} | {len(values)} | {_fmt(_mean(values))} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(args: argparse.Namespace) -> Dict[str, Any]:
    in_dir = Path(args.input)
    in_dir.mkdir(parents=True, exist_ok=True)
    records = _load_records(in_dir)
    summaries = _aggregate(records)
    _add_ratios(summaries)
    paired = _paired_token_ratios(records)

    out = {
        "input": str(in_dir),
        "agent": "react",
        "records": len(records),
        "summary": summaries,
        "paired_token_ratios": paired,
    }

    summary_json = in_dir / "summary.json"
    summary_csv = in_dir / "summary.csv"
    summary_md = in_dir / "summary.md"
    summary_json.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    _write_csv(summary_csv, summaries)
    _write_markdown(summary_md, summaries, paired)

    print(f"Loaded {len(records)} record(s)")
    print(f"Wrote {summary_md}")
    print(f"Wrote {summary_csv}")
    print(f"Wrote {summary_json}")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=os.path.join("logs", "react_ablation"))
    return parser.parse_args()


def main() -> None:
    summarize(parse_args())


if __name__ == "__main__":
    main()
