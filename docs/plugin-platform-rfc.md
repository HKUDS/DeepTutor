# DeepTutor Plugin Platform RFC (Phase C and Catalog E)

Status: accepted implementation slice
Schema: `deeptutor.plugin/v1`
Last reviewed: 2026-09-08

## Problem

DeepTutor already has several isolated extension mechanisms: capability
plugins, loop capabilities, Reading extensions, tools, and the newer
visualizer catalog. Third-party developers cannot describe one package with
one identity, compatibility matrix, permission disclosure, artifact pin, and
marketplace state. The absence of that root contract makes every extension
point invent its own distribution and trust model.

The plugin platform therefore standardizes package metadata and catalog state
first. It does not attempt to make every extension use one universal runtime
API.

## Non-goals for this slice

- No arbitrary Chrome CRX/extension loading. Chrome extensions assume browser
  APIs, extension process boundaries, and a browser permission model that do
  not map safely to a Python server process.
- No arbitrary URL installation, background update check, or automatic upgrade.
  Catalog installation is an explicit command that resolves a vendored,
  reviewed artifact pin before downloading.
- No claim that Python permission fields create an OS sandbox. They define the
  approval and runtime contract boundary. Managed Tool and Capability workers
  run in a separate Python process with a plugin-private environment, but that
  process boundary is dependency isolation, not a hard security sandbox.
- No replacement of the existing `deeptutor.plugins` capability loader,
  `deeptutor.loop_capabilities`, or `deeptutor.reading_extensions` entry-point
  behavior. Those loaders now honor an approved root manifest whenever a
  package declares one; packages without a root manifest retain the migration
  window.
- Learning Experience widgets/events are intentionally deferred.

## Root manifest

A Python plugin ships `deeptutor.plugin.json` inside its package or wheel. The
file is static JSON and must be readable without importing the plugin.

```json
{
  "schema_version": "deeptutor.plugin/v1",
  "id": "org.author.example",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description_i18n": {
    "en": "Example extension package",
    "zh": "示例扩展包"
  },
  "author": "Author Name",
  "license": "Apache-2.0",
  "homepage": "https://example.com",
  "source_url": "https://github.com/author/example",
  "compatibility": {
    "deeptutor": ">=1.6.0,<2",
    "api": {
      "capability": "1",
      "loop_capability": "1",
      "http_route": "1",
      "frontend_page": "1",
      "persistence_schema": "1",
      "app_connector": "1",
      "tool": "1",
      "reading_extension": "1",
      "visualizer": "1"
    }
  },
  "permissions": {
    "reading": ["selection", "visible_text"],
    "learning_events": [],
    "network": ["https://api.example.com"],
    "models": [],
    "storage": ["plugin-private"],
    "ui": ["sandboxed-iframe"]
  },
  "dependencies": ["requests>=2.32,<3"],
  "extensions": [
    {
      "type": "reading_extension",
      "id": "translation",
      "entry_point": "translation"
    },
    {
      "type": "visualizer",
      "id": "fraction_tiles",
      "manifest": "visualizers/fraction_tiles/visualizer.json"
    },
    {
      "type": "http_route",
      "id": "study_summary",
      "entry_point": "example_plugin.worker",
      "path": "/study/summary",
      "methods": ["GET", "POST"],
      "auth": "authenticated"
    }
  ]
}
```

The manifest parser rejects unknown fields. This is deliberate: the root file
is a public compatibility contract, and silently accepting misspelled fields
would make plugin behavior depend on the DeepTutor release.

### Extension types

| Type | Meaning | Current behavior |
| --- | --- | --- |
| `capability` | Turn-owning capability | Existing entry points load only after manifest approval; managed workers load through the JSON subprocess adapter |
| `loop_capability` | Chat-loop capability | Existing entry points load only after manifest approval |
| `tool` | Single-shot LLM tool | Existing entry points load only after manifest approval; managed workers load through the JSON subprocess adapter |
| `reading_extension` | Reading toolbar/action extension | Existing entry point remains authoritative and loads only after manifest approval |
| `visualizer` | Packaged visualizer asset bundle | Manifest declaration; bundle manifest is not eagerly read |
| `http_route` | Managed JSON HTTP endpoint | Approved managed routes execute in the plugin venv worker |
| `frontend_page` | Declared plugin page | Authenticated introspection only in this slice; page assets and mounting are future work |
| `persistence_schema` | Declared plugin data schema | Authenticated introspection only; migrations and data access are future work |
| `app_connector` | Declared downstream application adapter | Authenticated introspection only; adapter execution is future work |

Each extension has one stable `id`. Python-backed extensions declare
`entry_point`; visualizers declare their packaged bundle `manifest`. A root
manifest may contain multiple extensions, but it does not grant a universal
runtime API. Runtime code still binds each extension to its typed protocol.

`http_route` and `frontend_page` declare static paths beginning with `/`.
HTTP route methods are limited to `GET`, `POST`, `PUT`, `PATCH`, and `DELETE`;
authentication is exactly one of `public`, `authenticated`, or `admin`.
Persistence schemas declare a packaged JSON file and named operations. App
connectors declare named operations. Unknown fields remain invalid for every
extension type.

Built-in DeepTutor IDs always win. A plugin cannot replace a built-in
capability, tool, Reading action, or visualizer by reusing its ID.

`dependencies` is an explicit, ordered closure. Requirements must be PEP 508
name-and-version constraints; direct URLs, environment markers, extras, and
duplicate canonical names are rejected. Managed installation passes every
requirement plus the plugin wheel to the plugin-private interpreter with
`pip install --no-deps`, so pip cannot mutate the host environment or discover
a different transitive graph at install time.

## Registry states

`PluginRegistry` reads installed distribution files and the vendored catalog.
It never calls `entry_point.load()` and never imports third-party code.

| State | Meaning |
| --- | --- |
| `available` | Catalog entry is not installed |
| `approval-required` | Installed and compatible, but its exact permission snapshot has not been approved |
| `enabled` | Installed, compatible, and not locally disabled |
| `disabled` | Installed and locally disabled |
| `incompatible` | Installed, but its DeepTutor or API contract is not supported |
| `broken` | Manifest unreadable/invalid, duplicate ID, or cannot be represented |
| `deprecated` | Catalog or review metadata marks the plugin obsolete |

A malformed installed manifest affects only that plugin. A malformed catalog
row affects only that row. Existing entry-point loaders keep their containment
behavior.

Local enablement is persisted as:

```json
{
  "version": 2,
  "disabled": [],
  "plugins": {
    "org.author.example": {
      "manifest": {},
      "installation": null,
      "history": [],
      "approval": {
        "digest": "sha256-of-the-permission-snapshot",
        "approved_at": "2026-09-08T00:00:00Z"
      }
    }
  }
}
```

The file is written atomically under `data/user/settings/plugins.json`. The
legacy version 1 `{version, disabled}` shape is read as version 2 with no
plugin rows; the legacy file itself is not rewritten until another plugin state
operation commits.

`approval.digest` is a stable SHA-256 over the normalized manifest permission
object. A change to any scope or value invalidates approval and returns the
plugin to `approval-required`. Approval does not automatically enable a locally
disabled plugin.

## Official catalog

The official catalog is a vendored, manually reviewed JSON snapshot. Browsing
and version resolution do not make a live third-party registry request:

- schema `deeptutor.plugin-catalog/v2` has one row per immutable
  `(plugin ID, version)` pair; legacy v1 snapshots remain readable but cannot
  be remote-install sources;
- the package requirement is pinned;
- the distribution artifact has a direct immutable HTTPS wheel URL, SHA-256
  digest, exact byte size, and non-empty platform tags;
- compatibility and permissions are repeated from review-time metadata;
- status is `available`, `deprecated`, or `hidden`;
- malformed or duplicate rows are dropped without invalidating the catalog;
- `latest` resolves only the newest available non-prerelease version; exact
  versions must match the catalog string, deprecated versions require an
  explicit flag, and hidden rows are never returned.

The initial snapshot is intentionally empty. DeepTutor maintainers must not
invent third-party plugins to seed it. Real entries are added only with source
review, artifact pinning, and recorded reviewers.

## Catalog distribution

`deeptutor plugin install <plugin-id>` resolves a row in the vendored catalog,
downloads only that row's reviewed HTTPS URL, and then invokes the local
lifecycle with the catalog digest. Redirects are rejected, the download has a
timeout and bounded size, `Content-Length` must match the reviewed size, and
the streamed bytes must match both size and SHA-256 before installation. A
failed download removes its temporary wheel and never reaches pip or plugin
state. The URL is review metadata, not a CLI input: there is no arbitrary URL
install path and no automatic update check.

## Managed lifecycle

`PluginLifecycleManager` installs only an existing local wheel. That wheel can
come from the explicit local command or the verified catalog downloader. It
reads and validates the root manifest directly from the zip archive before
creating an environment or importing plugin code. An optional local `--sha256`
pin and the mandatory catalog pin are checked before install. The reviewed
artifact is copied under the plugin's managed root, and each plugin version
receives its own virtual environment.

Installation, upgrade, same-version reinstall, and rollback all clear the
previous approval. This is deliberate: the user approved an exact permission,
artifact, and manifest snapshot, not an implicit trust transfer to another
version. Failed dependency installation leaves the current version, approval,
and environment unchanged. A successful upgrade keeps the prior version
directory and environment for rollback; rollback moves the current version to
history and restores the prior environment. Uninstall removes the managed state,
artifacts, environments, and local enable/disable entry for that plugin.

Managed Tool and Capability extensions use a worker module entry point such as
`learning_echo.worker`. DeepTutor launches that module with the plugin venv
interpreter, exchanges one JSON request and response over stdin/stdout, and
rejects worker declarations whose permission snapshot exceeds the approved
manifest. Existing Python entry-point extensions continue to load classes or
factories in the host process, but only after the root-manifest gate accepts
them.

## Managed HTTP and introspection API

Managed HTTP routes are always dispatched under
`/api/plugins/{plugin-id}{path}`. They cannot override a built-in route and are
resolved from plugin state once at the start of each request. Only an approved,
compatible, enabled, managed installation with an installation record can
expose a route.
Unapproved, incompatible, broken, deprecated, disabled, external, and missing
routes all return the same HTTP 404 response.

The host performs route authentication before launching the worker. A public
route has no host credential dependency; `authenticated` uses the normal
session/bearer dependency; `admin` uses the host admin dependency. The worker
request contains only the declared method and path, normalized query values,
a JSON body no larger than 1 MiB, and the manifest's auth policy. Cookies,
bearer tokens, and raw host request headers are never forwarded.

Workers implement `handle_http` and return one JSON object containing a
response `status`, JSON `body`, and optional headers. Allowed statuses are the
normal application statuses the plugin can own (`200`, `201`, `202`, `204`,
`400`, `404`, `409`, `422`, and `500`); authentication and redirect statuses
belong to the host. `Cache-Control` is the only worker-provided response
header, with values limited to `no-store`, `no-cache`, or `max-age=<seconds>`.
The host always sets the JSON media type. Invalid worker output becomes a
generic HTTP 500 response and affects only that plugin request.

`GET /api/plugins/extensions` is authenticated and enumerates the extension
declarations of approved, enabled, managed installations. It is the discovery
surface for future frontend pages, persistence schemas, and app connectors;
those types are declaration-only in this slice.

## Trust and compatibility

The current trust model is human curation plus pinned metadata. Catalog
browsing and version resolution remain offline. Local installation accepts a
wheel and verifies an optional artifact digest before invoking pip; catalog
installation additionally binds the download URL, size, and digest to the
reviewed snapshot. Signing and a process/container security sandbox are
separate future phases and must not be implied by this catalog format.

Python permissions are disclosure and approval metadata in v1. Existing
entry-point extensions still execute in the host Python process after approval.
Managed worker extensions execute outside the host process but retain host
operating-system access. Reviewers and users need that fact to be visible; OS
scope enforcement belongs to a later isolation design.

Reading extensions continue to use the server-verified Reading context and
restricted result types. A plugin cannot widen its context by changing its
manifest declaration.

Visualizers that need untrusted HTML/UI execution use the existing sandboxed
iframe model. Their packaged asset manifests and renderer contracts remain
separate typed specs.

## Chrome compatibility

Direct Chrome extension reuse is out of scope. A future compatibility layer can
target a narrow subset, but it must translate a Chrome extension into a typed
DeepTutor extension declaration and a review record. It must not import Chrome
background/service-worker code into DeepTutor or hand browser-level authority
to a Python plugin. Marketplace distribution remains based on Python packages;
Chrome-specific assets may ship as resources inside such a package.

## Delivery phases

1. **Phase A - contract**: root manifest validation, RFC, catalog schema.
2. **Phase B - visibility**: metadata-only installed/catalog registry and CLI
   state/search/show/enable/disable commands.
3. **Phase C - runtime gating**: existing capability, loop, Reading, and tool
   loaders respect local enablement and manifest compatibility.
4. **Phase D - visualizer loading**: package visualizer manifests into the
   v1.6.2-style visualizer catalog while preserving built-in precedence.
5. **Phase E - installation**: pinned artifact download, digest verification,
   and an explicit user-approved installation flow.
6. **Phase F - sandbox/signing**: stronger isolation, signatures, and developer
   publishing workflow.

This repository currently implements Phases A through C, plus the local-wheel
and catalog-driven remote installation, approval, Tool/Capability/HTTP worker,
upgrade, rollback, uninstall, and managed introspection slice of Phase E.
Developer publishing automation, frontend asset mounting, persistence
migrations, app connector execution, visualizer packaging, signing, and a
stronger sandbox remain future phases.
