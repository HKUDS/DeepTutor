# ADR-0001: Backend-Owned Browser Contracts

## Status

Accepted

## Context

The backend stabilization and frontend stabilization work were developed from
the same base commit in parallel. The backend introduced
`deeptutor.core.turn_request.TurnRequest`; the frontend branch independently
introduced a second `TurnRequest` plus WebSocket models under the API adapter.
The generated browser schema therefore described the frontend branch's copy of
the backend rather than the backend being integrated.

This allowed generated artifacts to pass drift checks while still containing
deleted chat routes and omitting new runtime and health routes.

## Decision

- Adapter-neutral request value objects live in `deeptutor.core`.
- `deeptutor.app.contracts` only re-exports those value objects.
- Wire-only WebSocket models live in `deeptutor.api.contracts`.
- OpenAPI and WebSocket JSON Schema are generated from the running FastAPI app
  and those canonical models after backend and frontend integration.
- Duplicate OpenAPI operation IDs are defects in router declarations. The
  exporter must report them and must not silently rename them.
- CI fails if generated JSON or TypeScript differs from canonical Python.

## Consequences

### Positive

- There is one owner for every cross-process field.
- Frontend compilation detects backend contract drift.
- Generated files can no longer hide invalid backend OpenAPI.

### Negative

- Backend route or model changes require contract regeneration.
- Wire evolution requires an explicit protocol decision.

### Neutral

- Frontend-only presentation metadata remains frontend-owned.

## Alternatives Considered

- Maintain equivalent TypeScript and Python models by hand: rejected because
  the parallel refactors already demonstrated silent drift.
- Own all contracts in `deeptutor.api`: rejected because CLI and Python SDK
  requests must not depend on the HTTP adapter.
