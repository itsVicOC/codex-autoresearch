# Installation

`codex-autoresearch` is a Markdown-first Codex skill package with bundled helper scripts. No build step, no runtime dependencies.

## Install

### Via Skill Installer (recommended)

In Codex, run:

```text
$skill-installer install https://github.com/leo-lilinxiao/codex-autoresearch
```

Restart Codex after installation.

### Option A: Clone into a repository

```bash
git clone https://github.com/leo-lilinxiao/codex-autoresearch.git
cp -r codex-autoresearch your-project/.agents/skills/codex-autoresearch
```

### Option B: Install for all projects (user scope)

```bash
git clone https://github.com/leo-lilinxiao/codex-autoresearch.git
cp -r codex-autoresearch ~/.agents/skills/codex-autoresearch
```

### Option C: Symlink for live development

```bash
git clone https://github.com/leo-lilinxiao/codex-autoresearch.git
ln -s $(pwd)/codex-autoresearch your-project/.agents/skills/codex-autoresearch
```

Codex supports symlinked skill folders. Edits to the source repo take effect immediately.

## Skill Discovery Locations

Codex scans these directories for skills:

| Scope | Location | Use case |
|-------|----------|----------|
| Repo (CWD) | `$CWD/.agents/skills/` | Skills for the current working directory |
| Repo (parent) | `$CWD/../.agents/skills/` | Shared skills in a parent folder (monorepo) |
| Repo (root) | `$REPO_ROOT/.agents/skills/` | Root skills available to all subfolders |
| User | `~/.agents/skills/` | Personal skills across all projects |
| Admin | `/etc/codex/skills/` | Machine-wide defaults for all users |
| System | Bundled with Codex | Built-in skills by OpenAI |

## Verify Installation

Open Codex in the target repo and verify:

1. Type `$` and confirm `codex-autoresearch` appears in the skill list.
2. Invoke the skill:

```text
$codex-autoresearch
I want to reduce my failing tests to zero
```

Expected behavior:

- Codex recognizes the skill,
- loads `SKILL.md`,
- loads the relevant workflow for the request,
- and collects any missing fields via the wizard.

## Optional Long-Running Hooks

If you want better long-running continuity in both `foreground` and `background`, install the optional user-level Codex hooks:

```bash
python3 /absolute/path/to/codex-autoresearch/scripts/autoresearch_hooks_ctl.py install
```

Inspect the current state first if you want:

```bash
python3 /absolute/path/to/codex-autoresearch/scripts/autoresearch_hooks_ctl.py status
```

What they do:

- `SessionStart` reinjects the short runtime checklist when a future session starts or resumes.
- `Stop` lets Codex continue only when the autoresearch run still looks active/resumable.

Important:

- Hooks are optional. The skill still works without them.
- Hooks affect **future sessions only**, and they only attach to sessions that clearly look like `codex-autoresearch` work. Unrelated Codex conversations in the same repo are left alone.
- The currently open foreground session will not hot-reload them. If you want hooks for `foreground`, install them first, then open a new Codex session (for example via `codex resume`) and continue the run there.
- New background nested `codex exec` sessions launched after installation will pick them up automatically, so installing them before a `background` launch helps that run immediately.
- Managed `background` runs explicitly pass their configured artifact paths into those nested sessions, so custom `--results-path` / `--state-path` layouts continue to work there.
- Future `foreground` sessions can also recover repo-local custom artifact paths through the repo's hook context pointer, but hooks still require an explicit autoresearch session signal before they attach.

## Updating

If installed by copy: re-clone and replace the installed folder.

If installed by symlink: `git pull` in the source repo. Changes are live immediately.

If an update does not appear, restart Codex.

## Disable Without Deleting

Use `~/.codex/config.toml`:

```toml
[[skills.config]]
path = "/absolute/path/to/codex-autoresearch/SKILL.md"
enabled = false
```

Restart Codex after changing the config.
