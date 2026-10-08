# Learning Echo plugin

This package is the reference implementation for the managed plugin runtime.
It declares one Tool, one Capability, one HTTP route, and one static frontend
page. The page requests only the `sandboxed-iframe` UI permission; the package
has no Python dependencies.

Build a local wheel:

```bash
python -m pip wheel --no-deps -w /tmp/deeptutor-plugins examples/plugins/learning_echo
```

Install, review, approve, and roll back through `deeptutor plugin`. The install
step reads `deeptutor.plugin.json` before importing plugin code and creates a
plugin-private virtual environment.

After approval and enablement, the page is available at
`/api/plugins/org.deeptutor.learning_echo/pages/learning_echo_page/`. Its entry
and asset closure are declared in `learning_echo/frontend/page.json`.
