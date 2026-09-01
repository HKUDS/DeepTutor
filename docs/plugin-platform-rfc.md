# DeepTutor Plugin Platform RFC (Phase A/B)

Status: accepted implementation slice
Schema: `deeptutor.plugin/v1`
Last reviewed: 2026-08-31

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
- No automatic `pip install` from the catalog. The catalog is metadata-only in
  this phase.
- No claim that Python permission fields create a hard sandbox. In v1 they are
  review and user-facing disclosure metadata. The only hard UI sandbox claim is
  the browser-enforced iframe boundary used by visualizers.
- No replacement of the existing `deeptutor.plugins` capability loader,
  `deeptutor.loop_capabilities`, or `deeptutor.reading_extensions` entry-point
  behavior.
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
    }
  ]
}
```

The manifest parser rejects unknown fields. This is deliberate: the root file
is a public compatibility contract, and silently accepting misspelled fields
would make plugin behavior depend on the DeepTutor release.

### Extension types

| Type | Meaning | Phase A/B behavior |
| --- | --- | --- |
| `capability` | Legacy turn-owning capability | Manifest declaration and compatibility state only |
| `loop_capability` | Chat-loop capability | Manifest declaration and compatibility state only |
| `tool` | Single-shot LLM tool | Manifest declaration and compatibility state only |
| `reading_extension` | Reading toolbar/action extension | Manifest declaration; existing entry point remains authoritative |
| `visualizer` | Packaged visualizer asset bundle | Manifest declaration; bundle manifest is not eagerly read |

Each extension has one stable `id`. Python-backed extensions declare
`entry_point`; visualizers declare their packaged bundle `manifest`. A root
manifest may contain multiple extensions, but it does not grant a universal
runtime API. Runtime code still binds each extension to its typed protocol.

Built-in DeepTutor IDs always win. A plugin cannot replace a built-in
capability, tool, Reading action, or visualizer by reusing its ID.

## Registry states

`PluginRegistry` reads installed distribution files and the vendored catalog.
It never calls `entry_point.load()` and never imports third-party code.

| State | Meaning |
| --- | --- |
| `available` | Catalog entry is not installed |
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
  "version": 1,
  "disabled": ["org.author.example"]
}
```

The file is written atomically under `data/user/settings/plugins.json`. The
current slice exposes state and review visibility; runtime registries continue
to use their existing loaders. Gating those loaders on this state is the next
integration step.

## Official catalog

The official catalog is a vendored, manually reviewed JSON snapshot. It is not
a live third-party registry request:

- entries are sorted by immutable plugin ID;
- the package requirement is pinned;
- the distribution artifact has a SHA-256 digest;
- compatibility and permissions are repeated from review-time metadata;
- status is `available`, `deprecated`, or `hidden`;
- malformed or duplicate rows are dropped without invalidating the catalog.

The initial snapshot is intentionally empty. DeepTutor maintainers must not
invent third-party plugins to seed it. Real entries are added only with source
review, artifact pinning, and recorded reviewers.

## Trust and compatibility

The v1 trust model is human curation plus pinned metadata. Catalog browsing is
offline. Installation, once added in a later phase, must resolve exactly the
pinned artifact and verify its digest before invoking pip. Signing and a
process/container sandbox are separate future phases and must not be implied by
this catalog format.

Python permissions are disclosure metadata in v1. A plugin that declares only
plugin-private storage still executes in the host Python process. Reviewers and
users need that fact to be visible; enforcement belongs to a later runtime
isolation design.

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

This repository currently implements Phases A and B.
