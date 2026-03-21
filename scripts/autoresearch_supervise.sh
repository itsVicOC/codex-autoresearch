#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(pwd)"
PROMPT=""
PROMPT_FILE=""
RESULTS_PATH="research-results.tsv"
STATE_PATH=""
SLEEP_SECONDS=5
MAX_STAGNATION=3
CODEX_BIN="codex"
CODEX_ARGS=(--full-auto)

usage() {
  cat <<'EOF'
Usage: autoresearch_supervise.sh [options]

Run Codex in fresh-session loops and decide whether to relaunch based on
research-results.tsv + autoresearch-state.json instead of blindly restarting.
This script is intended to be launched by an outer shell / tmux / CI job.

Options:
  --repo PATH             Repo root to run in (default: current working directory)
  --prompt TEXT           Prompt text to send to Codex
  --prompt-file PATH      Read prompt text from a file
  --results-path PATH     Results log path relative to repo (default: research-results.tsv)
  --state-path PATH       Explicit state JSON path (optional)
  --sleep-seconds N       Delay between relaunches (default: 5)
  --max-stagnation N      Consecutive no-progress exits tolerated (default: 3)
  --codex-bin PATH        Codex binary to invoke (default: codex)
  --codex-arg ARG         Extra argument passed through to Codex (repeatable)
  -h, --help              Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    --prompt-file)
      PROMPT_FILE="$2"
      shift 2
      ;;
    --results-path)
      RESULTS_PATH="$2"
      shift 2
      ;;
    --state-path)
      STATE_PATH="$2"
      shift 2
      ;;
    --sleep-seconds)
      SLEEP_SECONDS="$2"
      shift 2
      ;;
    --max-stagnation)
      MAX_STAGNATION="$2"
      shift 2
      ;;
    --codex-bin)
      CODEX_BIN="$2"
      shift 2
      ;;
    --codex-arg)
      CODEX_ARGS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$PROMPT" && -n "$PROMPT_FILE" ]]; then
  echo "Provide either --prompt or --prompt-file, not both." >&2
  exit 2
fi

if [[ -z "$PROMPT" && -z "$PROMPT_FILE" ]]; then
  echo "One of --prompt or --prompt-file is required." >&2
  exit 2
fi

if [[ -n "$PROMPT_FILE" && ! -f "$PROMPT_FILE" ]]; then
  echo "Prompt file not found: $PROMPT_FILE" >&2
  exit 2
fi

if ! [[ "$SLEEP_SECONDS" =~ ^[0-9]+$ ]]; then
  echo "--sleep-seconds must be a non-negative integer." >&2
  exit 2
fi

if ! [[ "$MAX_STAGNATION" =~ ^[0-9]+$ ]] || [[ "$MAX_STAGNATION" -lt 1 ]]; then
  echo "--max-stagnation must be an integer >= 1." >&2
  exit 2
fi

REPO="$(cd "$REPO" && pwd)"
if [[ -n "$PROMPT_FILE" ]]; then
  PROMPT_FILE="$(cd "$(dirname "$PROMPT_FILE")" && pwd)/$(basename "$PROMPT_FILE")"
fi

load_prompt() {
  if [[ -n "$PROMPT_FILE" ]]; then
    cat "$PROMPT_FILE"
  else
    printf '%s' "$PROMPT"
  fi
}

json_field() {
  local field="$1"
  python3 -c '
import json
import sys

field = sys.argv[1]
payload = json.load(sys.stdin)
value = payload.get(field, "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
  ' "$field"
}

loop_count=0

while true; do
  loop_count=$((loop_count + 1))
  echo
  echo "==============================================================="
  echo "  Autoresearch Supervisor Loop $loop_count"
  echo "==============================================================="

  prompt_text="$(load_prompt)"
  codex_cmd=("$CODEX_BIN" "${CODEX_ARGS[@]}" -C "$REPO" "$prompt_text")

  set +e
  "${codex_cmd[@]}"
  codex_exit=$?
  set -e

  status_cmd=(
    python3
    "$SCRIPT_DIR/autoresearch_supervisor_status.py"
    --results-path
    "$RESULTS_PATH"
    --after-run
    --write-state
    --max-stagnation
    "$MAX_STAGNATION"
  )
  if [[ -n "$STATE_PATH" ]]; then
    status_cmd+=(--state-path "$STATE_PATH")
  fi

  set +e
  status_output="$(cd "$REPO" && "${status_cmd[@]}" 2>&1)"
  status_exit=$?
  set -e

  if [[ $status_exit -ne 0 ]]; then
    echo "Supervisor status check failed after Codex exit code $codex_exit:" >&2
    echo "$status_output" >&2
    exit 2
  fi

  decision="$(printf '%s' "$status_output" | json_field decision)"
  reason="$(printf '%s' "$status_output" | json_field reason)"
  stagnation_count="$(printf '%s' "$status_output" | json_field stagnation_count)"
  restart_count="$(printf '%s' "$status_output" | json_field restart_count)"

  echo "Supervisor decision: $decision (reason: $reason, codex_exit=$codex_exit, restarts=$restart_count, stagnation=$stagnation_count)"

  case "$decision" in
    relaunch)
      sleep "$SLEEP_SECONDS"
      ;;
    stop)
      exit 0
      ;;
    needs_human)
      exit 2
      ;;
    *)
      echo "Unknown supervisor decision: $decision" >&2
      exit 2
      ;;
  esac
done
