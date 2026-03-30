from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .base import AutoresearchScriptsTestBase


class AutoresearchHooksCtlTest(AutoresearchScriptsTestBase):
    maxDiff = None

    def hook_env(self, home: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(home / ".codex")
        return env

    def installed_hook_path(self, home: Path, name: str) -> Path:
        return home / ".codex" / "autoresearch-hooks" / name

    def run_installed_hook(
        self,
        hook_path: Path,
        *,
        cwd: Path,
        payload: dict[str, object],
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(hook_path)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )

    def test_install_merges_existing_config_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            codex_home = home / ".codex"
            codex_home.mkdir(parents=True)
            env = self.hook_env(home)

            (codex_home / "config.toml").write_text(
                "[features]\nother_feature = true\n",
                encoding="utf-8",
            )
            (codex_home / "hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "UserPromptSubmit": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python3 /tmp/existing.py",
                                            "statusMessage": "existing",
                                        }
                                    ]
                                }
                            ]
                        }
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            installed = self.run_script("autoresearch_hooks_ctl.py", "install", env=env)
            self.assertTrue(installed["ready_for_future_sessions"])
            self.assertTrue(installed["feature_enabled"])
            self.assertTrue(installed["managed_scripts_present"])

            hooks_payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("UserPromptSubmit", hooks_payload["hooks"])
            self.assertEqual(len(hooks_payload["hooks"]["SessionStart"]), 1)
            self.assertEqual(len(hooks_payload["hooks"]["Stop"]), 1)
            session_command = hooks_payload["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            stop_command = hooks_payload["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertIn(str(self.installed_hook_path(home, "session_start.py")), session_command)
            self.assertIn(str(self.installed_hook_path(home, "stop.py")), stop_command)

            reinstalled = self.run_script("autoresearch_hooks_ctl.py", "install", env=env)
            self.assertTrue(reinstalled["ready_for_future_sessions"])
            hooks_payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(hooks_payload["hooks"]["SessionStart"]), 1)
            self.assertEqual(len(hooks_payload["hooks"]["Stop"]), 1)

            removed = self.run_script("autoresearch_hooks_ctl.py", "uninstall", env=env)
            self.assertEqual(removed["managed_groups_removed"], 2)
            hooks_payload = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            self.assertNotIn("SessionStart", hooks_payload["hooks"])
            self.assertNotIn("Stop", hooks_payload["hooks"])
            self.assertIn("UserPromptSubmit", hooks_payload["hooks"])
            config_text = (codex_home / "config.toml").read_text(encoding="utf-8")
            self.assertIn("codex_hooks = true", config_text)

    def test_uninstall_turns_feature_off_when_installer_enabled_it_and_no_other_hooks_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            env = self.hook_env(home)

            self.run_script("autoresearch_hooks_ctl.py", "install", env=env)
            removed = self.run_script("autoresearch_hooks_ctl.py", "uninstall", env=env)
            self.assertFalse(removed["ready_for_future_sessions"])

            config_text = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
            self.assertIn("codex_hooks = false", config_text)
            self.assertFalse(self.installed_hook_path(home, "session_start.py").exists())
            self.assertFalse(self.installed_hook_path(home, "stop.py").exists())

    def test_session_start_hook_emits_short_checklist_only_for_active_autoresearch_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            env = self.hook_env(home)
            self.run_script("autoresearch_hooks_ctl.py", "install", env=env)

            empty_repo = root / "empty-repo"
            empty_repo.mkdir()
            hook_path = self.installed_hook_path(home, "session_start.py")
            completed = self.run_installed_hook(
                hook_path,
                cwd=empty_repo,
                payload={"cwd": str(empty_repo), "source": "startup"},
                env=env,
            )
            completed.check_returncode()
            self.assertEqual(completed.stdout, "")

            repo = root / "active-repo"
            repo.mkdir()
            (repo / "research-results.tsv").write_text(
                "iteration\tcommit\tmetric\tdelta\tguard\tstatus\tdescription\n",
                encoding="utf-8",
            )
            completed = self.run_installed_hook(
                hook_path,
                cwd=repo,
                payload={"cwd": str(repo), "source": "resume"},
                env=env,
            )
            completed.check_returncode()
            payload = json.loads(completed.stdout)
            context = payload["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Record every completed experiment before starting the next one.", context)
            self.assertIn("Do not rerun the wizard after launch is already confirmed.", context)

    def test_stop_hook_blocks_only_when_supervisor_says_the_run_should_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            env = self.hook_env(home)
            self.run_script("autoresearch_hooks_ctl.py", "install", env=env)
            hook_path = self.installed_hook_path(home, "stop.py")

            repo = root / "active-repo"
            repo.mkdir()
            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(repo / "research-results.tsv"),
                "--state-path",
                str(repo / "autoresearch-state.json"),
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
                "base111",
                "--baseline-description",
                "baseline failures",
                env=env,
            )

            completed = self.run_installed_hook(
                hook_path,
                cwd=repo,
                payload={"cwd": str(repo), "stop_hook_active": False},
                env=env,
            )
            completed.check_returncode()
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["decision"], "block")
            self.assertIn("Do not rerun the wizard.", payload["reason"])
            self.assertIn("record it before starting the next one", payload["reason"])

            terminal_repo = root / "terminal-repo"
            terminal_repo.mkdir()
            self.run_script(
                "autoresearch_init_run.py",
                "--results-path",
                str(terminal_repo / "research-results.tsv"),
                "--state-path",
                str(terminal_repo / "autoresearch-state.json"),
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
                "--stop-condition",
                "stop when metric reaches 0",
                "--baseline-metric",
                "0",
                "--baseline-commit",
                "base000",
                "--baseline-description",
                "baseline failures",
                env=env,
            )

            completed = self.run_installed_hook(
                hook_path,
                cwd=terminal_repo,
                payload={"cwd": str(terminal_repo), "stop_hook_active": False},
                env=env,
            )
            completed.check_returncode()
            self.assertEqual(completed.stdout, "")
