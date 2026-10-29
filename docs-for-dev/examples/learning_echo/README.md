# Learning Echo plugin

[Handbook](../../README.md) · [Plugin contract](../../PLUGINS.md) · [Testing](../../TESTING.md)

This package is the reference implementation for the managed plugin runtime.
It declares one Tool, one Capability, one HTTP route, and one static frontend
page. The page requests only the `sandboxed-iframe` UI permission; the package
has no Python dependencies.

## Package layout

- [Manifest](learning_echo/deeptutor.plugin.json): plugin identity, permissions
  and the four extension declarations.
- [Worker](learning_echo/worker.py): descriptions, tool execution, capability
  streaming and JSON HTTP responses.
- [Page manifest](learning_echo/frontend/page.json): the explicit static asset
  closure; [index.html](learning_echo/frontend/index.html) and
  [app.js](learning_echo/frontend/app.js) implement the sandboxed page.
- [Build metadata](pyproject.toml): packages the worker, manifest and assets.

## Build and inspect

From the repository root, build a local wheel:

```bash
python -m pip wheel --no-deps -w /tmp/deeptutor-plugins docs-for-dev/examples/learning_echo
```

Use a disposable `DEEPTUTOR_HOME`, then run `deeptutor plugin install` with
the generated wheel path and inspect it with:

```bash
deeptutor plugin show org.deeptutor.learning_echo
deeptutor plugin state
```

Review the manifest and artifact before calling
`deeptutor plugin approve org.deeptutor.learning_echo`; explicitly enable it
if it is disabled. Installed and approved are distinct states. The install
step reads `deeptutor.plugin.json` before importing plugin code and creates a
plugin-private virtual environment.

After approval and enablement, the page is available at
`/api/plugins/org.deeptutor.learning_echo/pages/learning_echo_page/`. Its entry
and asset closure are declared in `learning_echo/frontend/page.json`.

With host authentication enabled, opening the page or its `public` HTTP route
still requires the host session. The page's CSP blocks arbitrary network
access; it is not an example of injecting host frontend code.

## Verify and adapt

From the repository root:

```bash
python -m pytest tests/plugins/test_runtime.py tests/api/test_plugins_router.py
```

These tests use this package as the worker/page fixture. Preserve the tests
when moving or changing the example. For a new plugin, choose a distinct
package/manifest identity, declare the actual permission and dependency
closure, and test failure, cancellation, disabled state and reapproval after
an upgrade. See [the plugin guide](../../PLUGINS.md) for trust limits and
rollback behavior.
