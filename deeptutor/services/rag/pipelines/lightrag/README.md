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
LightRAG base before querying; creation can also use explicit indexing selections.
New role configurations disable VLM by default. Inheriting the base for VLM
requires a model that supports image inputs. Disabling VLM preserves text,
table and equation processing. An explicit image-analysis request on a disabled
index fails with full-rebuild guidance.

Each enabled role can override supported reasoning effort. An unspecified value
inherits the selected model's saved default; `none` explicitly disables reasoning
where supported. Unsupported choices are rejected without substituting another
model or reasoning level. Concurrency and timeout limits apply per role to
subsequent tasks and do not require rebuilding. Accepted tasks keep their effective
models, reasoning and limits while queued and running.

## Creating, appending and rebuilding

Creation and full rebuild dialogs prefill EXTRACT and VLM from engine settings.
You may change both for that index. An empty, idle knowledge base also allows
editing its pending selection before first publication.

After publication, uploads and folder/GitHub sync use the index's pinned EXTRACT
and VLM identities. Changing engine defaults does not change an existing index.
Enabling, disabling or replacing VLM, or replacing EXTRACT or their reasoning
configuration, requires a full rebuild. If a valid VLM was pinned before the first
image, later image uploads can use it without another rebuild.

The index details show pending or published model provenance, effective vision
state and whether VLM was used. A failed or cancelled rebuild keeps the previous
published index. A queued operation whose target changed fails before writing;
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
