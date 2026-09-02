# ADR-0002: Unversioned Canonical URLs Without Compatibility Aliases

## Status

Accepted

## Context

DeepTutor is shipped as one repository whose browser and backend are upgraded
together. Existing routes mix `/api/v1`, `/api/outputs`, singular and plural
resources, RPC verbs, `/home`, query-string session routing, and duplicate
Settings pages. The product does not promise that an old third-party client
can use a newly upgraded server.

## Decision

- The supported REST namespace is `/api/...`; URL paths do not carry a product
  or contract version.
- The primary turn WebSocket is `/ws`.
- Downloadable artifacts use `/files/...`.
- Canonical page routes use product nouns, including `/chat/{sessionId}` and
  fragment-addressed sections under `/settings`.
- REST compatibility aliases, page redirects, and query-string session-routing
  fallbacks are removed in the breaking release rather than retained
  indefinitely. Query parameters may still express one-shot launch intent,
  such as a capability or course, but never session identity.
- Contract version belongs in OpenAPI `info.version`; WebSocket compatibility
  belongs in the required `protocol_version` envelope; persisted data retains
  its own `schema_version`.

## Consequences

### Positive

- One route exists for each supported action or resource.
- Product version labels no longer leak into transport topology.
- Dead aliases can be guarded by repository-wide tests.

### Negative

- Bookmarks and external scripts using old URLs break at the release boundary.
- The frontend, backend, docs, tests, and generated schemas must migrate in one
  atomic release.

### Neutral

- Future public API versioning would require a new ADR and an explicit support
  window, not merely adding `/v2` to paths.

## Alternatives Considered

- Keep `/api/v1`: rejected because this release makes breaking changes while
  offering no v1/v2 coexistence policy.
- Introduce `/api/v2`: rejected because it would be a label without parallel
  lifecycle governance.
- Permanent redirects and aliases: rejected because the stated goal is to
  remove obsolete compatibility logic.
