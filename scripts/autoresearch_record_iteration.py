#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from autoresearch_helpers import (
    AutoresearchError,
    append_rows,
    build_state_payload,
    clone_state_payload,
    decimal_to_json_number,
    improvement,
    make_row,
    parse_decimal,
    parse_results_log,
    require_consistent_state,
    resolve_state_path_for_log,
    write_json_atomic,
)


STATUSES = ["keep", "discard", "crash", "no-op", "blocked", "drift", "refine", "pivot", "search", "split"]
TRIAL_COMMIT_STATUSES = {"keep", "discard", "crash"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append one main iteration row and atomically update autoresearch-state.json."
    )
    parser.add_argument("--results-path", default="research-results.tsv")
    parser.add_argument(
        "--state-path",
        help=(
            "State JSON path. Defaults to autoresearch-state.json, except logs tagged "
            "with '# mode: exec' default to the deterministic exec scratch state."
        ),
    )
    parser.add_argument("--status", required=True, choices=STATUSES)
    parser.add_argument("--metric")
    parser.add_argument("--commit", default="-")
    parser.add_argument("--guard", default="-")
    parser.add_argument("--description", required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    results_path = Path(args.results_path)
    parsed = parse_results_log(results_path)
    state_path = resolve_state_path_for_log(args.state_path, parsed)
    parsed, payload, reconstructed, direction = require_consistent_state(
        results_path,
        state_path,
        parsed=parsed,
    )
    next_iteration = reconstructed["iteration"] + 1
    current_metric = reconstructed["current_metric"]

    if args.status in {"crash", "no-op", "blocked", "refine", "pivot", "search"}:
        metric = current_metric if args.metric is None else parse_decimal(args.metric, "metric")
    else:
        if args.metric is None:
            raise AutoresearchError(f"--metric is required for status {args.status}")
        metric = parse_decimal(args.metric, "metric")

    requires_trial_commit = args.status in TRIAL_COMMIT_STATUSES or (
        args.status == "refine" and (args.metric is not None or args.guard != "-")
    )
    if requires_trial_commit and args.commit == "-":
        raise AutoresearchError(
            f"Status {args.status} must provide --commit to preserve trial provenance."
        )
    if args.status == "keep" and not improvement(metric, current_metric, direction):
        raise AutoresearchError("Keep iterations must improve over the retained metric.")

    new_row = make_row(
        iteration=str(next_iteration),
        commit=args.commit,
        metric=metric,
        delta=metric - current_metric,
        guard=args.guard,
        status=args.status,
        description=args.description,
    )
    append_rows(results_path, [new_row])

    new_payload = clone_state_payload(payload)
    state = new_payload["state"]
    state["iteration"] = next_iteration
    state["last_status"] = args.status
    state["last_trial_commit"] = args.commit
    state["last_trial_metric"] = decimal_to_json_number(metric)

    if args.status == "keep":
        state["keeps"] = state.get("keeps", 0) + 1
        state["current_metric"] = decimal_to_json_number(metric)
        state["last_commit"] = args.commit
        state["consecutive_discards"] = 0
        state["pivot_count"] = 0
        previous_best = parse_decimal(state["best_metric"], "best_metric")
        if improvement(metric, previous_best, direction):
            state["best_metric"] = decimal_to_json_number(metric)
            state["best_iteration"] = next_iteration
    elif args.status == "discard":
        state["discards"] = state.get("discards", 0) + 1
        state["consecutive_discards"] = state.get("consecutive_discards", 0) + 1
    elif args.status == "crash":
        state["crashes"] = state.get("crashes", 0) + 1
        state["consecutive_discards"] = state.get("consecutive_discards", 0) + 1
    elif args.status == "no-op":
        state["no_ops"] = state.get("no_ops", 0) + 1
        state["consecutive_discards"] = state.get("consecutive_discards", 0) + 1
    elif args.status == "blocked":
        state["blocked"] = state.get("blocked", 0) + 1
    elif args.status == "drift":
        state["current_metric"] = decimal_to_json_number(metric)
        if args.commit != "-":
            state["last_commit"] = args.commit
        state["consecutive_discards"] = 0
        previous_best = parse_decimal(state["best_metric"], "best_metric")
        if improvement(metric, previous_best, direction):
            state["best_metric"] = decimal_to_json_number(metric)
            state["best_iteration"] = next_iteration
    elif args.status == "pivot":
        state["pivot_count"] = state.get("pivot_count", 0) + 1
    elif args.status == "split":
        state["splits"] = state.get("splits", 0) + 1

    rewritten_summary = {
        "iteration": state["iteration"],
        "baseline_metric": parse_decimal(state["baseline_metric"], "baseline_metric"),
        "best_metric": parse_decimal(state["best_metric"], "best_metric"),
        "best_iteration": state["best_iteration"],
        "current_metric": parse_decimal(state["current_metric"], "current_metric"),
        "last_commit": state["last_commit"],
        "last_trial_commit": state["last_trial_commit"],
        "last_trial_metric": parse_decimal(state["last_trial_metric"], "last_trial_metric"),
        "keeps": state["keeps"],
        "discards": state["discards"],
        "crashes": state["crashes"],
        "no_ops": state.get("no_ops", 0),
        "blocked": state.get("blocked", 0),
        "splits": state.get("splits", 0),
        "consecutive_discards": state["consecutive_discards"],
        "pivot_count": state["pivot_count"],
        "last_status": state["last_status"],
    }
    final_payload = build_state_payload(
        mode=new_payload["mode"],
        run_tag=new_payload.get("run_tag") or None,
        config=new_payload["config"],
        summary=rewritten_summary,
        supervisor=new_payload.get("supervisor"),
    )
    write_json_atomic(state_path, final_payload)

    print(
        json.dumps(
            {
                "iteration": next_iteration,
                "status": args.status,
                "retained_metric": state["current_metric"],
                "trial_metric": state["last_trial_metric"],
                "results_path": str(results_path),
                "state_path": str(state_path),
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
