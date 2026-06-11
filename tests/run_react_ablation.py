"""
ReAct ablation harness — per-step reasoning instead of plan-and-execute.

Each step is one LLM call (Thought → Action) followed by tool dispatch
(Observation = the framework-updated SCENE GRAPH). Two input conditions:

    sg_only       -> ONE initial screenshot taken right after the environment
                     reset is attached to the FIRST LLM call (together with the
                     user prompt). Every later step sees only the updated
                     SCENE GRAPH — no images.
    screenshot_sg -> every step gets BOTH a fresh screenshot and the updated
                     SCENE GRAPH.

Token usage (prompt/completion) is recorded per LLM call and totalled per run
so the two conditions can be compared on cost, not just wall time.

Environment reset: before each run the harness resets the scene graph, the
canvas content, AND the viewport — Escape, clear selection, select-all +
delete, Ctrl+Shift+H (draw.io "Reset View": zoom 100% + scroll to origin),
deselect. Pass ``--reload-page`` to additionally reload the draw.io tab
between runs (chrome_cdp backend only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config
from core.agents.executor import infer
from core.capture import screenshot
from core.state import scene_graph as sg
from core.target import manager as target_manager
from core.tools import TOOL_CATALOG, dispatch

# Shared task definitions, final-state checks, and small helpers from the
# plan-and-execute ablation so both experiments grade runs identically.
from run_screenshot_ablation import (  # noqa: E402
    TASKS,
    _countdown,
    _failure_type,
    _final_checks,
    _git_value,
    _now_utc,
    _safe_name,
)

CONDITIONS = ("sg_only", "screenshot_sg")

# Signals the model may always emit, on top of --allowed-tools.
SPECIAL_SIGNALS = {"task_complete", "request_rescan"}

# Abort the run when the model emits the exact same tool+params this many
# times in a row — it is stuck, and further LLM calls only burn tokens.
MAX_IDENTICAL_DECISIONS = 3

# ReAct error feedback: dispatch errors and unparseable responses are fed
# back as observations so the model can correct itself, but this many in a
# row means it cannot recover — abort instead of burning the step budget.
MAX_CONSECUTIVE_ERRORS = 3

# Offset palette suggested when the model reuses a place_label_and_move
# direction+amount pair (which would stack two shapes at the same point).
OFFSET_PALETTE = [
    ("w", 220), ("e", 220), ("n", 220), ("s", 220),
    ("nw", 220), ("ne", 220), ("se", 220), ("sw", 220),
    ("w", 440), ("e", 440), ("n", 440), ("s", 440),
]


def _offset_key(params: Dict[str, Any]) -> Optional[tuple]:
    direction = str(params.get("direction", "")).lower().strip()
    amount = params.get("amount")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return None
    return (direction, amount) if direction else None


def _parse_allowed_tools(spec: str) -> Optional[set]:
    """Parse --allowed-tools; 'all' (or empty) disables the restriction."""
    if not spec or spec.strip().lower() == "all":
        return None
    tools = {t.strip() for t in spec.split(",") if t.strip()}
    unknown = tools - set(TOOL_CATALOG)
    if unknown:
        raise SystemExit(f"--allowed-tools contains unknown tool(s): "
                         f"{', '.join(sorted(unknown))}")
    return tools


# ---------------------------------------------------------------------------
# Environment reset — scene graph + canvas + viewport
# ---------------------------------------------------------------------------

def reset_environment(
    graph: Dict[str, Any],
    *,
    countdown_seconds: int = 0,
    reload_page: bool = False,
    reload_settle_s: float = 6.0,
) -> Dict[str, Any]:
    """Bring draw.io to a known-clean state before a run.

    Steps (all best-effort, recorded in the returned dict):
      1. Escape           — exit any in-place text editing / close dialogs
      2. click empty      — focus canvas, clear selection
      3. select all + Del — clear canvas content
      4. optional page reload (chrome_cdp only) — done AFTER the canvas is
         emptied so draw.io's autosaved document is empty when it comes back
      5. viewport reset   — editor resetView via CDP JS: zoom 100% +
         canonical scroll + clear selection (NOT the Ctrl+Shift+H hotkey,
         which is "Fit Page" in recent draw.io builds and shrinks the view)
      6. click empty      — clear focus/selection remnants
      7. scene graph reset
    """
    _countdown(countdown_seconds, "Focus draw.io now; resetting environment in:")
    report: Dict[str, Any] = {"reload_page_requested": reload_page}

    def _step(name: str, tool: str, params: Dict[str, Any], wait: float = 0.2) -> None:
        try:
            dispatch(tool, params, ui_graph=graph)
            report[name] = "ok"
        except Exception as exc:
            report[name] = f"error: {exc}"
        time.sleep(wait)

    _step("press_escape", "press_escape", {})
    _step("click_empty_canvas", "click_empty_canvas", {})
    _step("select_all", "select_all", {})
    _step("press_delete", "press_delete", {})

    if reload_page:
        try:
            report["reload_page_done"] = target_manager.reload_page(
                settle_seconds=reload_settle_s
            )
        except Exception as exc:
            report["reload_page_done"] = False
            report["reload_page_error"] = str(exc)

    try:
        viewport = target_manager.reset_view()
        if viewport is None:
            report["reset_view"] = "unsupported (non-CDP backend; viewport unchanged)"
        else:
            report["reset_view"] = "ok"
            report["viewport"] = viewport
    except Exception as exc:
        report["reset_view"] = f"error: {exc}"
    time.sleep(0.5)

    _step("deselect", "click_empty_canvas", {})

    graph["scene_graph"] = sg.reset()
    graph["selected_handles"] = None
    report["scene_graph_reset"] = "ok"
    return report


# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------

def _accumulate_usage(total: Dict[str, int], usage: Optional[Dict[str, Any]]) -> None:
    if not isinstance(usage, dict):
        return
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + int(value)


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------

def run_react(args: argparse.Namespace) -> Dict[str, Any]:
    task_def = TASKS[args.task_id]
    condition = args.condition
    per_step_screenshot = condition == "screenshot_sg"
    # A run needs one turn per shape, one per edge, one task_complete; give
    # 5 slack turns for error/rejection recovery. config.llm_max_steps()
    # (10) is too tight for rect6 (6 shapes + 5 edges + done = 12 minimum).
    steps_needed = (len(task_def["labels"]) + len(task_def["edges"]) + 1) + 5
    max_steps = args.max_steps or max(config.llm_max_steps(), steps_needed)
    cooldown = 0.0 if args.dry_run else config.step_cooldown()
    allowed_tools = _parse_allowed_tools(args.allowed_tools)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    graph = config.ui_graph()
    graph["scene_graph"] = sg.load()

    reset_report: Dict[str, Any] = {}
    if args.reset_env:
        reset_report = reset_environment(
            graph,
            countdown_seconds=args.countdown,
            reload_page=args.reload_page,
            reload_settle_s=args.reload_settle,
        )
    else:
        graph["scene_graph"] = sg.reset()

    print(f"Task: {args.task_id}")
    print(f"Condition: {condition}")
    print("Agent: react")

    started_at = _now_utc()
    total_start = time.perf_counter()
    history: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    usage_total: Dict[str, int] = {}
    llm_calls = 0
    usage_missing_calls = 0
    screenshot_input_count = 0
    llm_wall_s = 0.0
    tool_wall_s = 0.0
    terminated_by_task_complete = False
    max_steps_reached = False
    aborted_by_repetition = False
    aborted_by_errors = False
    last_decision_key: Optional[str] = None
    repeat_count = 0
    consecutive_errors = 0
    parse_error_count = 0
    tool_error_count = 0
    used_offsets: Dict[tuple, str] = {}

    # sg_only: one screenshot of the freshly reset canvas, attached to the
    # FIRST LLM call only, alongside the user prompt.
    initial_screenshot: Optional[str] = None
    initial_screenshot_error: Optional[str] = None
    if not per_step_screenshot:
        name = f"react_{args.task_id}_{condition}_rep{args.rep:02d}_initial.png"
        try:
            initial_screenshot = screenshot(name)
            screenshot_input_count += 1
        except Exception as exc:
            initial_screenshot_error = str(exc)
            print(f"WARNING: initial screenshot failed ({exc}); "
                  "first step falls back to text-only.")

    for step in range(1, max_steps + 1):
        step_record: Dict[str, Any] = {"step": step}

        if per_step_screenshot:
            name = (f"react_{args.task_id}_{condition}_rep{args.rep:02d}"
                    f"_step{step:02d}.png")
            try:
                image_path: Optional[str] = screenshot(name)
            except Exception as exc:
                step_record["result"] = {
                    "status": "error",
                    "phase": "screenshot_capture",
                    "error": str(exc),
                }
                step_record["result_status"] = "error"
                trace.append(step_record)
                break
            screenshot_input_count += 1
        else:
            image_path = initial_screenshot if step == 1 else None
        step_record["used_screenshot_input"] = image_path is not None
        if image_path:
            step_record["screenshot_input"] = image_path

        llm_start = time.perf_counter()
        try:
            decision = infer(task_def["task"], graph, image_path, history or None,
                             allowed_tools=allowed_tools)
        except ValueError as exc:
            # Malformed response (e.g. a status object with no "tool" key).
            # ReAct-style recovery: tell the model what was wrong and retry.
            step_llm_s = time.perf_counter() - llm_start
            llm_wall_s += step_llm_s
            llm_calls += 1
            parse_error_count += 1
            consecutive_errors += 1
            step_record.update({
                "llm_wall_s": step_llm_s,
                "result": {"status": "error", "phase": "llm_parse",
                           "error": str(exc)},
                "result_status": "error",
            })
            trace.append(step_record)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                aborted_by_errors = True
                break
            history.append({
                "role": "assistant",
                "content": json.dumps({"reasoning": "(previous response was "
                                       "not a valid decision object)",
                                       "tool": None, "params": {}}),
            })
            history.append({
                "role": "user",
                "content": ("Observation: your previous response was INVALID — "
                            "it must be one JSON object with the keys "
                            "'reasoning', 'tool', and 'params'. Do not emit "
                            "status or summary objects. If the SCENE GRAPH "
                            "shows the task is fully done, respond with "
                            "{\"reasoning\": \"...\", \"tool\": "
                            "\"task_complete\", \"params\": {}}."),
            })
            continue
        except Exception as exc:
            step_llm_s = time.perf_counter() - llm_start
            llm_wall_s += step_llm_s
            step_record.update({
                "llm_wall_s": step_llm_s,
                "result": {"status": "error", "phase": "llm", "error": str(exc)},
                "result_status": "error",
            })
            trace.append(step_record)
            break
        step_llm_s = time.perf_counter() - llm_start
        llm_wall_s += step_llm_s
        llm_calls += 1

        usage = decision.pop("_usage", None)
        if usage:
            _accumulate_usage(usage_total, usage)
        else:
            usage_missing_calls += 1

        tool_name = decision.get("tool", "")
        params = decision.get("params", {}) or {}
        step_record.update({
            "tool": tool_name,
            "params": params,
            "reasoning": decision.get("reasoning", ""),
            "llm_wall_s": step_llm_s,
            "usage": usage,
        })

        history.append({"role": "assistant", "content": json.dumps(decision)})

        # Repetition guard — a model stuck emitting the identical decision
        # never recovers; cut the run instead of burning the step budget.
        decision_key = f"{tool_name}|{json.dumps(params, sort_keys=True)}"
        if decision_key == last_decision_key:
            repeat_count += 1
        else:
            repeat_count = 1
            last_decision_key = decision_key
        if repeat_count >= MAX_IDENTICAL_DECISIONS and tool_name != "task_complete":
            aborted_by_repetition = True
            step_record["result"] = {
                "status": "aborted",
                "phase": "repetition_loop",
                "error": (f"identical decision repeated "
                          f"{repeat_count} times: {decision_key}"),
            }
            step_record["result_status"] = "aborted"
            trace.append(step_record)
            break

        # Action-space restriction — reject without dispatching.
        if allowed_tools is not None and tool_name not in allowed_tools \
                and tool_name not in SPECIAL_SIGNALS:
            step_record["result"] = {"status": "rejected",
                                     "reason": "tool_not_allowed"}
            step_record["result_status"] = "rejected"
            trace.append(step_record)
            history.append({
                "role": "user",
                "content": (f"Observation: tool '{tool_name}' is NOT available "
                            f"in this experiment. You may ONLY use: "
                            f"{', '.join(sorted(allowed_tools))} — plus "
                            f"'task_complete' when the SCENE GRAPH shows the "
                            f"task is fully done. Choose again."),
            })
            continue

        if tool_name == "task_complete":
            terminated_by_task_complete = True
            step_record["result"] = {"status": "ok", "tool": "task_complete"}
            step_record["result_status"] = "ok"
            step_record["tool_wall_s"] = 0.0
            trace.append(step_record)
            break

        if tool_name == "request_rescan":
            step_record["result"] = {"status": "skipped", "reason": "request_rescan"}
            step_record["result_status"] = "skipped"
            trace.append(step_record)
            history.append({
                "role": "user",
                "content": "Observation: rescan noted; the SCENE GRAPH in the "
                           "system prompt is current. Choose the next action.",
            })
            continue

        # Offset-reuse guard — two place_label_and_move calls with the same
        # direction+amount stack their shapes at the same point (the #1
        # layout bug). Reject before dispatch and suggest free offsets.
        if tool_name == "place_label_and_move":
            key = _offset_key(params)
            if key is not None and key in used_offsets:
                free = [f"{d} {a}" for d, a in OFFSET_PALETTE
                        if (d, a) not in used_offsets][:6]
                step_record["result"] = {"status": "rejected",
                                         "reason": "offset_already_used",
                                         "offset": list(key),
                                         "used_by": used_offsets[key]}
                step_record["result_status"] = "rejected"
                trace.append(step_record)
                history.append({
                    "role": "user",
                    "content": (f"Observation: REJECTED — offset "
                                f"'{key[0]} {key[1]}' was already used for "
                                f"shape '{used_offsets[key]}'. Reusing it "
                                f"would stack both shapes at the same spot. "
                                f"Nothing was placed. Re-place "
                                f"'{params.get('label')}' with an UNUSED "
                                f"direction/amount, e.g.: {', '.join(free)}."),
                })
                continue

        # Drop params the tool does not declare (models occasionally invent
        # extras like connect_shapes(auto=true), which would raise TypeError).
        node = TOOL_CATALOG.get(tool_name)
        if node is not None and isinstance(params, dict):
            unknown_params = [k for k in params if k not in node.params]
            if unknown_params:
                params = {k: v for k, v in params.items() if k in node.params}
                step_record["dropped_params"] = unknown_params

        tool_start = time.perf_counter()
        if args.dry_run:
            result = {"status": "dry_run", "tool": tool_name}
        else:
            try:
                result = dispatch(tool_name, params, ui_graph=graph)
            except Exception as exc:
                result = {
                    "status": "error",
                    "phase": "dispatch",
                    "tool": tool_name,
                    "error": str(exc),
                }
        step_tool_s = time.perf_counter() - tool_start
        tool_wall_s += step_tool_s

        step_record["result"] = result
        step_record["result_status"] = result.get("status")
        step_record["tool_wall_s"] = step_tool_s
        trace.append(step_record)

        if result.get("status") == "error":
            # ReAct error feedback: report the failure and let the model
            # correct itself, up to MAX_CONSECUTIVE_ERRORS in a row.
            tool_error_count += 1
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                aborted_by_errors = True
                break
            history.append({
                "role": "user",
                "content": (f"Observation: tool '{tool_name}' FAILED with "
                            f"error: {result.get('error')}. The canvas did "
                            f"NOT change. Fix the params (or pick a different "
                            f"action) and try again."),
            })
            continue

        consecutive_errors = 0
        if tool_name == "place_label_and_move":
            key = _offset_key(params)
            if key is not None:
                used_offsets[key] = str(params.get("label", ""))
        observation = f"Observation: tool '{tool_name}' -> {result.get('status')}"
        observation += (". The SCENE GRAPH in the system prompt reflects the "
                        "updated canvas. Choose the next action, or "
                        "'task_complete' if the task is fully done.")
        history.append({"role": "user", "content": observation})

        if cooldown:
            time.sleep(cooldown)
    else:
        max_steps_reached = True

    final_graph = graph.get("scene_graph") or sg.load()
    checks = _final_checks(final_graph, task_def["labels"], task_def["edges"])
    success = bool(checks["labels_ok"] and checks["edges_ok"]
                   and checks["no_obvious_overlap"])
    failure = _failure_type(
        terminated_by_task_complete=terminated_by_task_complete,
        final_checks=checks,
        trace=trace,
        max_steps_reached=max_steps_reached,
    )
    if not success and aborted_by_repetition:
        failure = "model_repetition_loop"
    elif not success and aborted_by_errors:
        failure = "model_unrecoverable_errors"

    final_screenshot = None
    final_screenshot_error = None
    if not args.skip_final_screenshot and not args.dry_run:
        final_name = f"react_{args.task_id}_{condition}_rep{args.rep:02d}_final.png"
        try:
            final_screenshot = screenshot(final_name)
        except Exception as exc:
            final_screenshot_error = str(exc)

    ended_at = _now_utc()
    total_wall_s = time.perf_counter() - total_start
    model_cfg = config.executor_model_config()

    record: Dict[str, Any] = {
        "agent": "react",
        "task_id": args.task_id,
        "task": task_def["task"],
        "condition": condition,
        "input_mode": {
            "initial_screenshot_only": not per_step_screenshot,
            "per_step_screenshot": per_step_screenshot,
        },
        "rep": args.rep,
        "branch": _git_value("branch", "--show-current"),
        "commit": _git_value("rev-parse", "HEAD"),
        "model": {
            "executor": model_cfg.model,
            "provider": model_cfg.provider,
            "temperature": model_cfg.temperature,
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "total_wall_s": total_wall_s,
        "success": success,
        "failure_type": failure,
        "terminated_by_task_complete": terminated_by_task_complete,
        "max_steps_reached": max_steps_reached,
        "aborted_by_repetition": aborted_by_repetition,
        "aborted_by_errors": aborted_by_errors,
        "parse_error_count": parse_error_count,
        "tool_error_count": tool_error_count,
        "allowed_tools": sorted(allowed_tools) if allowed_tools else None,
        "turns": len(trace),
        "llm_calls": llm_calls,
        "llm_wall_s": llm_wall_s,
        "tool_wall_s": tool_wall_s,
        "usage_total": usage_total or None,
        "prompt_tokens": usage_total.get("prompt_tokens"),
        "completion_tokens": usage_total.get("completion_tokens"),
        "total_tokens": usage_total.get("total_tokens"),
        "usage_missing_calls": usage_missing_calls,
        "screenshot_input_count": screenshot_input_count,
        "initial_screenshot": initial_screenshot,
        "initial_screenshot_error": initial_screenshot_error,
        "final_screenshot": final_screenshot,
        "final_screenshot_error": final_screenshot_error,
        "env_reset": reset_report,
        "final_scene_graph": final_graph,
        "final_summary": sg.summary_for_prompt(final_graph),
        "trace": trace,
        "final_checks": checks,
        "notes": args.notes,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = (
        f"{stamp}_react_{_safe_name(args.task_id)}_{_safe_name(condition)}_"
        f"rep{args.rep:02d}.json"
    )
    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False, default=str)

    tokens = usage_total.get("total_tokens")
    print(f"Wrote {out_path}")
    print(f"success={success} turns={len(trace)} llm_calls={llm_calls} "
          f"total_tokens={tokens if tokens is not None else 'n/a'} "
          f"total_wall_s={total_wall_s:.2f}")
    return record


def run(args: argparse.Namespace) -> Dict[str, Any]:
    if args.reset_only:
        graph = config.ui_graph()
        graph["scene_graph"] = sg.load()
        report = reset_environment(
            graph,
            countdown_seconds=args.countdown,
            reload_page=args.reload_page,
            reload_settle_s=args.reload_settle,
        )
        print("reset_only:", json.dumps(report, indent=2))
        return {"status": "ok", "reset_only": True, "env_reset": report}
    return run_react(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", choices=sorted(TASKS))
    parser.add_argument("--condition", choices=CONDITIONS)
    parser.add_argument("--rep", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--out", default=os.path.join("logs", "react_ablation"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Ask the model but do not dispatch tools.")
    parser.add_argument("--allowed-tools",
                        default="place_label_and_move,connect_shapes",
                        help="Comma-separated tool whitelist shown to the model "
                             "(task_complete is always available). Pass 'all' "
                             "for the unrestricted catalog.")
    parser.add_argument("--no-reset-env", dest="reset_env", action="store_false",
                        help="Skip the canvas/viewport reset (scene graph still "
                             "resets).")
    parser.set_defaults(reset_env=True)
    parser.add_argument("--reload-page", action="store_true",
                        help="Reload the draw.io tab before the run (chrome_cdp "
                             "only). Normally unnecessary: the viewport reset "
                             "already restores zoom/scroll deterministically.")
    parser.add_argument("--reload-settle", type=float, default=6.0,
                        help="Seconds to wait after a page reload.")
    parser.add_argument("--reset-only", action="store_true",
                        help="Reset canvas/viewport/scene graph, then exit.")
    parser.add_argument("--countdown", type=int, default=config.countdown_seconds())
    parser.add_argument("--skip-final-screenshot", action="store_true")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    if not args.reset_only and (not args.task_id or not args.condition):
        parser.error("--task-id and --condition are required unless --reset-only")
    return args


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
