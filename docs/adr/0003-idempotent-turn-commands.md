# ADR-0003: Explicit Acknowledgement for Idempotent Turn Commands

## Status

Accepted

## Context

The new runtime coordinator provides at-least-once command delivery and can
deduplicate a stable `command_id`. The new browser runtime queued commands over
reconnects, but did not send IDs and considered any later stream event an
acknowledgement. An unrelated replayed event could therefore discard an
unprocessed cancel or user reply, while reconnect could duplicate the command.

## Decision

- Every retryable mutation (`cancel_turn`, `submit_user_reply`, `user_input`)
  carries a client-generated stable `command_id`.
- The server emits a non-stream `command_ack` identifying that ID, command kind,
  acceptance, and any stable error code.
- The browser removes a queued mutation only after its matching acknowledgement.
- Stream sequence numbers acknowledge stream persistence only; they never
  acknowledge commands.
- All WebSocket commands and server frames require `protocol_version: "2.0"`.

## Consequences

### Positive

- Reconnect is safe under at-least-once delivery.
- UI state can distinguish command rejection from transport loss.
- Command and event ordering are no longer conflated.

### Negative

- The protocol gains another server frame type.
- Browser tests must retain commands until explicit acknowledgement.

### Neutral

- Starting or regenerating a turn remains reconciled through active-turn state;
  a future global command log may extend the same acknowledgement model.

## Alternatives Considered

- Treat the next event as an acknowledgement: rejected because event replay and
  command consumption are independent streams.
- Rely on WebSocket delivery: rejected because a successful `send()` does not
  prove application processing.
