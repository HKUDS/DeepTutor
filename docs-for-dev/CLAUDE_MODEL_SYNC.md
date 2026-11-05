# Claude Code model discovery

The model Sync action for the Claude Code connected-agent backend can use the
official Python Agent SDK to obtain the CLI's current model catalog. Install
the optional dependency from a source checkout:

```bash
python scripts/install_extras.py claude-code
```

Use the existing Claude Code login and environment. Sync prefers the `claude`
executable on PATH, or the SDK's bundled CLI when none is installed. The SDK
initialization response supplies display names and resolved model IDs, which
are stored in the existing `claude_models_cache.json`. No inference request is
made, and account metadata from that response is not stored.

The recommended/default row is omitted because the UI already offers the CLI
default. Disabled entries and duplicate resolved IDs are skipped. Older CLIs
that omit resolved IDs retain their returned aliases; explicit `[1m]` variants
remain separate. Models are not limited to a hard-coded family list.

When the SDK is missing, times out, or returns no catalog, Sync falls back to
the existing POSIX terminal picker. If both discovery methods fail, the previous
cache remains untouched. Alias suggestions without a synced cache do not claim
specific version numbers. Listing a model does not verify account entitlement
or remaining quota; Sync does not test each model by sending a prompt.

The SDK session runs in a temporary folder, with project settings, native tools,
and implicit MCP configurations disabled. Authentication is managed by Claude
Code; this feature does not copy credentials or add a primary-model provider.
