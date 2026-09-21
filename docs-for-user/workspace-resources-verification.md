# Workspace resource assignment verification

Verified locally on 2026-09-19 against the current working tree.

## Compatibility

- Missing resource policies keep the previous workspace access rules; no existing indexes, credentials or learning records are moved.
- Null means inherited access; an empty list explicitly disables that resource type.
- MCP selections narrow account grants at discovery, schema loading, cached schema recovery and dispatch.
- Skill manifests and reads share one resolver, including local overrides and always-loaded bodies.
- Knowledge references identify both catalog origin and name; selections cannot grant another account's private resources.
- Referenced knowledge catalogs cannot be moved through aggregate data migration until their assignments are removed. Moving a workspace folder preserves its identity.

## Passed checks

- Related knowledge, skills and provider regression run: 153 tests.
- Workspace, permissions and provider boundary regression run: 143 tests.
- Final focused policy, MCP and read-skill run: 25 tests. Counts overlap.
- Frontend workspace settings, resource picker, knowledge creation, Co-Writer and scope regression: 24 tests across six files.
- TypeScript typecheck; lint on the affected surfaces; backend Ruff; API contract export/generation check; locale key parity; production build.
- Browser verification in an isolated runtime: existing inherited workspace, creation of a selected workspace, persisted skills/MCP/KB assignments, account resource library and workspace-specific skill creation, verified absent from the account-shared catalog. Existing user data and the running user instance were not used for QA.

## Broader working-tree test result

The full Node frontend test suite reported 1,150 passed and 34 failed. This is **not** a claim of a clean repository-wide baseline. The working tree contains other ongoing changes; several failures assert older URLs without the current `dt_workspace` query parameter, while others concern unrelated update/trace/settings contracts. The failures are preserved here rather than counted as passing resource-assignment validation.

- app update client uses the canonical system routes
- sidebar presents the update state as a clickable status dot
- reasoning produced after a card becomes its own segment below it
- a turn with no tool work is a single run of prose
- an app id with URL-significant characters is escaped in the path
- ordinary users send a scoped Codex reasoning effort update
- global surfaces are handed the course so they can scope themselves
- course organization patch sends only the requested metadata
- GraphRAG candidate probe sends catalog IDs without activating the model
- listImaKnowledgeBases sends credentials and preserves pagination
- IMA credential rejection stays inline instead of redirecting login
- connectImaKnowledgeBase sends the DeepTutor name and invalidates on success
- create and re-index send the exact pinned selection and preserve none
- pending-policy update is JSON-only and creates no indexing request
- model controls are scoped to built-in LightRAG create/rebuild surfaces
- a timed-out model catalog request can be retried
- every device-bridge call names its library through X-MN4-KB
- a device id is escaped into the revoke path
- a hand-written disabled_tools blocklist survives GET → edit → PUT
- the request path comes from the caller's surface, not a hardcoded base
- the per-user surface reads its own route and keeps the additive fields
- toggling one server writes only that server
- a rename adds the new server before removing the old one
- a refused rename never reaches the delete
- a name with URL-significant characters is escaped in the path
- removing the last server still refreshes from the response
- a no-op write re-reads instead of PUTting anything
- the admin registry keeps its whole-map PUT
- onboarding client sends the partner-scoped lifecycle requests
- channel runtime client reads the partner-scoped status endpoint
- settings-context: persistUiSettingsPatch sends only the changed code-block field
- settings-context: persistUiSettingsPatch can save theme without sending code-block fields
- Next's checked-in environment declaration uses the canonical dev cache
- Watching links retain their owning workspace, including legacy sessions
