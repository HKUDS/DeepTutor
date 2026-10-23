# Mastery memory: routed image-budget compatibility

## Intent and reuse

Derived from the integration feedback on #1910: keep the memory contribution
compatible with the native route-aware ContextBuilder without duplicating the
image projection or making this PR import an unavailable future helper.

The existing replay_history, project_mastery_replay, deduplicate_user_images
and token accounting functions remain the owners. Stored rows, actual replay,
archive IDs, score/state ownership and memory validation are unchanged.

## RED / GREEN checkpoints

- 62bae08a: new executed tests reproduce the missing optional route argument
  and final image count disagreeing with effective request projection.
  RED in the clean contribution and extended integration: 4 failed, 1 passed.
- 539bd80f: accept/forward optional route and count the final deduplicated
  Mastery view without changing model_history. GREEN: 20 focused tests in
  the clean contribution; the extended integration's memory scope passed 22.

The new regression file covers omitted/same/changed routes, route-specific
reasoning replay, non-mutation of records, and duplicate-image final accounting
without a new summary call or summary-watermark write.

## Scope and limits

No provider inference, live learner database mutation, migration or new
dependency. Budget figures are planning estimates, not billing or subscription
usage measurements. The broader memory contribution remains draft pending
representative teaching-preservation/model evaluation. Route compatibility
does not prove every semantic detail survives summarization.

#1910 owns the separate generic projected-image guard and optimized recent
history selection; this PR is not a competing implementation of those changes.
