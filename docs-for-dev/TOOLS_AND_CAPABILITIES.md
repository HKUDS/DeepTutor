# Tools and capabilities

[Handbook](README.md) · [Architecture](ARCHITECTURE.md) · [Modules](MODULES.md) · [Plugins](PLUGINS.md)

## The two contracts

[`BaseTool`, `ToolDefinition`, and `ToolResult`](../deeptutor/core/tool_protocol.py)
describe one operation selected by a model. A tool validates arguments,
performs the operation and returns content plus structured metadata/error
state. Availability is not equivalent to permission to access every resource.

[`TurnCapability` and `CapabilityManifest`](../deeptutor/core/capability_protocol.py)
describe a pipeline that owns a turn. A capability consumes `UnifiedContext`
and emits stream events. Capabilities converge on
[`emit_capability_result()`](../deeptutor/agents/_shared/capability_result.py) for the
response payload and `cost_summary`; do not invent another completion envelope.

The built-in catalog is derived from
[`modules/manifests/`](../deeptutor/modules/manifests/) by
[`builtin_capabilities.py`](../deeptutor/runtime/bootstrap/builtin_capabilities.py).
Use `deeptutor module list`, `deeptutor plugin list` and `deeptutor plugin info`
to inspect the current installation rather than assuming every source feature
is available in a core-only wheel environment.

## Mounting rules

The eight user-toggleable tools are `brainstorm`, `web_search`, `paper_search`,
`zotero_search`, `reason`, `geogebra_analysis`, `imagegen` and `videogen`.
`USER_TOGGLEABLE_TOOL_NAMES` in
[`tools/builtin/__init__.py`](../deeptutor/tools/builtin/__init__.py) is the
authoritative list; CLI `--tool` selects from it.

`CONFIGURABLE_BUILTIN_TOOL_NAMES` declares context-gated tools, including
research, retrieval, memory, notebook, execution and deferred tool discovery.
[`tool_composition.py`](../deeptutor/agents/_shared/tool_composition.py) owns
mount flags and always-available workspace tools. Capability-owned solve,
mastery and other specialized tools follow their activation contracts.
The Partner allow/deny surface can further narrow access.

Account grants, workspace resource policies, module selection and capability
activation must all remain effective at discovery and dispatch. A tool name
in a UI or a manifest must not bypass those checks. MCP/CLI deferred discovery
must use the existing loader rather than installing a parallel registry.

## Add or change a built-in

1. Implement the typed operation or capability in its owning module. Keep
   optional libraries out of metadata-only imports.
2. Update the tool spec or capability declaration, aliases and the owning
   module manifest. The lazy tool descriptors live in
   [`builtin_specs.py`](../deeptutor/tools/builtin_specs.py).
3. Put mounting logic in the existing composition/activation owner. Decide
   explicitly whether a tool is user-toggleable, context-gated or
   capability-owned.
4. Update request validation and translated prompts where needed. Capability
   prompts live under [`capabilities/prompts/`](../deeptutor/capabilities/prompts/);
   some agent implementations own additional prompts in their own directory.
5. Test metadata/implementation parity, missing-module behavior, authorized
   resource scope, failure and cancellation, and the public result envelope.
   Follow [Testing](TESTING.md) for schema regeneration and broader checks.

For an independently distributed package, use the [plugin contract](PLUGINS.md)
and [Learning Echo example](examples/learning_echo/README.md) instead of
modifying built-in registration. Reading toolbar actions have a separate
[Reading extension protocol](READING_EXTENSIONS.md).

## Diagnose an unexpected tool call

Compare the active module state, capability, selected resources, user tool
selection and workspace policies with the actual schemas admitted to the
model request. Then inspect dispatch and the returned evidence. A selected KB
does not prove retrieval ran; a retrieved URL does not prove pixels reached
the model. See [source visuals](SOURCE_VISUALS.md) and
[answer-quality diagnosis](REASONING_SAFETY_CHECKLIST.md).
