# Watching learning mode

Watching's **Fullscreen learning** button expands the existing workspace without replacing its player or chat runtime. Desktop defaults to a 60/40 split; drag the divider or use its arrow keys. Conversation and video notes share the right panel. Mobile provides video, transcript, conversation and notes controls. **System fullscreen** is optional and requires a user gesture; unsupported browsers retain the webpage layout.

## Caption semantics

- **CC · Has captions** is provider metadata, not proof of a successful download.
- **Captions ready · language** comes from the current user's saved, nonempty transcript. Account linking does not download subtitles.
- Source VTT inline timestamps are retained as optional `words` in each transcript cue. Plain `start`, `end` and `text` remain compatible with existing sessions; `lines` retains source line breaks.
- Missing or invalid word timings use sentence-level captions. No synthetic alignment or translation is performed. Full transcript search remains available below the compact two-line display.
- Existing caches are not bulk-refreshed. Retry captions to obtain enhanced data from the configured provider.

The authenticated `POST /api/video-learning/captions/status` endpoint accepts `video_ids` (at most 48 valid YouTube IDs), reads only the current user's timed-media store, and returns a mapping of saved ready captions with their language. It never contacts Invidious. Public list browsing retains optional `hasCaptions`; caption-filtered searches use the provider's existing `features:subtitles` query operator.

## Validation and rollout

Use both a word-timed VTT fixture and an actual configured-instance video. Check seeking, playback speed, pause, fullscreen exit, mobile panel switching, unsaved notes, refresh, and cross-user caption isolation. A successful caption-list response is not a successful playback or word-timing test.

Before deployment, save the active commit, tracked and untracked changes, service launch configuration and runtime video settings. Build and test in a separate release directory, retaining the existing data root. Switch the service only after those checks pass. Validate real video playback plus Watching, Reading and ordinary chat. On failure restore the previous launch configuration and settings, restart, and verify the previous release. Record the deployed commit and source-timing limitations in the contribution.

See [Watching workspace deployment](watching-workspace.md) for the underlying workspace configuration. No instance addresses belong in product source.
