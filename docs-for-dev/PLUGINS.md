# Third-party plugin development

[Handbook](README.md) · [Tools and capabilities](TOOLS_AND_CAPABILITIES.md) · [Reading extensions](READING_EXTENSIONS.md)

Official [module wheels](MODULES.md) share DeepTutor's interpreter and version.
Third-party plugins have a separate manifest, approval and lifecycle contract.
Start with the runnable [Learning Echo example](examples/learning_echo/README.md),
which declares a tool, capability, HTTP route and static page without external
Python dependencies.

## Manifest and registration

A package ships static `deeptutor.plugin.json` using schema
`deeptutor.plugin/v1`. Read
[`manifest.py`](../deeptutor/plugins/manifest.py) and the
[example manifest](examples/learning_echo/learning_echo/deeptutor.plugin.json)
for the exact fields. It declares identity/version, DeepTutor/API compatibility,
permission disclosure, dependency closure and typed extensions. Unknown fields
and invalid paths are rejected.

| Extension | Runtime contract |
| --- | --- |
| `tool`, `capability` | Host entry-point protocol or approved managed JSON worker |
| `loop_capability` | Existing shared-loop extension protocol |
| `reading_extension` | Server-verified Reading context and bounded result types |
| `visualizer` | Typed packaged visualizer declaration |
| `http_route` | Managed worker endpoint under the host plugin namespace |
| `frontend_page` | Declared static assets served with restrictive sandbox CSP |
| `persistence_schema`, `app_connector` | Approved declaration/introspection; no general migration or connector execution API |

Built-in IDs take precedence. Each extension retains its own typed protocol.
Existing Python entry-point groups honor root-manifest approval when one is
present; new packages should not rely on the legacy manifest-free path.
Discovery reads metadata without importing third-party code. The
[registry](../deeptutor/plugins/registry.py) distinguishes available,
approval-required, enabled, disabled, incompatible, broken and deprecated state.

## Installation and approval

Use `deeptutor plugin --help` for lifecycle commands. Managed installation
accepts a local wheel or resolves a reviewed entry from the vendored
[`catalog.json`](../deeptutor/plugins/catalog.json). Catalog browsing/version
resolution is offline; explicit installation downloads the pinned artifact.
There is no arbitrary URL installer or automatic background upgrade.

Catalog artifacts bind an HTTPS wheel URL, SHA-256, size and platform metadata.
Downloads reject redirects and size/digest mismatches before pip. The local
lifecycle validates the manifest from the wheel before importing code, creates
a version-private environment, and installs an explicit wheel-only dependency
closure. It does not mutate the host interpreter.

Approval binds the normalized manifest and artifact identity. Inspect the
current snapshot before approving. Installation, upgrade, same-version
reinstall and rollback clear prior approval. Approval does not automatically
enable a locally disabled plugin. Failed installations preserve the previous
usable state; retained versions support rollback. External host-installed
plugin upgrades need restart to replace already imported Python modules.

The owner is [`lifecycle.py`](../deeptutor/plugins/lifecycle.py), with state
under runtime `data/user/settings/plugins.json`. API lifecycle mutations need
administrator authorization. [Plugin tests](../tests/plugins/) cover manifest,
artifact, transaction, recovery and approval boundaries.

## Worker protocol and cancellation

[`runtime.py`](../deeptutor/plugins/runtime.py) launches a worker module using
the plugin environment's Python. Worker declarations cannot exceed the approved
manifest. Legacy workers exchange one JSON request and response on stdin/stdout.

A capability can advertise `"transport": "ndjson-v1"` in its description.
It then emits JSON lines with `{"kind":"event","event":{...}}`, followed
by `{"kind":"complete"}`. Events enter the normal durable turn stream;
workers do not own a parallel public stream. EOF before completion and
malformed frames fail the run. Requests, frames, output, stderr and execution
have bounds; queues apply backpressure. Cancellation closes the process group
and waits for cleanup. The example supports both streaming and legacy modes.

## HTTP and static pages

Managed HTTP routes use `/api/plugins/{plugin-id}{path}` and cannot replace
built-in routes. The host resolves approved, enabled, compatible managed state
and authenticates before starting a worker. With host authentication enabled,
even a plugin route declared `public` requires a host session: it does not
bypass the host account boundary. The `admin` policy adds an administrator
check. Unavailable plugin routes return 404.

Workers receive declared method/path, normalized query values and a bounded
JSON body, not host cookies, bearer tokens or authentication headers.
Responses have validated JSON status/body and restricted `Cache-Control`;
redirects and authentication responses belong to the host. See
[API tests](../tests/api/test_plugins_router.py).

A static page declares schema `deeptutor.plugin-frontend-page/v1`, one entry
and an explicit asset closure. Only approved regular package files may be
served; symlinks and undeclared assets are rejected. The canonical URL is
`/api/plugins/{plugin-id}/pages/{extension-id}/`. Keep the trailing slash for
relative assets.

Pages run in a sandboxed browser context with restrictive CSP, including
`connect-src 'none'`; they do not inject React/Next code into the host bundle
or arbitrarily fetch host APIs. See [`frontend.py`](../deeptutor/plugins/frontend.py),
[frontend tests](../tests/plugins/test_frontend.py), and the
[example page manifest](examples/learning_echo/learning_echo/frontend/page.json).

## Trust limits and validation

Permission declarations and approval are not an OS sandbox. Host entry-point
extensions execute in the host interpreter; managed workers isolate Python
dependencies but retain host operating-system access. Review actual packages
and dependencies. Packaged browser pages have their own browser sandbox.
Direct Chrome extension reuse is unsupported.

Validate the manifest, build a wheel, exercise approval/enablement, the worker
and page, then disable/revoke and cancel a run. Use a disposable runtime home.
See [Testing](TESTING.md) and the separate
[Reading extension context/result rules](READING_EXTENSIONS.md).
