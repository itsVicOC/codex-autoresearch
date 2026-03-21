from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


class AutoresearchScriptsTest(unittest.TestCase):
    maxDiff = None

    def run_script_completed(
        self, script_name: str, *args: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / script_name), *args],
            capture_output=True,
            text=True,
            cwd=cwd,
        )

    def run_script(
        self, script_name: str, *args: str, cwd: Path | None = None
    ) -> dict[str, object]:
        completed = self.run_script_completed(script_name, *args, cwd=cwd)
        completed.check_returncode()
        return json.loads(completed.stdout)

    def run_script_text(
        self, script_name: str, *args: str, cwd: Path | None = None
    ) -> str:
        completed = self.run_script_completed(script_name, *args, cwd=cwd)
        completed.check_returncode()
        return completed.stdout.strip()

    def test_init_and_serial_iteration_state_is_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "discard",
                "--metric",
                "12",
                "--commit",
                "deadbee",
                "--description",
                "worse attempt",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "keep",
                "--metric",
                "8",
                "--commit",
                "b2c3d4e",
                "--guard",
                "pass",
                "--description",
                "better attempt",
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["iteration"], 2)
            self.assertEqual(state["state"]["current_metric"], 8)
            self.assertEqual(state["state"]["best_metric"], 8)
            self.assertEqual(state["state"]["best_iteration"], 2)
            self.assertEqual(state["state"]["keeps"], 1)
            self.assertEqual(state["state"]["discards"], 1)
            self.assertEqual(state["state"]["last_commit"], "b2c3d4e")
            self.assertEqual(state["state"]["last_trial_metric"], 8)

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(resume["decision"], "full_resume")
            self.assertEqual(resume["tsv_summary"]["iteration"], 2)

    def test_discard_requires_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            completed = self.run_script_completed(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "discard",
                "--metric",
                "12",
                "--description",
                "worse attempt without commit",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Status discard must provide --commit", completed.stderr)

    def test_crash_requires_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            completed = self.run_script_completed(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "crash",
                "--description",
                "verification crashed before metric extraction",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Status crash must provide --commit", completed.stderr)

    def test_strategy_only_refine_can_omit_commit_but_measured_refine_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "refine",
                "--description",
                "switch strategy family without testing a committed diff",
            )

            completed = self.run_script_completed(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "refine",
                "--metric",
                "9",
                "--guard",
                "pass",
                "--description",
                "measured refine without commit",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Status refine must provide --commit", completed.stderr)

    def test_parallel_batch_selects_best_worker_and_appends_main_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"
            batch_path = tmpdir / "batch.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                "--parallel-mode",
                "parallel",
            )
            batch_path.write_text(
                json.dumps(
                    [
                        {
                            "worker_id": "a",
                            "commit": "c3d4e5f",
                            "metric": 7,
                            "guard": "pass",
                            "description": "narrowed hot path",
                            "diff_size": 12,
                        },
                        {
                            "worker_id": "b",
                            "commit": "d4e5f6a",
                            "metric": 9,
                            "guard": "pass",
                            "description": "wrapper experiment",
                            "diff_size": 4,
                        },
                        {
                            "worker_id": "c",
                            "status": "crash",
                            "description": "timeout after 20m",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = self.run_script(
                "autoresearch_select_parallel_batch.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--batch-file",
                str(batch_path),
            )
            self.assertEqual(result["selected_worker"], "a")
            self.assertEqual(result["status"], "keep")

            log_text = results_path.read_text(encoding="utf-8")
            self.assertIn("1a\tc3d4e5f\t7\t-3\tpass\tkeep", log_text)
            self.assertIn("1b\t-\t9\t-1\tpass\tdiscard", log_text)
            self.assertIn("1c\t-\t10\t0\t-\tcrash", log_text)
            self.assertIn("1\tc3d4e5f\t7\t-3\tpass\tkeep\t[PARALLEL batch] selected worker-a", log_text)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["iteration"], 1)
            self.assertEqual(state["state"]["current_metric"], 7)

    def test_resume_check_can_rebuild_missing_state_from_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "keep",
                "--metric",
                "8",
                "--commit",
                "b2c3d4e",
                "--guard",
                "pass",
                "--description",
                "better attempt",
            )
            state_path.unlink()

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--write-repaired-state",
            )
            self.assertEqual(resume["decision"], "tsv_fallback")
            self.assertTrue(resume["repaired_state"])

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["config"], {"direction": "lower"})
            self.assertEqual(state["state"]["iteration"], 1)
            self.assertEqual(state["state"]["current_metric"], 8)

            second_resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(second_resume["decision"], "mini_wizard")
            self.assertTrue(
                any("config is missing required resume fields" in reason for reason in second_resume["reasons"])
            )

    def test_resume_check_detects_json_tsv_divergence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["state"]["current_metric"] = 999
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(resume["decision"], "mini_wizard")
            self.assertTrue(any("current_metric" in reason for reason in resume["reasons"]))

    def test_resume_check_ignores_stale_exec_scratch_for_fresh_interactive_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            scratch_state_path = Path(
                self.run_script_text(
                    "autoresearch_exec_state.py",
                    "--repo-root",
                    str(repo),
                )
            )
            scratch_state_path.parent.mkdir(parents=True, exist_ok=True)
            scratch_state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mode": "exec",
                        "config": {"direction": "lower"},
                        "state": {
                            "iteration": 3,
                            "baseline_metric": 10,
                            "best_metric": 7,
                            "best_iteration": 2,
                            "current_metric": 7,
                            "last_commit": "keep123",
                            "last_trial_commit": "keep123",
                            "last_trial_metric": 7,
                            "keeps": 1,
                            "discards": 2,
                            "crashes": 0,
                            "no_ops": 0,
                            "blocked": 0,
                            "splits": 0,
                            "consecutive_discards": 0,
                            "pivot_count": 0,
                            "last_status": "keep",
                        },
                    }
                ),
                encoding="utf-8",
            )

            resume = self.run_script("autoresearch_resume_check.py", cwd=repo)
            self.assertEqual(resume["decision"], "fresh_start")
            self.assertEqual(resume["state_path"], "autoresearch-state.json")

    def test_resume_check_treats_incomplete_json_state_as_unusable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            results_path.write_text(
                "\n".join(
                    [
                        "# metric_direction: lower",
                        "iteration\tcommit\tmetric\tdelta\tguard\tstatus\tdescription",
                        "0\tbase123\t10\t0\t-\tbaseline\tbaseline score",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mode": "loop",
                        "config": {"direction": "lower"},
                        "state": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(resume["decision"], "tsv_fallback")
            self.assertTrue(any("missing state fields" in reason for reason in resume["reasons"]))

    def test_resume_check_rejects_missing_main_iteration_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            results_path.write_text(
                "\n".join(
                    [
                        "# metric_direction: lower",
                        "iteration\tcommit\tmetric\tdelta\tguard\tstatus\tdescription",
                        "0\tbase123\t10\t0\t-\tbaseline\tbaseline score",
                        "2\tkeep123\t8\t-2\tpass\tkeep\tjumped iteration",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mode": "loop",
                        "config": {"direction": "lower"},
                        "state": {
                            "iteration": 2,
                            "baseline_metric": 10,
                            "best_metric": 8,
                            "best_iteration": 2,
                            "current_metric": 8,
                            "last_commit": "keep123",
                            "last_trial_commit": "keep123",
                            "last_trial_metric": 8,
                            "keeps": 1,
                            "discards": 0,
                            "crashes": 0,
                            "no_ops": 0,
                            "blocked": 0,
                            "splits": 0,
                            "consecutive_discards": 0,
                            "pivot_count": 0,
                            "last_status": "keep",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(resume["decision"], "mini_wizard")
            self.assertTrue(any("expected 1, got 2" in reason for reason in resume["reasons"]))

    def test_resume_check_keeps_json_path_when_tsv_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            results_path.unlink()

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
            )
            self.assertEqual(resume["decision"], "mini_wizard")
            self.assertTrue(any("results log is missing" in reason for reason in resume["reasons"]))

    def test_exec_mode_uses_scratch_state_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            repo_state_path = tmpdir / "autoresearch-state.json"
            scratch_state_path = Path(
                self.run_script_text(
                    "autoresearch_exec_state.py",
                    "--repo-root",
                    str(tmpdir),
                )
            )

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--mode",
                "exec",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                cwd=tmpdir,
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--status",
                "keep",
                "--metric",
                "8",
                "--commit",
                "b2c3d4e",
                "--guard",
                "pass",
                "--description",
                "better attempt",
                cwd=tmpdir,
            )

            self.assertFalse(repo_state_path.exists())
            self.assertTrue(scratch_state_path.exists())

            state = json.loads(scratch_state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "exec")
            self.assertEqual(state["state"]["iteration"], 1)
            self.assertEqual(state["state"]["current_metric"], 8)

            cleanup = self.run_script(
                "autoresearch_exec_state.py",
                "--repo-root",
                str(tmpdir),
                "--cleanup",
                "--json",
            )
            self.assertTrue(cleanup["removed"])
            self.assertEqual(cleanup["state_path"], str(scratch_state_path))
            self.assertFalse(scratch_state_path.exists())

    def test_resume_check_defaults_to_exec_scratch_when_log_declares_exec_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            scratch_state_path = Path(
                self.run_script_text(
                    "autoresearch_exec_state.py",
                    "--repo-root",
                    str(tmpdir),
                )
            )

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--mode",
                "exec",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                cwd=tmpdir,
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--status",
                "keep",
                "--metric",
                "8",
                "--commit",
                "b2c3d4e",
                "--guard",
                "pass",
                "--description",
                "better attempt",
                cwd=tmpdir,
            )

            resume = self.run_script(
                "autoresearch_resume_check.py",
                "--results-path",
                str(results_path),
                cwd=tmpdir,
            )
            self.assertEqual(resume["decision"], "full_resume")
            self.assertEqual(resume["state_path"], str(scratch_state_path))

    def test_exec_init_run_clears_stale_default_scratch_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git").mkdir()
            scratch_state_path = Path(
                self.run_script_text(
                    "autoresearch_exec_state.py",
                    "--repo-root",
                    str(repo),
                )
            )
            scratch_state_path.parent.mkdir(parents=True, exist_ok=True)
            scratch_state_path.write_text('{"stale": true}\n', encoding="utf-8")

            result = self.run_script(
                "autoresearch_init_run.py",
                "--mode",
                "exec",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                cwd=repo,
            )

            self.assertEqual(result["state_path"], str(scratch_state_path))
            state = json.loads(scratch_state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "exec")
            self.assertEqual(state["config"]["goal"], "Reduce failures")
            self.assertFalse(state.get("stale", False))

    def test_record_iteration_does_not_use_exec_scratch_for_loop_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            scratch_state_path = Path(
                self.run_script_text(
                    "autoresearch_exec_state.py",
                    "--repo-root",
                    str(tmpdir),
                )
            )

            results_path.write_text(
                "\n".join(
                    [
                        "# metric_direction: lower",
                        "# mode: loop",
                        "iteration\tcommit\tmetric\tdelta\tguard\tstatus\tdescription",
                        "0\tbase123\t10\t0\t-\tbaseline\tbaseline score",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            scratch_state_path.parent.mkdir(parents=True, exist_ok=True)
            scratch_state_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mode": "exec",
                        "config": {
                            "goal": "Reduce failures",
                            "scope": "src/**/*.py",
                            "metric": "failure count",
                            "direction": "lower",
                            "verify": "pytest -q",
                            "guard": None,
                        },
                        "state": {
                            "iteration": 0,
                            "baseline_metric": 10,
                            "best_metric": 10,
                            "best_iteration": 0,
                            "current_metric": 10,
                            "last_commit": "base123",
                            "last_trial_commit": "base123",
                            "last_trial_metric": 10,
                            "keeps": 0,
                            "discards": 0,
                            "crashes": 0,
                            "no_ops": 0,
                            "blocked": 0,
                            "splits": 0,
                            "consecutive_discards": 0,
                            "pivot_count": 0,
                            "last_status": "baseline",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            completed = self.run_script_completed(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--status",
                "discard",
                "--metric",
                "12",
                "--commit",
                "deadbee",
                "--description",
                "worse attempt",
                cwd=tmpdir,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Missing JSON file", completed.stderr)

    def test_parallel_batch_uses_best_discarded_attempt_when_nothing_keeps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"
            batch_path = tmpdir / "batch.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                "--parallel-mode",
                "parallel",
            )
            batch_path.write_text(
                json.dumps(
                    [
                        {
                            "worker_id": "a",
                            "commit": "c3d4e5f",
                            "metric": 12,
                            "guard": "pass",
                            "description": "worse attempt",
                        },
                        {
                            "worker_id": "b",
                            "commit": "d4e5f6a",
                            "metric": 11,
                            "guard": "pass",
                            "description": "closer miss",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = self.run_script(
                "autoresearch_select_parallel_batch.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--batch-file",
                str(batch_path),
            )
            self.assertIsNone(result["selected_worker"])
            self.assertEqual(result["status"], "discard")

            log_text = results_path.read_text(encoding="utf-8")
            self.assertIn("1\t-\t11\t+1\tpass\tdiscard", log_text)

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["current_metric"], 10)
            self.assertEqual(state["state"]["last_trial_metric"], 11)
            self.assertEqual(state["state"]["last_trial_commit"], "d4e5f6a")

    def test_parallel_batch_keep_requires_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"
            batch_path = tmpdir / "batch.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
                "--parallel-mode",
                "parallel",
            )
            batch_path.write_text(
                json.dumps(
                    [
                        {
                            "worker_id": "a",
                            "metric": 8,
                            "guard": "pass",
                            "description": "better attempt without commit",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            completed = self.run_script_completed(
                "autoresearch_select_parallel_batch.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--batch-file",
                str(batch_path),
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("did not report a commit", completed.stderr)

    def test_drift_and_later_keep_preserve_historical_best_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "keep",
                "--metric",
                "5",
                "--commit",
                "keep001",
                "--guard",
                "pass",
                "--description",
                "strong improvement",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "drift",
                "--metric",
                "7",
                "--description",
                "environment drift after resume check",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "keep",
                "--metric",
                "6",
                "--commit",
                "keep002",
                "--guard",
                "pass",
                "--description",
                "partial recovery after drift",
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["current_metric"], 6)
            self.assertEqual(state["state"]["best_metric"], 5)
            self.assertEqual(state["state"]["best_iteration"], 1)

    def test_record_iteration_preserves_existing_supervisor_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["supervisor"] = {
                "recommended_action": "relaunch",
                "should_continue": True,
                "terminal_reason": "none",
                "last_exit_kind": "turn_complete",
                "last_turn_finished_at": "2026-03-21T00:00:00Z",
                "last_observed_signature": "sig-1",
                "last_observed_iteration": 0,
                "last_observed_status": "baseline",
                "last_observed_updated_at": state["updated_at"],
                "last_observed_metric": 10,
                "restart_count": 4,
                "stagnation_count": 1,
                "last_reason": "still making progress",
            }
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "discard",
                "--metric",
                "12",
                "--commit",
                "deadbee",
                "--description",
                "worse attempt",
            )

            updated = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["supervisor"]["restart_count"], 4)
            self.assertEqual(updated["supervisor"]["stagnation_count"], 1)
            self.assertEqual(updated["supervisor"]["recommended_action"], "relaunch")

    def test_blocked_iteration_preserves_retained_metric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "keep",
                "--metric",
                "8",
                "--commit",
                "keep001",
                "--guard",
                "pass",
                "--description",
                "initial improvement",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "blocked",
                "--description",
                "verify command removed unexpectedly",
            )

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["iteration"], 2)
            self.assertEqual(state["state"]["blocked"], 1)
            self.assertEqual(state["state"]["current_metric"], 8)
            self.assertEqual(state["state"]["best_metric"], 8)
            self.assertEqual(state["state"]["best_iteration"], 1)
            self.assertEqual(state["state"]["last_commit"], "keep001")

    def test_supervisor_status_relaunches_after_non_terminal_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "pivot",
                "--description",
                "close this branch and continue with a new strategy",
            )

            status = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
            )
            self.assertEqual(status["decision"], "relaunch")
            self.assertEqual(status["reason"], "none")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["supervisor"]["recommended_action"], "relaunch")
            self.assertTrue(state["supervisor"]["should_continue"])
            self.assertEqual(state["supervisor"]["last_exit_kind"], "turn_complete")

    def test_supervisor_status_needs_human_after_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "blocked",
                "--description",
                "external dependency vanished",
            )

            status = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
            )
            self.assertEqual(status["decision"], "needs_human")
            self.assertEqual(status["reason"], "blocked")

    def test_supervisor_status_stops_at_iteration_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--iterations",
                "1",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )
            self.run_script(
                "autoresearch_record_iteration.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--status",
                "discard",
                "--metric",
                "12",
                "--commit",
                "deadbee",
                "--description",
                "bounded miss",
            )

            status = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
            )
            self.assertEqual(status["decision"], "stop")
            self.assertEqual(status["reason"], "iteration_cap_reached")

    def test_supervisor_status_detects_stagnation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            first = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
                "--max-stagnation",
                "2",
            )
            second = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
                "--max-stagnation",
                "2",
            )
            third = self.run_script(
                "autoresearch_supervisor_status.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--after-run",
                "--write-state",
                "--max-stagnation",
                "2",
            )

            self.assertEqual(first["decision"], "relaunch")
            self.assertEqual(second["decision"], "relaunch")
            self.assertEqual(third["decision"], "needs_human")
            self.assertEqual(third["reason"], "stagnated")

    def test_supervise_wrapper_relaunches_and_then_stops_for_blocked_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            results_path = tmpdir / "research-results.tsv"
            state_path = tmpdir / "autoresearch-state.json"
            prompt_path = tmpdir / "prompt.txt"
            fake_codex_path = tmpdir / "fake-codex"
            counter_path = tmpdir / ".fake-codex-count"

            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(results_path),
                "--state-path",
                str(state_path),
                "--mode",
                "loop",
                "--goal",
                "Reduce failures",
                "--scope",
                "src/**/*.py",
                "--metric-name",
                "failure count",
                "--direction",
                "lower",
                "--verify",
                "pytest -q",
                "--baseline-metric",
                "10",
                "--baseline-commit",
                "a1b2c3d",
                "--baseline-description",
                "baseline failures",
            )

            prompt_path.write_text("Run autoresearch overnight.\n", encoding="utf-8")
            fake_codex_path.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env bash",
                        "set -euo pipefail",
                        'repo=""',
                        'while [[ $# -gt 0 ]]; do',
                        '  case "$1" in',
                        '    -C)',
                        '      repo="$2"',
                        "      shift 2",
                        "      ;;",
                        "    *)",
                        "      shift",
                        "      ;;",
                        "  esac",
                        "done",
                        'if [[ -n "$repo" ]]; then',
                        '  cd "$repo"',
                        "fi",
                        f'counter_path="{counter_path}"',
                        'count=0',
                        'if [[ -f "$counter_path" ]]; then',
                        '  count="$(cat "$counter_path")"',
                        "fi",
                        'count=$((count + 1))',
                        'printf "%s" "$count" > "$counter_path"',
                        f'python_bin="{sys.executable}"',
                        f'record_script="{SCRIPTS_DIR / "autoresearch_record_iteration.py"}"',
                        'if [[ "$count" -eq 1 ]]; then',
                        '  "$python_bin" "$record_script" --results-path research-results.tsv --state-path autoresearch-state.json --status pivot --description "close this branch and continue with a new strategy"',
                        "else",
                        '  "$python_bin" "$record_script" --results-path research-results.tsv --state-path autoresearch-state.json --status blocked --description "external dependency vanished"',
                        "fi",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_codex_path.chmod(0o755)

            completed = subprocess.run(
                [
                    "bash",
                    str(SCRIPTS_DIR / "autoresearch_supervise.sh"),
                    "--repo",
                    str(tmpdir),
                    "--prompt-file",
                    str(prompt_path),
                    "--codex-bin",
                    str(fake_codex_path),
                    "--sleep-seconds",
                    "0",
                    "--max-stagnation",
                    "3",
                ],
                capture_output=True,
                text=True,
                cwd=tmpdir,
            )

            self.assertEqual(completed.returncode, 2, msg=completed.stderr)
            self.assertIn("Supervisor decision: relaunch", completed.stdout)
            self.assertIn("Supervisor decision: needs_human", completed.stdout)
            self.assertEqual(counter_path.read_text(encoding="utf-8"), "2")

            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["state"]["iteration"], 2)
            self.assertEqual(state["state"]["last_status"], "blocked")
            self.assertEqual(state["supervisor"]["recommended_action"], "needs_human")
            self.assertEqual(state["supervisor"]["terminal_reason"], "blocked")
            self.assertEqual(state["supervisor"]["restart_count"], 2)


if __name__ == "__main__":
    unittest.main()
