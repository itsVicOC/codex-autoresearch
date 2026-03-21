#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from autoresearch_helpers import (
    AutoresearchError,
    compare_summary_to_state,
    decimal_to_json_number,
    parse_results_log,
    read_state_payload,
    resolve_state_path_for_log,
    utc_now,
    write_json_atomic,
    log_summary,
)


RELAUNCH = "relaunch"
STOP = "stop"
NEEDS_HUMAN = "needs_human"
VALID_DECISIONS = {RELAUNCH, STOP, NEEDS_HUMAN}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide whether an external autoresearch supervisor should relaunch Codex, stop, or ask for human help."
    )
    parser.add_argument("--results-path", default="research-results.tsv")
    parser.add_argument(
        "--state-path",
        help=(
            "State JSON path. Defaults to autoresearch-state.json, except logs tagged "
            "with '# mode: exec' default to the deterministic exec scratch state."
        ),
    )
    parser.add_argument(
        "--max-stagnation",
        type=int,
        default=3,
        help="Consecutive no-progress exits tolerated before returning needs_human.",
    )
    parser.add_argument(
        "--after-run",
        action="store_true",
        help="Indicates this check is happening after a Codex run finished; increments restart accounting.",
    )
    parser.add_argument(
        "--write-state",
        action="store_true",
        help="Persist the computed supervisor metadata back into autoresearch-state.json.",
    )
    return parser


def as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return default


def progress_signature(payload: dict[str, Any]) -> str:
    state = payload.get("state", {})
    signature = {
        "iteration": state.get("iteration"),
        "last_status": state.get("last_status"),
        "last_trial_commit": state.get("last_trial_commit"),
        "last_trial_metric": state.get("last_trial_metric"),
        "updated_at": payload.get("updated_at"),
    }
    return json.dumps(signature, sort_keys=True, separators=(",", ":"))


def determine_base_decision(payload: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    reasons: list[str] = []
    mode = payload.get("mode")
    config = payload.get("config", {})
    state = payload.get("state", {})
    last_status = state.get("last_status")
    iteration = as_int(state.get("iteration"))
    iterations_cap = config.get("iterations")

    if mode == "exec":
        reasons.append("Exec mode is one-shot and should not be relaunched automatically.")
        return STOP, "exec_mode_completed", "exec_complete", reasons

    if last_status == "blocked":
        reasons.append("Last recorded status is blocked; unattended relaunch would likely spin without progress.")
        return NEEDS_HUMAN, "blocked", "terminal", reasons

    if isinstance(iterations_cap, int) and iterations_cap >= 0 and iteration >= iterations_cap:
        reasons.append(
            f"Configured iteration cap reached ({iteration} >= {iterations_cap})."
        )
        return STOP, "iteration_cap_reached", "terminal", reasons

    if last_status == "split":
        reasons.append("Last recorded status is split; restart is the expected continuation path.")
        return RELAUNCH, "session_split", "session_split", reasons

    reasons.append(
        f"Last recorded status is {last_status!r}; the loop remains resumable and should continue in a fresh Codex session."
    )
    return RELAUNCH, "none", "turn_complete", reasons


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_stagnation < 1:
        raise SystemExit("error: --max-stagnation must be at least 1")

    results_path = Path(args.results_path)
    parsed = parse_results_log(results_path)
    state_path = resolve_state_path_for_log(args.state_path, parsed)
    payload = read_state_payload(state_path)

    direction = payload.get("config", {}).get("direction")
    if direction not in {"lower", "higher"}:
        raise AutoresearchError("State config.direction must be 'lower' or 'higher'.")

    reconstructed = log_summary(parsed, direction)
    mismatches = compare_summary_to_state(reconstructed, payload)

    observed_at = utc_now()
    previous_supervisor = payload.get("supervisor", {})
    if not isinstance(previous_supervisor, dict):
        previous_supervisor = {}

    signature = progress_signature(payload)
    previous_signature = previous_supervisor.get("last_observed_signature")
    same_signature = previous_signature == signature

    restart_count = as_int(previous_supervisor.get("restart_count"))
    if args.after_run:
        restart_count += 1

    previous_stagnation = as_int(previous_supervisor.get("stagnation_count"))
    if args.after_run and same_signature:
        stagnation_count = previous_stagnation + 1
    elif same_signature:
        stagnation_count = previous_stagnation
    else:
        stagnation_count = 0

    if mismatches:
        decision = NEEDS_HUMAN
        reason = "state_inconsistent"
        exit_kind = "state_inconsistent"
        reasons = [
            "Results log and JSON state diverged; unattended relaunch is unsafe.",
            *mismatches,
        ]
    else:
        decision, reason, exit_kind, reasons = determine_base_decision(payload)

    if decision == RELAUNCH and stagnation_count >= args.max_stagnation:
        decision = NEEDS_HUMAN
        reason = "stagnated"
        exit_kind = "state_inconsistent"
        reasons.append(
            f"No progress signature change across {stagnation_count} consecutive supervised exits."
        )

    if decision not in VALID_DECISIONS:
        raise AutoresearchError(f"Internal error: unsupported supervisor decision {decision!r}")

    supervisor = {
        "recommended_action": decision,
        "should_continue": decision == RELAUNCH,
        "terminal_reason": "none" if decision == RELAUNCH else reason,
        "last_exit_kind": exit_kind,
        "last_turn_finished_at": observed_at,
        "last_observed_signature": signature,
        "last_observed_iteration": payload["state"]["iteration"],
        "last_observed_status": payload["state"]["last_status"],
        "last_observed_updated_at": payload.get("updated_at"),
        "last_observed_metric": decimal_to_json_number(reconstructed["current_metric"]),
        "restart_count": restart_count,
        "stagnation_count": stagnation_count,
        "last_reason": reasons[0] if reasons else "",
    }

    if args.write_state:
        new_payload = dict(payload)
        new_payload["supervisor"] = supervisor
        write_json_atomic(state_path, new_payload)

    print(
        json.dumps(
            {
                "decision": decision,
                "reason": reason,
                "reasons": reasons,
                "results_path": str(results_path),
                "state_path": str(state_path),
                "mode": payload.get("mode"),
                "iteration": payload["state"]["iteration"],
                "last_status": payload["state"]["last_status"],
                "restart_count": restart_count,
                "stagnation_count": stagnation_count,
                "supervisor_state_written": args.write_state,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AutoresearchError as exc:
        raise SystemExit(f"error: {exc}")
