# Immersive Reading extensions

Immersive Reading lazily registers its built-in read-aloud, study-guidance,
vocabulary, quiz, and explicit-target translation extensions even when Python
distribution metadata is unavailable. Additional server-side packages are
discovered through the `deeptutor.reading_extensions` Python entry-point group.
Built-in IDs are reserved; third-party packages cannot replace them.

The EPUB, PDF, and text readers keep authorized Read aloud, Look up word, and
Quiz me actions in a fixed toolbar. Other actions appear under More. Word lookup
requires selected source text and explains its meaning in context. A failed
catalog request offers Retry; a successfully loaded empty catalog (for example,
a learner with no allowed extensions) does not show actions. Account extension
allowlists still govern both discovery and execution. Explicitly constructing
`ReadingExtensionRegistry([])` continues to provide an empty registry for
embedding and tests.

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

## Independently installed reading bundle

The three core learning actions can be upgraded together with the
`deeptutor-reading-extensions` wheel, while each action retains its own ID
and learner permissions. Administrators can open **Settings → Reading
extensions** (`/settings#reading-extensions`) to download the latest GitHub
Release, upload a local wheel, toggle actions, uninstall, or restore the host's
bundled versions. The host integration must be deployed once before this page
and the CLI lifecycle commands are available.

```sh
deeptutor plugin reading list
deeptutor plugin reading install ./deeptutor_reading_extensions-0.1.0-py3-none-any.whl
deeptutor plugin reading update
deeptutor plugin reading disable vocabulary
deeptutor plugin reading enable vocabulary
deeptutor plugin reading uninstall
deeptutor plugin reading restore
```

Run these commands from the same runtime home as the backend, or set
`DEEPTUTOR_HOME` to that directory. Restart **all** backend workers after any
change. No frontend rebuild is needed for subsequent compatible plugin updates.

Managed wheels and their selected generation live under
`data/system/reading-plugins`. Keep this directory in the Docker data volume.
The installer does not modify Python site-packages, install dependencies, or
execute build hooks. It verifies package identity, the supported pure-Python
wheel layout, host/Python compatibility, and the exact extension entry points.
The fixed GitHub release download is verified against its asset SHA-256 digest.
Administrators should install only publishers they trust: these are Python
extensions with backend process permissions, not sandboxed browser components.

An installed managed bundle takes precedence over the three bundled actions.
An explicit uninstall disables those IDs after restart; it does not silently
reactivate the host versions. Restore explicitly selects the bundled versions.
Immutable older wheel files are retained so existing workers can finish; they
may be removed manually after every worker has restarted. Installation errors
leave the prior selection intact. A damaged selected wheel fails closed for
those three actions and logs the load error.

Standard pip installation of the same distribution is also supported when no
managed selection has been configured. Managed selection always wins, including
explicit uninstall and restore. Other third-party extensions cannot take over
these reserved IDs. Study guidance and translation remain bundled extensions.

### Independent providers and additional actions

Provider wheels can now be installed independently of the convenience bundle.
Each uses a unique `deeptutor-reading-*` package/namespace, a protocol-1
`reading_plugin.json`, and `deeptutor.reading_extensions` entry points. No
provider is selected automatically on installation. Administrators select one
provider per action in Settings → Reading extensions, or with
`deeptutor plugin reading provider vocabulary --package <installed-package>`.
Use `deeptutor plugin reading remove <package>` to uninstall only that provider.
Restart all backend workers to apply lifecycle changes.

Novel extension IDs are supported and appear under More when selected; existing
learner allowlists still authorize those IDs. Third-party upload supports the
same validated pure-Python wheel format; automatic downloads use the fixed
published catalog. The independent repository includes a small dictionary
example and a [provider contract and roadmap](https://github.com/evan188199-tech/deeptutor-reading-extensions/blob/main/docs/PLUGIN_DESIGN.md).
