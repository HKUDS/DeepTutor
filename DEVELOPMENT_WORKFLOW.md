# Local development workflow

This repository uses a stable-mainline model. `main` is always deployable, and
product work happens in short-lived branches checked out in separate worktrees.
The primary checkout remains tied to the launchd-managed product so development
does not disturb the running local service.

## Starting work

1. Confirm the primary checkout is clean and either on `main` or on a release
   candidate pointing at the same commit:

   ```bash
   git status --short --branch
   git rev-parse main
   ```

2. Create an isolated worktree and branch from `main`:

   ```bash
   git worktree add /tmp/DeepTutor-<slug> -b codex/<slug> main
   cd /tmp/DeepTutor-<slug>
   ```

3. Keep one product theme per branch. Classify work explicitly:

   - `feat`: new product capability or behavior.
   - `fix`: a defect in an already promised feature.
   - `test`: regression or real-device verification coverage.
   - `chore`: build, dependency, port, deployment, or release engineering.

Do not combine a feature, an unrelated bug fix, and broad cleanup in one branch.
Do not commit `.worktrees/`, build output, logs, local launchd configuration,
tokens, or cached credentials.

## Merging

Before merging a branch into `main`:

1. Rebase it on the latest `main`.
2. Keep the worktree clean.
3. Run the checks required for the touched subsystem.
4. Bind every new product behavior to at least one regression test.

Merge only as a fast-forward from the primary checkout:

```bash
git switch main
git merge --ff-only codex/<slug>
git push myfork main
git worktree remove /tmp/DeepTutor-<slug>
git branch -d codex/<slug>
```

If the merge is not a fast-forward, return to the development worktree, rebase,
and rerun the focused checks. Do not hide divergence with an unplanned merge
commit, reset, or force push.

## Verification gates

Use the smallest relevant gate while developing, then the broader gate before
local product consolidation.

- Python changes: run focused `pytest` targets and Ruff on touched files.
- Web changes: run `cd web && npm run test:node` and `npm run lint`; require
  zero errors and no new warnings.
- Browser behavior: run the relevant Playwright suite. Kids changes must keep
  the current golden-path coverage passing.
- Kids: run the Kids backend ledger and Kids Playwright golden path before
  consolidating.
- MarginNote 4: run its router, capability, and knowledge-base tests.
- Partner channels: run the Partner router, channel onboarding, and Feishu
  domain tests.

Before treating a revision as a local release candidate, also run the full
backend ledger from `LOCAL_FEATURES.md`, `npm run build`, and the Kids browser
golden path. Report every check as pass, fail, or blocked; do not claim success
for an unavailable check.

## Ports and product deployment

The product ports are fixed:

- Backend: `8001`
- Frontend: `3782`

The launchd services own those ports in the primary checkout. Development
worktrees must not write alternate ports into repository configuration or
`data/user/settings/system.json`. Pass temporary runtime ports explicitly with
environment variables, for example:

```bash
WEB_BASE_URL=http://127.0.0.1:4317
NEXT_PUBLIC_API_BASE=http://127.0.0.1:4318
```

After backend source changes reach the primary checkout, restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.deeptutor.api
```

After frontend source changes reach the primary checkout, rebuild the
production standalone bundle, restart `com.deeptutor.web.3782`, and verify that
`/kids` returns 200 and that the standalone build contains the new code.

## Upstream contributions

Create small upstream PRs from `origin/main`, not from the local product
integration history. Keep these fork-local concerns out of upstream PRs unless
a maintainer explicitly asks for them:

- `LOCAL_FEATURES.md` and this workflow document.
- Partner QR onboarding and private Kids product flows.
- Local MarginNote 4 configuration or launchd setup.
- Temporary ports and local deployment details.

For the Kids current-page concept-learning contribution, wait for PR #823 to be
merged or for a maintainer to accept issue #957 before preparing the focused
upstream implementation PR.

## Recovery

When a long-lived branch diverges:

1. Preserve it with an explicitly named branch.
2. Recreate the development branch from current `main`.
3. Rebase or cherry-pick only still-valid work.
4. Rerun the focused regression gate.

When `main` fails after consolidation, stop deployment, isolate the failure with
the relevant tests, and fix it through a `fix/...` branch. Do not use history
rewrites to make a broken release disappear.
