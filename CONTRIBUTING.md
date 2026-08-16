# Contributing to DeepTutor

Thank you for your interest in contributing to DeepTutor! We welcome developers of all skill levels to help build the next-generation intelligent learning companion.

<p align="center">
<a href="https://discord.gg/eRsjPgMU4t"><img src="https://img.shields.io/badge/Discord-Join_Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>&nbsp;
<a href="https://github.com/HKUDS/DeepTutor/issues/78"><img src="https://img.shields.io/badge/WeChat-Join_Group-07C160?style=for-the-badge&logo=wechat&logoColor=white" alt="WeChat"></a>&nbsp;
<a href="./Communication.md"><img src="https://img.shields.io/badge/Feishu-Join_Group-00D4AA?style=for-the-badge&logo=feishu&logoColor=white" alt="Feishu"></a>
</p>

---

## Table of Contents

- [Maintainers](#maintainers)
- [Branching Strategy](#branching-strategy)
- [Quick Start for Contributors](#quick-start-for-contributors)
- [Development Setup](#development-setup)
- [Code Quality & Security](#code-quality--security)
- [Coding Standards](#coding-standards)
- [Commit Message Format](#commit-message-format)
- [Security Best Practices](#security-best-practices)

---

## Maintainer

[@pancacake](https://github.com/pancacake) — Currently just me!

---

## Branching Strategy

We use a multi-branch model to keep development organized:

| Branch | Purpose | Stability |
|---|---|---|
| `dev` | General development | May have bugs or breaking changes |
| `multi-user` | Multi-user scenario development | Experimental, focused on multi-tenant features |

> [!IMPORTANT]
> Please do **not** submit PRs directly to `main`. All contributions should target `dev` or `multi-user`.

### Which Branch Should I Target?

**Target `dev`** if your PR includes:

- New features or functionality
- Refactoring that may affect existing behavior
- Changes to APIs or configuration
- General bug fixes

**Target `multi-user`** if your PR includes:

- Multi-user / multi-tenant related features
- Session isolation, user management, or permission changes
- Collaborative or shared workspace functionality

> [!NOTE]
> When in doubt, target `dev` — it is the default development branch.

---

## Quick Start for Contributors

1. **Fork & Clone** the repository.
2. **Sync** with the target branch before starting:

```bash
git checkout dev && git pull origin dev
```

3. **Create** your feature branch from the target branch:

```bash
git checkout -b feature/your-feature-name
```

4. **Develop** your changes, following the coding standards below.
5. **Validate** by running pre-commit checks:

```bash
pre-commit run --all-files
```

6. **Submit** your Pull Request to the correct target branch (not `main` unless it's a hotfix or docs-only change).

> [!TIP]
> Browse our [Issues](https://github.com/HKUDS/DeepTutor/issues) for tasks labeled `good first issue` to find a great starting point. Comment on the issue to let others know you're working on it.

---

## Development Setup

<details>
<summary><b>Setting Up Your Environment</b></summary>

**Step 1: Create a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**Step 2: Install dependencies**

```bash
pip install -e ".[all]"
```

</details>

<details>
<summary><b>Setting Up Pre-commit (First Time Only)</b></summary>

**Step 1: Install pre-commit**

```bash
pip install pre-commit
# Or: conda install -c conda-forge pre-commit
```

**Step 2: Install Git hooks**

```bash
pre-commit install
```

**Step 3: Initialize the Secrets Baseline**

If you encounter false-positive secrets (like API hash placeholders), update the baseline:

```bash
detect-secrets scan > .secrets.baseline
```

</details>

### Common Commands

| Task | Command |
|---|---|
| Check clean workspace + tracked hygiene | `python3 scripts/check_workspace_hygiene.py` |
| Check repository hygiene | `python3 scripts/check_repo_hygiene.py` |
| Check all files | `pre-commit run --all-files` |
| Check quietly | `pre-commit run --all-files -q` |
| Update tools | `pre-commit autoupdate` |
| Emergency skip | `git commit --no-verify -m "message"` *(not recommended)* |

### Generated Files and Worktrees

Keep build outputs out of Git. `web/.next*`, `node_modules`, test reports, and
bytecode caches are regeneratable and must remain untracked. If a build output
is already tracked, remove it from the index with `git rm --cached` rather than
deleting the local file needed by an application run.

Fresh checkouts can enable the dependency-free safety hook with:

```bash
git config core.hooksPath scripts/hooks
```

The hook also blocks accidental direct commits on `main`. Release maintainers who
deliberately need a local `main` commit may opt in once with
`git config deeptutor.allowMainCommit true`, then remove the setting immediately
afterward.

Use a separate Git worktree for each feature (`git worktree add ../DeepTutor-<task>
-b <branch> dev`) and keep the primary checkout clean. This lets builds, tests,
and long-running agents operate independently without rewriting one another's
outputs. Before removing a worktree, commit or explicitly preserve its changes;
do not use `git reset --hard` or `git clean` as a routine cleanup shortcut.
---

## Code Quality & Security

We use automated tools (configured via `pyproject.toml` and `.pre-commit-config.yaml`) to maintain high standards:

| Tool | Purpose |
|---|---|
| **Ruff** | Python linting and formatting |
| **Prettier** | Frontend & config file formatting |
| **detect-secrets** | Hardcoded secret scanning |
| **pip-audit** | Dependency vulnerability scanning |
| **Bandit** | Security issue analysis |
| **MyPy** | Static type checking |
| **Interrogate** | Docstring coverage reporting |

> [!IMPORTANT]
> Local pre-commit hooks may only show warnings, but **CI will perform strict checks** and automatically reject PRs that fail.

---

## Coding Standards

### Python

- Use **type hints** for all function signatures.
- Prefer **f-strings** for string formatting.
- Follow **PEP 8** (enforced by Ruff).
- Keep functions **small and focused** on a single responsibility.

### Documentation

- Every new module, class, and public function should have a **docstring** (Google Python Style Guide format).
- Update `README.md` if your change introduces new features or configuration.

---

## Commit Message Format

```
<type>: <short description>

[optional body]
```

| Type | Description |
|---|---|
| `feat` | A new feature (MINOR version bump) |
| `fix` | A bug fix (PATCH version bump) |
| `docs` | Documentation only changes |
| `style` | Formatting, no logic changes |
| `refactor` | Code restructuring, no new features or fixes |
| `test` | Adding or correcting tests |
| `chore` | Build process, tooling, or dependency updates |

---

## Security Best Practices

### File Uploads

- **Size Limits**: General files capped at 100 MB; PDFs capped at 50 MB.
- **Validation**: Multi-layer validation (extension + MIME type + content sanitization).
- **Sanitization**: All filenames are sanitized to prevent path traversal.

### Development Standards

- **Subprocesses**: Always use `shell=False` to prevent command injection.
- **Pathing**: Use `pathlib.Path` for cross-platform compatibility.
- **Line Endings**: LF (Unix) line endings enforced for critical scripts via `.gitattributes`.

---

Questions? Reach out on [Discord](https://discord.gg/eRsjPgMU4t). Let's build the future of AI tutoring together!
