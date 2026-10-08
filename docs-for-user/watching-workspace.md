# Video learning in Immersive Reading

Open **Reading** under Learning, add a YouTube or Bilibili URL to a collection, and study it beside the tutor. Videos use the same reading material, transcript, annotations and conversation stores as documents. The media stage supports transcript search and follow, timestamp citations, fullscreen viewing and the current/next caption lines. Missing captions or unsupported playback are shown explicitly; a tutor must not claim to have watched footage from transcript text alone.

New timestamped notes are Reading annotations. Their location is captured when the editor opens, so playback moving while you write does not move the note. Failed saves keep the draft for retry; an older save finishing does not erase newer text.

## Existing Watching conversations

Standalone Watching is retired. Existing `/watching/{sessionId}` and `/learning/watching/{sessionId}` links open a compatibility route that explicitly migrates the conversation into Reading. The conversation ID and messages stay the same. Legacy video JSON remains a provider/cache record; existing **Video Learning** notebook records remain readable and are not rewritten. Compatible transcripts, notes and saved positions are copied into Reading idempotently, and an existing Reading position wins over an older imported position.

Session listing and inspection do not create materials. Migration happens when the learner opens the legacy conversation or continues a legacy turn. If the legacy video cache is missing, its conversation remains available as ordinary chat with the unavailable-video state recorded; another video is never silently substituted. Other migration failures preserve the original preferences and offer retry.

## Configure Invidious

In administrator settings, open video-learning settings, enter the instance's backend API origin and public origin, test the connection, and select Invidious as the default provider. Reading's YouTube-caption loader uses that configured provider. Bilibili remains independent. An unavailable caption service does not make a natively playable video unusable, but the missing transcript is visible and the tutor's evidence remains limited.

`invidious.api_base_url` must be reachable by the backend; `invidious.public_base_url` must be reachable by the browser. Private HTTP origins can use loopback, LAN or overlay addresses under the existing configured-instance policy. Public instances require HTTPS. Keep settings in `video_learning.json`; project `.env` files are ignored.

Use **Browse Invidious** in the add-material dialog to search or select from an account's subscriptions and playlists. Account tokens remain owner-private. Older tokens without `GET:feed`, `GET:playlists` and `GET:playlists/*` require reconnection; no subscription or playlist mutations are requested. DeepTutor never asks for the Invidious password. Authorization occurs on the configured instance, and callback feedback returns to Reading without placing a token in the redirect target. Disconnect failure preserves the token for retry.

## Verification and recovery

Check playback, seeking, transcript search/follow, timestamp citations, and note save/edit/retry. Reopen a migrated conversation and confirm that its message history and source identity remain unchanged. Also check missing captions, an unavailable provider, narrow screens and owner access boundaries. Preserve the existing data directory and owner identity during deployment or rollback; do not overwrite newer user data with a backup merely to undo a frontend change.
