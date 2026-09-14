# LightRAG role models

In Knowledge Center, open the native LightRAG engine and choose a base model.
The saved base is independent of the chat model and the embedding model.
Shared engine settings require administrator access when authentication is enabled.

| Role | Used for | Available sources |
| --- | --- | --- |
| EXTRACT | Entity/relation extraction, structured tables and equations | Base or explicit model |
| KEYWORD | Query keyword extraction | Base or explicit model |
| QUERY | Answer generation | Base or explicit model |
| VLM | Requested image analysis | Disabled, base or explicit vision model |

Fresh settings are distinguished from historical settings. Choose and save a
LightRAG base in Settings before querying or creating a knowledge base.
New role configurations disable VLM by default. Inheriting the base for VLM
requires a model that supports image inputs. Disabling VLM preserves text,
table and equation processing. An explicit image-analysis request on a disabled
index fails with full-rebuild guidance.

Each enabled role can override supported reasoning effort. `Auto` leaves reasoning
controls to the provider; `none` explicitly disables reasoning where supported.
An inherited role follows the base reasoning unless it has its own override.
Restoring an older pinned index retains its recorded reasoning semantics.
Unsupported choices are rejected without substituting another model or reasoning
level. Concurrency and timeout limits apply per role to
subsequent tasks and do not require rebuilding. Accepted tasks keep their effective
models, reasoning and limits while queued and running.

DeepTutor forwards LightRAG structured-output requests, including the JSON
object contracts used by EXTRACT, KEYWORD and VLM, through its provider
capability filter. Provider reasoning is controlled by the saved role effort.
DeepTutor intentionally omits provider reasoning traces from the returned answer
even when LightRAG requests its COT output format.

## Creating, appending and rebuilding

Configure models in Settings. Creation and full rebuild do not offer per-index
model overrides. An idle, unpublished empty knowledge base follows current valid
defaults until its first accepted indexing task freezes the configuration.

Before rebuilding, review the current default embedding model/dimension and
EXTRACT/VLM models and reasoning. If defaults change before submission, review
and confirm the refreshed configuration. Accepted tasks retain the same embedding
and role settings through execution and version publication. Failed-task retry
actions also use this confirmation flow.

After publication, uploads and folder/GitHub sync use the index's pinned EXTRACT
and VLM identities. Changing engine defaults does not change an existing index.
Enabling, disabling or replacing VLM, or replacing EXTRACT or their reasoning
configuration, requires a full rebuild. If a valid VLM was pinned before the first
image, later image uploads can use it without another rebuild.

Index versions show their version identifier, state, timestamp and actual embedding,
EXTRACT and VLM configuration. The display distinguishes provider-default reasoning,
explicit `none` and disabled VLM. Returning from Settings refreshes default-role
summaries. Unavailable pinned indexing models require restoring access or rebuilding
with new defaults, but do not unconditionally block existing text retrieval.
A failed or cancelled rebuild keeps the previous published index. A queued
operation whose target changed fails before writing;
resubmit it against the current index. Concurrent writers for one knowledge base
are rejected, so wait for the active operation to finish before resubmitting.

## Existing settings and indexes

Legacy engine settings are prefilled from an accessible existing selection.
Saving detaches the LightRAG base from chat. Missing or inaccessible selections
must be replaced explicitly.

Verifiable legacy single-model indexes retain their original model fingerprint
and recorded vision state without a format-only rebuild. Unknown historical
identity remains queryable but blocks incremental writes until a full rebuild.
Malformed policies and models that have been deleted, changed identity or lost
access cannot silently acquire current defaults. Credential rotation alone does
not change the pinned identity; credentials are resolved privately for execution
and are excluded from persisted index policy and public provenance.
