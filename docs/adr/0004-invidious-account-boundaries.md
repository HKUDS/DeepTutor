# ADR-0004: Separate Invidious Account Workflow, Storage, and Transport

## Status

Accepted

## Context

The Invidious account module initially combined three security-sensitive
responsibilities: authorization workflow decisions, owner-private filesystem
persistence, and upstream HTTP requests. The public surface was small, but a
change to token validation could accidentally affect atomic state claims or
transport behavior because all three concerns shared one implementation file.

Pending callbacks also have stricter storage requirements than ordinary
settings: state must not become a path segment, records must be private, and a
callback must be claimed exactly once across workers and process restarts.
Those invariants need an explicit owner independent of the web workflow.

## Decision

- `invidious_account.py` remains the application facade. It validates workflow
  input, chooses scopes, coordinates verification, and exposes the public API.
- `invidious_account_storage.py` owns filesystem layout, permissions, atomic
  JSON publication, expiration cleanup, and one-time pending-flow claims.
- `invidious_account_client.py` owns bearer serialization and all HTTP calls to
  the configured Invidious instance.
- Dependencies point inward from the facade to those two adapters. The storage
  adapter does not import HTTP or workflow services, and callers outside video
  learning continue to use only the facade.
- The persisted JSON shapes, callback lifetime, public functions, and
  user-facing errors remain unchanged.

## Consequences

### Positive

- Filesystem and cross-worker invariants can evolve without touching OAuth-like
  workflow or HTTP code.
- Transport tests patch the transport module directly, making network ownership
  visible.
- The facade is short enough to review as a state transition rather than as a
  mixture of storage and protocol mechanics.

### Negative

- Two private transport call seams remain in the facade so workflow tests can
  substitute upstream behavior without mocking filesystem persistence.
- The feature now spans three modules instead of one.

### Neutral

- This does not introduce a general credential-store abstraction; the unusual
  one-time claim semantics remain local to Invidious accounts.

## Alternatives Considered

- Keep the single module and group functions by comments: rejected because it
  preserves shared implementation ownership and hidden transport coupling.
- Introduce a repository-wide OAuth framework: rejected because Invidious uses
  a provider-specific signed-token callback and there is not yet a second flow
  with the same lifecycle.
- Move only HTTP calls: rejected because the more important concurrency and
  permission invariants would still be embedded in the workflow facade.
