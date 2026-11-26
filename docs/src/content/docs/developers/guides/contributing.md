---
title: Contributing
description: How to contribute code, docs, or bug fixes to DeepTutor — branching, setup, and the PR checklist.
quadrant: how-to
---

Thanks for your interest in contributing to DeepTutor. We recruit triagers and maintainers; roles and application details are in [`CONTRIBUTING.md`](https://github.com/HKUDS/DeepTutor/blob/main/CONTRIBUTING.md) at the repo root.

## Roadmap

DeepTutor's roadmap is tracked in the open at [`HKUDS/DeepTutor#498`](https://github.com/HKUDS/DeepTutor/issues/498). Use that issue to see what is planned, vote on priorities, or propose new work before starting a larger contribution.

## Where to target your PR

**Target `dev` for all contributions.** `main` moves only at release time.

| Branch | Use for |
|--------|---------|
| `dev` | Default target — features, refactors, bug fixes, API/config changes |
| `main` | Release branch — PRs targeting it are retargeted to `dev` |

Discuss feature changes first; keep each PR focused.

## Quick start

```bash
# 1. Fork and clone, then sync with the target branch
git checkout dev && git pull origin dev

# 2. Branch off
git checkout -b feature/your-feature-name

# 3. Install in editable mode with everything
python -m pip install -r requirements/full.txt
python -m pip install -e . --no-deps
python scripts/install_extras.py dev
(cd web && npm ci --legacy-peer-deps)

# 4. Wire up pre-commit (once per machine)
pip install pre-commit
pre-commit install

# 5. Make your changes, then validate locally
pre-commit run --all-files

# 6. Open the PR against dev with relevant test evidence
```

Browse [`good first issue`](https://github.com/HKUDS/DeepTutor/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) labels for an entry point. Comment on the issue first so others know you're on it.

## Coding standards

We enforce these in CI; running `pre-commit run --all-files` catches the common ones locally.

| Area | Rule |
|------|------|
| Python | Type hints on all signatures; PEP 8 (Ruff); f-strings; small focused functions |
| Docstrings | Google-style for new modules, classes, and public functions |
| Secrets | Never commit; `detect-secrets` runs on every PR |
| Subprocesses | Always `shell=False` |
| Paths | `pathlib.Path` over string concatenation |

Tooling under the hood: **Ruff** (lint + format), **Prettier** (frontend / config), **detect-secrets**, **pip-audit**, **Bandit**, **MyPy**, **Interrogate**.

## Commit messages

```
<type>: <short description>

[optional body]
```

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no logic |
| `refactor` | Restructuring, no behavior change |
| `test` | Adding or correcting tests |
| `chore` | Build / tooling / deps |

## What gets reviewed

- **Correctness** — does it solve the stated problem and not introduce regressions?
- **Scope** — small focused changes get merged faster than sprawling ones; split when in doubt.
- **Tests** — new behavior needs new coverage; bug fixes need a regression test where reasonable.
- **Docs** — user-facing changes update the relevant page in `site/docs/src/content/docs/`.

## Help

- [Discord](https://discord.gg/eRsjPgMU4t) — fastest place to ask
- [GitHub Discussions](https://github.com/HKUDS/DeepTutor/discussions) — long-form Q&A
- [WeChat community](https://github.com/HKUDS/DeepTutor/issues/78) — Chinese-speaking contributors
- [Issues](https://github.com/HKUDS/DeepTutor/issues) — bug reports and feature requests

## See also

- [`CONTRIBUTING.md`](https://github.com/HKUDS/DeepTutor/blob/main/CONTRIBUTING.md) — full document (branching policy, security practices, maintainer)
