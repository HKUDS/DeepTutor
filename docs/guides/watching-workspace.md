# Immersive Watching workspace

Open **Immersive Watching** in the sidebar, or visit `/watching`. Paste a YouTube URL and open the video. The first question creates a conversation at `/watching/{sessionId}`. Desktop shows video beside the conversation; smaller screens have Video and Conversation buttons that preserve the mounted player.

The workspace reuses the chat runtime and the existing timed-media APIs. Session preferences store `workspace_mode: "immersive_watching"` and `timed_media_id`; material access is checked against the current user's store. Existing Watching conversations recover their material from their latest recorded turn when the preference is absent. Browser-global recent-video storage is no longer a source of session identity. A new draft starts empty; send a question to save it as a conversation.

## Configure Invidious

In administrator settings, open the video-learning section, enter the existing instance's backend API origin and public origin, test the connection, and select Invidious as the default provider. Settings are persisted by the application's administrator path service as `video_learning.json`; do not put them in the project `.env` or hard-code them in frontend code.

- `invidious.api_base_url`: an origin reachable by the DeepTutor backend. Loopback is suitable only when the backend and instance share a host network. Containers must use an appropriate service or host address.
- `invidious.public_base_url`: the same instance's origin reachable by the user's browser/device.
- `default_provider`: `invidious` or `youtube`.

DeepTutor continues to proxy media through its authenticated video-learning endpoints. Do not replace the player with an Invidious iframe or relax the stream proxy's allowed-origin checks. Invidious failure remains visible; switching to native YouTube requires the user's explicit action.

## Verify and troubleshoot

1. Open a captioned video and check actual playback and seeking, not just the instance status endpoint. Media requests should support byte ranges (`206` where applicable).
2. Click a caption, use Explain here, follow an answer's timestamp, and save/reopen a timestamped note.
3. Refresh the conversation URL, visit another conversation, and return. Confirm both the material and saved progress; ordinary Chat and Reading must retain their own context.
4. Repeat with a narrow viewport, missing captions, an unavailable instance, and a user who cannot access the material.

If metadata works but playback fails, inspect the authenticated stream response and the configured instance's media/companion service. If captions are unavailable, use Retry captions; do not silently substitute a different provider. A missing or unauthorized saved video leaves an error and an empty video surface rather than another conversation's video.

## Deployment and rollback

Before deployment, record the running commit, save the tracked working-tree diff, and back up the video settings and service launch configuration. Build a separate release directory containing the existing deployment changes plus the reviewed Watching patch. Keep the existing data directory and owner identity; do not copy user data into Git.

Run frontend type, contract, lint, translation and build checks, the Watching browser tests, and `pytest tests/video_learning`. Switch service paths only after the release is ready. Check `/watching`, `/reading`, `/chat` and real Invidious playback. On failure, restore the previous service paths and video settings, restart the old release, and verify readiness. Leave the previous working tree and its uncommitted changes intact.
