# Testing and validation

[Handbook](README.md) · [Development](DEVELOPMENT.md) · [Modules](MODULES.md#validation)

Use the repository's configured tools and the environment from
[Agent setup](AGENT_SETUP.md). Run targeted checks during development and the
affected project gates before publishing. A documentation-only change does
not require paid model calls or a full rendering workload.

## Select checks by change

| Change | Minimum useful evidence |
| --- | --- |
| Documentation and CLI examples | Links/anchors, CLI documentation contracts, command help, no stale paths |
| Python domain logic | Focused pytest reproduction; Ruff; relevant import boundaries |
| API or turn events | Request/authorization tests, generated contract check, persistence/replay tests, consumer tests |
| Frontend behavior | Typecheck, focused Node/Vitest test, dependency check; browser verification for interaction/layout |
| Module ownership/dependencies | Generated requirements, module isolation, wheel lifecycle smoke |
| Plugin worker or packaged page | Manifest, runtime/lifecycle and API tests, reference example wheel |
| Parsing/subprocess code | Real child success/error/timeout/cancellation; relevant platform checks |
| Provider/model integration | Mocked contract tests plus an explicitly configured real-provider probe when needed |

## Python

```bash
python -m pytest tests/cli/test_docs_contract.py tests/scripts/test_docker_compose.py
python -m pytest tests/app tests/runtime/coordination
python -m pytest tests/plugins tests/api/test_plugins_router.py
python -m ruff check .
python -m ruff format --check .
lint-imports
python scripts/check_architecture.py
python scripts/sync_module_requirements.py --check
python scripts/check_repo_hygiene.py
```

These are separate entry points; select the relevant suites rather than
assuming the first command covers all changes. The full Python suite is
`python -m pytest tests deeptutor/learning/tests`. Some integration cases
need fixtures such as Redis, optional engines or platform executables.
Read skip conditions and report skipped checks accurately.

`check_repo_hygiene.py` checks tracked paths. The stricter
`check_workspace_hygiene.py` also requires an entirely clean checkout, so run
it after committing rather than interpreting intended edits as a test failure.

## Web and generated contracts

From `web/`:

```bash
npm run typecheck
npm run architecture:check
npm run test:node
npm run test:unit
npm run lint
npm run i18n:check
npm run contracts:check
```

`npm run check:fast` runs the deterministic checks above; `npm run check`
adds the production build and route budgets. Use `npm run contracts:generate`
after changing backend schemas, then inspect and commit the generated diff.
The generator owns [`web/contracts/`](../web/contracts/) and calls the
[Python export script](../scripts/export_frontend_contracts.py).

Rendered component tests use Vitest and Testing Library. Node tests cover
pure contracts and state logic. Playwright `npm run audit` expects a running
frontend at `WEB_BASE_URL`; critical and multi-worker projects have separate
fixture requirements in [`playwright.config.ts`](../web/playwright.config.ts).
Do not run browser mutations against a learner's only copy of data.

## Modules, engines and optional integration

Follow [Modules → Validation](MODULES.md#validation) for disposable wheel
installation, uninstall/reinstall and retained-data checks. Do not use the
development interpreter to test package removal.

The experimental TypeScript engine has its own `npm test` under
[`packages/chat-engine/`](../packages/chat-engine/), plus Python bridge and
application compatibility tests. The canonical matrix is in
[`tests.yml`](../.github/workflows/tests.yml) and
[`modules.yml`](../.github/workflows/modules.yml).

`deeptutor doctor --online` performs a real model request. Prompt-cache,
video rendering and multi-worker acceptance tests may require explicit opt-in
variables. State the actual environment and verification performed; historical
test counts and a mock provider do not establish current production behavior.

## Reviewing a documentation change

Check relative links from each file, not from the repository root. Search
README translations, CLI help, UI setup prompts and test fixtures when moving
a guide. Keep source links free of fragile line numbers. Use the installed
CLI's `--help` and authoritative manifests/settings to validate commands and
defaults. Keep local artifacts and secrets out of the commit.
