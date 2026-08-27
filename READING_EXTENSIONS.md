# Immersive Reading extensions

Immersive Reading discovers optional server-side packages through the
`deeptutor.reading_extensions` Python entry-point group. DeepTutor ships no
extensions in this group by default: when none are installed, the Reader does
not render an extension toolbar.

An entry point resolves to an object or class with a validated `manifest` and a
`run_action(action, context)` method. The current protocol version is `1`.

```toml
[project.entry-points."deeptutor.reading_extensions"]
example = "example_reading_plugin:ExampleExtension"
```

```python
from deeptutor.reading.extensions import (
    ReadingAction,
    ReadingExtensionManifest,
    ReadingExtensionResult,
)


class ExampleExtension:
    manifest = ReadingExtensionManifest(
        id="example",
        version="1.0.0",
        name="Example",
        actions=[ReadingAction(id="explain", label="Explain")],
        result_types=["card"],
    )

    def run_action(self, action, context):
        return ReadingExtensionResult(
            type="card",
            title="Example",
            payload={"body": context.visible_text[:500]},
        )
```

## Security boundary

- The global Reading API authentication policy protects extension routes.
- The server resolves the material, locator, saved source anchor, and stored
  unit text; the browser cannot replace them with arbitrary values.
- A selection is forwarded only when it occurs verbatim in the stored unit.
- Extensions return one of four validated result types: `card`, `quiz`,
  `feedback`, or `browser_speech`.
- Results have a 64 KB serialized ceiling. Quiz and speech payloads receive
  additional shape and length validation.
- Units larger than the protocol's 60,000-character context ceiling are
  rejected with a client error instead of invoking an extension.
- Actions have a 30-second execution timeout and return the standard
  recoverable unavailability response when exceeded. A synchronous Python
  handler already running in a thread cannot be killed safely, so each
  extension has one private worker and its circuit remains open after a timeout;
  later calls fail fast instead of consuming or queueing work on the process-wide
  thread pool. Restart DeepTutor after fixing or removing the stuck extension.
- Result data is rendered as React text. Extensions cannot send JavaScript or
  raw HTML to the Reader.
- Discovery and execution failures are isolated. A broken optional package
  cannot prevent documents or other extensions from opening.

Protocol changes must remain backward-compatible within version `1`. A future
incompatible contract must use a new protocol version rather than changing the
meaning of an existing field.
